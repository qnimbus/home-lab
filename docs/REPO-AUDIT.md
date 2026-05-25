# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-05-25** · Auditor: Claude Code (`gitops-repo-audit` skill) — W2 resolved same session

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
| HelmRelease | 20 |
| Kustomization | 30 |
| OCIRepository | 14 |
| HelmRepository | 5 |
| Receiver | 1 |
| Alert | 0 |
| Provider | 0 |
| ImageUpdateAutomation | 0 |

**Namespaces**: actions-runner-system, cert-manager, external-secrets, flux-system, kube-system, longhorn-system, network, observability, openebs, system-upgrade, tailscale

**Applications**: cilium · coredns · cert-manager · external-secrets · onepassword-connect · longhorn · openebs · envoy-gateway · cloudflared · external-dns (cloudflare + unifi) · tailscale-operator · actions-runner-controller · kube-prometheus-stack · spegel · metrics-server · tuppr · flux-operator · flux-instance · flux-receiver

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

#### ⚠️ WARNING — No Flux Alerts configured

`Alert` and `Provider` resources are absent. Errors from any HelmRelease or Kustomization are silently swallowed — there is no path to a human operator.

The `Receiver` only handles inbound webhook triggers; it does not send outbound notifications. See [ROADMAP.md → Alertmanager Receiver](ROADMAP.md#alertmanager-receiver) for the planned Alertmanager wiring. A minimal Flux-native alert should also be added independently of Alertmanager — a Slack/Discord webhook `Provider` + `Alert` with `severity: error` across `flux-system` gives immediate feedback on reconciliation failures.

#### ✅ RESOLVED — Drift detection now cluster-wide default

`driftDetection.mode: enabled` added to the global `cluster-apps` patch (`kubernetes/flux/cluster/ks.yaml`). All 20 HelmReleases now have drift detection enabled. Per-release opt-out via label `driftDetection.flux.home.arpa/disabled: "true"`; fine-grained path exclusions via `spec.driftDetection.ignore` in the HelmRelease YAML. See [CONVENTIONS.md → Drift Detection](CONVENTIONS.md#drift-detection).

#### ℹ️ INFO — FluxInstance `cluster.size` not set

`spec.cluster` is `{}` (empty). Without `cluster.size`, controllers run on default resource limits which may be insufficient as the workload count grows.

**Recommendation**: set `cluster.size: medium` — appropriate for a 3-node cluster with ~20 HelmReleases and ~30 Kustomizations. This enables tuned CPU/memory limits and concurrency settings for kustomize-controller and helm-controller.

#### ℹ️ INFO — FluxInstance sync using SSH deploy key, not GitHub App

`sync.pullSecret: flux-system` with `ssh://git@github.com/...` URL. SSH deploy keys are personal and harder to rotate; GitHub App tokens are short-lived and organisation-scoped.

**Tracked in**: [ROADMAP.md → FluxInstance: Migrate Sync to GitHub App Authentication](ROADMAP.md#fluxinstance-migrate-sync-to-github-app-authentication)

#### ℹ️ INFO — No `retryInterval` on any HelmRelease

No HelmRelease sets `retryInterval`. Failed reconciliations retry on the controller's default schedule rather than a predictable interval.

**Recommendation**: add `retryInterval: 1m` to HelmReleases as a cluster-wide default (via the `cluster-apps` global patch) or on individual critical releases. This gives faster recovery from transient failures without overwhelming the API server.

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

14 OCIRepositories in use. 6 have `spec.verify.provider: cosign`:

| OCIRepository | Cosign |
|---|---|
| flux-operator | ✅ |
| flux-instance | ✅ |
| app-template (bjw-s) | ✅ |
| tailscale-operator | ✅ |
| external-dns | ✅ |
| openebs | ✅ |
| cert-manager | ❌ |
| coredns | ❌ |
| envoy-gateway | ❌ |
| gha-runner-scale-set-controller | ❌ |
| gha-runner-scale-set | ❌ |
| kube-prometheus-stack | ❌ |
| spegel | ❌ |
| tuppr | ❌ |

The 8 unverified repositories should be assessed individually — some upstream projects (e.g. cert-manager, coredns) publish cosign signatures; others (gha-runner-scale-set) may not yet. The session `2026-05-24 gitops-repo-audit` added cosign to the 6 that support it; the remaining 8 are downstream-limited or not yet investigated.

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
| W1 | No Flux `Alert`/`Provider` configured — reconciliation errors are silent | Add a Discord/Slack `Provider` + `Alert` in `flux-system` with `severity: error` |
| ~~W2~~ | ~~Drift detection on 5/20 HelmReleases only~~ | ✅ Resolved — global patch in `cluster-apps` now injects `driftDetection: enabled` for all HelmReleases |

### Info

| # | Finding | Action |
|---|---|---|
| I1 | FluxInstance `cluster.size` unset | Set `cluster.size: medium` in `flux-instance` values |
| I2 | FluxInstance sync: SSH deploy key | Migrate to GitHub App auth (tracked in ROADMAP) |
| I3 | No `retryInterval` on HelmReleases | Add `retryInterval: 1m` via global `cluster-apps` patch |
| I4 | 8 OCIRepositories without cosign | Audit each upstream for cosign availability; add verification where supported |
| I5 | Validation CI picks up non-K8s YAMLs | Add `-e talos -e assets -e kubernetes/bootstrap` to validate invocation |
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
