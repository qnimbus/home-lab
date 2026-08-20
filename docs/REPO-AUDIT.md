# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-08-20** · Auditor: Claude Code (`gitops-repo-audit` skill) — eighth pass, baseline `284d80f` (last commit to touch this doc) → `c86fc80` (HEAD), 120 commits (91 touching `kubernetes/`). This was a heavy pass: six weeks of real application growth since the seventh pass — 16 new HelmRelease-bearing apps landed (`open-webui` + db, `paperless-ngx` + db, `forgejo` + db, `firefly-iii` + db + `firefly-iii-importer`, `smtp-relay`, `dragonfly` + `dragonfly-operator`, `keda` + `keda-add-ons-http`, `intel-device-plugins` gpu + operator, `node-feature-discovery`, `csi-driver-nfs`, `csi-driver-smb`), plus a Flux upgrade (2.8.8 → 2.9.4) and a GitHub App auth rollout already tracked as resolved. **Audit-tooling bug found and fixed**: a naive repo-wide scan (`discover.sh`/`validate.sh` with no excludes) inflated resource counts 8x — `.claude/worktrees/` holds 8 stale git worktrees (`ceph-packetdrops-docs-refresh`, `flux-operator-0.57.0-bump`, `gitops-repo-audit-2026-08-04`, `homepage-ha-external-service`, `just-bootstrap-default-list`, `keda-dashboard-and-scaler-refactor`, `paperless-ngx-keda-scaler-fix`, `paperless-restore-memory-bump`), each a full checkout duplicating the entire `kubernetes/` tree — on top of the already-known `tmp/` (kubesearch.dev clones, ~1474 YAMLs). Neither was excluded by the documented re-audit recipe; `.claude` is now added to every exclude list below (see the new Info finding). Re-ran the full discovery/validation/API-compliance/security suite with correct exclusions: 53 HelmReleases / 79 Kustomizations / 35 OCIRepositories / 4 HelmRepositories, zero `dependsOn` cycles or dangling references across all 79 Kustomizations, zero drift-detection opt-outs, `flux migrate --dry-run` still reports no deprecated APIs. Validation reports 29 "invalid" resources, all confirmed false positives (17 `HTTPRoute`s with unresolved `${DOMAIN_*}` `postBuild.substitute` placeholders, 12 `${APP}`/`${VOLSYNC_CLAIM}`-templated resource names in reusable `kubernetes/components/` — a new category this pass, since component reuse grew with the new apps) — see [Validation Results](#validation-results) for the full breakdown. One carried-over finding (W4, `fluent-bit` localapi filter shipped commented-out) is now **resolved** — confirmed active in the current `helmrelease.yaml` (landed same day as the seventh audit, commit `0aea67e`). One new Info-level finding: `homepage-config`'s `configMapGenerator` still lacks the `reconcile.fluxcd.io/watch: Enabled` label — confirmed purely cosmetic (not a functional gap) after tracing the actual reconcile path: the label only matters when a ConfigMap is consumed *indirectly* by a different controller's object (HelmRelease `valuesFrom`, Kustomization `postBuild.substituteFrom`), because that controller has no built-in way to notice the referenced object changed. `homepage-config` is rendered and applied directly by its own owning Kustomization (not referenced via `valuesFrom`), so a Git-triggered reconcile picks up content changes in the same pass regardless of the label — and the GitHub webhook Receiver (targeting the shared `GitRepository/flux-system`, which every Kustomization watches) is what makes that reconcile near-instant rather than waiting on the hourly interval. Reloader's `reloader.stakater.com/auto` annotation then handles the actual pod restart once the ConfigMap content changes live. Still worth adding for consistency with the other 13 generated ConfigMaps, but downgraded from "possible functional gap" to "cosmetic-only." Cosign coverage held roughly steady in proportion (13/35, was 8/26) as new OCIRepository sources kept following the existing pattern (verified where upstream ships signatures, unverified otherwise). `renovate-pr-review.yml` remains disabled (per `docs/ROADMAP.md`, unresolved since 2026-07-04) — I13's residual open-egress risk is still moot but unre-assessed; unchanged, not re-litigated this pass.

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
| Flux version | 2.9.4 (managed by flux-operator; was 2.8.8 at the seventh pass) |
| Overall status | **Healthy** — no deprecated APIs, no plaintext secrets, clean manifest validation (0 real failures), zero `dependsOn` cycles |

