# Cluster Q&A — Operational Knowledge Log

Concise answers to questions that came up during cluster operation. Each entry captures the *why* so it's useful months later.

---

## Table of Contents

**Networking**
- [Why does cp-03 show many `eth0: renamed from tmp<random>` messages?](#why-does-the-talos-console-for-cp-03-show-many-eth0-renamed-from-tmprandom-kernel-messages)

**Cluster Recovery / Unclean Shutdown**
- [After a simultaneous power-off, the dashboard shows ~90 failed pods — but the cluster looks healthy. What happened?](#after-a-simultaneous-power-off-of-all-nodes-the-dashboard-shows-90-failed-pods-and-a-failed-deployment--but-the-cluster-looks-healthy-what-happened)

**GitOps / Flux**
- [When deploying a chart that installs CRDs, why must the CRD instances live in a separate Kustomization?](#when-deploying-a-chart-that-installs-crds-why-must-the-crd-instances-live-in-a-separate-kustomization)
- [Why add `crds: CreateReplace` to operator HelmReleases?](#why-add-crds-createreplace-to-operator-helmreleases)
- [Why does `charts/tuppr` not support cosign, when `charts-mirror/openebs` does?](#why-does-ghcriohome-operationschartstuppr-not-support-cosign-verification-when-ghcriohome-operationscharts-mirroropenebs-does)
- [Why does `valuesFrom` require both a `configMapGenerator` and a `kustomizeconfig.yaml`?](#why-does-every-app-that-uses-valuesfrom-need-both-a-configmapgenerator-and-a-kustomizeconfigyaml)

**Kubernetes Workloads**
- [A healthy Deployment shows both `Available` and `Progressing` — is something wrong?](#a-healthy-deployment-shows-both-available-and-progressing--is-something-wrong)

**Upgrades (tuppr + Renovate)**
- [Does Renovate create incremental PRs per minor version, or one PR to the latest?](#does-renovate-create-incremental-prs-for-each-talosk8s-minor-version-or-one-pr-jumping-to-the-latest)

---

## Networking

### Why does the Talos console for cp-03 show many `eth0: renamed from tmp<random>` kernel messages?

**Short answer:** Normal CNI activity — not errors.

**Detail:** Each message represents Cilium creating a veth pair for a newly scheduled pod. The kernel assigns a temporary name (`tmp<hex>`) to the host-side interface; the CNI then renames the pod-side end to `eth0` inside the pod's network namespace. The kernel logs that rename at the host level, which is why it surfaces in the Talos console.

Bursts of these messages (e.g. many within a second) indicate pods being created or rescheduled in rapid succession — common after a DaemonSet rollout, Longhorn stabilising after initial deployment, or a deployment restart. cp-03 (32c, 92 GB) attracts the most pods due to scheduler resource-fit, so it generates these more frequently than the M920Q nodes.

**Actionable only if:** the same burst pattern repeats continuously over minutes, which would suggest a pod CrashLoopBackOff cycling through restarts. In that case, check `kubectl get pods -A | grep -v Running`.

---

## Cluster Recovery / Unclean Shutdown

### After a simultaneous power-off of all nodes, the dashboard shows ~90 failed pods and a failed Deployment — but the cluster looks healthy. What happened?

**Short answer:** Ghost pods from an unclean shutdown. The cluster is fine; the pod objects need manual deletion.

**Detail:** When all nodes lose power simultaneously, kubelets never get a chance to write terminal status for their running containers. On restart, the kubelet can no longer find those containers and reports their status as `ContainerStatusUnknown`, which transitions the pod to `Failed` phase. Kubernetes does **not** automatically garbage-collect `Failed` pods (only `Succeeded` ones are eligible for GC by default).

Meanwhile the Deployment controller sees the failed pods and creates replacements — potentially dozens of times before one stabilises. The result is a large number of stale `Failed` pod objects in etcd that have no containers behind them, but are never cleaned up automatically.

In this cluster the pattern after a full 3-node shutdown was:
- ~91 `cilium-operator` pods in `kube-system`, all `ContainerStatusUnknown`, all on `talos-cp-03`
- `cilium-operator` Deployment showing `1/1` (healthy) despite the pod count
- Dashboard reporting "Failed: 1" for Deployment and ReplicaSet — it counts pod failures, not desired/ready state
- `openebs` Flux Kustomization throwing transient health-check timeouts during boot sequencing (self-resolved)

**How to confirm this is the issue (not a real failure):**

```bash
# Are all failed pods for the same workload and ContainerStatusUnknown?
kubectl get pods -A --field-selector=status.phase=Failed

# Is the Deployment itself healthy?
kubectl get deployment -n kube-system cilium-operator
# Expect: READY 1/1

# Are there NodeShutdown events matching the outage timestamp?
kubectl get events -n kube-system --field-selector=reason=NodeShutdown
```

**Fix — delete the stale pods (safe, no config change needed):**

```bash
# Generalised: delete all Failed pods in a namespace for a specific workload
kubectl delete pods -n kube-system \
  -l app.kubernetes.io/name=cilium-operator \
  --field-selector=status.phase=Failed
```

If the outage affected multiple workloads across namespaces, run a broader sweep:

```bash
kubectl delete pods -A --field-selector=status.phase=Failed
```

This is safe as long as the owning Deployments/DaemonSets show healthy desired/ready counts beforehand. The controllers will not create new replacements because they already have the desired number of running pods.

**Safer alternative — script that verifies owner health first:**

`scripts/purge-failed-pods.sh` (also exposed as `task purge-failed-pods`) walks the full ownership chain (Pod → ReplicaSet → Deployment) and checks controller health before deleting anything. It skips pods whose owner is not confirmed healthy, and skips unrecognised owner kinds (e.g. Jobs) entirely.

```bash
task purge-failed-pods              # dry-run: prints what would be deleted, no changes made
task purge-failed-pods DELETE=true  # live: deletes only pods with a confirmed-healthy owner
```

Health criteria used by the script:
- **Deployment** — `Available` condition is `True`
- **DaemonSet** — `numberReady == desiredNumberScheduled`
- **StatefulSet** — `readyReplicas == replicas`

Use this instead of the broad `kubectl delete pods -A` sweep when you want an automated check rather than a manual pre-flight.

**Why cp-03 accumulates more than the other nodes:** The scheduler preferentially places workloads on cp-03 (AMD, 32c, 92 GB) due to resource fit. More pods means more `ContainerStatusUnknown` events after a crash.

---

## GitOps / Flux

### When deploying a chart that installs CRDs, why must the CRD instances live in a separate Kustomization?

**Short answer:** Flux dry-runs every resource in a Kustomization before applying any of them. If the Kustomization contains both the HelmRelease (which installs the CRDs) and instances of those CRDs, the dry-run fails — the API types don't exist yet at validation time.

**Detail:** Before applying a Kustomization, the Flux kustomize-controller performs a server-side dry-run of every resource it is about to create or update. This validates that the API server knows about the resource types. When a HelmRelease and its CRD instances are in the same Kustomization, the dry-run order is non-deterministic — the HelmRelease itself is just a CR telling the helm-controller to do work later; it does not install the CRDs synchronously during the dry-run. So Flux tries to validate `TalosUpgrade` against the API, gets `no matches for kind "TalosUpgrade"`, and the whole Kustomization fails before anything is applied.

**The fix — split into two Kustomizations (both in one multi-document `ks.yaml`):**

```yaml
# Document 1 — operator
kind: Kustomization
metadata:
  name: my-operator
spec:
  path: ./app          # contains HelmRelease only
  healthChecks:
    - kind: HelmRelease
      name: my-operator
      namespace: my-ns

# Document 2 — CRD instances
kind: Kustomization
metadata:
  name: my-operator-config
spec:
  path: ./config       # contains CRD instances
  dependsOn:
    - name: my-operator
```

`dependsOn` tells Flux not to attempt the second Kustomization until the first is Ready. `ks.yaml` is only marked Ready once its `healthChecks` (the HelmRelease) pass — meaning the chart is fully installed and the CRDs exist in the API. By the time `ks-upgrade.yaml` runs its dry-run, the types are registered.

**Important subtlety — `wait: false` vs `healthChecks`:** Setting `wait: false` on a Kustomization skips waiting for resources that have no explicit health check. But if you define `healthChecks` explicitly, Flux always evaluates those regardless of `wait`. So `ks.yaml` with `wait: false` + a HelmRelease `healthCheck` still correctly gates `ks-upgrade.yaml`.

**This pattern applies to any chart that installs CRDs you want to use in Git** — cert-manager (Certificate, ClusterIssuer), external-secrets (ExternalSecret, SecretStore), Longhorn (custom node configs), etc. The pattern is: operator Kustomization → `dependsOn` → CRD-instance Kustomization.

---

### Why add `crds: CreateReplace` to operator HelmReleases?

**Short answer:** By default, Helm never updates CRDs on `helm upgrade` — only on `helm install`. Without `CreateReplace`, a chart upgrade that ships a new CRD schema silently leaves the old schema in the cluster.

**Detail:** Helm's conservative default exists because CRD schema changes can be destructive — a `replace` deletes and recreates the CRD object, which briefly interrupts controllers watching that resource. Rather than risk accidental breakage, Helm chose to do nothing on upgrade. The consequence is that if an operator chart ships a new field in a CRD (e.g. a new `spec.policy.rebootMode` on `TalosUpgrade`), upgrading the HelmRelease installs the new controller binary but leaves the old CRD schema in place. Resources using the new field are silently ignored or rejected.

`CreateReplace` opts in to CRD updates on both install and upgrade:

```yaml
install:
  crds: CreateReplace
upgrade:
  crds: CreateReplace
```

This should be set on any HelmRelease for a chart that owns CRDs — operators, admission controllers, storage drivers, etc. It is safe for home-lab use where the tradeoff (brief CRD replacement vs. stale schema) clearly favours keeping schemas current.

**Note:** `CreateReplace` is a Flux helm-controller option, not a native Helm flag. The equivalent in raw Helm is `--skip-crds=false` combined with manual CRD management, which is why the Flux field exists as a convenience.

---

### Why does `ghcr.io/home-operations/charts/tuppr` not support cosign verification, when `ghcr.io/home-operations/charts-mirror/openebs` does?

**Short answer:** They are two different registry paths with different release pipelines. `charts-mirror` is a community-signed mirror of third-party charts; `charts` is the home-operations org's own first-party charts and does not go through the same signing pipeline.

**Detail:** The home-operations community maintains two distinct OCI chart registries under `ghcr.io/home-operations/`:

- **`charts-mirror/`** — mirrors of popular third-party charts (openebs, etc.) that the community re-signs with cosign keyless signing as part of their automated mirror pipeline. These can use `verify: provider: cosign`.

- **`charts/`** — first-party charts for community-authored tools (tuppr, etc.). As of May 2026, these are pushed without cosign signatures, so `verify: provider: cosign` causes an immediate `VerificationError`.

Using `verify: cosign` on an unsigned chart produces a failure that is *not retried until the next interval* (1h by default). Because the OCIRepository is a health-checked dependency of `cluster-meta`, this failure cascades: `cluster-meta` gets stuck running health checks for the bad revision, and `cluster-apps` (which `dependsOn: cluster-meta`) never unblocks. Removing the bad resource spec mid-health-check requires patching the live resource directly and force-reconciling the source — a Flux reconcile alone is not enough because the kustomization is frozen mid-health-check.

**Rule of thumb:** only add `verify: provider: cosign` when you have confirmed the upstream registry signs its releases. For home-operations charts, check the release workflow in the source repo, or look for `*.sig` artifacts alongside the chart tag in GHCR.

---

### Why does every app that uses `valuesFrom` need both a `configMapGenerator` and a `kustomizeconfig.yaml`?

**Short answer:** Kustomize mangles ConfigMap names by appending a content hash. The `kustomizeconfig.yaml` tells it to apply the same rename to the HelmRelease's `valuesFrom` reference — otherwise Flux tries to mount a ConfigMap that doesn't exist.

**Detail:** When Kustomize sees a `configMapGenerator` block, it creates the ConfigMap but renames it from (e.g.) `tuppr-values` to `tuppr-values-6bk9f2t`. The hash is derived from the file contents, so it changes whenever `helm/values.yaml` changes — giving Flux a reliable trigger to re-apply the HelmRelease with the new values.

The problem is that the HelmRelease manifest has a static reference:

```yaml
valuesFrom:
  - kind: ConfigMap
    name: tuppr-values        # ← Kustomize doesn't know to rewrite this by default
```

Without `kustomizeconfig.yaml`, Kustomize rewrites the ConfigMap's own name but leaves the HelmRelease reference pointing at the old bare name. Flux then tries to load `tuppr-values` (no hash), finds nothing, and the HelmRelease fails.

The `kustomizeconfig.yaml` in `app/helm/` registers an additional field spec that tells Kustomize: "also rewrite `spec/valuesFrom/name` inside any `HelmRelease` resource when it matches a generated ConfigMap name." After that, both the ConfigMap and the reference in the HelmRelease carry the same hash, and Flux resolves them correctly.

```yaml
# helm/kustomizeconfig.yaml
nameReference:
  - kind: ConfigMap
    version: v1
    fieldSpecs:
      - path: spec/valuesFrom/name
        kind: HelmRelease
```

**Why bother with the hash at all?** It makes values changes self-propagating in GitOps — Kustomize produces a new ConfigMap name, Flux detects the HelmRelease spec changed, and triggers a Helm upgrade automatically. Without the hash, editing `values.yaml` and pushing would *not* trigger a reconcile because the HelmRelease manifest itself wouldn't change.

---

## Kubernetes Workloads

### A healthy Deployment shows both `Available` and `Progressing` — is something wrong?

**Short answer:** No. `Progressing=True` is the permanent **success** state after a rollout completes. It does not mean the rollout is still running.

**Detail:** Kubernetes Deployments carry three conditions:

| Condition | Meaning |
|-----------|---------|
| `Available` | The deployment has at least the desired number of ready pods right now |
| `Progressing` | The last rollout completed successfully (`NewReplicaSetAvailable`) — or is actively rolling out |
| `ReplicaFailure` | Pods could not be created (e.g. image pull error, resource quota) |

The counter-intuitive part: Kubernetes sets `Progressing=True` when a rollout completes and **never clears it**. A fully healthy, idle deployment that rolled out days ago will still show `Progressing=True`. UIs (Lens, k9s) often render this condition alongside `Available`, making it look alarming.

**The only bad `Progressing` state** is `Progressing=False` with reason `ProgressDeadlineExceeded` — meaning a rollout *started* but stalled before completing within `spec.progressDeadlineSeconds` (default 600 s). That is the signal to investigate.

**How to check from the CLI:**

```bash
# Quick sanity check — look for Progressing=False or ReplicaFailure=True
kubectl describe deployment <name> -n <ns> | grep -A3 "Conditions:"

# All conditions at once
kubectl get deployment <name> -n <ns> -o jsonpath='{.status.conditions[*]}'
```

**Common trigger in this cluster:** Running `task reconcile` or pushing a commit causes Flux to reconcile and possibly issue a Helm upgrade. This creates a new ReplicaSet (visible in the Deployment's "Deploy Revisions" in Lens), the old one scales to 0, and `Progressing` reflects the completed rollout. The old ReplicaSet lingers at 0 replicas (Kubernetes keeps a history for rollback); that is also normal.

---

## Upgrades (tuppr + Renovate)

### Does Renovate create incremental PRs for each Talos/K8s minor version, or one PR jumping to the latest?

**Short answer:** One PR to the latest — `separateMinorPatch: true` separates minor PRs from patch PRs, but within the minor category it still jumps to the newest available version.

**Detail:** With the current config, if the cluster is on `v1.10.6` and both `v1.11.x` and `v1.12.x` are released, Renovate opens a single minor PR targeting `v1.12.x` — not two separate PRs stepping through `v1.11` first. Both Talos and Kubernetes require sequential minor upgrades (you cannot skip `v1.11` entirely), so merging such a PR and letting tuppr act on it would fail.

**Is this a real risk?** For a weekly Renovate schedule and a cluster that is kept reasonably current, in practice no. Talos releases minor versions roughly every 2–3 months; running weekly means you are almost never more than one minor behind when Renovate opens the PR.

**What to do when a minor-bump PR arrives:**
1. Open the PR and check the version jump in `talosupgrade.yaml` (and `talenv.yaml`).
2. If it skips a minor (e.g. `v1.10.x → v1.12.y`), edit the PR to target only the next minor (`v1.11.latest`) and merge that first.
3. After tuppr finishes the rolling upgrade, Renovate will re-open with the next step.

Patch PRs (e.g. `v1.10.6 → v1.10.9`) are always safe to merge directly — Talos supports arbitrary patch skips within a minor.
