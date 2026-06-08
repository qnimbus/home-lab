# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-06-05** · Auditor: Claude Code (`gitops-repo-audit` skill) — post storage-VLAN rollback; I3 resolved, W1 partially resolved (see below)

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
| Cluster | home-lab (3-node bare-metal Talos Linux, single-tenant) |
| Pattern | Monorepo · Flux Operator (`FluxInstance`) |
| Flux version | 2.6.4 (managed by flux-operator) |
| Overall status | **Healthy** — no deprecated APIs, no plaintext secrets, clean manifest validation |

---

## Resource Inventory

| Kind | Count |
|---|---|
| HelmRelease | 26 |
| Kustomization | 40 |
| OCIRepository | 17 |
| HelmRepository | 5 |
| Receiver | 1 |
| Alert | 1 |
| Provider | 1 |
| ImageUpdateAutomation | 0 |

**Namespaces**: actions-runner-system, automation, cert-manager, database, external-secrets, flux-system, kube-system, longhorn-system, network, observability, openebs, system, system-upgrade, tailscale

**Applications**: cilium · coredns · cert-manager · external-secrets · onepassword-connect · longhorn · openebs · envoy-gateway · cloudflared · external-dns (cloudflare + unifi) · tailscale-operator · actions-runner-controller · kube-prometheus-stack · smartctl-exporter · spegel · metrics-server · reloader · tuppr · cloudnative-pg (+ pgadmin + postgres-backup-local) · waha · external-services (truenas + wan-failover) · flux-operator · flux-instance · flux-receiver · flux-alerts