---

## Resource Inventory

| Kind | Count | Δ since 2026-07-08 |
|---|---|---|
| HelmRelease | 53 | +16 |
| Kustomization | 79 | +26 |
| OCIRepository | 35 | +9 |
| HelmRepository | 4 | — |
| Receiver | 1 | — |
| Alert | 1 | — |
| Provider | 1 | — |
| ImageUpdateAutomation | 0 | — (Renovate remains the version-update mechanism, not Flux image automation) |

**New namespaces since 2026-07-08**: `ai`, `csi-driver-nfs`, `csi-driver-smb`, `development`, `documents`, `finance`, `intel-device-plugins`, `keda`, `mail`, `node-feature-discovery` (10 new, 23 total app-declared namespaces).

**New applications since 2026-07-08**: `open-webui` (ai — CNPG-backed chat UI, no LLM backend wired), `paperless-ngx` (documents), `forgejo` (development — self-hosted Git), `firefly-iii` + `firefly-iii-importer` (finance), `smtp-relay` (mail), `dragonfly` + `dragonfly-operator` (database — Redis-compatible cache/websocket manager), `keda` + `keda-add-ons-http` (system — scale-to-zero for several of the above), `intel-device-plugins` operator + `gpu` (iGPU passthrough), `node-feature-discovery` (labels GPU-capable nodes for the above), `csi-driver-nfs` + `csi-driver-smb` (system — NFS/SMB-backed storage classes), plus a `home-assistant` external-service proxy (this session, `homepage-ha-external-service`).

> **Note on the whoami count**: `kubernetes/apps/default/whoami/ks.yaml` exists on disk (a static-scan inventory counts it) but remains commented out of `kubernetes/apps/default/kustomization.yaml`'s `resources:` — not applied to the live cluster. Unchanged since the sixth pass.

---

## Validation Results

### Kubernetes Manifests — PASS (0 real failures)

All Flux CRDs and Kustomize overlays under `kubernetes/` validate cleanly against the Flux OpenAPI schemas. Kustomize build produces 0 errors across all overlays.

With `-e talos -e assets -e .archive -e ops -e tmp -e .claude` applied, `flux-schema validate` reports **499 valid, 29 "invalid", 14 skipped**. Every "invalid" and "skipped" result is a confirmed false positive:

| Category | Count | Cause |
|---|---|---|
| `HTTPRoute` (`schema violation`) | 17 | `postBuild.substitute` placeholders (`${DOMAIN_CLUSTER}`, `${DOMAIN_APP}`, `${DOMAIN_IO}`) in `hostnames` don't match the DNS-label regex until Flux resolves them at apply time. Affects: `open-webui`, `victoria-logs`, `grafana`, `kube-prometheus-stack-alertmanager`, `kube-prometheus-stack-prometheus`, `truenas`, `home-assistant`, `paperless-ngx`, `rook-ceph-dashboard`, `waha`, `homepage`, `whoami`, `forgejo`, `github-webhook`, `firefly-iii-importer`, `firefly-iii`, `pgadmin` |
| `${APP}` / `${VOLSYNC_CLAIM:=${APP}}` templated `metadata.name` (`schema violation`) | 12 | Same root cause (unresolved `postBuild.substitute` variable), different field — reusable `kubernetes/components/` templates validated in isolation before the consuming app's Kustomization substitutes `${APP}`. New category this pass: `components/volsync` (PVC + ExternalSecret), `components/keda/{http,smb,redis,postgres}-scaler` (4 ScaledObjects), `open-webui`/`paperless-ngx` app-level `ScaledObject`s, `paperless-ngx`'s SMB `PersistentVolume`/`PersistentVolumeClaim` pair (2 each) |

