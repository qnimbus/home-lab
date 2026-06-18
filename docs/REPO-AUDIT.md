# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-06-17** · Auditor: Claude Code (`gitops-repo-audit` skill) — post Rook-Ceph migration + GitHub App auth cutover. Follow-up fix pass same cycle: W3, I1, I5, I7, I8, I9 resolved; only W1 (Alertmanager receiver) and I4 (cosign coverage) remain open

## Contents <!-- omit from toc -->

- [Summary](#summary)
- [Resource Inventory](#resource-inventory)
- [Validation Results](#validation-results)
- [API Compliance](#api-compliance)
- [Best Practices](#best-practices)
- [Security Posture](#security-posture)
- [Recommendations](#recommendations)
- [How to Re-Audit](#how-to-re-audit)

---

## Summary

| Property | Value |
|---|---|
| Cluster | home-lab (bare-metal Talos Linux, single-tenant) |
| Pattern | Monorepo · Flux Operator (`FluxInstance`) |
| Flux version | 2.8.8 (managed by flux-operator) |
| Overall status | **Healthy** — no deprecated APIs, no plaintext secrets, clean manifest validation, zero `dependsOn` cycles |

---

## Resource Inventory

| Kind | Count | Δ since 2026-06-05 |
|---|---|---|
| HelmRelease | 27 | +1 |
| Kustomization | 41 | +1 |
| OCIRepository | 19 | +2 (rook-ceph, rook-ceph-cluster) |
| HelmRepository | 4 | -1 |
| Receiver | 1 | — |
| Alert | 1 | — |
| Provider | 1 | — |
| ImageUpdateAutomation | 0 | — |

**Namespaces (app-declared via `namespace.yaml`)**: actions-runner-system, automation, database, external-secrets, network, observability, openebs, reloader, rook-ceph, system-upgrade, tailscale. **Bootstrap-managed** (created by the Helmfile bootstrap phase before Flux takes over, not by a GitOps `namespace.yaml`): kube-system, cert-manager, flux-system.

**Applications**: cilium · coredns · cert-manager · external-secrets · onepassword-connect · openebs · rook-ceph (operator + cluster) · envoy-gateway · cloudflared · external-dns (cloudflare + unifi) · tailscale-operator · actions-runner-controller · kube-prometheus-stack · smartctl-exporter · spegel · metrics-server · reloader · tuppr · cloudnative-pg (+ pgadmin + postgres-backup-local) · waha · external-services (truenas + wan-failover) · flux-operator · flux-instance · flux-receiver · flux-alerts

> Longhorn is fully gone (superseded by Rook-Ceph, big-bang migration). `rook-ceph` (`ceph-block`) is now the default StorageClass with all 5 stateful consumers migrated.

---

## Validation Results

### Kubernetes Manifests — PASS

All Flux CRDs and Kustomize overlays under `kubernetes/` validate cleanly against the Flux OpenAPI schemas.

```
kubeconform: 0 errors
kustomize build: 0 errors
```

### Non-Kubernetes Files — Expected False Positives

The validate script also scans root-level YAML and `talos/` patches, producing 16 "missing `kind` key" errors (was 15 — the CRD-prebootstrap split added a second Helmfile file). These are **not Kubernetes resources** and should be excluded in CI:

| File | Reason |
|---|---|
| `Taskfile.yaml` | go-task task runner, not Kubernetes |
| `bootstrap/helmfile.d/00-crds.yaml`, `01-apps.yaml` | Helmfile bootstrap (CRD pre-bootstrap phase), not Kubernetes |
| `talos/talconfig.yaml`, `talenv.yaml`, `talsecret.sops.yaml`, `schematic.yaml` | Talos machine config |
| `talos/patches/**/*.yaml` (9 files) | Talos strategic-merge patches |

**CI fix**: add `-e talos -e assets -e bootstrap` to the validate invocation. See [How to Re-Audit](#how-to-re-audit).

---

## API Compliance

```
flux migrate -f . --dry-run → no custom resources found that require migration
```

All Flux resources use current stable API versions. No migration required.

---

## Best Practices

### What's Working Well

| Practice | Status |
|---|---|
| All Kustomizations have `prune: true` | ✅ |
| `cluster-settings` ConfigMap + `cluster-secrets` Secret carry `reconcile.fluxcd.io/watch: Enabled` | ✅ |
| All OCI-sourced HelmReleases use `chartRef` (modern pattern); the 4 remaining `HelmRepository`+`chart.spec` HelmReleases (cilium, external-secrets, onepassword-connect, metrics-server) are pinned to upstreams with no official OCI artifact | ✅ |
| No legacy `install.remediation.retries`-only pattern — global `cluster-apps` patch injects `strategy.name: RetryOnFailure` + remediation defaults for every HelmRelease | ✅ |
| Zero `dependsOn` cycles or dangling references across all 41 Kustomizations (verified programmatically) | ✅ |
| Multi-document `ks.yaml` for operator + CRD-instance Kustomizations (operator dry-run isolation) | ✅ |
| Renovate tracks all pinned versions via `# renovate: datasource=...` annotations; all OCIRepository refs use immutable exact tags | ✅ |
| Receiver deployed for webhook-triggered immediate reconciliation on Git push | ✅ |
| kube-prometheus-stack deployed for Flux controller monitoring | ✅ |
| SOPS + ESO two-tier secrets — Talos secrets encrypted at rest, app secrets never in Git | ✅ |
| Flux controllers (helm/kustomize/notification) run 2 replicas + `topologySpreadConstraints` (`ScheduleAnyway`) — survive single-node reboots during Talos/K8s upgrades | ✅ |

### Gaps

#### ✅ RESOLVED — 13 generated values ConfigMaps now carry the reactivity label

Was W3. Added `generatorOptions: { labels: { reconcile.fluxcd.io/watch: "Enabled" } }` to all 13 `kustomization.yaml` files using `configMapGenerator` for chart values (merged into the existing `generatorOptions` block for `cloudflared`, which also sets `disableNameSuffixHash`). Verified via `kustomize build` that the label renders on the generated ConfigMap. This closes the gap behind the known `feedback_flux_configmap_hash.md` gotcha — `values.yaml` edits now trigger immediate reconciliation instead of requiring `flux reconcile helmrelease --force`.

#### ⚠️ WARNING — Flux alerts wired, but Alertmanager has no outbound receiver

**Still open.** `kubernetes/apps/flux-system/flux-alerts/` deploys a Flux-native `Provider` (`type: alertmanager`) + `Alert` (`eventSeverity: error`) forwarding reconciliation errors into Alertmanager. But `kube-prometheus-stack`'s `alertmanagerSpec` has no `config:`/receiver/route — Alertmanager runs the chart's default config, whose route terminates in the `null` receiver. Flux errors reach Alertmanager's state but never page a human. Tracked in [ROADMAP.md → Alertmanager Receiver](ROADMAP.md#alertmanager-receiver).

#### ✅ RESOLVED — FluxInstance sync now uses GitHub App authentication

Was tracked as I2 (SSH deploy key). `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` now sets `sync.provider: github` with an HTTPS URL and `pullSecret: flux-github-app`, backed by an `ExternalSecret` populating `githubAppID`/`githubAppInstallationID`/`githubAppPrivateKey`. The corresponding `docs/ROADMAP.md` entry was stale (described this as pending) and has been marked done.

#### ✅ RESOLVED — kustomize-controller / Flux pod concentration

Was tracked as I6 (recommended `podAntiAffinity`). Implemented instead via `topologySpreadConstraints` (`maxSkew: 1`, `ScheduleAnyway`) + `replicas: 2` on helm-controller/kustomize-controller/notification-controller, scoped via a shared `app.kubernetes.io/part-of: flux` label. The soft constraint was a deliberate choice over `DoNotSchedule` — it keeps controllers running through the ~80-minute single-node reboot window of a Talos/K8s upgrade instead of leaving them Pending.

#### ✅ RESOLVED — Drift detection now cluster-wide default

`driftDetection.mode: enabled` is in the global `cluster-apps` patch. All 27 HelmReleases have drift detection enabled.

#### ✅ RESOLVED — FluxInstance `cluster.size` now set to `medium`

Was I1. `spec.cluster.size: medium` set in `flux-instance` values — appropriate for ~27 HelmReleases / ~41 Kustomizations (upstream guidance reserves `large` for fleets approaching a thousand apps).

#### ✅ RESOLVED — Redundant `createNamespace: true` removed from 5 HelmReleases

Was I7. Removed the now-empty `install:` block from `openebs`, `kube-prometheus-stack`, `actions-runner-controller`, `envoy-gateway`, `tuppr` — all five already have a `namespace.yaml` ordered before `helmrelease.yaml` in the same Kustomization, so the flag was a no-op. Verified all 5 still build cleanly via `kustomize build`.

#### ✅ RESOLVED — Redundant `driftDetection: mode: enabled` removed from 4 HelmReleases

Was I8. Removed the local `driftDetection` block from `external-secrets`, `envoy-gateway`, `cilium`, `cert-manager` — the global `cluster-apps` patch already sets this for every HelmRelease. Verified via `kustomize build` that drift detection still applies (injected by the global patch).

#### ✅ RESOLVED — `retryInterval` now a cluster-wide default

`retryInterval: 2m` is set via the global `cluster-apps` patch + top-level Kustomizations. (Was I3.)

#### ✅ RESOLVED — `kustomize-controller` concurrency no longer relies on patch-ordering

Was I9 (found during a follow-up discussion, not the original audit pass). `flux-instance`'s `values.yaml` had two separate `kustomize.patches` entries both appending a `--concurrent=N` arg to `kustomize-controller` — `--concurrent=10` (via the shared 3-controller patch) followed by `--concurrent=20` (via a kustomize-controller-only patch). Both ended up in the rendered args list; the last one parsed wins, so the *effective* value was already 20, but only by virtue of list order, not because anything declared 20 explicitly. Restructured so the shared patch targets `(helm-controller|source-controller)` only, and the dedicated `kustomize-controller` patch carries `--concurrent=20` + `--requeue-dependency=5s` + the tmpfs volume swap together — same effective runtime behavior, no more silent override.

---

## Security Posture

### Secrets

| Check | Status |
|---|---|
| No plaintext Secrets in Git | ✅ |
| No unencrypted `secretGenerator` literals in kustomization.yaml files | ✅ — none found at all |
| No hardcoded credentials in HelmRelease `.spec.values` or Kustomization substitutions | ✅ |
| SOPS encryption on `talsecret.sops.yaml` and `cluster-secrets.sops.yaml` | ✅ |
| External Secrets Operator + 1Password Connect for all application secrets | ✅ |

### Sources

| Check | Status |
|---|---|
| No `insecure: true` on any source | ✅ |
| No cloud-registry sources requiring Workload Identity | ✅ — all OCI sources are public GHCR/registries |
| Sync source uses GitHub App auth (short-lived tokens) | ✅ — resolved, was SSH deploy key |
| GitHub webhook Receiver secured with `secretRef` | ✅ |

### OCI Supply Chain (Cosign Verification)

19 OCIRepositories in use. 6 have `spec.verify.provider: cosign`:

| OCIRepository | Cosign |
|---|---|
| flux-operator | ✅ |
| flux-instance | ✅ |
| app-template (bjw-s) | ✅ |
| tailscale-operator | ✅ |
| external-dns | ✅ |
| openebs | ✅ |
| cert-manager | ❌ |
| cloudnative-pg | ❌ |
| coredns | ❌ |
| envoy-gateway | ❌ |
| gha-runner-scale-set-controller | ❌ |
| gha-runner-scale-set | ❌ |
| kube-prometheus-stack | ❌ |
| reloader | ❌ |
| **rook-ceph** | ❌ (new) |
| **rook-ceph-cluster** | ❌ (new) |
| smartctl-exporter | ❌ |
| spegel | ❌ |
| tuppr | ❌ |

13 repositories remain unverified, including the two new Rook-Ceph sources added during the storage migration. Should be assessed individually — some upstreams (e.g. cert-manager) publish cosign signatures; others may not.

### Network & RBAC

| Check | Status |
|---|---|
| FluxInstance network policies enabled (default `true`) | ✅ |
| Single-tenant cluster — cross-namespace source refs are expected pattern | ✅ |
| No cluster-admin bindings for application workloads | ✅ |
| No multi-tenant admission policies needed (single tenant) | ✅ N/A |

---

## Recommendations

### Critical

_None._

### Warning

| # | Finding | Action |
|---|---|---|
| W1 | Flux `Alert`/`Provider` forward errors into Alertmanager, but Alertmanager has **no outbound receiver** (default `null` route) | Add an Alertmanager `config:` with a Slack/Discord/email/PagerDuty receiver + `route` (tracked in ROADMAP → Alertmanager Receiver) |
| ~~W2~~ | ~~Drift detection on 5/20 HelmReleases only~~ | ✅ Resolved — global patch in `cluster-apps` now injects `driftDetection: enabled` for all 27 HelmReleases |
| ~~W3~~ | ~~13 `configMapGenerator`-based values ConfigMaps lack `reconcile.fluxcd.io/watch: Enabled`~~ | ✅ Resolved — `generatorOptions.labels` added to all 13 `kustomization.yaml` files |

### Info

| # | Finding | Action |
|---|---|---|
| ~~I1~~ | ~~FluxInstance `cluster.size` unset (`cluster: {}`)~~ | ✅ Resolved — set to `medium` |
| ~~I2~~ | ~~FluxInstance sync: SSH deploy key~~ | ✅ Resolved — GitHub App auth live (`provider: github`, `flux-github-app` secret); ROADMAP.md entry marked done |
| ~~I3~~ | ~~No `retryInterval` on HelmReleases~~ | ✅ Resolved — `retryInterval: 2m` in the global `cluster-apps` patch + top-level Kustomizations |
| I4 | 13 OCIRepositories without cosign (2 new: `rook-ceph`, `rook-ceph-cluster`) | Audit each upstream for cosign availability; add verification where supported |
| ~~I5~~ | ~~Validation CI picks up non-K8s YAMLs~~ | ✅ Resolved — turned out CI/Task already scope `validate.sh` to `-d kubernetes`, never touching `Taskfile.yaml`/`talos/`; removed the dead `-e kubernetes/bootstrap` exclude (bootstrap moved to repo-root `bootstrap/` some time ago, so the flag pointed at a non-existent path) |
| ~~I6~~ | ~~kustomize-controller co-location~~ | ✅ Resolved — `topologySpreadConstraints` + 2 replicas on helm/kustomize/notification-controller |
| ~~I7~~ | ~~5 HelmReleases set redundant `createNamespace: true`~~ | ✅ Resolved — removed the now-empty `install:` block from all 5 |
| ~~I8~~ | ~~4 HelmReleases redundantly redeclare `driftDetection: mode: enabled`~~ | ✅ Resolved — removed the local declaration from all 4 |
| ~~I9~~ | ~~`kustomize-controller` `--concurrent` set via two colliding patches (10, then 20) — last one silently won~~ | ✅ Resolved — consolidated into one explicit patch; `(helm-controller\|source-controller)` keep `--concurrent=10` |

---

## How to Re-Audit

Run these commands from the repo root to refresh findings:

```bash
# 1. Resource inventory
bash .claude/skills/gitops-repo-audit/scripts/discover.sh -d .

# 2. Manifest validation (with non-K8s exclusions)
bash .claude/skills/gitops-repo-audit/scripts/validate.sh -d . \
  -e talos -e assets -e .archive -e bootstrap

# 3. Deprecated API check
bash .claude/skills/gitops-repo-audit/scripts/check-deprecated.sh -d .

# 4. Security spot-checks
# Unencrypted secrets (false positives expected for cert refs):
grep -rl "kind: Secret" kubernetes/ --include="*.yaml" | \
  xargs -I{} sh -c 'grep -q "sops:\|ENC\[" "$1" || echo "CHECK: $1"' _ {}

# OCIRepositories missing cosign:
for f in kubernetes/flux/meta/repos/oci/*.yaml; do
  grep -q "provider: cosign" "$f" || echo "NO-VERIFY: $(basename $f .yaml)"
done

# HelmReleases missing drift detection:
find kubernetes/ -name "helmrelease.yaml" | \
  xargs -l sh -c 'grep -q "driftDetection" "$1" || echo "NO-DRIFT: $1"'

# Generated values ConfigMaps missing the reactivity watch label:
for f in $(grep -rl "configMapGenerator" kubernetes/apps --include="kustomization.yaml"); do
  grep -q "reconcile.fluxcd.io/watch" "$f" || echo "NO-WATCH-LABEL: $f"
done

# dependsOn cycle / dangling-reference check (requires PyYAML):
python3 - <<'PYEOF'
import glob, yaml
files = glob.glob("kubernetes/apps/**/ks.yaml", recursive=True) + glob.glob("kubernetes/flux/**/ks.yaml", recursive=True)
edges = {}
for f in files:
    for d in yaml.safe_load_all(open(f)):
        if not d or d.get("kind") != "Kustomization": continue
        ns = d.get("metadata",{}).get("namespace","flux-system")
        key = f"{ns}/{d['metadata']['name']}"
        edges[key] = [f"{x.get('namespace',ns)}/{x['name']}" for x in d.get("spec",{}).get("dependsOn",[]) or []]
visited = {}
def visit(n, stack):
    if n in stack: print("CYCLE:", " -> ".join(stack+[n])); return
    if visited.get(n): return
    visited[n] = True
    for d in edges.get(n, []): visit(d, stack+[n])
for n in edges: visit(n, [])
for n, deps in edges.items():
    for d in deps:
        if d not in edges: print(f"DANGLING: {n} -> {d}")
print(f"Total Kustomizations checked: {len(edges)}")
PYEOF
```

After re-running, update the **Last audited** date at the top and revise findings as needed. Close resolved items by moving them to a _Resolved_ table or deleting them.
