# GitOps Repository Audit <!-- omit from toc -->

> **Living document** — re-run the audit commands in [How to Re-Audit](#how-to-re-audit) after significant changes and update the findings below.
> Last audited: **2026-07-03** · Auditor: Claude Code (`gitops-repo-audit` skill) — sixth pass, baseline `e542cd3` (last commit to touch this doc) → `7d8e377` (HEAD), 26 commits. Notable arrivals: `unpoller` (UniFi metrics) + `grafana-operator` in external mode (dashboards/datasources managed via the Grafana HTTP API against the existing kube-prometheus-stack Grafana, no second Grafana instance), `silence-operator` fully live with 4 GitOps-managed Alertmanager silences (hardware-fallback noise suppression, each with a documented revert condition), a `cp-03` hardware replacement, and three same-day rook-ceph logging-volume tuning commits — one of which (`8c7162d`) shipped an invalid Ceph config key that was self-diagnosed via the week-old VictoriaLogs pipeline and corrected the same day (`76d5ada`), a good early proof-of-value for the log-aggregation investment. Re-ran the full discovery/validation/API-compliance/security suite: resource counts now 37 HelmReleases / 53 Kustomizations / 26 OCIRepositories (was 34/48/24), `flux migrate --dry-run` reports no deprecated APIs, drift-detection opt-outs and `configMapGenerator` watch-label gaps both still zero. `flux-schema` was not preinstalled in this container and had to be fetched fresh (v0.6.0, up from whatever version ran the fifth pass) — its newer Gateway API CEL rules surfaced two likely-false-positive `cel violation` findings not seen last pass (see Validation Results). One genuine new finding: a `fluent-bit` log filter that the commit message says was added is actually shipped fully commented-out, so the noise reduction it describes isn't happening (see W4 in Recommendations). Also discovered and excluded a `tmp/` scratch directory (gitignored, holding two full reference-repo clones from prior kubesearch.dev research) that inflated a naive discovery pass to 1480 resources — not part of this repo's actual GitOps tree, exclude it in any future ad-hoc scan.

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

| Kind | Count | Δ since 2026-06-24 |
|---|---|---|
| HelmRelease | 37 | +3 (unpoller, grafana-operator, silence-operator) |
| Kustomization | 53 | +5 (unpoller, grafana-operator + grafana-operator-instance, silence-operator + silence-operator-silences) |
| OCIRepository | 26 | +2 (grafana-operator, silence-operator; unpoller reuses the shared `app-template` source) |
| HelmRepository | 4 | — |
| Receiver | 1 | — |
| Alert | 1 | — |
| Provider | 1 | — |
| ImageUpdateAutomation | 0 | — |

> **Note on the whoami count**: `kubernetes/apps/default/whoami/ks.yaml` exists on disk (a static-scan inventory like `discover.sh` counts it), but `kubernetes/apps/default/kustomization.yaml` has it commented out of `resources:`. It is **not applied to the live cluster** — added as a connectivity smoke-test, then deliberately disabled (commit `a88ecf1`). Don't read the +1 as a live resource change.

**Namespaces (app-declared via `namespace.yaml`)**: actions-runner-system, automation, database, external-secrets, network, observability, openebs, reloader, rook-ceph, snapshot-controller, system-upgrade, tailscale, volsync. **Bootstrap-managed** (created by the Helmfile bootstrap phase before Flux takes over, not by a GitOps `namespace.yaml`): kube-system, cert-manager, flux-system. `default` is a built-in namespace — whoami targets it directly via `targetNamespace`, no `namespace.yaml` needed.

**Applications**: cilium · coredns · cert-manager · external-secrets · onepassword-connect · openebs · rook-ceph (operator + cluster) · envoy-gateway · cloudflared · external-dns (cloudflare + unifi) · tailscale-operator · actions-runner-controller (split into `home-lab` privileged + `home-lab-readonly` zero-permission runner groups) · kube-prometheus-stack · smartctl-exporter · spegel · metrics-server · reloader · snapshot-controller · tuppr · cloudnative-pg (+ pgadmin + postgres-backup-local + plugin-barman-cloud) · waha · volsync (PVC backup) · victoria-logs (log storage) · fluent-bit (log shipper) · unpoller (new — UniFi metrics) · grafana-operator (new — external-mode dashboard/datasource management) · silence-operator (new — GitOps Alertmanager silences) · external-services (truenas + wan-failover) · flux-operator · flux-instance · flux-receiver · flux-alerts · whoami (disabled)

> Longhorn is fully gone (superseded by Rook-Ceph, big-bang migration). `rook-ceph` (`ceph-block`) is now the default StorageClass with all 5 stateful consumers migrated. A `ceph-block-single` (size=1) StorageClass was added (`ee1ada8`) for disposable, non-redundant PVCs, then retired the same week (`8d12fc0`) — its single-replica PGs made `ceph osd ok-to-stop` return false for every OSD, jamming Rook's one-at-a-time rolling OSD updates. The pool held 0 PVCs/PVs, so removal was lossless; `openebs-hostpath` is now documented as the canonical choice for disposable single-node data instead.

---

## Validation Results

### Kubernetes Manifests — PASS

All Flux CRDs and Kustomize overlays under `kubernetes/` validate cleanly against the Flux OpenAPI schemas. Kustomize build produces 0 errors across all overlays.

With `-e talos -e assets -e .archive -e ops -e tmp` applied, `flux-schema validate` (v0.6.0 — see note below) reports 14 "invalid" resources, all confirmed false positives:

| Kind | Count | Cause |
|---|---|---|
| HTTPRoute | 13 | `postBuild.substitute` placeholders (`${DOMAIN_CLUSTER}`, `${DOMAIN_APP}`, `${DOMAIN_IO}`) in `hostnames` don't match the DNS-label regex until Flux resolves them at apply time — expected per the skill's own documented edge case |
| PersistentVolumeClaim | 1 | Same cause — VolSync's `${VOLSYNC_CLAIM:=${APP}}` templated `metadata.name` |

The 2 `Gateway` `cel violation` findings seen earlier this pass (`envoy-external`/`envoy-internal` omitting explicit `tls.mode`) were resolved same-day — see I15 in Recommendations, now closed.

Also observed (not counted as "invalid" — `cel violation` against `envoy-external-http-redirect`/`envoy-internal-http-redirect` HTTPRoutes, "sectionName must be unique when parentRefs includes 2 or more references to the same parent"): both routes' rendered `parentRefs` array has exactly one entry with `sectionName: http` already set (confirmed via the merged validation bundle) — the rule is misfiring on a single-element array, another apparent v0.6.0 CEL artifact, not a real duplicate-parentRef bug. No repo-side fix available for this one (there's no equivalent explicit field to add); left as a known tool quirk.