No new false-positive categories beyond the two above — the sixth/seventh-pass CEL `sectionName` quirk on the `envoy-external`/`envoy-internal` HTTP-redirect routes did not reappear (still resolved by I15's explicit `tls.mode`).

**Skipped (14)** — all expected, not failures:

| Cause | Count | Detail |
|---|---|---|
| Non-Kubernetes YAML (missing `apiVersion`/`kind`) | 5 | `Taskfile.yaml`, `docs/EXTERNAL-SECRETS.yaml`, 3× `truenas/docker/*/docker-compose.yaml` — none are in scope for CI (see below) |
| Third-party CRD with no `flux-schema` catalog entry | 9 | `ReplicationDestination`/`ReplicationSource` (VolSync), `Silence` (silence-operator), `KubernetesUpgrade`/`TalosUpgrade` (tuppr), `InterceptorRoute`×2 (KEDA HTTP add-on), `Dragonfly` (dragonfly-operator), `ObjectStore` (barman-cloud CNPG plugin) — all newly-adopted CRDs since the seventh pass; expected per the skill's own documented edge case |

### Non-Kubernetes Files — Expected False Positives

Confirmed CI never hits the 5 non-K8s files above: `.github/workflows/validate.yaml` scopes `validate.sh` to `-d kubernetes`, which never touches `Taskfile.yaml`, `docs/`, or `truenas/`.

### 🆕 Audit-tooling gap: `.claude/worktrees/` was never excluded

The documented re-audit recipe (`-e talos -e assets -e .archive -e ops -e tmp`) predates this repo's adoption of per-task git worktrees under `.claude/worktrees/`. Running `discover.sh`/`validate.sh` without also excluding `.claude` picks up 8 stale worktree checkouts, each duplicating the entire `kubernetes/` tree (470 → 4057 files, 397 → 3131 resources in this pass's initial, uncorrected run) — and made `validate.sh` slow enough to need backgrounding (~10+ minutes validating thousands of redundant/irrelevant manifests, several times over). Fixed in this doc's own recipe below (`-e .claude` added). See I17 in Recommendations for the worktree-hygiene angle.

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
| All Kustomizations have `prune: true`; zero `dependsOn` cycles or dangling references across all 79 Kustomizations (verified programmatically) | ✅ |
| `cluster-settings` ConfigMap + `cluster-secrets` Secret carry `reconcile.fluxcd.io/watch: Enabled`; 12/13 other `configMapGenerator`-based values ConfigMaps do too (see I18 for the one gap) | ✅ |
| Legacy `HelmRepository` + `chart.spec` pattern is now down to 5 HelmReleases (`cilium`, `external-secrets`, `onepassword-connect`, `intel-device-plugins` gpu + operator) — all pinned to upstreams with no official OCI artifact; `metrics-server` moved to `chartRef`/OCI since the seventh pass | ✅ |
| No legacy `install.remediation.retries`-only pattern anywhere — global `cluster-apps` patch injects `strategy.name: RetryOnFailure` + remediation defaults, `retryInterval: 2m`, and `driftDetection.mode: enabled` for every HelmRelease; zero local overrides or opt-out labels found | ✅ |
| Multi-document `ks.yaml` for operator + CRD-instance Kustomizations, used consistently across all new additions this pass (`open-webui`/`open-webui-db`, `firefly-iii`/`-db`, `forgejo`/`-db`, `paperless-ngx`/`-db`, `dragonfly`/`dragonfly-operator`, `intel-device-plugins-{gpu,operator}`) | ✅ |
| Renovate tracks all pinned versions via `# renovate: datasource=...` annotations; all OCIRepository refs use immutable exact tags, no `latest` found | ✅ |
| Receiver deployed for webhook-triggered immediate reconciliation on Git push | ✅ |
| SOPS + ESO two-tier secrets — Talos secrets encrypted at rest, app secrets never in Git; no plaintext Secrets or credential literals found anywhere in the repo | ✅ |
| FluxInstance sync uses GitHub App auth (`sync.provider: github`, `flux-github-app` secret) — no long-lived PAT/SSH key | ✅ |
| ~~`fluent-bit`'s localapi noise-reduction filter shipped commented-out~~ | ✅ Resolved (W4) — confirmed active in current `helmrelease.yaml` (commit `0aea67e`, 2026-07-08) |