> **Removed in the 2026-06-05 storage-VLAN rollback** (commit `299904e`): the Multus stack (`kube-system/multus/`), the whereabouts OCI chart source + HelmRelease (incl. the PR #703 backport), and the Longhorn `longhorn-storage` NAD + its `longhorn-nad` Kustomization. Longhorn-on-storage-VLAN was abandoned after 5 attempts; the cluster is pivoting to Rook-Ceph. See [SESSIONS.md → `longhorn-storagevlan-rollback`](SESSIONS.md) and `docs/history/longhorn-storage-network.md`.

---

## Validation Results

### Kubernetes Manifests — PASS

All Flux CRDs and Kustomize overlays under `kubernetes/` validate cleanly against the Flux OpenAPI schemas.

```
kubeconform: 0 errors
kustomize build: 0 errors
```

### Non-Kubernetes Files — Expected False Positives

The validate script also scans root-level YAML and `talos/` patches, producing 15 "missing `kind` key" errors. These are **not Kubernetes resources** and should be excluded in CI:

| File | Reason |
|---|---|
| `Taskfile.yaml` | go-task task runner, not Kubernetes |
| `kubernetes/bootstrap/helmfile.yaml` | Helmfile bootstrap, not Kubernetes |
| `talos/talconfig.yaml`, `talenv.yaml`, `talsecret.sops.yaml` | Talos machine config |
| `talos/patches/**/*.yaml` (10 files) | Talos strategic-merge patches |
| `talos/schematic.yaml` | Image Factory schematic |

**CI fix**: add `-e talos -e assets -e kubernetes/bootstrap` to the validate invocation. See [How to Re-Audit](#how-to-re-audit).

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
| All OCI-sourced HelmReleases use `chartRef` (modern pattern, not legacy `HelmRepository type: oci`) | ✅ |
| No legacy `install.remediation.retries` pattern — global `cluster-apps` patch injects defaults | ✅ |
| Explicit `dependsOn` chains enforcing `cilium → coredns → cert-manager → external-secrets → apps` | ✅ |
| Multi-document `ks.yaml` for operator + CRD-instance Kustomizations (operator dry-run isolation) | ✅ |
| Renovate tracks all pinned versions via `# renovate: datasource=...` annotations | ✅ |
| Receiver deployed for webhook-triggered immediate reconciliation on Git push | ✅ |
| kube-prometheus-stack deployed for Flux controller monitoring | ✅ |
| SOPS + ESO two-tier secrets — Talos secrets encrypted at rest, app secrets never in Git | ✅ |

### Gaps

#### ⚠️ WARNING — Flux alerts wired, but Alertmanager has no outbound receiver

**Half resolved (2026-06-05).** `kubernetes/apps/flux-system/flux-alerts/` now deploys a Flux-native
`Provider` (`type: alertmanager`, in-cluster address — resilient to gateway outages) + `Alert`
(`eventSeverity: error`, `eventSources` = all `Kustomization` + `HelmRelease`, with a sensible
`exclusionList`). So reconciliation errors **are** now forwarded into Alertmanager.

**Remaining gap:** the kube-prometheus-stack `alertmanagerSpec` sets only tolerations + storage — there
is **no `config:` / receiver / route**. Alertmanager therefore runs the chart's default config, whose
top-level route terminates in the `null` receiver. Net effect: Flux errors reach Alertmanager's state
but **never page a human**. Routing *into* the pipeline (done) and routing *out* to a channel (missing)
are independent. Add an Alertmanager `config:` block (or `alertmanager.config` in the chart values) with a
Slack/Discord/email/PagerDuty receiver and a `route` that matches the Flux alerts. Tracked in
[ROADMAP.md → Alertmanager Receiver](ROADMAP.md#alertmanager-receiver).

#### ✅ RESOLVED — Drift detection now cluster-wide default

`driftDetection.mode: enabled` added to the global `cluster-apps` patch (`kubernetes/flux/cluster/ks.yaml`). All 20 HelmReleases now have drift detection enabled. Per-release opt-out via label `driftDetection.flux.home.arpa/disabled: "true"`; fine-grained path exclusions via `spec.driftDetection.ignore` in the HelmRelease YAML. See [CONVENTIONS.md → Drift Detection](CONVENTIONS.md#drift-detection).

#### ℹ️ INFO — FluxInstance `cluster.size` not set

`spec.cluster` is `{}` (empty). Without `cluster.size`, controllers run on default resource limits which may be insufficient as the workload count grows.

**Recommendation**: set `cluster.size: medium` — appropriate for a 3-node cluster with ~20 HelmReleases and ~30 Kustomizations. This enables tuned CPU/memory limits and concurrency settings for kustomize-controller and helm-controller.

#### ℹ️ INFO — FluxInstance sync using SSH deploy key, not GitHub App

`sync.pullSecret: flux-system` with `ssh://git@github.com/...` URL. SSH deploy keys are personal and harder to rotate; GitHub App tokens are short-lived and organisation-scoped.

**Tracked in**: [ROADMAP.md → FluxInstance: Migrate Sync to GitHub App Authentication](ROADMAP.md#fluxinstance-migrate-sync-to-github-app-authentication)

#### ✅ RESOLVED — `retryInterval` now a cluster-wide default

`retryInterval: 2m` is now set on the top-level Flux Kustomizations and injected via the global
`cluster-apps` patch (`kubernetes/flux/cluster/ks.yaml`), so failed reconciliations retry on a
predictable schedule rather than the controller default. (Was I3.)

---

## Security Posture

### Secrets

| Check | Status |
|---|---|
| No plaintext Secrets in Git | ✅ |
| No unencrypted `secretGenerator` literals in kustomization.yaml files | ✅ |
| No hardcoded credentials in HelmRelease `.spec.values` or Kustomization substitutions | ✅ — flagged files are all `ExternalSecret` refs |
| SOPS encryption on `talsecret.sops.yaml` and `cluster-secrets.sops.yaml` | ✅ |
| External Secrets Operator + 1Password Connect for all application secrets | ✅ |

### Sources

| Check | Status |
|---|---|
| No `insecure: true` on any source | ✅ |
| No cloud-registry sources requiring Workload Identity | ✅ — all OCI sources are public GHCR |
| Sync source uses SSH private key (flux-system Secret) | ✅ functional · upgrade to GitHub App tracked in ROADMAP |

### OCI Supply Chain (Cosign Verification)

17 OCIRepositories in use. 6 have `spec.verify.provider: cosign`:

| OCIRepository | Cosign |
|---|---|
| flux-operator | ✅ |
| flux-instance | ✅ |
| app-template (bjw-s) | ✅ |
| tailscale-operator | ✅ |
| external-dns | ✅ |
| openebs | ✅ |
| cert-manager | ❌ |
| cloudnative-pg | ❌ (new) |
| coredns | ❌ |
| envoy-gateway | ❌ |
| gha-runner-scale-set-controller | ❌ |
| gha-runner-scale-set | ❌ |
| kube-prometheus-stack | ❌ |
| reloader | ❌ (new) |
| smartctl-exporter | ❌ (new) |
| spegel | ❌ |
| tuppr | ❌ |

The 11 unverified repositories should be assessed individually — some upstream projects (e.g.
cert-manager, coredns) publish cosign signatures; others (gha-runner-scale-set) may not yet. The
session `2026-05-24 gitops-repo-audit` added cosign to the 6 that support it. Three new repos
(`cloudnative-pg`, `reloader`, `smartctl-exporter`) were added since without verification and should
be checked for upstream cosign availability. (The whereabouts chart source — previously unverified —
was removed in the 2026-06-05 storage-VLAN rollback.)

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
| W1 | Flux `Alert`/`Provider` now forward errors into Alertmanager, but Alertmanager has **no outbound receiver** (default `null` route) — errors still don't reach a human | Add an Alertmanager `config:` with a Slack/Discord/email/PagerDuty receiver + `route` (tracked in ROADMAP → Alertmanager Receiver) |
| ~~W2~~ | ~~Drift detection on 5/20 HelmReleases only~~ | ✅ Resolved — global patch in `cluster-apps` now injects `driftDetection: enabled` for all HelmReleases |

### Info

| # | Finding | Action |
|---|---|---|
| I1 | FluxInstance `cluster.size` unset (`cluster: {}`) — now 26 HR / 40 KS | Set `cluster.size: medium` in `flux-instance` values |
| I2 | FluxInstance sync: SSH deploy key | Migrate to GitHub App auth (tracked in ROADMAP) |
| ~~I3~~ | ~~No `retryInterval` on HelmReleases~~ | ✅ Resolved — `retryInterval: 2m` in the global `cluster-apps` patch + top-level Kustomizations |
| I4 | 11 OCIRepositories without cosign (3 new: `cloudnative-pg`, `reloader`, `smartctl-exporter`) | Audit each upstream for cosign availability; add verification where supported |
| I5 | Validation CI picks up non-K8s YAMLs (`Taskfile.yaml`) | Add `-e talos -e assets -e kubernetes/bootstrap` to validate invocation; `Taskfile.yaml` at root is an unavoidable false positive |
| I6 | kustomize-controller co-location on cp-02 | Add `podAntiAffinity` (preferred) (tracked in ROADMAP) |

---

## How to Re-Audit

Run these commands from the repo root to refresh findings:

```bash
# 1. Resource inventory
bash .claude/skills/gitops-repo-audit/scripts/discover.sh -d .

# 2. Manifest validation (with non-K8s exclusions)
bash .claude/skills/gitops-repo-audit/scripts/validate.sh -d . \
  -e talos -e assets -e .archive -e kubernetes/bootstrap

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
```

After re-running, update the **Last audited** date at the top and revise findings as needed. Close resolved items by moving them to a _Resolved_ table or deleting them.