### Non-Kubernetes Files — Expected False Positives

With the `-e talos -e assets -e .archive -e ops -e tmp` exclusions applied, only `Taskfile.yaml` (go-task runner, not a Kubernetes manifest — missing `kind` key) remains as an expected false positive from the general scan. Confirmed CI never hits this either way, since `Taskfile.yaml`/`talos/`/`ops/` sit outside the `-d kubernetes` scope the actual CI/Task invocation uses (I5, resolved 2026-06-17). `tmp/` is a newly-observed, gitignored scratch directory (see header note) — add `-e tmp` to the recipe going forward.

Note: the repo restructure in commit `c8771da` moved `bootstrap/` → `ops/bootstrap/` and `cnpg/` → `ops/cnpg/`. The previous version of this exclusion list (`-e bootstrap`) is now stale — `ops/bootstrap/helmfile.d/{00-crds,01-apps}.yaml` (Helmfile configs, not Kubernetes manifests) surface as two additional false positives if you still pass `-e bootstrap` instead of `-e ops`. Fixed in the "How to Re-Audit" recipe below (I11).

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
| Zero `dependsOn` cycles or dangling references across all 53 Kustomizations (verified programmatically) | ✅ |
| Multi-document `ks.yaml` for operator + CRD-instance Kustomizations (operator dry-run isolation) | ✅ |
| Renovate tracks all pinned versions via `# renovate: datasource=...` annotations; all OCIRepository refs use immutable exact tags | ✅ |
| Receiver deployed for webhook-triggered immediate reconciliation on Git push | ✅ |
| kube-prometheus-stack deployed for Flux controller monitoring | ✅ |
| SOPS + ESO two-tier secrets — Talos secrets encrypted at rest, app secrets never in Git | ✅ |
| Flux controllers (helm/kustomize/notification) run 2 replicas + `topologySpreadConstraints` (`ScheduleAnyway`) — survive single-node reboots during Talos/K8s upgrades | ✅ |
| New `ceph-grafana-dashboards` `configMapGenerator` (9 dashboard JSONs) correctly inherits the reactivity-watch label | ✅ — verified via `kustomize build`: Kustomize **merges** top-level `generatorOptions.labels` with a generator's own `options.labels` (doesn't override), so the rendered ConfigMap carries both `grafana_dashboard: "1"` and `reconcile.fluxcd.io/watch: Enabled` |
| `ops/` repo restructure (`bootstrap/`, `cnpg/` → `ops/bootstrap/`, `ops/cnpg/`) left no broken references | ✅ — `.github/workflows/validate.yaml`'s scoping comment was updated in the same commit (`c8771da`) to reflect the new path; `values.yaml.gotmpl`'s relative `readFile` (previously hardcoded to the old 3-levels-deep nesting) was also fixed and verified via `helmfile template` |
| `cloudflared` origin-cert verification (`noTLSVerify: true` → `false`) shipped together with a `reloader.stakater.com/auto` annotation | ✅ — correctly recognizes that `config.yaml` is mounted via `subPath`, which Kubernetes never live-updates; without Reloader this and future config edits would sit inert in Git until a manual restart |
| New `victoria-logs`/`fluent-bit`/`volsync` Kustomizations all carry explicit, commented `dependsOn` reasoning rather than guessed ordering | ✅ — e.g. `fluent-bit`'s `ks.yaml` deliberately does *not* depend on `victoria-logs` ("the http output plugin retries on its own if it isn't up yet"), while `victoria-logs` *does* depend on `kube-prometheus-stack` for the ServiceMonitor/dashboard-sidecar CRDs it relies on — the dependency graph reflects actual coupling, not blanket caution |
| `volsync`'s `MutatingAdmissionPolicy` (native CEL admission, GA in this cluster's K8s version) injects a random 0–30s jitter `initContainer` into every backup Job | ✅ — scoped to `volsync-src-` name-prefix + `app.kubernetes.io/created-by: volsync` label match, verified against VolSync's own shared (not fork-specific) controller code; spreads backup start times so a growing number of scheduled apps doesn't spike NFS/CPU simultaneously |
| `components/volsync/pvc.yaml`'s `kustomize.toolkit.fluxcd.io/ssa: IfNotPresent` label correctly anticipates that `dataSourceRef` is immutable on existing PVCs | ✅ — lets Flux skip the generated PVC for apps retrofitted onto a pre-existing live PVC instead of erroring, while still creating fresh bootstrap-restore-enabled PVCs for genuinely new apps |
| actions-runner-controller RBAC split: `home-lab` keeps the (deliberately reserved) `cluster-admin` binding; `home-lab-readonly` (used for automated Renovate-PR-review jobs) gets a `ServiceAccount` bound to nothing | ✅ — `rbac.yaml`'s comment documents a real gotcha: leaving `serviceAccountName` unset lets the `gha-runner-scale-set` chart auto-provision its own namespace-scoped Role (pods/exec/log, jobs, secrets — all with create+delete), silently reintroducing the privilege the split exists to remove |
| 2026-06-23 Anthropic API key leak (PR-review job log, via an un-masked `${{ env.* }}` reference) was root-caused, the key rotated, and the workflow fixed to source it via `${{ secrets.* }}` (auto-masked by GitHub everywhere) within hours | ✅ — see `68fbc4d`; the dead `ExternalSecret`/pod-env injection paths that produced the leaked value were removed from both runner groups in the same commit, not left dangling |
| `renovate-pr-review.yml`'s job condition keys off `pull_request.user.login` (the PR's actual creator) plus a fork-head check, instead of `github.actor` alone | ✅ (2026-06-24) — `github.actor` reflects whoever triggered the *current* event, which would flip to a human on `synchronize` if anyone but Renovate ever pushed to the branch; gating on the stable creator identity avoids that false-skip, and the fork-head check is cheap defense-in-depth even on a private repo |
| `renovate-pr-review.yml` now skips the paid Claude review entirely for patch-only or unlabeled (e.g. digest) Renovate PRs, using the `type/major`/`type/minor` labels Renovate already applies via `renovate.json5` | ✅ (2026-06-24) — a pre-checkout step reads labels live via `gh pr view` rather than trusting the triggering event's label snapshot (Renovate adds labels in a follow-up API call after PR creation, so `opened` can fire before they land — `labeled` was added to the trigger `types:` to catch that race) |
| `renovate-pr-review.yml` gained a `workflow_dispatch` input (`pr_number`) so the review can still be run by hand against any PR | ✅ (2026-06-24) — manual dispatch deliberately bypasses both the Renovate-actor/fork gate and the type-label gate; this is safe because `workflow_dispatch` is itself restricted by GitHub to users with write access to the repo, so there's no third-party-trigger risk left to additionally guard against on that path |
| `grafana-operator`'s CRD-instance Kustomization (`grafana-operator-instance`) correctly `dependsOn`s both `grafana-operator` (owns the `Grafana` CRD) and `kube-prometheus-stack` (owns the Grafana Deployment + `grafana-admin-secret` this external-mode `Grafana` CR points at), and adds an explicit `healthChecks` entry for the `grafana-admin` `ExternalSecret` even though that Secret is created by a different Kustomization | ✅ — correctly applies the "async prerequisites in the earlier Kustomization" bootstrap-ordering rule (CLAUDE.md) to a cross-Kustomization dependency, not just a same-Kustomization one: kube-prometheus-stack's own `ks.yaml` sets `wait: false`, so without this explicit healthCheck a fresh bootstrap could race the external `Grafana` CR against a not-yet-created admin Secret |
| `unpoller`'s `ExternalSecret` uses `dataFrom.extract` + a `rewrite.regexp` prefix (`UNIFI_$1`) to map a single 1Password item's fields onto multiple `UP_UNIFI_DEFAULT_*` env vars | ✅ — same rewrite pattern already validated in the alertmanager/rook-ceph ExternalSecrets; correctly keeps the container's env-var contract independent of 1Password's internal field names |
| Rook-Ceph mon/mgr log-volume tuning (`8c7162d`, `76d5ada`, `3b8966c`) shipped a bug (invalid `rocksdb_stats_dump_period_sec` config key causing a set→ENOENT→delete retry loop) that was root-caused via a VictoriaLogs log-volume query and fixed same-day | ✅ — early real-world payoff from the week-old log-aggregation pipeline; the fix (`bluestore_rocksdb_options_annex`) correctly avoids clobbering the chart/Ceph-default `bluestore_rocksdb_options` string |
| `silence-operator`'s 4 `Silence` CRs are all scoped to specific `alertname` matchers with revert conditions documented inline (pointing at the underlying hardware root cause, e.g. `.claude/agent-memory/cluster-doctor/project_cp02_storage_bond_ixgbe_failure.md`) rather than broad label-based suppressions | ✅ — none of the silences risk masking an unrelated real alert; each is traceable back to a specific, temporary hardware condition |