### Gaps

#### 🆕 NEW (Info) — `homepage-config` `configMapGenerator` missing the reactivity watch label

`kubernetes/apps/default/homepage/app/kustomization.yaml`'s `configMapGenerator` (9 files: `settings.yaml`, `kubernetes.yaml`, `widgets.yaml`, `services.yaml`, `bookmarks.yaml`, `docker.yaml`, `proxmox.yaml`, `custom.css`, `custom.js`) is the only `configMapGenerator` in the repo without `reconcile.fluxcd.io/watch: Enabled`. **Confirmed cosmetic, not functional**, by tracing the actual reconcile path: the watch label exists to solve a specific cross-controller problem — a ConfigMap/Secret referenced *indirectly* via a HelmRelease's `valuesFrom` or a Kustomization's `postBuild.substituteFrom`, where the *consuming* controller (helm-controller, or another Kustomization's kustomize-controller instance) has no built-in way to notice the referenced object changed, because from its perspective the object it actually owns (the HelmRelease/Kustomization) never changed. `homepage-config` doesn't hit that problem: it's a plain resource rendered and applied *directly* by its own owning Kustomization (`kubernetes/apps/default/`), and it's volume-mounted (`persistence.config.type: configMap` in `helmrelease.yaml`), not referenced via `valuesFrom`. A Git push → GitHub webhook `Receiver` (targets the shared `GitRepository/flux-system`, which every Kustomization in the repo watches for revision changes) → near-instant reconcile of the owning Kustomization → the updated ConfigMap is applied in the very same pass the label would have forced anyway. `reloader.stakater.com/auto: "true"` on the Homepage controller then handles the live pod restart once the ConfigMap's content hash changes. Flagged for consistency with the other 13 rather than a real gap. See I18.

#### ✅ RESOLVED — `fluent-bit` localapi noise filter now active

Was W4 (open since the sixth pass, 2026-07-03). The `[FILTER]` / `grep` / `exclude log` block in `kubernetes/apps/observability/fluent-bit/app/helmrelease.yaml` is no longer commented out — confirmed active, landed same day as the seventh audit in commit `0aea67e` ("rename app labels to app_name for consistency with VictoriaLogs"), which appears to have folded in the localapi fix alongside its stated rename work.

---

## Security Posture

### Secrets

| Check | Status |
|---|---|
| No plaintext Secrets in Git | ✅ — both grep hits (`kubernetes/flux/cluster/ks.yaml`, `envoy-gateway/config/gateway.yaml`) are `kind: Secret` used as a decryption/certificateRef target-type reference, not an actual Secret manifest |
| No unencrypted `secretGenerator` literals in kustomization.yaml files | ✅ — none found repo-wide; all 15 `configMapGenerator`/`secretGenerator` usages are file-based `configMapGenerator` (no `secretGenerator` at all) |
| No hardcoded credentials in HelmRelease `.spec.values`, Kustomization substitutions, or env-style `_KEY=`/`_SECRET=`/`_TOKEN=` literals | ✅ |
| SOPS encryption on `talsecret.sops.yaml` and `cluster-secrets.sops.yaml` | ✅ |
| External Secrets Operator + 1Password Connect for all application secrets (35 ExternalSecrets, up from an unrecorded baseline) | ✅ |

### Sources

| Check | Status |
|---|---|
| No `insecure: true` on any source | ✅ |
| No cloud-registry sources requiring Workload Identity | ✅ — all 35 OCI sources are public GHCR/quay/docker.io/registry.k8s.io/azurecr.io registries; all 4 HelmRepositories are public chart indexes |
| Sync source uses GitHub App auth (short-lived tokens) | ✅ |
| GitHub webhook Receiver secured with `secretRef` | ✅ |

### OCI Supply Chain (Cosign Verification)

35 OCIRepositories in use (was 26). 13 have `spec.verify.provider: cosign` (was 8) — proportional coverage held roughly steady (37% → 37%) as new sources landed:

| OCIRepository | Cosign | | OCIRepository | Cosign |
|---|---|---|---|---|
| app-template (bjw-s) | ✅ | | grafana-operator | ❌ |
| csi-driver-nfs | ✅ **new** | | kube-prometheus-stack | ❌ |
| csi-driver-smb | ✅ **new** | | node-feature-discovery | ❌ **new** |
| external-dns | ✅ | | reloader | ❌ |
| flux-instance | ✅ | | rook-ceph | ❌ |
| flux-operator | ✅ | | rook-ceph-cluster | ❌ |
| keda | ✅ **new** | | silence-operator | ❌ |
| keda-add-ons-http | ✅ **new** | | smartctl-exporter | ❌ |
| metrics-server | ✅ (moved to OCI this pass) | | snapshot-controller | ❌ |
| openebs | ✅ | | spegel | ❌ |
| plugin-barman-cloud | ✅ | | tuppr | ❌ |
| tailscale-operator | ✅ | | victoria-logs | ❌ |
| volsync | ✅ | | blackbox-exporter | ❌ |
| | | | cert-manager | ❌ |
| | | | cloudnative-pg | ❌ |
| | | | coredns | ❌ |
| | | | dragonfly-operator | ❌ **new** |
| | | | envoy-gateway | ❌ |
| | | | fluent-bit | ❌ |
| | | | forgejo | ❌ **new** |
| | | | gha-runner-scale-set | ❌ |
| | | | gha-runner-scale-set-controller | ❌ |

22 of 35 repositories remain unverified. All 9 net-new OCIRepository sources this pass split 4 verified (`csi-driver-nfs`, `csi-driver-smb`, `keda`, `keda-add-ons-http` — home-operations.com charts-mirror and upstream KEDA both ship cosign) / 5 unverified (`dragonfly-operator`, `forgejo`, `grafana-operator` — carried over as unverified, `node-feature-discovery`, plus `metrics-server` moving into the verified column from the legacy-`HelmRepository` pattern nets out separately). Tracked as I4; no action beyond periodic re-assessment of each upstream's cosign availability.

### Network & RBAC

| Check | Status |
|---|---|
| FluxInstance network policies enabled (default `true`) | ✅ |
| Single-tenant cluster — cross-namespace source refs (HelmRelease `sourceRef.namespace: flux-system`, Kustomization `sourceRef` to the central `GitRepository`) are the expected centralized-sources pattern, not a tenancy violation | ✅ N/A |
| No cluster-admin bindings for application workloads | ✅ — the one `ClusterRoleBinding` in the repo (`actions-runner-cluster-admin`) is the documented, deliberate `home-lab` runner-group exception; `home-lab-readonly` has no RBAC at all |
| No multi-tenant admission policies needed (single tenant) | ✅ N/A |
| Application-level `NetworkPolicy` resources | ℹ️ None found repo-wide (0 of any kind). Unchanged posture, not a regression — noting for completeness since this is a growing app surface. Low priority for a single-tenant homelab behind Tailscale/internal-only ingress; see I19 |

---

## Recommendations

### Critical

_None._

### Warning

