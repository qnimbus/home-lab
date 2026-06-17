# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-06-17** · Auditor: Claude Code (`gitops-repo-audit` skill) — post Rook-Ceph migration + GitHub App auth cutover; I2/I6/W2 resolved (see below)

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

#### ⚠️ WARNING — 13 generated values ConfigMaps lack the reactivity label

Every chart using the `configMapGenerator` (+ `disableNameSuffixHash: true` for 3 of them) pattern for Helm values is missing `reconcile.fluxcd.io/watch: Enabled`. This is the root cause of the known gotcha in `feedback_flux_configmap_hash.md`: editing `values.yaml` doesn't trigger immediate reconciliation, requiring a manual `flux reconcile helmrelease <name> --force`.

**Recommendation**: add a `labels:` block (or `generatorOptions.labels`) with `reconcile.fluxcd.io/watch: "Enabled"` to each of the 13 `kustomization.yaml` files using `configMapGenerator` for chart values. Turns the documented manual workaround into automatic behavior.

#### ⚠️ WARNING — Flux alerts wired, but Alertmanager has no outbound receiver

**Still open.** `kubernetes/apps/flux-system/flux-alerts/` deploys a Flux-native `Provider` (`type: alertmanager`) + `Alert` (`eventSeverity: error`) forwarding reconciliation errors into Alertmanager. But `kube-prometheus-stack`'s `alertmanagerSpec` has no `config:`/receiver/route — Alertmanager runs the chart's default config, whose route terminates in the `null` receiver. Flux errors reach Alertmanager's state but never page a human. Tracked in [ROADMAP.md → Alertmanager Receiver](ROADMAP.md#alertmanager-receiver).

#### ✅ RESOLVED — FluxInstance sync now uses GitHub App authentication

Was tracked as I2 (SSH deploy key). `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` now sets `sync.provider: github` with an HTTPS URL and `pullSecret: flux-github-app`, backed by an `ExternalSecret` populating `githubAppID`/`githubAppInstallationID`/`githubAppPrivateKey`. The corresponding `docs/ROADMAP.md` entry was stale (described this as pending) and has been marked done.

#### ✅ RESOLVED — kustomize-controller / Flux pod concentration

Was tracked as I6 (recommended `podAntiAffinity`). Implemented instead via `topologySpreadConstraints` (`maxSkew: 1`, `ScheduleAnyway`) + `replicas: 2` on helm-controller/kustomize-controller/notification-controller, scoped via a shared `app.kubernetes.io/part-of: flux` label. The soft constraint was a deliberate choice over `DoNotSchedule` — it keeps controllers running through the ~80-minute single-node reboot window of a Talos/K8s upgrade instead of leaving them Pending.

#### ✅ RESOLVED — Drift detection now cluster-wide default

`driftDetection.mode: enabled` is in the global `cluster-apps` patch. All 27 HelmReleases have drift detection enabled (4 redundantly redeclare it locally — cosmetic only, see I-new below).

#### ℹ️ INFO — FluxInstance `cluster.size` not set

`spec.cluster` is still `{}`. Without `cluster.size`, controllers run on default resource limits. **Recommendation**: set `cluster.size: medium` — appropriate for ~27 HelmReleases / ~41 Kustomizations.

#### ℹ️ INFO — 5 HelmReleases set redundant `createNamespace: true`

`openebs`, `kube-prometheus-stack`, `actions-runner-controller`, `envoy-gateway`, `tuppr`. All five already have a `namespace.yaml` ordered before `helmrelease.yaml` in the same Kustomization, so this is a harmless no-op — drop it for consistency with the other 22 HelmReleases.

#### ℹ️ INFO — 4 HelmReleases redundantly redeclare `driftDetection: mode: enabled`

`external-secrets`, `envoy-gateway`, `cilium`, `cert-manager` — the global `cluster-apps` patch already sets this for every HelmRelease (and patches are the last writer regardless). Cosmetic cleanup only.

#### ✅ RESOLVED — `retryInterval` now a cluster-wide default

`retryInterval: 2m` is set via the global `cluster-apps` patch + top-level Kustomizations. (Was I3.)

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
| W3 | 13 `configMapGenerator`-based values ConfigMaps lack `reconcile.fluxcd.io/watch: Enabled` | Add the label via `generatorOptions.labels` or per-generator `labels:` in each of the 13 `kustomization.yaml` files |
| ~~W2~~ | ~~Drift detection on 5/20 HelmReleases only~~ | ✅ Resolved — global patch in `cluster-apps` now injects `driftDetection: enabled` for all 27 HelmReleases |

### Info

| # | Finding | Action |
|---|---|---|
| I1 | FluxInstance `cluster.size` unset (`cluster: {}`) — now 27 HR / 41 KS | Set `cluster.size: medium` in `flux-instance` values |
| ~~I2~~ | ~~FluxInstance sync: SSH deploy key~~ | ✅ Resolved — GitHub App auth live (`provider: github`, `flux-github-app` secret); ROADMAP.md entry marked done |
| ~~I3~~ | ~~No `retryInterval` on HelmReleases~~ | ✅ Resolved — `retryInterval: 2m` in the global `cluster-apps` patch + top-level Kustomizations |
| I4 | 13 OCIRepositories without cosign (2 new: `rook-ceph`, `rook-ceph-cluster`) | Audit each upstream for cosign availability; add verification where supported |
| I5 | Validation CI picks up non-K8s YAMLs (`Taskfile.yaml`, `bootstrap/helmfile.d/*`) | Add `-e talos -e assets -e bootstrap` to validate invocation; `Taskfile.yaml` at root is an unavoidable false positive |
| ~~I6~~ | ~~kustomize-controller co-location~~ | ✅ Resolved — `topologySpreadConstraints` + 2 replicas on helm/kustomize/notification-controller |
| I7 | 5 HelmReleases set redundant `createNamespace: true` despite an explicit `namespace.yaml` in the same Kustomization | Drop the field for consistency (harmless no-op otherwise) |
| I8 | 4 HelmReleases redundantly redeclare `driftDetection: mode: enabled` (already a global default) | Drop the local declaration; cosmetic only |

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
