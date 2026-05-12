# Cluster Q&A — Operational Knowledge Log

Concise answers to questions that came up during cluster operation. Each entry captures the *why* so it's useful months later.

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

**Why cp-03 accumulates more than the other nodes:** The scheduler preferentially places workloads on cp-03 (AMD, 32c, 92 GB) due to resource fit. More pods means more `ContainerStatusUnknown` events after a crash.

---

## GitOps / Flux

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

## Upgrades (tuppr + Renovate)

### Does Renovate create incremental PRs for each Talos/Kubernetes minor version, or one PR jumping to the latest?

**Short answer:** One PR to the latest — `separateMinorPatch: true` separates minor PRs from patch PRs, but within the minor category it still jumps to the newest available version.

**Detail:** With the current config, if the cluster is on `v1.10.6` and both `v1.11.x` and `v1.12.x` are released, Renovate opens a single minor PR targeting `v1.12.x` — not two separate PRs stepping through `v1.11` first. Both Talos and Kubernetes require sequential minor upgrades (you cannot skip `v1.11` entirely), so merging such a PR and letting tuppr act on it would fail.

**Is this a real risk?** For a weekly Renovate schedule and a cluster that is kept reasonably current, in practice no. Talos releases minor versions roughly every 2–3 months; running weekly means you are almost never more than one minor behind when Renovate opens the PR.

**What to do when a minor-bump PR arrives:**
1. Open the PR and check the version jump in `talosupgrade.yaml` (and `talenv.yaml`).
2. If it skips a minor (e.g. `v1.10.x → v1.12.y`), edit the PR to target only the next minor (`v1.11.latest`) and merge that first.
3. After tuppr finishes the rolling upgrade, Renovate will re-open with the next step.

Patch PRs (e.g. `v1.10.6 → v1.10.9`) are always safe to merge directly — Talos supports arbitrary patch skips within a minor.