_None open this pass_ — W4 (fluent-bit localapi filter) is resolved; see [Best Practices → Gaps](#gaps).

### Info

| # | Finding | Action |
|---|---|---|
| I4 | 22 of 35 OCIRepositories without cosign — see [OCI Supply Chain](#oci-supply-chain-cosign-verification) for the full table | Audit each upstream for cosign availability; add verification where supported |
| I13 | `home-lab-readonly`'s Cilium egress restriction remains reverted (accepted residual risk); `renovate-pr-review.yml` remains disabled since 2026-07-04, so this risk continues to have no live exposure | Unchanged — re-assess before re-enabling the workflow, not before |
| I16 | `renovate-pr-review.yml` disabled since 2026-07-04, root cause still not identified per `docs/ROADMAP.md` | Track via ROADMAP.md, not this doc |
| I17 | 8 stale git worktrees under `.claude/worktrees/` (`ceph-packetdrops-docs-refresh`, `flux-operator-0.57.0-bump`, `gitops-repo-audit-2026-08-04`, `homepage-ha-external-service`, `just-bootstrap-default-list`, `keda-dashboard-and-scaler-refactor`, `paperless-ngx-keda-scaler-fix`, `paperless-restore-memory-bump`) — all correspond to sessions already listed as complete/merged in `CLAUDE.md`'s session table. Gitignored and untracked (confirmed via `git ls-files`), so no commit-hygiene risk, but each is a full checkout that inflated a naive repo scan 8x and made unfiltered `validate.sh` runs slow enough to need backgrounding this pass | Not a repo-file change — prune with `git worktree remove .claude/worktrees/<name>` for the ones confirmed merged, at the user's discretion (destructive, out of scope for this audit to do unilaterally) |
| I18 | `homepage-config` `configMapGenerator` lacks `reconcile.fluxcd.io/watch: Enabled`, the only one of 14 generated ConfigMaps missing it. Confirmed cosmetic, not functional — see [Best Practices → Gaps](#gaps) for the full reconcile-path trace | Add `generatorOptions.labels: { reconcile.fluxcd.io/watch: "Enabled" }` to `kubernetes/apps/default/homepage/app/kustomization.yaml` purely for consistency with the other 13 |
| I19 | Zero application-level `NetworkPolicy` resources anywhere in the repo | Low priority given single-tenant + Tailscale/internal-only ingress; revisit if the cluster ever exposes a workload beyond the current trust boundary |

---

## How to Re-Audit

If `flux-schema` isn't already on `PATH`, fetch the binary release before running any of the below:

```bash
curl -sL -o /tmp/flux-schema.tar.gz \
  "https://github.com/fluxcd/flux-schema/releases/download/v0.6.0/flux-schema_0.6.0_linux_amd64.tar.gz"
tar -C /tmp -xzf /tmp/flux-schema.tar.gz flux-schema
chmod +x /tmp/flux-schema && mv /tmp/flux-schema ~/.local/bin/
```

`kubectl`/`kustomize`/`flux` are installed via `mise` but may not be symlinked onto a fresh shell's
`PATH` — if `validate.sh` errors with `neither kustomize nor kubectl is installed`, prepend the mise
shims dir: `export PATH="$HOME/.local/share/mise/shims:$PATH"` (avoid `eval "$(mise activate)"` in
non-interactive tool invocations — it can trip shell-injection guards in sandboxed environments).

Run these commands from the repo root to refresh findings. **`-e .claude` is required** —
`.claude/worktrees/` holds per-task git worktrees that duplicate the entire `kubernetes/` tree;
omitting this exclude (as every prior pass's recipe did) inflates resource counts ~8x and makes
`validate.sh` slow enough to need backgrounding:

```bash
# 1. Resource inventory
bash .claude/skills/gitops-repo-audit/scripts/discover.sh -d . -e tmp -e .claude

# 2. Manifest validation (with non-K8s exclusions)
bash .claude/skills/gitops-repo-audit/scripts/validate.sh -d . \
  -e talos -e assets -e .archive -e ops -e tmp -e .claude

# 3. Deprecated API check
bash .claude/skills/gitops-repo-audit/scripts/check-deprecated.sh -d .

# 4. Security spot-checks
# Unencrypted secrets (false positives expected for cert refs):
grep -rl "kind: Secret" kubernetes/ --include="*.yaml" | \
  xargs -I{} sh -c 'grep -q "sops:\|ENC\[" "$1" || echo "CHECK: $1"' _ {}

# OCIRepositories missing cosign:
for f in kubernetes/flux/meta/repos/oci/*.yaml; do
  [ "$(basename "$f")" = "kustomization.yaml" ] && continue
  grep -q "provider: cosign" "$f" || echo "NO-VERIFY: $(basename $f .yaml)"
done

# HelmReleases opted OUT of the cluster-wide drift-detection default.
# driftDetection.mode: enabled is injected centrally by a patch in
# kubernetes/flux/cluster/ks.yaml — it never appears in individual
# helmrelease.yaml files, so grepping those files for the string always
# reports 100% missing regardless of truth. Check for the opt-out label
# instead:
grep -rl "drift-detection.flux.home.arpa/disabled" kubernetes/apps --include="*.yaml" \
  || echo "No opt-outs — all HelmReleases inherit the global default"

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