### Gaps

#### 🆕 NEW — `fluent-bit` localapi noise filter is shipped disabled

Commit `50fe449` ("enhance log filtering for tailscale-operator and localapi calls") added a
well-reasoned comment explaining that `tailscaled`'s `containerboot` polls
`POST /localapi/v0/debug` on every netmap change, "unconditionally, high-volume, zero signal" —
and a `[FILTER]` / `grep` / `exclude log` block to drop those lines. But the entire filter block
(lines 94–97 of `kubernetes/apps/observability/fluent-bit/app/helmrelease.yaml`) is committed
**commented out** inside the live Fluent Bit `filters:` config string, so it has no effect at
runtime — the noise this commit set out to reduce is still being shipped to VictoriaLogs. This
reads as an accidental omission rather than a deliberate no-op: the companion `hard_rename`
change in the same section (tailscale-operator's `app` label handling), which *was* deliberately
left disabled, has its own "Decided against it" rationale in the same follow-up commit
(`45230c8`); the localapi block has no equivalent "why this stays off" note, only a description
of the problem it's meant to fix. See W4 in Recommendations.

#### ✅ RESOLVED — 13 generated values ConfigMaps now carry the reactivity label

Was W3. Added `generatorOptions: { labels: { reconcile.fluxcd.io/watch: "Enabled" } }` to all 13 `kustomization.yaml` files using `configMapGenerator` for chart values (merged into the existing `generatorOptions` block for `cloudflared`, which also sets `disableNameSuffixHash`). Verified via `kustomize build` that the label renders on the generated ConfigMap. This closes the gap behind the known `feedback_flux_configmap_hash.md` gotcha — `values.yaml` edits now trigger immediate reconciliation instead of requiring `flux reconcile helmrelease --force`.

#### ✅ RESOLVED — Alertmanager outbound receiver (Pushover) live

Was W1. Implemented and committed (`878b7d1`):
- `app/alertmanagerconfig.yaml` — a root `AlertmanagerConfig` (wired via `alertmanagerSpec.alertmanagerConfiguration.name`, which replaces the chart's literal `config:` rather than being discovered as a sub-route — sidesteps `alertmanagerConfigSelector`'s default `OnNamespace` matcher entirely). Routes `severity=critical` → `pushover-critical` (priority 2, `retry: 60s`, `expire: 1h`), `severity=~"warning|error"` → `pushover` (priority 1). The `error` severity value is what Flux's own `notification-controller` uses for its `alertmanager`-type `Provider` (`flux-errors` Alert in `flux-alerts/`), so Flux reconciliation failures now route into the same paging path.
- `app/externalsecret.yaml` — new `alertmanager` ExternalSecret pulling a 1Password item (key `alertmanager`) and rewriting every extracted field via `regexp: (.*) → ALERTMANAGER_$1` into `alertmanager-secret`, with the target `template.data` referencing `{{ .ALERTMANAGER_PUSHOVER_TOKEN }}` / `{{ .ALERTMANAGER_PUSHOVER_USER_KEY }}`.
- `app/helm/values.yaml` + `app/kustomization.yaml` wiring.

Both verification items closed: the 1Password `alertmanager` item's fields are confirmed named literally `PUSHOVER_TOKEN`/`PUSHOVER_USER_KEY`, matching the `ALERTMANAGER_` rewrite + template lookup; and the path has been live-tested end-to-end by the user, who found and fixed a message-truncation issue (`0d51e10` — the per-alert label dump multiplied across grouped alerts and blew past Pushover's 1024-rune message cap; dropped the label dump, capped the loop to 5 alerts, and dropped `html: true` since it's no longer needed) before confirming delivery works.

#### ✅ RESOLVED — `whoami` HelmRelease now has Pod-security hardening

Was I10, found and fixed in the same pass. `traefik/whoami` runs as root and binds port 80 by
default with no support for non-root execution out of the box — naively adding
`runAsNonRoot: true` + `capabilities.drop: ["ALL"]` would have broken the privileged-port bind.
Verified (via the upstream README) that the binary supports `WHOAMI_PORT_NUMBER` to change its
listening port, so the fix moves the app to `:8080` internally and uses app-template's
`service.<name>.ports.<name>.targetPort` to keep the Service/HTTPRoute-facing port at 80 — no
external contract change. This allows `runAsNonRoot: true` + `runAsUser/runAsGroup/fsGroup: 65534`
+ `capabilities.drop: ["ALL"]` with no capability add-back, matching the `waha` pattern. Confirmed
via `kustomize build` + `kubeconform` that the HelmRelease still renders and validates cleanly.

#### ✅ RESOLVED — FluxInstance sync now uses GitHub App authentication

Was tracked as I2 (SSH deploy key). `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` now sets `sync.provider: github` with an HTTPS URL and `pullSecret: flux-github-app`, backed by an `ExternalSecret` populating `githubAppID`/`githubAppInstallationID`/`githubAppPrivateKey`. The corresponding `docs/ROADMAP.md` entry was stale (described this as pending) and has been marked done.

#### ✅ RESOLVED — kustomize-controller / Flux pod concentration

Was tracked as I6 (recommended `podAntiAffinity`). Implemented instead via `topologySpreadConstraints` (`maxSkew: 1`, `ScheduleAnyway`) + `replicas: 2` on helm-controller/kustomize-controller/notification-controller, scoped via a shared `app.kubernetes.io/part-of: flux` label. The soft constraint was a deliberate choice over `DoNotSchedule` — it keeps controllers running through the ~80-minute single-node reboot window of a Talos/K8s upgrade instead of leaving them Pending.

#### ✅ RESOLVED — Drift detection now cluster-wide default

`driftDetection.mode: enabled` is in the global `cluster-apps` patch. All 37 HelmReleases have drift detection enabled, including the disabled `whoami` and the three newest additions (`unpoller`, `grafana-operator`, `silence-operator`) — re-verified this pass, zero opt-out labels found.

#### ✅ RESOLVED — FluxInstance `cluster.size` now set to `medium`

Was I1. `spec.cluster.size: medium` set in `flux-instance` values — appropriate then for ~28 HelmReleases / ~42 Kustomizations and still appropriate now at 34/48 (upstream guidance reserves `large` for fleets approaching a thousand apps).

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

26 OCIRepositories in use. 8 have `spec.verify.provider: cosign` — unchanged in absolute count from
the fifth pass:

| OCIRepository | Cosign |
|---|---|
| flux-operator | ✅ |
| flux-instance | ✅ |
| app-template (bjw-s) | ✅ |
| tailscale-operator | ✅ |
| external-dns | ✅ |
| openebs | ✅ |
| plugin-barman-cloud | ✅ |
| volsync | ✅ |
| cert-manager | ❌ |
| cloudnative-pg | ❌ |
| coredns | ❌ |
| envoy-gateway | ❌ |
| fluent-bit | ❌ |
| gha-runner-scale-set-controller | ❌ |
| gha-runner-scale-set | ❌ |
| **grafana-operator** | ❌ (new, `f6cd374`) |
| kube-prometheus-stack | ❌ |
| reloader | ❌ |
| rook-ceph | ❌ |
| rook-ceph-cluster | ❌ |
| **silence-operator** | ❌ (new, `0306927`) |
| smartctl-exporter | ❌ |
| snapshot-controller | ❌ |
| spegel | ❌ |
| tuppr | ❌ |
| victoria-logs | ❌ |

18 of 26 repositories remain unverified. Both sources added this pass (`grafana-operator`,
`silence-operator`) arrived unverified, continuing the pattern where only `app-template`-adjacent
and a handful of security-focused projects (tailscale-operator, external-dns, openebs,
plugin-barman-cloud, volsync) ship cosign signatures upstream. `unpoller` doesn't add a new
OCIRepository — it's deployed via the shared, already-verified `app-template` chart. This remains
tracked as I4; no new action beyond periodic re-assessment of each upstream's cosign availability.

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
| ~~W1~~ | ~~Flux `Alert`/`Provider` forward errors into Alertmanager, but Alertmanager has no outbound receiver~~ | ✅ Resolved — Pushover receiver + `AlertmanagerConfig` live (`878b7d1`, `0d51e10`); 1Password fields and end-to-end delivery both confirmed |
| ~~W2~~ | ~~Drift detection on 5/20 HelmReleases only~~ | ✅ Resolved — global patch in `cluster-apps` now injects `driftDetection: enabled` for all 28 HelmReleases |
| ~~W3~~ | ~~13 `configMapGenerator`-based values ConfigMaps lack `reconcile.fluxcd.io/watch: Enabled`~~ | ✅ Resolved — `generatorOptions.labels` added to all 13 `kustomization.yaml` files |
| W4 | `fluent-bit`'s localapi noise-reduction `[FILTER]` block (`kubernetes/apps/observability/fluent-bit/app/helmrelease.yaml` lines 94–97) is committed fully commented-out inside the live Fluent Bit config string — the tailscaled `localapi` chatter it was written to suppress is still flowing to VictoriaLogs. Low severity (cosmetic log volume, not correctness/security), but the commit message ("enhance log filtering... for localapi calls") states an intent the shipped config doesn't deliver | Uncomment the `[FILTER]`/`grep`/`exclude log` block (or add a comment explaining why it's deliberately parked, matching the pattern already used for the adjacent `hard_rename` decision) |

### Info

| # | Finding | Action |
|---|---|---|
| ~~I1~~ | ~~FluxInstance `cluster.size` unset (`cluster: {}`)~~ | ✅ Resolved — set to `medium` |
| ~~I2~~ | ~~FluxInstance sync: SSH deploy key~~ | ✅ Resolved — GitHub App auth live (`provider: github`, `flux-github-app` secret); ROADMAP.md entry marked done |
| ~~I3~~ | ~~No `retryInterval` on HelmReleases~~ | ✅ Resolved — `retryInterval: 2m` in the global `cluster-apps` patch + top-level Kustomizations |
| I4 | 18 of 26 OCIRepositories without cosign (`rook-ceph`, `rook-ceph-cluster`, `snapshot-controller`, and the two newest, `grafana-operator`/`silence-operator`, among them; `plugin-barman-cloud` and `volsync` remain the only recent additions that arrived pre-verified) | Audit each upstream for cosign availability; add verification where supported |
| ~~I5~~ | ~~Validation CI picks up non-K8s YAMLs~~ | ✅ Resolved — turned out CI/Task already scope `validate.sh` to `-d kubernetes`, never touching `Taskfile.yaml`/`talos/`; removed the dead `-e kubernetes/bootstrap` exclude (bootstrap moved to repo-root `bootstrap/` some time ago, so the flag pointed at a non-existent path) |
| ~~I6~~ | ~~kustomize-controller co-location~~ | ✅ Resolved — `topologySpreadConstraints` + 2 replicas on helm/kustomize/notification-controller |
| ~~I7~~ | ~~5 HelmReleases set redundant `createNamespace: true`~~ | ✅ Resolved — removed the now-empty `install:` block from all 5 |
| ~~I8~~ | ~~4 HelmReleases redundantly redeclare `driftDetection: mode: enabled`~~ | ✅ Resolved — removed the local declaration from all 4 |
| ~~I9~~ | ~~`kustomize-controller` `--concurrent` set via two colliding patches (10, then 20) — last one silently won~~ | ✅ Resolved — consolidated into one explicit patch; `(helm-controller\|source-controller)` keep `--concurrent=10` |
| ~~I10~~ | ~~`whoami` HelmRelease lacked `securityContext`/`defaultPodOptions` hardening~~ | ✅ Resolved — moved app to internal port 8080 (`WHOAMI_PORT_NUMBER`) + `targetPort: 8080` on the Service, enabling `runAsNonRoot`/`capabilities.drop: ["ALL"]` with no capability add-back |
| ~~I11~~ | ~~This doc's own "How to Re-Audit" recipe used a stale `-e bootstrap` exclude after the `ops/` restructure (`c8771da`)~~ | ✅ Resolved — updated to `-e ops`; verified `ops/bootstrap/helmfile.d/*.yaml` no longer false-positive when scanning from repo root |
| ~~I12~~ | ~~This doc's own "How to Re-Audit" recipe had two latent bugs in its spot-checks: the drift-detection check grepped individual `helmrelease.yaml` files for `driftDetection`, which never appears there (it's injected centrally by a `cluster-apps` patch in `kubernetes/flux/cluster/ks.yaml`) — would report 100% of HelmReleases as missing drift detection regardless of truth; previously masked by an unrelated `xargs -l` syntax bug that silently no-op'd instead of running. The cosign-coverage loop's glob also picked up the oci repos directory's own `kustomization.yaml` as a false `NO-VERIFY` entry~~ | ✅ Resolved — drift-detection check rewritten to look for the `drift-detection.flux.home.arpa/disabled` opt-out label instead (none found — all 29 HelmReleases genuinely inherit the global default, confirming the existing W2 finding was correct despite the broken check); cosign loop now excludes `kustomization.yaml` |
| I13 | `home-lab-readonly`'s `CiliumNetworkPolicy` egress restriction was reverted (`b4f1e38`) after proving unreliable: `broker.actions.githubusercontent.com` CNAMEs through a GitHub GLB hostname, and Cilium never allocated a CIDR identity for the resolved IP (confirmed live via `cilium-dbg`, well past any agent-settling window). Network containment itself is **not** restored by the fix below — this remains an accepted residual risk | ⚠️ Narrowed, not resolved (2026-06-24) — `renovate-pr-review.yml` hardened so the open-egress runner now executes far less often: the job gates on `pull_request.user.login == 'renovate[bot]'` (stable across `synchronize`, unlike `github.actor`, which flips to a human if anyone else ever pushes to the branch) **and** rejects any PR whose head lives outside this repo (fork check — this repo is private, so this is defense-in-depth, not the primary control), **and** a new pre-checkout step skips the Claude review entirely unless the PR carries a `type/major` or `type/minor` label, reading labels live via `gh pr view` rather than the trigger event's snapshot (Renovate attaches labels in a follow-up call, so `opened` can race ahead of them — `labeled` was added to the trigger list to catch that). Patch-only and unlabeled (e.g. digest) PRs no longer invoke the AI reviewer — or even check out the repo — at all. If untrusted-input exposure grows further, revisit egress restriction via a non-FQDN mechanism (e.g. a static CIDR allowlist for GitHub's published IP ranges, or an explicit egress proxy) rather than retrying Cilium `toFQDNs` against a GLB-fronted hostname |
| ~~I14~~ | ~~`kubernetes/apps/automation/waha/ks.yaml`'s comment described the VolSync PVC cutover as "step 3 (separate, deliberate, not yet done)", but `docs/ROADMAP.md`'s VolSync section says the canary cutover is "✅ DONE" — the live PVC was swapped, just via an incident rather than the deliberate procedure the comment described~~ | ✅ Resolved (2026-06-24) — comment rewritten to match the completed state recorded in ROADMAP.md |
| ~~I15~~ | ~~`envoy-gateway/config/gateway.yaml`'s `envoy-external`/`envoy-internal` HTTPS listeners relied on the Gateway API's implicit `tls.mode: Terminate` default rather than setting it explicitly, which a newer `flux-schema` v0.6.0 CEL rule flagged as a false-positive `cel violation`~~ | ✅ Resolved (2026-07-03) — added `mode: Terminate` explicitly to both listeners' `tls:` blocks. Zero behavior change (`kustomize build` output unchanged apart from the added field); re-validated with `flux-schema validate --verbose` — both Gateways now report `is valid` with no CEL findings |

---

## How to Re-Audit

If `flux-schema` isn't already on `PATH` (fresh devcontainer — it isn't preinstalled as of this
pass), fetch the binary release before running any of the below:

```bash
curl -sL -o /tmp/flux-schema.tar.gz \
  "https://github.com/fluxcd/flux-schema/releases/download/v0.6.0/flux-schema_0.6.0_linux_amd64.tar.gz"
tar -C /tmp -xzf /tmp/flux-schema.tar.gz flux-schema
chmod +x /tmp/flux-schema && mv /tmp/flux-schema ~/.local/bin/
```

Run these commands from the repo root to refresh findings:

```bash
# 1. Resource inventory (exclude tmp/ — gitignored scratch space for kubesearch.dev
# reference-repo clones, not part of this repo's GitOps tree)
bash .claude/skills/gitops-repo-audit/scripts/discover.sh -d . -e tmp

# 2. Manifest validation (with non-K8s exclusions)
bash .claude/skills/gitops-repo-audit/scripts/validate.sh -d . \
  -e talos -e assets -e .archive -e ops -e tmp

# 3. Deprecated API check
bash .claude/skills/gitops-repo-audit/scripts/check-deprecated.sh -d .

# 4. Security spot-checks
# Unencrypted secrets (false positives expected for cert refs):
grep -rl "kind: Secret" kubernetes/ --include="*.yaml" | \
  xargs -I{} sh -c 'grep -q "sops:\|ENC\[" "$1" || echo "CHECK: $1"' _ {}

# OCIRepositories missing cosign (excludes the directory's own kustomization.yaml):
for f in kubernetes/flux/meta/repos/oci/*.yaml; do
  [ "$(basename "$f")" = "kustomization.yaml" ] && continue
  grep -q "provider: cosign" "$f" || echo "NO-VERIFY: $(basename $f .yaml)"
done

# HelmReleases opted OUT of the cluster-wide drift-detection default.
# driftDetection.mode: enabled is injected centrally by a patch in
# kubernetes/flux/cluster/ks.yaml — it never appears in individual
# helmrelease.yaml files, so grepping those files for the string always
# reports 100% missing regardless of truth. Check for the opt-out label
# instead (see I12):
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
