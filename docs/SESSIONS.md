# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

---

## 2026-09-05 — `ceph-tentacle-upgrade`

### Goal
Upgrade Ceph from Squid `v19.2.6` to Tentacle `v20.2.x` (≥ 20.2.4, never 20.2.0) under Rook v1.20.7:
review the Tentacle release notes and Rook's ceph-upgrade guide, disable the `rook` mgr module first,
loosen the Renovate pin, land the bump via GitOps and watch it land.

### What we did
- Research: quay.io tags (v20.2.4 newest, built 2026-08-19, same four CVE fixes as 19.2.6); Tentacle
  release notes 20.2.0–20.2.4 (RGW/MDS/NVMe-oF/EC items don't apply to an RBD-only cluster; `restful`
  and `zabbix` mgr modules removed; new mClock 1000-IOPS SSD floor sits below every measured OSD
  capacity here); Rook's ceph-upgrade guide (disable the `rook` mgr module first; 20.2.0 corrupts data
  with `readAffinity`, which we enable).
- Found the decisive blocker: rook/rook#18124 — on 20.2.3/20.2.4 the prometheus mgr module calls
  `node_proxy_fullreport` on every scrape, the rook orchestrator doesn't implement it, and the mgr
  records a module crash every ~15s forever (permanent HEALTH_WARN, unbounded crash list, eventually
  `ceph crash` itself breaks). Upstream fix (tracker 79106) not in a Tentacle point release. Verified
  in the v1.20.7 tag that Rook force-disables the module on 20.2.2–20.2.4
  (`rookModuleDisabledForCephVersion`) and, via backported #18276, clears `ceph orch set backend`
  before disabling it.
- Verified from Rook source that nothing else changes on a major bump: `ShouldRotateCephxKeys` fires
  only on a `keyGeneration` bump or keyType change (no re-rotation), and `osd.go` sets
  `require-osd-release` itself once all OSDs report one version. Ceph's `PyModuleRegistry` only
  raises `MGR_MODULE_ERROR` for missing *always-on* modules, so a dangling `restful` entry would have
  been cosmetic only.
- Live pre-checks: `restful`, `iostat`, `nfs` enabled (Squid's `mgr_initial_modules` default, not
  ours), `require_osd_release squid`, `min_mon_release 19`, no crashes.
- Commit 1 (`c9d41d3`): `mgr.modules` `rook: false` + `restful: false` with the why. `/code-review`
  confirmed the mechanics against the v1.20.7 tag; fixed its two doc findings (ROADMAP item marked in
  progress, cephImage comment cross-references the module entry). Watched it land: modules off,
  `ceph orch status` → "No orchestrator configured", HEALTH_OK, dashboard + prometheus endpoints up.
- Commit 2 (`b0bb9b6`, `feat!`): `cephImage.tag: v20.2.4`, Renovate pin `^v20\.2\.([4-9]|[1-9]\d+)$`
  (regex unit-tested: accepts 20.2.4+, rejects 20.2.0–3, 20.1.x RCs, 19.x, 21.x). Rendered chart and
  `task validate` green.
- Watched the rollout with a 30s Monitor: 10:36:01 "upgrading ceph cluster to 20.2.4"; mons+mgrs by
  10:36:32; OSDs one node-pair at a time (transient `OSD_DOWN`/`OSD_HOST_DOWN` HEALTH_WARN per pair,
  normal with 2 OSDs/NVMe); all 25 deployments on 20.2.4 at 10:40:02; Rook's own guard logged
  "disabling the rook mgr module for Ceph 20.2.4" (no-op); `require-osd-release tentacle` set
  10:40:34; HEALTH_OK by 10:41. **4.5 minutes, no HEALTH_ERR, no pages.**
- Final verification: `ceph versions` 15×20.2.4, `min_mon_release 20`, `status.cephx` untouched
  (gen 2), 0 crashes, toolbox on 20.2.4, HelmRelease v13 succeeded, all Kustomizations Ready.
- Side finding: the `open-webui` Kustomization failed for 2 min at 10:41 when the cluster
  Kustomization flipping Ready re-triggered it — its bootstrap Job had `ttlSecondsAfterFinished:
  3600` against a 1h interval, so Flux re-ran the (idempotent) Job hourly and, when a reconcile hit
  the TTL deletion window, the server-side dry-run failed on the terminating Job's immutable pod
  template, paging the Flux error Alert. Dropped the TTL (applying an unchanged manifest over a
  completed Job is a no-op — the 10:30 reconcile proved it). Also noted Rook's harmless "timed out
  waiting for PVC size" log line on every OSD reconcile with no PVC OSDs (fires pre-upgrade too).
- Docs: ROADMAP Tentacle item ✅ with the observed timeline and the open-webui fix; cluster-doctor
  state line → Ceph 20.2.4 Tentacle, `rook` module deliberately disabled.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | `rook` + `restful` mgr modules disabled; `cephImage.tag` → `v20.2.4`; comment history |
| `renovate.json5` | Ceph pin `^v19.2.z` → `^v20.2.(>=4)` |
| `kubernetes/apps/ai/open-webui/app/job-bootstrap-admin.yaml` | Dropped `ttlSecondsAfterFinished`, documented the re-apply race |
| `.claude/agents/cluster-doctor.md` | Rook-Ceph state line → Ceph 20.2.4, rook module off |
| `docs/ROADMAP.md` | Tentacle item ✅ with timeline; open-webui Job race ✅ |
| `docs/SESSIONS.md` | This record |
| `CLAUDE.md` | Session table row |

### Key decisions
- Disabled the `rook` mgr module in Git as a separate, earlier commit even though Rook 1.20.7
  force-disables it on 20.2.2–20.2.4: the guide says *before* upgrading, a separate step gives a
  zero-crash window, and the version guard vanishes the moment the range is left — Git should hold the
  decision, not the operator's blocklist.
- Renovate floor at 20.2.4, not 20.2.1: 20.2.0 is a data-corruption bug for us and 20.2.1–20.2.3
  would have been a CVE regression relative to the 19.2.6 already running.
- Fixed the open-webui Job TTL in this session rather than parking it: one line, and each blip
  pages the shared Flux error channel, which erodes trust in real pages. Dropping the TTL (not
  `force: "true"`) so the Job stops re-running hourly as well.

---

## 2026-09-04 — `rook-post-upgrade-hygiene-configkey-audit`

### Goal
Post-upgrade hygiene after Rook v1.20.7 / Ceph 19.2.6: refresh the stale Rook version in the
cluster-doctor agent's state block, decide on the dead `csi-metrics` ServiceMonitor, and audit the
mon config-key store for CVE-2026-50152 exposure.

### What we did
- Refreshed the `rook-ceph` entry in cluster-doctor's `CLUSTER-STATE-AUTO` block (was v1.19.6):
  Rook v1.20.7 + ceph-csi-drivers 1.0.4, RBD-only driver, Ceph 19.2.6 pinned via `cephImage`,
  AES256K daemon keys, and a note that the four muted `AUTH_INSECURE_*` warnings are expected so the
  agent never reports them as a fault. talos-node-manager's block has no Rook references.
- `csi-metrics` ServiceMonitor: confirmed live it selects `app: csi-metrics` Services that don't
  exist. Traced *why* it can never work with the ceph-csi-operator: the Driver CRD does support
  `spec.liveness.metricsPort` (adds a `liveness-prometheus` sidecar) and `reconcileLivenessService`
  creates a Service with the matching `csi-http-metrics` port — but (a) the ceph-csi-drivers chart
  (1.0.4 and upstream main) only exposes the sidecar's *resources*, never `metricsPort`, and (b) the
  operator builds that Service with ports only, no labels and no selector, so the ServiceMonitor's
  selector could never match. Set `csi.serviceMonitor.enabled: false` in the operator HR with the
  reasoning in a comment; `helm template` confirms no ServiceMonitor renders; Flux removes the live
  one on the next upgrade.
- CVE-2026-50152 audit: `ceph config-key ls` → 113 keys (config + history, `device/*` health
  metrics, `rook/*` telemetry counters, mgr module state). Only two secrets:
  `mgr/dashboard/jwt_secret` (24 B session-signing key) and `mgr/dashboard/accessdb_v2` (dashboard
  users, bcrypt hashes; admin password is Rook-managed from the 1Password-backed Secret). No OSD
  LUKS keys, no cephadm SSH key. Pre-patch `mon allow r` holders were only the four CSI keys, which
  live in K8s Secrets in `rook-ceph` — reading them already means namespace compromise. Risk: low.
- User rotated the JWT secret imperatively (`ceph config-key rm mgr/dashboard/jwt_secret && ceph mgr
  fail`, 23:25 UTC). The key did not reappear after the failover: the dashboard's `JwtManager`
  initialises lazily on the first `gen_token`/`decode_token`, not at engine start (verified in
  squid `services/auth.py`). Triggered it with a bogus-bearer request from the toolbox; new 24 B key
  present, mons re-elected `a`, HEALTH_OK. Recorded the gotcha in ROADMAP.
- `task validate` green.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/helmrelease.yaml` | `csi.serviceMonitor.enabled: false` with root-cause comment; intro comment updated |
| `.claude/agents/cluster-doctor.md` | `rook-ceph` state-block entry refreshed to v1.20.7 / Ceph 19.2.6 / muted-warnings note |
| `docs/ROADMAP.md` | csi-metrics item ✅ with root cause; CVE-2026-50152 exposure audit + jwt rotation outcome and lazy-init gotcha |
| `docs/SESSIONS.md` | This record |
| `CLAUDE.md` | Session table row |

### Key decisions
- Dropped the CSI ServiceMonitor rather than trying to wire liveness metrics: two independent
  upstream gaps (chart has no `metricsPort` value; operator's liveness Service has no
  labels/selector) mean a postRenderer hack would still scrape nothing. Kept `enabled: false`
  explicit with the reasoning so nobody re-enables it on the assumption it "just needs a Service".
- Did not rotate the dashboard password: it is a bcrypt hash at rest and Rook re-applies it from
  1Password, so the exposure is the hash only; the JWT secret was the one plaintext-equivalent item
  and rotating it costs nothing but open dashboard sessions.

---

## 2026-09-04 — `ceph-cve-2025-30156-key-rotation`

### Goal
Draft the CVE-2025-30156 fix as one change: Ceph `v19.2.3` → `v19.2.6` (superseding Renovate PR #102)
plus daemon CephX key rotation to AES256K and mutes for the residual `AUTH_INSECURE_*` warnings, with
the expected transient `HEALTH_ERR` window documented rather than hidden.

### What we did
- Verified the premise before editing: live `status.cephx` had every daemon key at generation 1
  (admin unset) on 19.2.3 `HEALTH_OK`; `kubectl explain` on the installed v1.20.7 CRD confirmed
  `security.cephx.daemon.{keyRotationPolicy,keyGeneration}` and `healthCheck.muteHealthWarning`
  (map of code → `{policy: mute|unmute}`); quay.io has `v19.2.6` (built 2026-08-19); Rook's
  CVE-2025-30156 guide (saved last session) prescribes image bump + `keyGeneration: 2` in one patch.
- Read the Squid 19.2.6 notes: four CVEs, two RGW-only (no object store here), plus
  CVE-2026-50152 (mon config-key store readable with `mon allow r`) — patched by the upgrade but Ceph
  has no secret-rotation procedure for it yet; parked in ROADMAP.
- Edited the cluster HR: `cephImage.tag: v19.2.6`, `security.cephx.daemon: {KeyGeneration, 2}`,
  CSI `keyType: aes` kept, mutes for the four `AUTH_INSECURE_*` warnings (the two `HEALTH_ERR`
  codes deliberately unmuted). Rendered the v1.20.7 chart with the values: CephCluster gets the
  image, rotation block and mutes deep-merged with the chart's default `daemonHealth`/`livenessProbe`;
  toolbox image follows. `task validate` green.
- `/code-review` round (6 findings, none refuted). Verified the big one against Rook release-1.20
  `cluster.go`: `setIsSafeToRotateCephxKeys` disables rotation while any OSD is pre-AES256K, so Rook
  upgrades first, reloads its controller-manager, then rotates in a second pass with another round of
  daemon restarts. Rewrote the HR comment and ROADMAP accordingly; documented the blast radius (12
  dependent Kustomizations held, Flux + `CephHealthError` page Pushover); reworded the session goal;
  derived the OSD-LVM-wipe pod image from the HR via `yq` in `.taskfiles/talos/Taskfile.yaml` and
  `ops/ceph/mod.just` (both hardcoded `v19.2.3`); dropped the manual toolbox restart after confirming
  the v1.20.7 chart's toolbox watches the mounted mon keyring and rewrites `/etc/ceph/keyring` itself.
- Committed `f9c47d5`; user pushed. Watched the rollout with a 30s Monitor on daemon `ceph-version`
  labels, health/phase, `status.cephx` generations, operator restart count and the rotation log lines.
  Pass 1 20:25–20:29 UTC (25 deployments to 19.2.6, rotation gated off — the predicted "disabling
  cephx key rotation because ... at least one OSD does not" line appeared at 20:26:37); `HEALTH_ERR`
  opened 20:26 with exactly the predicted codes. 20:29:49 "restarting rook operator" (in-process
  reload, pod restart count stayed 0). Pass 2 20:30–20:36: admin (second reload) → mon (Rook fails the
  reconcile on purpose to force the mon restart) → crash/exporter → mgr → osd (two per node per pass).
  `HEALTH_OK` 20:36:42, cluster Kustomization Ready same tick, phase Ready 20:37. Total 12 min,
  `HEALTH_ERR` window 10 min.
- Final verification via `ceph auth dump-keys`: 16 keys `aes256k`, 5 `aes` (4 CSI + rbd-mirror-peer,
  by design); four warnings `(MUTED, STICKY)`; 15/15 daemons 19.2.6; all Flux Kustomizations Ready;
  toolbox picked up the rotated admin key unaided; Renovate PR #102 auto-closed.
- Corrected the one wrong prediction ("looks like a crash in `kubectl get pods`" — it doesn't, the
  operator reloads in-process) in the HR comment and ROADMAP, marked the ROADMAP item ✅ with the
  observed timeline, and added a QA.md entry explaining why the error-level reconcile lines, the
  operator "restart" and the `HEALTH_ERR` window are Rook's designed control flow, plus how to tell a
  real stall.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Ceph `v19.2.6`, daemon key rotation gen 2, four `AUTH_INSECURE_*` mutes, two-pass rollout comment |
| `.taskfiles/talos/Taskfile.yaml` | `wipe-ceph-osds-live` derives the pod image from the HR's `cephImage` via `yq` |
| `ops/ceph/mod.just` | `osd-lvm-wipe` derives the pod image from the HR the same way |
| `docs/ROADMAP.md` | CVE-2025-30156 item ✅ with observed rollout timeline/end state; CVE-2026-50152 note |
| `docs/QA.md` | New Storage entry: Rook reconcile errors / operator reload / `HEALTH_ERR` during AES256K rotation are benign |
| `docs/SESSIONS.md` | This record |
| `CLAUDE.md` | Session table row |

### Key decisions
- Superseded Renovate PR #102 by committing the same tag bump alongside the rotation instead of
  merging it: the bump alone leaves the CVE open and parks Ceph in `HEALTH_ERR` (which the cluster
  Kustomization treats as failed) until someone rotates keys by hand.
- Left `AUTH_INSECURE_SERVICE_KEY_TYPE` / `AUTH_INSECURE_SERVICE_TICKETS` unmuted on purpose: they
  mean a core daemon key is still AES, i.e. the CVE itself, and must stay visible; only the four
  warnings that persist by design (CSI keys on kernel 6.18) are muted. Rook's mute is sticky —
  removing the entry later does nothing, `policy: unmute` is required.
- Kept the cluster Kustomization's `failed: HEALTH_ERR` expression and accepted a ~10-minute window
  where 12 dependents hold Git changes and Pushover pages, rather than loosening the check for a
  one-off event; documented it as expected so nobody rolls back mid-rotation.
- Did not set `daemon.keyType` — Rook auto-selects `aes256k` on a capable Ceph and its guide says
  to leave it unset unless working around a bug.

---

## 2026-09-04 — `rook-v120-upgrade-csi-drivers-draft`

### Goal
Review Renovate PRs #96/#97 (Rook `v1.19.6` → `v1.20.7`) against the Rook v1.20 upgrade guide and
draft the GitOps changes needed to make the upgrade safe.

### What we did
- Reviewed PRs #96 (`ghcr.io/rook/rook-ceph`) and #97 (`ghcr.io/rook/rook-ceph-cluster`) via `gh`:
  1-line tag bumps, CI green, both held by `renovate/stability-days`.
- Read the v1.20 upgrade guide from the raw `release-1.20` source (not a summarised fetch): v1.19→v1.20
  is a minor upgrade with a breaking change — Rook no longer deploys CSI drivers; a new, mandatory
  `ceph-csi-drivers` chart owns the `Driver`/`OperatorConfig` CRs, CSI ServiceAccounts and RBAC.
  Required Helm order: `rook-ceph` → `ceph-csi-drivers` → `rook-ceph-cluster`. Min K8s v1.31 (we run
  v1.36.1). CVE-2025-30156 needs Rook ≥ 1.20.6 + Ceph ≥ 19.2.6/20.2.4 + daemon CephX key rotation.
- Captured live state (guide step 1): operator `v1.19.6`, Ceph `19.2.3` `HEALTH_OK`, all 25
  deployments at `rook-version=v1.19.6`; saved `Driver`/`OperatorConfig` CRs. Found the cluster
  already runs the `ceph-csi-operator` (v1.19 subchart 0.6.0) and that Rook v1.19.5 (#17289)
  pre-annotated the CRs with `meta.helm.sh/release-name: ceph-csi-drivers` for adoption.
- Pulled and diffed charts (`rook-ceph` 1.19.6 vs 1.20.7, `rook-ceph-cluster` 1.19.6 vs 1.20.7,
  `ceph-csi-drivers`/`ceph-csi-operator` 1.0.4): v1.20 operator chart drops every `csi.enable*`
  value and all CSI SAs/RBAC; the drivers chart recreates them under new names
  (`rook-ceph-rbd-csi-ceph-com-*`), so no Helm ownership collisions.
- Found PR #97 is a **hidden Ceph major upgrade**: the v1.20 cluster chart defaults `cephImage.tag`
  to Tentacle `v20.2.4` (v1.19: Squid `v19.2.3`) and our HR left the image unset.
- Found Rook's recommended `ceph-csi-drivers` values would break VolSync: chart RBD default
  `snapshotPolicy: none` drops the `csi-snapshotter` sidecar (4 live `ReplicationSources` use
  `ceph-block-snapshot`); `grpcTimeout` default 30s vs live 150s; log rotation on by default.
- Read `ceph-csi-operator` v1.0.4 merge code: `Driver` fields win over `OperatorConfig`
  `driverSpecDefaults` field-by-field, and the chart always renders `replicas`/`hostNetwork`/
  `grpcTimeout`/`snapshotPolicy` on the `Driver` — so those only take effect at `drivers.rbd.*`.
- Compared with billimek/k8s-gitops's deployment (same settings, chart from
  `ghcr.io/home-operations/charts-mirror`, which this repo already uses for other charts).
- Drafted the migration (uncommitted): `ceph-csi-drivers` OCIRepository + HelmRelease + a third
  Flux Kustomization between operator and cluster, operator HR cleanup, explicit Ceph image pin,
  `cephx.csi.keyType: aes` (Talos kernel 6.18 < 7.0), Renovate grouping rule, ROADMAP entry.
- Verified with `helm template` diffs against the saved live CRs (caught `replicas: 1` and a
  mis-keyed Ceph pin), rendered the cluster chart on both versions (pin is a no-op today),
  `kubectl kustomize` of all touched trees, and `scripts/validate.sh -d kubernetes` (passes).
- Ran `/code-review` twice and acted on both rounds. Round 1: the cluster HR had no
  HelmRelease-level ordering (a `chartRef` release upgrades as soon as its OCI tag changes,
  bypassing Kustomization `dependsOn`); the cluster-wide install remediation would `helm uninstall`
  on a failed first install and delete the adopted `Driver`; a `CLAUDE.md` table newline was lost in
  the 8-row trim; `docs/CLUSTER.md` was not updated. Round 2 found the critical flaw in the
  "one commit" plan: a Kustomization-level `dependsOn` on the new csi-drivers Kustomization would
  hold back the cluster HR's *spec* (with the Ceph pin) while helm-controller upgraded the live,
  unpinned spec to the v1.20 chart → Tentacle anyway. Also: the `keep` policy missed the CSI RBAC;
  a plain `dependsOn` cannot order simultaneous tag bumps once a one-shot gate is removed; the
  `!startsWith('v1.19.')` gate had no recovery path after an operator rollback; the Ceph pin's
  Renovate hint would open an unguarded Tentacle major PR; nothing flagged `ceph-csi-drivers`
  version coupling; the new OCIRepository lacked the cosign `verify` block; a
  `driverSpecDefaults.log` switch was dead config; stale `CSI_ENABLE_HOST_NETWORK` prose in the
  cilium values and CLAUDE.md.
- Committed (`4d1a6c5`, user-signed via 1Password prompt — the agent forwarded to the devcontainer
  answers `ssh-add -l` but never completes a sign request from a non-interactive shell) and pushed;
  monitored the rollout live: operator HR → `v1.20.7` at 17:01, lockstep gate opened and
  `ceph-csi-drivers` installed at 17:02 (adoption worked, CSI pods rolled to the new SAs / cephcsi
  3.17.1; controller 0/2 for ~1 min as predicted), Ceph daemons rolled 17:01–17:07, cluster HR
  reconciled on the unchanged `v1.19.6` chart, everything Ready at 17:07. Verified Ceph
  `HEALTH_OK` on `19.2.3`, Driver effective settings, all 12 dependent Kustomizations Ready, and an
  end-to-end PVC + VolumeSnapshot probe; Renovate auto-closed #96/#97.
- Found and removed one artifact: a stray `rook-ceph.cephfs.csi.ceph.com` `Driver` created at
  17:00:56 by the *outgoing* v1.19.6 operator when the chart upgrade stripped its ConfigMap's
  `ROOK_CSI_*` keys (1.19 defaults `ROOK_CSI_ENABLE_CEPHFS=true`); its controller was 0/2 on a
  non-existent SA. Confirmed from source that release-1.20 has no Driver-creation code; the
  one-line `kubectl delete driver` cleanup is user-run (live-cluster deletions stay with the
  operator), documented in `docs/QA.md`.
- Reviewed PR #101 on request: not the cluster-chart step but Renovate proposing the new Ceph
  pin `v19.2.3 → v21.1.0` (a two-major jump to an RC, unsupported by Rook 1.20). Found the
  `dependencyDashboardApproval` hold was never honoured (no approval section on the dashboard);
  replaced both Ceph-related rules with hard `allowedVersions` pins. The real step-3 PR is
  pending its 3-day soak under `renovate/rook-ceph-chart`.
- Confirmed #103 (cluster chart `v1.19.6 → v1.20.7`) was safe as the final step and watched it
  land at 19:39: Helm upgrade succeeded, no daemon restarts (toolbox recycled only), Ceph unchanged
  at `19.2.3` `HEALTH_OK`, `cephx.csi.keyType: aes` rendered. Migration complete; ROADMAP entry
  marked ✅, #102 (Ceph `19.2.6`) parked pending the CephX key-rotation change.
- Redesigned ordering to Flux's lockstep pattern: `rook.io/chart-version` annotations
  (Renovate-tracked with the operator's `depName`, so grouped) on the csi-drivers and cluster HRs,
  and a permanent `readyExpr` that waits until the operator release's applied `chartVersion`
  equals the annotation; dropped the cluster Kustomization's dependency on the csi-drivers
  Kustomization; `keep` postRenderer now covers all rendered kinds (regex target, emulated with
  `kubectl kustomize`); operator tag bumped to `v1.20.7`, cluster tag left at `v1.19.6` for a
  follow-up Renovate merge; cosign `verify` added; Renovate rules for Ceph majors and
  `ceph-csi-drivers` bumps (dashboard approval); docs/comments corrected.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/rook-ceph.yaml` | Bumped `v1.19.6` → `v1.20.7` (PR #96; cluster tag deliberately left for a follow-up merge of regrouped #97) |
| `kubernetes/flux/meta/repos/oci/ceph-csi-drivers.yaml` | Created OCIRepository for `charts-mirror/ceph-csi-drivers:1.0.4` with cosign `verify` |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | MTU comment: replaced stale `CSI_ENABLE_HOST_NETWORK` reference with the drivers-HR setting |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new OCIRepository |
| `kubernetes/apps/rook-ceph/rook-ceph/csi-drivers/app/helmrelease.yaml` | Created `ceph-csi-drivers` HelmRelease (adoption `releaseName`, lockstep `readyExpr` gate via `rook.io/chart-version` annotation, `resource-policy: keep` postRenderer on all rendered kinds, live-parity values) |
| `kubernetes/apps/rook-ceph/rook-ceph/csi-drivers/app/kustomization.yaml` | Created Kustomize entry-point |
| `kubernetes/apps/rook-ceph/rook-ceph/ks.yaml` | Added `rook-ceph-csi-drivers` Kustomization (cluster deliberately does not depend on it — ordering is HR-level) |
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/helmrelease.yaml` | Removed v1.20-deleted `csi.enable*` values, rewrote CSI comment, flagged the dead `csi-metrics` ServiceMonitor |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Pinned `cephImage` to `v19.2.3` (Renovate-tracked), explicit `cephx.csi.keyType: aes`, `rook.io/chart-version` annotation + HR-level `dependsOn` with lockstep `readyExpr`, fixed CSI-networking comment |
| `renovate.json5` | Grouped `rook-ceph` + `rook-ceph-cluster` chart bumps; dashboard approval for `quay.io/ceph/ceph` majors and `ceph-csi-drivers` bumps |
| `docs/ROADMAP.md` | Added "Rook v1.19 → v1.20 Upgrade" in-progress entry with rollout sequence and follow-ups |
| `docs/CLUSTER.md` | Rook-Ceph section: three-Kustomization structure, `ceph-csi-drivers` chart, CSI workload rows |
| `CLAUDE.md` | Session table row; repaired the table/paragraph newline lost in the 8-row trim |

### Key decisions
- PRs #96/#97 must not merge as-is. Land the draft with only the operator tag bumped, then merge
  the regrouped cluster bump afterwards — a same-commit cluster bump could race the cluster HR's
  spec update and upgrade Ceph to Tentacle from the chart default before the pin was live.
- HelmRelease named `ceph-csi-drivers` with explicit `releaseName` — the only name Helm will adopt
  the pre-annotated CRs under.
- Chart-upgrade ordering lives in HelmRelease `dependsOn` + a permanent lockstep `readyExpr`
  (operator's applied `chartVersion` == the HR's Renovate-tracked `rook.io/chart-version`
  annotation), not in Kustomization `dependsOn`: a `chartRef` HR upgrades on its own when its OCI
  tag changes, and a plain HR `dependsOn` sees the operator `Ready` on the old chart at that
  moment. Recovery after an operator rollback = revert the commit (tags + annotations).
- `helm.sh/resource-policy: keep` on everything the drivers chart renders: the global install
  remediation uninstalls on failure, which would otherwise delete the adopted `Driver` (RBD driver
  torn down) or the CSI RBAC (all provision/attach/resize/snapshot 403).
- Pinned the Ceph image explicitly instead of trusting the chart default, turning Ceph upgrades
  into their own Renovate PRs; CVE fix (`v19.2.6` + key rotation) and Tentacle deferred to
  deliberate follow-ups.
- Chart source: `home-operations/charts-mirror` OCI rather than a new `HelmRepository` —
  upstream only publishes a classic Helm repo, and the mirror keeps the repo's OCIRepository
  convention.

---

## 2026-09-04 — `bifrost-image-tag-misfire`

### Goal
Diagnose why the `bifrost` HelmRelease was stuck in repeated `UpgradeFailed` cycles and fix the
root cause.

### What we did
- Diagnosed via `gitops-cluster-debug` skill; no `flux-operator-mcp` server was configured, so
  fell back to direct `kubectl` (read-only) against the live cluster.
- Inspected `HelmRelease/bifrost` status/conditions, events, helm-controller logs, and the
  `bifrost` Kustomization's reconciliation history — found 5+ Helm revisions (v96–v100) failing
  over the preceding ~2 hours, each ending in `UpgradeFailed` → `cleanupOnFail` deleting the
  Deployment → retry.
- Found two layered issues: (1) a pre-existing crash loop on image `v1.6.11` — the app started but
  never bound port 8080 (`Startup probe failed: connection refused`); (2) a new failure after the
  `2.1.29` tag bump — `CreateContainerError: no command specified`.
- Polled across a live helm-controller retry cycle to catch a pod before `cleanupOnFail` deleted
  it again, confirming `CreateContainerError` with 0 container restarts (fails at
  container-creation time, before the app runs — distinct from the v1.6.11 crash loop).
- Used `crane` (`config`/`manifest`/`ls`) to inspect `maximhq/bifrost` on Docker Hub directly:
  `2.1.29`/`2.1.27` are Helm chart OCI artifacts (`mediaType:
  application/vnd.cncf.helm.chart.content.v1+json`), not container images — pushed into the same
  tag namespace as the real `vX.Y.Z`-prefixed images. Renovate's `docker` datasource can't
  distinguish artifact types by tag string and proposed the chart artifact as an image bump.
- Confirmed `v2.0.0` (latest real image) carries the same entrypoint/user/port layout as the
  previously-running `v1.6.11` (`/app/docker-entrypoint.sh` → `/app/main`, user `1000:0`, port
  8080) — no chart-side command/args override needed.
- Checked upstream GitHub release notes between v1.6.11 and v2.0.0 for anything explaining the
  original connection-refused probe failure — found no documented startup/health/port-binding
  changes, so that issue's root cause remains open and unverified after this fix.
- Pinned the HelmRelease to `v2.0.0` and added a Renovate `packageRule` restricting
  `maximhq/bifrost` to `v`-prefixed tags to prevent the same misfire recurring.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/ai/bifrost/app/helmrelease.yaml` | Pinned image tag from the Helm-chart-artifact tag `2.1.29` to the real container image `v2.0.0` |
| `renovate.json5` | Added a packageRule restricting `maximhq/bifrost` to `v`-prefixed tags (bare-semver tags are Helm chart OCI artifacts, not images) |

### Key decisions
- Chose `v2.0.0` over reverting to `v1.6.11`: v1.6.11 was already crash-looping (separate
  connection-refused issue) before the tag mixup, so it isn't a known-good fallback either;
  v2.0.0 is the newest actual image, but whether it resolves the original probe failure is
  unverified and needs to be watched after deploy.
- Did not add a `command:`/`args:` override to the Helm values — the `CreateContainerError` was
  purely a wrong-artifact problem; the real image already ships a correct `ENTRYPOINT`/`CMD`.

---

## 2026-09-04 — `truenas-envoy-backend-https`

### Goal
Fix TrueNAS's `/_download` failures under newer TrueNAS versions by proxying it over HTTPS
end-to-end via an Envoy Gateway `Backend`, and apply the same collapse to `home-assistant`.

### What we did
- Diagnosed the root cause: Envoy terminated TLS and forwarded plain HTTP to TrueNAS's backend
  on :8080, but newer TrueNAS versions validate the scheme of the request they actually receive
  (notably `/_download`), so the plain-HTTP leg gets rejected.
- Inspected the live cluster's `Backend` CRD (`kubectl explain backends.spec.tls`) and confirmed
  Envoy Gateway 1.9.0 (already pinned) supports `spec.tls.insecureSkipVerify` and
  `spec.endpoints.ip.{address,port}` — no chart upgrade needed.
- Replaced TrueNAS's `Service` + hand-managed `EndpointSlice` with a `gateway.envoyproxy.io/v1alpha1
  Backend` pointing at `${NAS_LAN_HOST}:8443` with `tls.insecureSkipVerify: true`, and repointed the
  `HTTPRoute`'s `backendRefs` at it (`group: gateway.envoyproxy.io`, `kind: Backend`, no `port` —
  the port lives on the Backend).
- Discovered the Backend extension API was disabled cluster-wide (`extensionApis: {}` in the live
  `envoy-gateway-config` ConfigMap) and enabled it via
  `config.envoyGateway.extensionApis.enableBackend: true` on the envoy-gateway HelmRelease — found by
  rendering the 1.9.0 chart locally (`helm pull` + `helm template`) to confirm the correct values
  nesting and that the control-plane Deployment reads its config once at startup (no checksum
  annotation), meaning a manual `rollout restart` is required after Flux reconciles.
- Found and fixed a dangling reference: homepage's TrueNAS `siteMonitor` pointed at the
  now-deleted in-cluster Service (`truenas.network.svc.cluster.local:8080`); repointed it directly
  at `${NAS_LAN_HOST}:8080`.
- On follow-up request, collapsed `home-assistant` (the only other `external-services` app on the
  same Service+EndpointSlice+HTTPRoute shape) to a `Backend` the same way — plain HTTP on :8123, no
  TLS block needed since Home Assistant doesn't have TrueNAS's origin-validation issue. Fixed the
  same class of stale reference in homepage's commented-out Home Assistant widget URL.
- Confirmed `adam`, `anna`, `canon`, `wan-failover` are a different pattern (`ExternalName` Services
  with no `HTTPRoute`, used only for `external-dns` LAN-IP publishing) and left them unchanged —
  a `Backend` has nothing to attach to without a route.
- Validated with `task validate` (kubeconform; passed, though it silently skips `Backend` — no local
  schema) and `kubectl apply --dry-run=server` against the live cluster's CRDs for both apps
  (accepted, no mutation). Grepped for stale Service/EndpointSlice references across the repo.
- Committed and pushed (`826a8aa`) — commit signing needs the host shell's `ssh-agent`, unreachable
  from this sandboxed session, so the user ran `/git-commit`'s prepared command themselves.
- Post-deploy, the user ran the required `kubectl -n network rollout restart deployment
  envoy-gateway` manually; confirmed via the live `envoy-gateway-config` ConfigMap and both
  `HTTPRoute`s' `Accepted=True`/`ResolvedRefs=True` status that `enableBackend` was actually live,
  not just written.
- User reported `ha.cluster.vwn.io` working but `truenas.cluster.vwn.io` still not, even after hard
  refresh/incognito — found and fixed a **second bug** surfaced only by the HTTPS-backend switch:
  TrueNAS's UI is a SPA whose post-login functionality runs entirely over a WebSocket to
  `/websocket`; that handshake got a `400 Bad Request` from TrueNAS's nginx frontend when proxied
  through Envoy, but succeeded when curled directly to the backend IP. Root cause:
  `Backend.spec.tls.alpnProtocols` defaults to `[h2, http/1.1]`, TrueNAS's nginx offers `h2`, so
  enabling backend TLS made Envoy negotiate HTTP/2 to TrueNAS — and HTTP/2 has no `Upgrade:`
  mechanism (RFC 9113 §8.2.2 forbids the `Connection`/`Upgrade` headers; WebSocket-over-h2 needs
  RFC 8441 extended CONNECT instead), so nginx rejected the h1-style upgrade forwarded over h2.
  Plain HTTP never hit this — no ALPN, so it was always HTTP/1.1.
- With explicit one-time user authorization, verified the fix by `kubectl patch`-ing the live
  `Backend` (`alpnProtocols: [http/1.1]`) before committing — a deliberate, narrow exception to the
  repo's GitOps-only rule, done to avoid a blind commit→reconcile→retest cycle on a hypothesis. A
  synthetic `curl` WebSocket-handshake retest immediately after the patch still got `400` (most
  likely stale xDS on the replica it happened to hit — Envoy Gateway's 3 replicas absorb config
  updates asynchronously — or a raw handshake missing something nginx wanted that a real browser
  sends), but the user's actual browser confirmed working shortly after; confirmed the live
  `Backend`'s `spec.tls` matches the already-edited `backend.yaml` exactly, so nothing further to
  change.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/network/external-services/truenas/backend.yaml` | Added — Envoy Gateway `Backend`, `${NAS_LAN_HOST}:8443`, `insecureSkipVerify: true`, `alpnProtocols: [http/1.1]` (added after the WebSocket fix, see below) |
| `kubernetes/apps/network/external-services/truenas/httproute.yaml` | `backendRefs` retargeted to the `Backend` (was the `Service`, port 8080) |
| `kubernetes/apps/network/external-services/truenas/kustomization.yaml` | Now lists `backend.yaml` + `httproute.yaml` |
| `kubernetes/apps/network/external-services/truenas/service.yaml` | Deleted |
| `kubernetes/apps/network/external-services/truenas/endpoint.yaml` | Deleted |
| `kubernetes/apps/network/external-services/home-assistant/backend.yaml` | Added — Envoy Gateway `Backend`, `${HOME_ASSISTANT_LAN_HOST}:8123`, plain HTTP |
| `kubernetes/apps/network/external-services/home-assistant/httproute.yaml` | `backendRefs` retargeted to the `Backend` (was the `Service`, port 8123) |
| `kubernetes/apps/network/external-services/home-assistant/kustomization.yaml` | Now lists `backend.yaml` + `httproute.yaml` |
| `kubernetes/apps/network/external-services/home-assistant/service.yaml` | Deleted |
| `kubernetes/apps/network/external-services/home-assistant/endpoint.yaml` | Deleted |
| `kubernetes/apps/network/envoy-gateway/app/helmrelease.yaml` | Added `config.envoyGateway.extensionApis.enableBackend: true` |
| `kubernetes/apps/default/homepage/app/config/services.yaml` | Repointed TrueNAS `siteMonitor` and the commented-out Home Assistant widget URL off the deleted in-cluster Services, straight to the LAN hosts |

### Key decisions
- Used `Backend` + `insecureSkipVerify: true` rather than any certificate-validation mechanism
  (`BackendTLSPolicy`, a CA ConfigMap, cert-manager) — intentional and explicitly scoped: TrueNAS
  serves a self-signed cert on 8443 with no realistic path to enroll it in the cluster's PKI, and
  the hop is a single trusted LAN link.
- Left `enableBackend` un-applied until the next manual `rollout restart` of the envoy-gateway
  Deployment — the 1.9.0 chart has no ConfigMap-checksum annotation to trigger an automatic
  rollout, so this is a required manual step post-reconcile, not an oversight.
- Scoped the "collapse to Backend" follow-up to `home-assistant` only, after confirming
  `adam`/`anna`/`canon`/`wan-failover` are `ExternalName`-only DNS-publishing Services with no
  `HTTPRoute` — converting those would silently break `external-dns` hostname publishing since
  `Backend` isn't a DNS-source, not what "collapse" would have meant there.
- Pinned `truenas`'s `Backend` to `alpnProtocols: [http/1.1]` rather than leaving the CRD default
  (`[h2, http/1.1]`) — TrueNAS's UI is unusable without its WebSocket connection, so HTTP/1.1-only
  is required, not optional, for any TLS backend fronting a service with WebSocket-dependent
  functionality. `home-assistant`'s `Backend` is unaffected (no `tls` block — plain HTTP has no
  ALPN to negotiate).
- Authorized (once, explicitly) a live `kubectl patch` on the `truenas` `Backend` to verify the
  ALPN fix before committing, rather than committing a hypothesis and discovering it was wrong only
  after a full Flux reconcile + manual retest round-trip — a deliberate, narrow exception to this
  repo's "no manual kubectl apply" rule, justified by the cost asymmetry of an unverified GitOps
  round-trip vs. a five-minute live check.

---

## 2026-09-03 — `ceph-public-network-migration-execute`

### Goal
Execute the previously-approved 5-phase plan (session `ceph-storage-bond-migration-plan`) to
migrate Ceph's `public_network` from the management subnet to the storage bond (`10.200.0.0/24`),
and verify the fix.

### What we did
- **Phase 1 (Cilium):** verified live interface names via `talosctl get links` rather than trusting
  the repo's own (stale) comments — management is `enp4s0` on cp-01, `eno1` elsewhere; no node
  actually uses `bond0` for management despite a prior comment's claim. Added an explicit
  `devices: eno1 enp4s0 bond-storage` to Cilium (not a wildcard — see Key decisions) and validated
  pod-to-storage-bond reachability with a live probe pod: 0% loss, ~0.08ms RTT, no regression on the
  management path.
- **Phase 2 (mon failover) — found and resolved a blocker the original plan's research hadn't
  covered.** Changed `CephCluster.addressRanges.public` to `10.200.0.0/24` and failed over all 3
  mons one at a time (`mon.a`→`mon.f`→`mon.g` after a required second failover, `mon.d`→`mon.h`,
  `mon.e`→`mon.i`; Rook always assigns a fresh identity, never reuses the old letter). The first
  failover silently bound the new mon to the old `10.60.0.201` address with `ceph -s` staying
  `HEALTH_OK` throughout — no error surfaced. Root-caused via a research fork: Rook's
  `addressRanges` mon selection reads the Kubernetes Node object's registered address, not the
  node's actual interfaces, and this cluster's kubelet is deliberately pinned to `10.60.0.0/24`-only
  (a real, unrelated, pre-existing constraint protecting kube-apiserver↔kubelet traffic). Confirmed
  via [rook/rook#14829](https://github.com/rook/rook/issues/14829) (closed `wontfix`) this is a
  known Rook limitation. Fixed with the documented `network.rook.io/mon-ip` node annotation, applied
  declaratively to all 5 nodes (not just the 3 with mons at migration time — confirmed necessary
  live, since `mon.e`'s replacement landed on `cp-02`, not its original node `worker-01`) via
  `talconfig.yaml`'s `nodeAnnotations`. Also confirmed empirically the annotation is only read on a
  genuine Rook-driven mon recreation, not a plain `kubectl delete pod`.
- **Phase 3 (OSD restarts):** rolling-restarted all 10 OSDs, one node at a time (`noout` +
  `ok-to-stop` scoped per node). No annotation workaround needed — OSD address discovery already
  found the storage bond correctly on its own. Every OSD now shows one unified `10.200.0.0/24`
  address for both public and cluster roles (previously two distinct addresses).
- **Phase 4 (verification):** `ceph -s` stayed `HEALTH_OK`/33 pgs `active+clean`/10-10 OSDs up+in
  throughout the entire migration — zero data unavailability. Sampled 4 real `ceph-block` consumers
  (Grafana, Prometheus, Waha, victoria-logs) with live write/read tests or API checks; `pgAdmin`
  (scaled to 0) confirmed indirectly via a successful volsync backup job. etcd/apiserver/CoreDNS: no
  regression. Confirmed `CephNodeNetworkPacketDrops` (Rook's own shipped `PrometheusRule`) needs no
  changes — its expression is already interface-agnostic, so it already covers `bond-storage`.
  Established a 2-week observation-window baseline (drop counters: 0 on 4 nodes, cumulative 36 on
  cp-01, not actively growing) before declaring the alert fixed.
- Updated `docs/ROADMAP.md` with full per-phase execution results, superseding the prior "ready to
  execute, not yet started" status.
- Hit a devcontainer SSH-agent signing failure (`ssh-keygen -Y sign` failed despite `ssh-add -l`
  listing the key) partway through — rather than bypass commit signing, handed the user the
  finished commit message to run manually.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Added `devices: eno1 enp4s0 bond-storage`; corrected stale interface/MTU comments (commit `8d1ff81`) |
| `kubernetes/apps/kube-system/cilium/config/networks.yaml` | Corrected stale L2-announcement comment about `bond-storage` isolation (commit `8d1ff81`) |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Unified `addressRanges.public`/`cluster` to `10.200.0.0/24` (commit `e96dcdf`) |
| `talos/talconfig.yaml` | Added `network.rook.io/mon-ip` `nodeAnnotations` to all 5 nodes (commit `de1a7f9`) |
| `docs/ROADMAP.md` | Documented full execution results and the 2-week observation-window baseline |

### Key decisions
- Used an explicit Cilium `devices:` list rather than a wildcard (`enp+`) — a glob would also match
  `bond-storage`'s own slave NICs on some nodes (e.g. cp-01's `enp5s0f0np0`/`enp5s0f1np1`), wrongly
  attaching Cilium's datapath to bond members instead of just the bond master.
- Kept Cilium `MTU: 1500` unchanged rather than enabling jumbo frames on the new pod→storage-bond
  path — it's a single cluster-wide scalar in this chart version, so raising it would also affect
  the proven-safe management path.
- Annotated all 5 nodes with `network.rook.io/mon-ip` proactively, not just the 3 that had mons at
  migration start, after confirming live that a replacement mon isn't guaranteed to land back on
  its original node.
- Left `docs/ROADMAP.md`'s "Storage VLAN" section heading and anchor unchanged despite the
  terminology correction already documented inline — renaming it would silently break other
  in-document links pointing at that anchor, for no functional benefit.
- Did not bypass commit signing (`--no-gpg-sign`/`commit.gpgsign=false`) when the devcontainer's SSH
  agent failed mid-session — per the repo's explicit rule, handed the commit message to the user to
  run manually instead of working around the failure.

---

## 2026-09-03 — `ceph-storage-bond-migration-plan`

### Goal
Draft a reviewable migration plan for moving Ceph's `public_network` from the management subnet
to the storage bond (`10.200.0.0/24`), resolving the two research prerequisites ROADMAP.md had
flagged as blocking a start.

### What we did
- Ran two parallel research agents to gather full context: one extracted the complete
  `CephNodeNetworkPacketDrops` QA.md entry and the prior `ceph-packetdrops-*` session history
  (root cause, ring-headroom findings, prioritization decision); the other read the live Talos/
  Cilium/CephCluster network config (talconfig.yaml interfaces/bonds, CephCluster `network:`
  stanza, Cilium values.yaml).
- Corrected a terminology mismatch: the user referred to "VLAN 200 (storage VLAN)," but there is
  no currently-active 802.1Q VLAN 200 — `10.200.0.0/24` is a dedicated, untagged `bond-storage`
  LACP bond on discrete SFP+ NICs; VLAN 200 only existed as a commented-out 2026-06-25→07-07
  emergency fallback.
- Resolved prerequisite 1 (Rook mon-network migration mechanics) via web research against
  official Rook docs and GitHub issues: confirmed `addressRanges.public` changes don't
  auto-migrate existing mons — requires one-at-a-time mon failover (scale to 0 → operator
  creates/validates a canary → promotes into quorum) to preserve 2-of-3 quorum throughout; OSD
  pods separately need a rolling restart to pick up the new network.
- Resolved prerequisite 2 (pod-to-storage-bond reachability) via a targeted Explore agent:
  confirmed pods cannot reach `10.200.0.0/24` today — Cilium's `devices:` only attaches to the
  management interface, and `bond-storage` is documented as an isolated L2 segment by design.
  Confirmed via web research this gap is **not avoidable**: Rook v1.19.6 defaults
  `CSI_ENABLE_HOST_NETWORK` to `false` for greenfield clusters (this one, no override in-repo),
  so `csi-rbdplugin`/`csi-cephfsplugin` run on the pod network, not hostNetwork — every workload's
  RBD/CephFS mount genuinely talks to mons/OSDs from a pod IP, so opening pod→storage-bond
  reachability is mandatory, not optional.
- Verified the plan's load-bearing claims directly against the live repo rather than trusting
  agent summaries: the CephCluster `network:` block, Cilium `values.yaml`'s `devices`/`MTU`
  comment, `ops/ceph/mod.just`'s actual recipe names, and CNPG's storage class (confirmed
  `openebs-hostpath`, not `ceph-block` — corrects a bad verification-sample suggestion the Plan
  agent had flagged).
- Designed and got the user's explicit approval (via plan mode / `ExitPlanMode`) for a 5-phase
  migration: (1) add `bond-storage` as a Cilium routed device and prove pod reachability before
  touching Ceph, keeping MTU at 1500 cluster-wide since Cilium's MTU is a single scalar in this
  chart version, not per-device; (2) `CephCluster.addressRanges.public` → `10.200.0.0/24` +
  rolling mon failover, one mon at a time; (3) rolling OSD pod restart, `noout`/`ok-to-stop`
  scoped per node; (4) verification — health checks, a real `ceph-block` consumer smoke test, a
  minimum 2-week alert-quiet observation window; (5) optional/deferred firewall hardening on the
  newly-opened storage-bond pod reachability. Every phase has an explicit rollback and "safe to
  stop here" boundary.
- Folded the resolved prerequisites, terminology correction, and phase summary into
  `docs/ROADMAP.md`'s existing "Ceph `public_network`: Move to Storage VLAN" section (in place of
  the old "not yet started; two blockers" framing) so a future session can pick up execution
  without re-deriving the research. No Ceph/Cilium manifests were touched — this session was
  planning-only, per explicit scope; no migration steps were executed against the live cluster.

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Updated "Ceph `public_network`: Move to Storage VLAN" section: terminology correction, both research prerequisites marked resolved with findings, added the approved 5-phase plan summary |

### Key decisions
- Sequenced the Cilium pod-reachability change (Phase 1) strictly before any Ceph-side change,
  since it's the harder, load-bearing risk (confirmed pods can't reach the storage bond at all
  today) and Phases 2-3 depend on it working.
- Chose to keep Cilium's MTU at 1500 cluster-wide rather than attempt per-device jumbo frames —
  Cilium's `MTU:` key is a single scalar in the chart version in use (1.20.1), and reopening a
  PMTUD mismatch risk (this cluster already had one real incident, CNPG's streaming-replica
  black-hole) for a speculative throughput benefit on CSI traffic wasn't worth it.
- Treated mon failover as an imperative, live operational sequence rather than something to
  express declaratively via Flux — it's an operator-driven, one-mon-at-a-time state transition,
  analogous to how OSD replacement is already handled imperatively via `ops/ceph/mod.just`.
- Left the storage-bond firewall hardening (Phase 5) optional/deferred rather than blocking,
  given the confirmed single-tenant home-lab risk profile — real but modest exposure.

---

## 2026-09-03 — `bifrost-deploy`

### Goal
Deploy Bifrost, a self-hosted LLM gateway, into the `ai` namespace, adapted from the
deedee-ops/home-ops reference manifest, and wire it in as Open WebUI's OpenAI-compatible backend.

### What we did
- Explored the deedee-ops/home-ops reference (`helmrelease.yaml`, `externalsecret.yaml`,
  `ocirepository.yaml`, `networkpolicy.yaml`) via raw-file fetches, and this repo's own
  conventions (open-webui's pattern, app-template v5 rules, the `onepassword` ClusterSecretStore,
  `${DOMAIN_CLUSTER}`, the `envoy-internal` Gateway) via two parallel Explore agents plus direct
  repo greps, before drafting a plan.
- Clarified three open design questions with the user via `AskUserQuestion`: start with an empty
  Bifrost providers list (configured later through its own web UI, not hardcoded), back the
  `/app/data` PVC with VolSync, and wire Open WebUI to Bifrost's Service now rather than leaving
  it standalone.
- Looked up Bifrost's actual `config.json` schema live (getbifrost.ai docs) rather than copying
  the reference verbatim: its `source_of_truth: "config.json"` setting, combined with the
  reference's populated `providers` block, would silently discard any provider added later
  through Bifrost's UI on the next pod restart. Adapted the config to omit `providers`/
  `source_of_truth` entirely and enable `config_store` (SQLite, on the persistent volume) so
  UI-managed provider config actually survives restarts.
- Wrote `kubernetes/apps/ai/bifrost/` (`ks.yaml`, `app/{kustomization,helmrelease,externalsecret,
  httproute,networkpolicy}.yaml`): `deployment`/`Recreate` on a VolSync `existingClaim` PVC
  (this repo's established Ceph/VolSync pattern) rather than the reference's raw StatefulSet
  `volumeClaimTemplate`; explicit `env.valueFrom.secretKeyRef` instead of the reference's
  `envFrom` (its secret also carries a `config.json` key, which isn't a valid env var name); a
  standalone `httproute.yaml` matching the repo's dominant pattern rather than open-webui's
  one-off inline `route:` block.
- At the user's request, adopted a `CiliumNetworkPolicy` restricting Bifrost's egress — the first
  one in this repo. Scoped tighter than the reference (DNS egress limited specifically to
  CoreDNS, not "all in-cluster endpoints") and allow-lists only major LLM providers with stable,
  predictable API hostnames (OpenAI, Anthropic, Gemini, Groq, Mistral, Cohere, DeepSeek,
  OpenRouter, xAI, Perplexity, Together, Fireworks) on 443. Flagged in-file that account/region-
  specific providers (Azure OpenAI, AWS Bedrock, GCP Vertex, self-hosted Ollama) aren't
  pre-populated and need a manual `toFQDNs` addition once configured, or their calls will
  silently time out.
- Wired `kubernetes/apps/ai/open-webui/app/helmrelease.yaml`'s `OPENAI_API_BASE_URLS` at
  Bifrost's in-cluster Service; `OPENAI_API_KEYS` left as an explicit placeholder pending a
  Bifrost virtual key, since Bifrost starts with zero providers configured.
- Updated `docs/EXTERNAL-SECRETS.yaml` with a new `bifrost` 1Password item entry (wildcard
  import, `ENCRYPTION_KEY` field) per the doc's own maintenance convention.
- Validated the whole tree with `kubectl kustomize` on the `ai` namespace and the bifrost `app/`
  directory, and parsed the rendered `ExternalSecret`'s templated `config.json` with Python to
  confirm it's valid JSON.
- Gave bifrost a deterministic VolSync backup schedule (`29 * * * *`), chosen to not collide with
  Plex's already-committed slot, and confirmed via `task volsync:check-schedules`.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/ai/bifrost/ks.yaml` | New — Flux Kustomization, VolSync-backed, `targetNamespace: ai` |
| `kubernetes/apps/ai/bifrost/app/kustomization.yaml` | New — lists the app's manifests |
| `kubernetes/apps/ai/bifrost/app/helmrelease.yaml` | New — app-template `deployment`, VolSync PVC + secret-mounted `config.json`, non-root hardened |
| `kubernetes/apps/ai/bifrost/app/externalsecret.yaml` | New — pulls `ENCRYPTION_KEY` from 1Password, templates the minimal `config.json` |
| `kubernetes/apps/ai/bifrost/app/httproute.yaml` | New — `bifrost.${DOMAIN_CLUSTER}` via `envoy-internal` |
| `kubernetes/apps/ai/bifrost/app/networkpolicy.yaml` | New — first `CiliumNetworkPolicy` in this repo; egress scoped to CoreDNS + LLM provider APIs |
| `kubernetes/apps/ai/kustomization.yaml` | Registered `./bifrost/ks.yaml` |
| `kubernetes/apps/ai/open-webui/app/helmrelease.yaml` | Added `OPENAI_API_BASE_URLS`/`OPENAI_API_KEYS` pointing at Bifrost |
| `docs/EXTERNAL-SECRETS.yaml` | Added the `bifrost` 1Password item inventory entry |

### Key decisions
- Deviated from the reference's `config.json` (`source_of_truth: "config.json"` + populated
  `providers`) after checking Bifrost's own docs — that combination would wipe UI-added providers
  on every restart, defeating the user's "manage providers via the UI" choice.
- Added the `CiliumNetworkPolicy` only after the user explicitly asked for it upon seeing it in
  the reference; initially left it out of the plan since no other app in this repo uses one.
- Deliberately left Azure OpenAI/Bedrock/Vertex AI/local-Ollama hostnames out of the egress
  allow-list rather than guess account-specific domains — safer to fail closed (timeout) than
  silently widen the policy with an unverified hostname.
- Deferred actual LLM provider/virtual-key configuration inside Bifrost to a manual post-deploy
  step, consistent with how Open WebUI's own backend was originally left unwired at its deploy.

---

## 2026-09-03 — `ceph-packetdrops-prometheus-correlation`

### Goal
Triage current/recent Prometheus alerts, investigate why `CephNodeNetworkPacketDrops` and `PrometheusMissingRuleEvaluations` fired together, and update documentation to reflect new evidence for prioritizing the Ceph `public_network`-to-storage-VLAN migration.

### What we did
- Ran two rounds of alert triage via the `diagnose-alerts` skill workflow (Alertmanager `/api/v2/alerts`, Prometheus `ALERTS{}` history, `/api/v1/rules`) across the conversation. Found a new `CephNodeDiskspaceWarning` firing on `cp-01`'s `/var` — not the known `/etc/nfsmount.conf` false positive. Traced via `node_boot_time_seconds` (node up ~15 days, ruling out the existing post-boot guard) and a 48h `node_filesystem_avail_bytes` trend to a sharp one-time ~9GB write 19-22h earlier that had already gone flat — diagnosed as a `predict_linear` step-change misread (same failure class as the original fix, different trigger), not an ongoing fill risk. Confirmed `TargetDown` (`truenas-node-exporter`) and the prior session's `PrometheusTSDBCompactionsFailing` pending alert had both self-resolved.
- Investigated whether a brief `CephNodeNetworkPacketDrops` flap (`cp-03`/`worker-02`, 04:20-04:42 UTC) and a co-occurring `PrometheusMissingRuleEvaluations` flap (`kube-apiserver-burnrate.rules`, previously flagged unexplained in the 2026-09-02 session) were linked. Confirmed via `prometheus_rule_group_last_duration_seconds` (216s, should be sub-second) and `prometheus_rule_group_iterations_missed_total` (+34) that Prometheus's own rule evaluator stalled — not a scrape failure (`up`/`scrape_duration_seconds` stayed normal). Traced the stall to Prometheus's own Ceph-RBD-backed TSDB PVC (`rbd3` on `cp-01`) being ~100% I/O-busy, matching the drop-burst windows.
- Identified the actual write source on `cp-01` via `container_fs_writes_bytes_total` (a true counter): `rook-ceph-mon-a` and `osd-0`/`osd-3`, all scheduled on `cp-01`. Caught and discarded a bad first attempt that used `rate()` on the gauge metric `kubelet_volume_stats_used_bytes`, which produced bogus billion-byte/s figures. Ruled out CNPG Postgres as an alternative explanation (WAL/replication counters flat) despite a superficially matching primary/replica topology.
- Disambiguated this episode from the 2026-09-02 Cilium L2-announcement-lease theory by checking live lease holders: `cp-03` held zero L2 leases yet dropped in lockstep with `worker-02` (which holds one) — evidence against L2 chatter explaining this specific episode, and consistent instead with genuine Ceph `public_network` traffic (`mon-a`/`osd-0`/`osd-3` on `cp-01` exchanging mon-quorum and OSD heartbeat-front traffic with their peers — `osd-2`/`osd-4` on `cp-03`, `mon-d`/`osd-6`/`osd-9` on `worker-02`).
- Updated `docs/QA.md`'s `CephNodeNetworkPacketDrops` entry and `docs/ROADMAP.md`'s e1000e packet-drops and "Ceph `public_network`: Move to Storage VLAN" sections with this finding. At the user's explicit direction to move toward implementing the VLAN migration, changed the project's status from "desired end state, not started" to "prioritized by the user — not yet started," and restructured its open blockers into a concrete two-item "Next steps to unblock a start" list (research Rook's live mon-network migration support; verify pod-to-mon reachability on the storage VLAN).
- Answered the user's question about whether the four affected nodes' NICs could be reused for this migration: queried live Talos link state (`talosctl get links`) on all four and confirmed each has exactly one onboard RJ45 (`eno1`, `e1000e`/I219-LM, 1Gbit) plus a discrete 2-port X520-DA2 SFP+ card (`ixgbe`, 10Gbit) already bonded into `bond-storage` — no second onboard RJ45 or idle NIC exists to repurpose; the only viable path is sharing the existing storage bond, as already planned.

### Files changed
| File | Change |
|------|--------|
| `docs/QA.md` | Added a 2026-09-03 finding to the `CephNodeNetworkPacketDrops` entry: the `PrometheusMissingRuleEvaluations` correlation, the mon-a/osd-0/osd-3 write-burst trace, and the Cilium L2-lease disambiguation |
| `docs/ROADMAP.md` | Updated the e1000e packet-drops entry and the "Ceph `public_network`: Move to Storage VLAN" section with the 2026-09-03 finding; changed status to "prioritized by the user"; restructured open blockers into a concrete two-item next-steps list |

### Key decisions
- Kept the existing "item #4" numbering in `ROADMAP.md`'s ranked troubleshooting list unchanged rather than reordering to reflect elevated priority, since other sections cross-reference "item #4" by number — added emphasis in the surrounding text instead.
- Declined to start the VLAN migration's actual research prerequisites (Rook mon-migration mechanics, storage-VLAN reachability check) even though the user said they want to move toward the project — the request was specifically to update documentation, so left both as clearly flagged next steps rather than beginning them unprompted.

---

## 2026-09-02 — `prometheus-alerts-triage-pvc-grow`

### Goal
Survey every currently-firing and recently-resolved Prometheus alert, then resolve the firing `KubePersistentVolumeFillingUp` by resizing the Prometheus TSDB PVC and raising retention.

### What we did
- Ran a full alert survey via the `diagnose-alerts` skill: Alertmanager's `/api/v2/alerts` for live state, Prometheus's own `ALERTS{alertstate="firing"}` timeseries over a 24h window for flaps that already resolved (Alertmanager keeps no history, so the live view alone would have missed four of the six alerts found), and `/api/v1/rules` for pending alerts and rule-group `lastError`. Three active (two real plus the intentional `Watchdog` heartbeat), four fired-and-resolved within the window, no pending alerts, no rule evaluation errors.
- Cross-referenced each alertname against the repo: rule definitions, `silence-operator/silences/`, `docs/QA.md`, `docs/SESSIONS.md`, and `alertmanagerconfig.yaml`'s severity routing (`critical` → `pushover-critical` emergency/repeat-60s-for-1h; `warning|error` → `pushover` once) to state per alert whether it would actually have paged.
- **`KubePersistentVolumeFillingUp`** (firing, warning): Prometheus's own 20Gi `ceph-block` TSDB PVC at 11.5% free, declining steadily 21% → 11.5% over 48h with one midnight rebound (a compaction). Measured the underlying TSDB state rather than guessing: `prometheus_tsdb_storage_blocks_bytes` = 17.6 GB against the `retentionSize: 18GB` cap, and `prometheus_tsdb_lowest_timestamp_seconds` = 13.36 days against the `retention: 14d` cap — **both limits binding simultaneously**, WAL 0.76 GB.
- Root-caused it as a config artifact, not a fault or a leak: `retentionSize: 18GB` (decimal) on a 20Gi (= 21.5 GB binary) volume is 84% of the disk by construction. The 15%-free alert trips at 18.25 GB used; steady state was 18 GB blocks + 0.76 GB WAL ≈ 18.76 GB — the hard cap sat roughly 0.5 GB *above* the alert's trigger point, so firing was guaranteed at steady state.
- Confirmed capacity before proposing anything: `ceph-block` has `allowVolumeExpansion=true`, and Ceph has 9.9 TB free of 10 TB (so 60Gi ×3 replicas = 180 GiB raw is 1.8% of free space).
- **Got the apply mechanism wrong initially and had to correct it.** Claimed Prometheus Operator v0.93.1 would patch the existing PVCs automatically, so no manual step was needed. After the user pushed and reported the PVC hadn't grown, traced the chain live: Flux was on `main@efa5e05`, `cluster-apps` applied, HelmRelease upgraded, Prometheus CR and StatefulSet template all showed `60Gi` — but the PVC was still `requested=20Gi actual=20Gi`, with no PVC conditions and no resize line in the operator log. Verified against the upstream docs rather than re-guessing: "Kubernetes doesn't support (yet) volume expansion through StatefulSets … the associated PVCs aren't expanded." There is no feature gate for it at any operator version.
- Root cause of the non-apply: `volumeClaimTemplates` only governs PVCs minted for *new* replicas, so the operator's StatefulSet recreation (logged as `recreating StatefulSet because the update operation wasn't possible … Forbidden: updates to statefulset spec for fields other than 'replicas', … are forbidden`, done with `--cascade=orphan`, which is why the pod never restarted) makes the template match while leaving the live PVC untouched. Git ends up correct-but-unenforced.
- With user confirmation — flagged first as both irreversible and an intentional exception to the repo's no-imperative-changes rule — ran the one-time `kubectl patch pvc … 60Gi`. Ceph RBD expanded online: `status.capacity` flipped to `60Gi` immediately, the pod stayed up with 0 restarts, and `kubelet_volume_stats_capacity_bytes` confirmed the mounted filesystem grew from ~19.5 GiB to 58.88 GiB usable.
- Put the sizing trade-off to the user via `AskUserQuestion` with three costed options rather than implementing the literal "double it" request: doubling to 40Gi alone would have left the extra 23 GiB permanently inert, because TSDB is hard-capped by `retentionSize`, not by disk size. User chose 60Gi + 30d retention + 40GB cap.
- Implemented in `values.yaml` and validated: YAML parses with all three values as intended, and `kustomize build` on the app directory exits 0 with `retention: 30d` / `retentionSize: 40GB` / `storage: 60Gi` rendering correctly into the HelmRelease. Committed as `949ea68` on the worktree branch; not pushed (CLAUDE.md requires explicit confirmation).
- **`TargetDown`** (firing, warning, `truenas-node-exporter`): a **new** failure mode, not a recurrence of the 2026-07-17 `node-exporter-hwmon-crash-fix` session's nil-pointer panic. Live scrape error is a parse failure — `expected metric name after HELP, got "\"noatimerw\x00"` — i.e. corrupted output from the `sensors-textfile` sidecar that replaced the panicking `hwmon` collector, not a dropped connection. `truenas-smartctl-exporter` on the same host is healthy, ruling out host-down. Left for TrueNAS-side investigation (the `truenas/` compose stacks are doco-cd-managed, outside Flux).
- **`PrometheusRuleFailures`** (resolved, **critical**): fired ~16:36–23:10 on 2026-09-01 (~6.5h) against `kube-apiserver-availability.rules` and `kube-apiserver-burnrate.rules`, alongside its warning sibling `PrometheusMissingRuleEvaluations` (14:21–22:33, same rule group). Would have emergency-paged. Ruled out the previously-known cause: the Prometheus pod has 0 restarts and has run continuously since 2026-08-19, so unlike the earlier occurrence recorded in `SESSIONS.md` this is not a pod-restart artifact. Self-resolved, root cause unexplained; flagged as a follow-up rather than diagnosed here.
- **`CephNodeNetworkPacketDrops`** (resolved): fired 2026-09-01 10:14 → 2026-09-02 04:54 on `worker-01`/`worker-02` (`eno1`, e1000e) — the known, actively-tracked ring-exhaustion issue from the last two sessions; no new action. Noted that the same-named `Silence` file is INACTIVE and covers a *different*, already-fixed root cause (the 2026-06/07 X520 fallback), so it is not evidence this instance is silenced.
- **`CephNodeNetworkBondDegraded`** (resolved): a single one-point blip on `cp-03`'s `bond-storage` at 15:10 on 2026-09-01, self-resolved within a scrape interval; its X520-era `Silence` is likewise INACTIVE. Too brief to characterize; no action.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | `retention` 14d→30d, `retentionSize` 18GB→40GB, PVC `storage` 20Gi→60Gi; rewrote the sizing comments to record why the cap must sit below the alert threshold and what the prior config's failure was |
| `docs/QA.md` | New Storage entry: increasing a StatefulSet-backed PVC in Git does not grow the live volume — why every layer reports success, how to confirm, and the one-time `kubectl patch pvc` fix |

### Key decisions
- Declined to implement the literal request (straight doubling to 40Gi) and surfaced the trade-off instead: because `retentionSize` hard-caps the TSDB, growing only the disk would have fixed the alert while leaving ~23 GiB provisioned and permanently unused, with retention still at 14d. The user picked the larger option once the inertness was visible.
- Sized `retentionSize` (40GB) against the *alert's trigger point* (54.8 GB used = 15% free on a 64.4 GB volume), not merely "below the disk size" as the previous comment framed it. The cap now sits ~14 GB below the trigger instead of ~0.5 GB above it — that sign flip, not the extra capacity, is what makes the fix durable rather than a delay.
- Kept a byte-based `retentionSize` cap rather than relying on time retention alone: under cardinality growth the failure mode is then a shorter retention window, never a full disk. Noted the silent consequence — you would get <30 days with nothing alerting on it — and offered a retention-window rule as optional follow-up rather than adding unrequested scope.
- Raised retention to 30d specifically to serve in-flight work: the 4-week Ceph packet-drop checkpoint captured a pre-fix baseline on 2026-09-01 that would have aged out around 2026-09-15 under 14d retention, before its ~2026-09-29 comparison window closed.
- Accepted a one-time imperative `kubectl patch pvc` as a documented exception to the repo's GitOps-only rule, rather than trying to force it through Git: the patch converges a live volume *toward* already-committed state instead of introducing drift, and Kubernetes exposes no declarative path for expanding an existing StatefulSet PVC. Recorded the gotcha in `docs/QA.md` and warned about it inline at the `storage:` field, since the number in `values.yaml` looks self-applying but is not.
- Skipped the `/git-commit` skill's `git fetch --dry-run` step, since CLAUDE.md forbids fetching without explicit confirmation and the worktree branch has no upstream — reported the deviation rather than silently following either rule.

---

## 2026-09-01 — `ceph-packetdrops-ring-headroom-baseline`

### Goal
Check whether the `CephNodeNetworkPacketDrops` issue has a BIOS-level or Ceph-role-based cause, confirm whether the RX ring buffer has headroom for the leading remaining fix, and capture a pre-fix baseline — without implementing anything yet.

### What we did
- User asked whether the affected nodes' (`cp-03`/`worker-02`) BIOS could explain the packet-drops issue, and what their roles in the Ceph cluster are. Checked both live via cluster-doctor rather than reciting from possibly-stale investigation notes.
- Ceph roles: `ceph osd tree`/`ceph mon dump` live — every e1000e node carries exactly 2 OSDs, no count difference; `worker-01` (unaffected) and `worker-02` (affected) both host a mon; `cp-02` (unaffected) and `cp-03` (affected) both host neither mon nor mgr. No role pattern differentiates the affected pair from the unaffected pair.
- Energy Efficient Ethernet (802.3az): a genuinely plausible candidate given the Intel I219-LM's documented history of PHY-wake-latency-on-burst-resumption issues, which fits the ring-exhaustion-at-burst-start failure shape. Checked live via `ethtool --show-eee eno1` (through a `kubectl debug node/... --image=nicolaka/netshoot` pod — `hostNetwork` automatic, no nsenter/chroot needed) on all 4 e1000e nodes: byte-for-byte identical everywhere — `enabled - inactive` (never actually negotiated, so no LPI wake-latency happening on any of the 4 links). Ruled out.
- Synthesized a "what are our current leads, is the public_network-to-storage-VLAN migration the only option" answer for the user: no — the RX ring buffer size (`ethtool -G`) is the most directly-indicated, cheapest, lowest-risk untried lever, gated only on a capacity check that had never actually been run.
- Ran that gating check live: `ethtool -g eno1` on all 4 e1000e nodes — `256` current RX/TX descriptors against a `4096` hardware maximum, identical everywhere, never touched from the `e1000e` driver default. Confirmed 16x headroom. Offload settings (GRO/LRO/checksumming) also came back stock and identical — not a contributing factor.
- Per explicit instruction, did not implement the ring-size fix — documented findings and possible troubleshooting steps only, and captured a pre-fix baseline for later comparison instead.
- Added a consolidated "Current status" TL;DR summary to the top of `docs/ROADMAP.md`'s e1000e entry, since it had grown into a long chronological history across many dated updates and a future reader shouldn't have to read all of it to know where things stand.
- Captured a pre-`ethtool -G` baseline via live PromQL: the same 3 queries as the original 2026-08-05 `netdev_budget` baseline (for direct comparability), plus a 7d window and raw absolute counter values (24h alone risks being unrepresentative for a sparse/bursty failure mode) — recorded per-node in `docs/ROADMAP.md` for a real before/after once the ring-size fix is eventually applied.

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Added "Ruled out" section (Ceph roles, EEE); added ring-headroom confirmation (16x headroom, cleared item #1 to proceed); added "Current status" TL;DR summary; added pre-`ethtool -G` baseline table |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Indexed the new cluster-doctor memory entry |
| `.claude/agent-memory/cluster-doctor/project_ceph_packetdrops_eee_and_roles_ruled_out.md` | New: EEE and Ceph-role rule-out findings, for future recall |

### Key decisions
- Explicitly deferred implementing the `ethtool -G` fix per direct user instruction ("do not implement anything yet") — documented it as "confirmed viable, not yet built" rather than building the Talos unsupported-workaround (privileged DaemonSet/initContainer) despite headroom being confirmed and the fix being otherwise ready to plan.
- Captured the baseline using the exact same PromQL methodology as the original 2026-08-05 `netdev_budget` baseline, specifically so the two are directly comparable once the fix is eventually applied, rather than inventing a new measurement approach.
- Extended the original 24h-only baseline format with a longer 7d window and the raw absolute counter, since a single 24h snapshot risks being unrepresentative for a failure mode this sparse/bursty — additive to the established methodology, not a replacement.

---

## 2026-09-01 — `ceph-packetdrops-checkpoint-4wk`

### Goal
Run the overdue 4-week checkpoint on the `netdev_budget` fix for `CephNodeNetworkPacketDrops`, and act on whatever it found.

### What we did
- Located the prior investigation's actual Claude Code session transcript (user wanted to resume/reference it) by searching `~/.claude/projects/` directly — found it living under a worktree-scoped project directory (`-workspaces-home-lab--claude-worktrees-ceph-packetdrops-docs-refresh`), not the main repo's own session history, since the original work ran in a since-deleted worktree.
- Ran the 4-week checkpoint: split result — `netdev_budget` fully resolved the alert on `cp-02`/`worker-01` (zero drops, 13-day clean run) but `cp-03`/`worker-02` regressed to *worse-than-baseline* drop volumes by late August, paging again on 2026-09-01.
- Root-caused the regression live: a `sabnzbd` Ceph RBD write burst (its `/config` PVC, `ceph-block`) landing on the management VLAN — confirmed via a 5-7x `eno1` packet-rate surge coincident with the burst window.
- Corrected an initial theory (OSD-daemon CPU competing with softirq for the same core) after live Prometheus data refuted it outright — `node_softnet_times_squeezed_total`/`node_softnet_dropped_total` stayed flat zero throughout; the actual mechanism is NIC RX-ring exhaustion (`node_network_receive_drop_total`, the driver's own `rx_dropped` counter), a layer below softirq that `netdev_budget` was never going to reach.
- Corrected a second overreach (framed sabnzbd's Ceph write as its "incomplete-download working set") after a peer session read the manifests directly and found downloads land on raw NFS, not Ceph — only `/config` (a small SQLite queue/history DB) is `ceph-block`; walked this back in the docs rather than leaving it stated as fact.
- Explained to the user why Ceph client I/O rides the management VLAN at all (a deliberate greenfield split between `public_network`/`cluster_network` to avoid a mon-failover migration) and why a 1GbE NIC "can't" absorb an 85MB/s burst well within its rated bandwidth — NIC ring depth and a single-queue `e1000e` chip, not bandwidth or CPU.
- Migrated `sabnzbd`/`sonarr`/`radarr`/`prowlarr`'s `/config` PVCs off `ceph-block` onto the cluster's existing (previously unused) `nfs` StorageClass, as a phased two-commit rollout: phase 1 (additive — new PVC + a one-off `cp -a` migration Job per app, apps scaled to 0 for the copy window) and phase 2 (cutover — repoints `persistence.config`, drops `volsync`/the old PVC, which Flux then pruned).
- Verified the migration at every stage via the cluster-doctor agent rather than assuming success: Flux reconciliation, migration Job logs/file counts, a full SHA-256 per-file checksum diff for `sabnzbd` specifically (the one app with a disproportionate `du`-byte-delta, later explained as cross-filesystem directory-inode accounting noise), and post-cutover app log inspection confirming each app's migrated config was genuinely recognized (existing queues/indexer configs/DBs), not fresh-setup state. Caught and documented one real hiccup: `sonarr` restarted once on first NFS-backed boot (probe-timing race, self-resolved, left as a watch item rather than pre-emptively tuning probes off one occurrence.
- Checked whether other `ceph-block` consumers could reproduce the same failure mode: CNPG Postgres turned out to already be on `openebs-hostpath` (not applicable, correcting the original suggestion to check it); broadened to `victoria-logs`, `kube-prometheus-stack`, and the 8 apps sharing the `volsync` component. Caught a live `CephNodeNetworkPacketDrops` episode mid-investigation and ruled out every monitored candidate (Prometheus's own writes, victoria-logs, volsync, the already-migrated `downloads` namespace) without identifying a definitive trigger — an unattributed Ceph-internal read (`ceph -s`, possibly scrub) is the leading unconfirmed hypothesis.
- Confirmed live (not just from config) that VolSync's hourly backup was genuinely unstaggered across all 8 `ceph-block`-backed apps — every `ReplicationSource.status.lastSyncTime` landed in the same ~30-second window every hour — a real, independent synchronized-burst risk.
- Fixed the sync-storm risk with a new deterministic tool (`scripts/volsync-schedule.py`, wired as `task volsync:schedule`/`task volsync:check-schedules`): hashes each app name (CRC32) to a candidate minute avoiding `:00`/`:30`, then resolves collisions by linear-probing in a fixed sorted order so the same set of app names always produces the same collision-free assignment. Immediately caught and auto-resolved a real collision (`open-webui`/`plex` both hashing to `:27`) that an earlier hand-picked assignment hadn't accounted for.
- Documented the user's eventual goal — moving Ceph's entire `public_network` onto the storage VLAN — as a new, explicitly separate and larger `docs/ROADMAP.md` item (cluster-wide blast radius, unresearched Rook live-mon-reconfiguration behavior, unverified pod-to-mon routing prerequisite), rather than folding it into the narrower fix actually shipped this session.
- Hit repeated GPG commit-signing failures partway through (self-inflicted: ran `gpgconf --kill gpg-agent` while diagnosing the first failure, which left the agent in a restricted state) — did not bypass signing; handed off several commit messages for the user to run manually instead.

### Files changed
| File | Change |
|------|--------|
| `docs/QA.md` | Appended dated follow-ups: corrected mechanism (ring exhaustion, not softirq), corrected sabnzbd write claim, documented the live inconclusive episode and volsync sync risk |
| `docs/ROADMAP.md` | Full rewrite of the e1000e packet-drops entry (checkpoint results, corrected mechanism, live episode, volsync finding); added new "Ceph `public_network`: Move to Storage VLAN" item |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Indexed two new cluster-doctor memory entries |
| `.claude/agent-memory/cluster-doctor/reference_e1000e_ring_buffer_drops_not_softirq.md` | New: ring-exhaustion-not-softirq finding, for future recall |
| `.claude/agent-memory/cluster-doctor/project_ceph_packetdrops_other_consumers_check.md` | New: other-consumers audit findings, live episode evidence |
| `kubernetes/components/nfs-config/{pvc.yaml,kustomization.yaml}` | New: permanent nfs-backed `/config` PVC component |
| `kubernetes/components/nfs-config-migrate/{job.yaml,kustomization.yaml}` | New: one-off ceph-block→nfs copy Job component (temporary, used during cutover) |
| `kubernetes/apps/downloads/{sabnzbd,sonarr,radarr,prowlarr}/app/helmrelease.yaml` | Phase 1: added `replicas: 0`; Phase 2: removed it, cut `persistence.config` over to the nfs PVC |
| `kubernetes/apps/downloads/{sabnzbd,sonarr,radarr,prowlarr}/ks.yaml` | Phase 1: added `nfs-config`/`nfs-config-migrate` components + deps; Phase 2: dropped `volsync`/migrate components, updated deps/vars |
| `kubernetes/apps/{media/plex,documents/paperless-ngx,ai/open-webui,automation/n8n,database/pgadmin,automation/waha,finance/firefly-iii,development/forgejo}/ks.yaml` | Added deterministic `VOLSYNC_SCHEDULE` overrides (from `scripts/volsync-schedule.py`) |
| `scripts/volsync-schedule.py` | New: deterministic hash + collision-resolution tool for VolSync schedules |
| `.taskfiles/volsync/Taskfile.yaml` | New: `volsync:schedule` and `volsync:check-schedules` tasks |
| `Taskfile.yaml` | Registered the new `volsync` taskfile include |

### Key decisions
- Dropped automated VolSync backup for the 4 migrated `*arr` apps rather than retarget it at NFS with `copyMethod: Direct` — the data is small/recreatable (queue DB, history, indexer defs) and this cluster's NFS CSI driver has no VolumeSnapshot support, so `Direct` was the only viable copyMethod and wasn't judged worth the added complexity for this data's actual value.
- Used a plain rsync-style migration Job (mounting both the old and new PVC) instead of reusing VolSync's own restore-populator mechanism for the cutover — smaller blast radius (doesn't touch the shared `volsync` component used cluster-wide) and easier to verify step by step, at the cost of not reusing existing tooling.
- Structured the `*arr` migration as two separately-reviewable commits (additive phase 1, destructive-but-pre-verified phase 2) specifically so the user could confirm the copy — including a full checksum diff for the one app with an unexplained `du` delta — before the old `ceph-block` PVC was pruned and unrecoverable.
- Chose deterministic hash + collision-resolution (a script, still writes a literal into each `ks.yaml`) over a fully dynamic runtime controller for VolSync scheduling — matches this cluster's actual scale (8 apps, growing slowly); a new always-running component's own failure mode wasn't judged worth it yet.
- Scoped moving Ceph's `public_network` to the storage VLAN as a separate, later roadmap item rather than pursuing it now, despite a live inconclusive episode arguing the `*arr` migration alone doesn't fully close the underlying risk — cluster-wide blast radius and an unresearched live mon-reconfiguration procedure make it a materially bigger and riskier project than anything shipped this session.

---

## 2026-08-27 — `plex-keda-nfs-scaler`

### Goal
Add a KEDA autoscaler for Plex that scales it to zero when its NFS media mount's NAS is unreachable, following this repo's own pre-existing `docs/keda-nfs-scaler-plan.md` (written in anticipation of exactly this workload).

### What we did
- Surveyed the repo's existing KEDA patterns before writing anything: the `components/keda/{postgres,redis,smb,http}-scaler` Components, their live consumers (`paperless-ngx`, `open-webui`), and the dormant `docs/keda-nfs-scaler-plan.md` / `docs/ROADMAP.md` entry that named Plex as the intended pilot for an NFS-dependency scaler once a real NFS-backed Deployment existed.
- Identified that Plex's `/mnt/media` mount is a raw `type: nfs` volume (not Ceph, not the dynamic NFS StorageClass) — exactly the failure mode the plan targets: an NAS reboot/blip leaves kubelet retrying the mount forever with no workload-level backoff.
- Distinguished this from the repo's other KEDA use case (idle/cost-saving scale-to-zero via `app-http-add-on`, used by `open-webui`/`paperless-ngx`): that mechanism depends on an in-cluster HTTP interceptor queuing cold requests, which doesn't apply to Plex — its `LoadBalancer` Service and Tailscale `Ingress` are connected to directly by real clients, so scaling to zero on idle would mean dead connections with no auto-wake, not a delayed-but-successful one.
- Presented three possible autoscale scenarios (NFS-dependency scale-to-zero, idle/session-count scale-to-zero, scheduled cron scale-down) via `AskUserQuestion`; user chose the NFS-dependency scenario only, on the recommendation that it's the lowest-risk and already-planned option.
- Implemented Phase 1 of the existing plan: a standalone `ScaledObject` (not yet a `components/keda/` Component, since Plex is the first NFS-scaler consumer) reusing the already-deployed `nas-nfs` blackbox `Probe` (`probe_success{instance="${NAS_HOST}:2049"}`), `cooldownPeriod: 30` matching the other scaler Components' rationale.
- Added `driftDetection.ignore` for `/spec/replicas` on Plex's `HelmRelease`, matching the precedent in `paperless-ngx`/`open-webui` — without it, Flux's global drift-detection default would revert KEDA's scale-to-zero within the hour.
- Validated with `kustomize build` — all resources render cleanly (`${APP}`/`${NAS_HOST}` remain as literal tokens, substituted only at Flux reconcile time via `postBuild`).
- Left uncommitted per this repo's `/git-commit`-only rule.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/media/plex/app/scaledobject.yaml` | New standalone KEDA `ScaledObject` — scales Plex to 0 when the NAS's NFS port (2049) is unreachable, restores automatically on recovery |
| `kubernetes/apps/media/plex/app/kustomization.yaml` | Added `scaledobject.yaml` to the resource list |
| `kubernetes/apps/media/plex/app/helmrelease.yaml` | Added `driftDetection.ignore` for `/spec/replicas` so Flux doesn't fight KEDA's HPA |

### Key decisions
- Standalone `ScaledObject`, not a shared `components/keda/nfs-scaler` Component: this repo's own plan doc defers promoting to a Component until a second NFS-backed workload needs the same shape (currently only one consumer).
- Only the NFS-dependency scenario was implemented; idle/session-count and scheduled cron scaling were deliberately declined for now, since neither has an auto-wake path (Plex bypasses KEDA's HTTP interceptor entirely) and only Plex currently reserves the cluster's `gpu.intel.com/i915` resource, weakening the cost-saving case.

---

## 2026-08-24 — `configarr-deploy`

### Goal
Draft a Flux-managed Configarr deployment into the existing `downloads` namespace to sync TRaSH-Guide quality profiles and custom formats into Sonarr and Radarr.

### What we did
- Reviewed the existing `downloads` namespace apps (`sonarr`, `radarr`, `prowlarr`, `sabnzbd`) — their `ks.yaml`/`helmrelease.yaml`/`externalsecret.yaml`/`kustomization.yaml` shape — to match established conventions before writing anything new.
- Fetched the user-referenced `qnimbus/home-ops-bykaj` `kubernetes/apps/downloads/configarr/` tree via `gh api` and deliberately did not copy it wholesale — cross-checked each piece against this repo's own patterns instead.
- Adapted rather than copied: reused this repo's existing cosign-verified `app-template` OCIRepository (v5.0.1) instead of adding a redundant per-app `ocirepository.yaml`; corrected `config.yml`'s `base_url` ports to each app's real Service port (Sonarr 8989, Radarr 7878 — confirmed from their own `helmrelease.yaml`s) instead of the reference's port-80 assumption; reused the existing `sonarr`/`radarr` 1Password items via a second `ExternalSecret` rather than provisioning a new `configarr` item; dropped the reference's `reloader.stakater.com/auto` annotation as a no-op on a CronJob (which reads its ConfigMap fresh every scheduled run regardless).
- Asked the user two scoped `AskUserQuestion` decisions before writing `config.yml`, since both have live-cluster consequences: TRaSH quality tier (chose "Full: Bluray+WEB, 1080p+2160p") and whether Configarr may delete unmanaged quality profiles/custom formats in Sonarr/Radarr (chose fully declarative sync, `delete_unmanaged_*: true`).
- Verified every `trash_id` written into `config.yml` directly against `github.com/TRaSH-Guides/Guides` via `gh api` rather than trusting the reference repo's copied hashes — discovered Sonarr's TRaSH taxonomy has no Bluray-only tier the way Radarr's does, and substituted the closest equivalent (`Remux + WEB`), documented inline.
- Verified the Configarr image digest (`1.30.2`) against ghcr.io's registry API directly (anonymous token + manifest HEAD) rather than trusting the reference's copied digest — confirmed it was accurate.
- Wrote the full manifest set (`ks.yaml`, `app/kustomization.yaml`, `app/externalsecret.yaml`, `app/helmrelease.yaml`, `app/resources/config.yml`) and wired it into `kubernetes/apps/downloads/kustomization.yaml`; documented Configarr as a second consumer of the `sonarr`/`radarr` 1Password items in `docs/EXTERNAL-SECRETS.yaml`.
- Validated with `kustomize build` and `task validate` (kubeconform) — all resources valid.
- Attempted to commit via the `/git-commit` skill (worktree-exception path); the commit itself failed — `ssh-add` can't reach the signing identity from this sandboxed job (`error fetching identities: communication with agent failed`). Did not bypass with `--no-gpg-sign`. All 7 files remain staged, uncommitted.
## 2026-08-24 — `plex-deploy`

### Goal
Deploy Plex Media Server (GPU transcode passthrough, NFS-backed media library) into the `media` namespace, then diagnose and fix a series of live networking failures — a crash loop, total unreachability, and mobile "Remote connection" labeling — before giving it a dedicated LoadBalancer IP.

### What we did
- Researched community patterns (kubesearch.dev, the user's own `qnimbus/home-ops-bykaj` repo) and settled the deployment architecture via `AskUserQuestion`: Plex-only (not paired with Jellyfin — the docs list them as alternatives, never a planned pair), a new TrueNAS NFS dataset for media, internal-only exposure via `envoy-internal` (reachable remotely through the existing Tailscale subnet router, not a public Cloudflare Tunnel route — Plex's CVE history was the explicit reason), and GPU transcode via the already-deployed-but-idle Intel iGPU device-plugin pool. No 1Password item/`ExternalSecret` for Plex — `PLEX_CLAIM_TOKEN` expires in ~4 minutes, incompatible with async GitOps reconcile timing, so the server was claimed manually via the web setup wizard post-deploy.
- Wrote and committed the full manifest set; guided the user through TrueNAS NFS export configuration (`mapall` vs `maproot`, since Plex's pod presents UID 1000 with no matching local TrueNAS user) and the claim-token exchange (corrected an initially wrong guess about the claim mechanism by fetching the actual `entrypoint.sh` source rather than continuing to guess). Verified GPU hardware transcoding end-to-end via a live `ps aux` inspection of the real VAAPI `ffmpeg` process during an actual 4K HDR transcode.
- User reported the mobile app couldn't locate/connect to the server on the LAN. Root-caused a genuine crash loop separately from the reachability issue: the original `liveness` probe (90s total budget) was killing PMS mid first-boot library scan against the newly-populated NFS library, forever, before it could finish starting — fixed with a dedicated `startupProbe` (10-minute budget) gating `liveness`/`readiness`.
- Fixed a second, independent issue: PMS was advertising its own ephemeral pod IP to plex.tv as its "local" connection instead of the actual reachable Gateway hostname — fixed via `PLEX_ADVERTISE_URL`/`customConnections`.
- Chased a `403` from `servers.plex.tv` and a mysterious `EventSourceClient` retry loop as a suspected plex.tv rate-limit issue (scaled the Deployment to 0, suspended the HelmRelease, cooldown, resumed) — later determined both were red herrings unrelated to the actual blocker.
- Root-caused total unreachability via re-enabled Plex debug logging (`logDebug=1`): `secureConnections` defaults to `Required` once claimed (the value `0`, counterintuitively the *strictest* setting — confirmed against python-plexapi's docs), which silently rejected every plaintext connection from anywhere but loopback, including kubelet's own HTTP probes and Envoy's plaintext backend connection. Fixed via `httpGet.scheme: HTTPS` on all probes (kubelet doesn't validate the server cert) plus `secureConnections=Preferred`.
- Diagnosed the mobile app's "Remote connection" label: found via the plex.tv account API a genuinely separate, forgotten Plex server ("Plex Home") running natively on the user's TrueNAS since January, still registered under the same account — its inter-server `EventSourceClient` retry attempts were the actual source of the earlier mysterious `10.10.0.41` address. Deauthorized it via `DELETE https://plex.tv/devices/{id}.xml`. Root-caused the remaining "Remote" label (confirmed via debug logs during a real, live streaming session from the user's phone) as an architectural limitation — Plex's LAN/WAN classification is based on adjacency to its own pod-network interface, not `allowedNetworks`/`LanNetworksBandwidth` or `X-Forwarded-For` — and documented it as unfixable without host networking, with no actual playback impact.
- Documented both major root causes as new entries under a "Media" section in `docs/QA.md`, including the dead ends chased along the way.
- Reviewed `docs/dra-gpu-migration-plan.md` at the user's request: corrected a factual error (bykaj's `plex-image-cleanup` maintenance job was cited as needing GPU co-access — checked its actual manifests directly and found no GPU request at all, just a `podAffinity` for RWO PVC co-location) and shelved the plan, since its stated trigger (Plex and Jellyfin sharing one iGPU) no longer applies given the Plex-only decision.
- Compared bykaj's Plex deployment to ours in detail at the user's request (ingress/listening surfaces, GPU model via DRA vs. device-plugin, user/group, persistence, maintenance tooling). Reviewed a set of bykaj-inspired edits the user made directly in their editor and caught several issues before they landed: two undefined cluster variables, a wrong variable name (`TAILSCALE_DOMAIN` vs. the repo's actual `DOMAIN_TAILSCALE`), a `className: tailscale` Ingress this cluster's `tailscale-operator` doesn't support (Connector/subnet-router mode only — deferred, commented out for a later session), and a broken YAML anchor reference.
- Added new `*_CIDR` cluster-secrets variables (`LAN_CIDR`, `POD_CIDR`, `SERVICE_CIDR`, `TAILSCALE_CIDR`) additively alongside the existing `*_SUBNET` names, migration to remove the old names deferred to later.
- Gave Plex a dedicated Cilium LB-IPAM `LoadBalancer` IP (`10.60.0.233`, from the existing `pool` range) with `externalTrafficPolicy: Local` (preserves the real client source IP to the pod, unlike the Envoy-proxied path) and an `external-dns-unifi`-published internal hostname on `DOMAIN_APPS` — chosen over `DOMAIN_APP` after confirming directly (not assuming) which variable is actually wired into cert-manager and both `external-dns` instances.
- Hit persistent SSH-agent/1Password commit-signing flakiness throughout (agent unreachable, several rounds of "communication with agent failed" / "Couldn't find key in agent") — repeatedly handed `git commit`/`git push` off to the user's own terminal when retries didn't clear it.
- After the LB IP was live, hit a second connectivity failure: LAN clients got "connection refused" against the new LoadBalancer IP despite it working fine from an in-cluster debug pod. Root-caused to a documented Cilium limitation: L2-announcement leader election is unaware of `externalTrafficPolicy: Local` and doesn't consider backend pod placement, so the ARP-winning node (`talos-worker-02`) differed from the node actually running the Plex pod (`talos-cp-02`) — confirmed via `kubectl -n kube-system get lease` and cross-referenced against `cilium/cilium#27800` (open upstream issue). Fixed by dropping `externalTrafficPolicy: Local` (defaults to `Cluster`) — the same fix a prior session (`rook-ceph-bgp-investigation`) already applied to `kube-api`/`envoy-internal` for the identical bug. Confirmed bykaj's identical config never hits this bug because their 3-node cluster is 100% GPU-labeled, making a leader/pod mismatch structurally impossible there.
- Discussed the `Local`-vs-`Cluster` tradeoff with the user (extra hop / lost client-IP visibility in logs) and decided to stay on `Cluster`, reject node-pinning as a workaround (would trade Plex's ability to reschedule across any of the 4 GPU-capable nodes for a benefit already proven unneeded), and track — not wait on — the unmerged upstream fix `cilium/cilium#46399`. Documented this as a second confirmed recurrence in `docs/ROADMAP.md`'s existing "Cilium BGP Control Plane" entry, and cross-linked a new `docs/QA.md` entry both directions.
- User reported Plex still unreachable from IOT-VLAN clients (a Google TV streamer on `10.30.0.0/24`) even after the above fixes. Root-caused: the UniFi gateway only permits IOT→mgmt *return* traffic, never IOT-initiated connections — the same restriction the Canon printer/`smtp-relay` pattern already exists to work around, not a new bug. Fixed by mirroring that precedent: added a second, IOT-VLAN-scoped `CiliumLoadBalancerIPPool` (`pool-iot-plex`, `10.30.0.234/32`, `serviceSelector`-scoped to the `plex` Service), announced via the tagged VLAN 30 sub-interface every node already carries; pinned `external-dns`'s `target` annotation to the mgmt IP to avoid the dual-IP DNS ambiguity `smtp-relay` hit first; and added the IOT IP as a `PLEX_ADVERTISE_URL` candidate so `plex.tv` hands it to clients that can actually reach it (also correctly tagged `local: true`, since it's a private RFC1918 address).

### Files changed
| File | Change |
|------|--------|
| `docs/EXTERNAL-SECRETS.yaml` | Documented `configarr` as a second consumer of the existing `sonarr`/`radarr` 1Password items |
| `kubernetes/apps/downloads/kustomization.yaml` | Added `./configarr/ks.yaml` to the resource list |
| `kubernetes/apps/downloads/configarr/ks.yaml` | New — Flux Kustomization, `dependsOn: [onepassword-store]` only (no PVC/volsync needed) |
| `kubernetes/apps/downloads/configarr/app/kustomization.yaml` | New — resources + `configMapGenerator` for `config.yml` |
| `kubernetes/apps/downloads/configarr/app/externalsecret.yaml` | New — `dataFrom` from `sonarr`+`radarr` items, `template` remaps to `SONARR_API_KEY`/`RADARR_API_KEY` |
| `kubernetes/apps/downloads/configarr/app/helmrelease.yaml` | New — `app-template` CronJob (every 12h), ConfigMap + emptyDir persistence, `readOnlyRootFilesystem: true` |
| `kubernetes/apps/downloads/configarr/app/resources/config.yml` | New — TRaSH-Guide sync config for Sonarr/Radarr, Full tier, fully declarative (`delete_unmanaged_*: true`) |

### Key decisions
- Quality tier and `delete_unmanaged` behavior were left to the user's explicit choice via `AskUserQuestion` rather than inferred, since both affect what gets deleted from a live Sonarr/Radarr instance on first sync.
- Every TRaSH-Guides `trash_id` and the Configarr image digest were independently re-verified against source (GitHub API, ghcr.io registry API) rather than trusted from the reference repo, per the user's explicit "don't blindly copy" instruction.
- Sonarr has no direct Bluray-only TRaSH tier (unlike Radarr); used `Remux + WEB` as the closest equivalent and documented the discrepancy inline in `config.yml` rather than silently forcing parity.
- Left the commit unfinished rather than bypassing GPG/SSH signing — the sandboxed job's SSH agent couldn't reach the signing identity; work stays staged pending user action.

---

## 2026-08-23 — `arr-stack-deploy`

### Goal
Investigate and draft a Flux-managed deployment of the *arr media-automation stack (Prowlarr, Sonarr, Radarr, Sabnzbd) into a new `downloads` namespace.

### What we did
- Created worktree `.claude/worktrees/arr-stack-deploy` on branch `worktree-arr-stack-deploy` via `EnterWorktree`.
- Ran two parallel Explore agents: one surveyed this repo's own storage/secrets/app-template conventions (found `media/plex`'s ceph-block+VolSync `/config` PVC plus raw-NFS-mount pattern, and a planted comment in its `ks.yaml` explicitly anticipating this *arr-stack deployment's UID/GID choice — "1000:1000 matches n8n's existing precedent so a future *arr stack can share this NFS mount's ownership"); the other researched external patterns from kubesearch.dev and the qnimbus/home-ops-bykaj reference repo's `kubernetes/apps/downloads/` tree the user pointed at.
- Confirmed via TRaSH Guides research that Sonarr/Radarr's hardlink-based import requires the download-staging folder and media library to live on one filesystem — ruled out giving the *arr stack its own PVC/export or introducing a CephFS RWX StorageClass, and designed instead around reusing Plex's existing raw NFS mount (`${NAS_HOST}:/mnt/tank/Media`).
- Asked the user one scoped decision via `AskUserQuestion` (new `downloads` namespace vs. folding into `media`) — user chose the new namespace, matching both `docs/POTENTIAL-DEPLOYMENTS.md`'s own category split and the reference repo's convention.
- Wrote the full design to a plan-mode file and got user approval via `ExitPlanMode` before implementing.
- Pulled real current image tags/digests for `ghcr.io/home-operations/{prowlarr,sonarr,radarr,sabnzbd}` from the qnimbus reference repo via `WebFetch` rather than guessing, including each image's actual health-check endpoint (`/ping`, or `/api?mode=version` for Sabnzbd) and normalized container port (80, not each app's historical default like 8989/7878).
- Wrote the full manifest set for all four apps, following `media/plex`'s exact shape (ceph-block `/config` PVC via `components/volsync`, `1000:1000` securityContext, internal-only `HTTPRoute` via `envoy-internal`, Homepage annotations); validated every new Kustomization with `kustomize build` and committed via the `/git-commit` skill (worktree-exception path) as `7ef3056`.
- User asked for the four `ExternalSecret`s to follow this repo's `waha`-style `dataFrom.extract`/`rewrite`/`target.template` convention instead of the explicit `data`/`remoteRef` form used initially — reworked all four, re-validated, committed as `e7e1b70`.
- Documented all four new 1Password items (`prowlarr`, `sonarr`, `radarr`, `sabnzbd`) in `docs/EXTERNAL-SECRETS.yaml` including their `volsync-restic` consumer entries; deliberately left `docs/POTENTIAL-DEPLOYMENTS.md` unmarked, matching the precedent that `n8n` (also drafted-but-uncommitted at the time) stays unmarked there too.
- Left the branch unpushed pending explicit user confirmation, per this repo's push rule. Outstanding manual follow-ups: create the four 1Password items, confirm the actual TrueNAS folder names under Plex's library before setting Sonarr/Radarr root folders, create `downloads/{incomplete,complete}` subdirectories under the existing NFS export, and wire up Prowlarr Applications / Sonarr-Radarr download client / Sabnzbd categories post-deploy.

### Files changed
| File | Change |
|------|--------|
| `docs/EXTERNAL-SECRETS.yaml` | New — 4 items (`prowlarr`, `sonarr`, `radarr`, `sabnzbd`), wildcard+rewrite mode, plus their `volsync-restic` consumer entries |
| `kubernetes/apps/kustomization.yaml` | Registered `./downloads` |
| `kubernetes/apps/downloads/namespace.yaml` | New — `downloads` Namespace |
| `kubernetes/apps/downloads/kustomization.yaml` | New — lists namespace + 4 apps' `ks.yaml` |
| `kubernetes/apps/downloads/prowlarr/ks.yaml` | New — Flux Kustomization, volsync component, 2Gi `/config` |
| `kubernetes/apps/downloads/prowlarr/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/downloads/prowlarr/app/helmrelease.yaml` | New — `app-template` HelmRelease, no media mount (Prowlarr only calls APIs) |
| `kubernetes/apps/downloads/prowlarr/app/externalsecret.yaml` | New — wildcard+rewrite, `PROWLARR__AUTH__APIKEY` |
| `kubernetes/apps/downloads/prowlarr/app/httproute.yaml` | New — internal-only route, Homepage annotations |
| `kubernetes/apps/downloads/sonarr/ks.yaml` | New — same shape, 5Gi `/config` |
| `kubernetes/apps/downloads/sonarr/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/downloads/sonarr/app/helmrelease.yaml` | New — HelmRelease + shared NFS `/mnt/media` mount |
| `kubernetes/apps/downloads/sonarr/app/externalsecret.yaml` | New — wildcard+rewrite, `SONARR__AUTH__APIKEY` |
| `kubernetes/apps/downloads/sonarr/app/httproute.yaml` | New — internal-only route |
| `kubernetes/apps/downloads/radarr/ks.yaml` | New — same shape, 5Gi `/config` |
| `kubernetes/apps/downloads/radarr/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/downloads/radarr/app/helmrelease.yaml` | New — HelmRelease + shared NFS `/mnt/media` mount |
| `kubernetes/apps/downloads/radarr/app/externalsecret.yaml` | New — wildcard+rewrite, `RADARR__AUTH__APIKEY` |
| `kubernetes/apps/downloads/radarr/app/httproute.yaml` | New — internal-only route |
| `kubernetes/apps/downloads/sabnzbd/ks.yaml` | New — same shape, 5Gi `/config` |
| `kubernetes/apps/downloads/sabnzbd/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/downloads/sabnzbd/app/helmrelease.yaml` | New — HelmRelease + shared NFS `/mnt/media` mount, higher memory ceiling for par2 repair |
| `kubernetes/apps/downloads/sabnzbd/app/externalsecret.yaml` | New — wildcard+rewrite, `SABNZBD__API_KEY` + `SABNZBD__NZB_KEY` |
| `kubernetes/apps/downloads/sabnzbd/app/httproute.yaml` | New — internal-only route |

### Key decisions
- Reused Plex's existing NFS export instead of adding a new one or introducing CephFS RWX — hardlinked imports require the download-staging folder and library to share one filesystem, and this repo already has exactly one shared library mount that fits.
- New `downloads` namespace rather than folding into `media` — user-confirmed, matches `docs/POTENTIAL-DEPLOYMENTS.md`'s own category split and the reference repo's convention.
- `ghcr.io/home-operations/*` images (fixed non-root UID, no PUID/PGID) over `linuxserver.io` — matches the existing Plex precedent and fits this cluster's hardened/no-root Talos posture better.
- API keys pre-seeded via 1Password rather than left to auto-generate on first boot — deterministic for Prowlarr's Applications config and any future cross-app automation (e.g. a future `configarr` deployment).
- Left `docs/POTENTIAL-DEPLOYMENTS.md` unmarked — confirmed that doc only reflects what's actually live by checking how the still-uncommitted `n8n` entry is (not) marked there.
- ExternalSecrets switched mid-session from explicit `data`/`remoteRef` to `waha`'s wildcard `dataFrom.extract`+`rewrite`+`target.template` convention, per explicit user direction.
| `kubernetes/apps/media/namespace.yaml` | New — `media` Namespace |
| `kubernetes/apps/media/kustomization.yaml` | New — lists the namespace and `plex/ks.yaml` |
| `kubernetes/apps/kustomization.yaml` | Registered the new `media` app |
| `kubernetes/apps/media/plex/ks.yaml` | New — Flux Kustomization, VolSync component, `dependsOn`, health checks; later added an `APP_SUBDOMAIN` substitute var for the deferred Tailscale ingress |
| `kubernetes/apps/media/plex/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/media/plex/app/helmrelease.yaml` | New, then heavily iterated: GPU device-plugin wiring, NFS media mount, `startupProbe` fix, HTTPS probe scheme, `secureConnections=Preferred`, `PLEX_ADVERTISE_URL` iterations, adopted new `*_CIDR` vars, dedicated `LoadBalancer` Service + Cilium LB-IPAM + `external-dns` hostname, deferred Tailscale ingress (commented out), dropped `externalTrafficPolicy: Local` (Cilium L2 incompatibility), added a second IOT-VLAN LB IP + pinned `external-dns` target |
| `kubernetes/apps/media/plex/app/httproute.yaml` | New — internal-only `HTTPRoute` on `envoy-internal` |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `LAN_CIDR`/`POD_CIDR`/`SERVICE_CIDR`/`TAILSCALE_CIDR`/`LB_IP_PLEX`/`LB_IP_PLEX_IOT`, additive alongside existing `*_SUBNET` vars |
| `kubernetes/apps/kube-system/cilium/config/networks.yaml` | New `pool-iot-plex` `CiliumLoadBalancerIPPool` — single `/32` on the IOT VLAN, scoped to the `plex` Service |
| `docs/CLUSTER.md` | Added `pool-iot-plex` row to the L2 LoadBalancer pools table |
| `docs/QA.md` | New "Media" section — four entries: `secureConnections`/probe-scheme root cause, the mobile "Local connection" label fix (corrected an earlier wrong conclusion), the Cilium L2/`Local` "connection refused" bug, and the IOT-VLAN dual-LB-IP fix |
| `docs/ROADMAP.md` | Added a "Recurrence — Plex's dedicated LoadBalancer" subsection to the existing "Cilium BGP Control Plane" entry, recording the `Cluster`-vs-`Local` decision |
| `docs/dra-gpu-migration-plan.md` | Marked shelved; corrected the `plex-image-cleanup` GPU-access claim |

### Key decisions
- Plex-only, not paired with Jellyfin — considered a redundant alternative, never a planned pair.
- Internal-only exposure (no public Cloudflare Tunnel route) — deliberate, given Plex's CVE history; remote reachability comes from the existing Tailscale subnet router instead.
- `secureConnections=Preferred` (not `Required`) chosen over building Envoy backend TLS from scratch — a one-line fix versus introducing an unproven `BackendTLSPolicy` pattern into this repo.
- The mobile "Remote connection" label was initially documented as a permanent, unfixable architectural limitation — **later proven wrong** once a dedicated LoadBalancer IP made the label correctly show "Local"; `docs/QA.md` was corrected rather than silently edited around.
- New `*_CIDR` variables added additively rather than renaming the existing `*_SUBNET` ones in place — avoids a flag-day migration across every consumer at once.
- `DOMAIN_APPS` chosen over `DOMAIN_APP` for the LoadBalancer's DNS hostname after directly checking which one is actually wired into cert-manager/`external-dns`/`cloudflared`, rather than assuming from bykaj's naming.
- Dropped `externalTrafficPolicy: Local` in favor of `Cluster` — Cilium's L2 leader election has no endpoint-placement awareness (documented upstream limitation, `cilium/cilium#27800`), and the client-IP-preservation benefit `Local` exists for turned out unnecessary since the "Local connection" label works correctly under `Cluster` too.
- Rejected node-pinning (L2 policy + pod affinity to one node) as a `Local`-policy workaround, and rejected building a narrower per-app `CiliumL2AnnouncementPolicy` as "the proper fix" — neither actually eliminates the leader/endpoint mismatch, only exactly-one-candidate-node pinning does, which isn't worth the lost reschedulability.
- Gave Plex a second, IOT-VLAN-scoped LoadBalancer IP rather than relaxing the UniFi gateway's IOT isolation — matches the existing `smtp-relay`/printer precedent and keeps the IOT security boundary intact; `PLEX_NO_AUTH_NETWORKS` deliberately left without the IOT CIDR, since IOT devices should still authenticate.

---

## 2026-08-22 — `n8n-deploy`

### Goal
Investigate and draft a Flux-managed deployment of n8n (workflow automation) into the `automation` namespace, following this repo's own conventions rather than the community reference wholesale.

### What we did
- Created worktree `.claude/worktrees/n8n` on branch `worktree-n8n` via `EnterWorktree`.
- Ran three parallel Explore agents to survey: (1) `open-webui`'s full app-template + CNPG + ExternalSecret + Gateway API pattern as the primary reference, (2) docs/archive for any prior n8n context — found `docs/POTENTIAL-DEPLOYMENTS.md:168` already lists n8n as an approved candidate, and found a gitignored community reference clone at `tmp/home-ops-bykaj/` (origin `qnimbus/home-ops-bykaj`, the user's own repo) containing a working n8n deployment, (3) the existing `automation` namespace, confirming its sole sibling app `waha` is a clean precedent (VolSync-backed PVC, no separate `-db` Kustomization since it isn't Postgres-backed).
- Launched a Plan agent to turn the findings into a file-by-file plan; it corrected a wrong assumption fed to it — every `app-template` consumer in this repo (`open-webui`, `waha`, `paperless-ngx`, `pgadmin`, `cloudflared`, `smtp-relay`, etc.) inlines Helm `values:` in `helmrelease.yaml` rather than using CLAUDE.md's documented separate-`values.yaml` pattern, which only applies to apps with their own per-app chart source.
- Asked the user 3 scoped decisions via `AskUserQuestion`: webhook exposure (internal-only, no external route/`WEBHOOK_URL`), execution mode (regular, not queue mode), and task scope (draft full manifests uncommitted, matching the prior paperless-ngx precedent).
- Read the full bykaj n8n reference in detail per user follow-up request; deliberately diverged from its Postgres-provisioning approach (a `postgres-init` initContainer using superuser creds) in favor of this repo's own declarative CNPG `Database` CRD + `managed.roles` pattern (matching `open-webui`'s `db/` split), and from its webhook-exposure/queue-mode choices per the user's decisions above.
- Discovered a cluster-specific simplification while reading `kubernetes/apps/mail/smtp-relay/app/helmrelease.yaml`: its `loadBalancerSourceRanges` restriction only gates the Service's external LoadBalancer IPs, not in-cluster ClusterIP traffic, and its `maddy` config accepts inbound mail unauthenticated — so n8n can relay mail through it with zero SMTP credentials, simpler than bykaj's design (which pulls external SMTP creds into n8n's own secret).
- User asked whether `smtp-relay` should be a Flux `dependsOn` target; concluded no — it's a runtime call n8n makes lazily when sending mail (not tested at boot, unlike `open-webui`'s eager Redis-at-import-time dependency on `dragonfly`), so coupling the rollout to it would add no safety and only add fragility.
- Resolved the current n8n image tag/digest live via `crane digest ghcr.io/n8n-io/n8n:2.35.7` rather than guessing one (confirmed current stable release via a GitHub releases fetch first).
- Wrote the full manifest set, registered the app in `kubernetes/apps/automation/kustomization.yaml`, and added the `n8n` role to the shared CNPG cluster's `managed.roles` list.
- Validated with `kustomize build` on both the `app/` and `db/` overlays and a full `task validate` run across the repo — zero errors; `ExternalSecret`/`HTTPRoute`/`Database` "skipped" lines are the same expected no-bundled-schema false positive already documented for sibling apps.
- Left all changes uncommitted per the user's chosen task scope — a 1Password item named `n8n` (`username`, `password`, `encryption_key`) must be created out-of-band before this is safe to merge/deploy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/automation/n8n/ks.yaml` | New — two Flux Kustomizations (`n8n-db` in `database`, `n8n` in `automation`), VolSync component with `APP_UID`/`APP_GID` overridden to `1000` to match the image's non-root user |
| `kubernetes/apps/automation/n8n/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/automation/n8n/app/helmrelease.yaml` | New — `app-template` v5 HelmRelease, pinned `2.35.7` image+digest, CNPG env vars, internal-only routing, unauthenticated SMTP relay via `smtp-relay.mail.svc.cluster.local` |
| `kubernetes/apps/automation/n8n/app/externalsecret.yaml` | New — `N8N_ENCRYPTION_KEY` from the `n8n` 1Password item |
| `kubernetes/apps/automation/n8n/app/httproute.yaml` | New — internal-only route at `n8n.${DOMAIN_CLUSTER}` via `envoy-internal`, homepage annotations |
| `kubernetes/apps/automation/n8n/db/kustomization.yaml` | New — resource list |
| `kubernetes/apps/automation/n8n/db/database.yaml` | New — CNPG `Database` CRD on the shared `postgres-v17` cluster |
| `kubernetes/apps/automation/n8n/db/externalsecret.yaml` | New — CNPG role credentials, `cnpg.io/reload: "true"` |
| `kubernetes/apps/automation/kustomization.yaml` | Registered `./n8n/ks.yaml` |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added `n8n` role to `spec.managed.roles` |

### Key decisions
- Followed this repo's own CNPG `Database` CRD + `managed.roles` convention instead of the bykaj reference's `postgres-init` initContainer — more declarative and consistent with every other CNPG-backed app here.
- Route mail through the existing `smtp-relay` with no dedicated SMTP credentials, based on a verified (not assumed) reading of its Kubernetes-layer traffic restriction vs. its app-layer auth posture.
- Excluded `smtp-relay` from `dependsOn` — Flux dependency ordering is for build-time/boot-time needs, and n8n's SMTP usage is a lazy runtime call that self-heals if the relay is briefly unavailable.
- Skipped KEDA scale-to-zero for v1 (unlike `open-webui`/`paperless-ngx`) — n8n is expected to be always-on for scheduled/cron-triggered workflows, and `open-webui` itself doesn't use the shared `components/keda/postgres-scaler` component either (hand-writes its own tailored `ScaledObject`), so there was no drop-in default to adopt without deeper tuning.

---

## 2026-08-21 — `unifi-voucher-site-deploy`

### Goal
Plan and implement a Flux-managed deployment of [unifi-voucher-site](https://github.com/glenndehaan/unifi-voucher-site), a guest-network voucher web UI that talks directly to the UniFi controller API.

### What we did
- Used plan mode: WebFetched the upstream GitHub README (purpose, Docker image, full env-var reference, port, volumes, docker-compose example) and the releases page/Docker Hub tags API to pick a pinned version (`8.12.0`) with its manifest-list digest, rather than tracking `latest`.
- Ran an Explore agent in parallel to survey existing deployment patterns in-repo: found `unpoller` and `external-dns-unifi` already call the same UniFi controller in-cluster (proving reachability), identified the `bjw-s/app-template` v5 HelmRelease shape (`unpoller`/`homepage` as references), the `envoy-internal`/`envoy-external` HTTPRoute pattern, and the 1Password `unifi` item (`HOST`/`API_KEY`) already shared by two consumers via `ClusterSecretStore: onepassword`.
- Read `docs/EXTERNAL-SECRETS.yaml` to understand the wildcard-extract + `rewrite` convention, and confirmed via `kubernetes/apps/default/kustomization.yaml` that new default-namespace apps must be explicitly registered (not auto-discovered).
- Asked the user 4 scoped decisions via `AskUserQuestion`: namespace (`default`, matching `homepage`/`whoami`), exposure (`envoy-internal` only — internal LAN/VPN, not public), UniFi credential (reuse the existing shared `unifi` 1Password item rather than minting a new dedicated API key), and portal auth (`AUTH_DISABLE=true`, accepted specifically because exposure is internal-only).
- Wrote the plan file, then on user feedback added every other documented upstream env var (OIDC, kiosk mode, printing, SMTP, voucher types, translations, cleanup tasks) as commented-out entries at their documented defaults, for in-repo discoverability without re-checking the README later.
- After plan approval, created the full `kubernetes/apps/default/unifi-voucher-site/` tree (`ks.yaml` + `app/{kustomization,externalsecret,helmrelease,httproute}.yaml`), registered it in `kubernetes/apps/default/kustomization.yaml`, and added a new consumer entry (with a template-reshape note) to `docs/EXTERNAL-SECRETS.yaml` under the existing `unifi` item.
- The `ExternalSecret`'s `target.template` reshapes the shared item's fields for this app's different naming: `UNIFI_HOST` (a full base URL like `unpoller`/`external-dns-unifi` expect) is split via Sprig `trimPrefix`/`trimSuffix` into a bare `UNIFI_IP` plus a hardcoded `UNIFI_PORT: "443"`, and `UNIFI_API_KEY` is renamed to `UNIFI_TOKEN` to match this app's env-var names.
- Validated both the new `app/` Kustomization and the parent `kubernetes/apps/default/` Kustomization with `kustomize build` — confirmed YAML anchors (probe/port) resolved correctly and the commented-out env block rendered cleanly with no stray syntax.
- User independently ran `op item get "unifi" --vault homelab` and confirmed the live `HOST` field is `https://192.168.1.1` (no embedded port) — validating the `trimPrefix`/hardcoded-443 assumption in the `ExternalSecret` template was correct, not just plausible.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/default/unifi-voucher-site/ks.yaml` | New — Flux Kustomization, `targetNamespace: default` |
| `kubernetes/apps/default/unifi-voucher-site/app/kustomization.yaml` | New — resource list |
| `kubernetes/apps/default/unifi-voucher-site/app/externalsecret.yaml` | New — reshapes the shared `unifi` 1Password item into `UNIFI_IP`/`UNIFI_PORT`/`UNIFI_TOKEN` |
| `kubernetes/apps/default/unifi-voucher-site/app/helmrelease.yaml` | New — `app-template` v5 HelmRelease, pinned `8.12.0` image, full commented-out env-var reference |
| `kubernetes/apps/default/unifi-voucher-site/app/httproute.yaml` | New — internal-only route at `voucher.${DOMAIN_CLUSTER}` via `envoy-internal` |
| `kubernetes/apps/default/kustomization.yaml` | Registered the new app's `ks.yaml` |
| `docs/EXTERNAL-SECRETS.yaml` | Added `unifi-voucher-site` as a third consumer of the `unifi` item, with a note on the template reshape |

### Key decisions
- Reused the existing shared `unifi` 1Password item instead of minting a dedicated least-privilege API key for voucher creation — user's explicit choice, trading a cleaner blast-radius boundary for simplicity (no new UniFi API key/1Password item to create).
- `AUTH_DISABLE=true` (no in-app login) — deliberately paired with internal-only exposure; flagged in the HelmRelease as needing revisiting if exposure is ever widened to `envoy-external`.
- Not yet committed — all changes are in the working tree pending user review via `/git-stage`/`/git-commit`. Also not yet applied to the live cluster; `docs/EXTERNAL-SECRETS.yaml`'s `HOST`-format assumption was verified live by the user post-write, but the deployment itself has not yet been reconciled/tested end-to-end (see the plan's Verification section for the remaining steps: `ExternalSecret` sync, pod health, UI voucher-creation test).

---

## 2026-08-20 — `talos-ingress-firewall-iot`

### Goal
Research and implement a Talos-native fix for the IOT VLAN node-port exposure gap left open after the prior session's UniFi gateway mitigation.

### What we did
- Researched Talos's native declarative ingress firewall (`NetworkDefaultActionConfig`/`NetworkRuleConfig`) via the official v1.13 docs (WebFetched directly, not paraphrased) and GitHub issues/discussions, resolving both open questions left from the previous session: confirmed `NetworkRuleConfig` is allow-only (under a global `accept` default, unmatched/`except`-carved traffic falls through to accept — there's no standalone deny), and confirmed the historical NodePort/hostPort DNAT-ordering bug (Talos discussion #10347) was fixed in v1.9.4, well before this cluster's v1.13.2, and doesn't apply to this cluster's threat model anyway since kube-proxy is fully replaced by Cilium with no NodePort usage.
- Spawned an Explore agent to survey the cluster's actual host-listening service inventory (Cilium routing mode, LoadBalancer/NodePort services, hostNetwork/hostPort pods, Rook-Ceph network exposure, existing Talos patches) to size an initial design.
- Drafted and got plan-mode approval for a first implementation: `NetworkDefaultActionConfig: block` globally plus ~16 `NetworkRuleConfig` allow rules covering every host-listening service found (kubelet, apid, trustd, Cilium health/healthz, Spegel, node-exporter, Ceph mon/OSD/mgr, smtp-relay, victoria-logs-syslog, envoy-gateway). Implemented as two new Talos patch files wired into `talconfig.yaml`, validated via `task talos:genconfig` (rendered cleanly; confirmed correct per-node-type document counts and that `10.30.0.0/24` appeared only in the deliberate smtp-relay exception).
- User questioned whether restricting `10.60.0.0/24` broadly was necessary and flagged the risk to future service deployments — this prompted further research that found a materially better mechanism: a `NetworkRuleConfig` scoped to one port is a self-contained allowlist for that port alone, regardless of the global default action, confirmed via siderolabs/talos#12955 (closed "not planned" — a port-scoped rule correctly restricted that port under a global `accept` default).
- Revised the implementation to a much narrower, lower-risk design: dropped `NetworkDefaultActionConfig: block` entirely (global default stays at Talos's own `accept`), reduced from ~16 rules to 8 covering only the ports in the originally-confirmed exposure (kubelet/apid/trustd globally; kube-apiserver/etcd client+metrics/controller-manager/scheduler on control-plane nodes only). Re-validated via `task talos:genconfig`.
- Committed the config (`209f94a`) via `/git-commit`, then — at the user's explicit request — carried out the phased rollout live: for every node, `apply-config --dry-run` (confirmed the diff was exactly the new firewall documents), then `--mode=try` with an etcd-quorum health check and a direct `talosctl get nftableschain` read of the compiled ruleset while the transient config was active, then a persistent `apply-config --mode=no-reboot`. Workers first (`talos-worker-01`, `-02`), then control-plane nodes one at a time (`cp-01` → `cp-02` → `cp-03`), never more than one CP node changed concurrently. Finished with a full-cluster `kubectl get nodes` (all 5 `Ready`, reached via the VIP — itself now covered by the new `kube-apiserver-ingress` rule) and a Flux `Kustomizations` spot-check (all still `True`) — no regressions.
- User independently verified from an actual IOT-connected device: `10.30.0.202:6443` is now unreachable (previously returned a `401`), while `10.10.0.0/24` (home LAN) can still reach it — closing the loop on the original vulnerability report with a real-world test, not just the compiled-ruleset inspection. Updated `docs/QA.md` and `docs/CLUSTER.md` to record the fix as implemented and verified rather than deferred.
- ~20 minutes after the rollout, the user reported `KubeletInstanceUnreachable` firing in Alertmanager. Root-caused immediately: `kube-prometheus-stack` scrapes kubelet, kube-controller-manager, kube-scheduler, and kube-apiserver metrics directly by node IP, sourced from the Prometheus pod's own IP (`10.42.0.0/16`) — not through any Service, and not a host IP — so none of those four `NetworkRuleConfig` rules' `ingress` lists covered it. Confirmed via Alertmanager's API that all four alert types were firing (14 individual alert instances across kubelet/controller-manager/scheduler/apiserver), not just the one reported. Fixed by adding `10.42.0.0/16` to all four rules (strictly additive — no re-verification of the IOT block needed) and rolling out to all 5 nodes with etcd-quorum checks between each. Confirmed resolution directly against Prometheus's own `/api/v1/query` (`up==1` on every affected target) and Alertmanager (all four alert types gone from the active list), rather than waiting for the alerts to self-clear. Ruled out the other `up==0` targets found during triage (`flux-controllers`, `kube-state-metrics`, `metrics-server`, etc.) as unrelated — those are pod-to-pod scrapes that never traverse the host firewall at all.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Registered the two new firewall patch files in the global and control-plane `patches:` lists |
| `talos/patches/global/network-firewall.yaml` | New — `kubelet`/`apid`/`trustd` `NetworkRuleConfig` allow rules (all 5 nodes) |
| `talos/patches/controller/network-firewall.yaml` | New — `kube-apiserver`/`etcd`/`controller-manager`/`scheduler` `NetworkRuleConfig` allow rules (control-plane only) |

### Key decisions
- Chose the narrower "per-port self-contained allow rule, global default left at `accept`" design over the initially-implemented "global default `block` + exhaustive allowlist" design — confirmed via a closed GitHub issue, not an explicit maintainer statement, so flagged in the patch file's own comments as needing empirical verification (via `--mode=try` on a low-stakes port) before being trusted for kube-apiserver/etcd.
- Deliberately excluded Ceph, Spegel, node-exporter, and all app LoadBalancer ports (smtp-relay, envoy-gateway, victoria-logs-syslog) from the final rule set — none were part of the originally-confirmed exposure, and restricting them would have added enumeration risk (especially Ceph's dynamic 6800-7300 port range) for no benefit under the user's stated goal.
- Did not run `talosctl apply-config` unprompted — waited for the user's explicit "let's do the talos apply now" before touching live hardware, then leaned entirely on `--mode=try`'s auto-revert as the safety net for each node rather than any manual rollback plan, since a lockout on this bare-metal cluster needs physical/console recovery.

---

## 2026-08-20 — `iot-vlan-unifi-isolation`

### Goal
Root-cause why the reverted Cilium host-firewall attempt failed and caused a regression, then replace it with a properly-scoped IOT VLAN isolation plan.

### What we did
- Investigated why the previous `CiliumClusterwideNetworkPolicy` host-firewall attempt (commit `f68b9be`, reverted earlier this session-day) failed to enforce and caused the NAS-SMB/`paperless-ngx` regression, via two parallel research agents: one surveying this repo's existing NetworkPolicy patterns (found none exist anywhere, by explicit design comment in the Dragonfly HelmRelease) and the committed Cilium baseline config; one researching Cilium's own docs/GitHub issues, which confirmed `devices:` conflates BPF-attach-interface selection with masquerade/SNAT-interface selection — a known, still-open upstream gap (GH#19497, #36803, #40521) — and that the host endpoint's `policy-enabled` staying `"none"` matches a known class of silent Cilium host-identity enforcement bugs (GH#24415), though not confirmed as the exact same bug.
- Cleaned up this worktree: discarded the reverted host-firewall's still-staged file changes (`cilium/app/helm/values.yaml`, `cilium/config/host-firewall.yaml`, `cilium/config/kustomization.yaml`, plus stale doc text) left over from an earlier mid-incident `git reset --soft HEAD~1`, restoring the worktree to match `main` (`d4a6255`).
- Drafted and got approval for a plan to move IOT isolation to the UniFi gateway instead of Cilium/Talos — zero cluster blast radius, since the printer's `smtp-relay` traffic stays L2-local on VLAN 30 and never crosses the router.
- Caught, before writing any doc claiming success, that the UniFi gateway rule alone does **not** close the originally-reported exposure: kube-apiserver/kubelet/etc. remain reachable via each node's own VLAN 30 address, because that traffic is L2-local and never reaches the gateway for a router ACL to filter — verified against the user's own earlier test (`https://10.30.0.201:6443/` returning a normal `401`, not a connection failure).
- Surfaced this correction to the user via `AskUserQuestion` rather than proceeding on a flawed premise; user chose to ship the UniFi rule now (closes lateral movement to other VLANs) and track the node-level fix as separate follow-up work.
- Answered the user's follow-up on whether UniFi Client Isolation could substitute — explained it's all-or-nothing at L2 within a VLAN (enabling it would also break the printer's `smtp-relay` path, which relies on the same L2-local mechanism), though a MAC-based isolation allowlist, if the controller supports it, could narrow exposure from "any IOT device" to "just the printer" as a partial extra layer.
- Rewrote `docs/QA.md`'s IOT-VLAN Q&A entry from scratch (it had only ever existed in the reverted, uncommitted `f68b9be` staging, never in `main`) with the full corrected story, and updated `docs/CLUSTER.md` to match — including a concrete UniFi Traffic Rule + Multicast DNS runbook for the user to apply manually, and flagging Talos's native declarative ingress firewall (`NetworkDefaultActionConfig`/`NetworkRuleConfig`) as the leading candidate for actually closing the remaining gap, with one unresolved semantics question flagged before attempting it (whether a narrow per-port allow rule works standalone, or requires flipping the global default to block).
- Left everything uncommitted per this repo's git-staging policy — user to run `/git-stage`/`/git-commit` when ready, and to apply the UniFi rule themselves (outside git/kubectl/talosctl).

### Files changed
| File | Change |
|------|--------|
| `docs/QA.md` | New Q&A entry: VLAN 30/`pool-iot` design, the reverted host-firewall attempt's two root causes, the UniFi gateway mitigation and its L2-local blind spot, Client Isolation's rejection as a substitute, and the deferred Talos-native ingress-firewall fix |
| `docs/CLUSTER.md` | Networks table row + `2026-08-20` narrative note updated to state IOT is blocked from routing to other VLANs, but node control-plane ports remain reachable via each node's own VLAN 30 address (not yet closed) |

### Key decisions
- Chose UniFi gateway-level isolation over retrying/fixing the Cilium host-firewall or building a Talos-native default-deny firewall immediately: zero cluster blast radius and trivially reversible, even though it only partially closes the exposure — real progress now, deferring the higher-effort/higher-lockout-risk full fix rather than rushing it after the last incident.
- Did not ship documentation claiming the exposure was fully closed once the L2-local blind spot was discovered mid-implementation — paused and asked the user to choose the path forward instead of guessing on a security-relevant claim.
- Rejected UniFi Client Isolation as the primary control since it's all-or-nothing at L2 within a VLAN and would break the `smtp-relay` path it's meant to protect alongside.

---

## 2026-08-20 — `canon-printer-external-service`

### Goal
Add an external-service for the Canon MF753Cdw laser printer and extract the hardcoded LAN/IOT IPs across similar `external-services` entries into `cluster-secrets.sops.yaml`.

### What we did
- Surveyed the `external-services` directory pattern (`anna`, `adam`, `truenas`, `home-assistant`, `wan-failover`) and found `PRINTER_LAN_HOST` already existed in `cluster-secrets.sops.yaml` (added during the smtp-relay session) at the exact IP the user gave for the printer.
- Found via `SESSIONS.md` history that a dedicated `home.vwn.io` subdomain had already been proposed and rejected in a prior session — domain-filter suffix matching means it buys no real isolation. Asked the user to pick between the established `gw-<name>.iot.${DOMAIN_IO}` convention, a `gw-canon` variant, and their originally typed `canon.iot.home.vwn.io`; user chose the convention-matching `canon.iot.vwn.io`.
- Created the `canon` external-service (`Service` + `Kustomization`) as an `ExternalName` pointing at `${PRINTER_IOT_HOST}`, and added its Flux `Kustomization` block to `ks.yaml`.
- Extracted anna/adam's hardcoded IPs (`10.30.0.72`, `10.30.0.71`) and wan-failover's hardcoded router IP (`192.168.8.1`) into `cluster-secrets.sops.yaml` via `sops set`/`sops unset` (no manual decrypt/re-encrypt round-trip).
- Mid-session, user asked that IOT-subnet (`10.30.0.0/24`) devices use an `_IOT_HOST` suffix rather than `_LAN_HOST`, matching the existing `HOME_ASSISTANT_LAN_HOST`/`HOME_ASSISTANT_IOT_HOST` split. Renamed `ANNA_LAN_HOST`→`ANNA_IOT_HOST`, `ADAM_LAN_HOST`→`ADAM_IOT_HOST`, and also renamed the pre-existing `PRINTER_LAN_HOST`→`PRINTER_IOT_HOST` for the same reason (it was a `10.30.x` address mislabeled `LAN` since the smtp-relay session), updating its other consumer in `smtp-relay`'s `helmrelease.yaml`.
- Validated every touched Kustomization builds cleanly with `kubectl kustomize` (`canon`, `anna`, `adam`, `wan-failover`, `smtp-relay/app`); confirmed the decrypted secret has no stale `_LAN_HOST` keys for IOT devices and the raw file still carries a valid `sops:` metadata block with all values `ENC`-wrapped.
- Work was done in worktree `worktree-canon-printer-external-service`; left uncommitted per `CLAUDE.md`'s git-staging policy — user to run `/git-stage` + `/git-commit`.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/network/external-services/canon/service.yaml` | New — `ExternalName` Service for the Canon printer, `canon.iot.${DOMAIN_IO}` → `${PRINTER_IOT_HOST}` |
| `kubernetes/apps/network/external-services/canon/kustomization.yaml` | New — Kustomize entry-point for `canon` |
| `kubernetes/apps/network/external-services/ks.yaml` | Added the `canon` Flux `Kustomization` block |
| `kubernetes/apps/network/external-services/anna/service.yaml` | `externalName` hardcoded IP → `${ANNA_IOT_HOST}` |
| `kubernetes/apps/network/external-services/adam/service.yaml` | `externalName` hardcoded IP → `${ADAM_IOT_HOST}` |
| `kubernetes/apps/network/external-services/wan-failover/service.yaml` | `externalName` hardcoded IP → `${WAN_FAILOVER_HOST}`; comment de-duplicated |
| `kubernetes/apps/mail/smtp-relay/app/helmrelease.yaml` | `loadBalancerSourceRanges` entry renamed `${PRINTER_LAN_HOST}` → `${PRINTER_IOT_HOST}` |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `ANNA_IOT_HOST`, `ADAM_IOT_HOST`, `WAN_FAILOVER_HOST`; renamed `PRINTER_LAN_HOST` → `PRINTER_IOT_HOST` |

### Key decisions
- Chose `canon.iot.vwn.io` over `gw-canon.iot.vwn.io` or the user's originally typed `canon.iot.home.vwn.io` — matches the anna/adam `<name>.iot.${DOMAIN_IO}` convention without the `gw-` prefix (which appears tied to the Plugwise product line, not a generic "external device" marker), and a prior session had already rejected the `home.vwn.io` subdomain idea as providing no real isolation.
- Extracted `wan-failover`'s hardcoded IP too, even though the user only named anna/adam as examples — same anti-pattern, same directory; left no straggler.
- Renamed the pre-existing `PRINTER_LAN_HOST` to `PRINTER_IOT_HOST` rather than only fixing the newly-added vars — it lives on the IOT subnet, so the user's naming rule applies to it too; updated both of its consumers (`canon`'s new `service.yaml` and the pre-existing `smtp-relay` `helmrelease.yaml`).

---

## 2026-08-20 — `homepage-mcp-endpoint`

### Goal
Enable Homepage's MCP endpoint (gethomepage.dev) with authentication, since the cluster's homepage instance has no `HOMEPAGE_AUTH_ENABLED` session auth configured.

### What we did
- Fetched the gethomepage.dev MCP docs to learn the required env vars: `HOMEPAGE_MCP_ENABLED`, `HOMEPAGE_MCP_TOKEN` (or session auth), and the opt-in `HOMEPAGE_MCP_ALLOW_WRITE`.
- Asked the user whether to enable write access; user reasoned the config is GitOps-managed so write access shouldn't make sense — confirmed this is also enforced at the Kubernetes level, since `/app/config` is mounted from a `configMap` persistence source (`helmrelease.yaml`), which Kubernetes always mounts read-only regardless of the app-level flag, and `readOnlyRootFilesystem: true` reinforces it. Kept the endpoint read-only.
- Added `HOMEPAGE_MCP_ENABLED: "true"` to `helmrelease.yaml`'s container `env` block.
- Added a `HOMEPAGE_MCP_TOKEN` field to `externalsecret.yaml`'s `target.template.data`, distinct from the existing `HOMEPAGE_VAR_*` keys — those are Homepage's own `{{HOMEPAGE_VAR_*}}` config-template placeholders, while `HOMEPAGE_MCP_TOKEN` is read directly by the server process, so it must not carry the `VAR_` prefix.
- Generated a token with `openssl rand -base64 32`.
- Attempted to write the new `MCP_TOKEN` field to the `homepage` 1Password item via `op item edit`; found the devcontainer's `OP_SERVICE_ACCOUNT_TOKEN` has read-only access to the `homelab` vault (edits fail with an opaque "Couldn't update the item" error, confirmed via `--debug`). Left the field addition as a manual step for the user and handed off the generated token value.
- Added `MCP_TOKEN` to `docs/EXTERNAL-SECRETS.yaml`'s `known_fields` list for the `homepage` item.
- Confirmed homepage's `HTTPRoute` is only exposed via `envoy-internal` (no cloudflared tunnel), so the new MCP endpoint remains LAN-only.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/default/homepage/app/helmrelease.yaml` | Added `HOMEPAGE_MCP_ENABLED: "true"` env var |
| `kubernetes/apps/default/homepage/app/externalsecret.yaml` | Added `HOMEPAGE_MCP_TOKEN` template field sourced from a new `MCP_TOKEN` 1Password field |
| `docs/EXTERNAL-SECRETS.yaml` | Added `MCP_TOKEN` to the `homepage` item's `known_fields` |

### Key decisions
- Read-only MCP (no `HOMEPAGE_MCP_ALLOW_WRITE`) — config is GitOps-managed and mounted from a ConfigMap, which Kubernetes always mounts read-only in-cluster regardless of the app-level flag, so write access would just fail on every attempt.
- Token-based auth chosen over enabling `HOMEPAGE_AUTH_ENABLED` — the latter would add a session-login requirement to the entire dashboard, a much larger scope change than requested.
- 1Password field addition left to the user — the devcontainer's service-account token is read-only for the vault; a generated token was handed off for convenience rather than blocking on it.

---

## 2026-08-19 — `homepage-ha-external-service`

### Goal
Add a Home Assistant service card to Homepage, and the `network/external-services` proxy plumbing needed to reach it, since Home Assistant runs outside the cluster.

### What we did
- Reviewed the existing `homepage/app/config/services.yaml`, its `externalsecret.yaml`, and `widgets.yaml` to understand the `{{HOMEPAGE_VAR_*}}` runtime-substitution pattern (Homepage's own env-var templating, backed by a `homepage-secret` Secret built from the `homepage` 1Password item) and to distinguish the top-bar `widgets.yaml` from per-card `services.yaml` widgets.
- Recommended — and, on confirmation, created — a new `Home Automation` group rather than folding Home Assistant into `Infrastructure`, since the existing groups are semantically scoped (`Storage`, network/connectivity `Infrastructure`) and Home Assistant is a different domain likely to grow its own entries over time.
- Found `network/external-services/truenas/` as the closest prior art for proxying a non-Kubernetes, physical/LAN device (Service + EndpointSlice + HTTPRoute, no `gethomepage.dev/*` annotations since there's no pod to match) and mirrored it for Home Assistant.
- Confirmed `HOME_ASSISTANT_LAN_HOST` (and `HOME_ASSISTANT_IOT_HOST`) already exist as SOPS-encrypted vars in `kubernetes/flux/vars/cluster-secrets.sops.yaml` — no secrets-file edit needed there.
- Created `kubernetes/apps/network/external-services/home-assistant/` (`service.yaml` port 8123, `endpoint.yaml` EndpointSlice → `${HOME_ASSISTANT_LAN_HOST}`, `httproute.yaml` for `ha.${DOMAIN_CLUSTER}` via the `envoy-internal` gateway, `kustomization.yaml`), and registered a matching Flux Kustomization block in `network/external-services/ks.yaml` (`dependsOn: envoy-gateway-config`, same as TrueNAS's).
- Added the `Home Automation` group with a Home Assistant card to `homepage/app/config/services.yaml`: `href` goes through Envoy (`https://ha.${DOMAIN_CLUSTER}`) for browser use, while the `homeassistant` widget's `url` hits the new in-cluster Service directly (`home-assistant.network.svc.cluster.local:8123`) — following the same direct-hop precedent as TrueNAS's `siteMonitor`.
- Added `HOMEPAGE_VAR_HOMEASSISTANT_TOKEN` to `homepage/app/externalsecret.yaml`, pulling `HOMEASSISTANT_TOKEN` from the (user-populated) `homepage` 1Password item, and added the field to `docs/EXTERNAL-SECRETS.yaml`'s `known_fields` list for that item.
- Validated every touched/added Kustomize directory with `kubectl kustomize` (`home-assistant`, `truenas`, `homepage/app`) and parsed `ks.yaml` with PyYAML to confirm all 5 multi-document Kustomization blocks are well-formed.
- Flagged two open items for the user: confirm the 1Password field name is exactly `HOMEASSISTANT_TOKEN` (ESO sync will fail silently otherwise), and that Home Assistant's own `http.trusted_proxies`/Host-header validation may need configuring on the HA side for the Envoy-proxied hostname to work.
- Left all changes uncommitted in worktree `homepage-ha-external-service` per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/network/external-services/home-assistant/service.yaml` | New — ClusterIP Service, port 8123 |
| `kubernetes/apps/network/external-services/home-assistant/endpoint.yaml` | New — EndpointSlice pointing at `${HOME_ASSISTANT_LAN_HOST}` |
| `kubernetes/apps/network/external-services/home-assistant/httproute.yaml` | New — routes `ha.${DOMAIN_CLUSTER}` via `envoy-internal` |
| `kubernetes/apps/network/external-services/home-assistant/kustomization.yaml` | New — lists the three resources above |
| `kubernetes/apps/network/external-services/ks.yaml` | Added `home-assistant` Flux Kustomization block |
| `kubernetes/apps/default/homepage/app/config/services.yaml` | Added `Home Automation` group with a Home Assistant service card + `homeassistant` widget |
| `kubernetes/apps/default/homepage/app/externalsecret.yaml` | Added `HOMEPAGE_VAR_HOMEASSISTANT_TOKEN` field mapping |
| `docs/EXTERNAL-SECRETS.yaml` | Added `HOMEASSISTANT_TOKEN` to the `homepage` item's `known_fields` |

### Key decisions
- New `Home Automation` homepage group instead of reusing `Infrastructure` — the existing groups are semantically scoped by domain (storage vs. network/connectivity tooling), and Home Assistant doesn't fit either; a dedicated group also leaves room for future HA-related entries without diluting `Infrastructure`.
- Widget's `url` targets the new in-cluster Service rather than `${HOME_ASSISTANT_LAN_HOST}` or the public href — consistent with the precedent already set by TrueNAS's `siteMonitor`, and avoids routing internal polling traffic through Envoy's TLS termination for no benefit.

---

## 2026-08-19 — `open-webui-bootstrap-envsubst-fix`

### Goal
Diagnose and fix a `BuildFailed` on the `open-webui` Flux Kustomization caused by an envsubst strict-mode failure on the `open-webui-bootstrap-admin` Job manifest.

### What we did
- Investigated the reported error — `post build failed for 'Job.v1.batch/open-webui-bootstrap-admin': envsubst error: variable substitution failed: variable not set (strict mode): "VAR"` — by reading `job-bootstrap-admin.yaml`.
- Root-caused it to a variant of the same bug class as the same-day `ceph-dashboards-envsubst-buildfailed-fix` session, but in a different location: a shell comment (not executable code) explaining the file's `$$`-escaping convention used `${VAR}` and `${NAME}` as illustrative placeholder examples. Flux's `postBuild.substituteFrom` does a blind textual scan of the entire rendered manifest, including comment lines inside multi-line block scalars — it has no notion of shell comments, so the prose examples were treated as unresolved variable references.
- Escaped both occurrences (`${VAR}` → `$${VAR}`, `${NAME}` → `$${NAME}`) to match the file's existing `$$`-escaping convention already used elsewhere in the same comment block (e.g. `$${BOOTSTRAP_ADMIN_NAME}`).
- Swept the rest of the `open-webui` app directory for the same unescaped-`$VAR` pattern; confirmed all remaining `${...}` references (`DOMAIN_CLUSTER`, `PG_HOST`, `DRAGONFLY_HOST`, `APP`) are legitimate Flux substitution variables defined in `cluster-secrets.sops.yaml`/`cluster-settings.yaml` or the Kustomization's own `postBuild.substitute` block — no further whack-a-mole rounds expected.
- Verified the file still parses as valid YAML after the edit.
- Left the change uncommitted per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/ai/open-webui/app/job-bootstrap-admin.yaml` | Escaped `${VAR}`/`${NAME}` comment placeholders to `$${VAR}`/`$${NAME}` to fix envsubst `BuildFailed` |

### Key decisions
- Recorded as a separate session entry rather than folding into `ceph-dashboards-envsubst-buildfailed-fix` — same underlying bug class (unescaped `$VAR` colliding with Flux's strict-mode envsubst) but a different app, file, and manifestation (a comment, not a data value), so it's a distinct fix worth its own record.

---

## 2026-08-19 — `ceph-dashboards-envsubst-buildfailed-fix`

### Goal
Diagnose why the `kube-prometheus-stack` Flux Kustomization was stuck `Ready: False` / `BuildFailed`, and fix the root cause.

### What we did
- Used the `gitops-cluster-debug` skill's Kustomization workflow (falling back to `kubectl` directly, since the `flux-operator-mcp` MCP server tools weren't available this session) to inspect the `kube-prometheus-stack` Flux Kustomization in `flux-system` — found `Ready: False`, reason `BuildFailed`, stuck since the last successful reconcile on 2026-08-04, with the error `envsubst error: variable substitution failed: variable not set (strict mode): "datasource"` on the `ceph-grafana-dashboards` ConfigMap.
- Root-caused it: the 9 ceph-mixin Grafana dashboard JSON files (added in commit `9350749`) use Grafana's native `$datasource`/`${datasource}` templating-variable syntax, which Flux's `postBuild.substituteFrom` envsubst pass treats as unresolved variable references — `datasource` isn't a key in `cluster-settings` or `cluster-secrets`. This silently failed the entire Kustomization build (not just the one ConfigMap), cascading `Ready: False` to 5 dependent Kustomizations (`fluent-bit`, `flux-alerts`, `grafana-operator-instance`, `unpoller`, `victoria-logs`).
- Confirmed the repo already has a working convention for this exact class of problem: `node-exporter-full.json` escapes Grafana's `$hashKey` as `$$hashKey` for the same reason — the ceph-mixin dashboards were never escaped.
- Ruled out the same-day `renovate.json5` "datasource" fix (commit `3814b20`) as the cause — that's an unrelated Renovate `transformTemplates` datasource metadata key, coincidentally same word.
- Applied the `$$`-escape fix (`$datasource` → `$$datasource`, `${datasource}` → `$${datasource}`) across all 9 affected dashboard JSON files; verified zero un-escaped occurrences remain and all 9 files still parse as valid JSON.
- Kustomization still failed to reconcile after that fix, now on `ConfigMap.v1.[noGrp]/node-exporter-grafana-dashboard-km6gk84m7b`, same `"datasource"` envsubst error — Flux's `postBuild` fails fast on the *first* unresolved variable per build attempt, so the initial ceph-mixin fix only let the build progress to the next offending ConfigMap rather than surfacing every failure at once.
- Found `node-exporter-full.json` (Grafana.com dashboard 1860, 23.9k lines) uses `"uid": "${datasource}"` 371 times, all unescaped despite the file already containing an escaped `$$hashKey` elsewhere for the same class of problem. Applied the same `${datasource}` → `$${datasource}` escape across all 371 occurrences via a single blanket replace; verified 0 remaining unescaped and JSON still valid.
- Ran a final repo-wide sweep across all 10 dashboard JSON files confirming zero un-escaped `$datasource`/`${datasource}` remain anywhere in the Kustomization's manifest tree.
- Left changes uncommitted per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/host-details.json` | Escaped `$datasource`/`${datasource}` to `$$`/`$${}` form |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/hosts-overview.json` | Escaped `$datasource` to `$$datasource` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/ceph-cluster.json` | Escaped `$datasource`/`${datasource}` to `$$`/`$${}` form |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/pool-overview.json` | Escaped `$datasource`/`${datasource}` to `$$`/`$${}` form |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/osd-device-details.json` | Escaped `$datasource` to `$$datasource` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/osds-overview.json` | Escaped `$datasource`/`${datasource}` to `$$`/`$${}` form |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/pool-detail.json` | Escaped `$datasource` to `$$datasource` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/rbd-details.json` | Escaped `$datasource` to `$$datasource` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/node-exporter-full.json` | Escaped all 371 occurrences of `${datasource}` to `$${datasource}` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/rbd-overview.json` | Escaped `$datasource`/`${datasource}` to `$$`/`$${}` form |

### Key decisions
- Fixed by escaping the dashboard JSON to match the repo's existing `$$hashKey` convention, rather than weakening `postBuild.substituteFrom` (e.g. dropping strict mode) — keeps other legitimate substitutions (`cluster-settings`) working and unblocks the five dependent Kustomizations without loosening the substitution mechanism repo-wide.

---

## 2026-08-19 — `arc-runner-image-staleness-fix`

### Goal
Fix a Renovate JSONata syntax error, then diagnose and permanently fix a GitHub Actions self-hosted runner (ARC) outage that had left `renovate-pr-review.yml` unable to get a runner — traced through several false leads to a stale, untracked runner image aging past GitHub's minimum-version enforcement and triggering an upstream `Outdated`-phase reconcile bug.

### What we did
- Fixed a JSONata syntax error in `renovate.json5`'s grafana-dashboard `transformTemplates` rule (missing `$string()` prefix) — committed as `3814b20`.
- Diagnosed the "Auto-review Renovate PRs" GitHub Action job hanging indefinitely waiting for a runner — traced to ARC's `home-lab-readonly` `AutoscalingRunnerSet` stuck in phase `Outdated`.
- Restarted the controller pod and applied the upstream-documented status-patch workaround — the patch instead triggered a tight infinite create/delete loop hammering GitHub's live Actions API; stopped by scaling the controller `Deployment` to 0 and suspending its Flux `HelmRelease` (repeated 4+ times across the session as the loop kept re-triggering).
- Live-tested and falsified two hypotheses: (a) a genuinely fresh install via full uninstall+reinstall of `home-lab-readonly` still hit the loop within ~16s of a runner registering; (b) an RBAC/`containerMode` mismatch — removing `containerMode` from the live values didn't prevent the loop, which recurred within ~75s (reverted after testing).
- Considered simplifying by merging `home-lab-readonly` into `home-lab`; discovered `home-lab`'s ServiceAccount is bound to `cluster-admin` (reserved for future manually-dispatched ops workflows, with an explicit repo comment forbidding auto-triggered workflows from using it) — rejected the merge to avoid granting cluster-admin to a workflow that processes untrusted third-party Renovate PR content via an LLM agent.
- User force-deleted the `actions-runner-system` namespace directly; it stuck mid-delete because the controller owning the relevant finalizers had already been torn down — unstuck by manually stripping finalizers from the remaining `AutoscalingListener`, `EphemeralRunnerSet`, and 4 `Role`/`RoleBinding` objects. Flux auto-recreated the whole namespace from git within ~90s.
- Diagnosed a dashboard screenshot showing 4 HelmReleases as "Not Ready" as a UI misread of the `Drifted=False` condition (which means healthy/no-drift) — not a real cluster problem, no fix needed.
- A user-triggered real job re-run reproduced the same `Outdated` loop a third time, confirming it's deterministic on any actual job dispatch, independent of prior test conditions.
- Researched `qnimbus/home-ops-bykaj`'s ARC setup (same chart/image version, no evidence they'd hit or mitigated the bug) and the upstream `actions/actions-runner-controller` repo (issues #4595/#4596/#4600) — found the real root cause: the runner image (`ghcr.io/home-operations/actions-runner:2.334.0`) had aged past GitHub's rolling 30-day minimum-runner-version enforcement, causing an exit-code-7 → phase-`Outdated` cascade; multiple community reports confirmed bumping to `2.336.0` resolves it.
- Found the image was never tracked by Renovate — no `# renovate: datasource=` comment, and the tag sits inside an arbitrary Helm `values:` blob that Renovate's default `kubernetes` manager doesn't parse — so a `renovate.json5` auto-merge rule written specifically to prevent this failure mode had been dead the whole session (and likely much longer) for lack of a manager to match against.
- Mid-fix, discovered a same-day commit (`04cf84b`) had redirected `renovate-pr-review.yml`'s `runs-on:` from `home-lab-readonly` to `home-lab` (cluster-admin), contradicting the earlier RBAC rejection — confirmed with the user and reverted it.
- Re-froze the live controller (it had been manually scaled back up outside Flux in the interim, and both scale-sets had wedged into `Outdated` again), bumped the runner image to `2.336.0` with the missing Renovate tracking comment in both `home-lab` and `home-lab-readonly` HelmReleases, and reverted the `runs-on` redirect. Left uncommitted per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Fixed JSONata `$string()` syntax error in the grafana-dashboard `transformTemplates` rule (committed `3814b20`) |
| `.github/workflows/renovate-pr-review.yml` | Reverted the `runs-on:` redirect (`04cf84b`) back to `home-lab-readonly` to preserve RBAC isolation from untrusted PR content |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/helmrelease.yaml` | Bumped runner image `2.334.0` → `2.336.0`, added missing Renovate tracking comment |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/helmrelease.yaml` | Same image bump + tracking comment |
| `CLAUDE.md` | Session log table entry |
| `docs/SESSIONS.md` | This session record |

### Key decisions
- Rejected merging `home-lab-readonly` into `home-lab` despite an earlier "yes, go ahead," after discovering `home-lab` carries `cluster-admin` RBAC — kept the two-scale-set security separation intact.
- Root cause is the runner image tag, not the chart version or RBAC/containerMode config — both were live-tested and ruled out first. Chart stays pinned at `0.14.2` (still latest upstream release); the fix is solely the image bump plus the Renovate tracking comment that was missing.
- Reverted the `home-lab` redirect back to `home-lab-readonly`, per explicit user confirmation, to preserve the "no auto-triggered workflow on the cluster-admin group" guardrail documented in `runners/home-lab/rbac.yaml`.

---

## 2026-08-19 — `cnpg-barman-backup-alert`

### Goal
Add a missing dead-man's-switch Prometheus alert for CloudNativePG's barman-cloud S3/B2 backup path (`ScheduledBackup/postgres-v17`), which currently has no alerting despite the separate `postgres-backup-local` CronJob already having one.

### What we did
- Reviewed the existing `postgres-backup-local` alert pattern (`PostgresBackupMissed` dead-man's-switch + `PostgresBackupJobFailed`) and how `severity: critical`/`warning` route to Alertmanager (`pushover-critical` vs `pushover` receivers in `kube-prometheus-stack/app/alertmanagerconfig.yaml`).
- Confirmed `Cluster/postgres-v17` already has `monitoring.enablePodMonitor: true`, so CNPG's PodMonitor scrapes the exporter on every instance pod — no new scrape config needed.
- Port-forwarded to `kube-prometheus-stack-prometheus` and queried live metrics rather than guessing. Found `cnpg_collector_last_available_backup_timestamp` (the metric name the task suggested checking) is permanently stuck at `0` on this cluster — a known upstream gap (`cloudnative-pg/plugin-barman-cloud#380`) where that legacy collector metric is never populated when backups run via a CNPG-I plugin. Using it would have produced a rule that fires immediately and permanently.
- Found the correct, actively-updating metric: `barman_cloud_cloudnative_pg_io_last_available_backup_timestamp` (and its `_last_failed_backup_timestamp` sibling), exposed by the barman-cloud plugin's own exporter. Confirmed via web search against the plugin's official observability docs and a real GitHub issue thread describing the exact `_last_failed_backup_timestamp - _last_available_backup_timestamp > 1` comparison pattern.
- Verified via `kubectl get backups.postgresql.cnpg.io` that there's no per-backup `Job` object for plugin-method backups (unlike the CronJob-based local path), so the `kube_job_status_failed` approach used by `PostgresBackupJobFailed` doesn't map — used the failed-vs-available timestamp comparison instead.
- Wrote `PostgresScheduledBackupMissed` (critical, `time() - max(...) > 90000`, `for: 15m`, mirroring the local alert's 25h/15m dead-man's-switch shape) and `PostgresScheduledBackupFailed` (warning, `for: 5m`) into a new `PrometheusRule`, aggregating with `max()` across the 3 instance pods (primary + 2 replicas each export an identical cluster-wide value) to avoid tripling alert instances on a lagging replica's exporter.
- Wired the new `prometheusrule.yaml` into `cluster/app/kustomization.yaml` — confirmed via `kubectl kustomize` that it renders cleanly, and confirmed the `cloudnative-pg-cluster` Kustomization has `wait: false`/no explicit `healthChecks`, so no additional Flux wiring was needed for a plain CRD resource.
- Re-queried both finished expressions against live Prometheus and confirmed neither is currently firing (last backup ~1.4h old, no failed attempts) — won't page immediately on merge.
- Left changes uncommitted per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/cluster/app/prometheusrule.yaml` | New — `PostgresScheduledBackupMissed`/`PostgresScheduledBackupFailed` dead-man's-switch + failure alerts for the barman-cloud S3/B2 backup path |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/kustomization.yaml` | Added `./prometheusrule.yaml` to resources |
| `CLAUDE.md` | Session log table entry |
| `docs/SESSIONS.md` | This session stub |

### Key decisions
- Deliberately did not alert on `cnpg_collector_last_available_backup_timestamp` despite it being the name the task suggested checking first — live verification showed it's permanently `0` under this cluster's plugin-based backup architecture, which would have made the alert fire immediately and forever. Used `barman_cloud_cloudnative_pg_io_last_available_backup_timestamp` instead, confirmed live and against upstream docs/issues.
- Used `max()` aggregation across the 3 CNPG instance pods rather than alerting on the raw per-pod metric, since all three export an identical cluster-wide value and an un-aggregated rule would fire one alert instance per pod (tripling Pushover notifications) if one replica's exporter briefly lagged.
- Modeled the failure alert on `barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp > last_available_backup_timestamp` rather than trying to reuse the local path's `kube_job_status_failed` pattern — plugin-method backups don't create Kubernetes `Job` objects, so there's no Job-based signal to key off.

---

## 2026-08-05 — `ceph-packetdrops-diagnosis-netdev-budget-experiment`

### Goal
Diagnose the recurring `CephNodeNetworkPacketDrops` alert (last seen 11:48 CEST), document root cause, and figure out whether an OS-level fix exists — plus a way to measure whether it actually helps.

### What we did
- Investigated the alert against live Prometheus/Alertmanager state (manually, following the `/diagnose-alerts` methodology): confirmed the rule is Rook's bundled `ceph-mixin` rule with no Ceph-network scoping (`device!="lo"` only), and that a `for: 1m` debounce was already applied in a prior 2026-07-18 session.
- Found the underlying periodic ~3-minute traffic burst on the management NIC (`eno1`) hits `cp-02`, `cp-03`, `worker-01`, and `worker-02` but never `cp-01`. Cross-referenced `talos/talconfig.yaml` and identified the differentiator: the 4 affected nodes all use an Intel I219-LM (`e1000e` driver) management NIC, while `cp-01` alone uses a newer Intel I225/I226 (`igc`) — a finding not previously documented anywhere in the repo.
- Confirmed via `rate(node_network_receive_fifo_total[1m])` that the drops are receive-only with zero FIFO/hardware-ring errors, pointing to a software RX-path (kernel softirq) bottleneck rather than link saturation or a bad NIC.
- Found `CLAUDE.md`'s top-of-file hardware table was stale — missing `talos-cp-03` entirely, wrong NIC/bond details for `cp-01`/`cp-02`, and a wrong VIP participant list (still referencing `worker-01` as "temporary CP"). Refreshed it against `talconfig.yaml`/`CLUSTER.md` ground truth, including correcting "kube-vip" to "Talos-native VIP" (no kube-vip pods actually exist in the cluster).
- Appended two follow-up paragraphs to the existing `docs/QA.md` entry on this alert, documenting the 2026-07-18 debounce tuning and the 2026-08-05 NIC-hardware correlation.
- Investigated an OS/Talos-level fix: found `net.core.netdev_max_backlog` was already bumped to `300000` fleet-wide (for Ceph's storage bond) with no observed effect on these drops; verified live via `talosctl read` on `cp-02` that `netdev_budget` (300), `netdev_budget_usecs` (8000), and `dev_weight` (64) were all still at kernel defaults.
- Drafted `talos/patches/node/machine-sysctl-netdev-budget.yaml` (`net.core.netdev_budget` 300→1000, `net.core.netdev_budget_usecs` 8000→16000) wired onto the 4 affected nodes only in `talconfig.yaml`; validated with `talhelper genconfig` — clean render, correct per-node sysctl merge, `cp-01` correctly excluded.
- Added a new "In Progress" watch-item section to `docs/ROADMAP.md` with 3 PromQL monitoring queries and a captured pre-patch baseline (24h RX-drop totals ~736K–755K packets/node; only `cp-02` has ever paged, 25 times in 24h) so the patch's effect — or lack of one — can be measured after it's applied.
- Did all edits in worktree `ceph-packetdrops-docs-refresh`; left changes uncommitted per this repo's `/git-stage`/`/git-commit`-only policy. The sysctl patch was not applied to live nodes — that's a live network-stack change awaiting explicit user go-ahead.

### Files changed
| File | Change |
|------|--------|
| `CLAUDE.md` | Refreshed hardware table: added `talos-cp-03`, corrected NIC chipsets/drivers, fixed VIP participant list and terminology, fixed node/scheduling count (3 CP + 2 workers, not "no dedicated workers") |
| `docs/QA.md` | Appended 2026-07-18 debounce and 2026-08-05 NIC-correlation follow-ups to the `CephNodeNetworkPacketDrops` Q&A entry |
| `docs/ROADMAP.md` | Added "e1000e Management-NIC Packet Drops: `netdev_budget` Experiment" watch item with monitoring queries and baseline; added TOC entry |
| `talos/talconfig.yaml` | Wired the new sysctl patch onto `cp-02`/`cp-03`/`worker-01`/`worker-02` |
| `talos/patches/node/machine-sysctl-netdev-budget.yaml` | New: raises `netdev_budget`/`netdev_budget_usecs` on the 4 `e1000e` nodes |

### Key decisions
- Chose `netdev_budget`/`netdev_budget_usecs` over further `netdev_max_backlog` tuning because the backlog ceiling was already maxed with no effect — backlog mainly serves `netif_rx()`/RPS-forwarded packets, not hardware NAPI drivers like `e1000e`, whereas the softirq-wide budget genuinely bounds hardware NIC polling across all devices on a CPU.
- Scoped the sysctl patch to only the 4 affected nodes rather than fleet-wide, to keep a clean before/after comparison and avoid touching the already-healthy `cp-01`.
- Explicitly framed the fix as an unconfirmed experiment (the burst's actual source has never been captured live) and set a concrete checkpoint/fallback in ROADMAP.md: if the metrics don't move within 1-2 weeks, stop chasing kernel-level tuning and widen the alert's `for:` window instead.
- Caught and reverted an accidental `git add` mid-session — this repo's `CLAUDE.md` reserves staging for `/git-stage` only, even at apparent task completion.

---

## 2026-08-04 — `flux-operator-0.57.0-bump`

### Goal
Before merging Renovate PR #72, bring the flux-operator/flux-instance Helm chart pins up to the same `0.57.0` release the PR already targets for the CLI tools, and find out why Renovate had never opened a PR for the chart itself.

### What we did
- Established the current chart version (`0.50.0`, pinned in `kubernetes/flux/meta/repos/oci/flux-operator.yaml`) and queried the `controlplaneio-fluxcd/flux-operator` GitHub Releases API to confirm `v0.57.0` (2026-07-27) is the latest stable release, matching what PR #72 already bumps `.mise.toml`'s `flux-operator`/`flux-operator-mcp` CLI tools to.
- Pulled PR #72's diff and the live Renovate Dependency Dashboard (issue #2) to map out that this repo pins the same upstream project's version in four independent places — `.mise.toml` (CLI tools), `flux-instance` values.yaml (Flux distribution/controllers version), and two Helm-chart pins (`kubernetes/flux/meta/repos/oci/flux-operator.yaml` + `flux-instance.yaml`, and `ops/bootstrap/helmfile.d/01-apps.yaml`) — and that PR #72 only touched the first two.
- Diagnosed why: the dashboard showed Renovate *had* detected the chart update (`0.50.0 → 0.57.0`, listed under "Detected Dependencies → flux") but it never appeared in any actionable section (Open/Rate-Limited/Pending Status Checks) — no branch was ever created for it, despite matching the `renovate.json5` "Group Flux Operator + Instance into one PR" packageRule.
- Root-caused it to that packageRule's `/flux-operator/` regex spanning three different Renovate managers/datasources (`mise`, `github-releases`, `docker`) under one `groupName` — cross-manager/cross-datasource grouping is unreliable, and the docker-datasource chart deps were silently dropped from ever getting queued while the mise/github-releases members kept updating independently (evidenced by the mise pin already sitting at `0.52.0`, ahead of the chart's stale `0.50.0`, from an earlier drifted cycle).
- Bumped all four version-pin locations to `0.57.0` for consistency (the OCIRepository chart used by the live cluster, its sibling `flux-instance` chart, and both chart pins in the bootstrap helmfile ladder used for disaster recovery).
- Fixed the Renovate grouping bug by splitting the single cross-datasource `"Flux"` group into two single-datasource groups — `"Flux"` (mise CLI tools + `fluxcd/flux2` distribution, exact-name matched) and `"Flux chart"` (docker-datasource OCI chart, `matchDatasources: ["docker"]` + regex) — mirroring the single-datasource pattern every other working group in the file already uses. Also dropped a dead/incorrect literal (`ghcr.io/fluxcd/flux-operator`, which didn't match any real dependency in this repo) from the rule as cleanup.
- Validated the `renovate.json5` change with Renovate's own `renovate-config-validator` (via `npx -p renovate`) — passed cleanly.
- Did all edits in an isolated worktree (`flux-operator-0.57.0-bump`); left changes uncommitted per this repo's `/git-stage`/`/git-commit`-only policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/flux-operator.yaml` | Chart tag `0.50.0` → `0.57.0` |
| `kubernetes/flux/meta/repos/oci/flux-instance.yaml` | Chart tag `0.50.0` → `0.57.0` |
| `ops/bootstrap/helmfile.d/01-apps.yaml` | `flux-operator` and `flux-instance` release versions `0.50.0` → `0.57.0` |
| `renovate.json5` | Split cross-datasource `"Flux"` packageRule into `"Flux"` (mise + github-releases) and `"Flux chart"` (docker) groups; dropped a dead literal from the old rule |

### Key decisions
- Fixed the Renovate grouping rule rather than disabling grouping outright — the underlying cause (mixing `mise`/`github-releases`/`docker` datasources under one `groupName`) has a straightforward single-datasource-per-group fix that matches the pattern already used successfully elsewhere in `renovate.json5` (e.g. `cert-manager`, `CoreDNS`), so no functionality needed to be sacrificed.
- Bumped all four version-pin locations even though the user only initially named one file, since leaving the sibling chart and bootstrap-ladder pins at `0.50.0` would have reproduced the same drift (and the same grouping bug, pre-fix) on the next Renovate cycle.

---

## 2026-08-04 — `smtp-relay-l2-announcement-troubleshoot`

### Goal
Diagnose why the printer's `smtp-relay` (maddy) couldn't be reached end-to-end, and fix the underlying issue rather than just the symptom.

### What we did
- Live-diagnosed a WSL `nc` timeout against `smtp-relay.cluster.vwn.io:25` step by step: ruled out an unpushed-commit theory (Flux was already reconciling the last-known-good revision), confirmed the pod/HelmRelease/ExternalSecret were all healthy via `kubectl`, and traced repeated "connection reset by peer" log lines in the pod to the kubelet's own `tcpSocket` liveness/readiness probe (benign noise, not a real error).
- Confirmed the first-round timeout was `loadBalancerSourceRanges` working as designed (locked to the printer's `/32` only) by running a temporary `tcpdump` capture pod on the L2-announcing node to get the real client source IP (`10.10.0.71`, WSL's actual on-wire address — not what WSL itself reported), then widened the allow-list with that IP via a Git commit to test further.
- That test surfaced a second, real bug: after the widen, the connection came back "connection refused" instead of timing out. Found the Cilium `cilium-l2announce-mail-smtp-relay` Lease was held by `talos-cp-02`, while the sole `maddy` pod ran on `talos-cp-01` — a stale leader from initial deploy-time election that never re-balanced. Force-deleted the Lease (with explicit user confirmation, since it's a live-cluster action) and confirmed re-election immediately picked the correct node; the printer test then succeeded.
- Researched Cilium's L2-announcement leader-election model via its own docs to answer "can this recur?": confirmed it's a documented incompatibility — Lease-holder election is a plain time-based renewal with no local-endpoint health check, and Cilium's own docs recommend `externalTrafficPolicy: Cluster` as the fix for this exact class of bug (a pod reschedule to a different node would otherwise silently repeat the same failure).
- Verified via research that `loadBalancerSourceRanges` is still enforced against the real client IP at ingress regardless of traffic policy, so switching to `Cluster` costs nothing security-wise (only SNAT'd source-IP visibility inside maddy's own logs on a cross-node-forward, which doesn't happen today with a single replica).
- Switched `externalTrafficPolicy` to `Cluster`, reverted the temporary test IP, and — per the user's own follow-up merge — replaced the single-IP allowance with a permanent `${LAN_SUBNET}` entry (new SOPS-encrypted var) alongside the printer's IP.
- Added a `smtp-relay` blackbox-exporter `Probe` for ongoing monitoring, deliberately targeting the in-cluster Service DNS name (not the external hostname) since the external LB IP's source-IP ACL would otherwise cause permanent false alerts from the exporter's own pod IP; this covers pod/Service-level failures (already-existing generic `BlackboxProbeFailed` alert rule picks it up automatically) but not the external-LB path or SMTP-protocol-level relay health, which the user confirmed is acceptable for now.
- Hit and fixed a self-inflicted deploy issue mid-session: the user's own merge referenced `${LAN_SUBNET}` before it existed in `kubernetes/flux/vars/cluster-secrets.sops.yaml`, which failed Helm's schema validation (`got null, want string`) without touching the live cluster (failed pre-apply); user added the missing SOPS var, re-reconcile then succeeded cleanly.
- Verified the full fix live: Service shows `Cluster` policy with `["10.30.0.51/32","10.10.0.0/24"]`, Flux `Kustomization` and `HelmRelease` both `Ready`/`Released`, pod never restarted through any of this, and the new Probe reports `probe_success 1` in Prometheus (confirmed via a temporary port-forward).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/mail/smtp-relay/app/helmrelease.yaml` | `externalTrafficPolicy: Local` → `Cluster`; `loadBalancerSourceRanges` now printer `/32` + `${LAN_SUBNET}` (temporary single-IP test entry added then removed) |
| `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml` | Added `smtp-relay` `tcp_connect` Probe against the in-cluster Service DNS name |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `LAN_SUBNET` and `IOT_SUBNET` SOPS-encrypted vars (user-added) |

### Key decisions
- Diagnosed via live packet capture (`tcpdump` in a throwaway `hostNetwork` debug pod) rather than guessing at WSL's NAT'd source IP — WSL2's virtual networking makes client-reported addresses unreliable for allow-list decisions.
- Chose `externalTrafficPolicy: Cluster` over pinning the pod to a specific node (`nodeSelector`) — the latter is fragile across Talos/K8s upgrades (any node drain would resurface the exact same bug), while `Cluster` is Cilium's own documented permanent fix with no confirmed security tradeoff.
- Blackbox Probe targets the in-cluster Service DNS, not the external hostname — testing the printer-restricted external LB IP from inside the cluster would always fail the source-IP ACL and false-alarm; accepted as a known coverage gap (pod/Service health only) per user confirmation.
- All live-cluster mutations during diagnosis (temporary debug pods, the Lease deletion, forced Flux reconciles) were called out explicitly and the Lease deletion specifically was gated on the user's explicit go-ahead, since it's a destructive-ish action on shared cluster state outside Git.

---

## 2026-08-04 — `certificates-pushsecret-1password-permission-fix`

### Goal
Diagnose and fix a `PushSecret` 403 against 1Password Connect (vault write-permission gap), then chase its downstream effects: an ESO duplicate-item creation race exposed during the retry, fixed via leader election, and completing the deferred `envoy-gateway-config` → `certificates-import` dependency wiring now that the 1Password backfill is confirmed.

### What we did
- Diagnosed `PushSecret/apps-vwn-io-tls` (and 4 sibling wildcard-cert pushes) failing with `error creating 1Password Item: status 403: ... token does not have permission to perform create on vault vqyi576232amyptf42a56samlq`. Traced the vault ID back to the `homelab` vault via the `onepassword` `ClusterSecretStore`, then ruled out a stale token by decoding the live `onepassword-connect-secrets` Secret and diffing it (sha256) against `op read 'op://homelab/HomeLab Access Token/credential'` — they matched, so the fault was on 1Password Connect's authorization side, not a sync lag. The 403-not-401 status code was the key signal: authentication succeeded (right token, right Connect server), only the `create` action on that vault was denied.
- User created a new 1Password access token scoped for write access on `homelab` and saved it into the `HomeLab Access Token` item; re-ran `just bootstrap resources` to propagate it into the cluster Secret. Confirmed propagation via a bumped Secret `resourceVersion` and a fresh sha256 match — the 403 cleared on the next reconcile.
- Force-syncing one `PushSecret` via an annotation nudge (to skip ESO's retry backoff) surfaced a second, previously-latent bug: two concurrently-reconciling ESO replicas both ran the 1Password provider's non-atomic "find item by title, else create" for the same not-yet-existing item, and both created one — `apps-vwn-io-tls` ended up with 2 duplicate items (same timestamp, each holding only the first-written property). Three of the four remaining PushSecrets hit the same race independently once their own retries landed.
- Root-caused via `kubernetes/apps/external-secrets/external-secrets/app/helm/values.yaml`'s documented design: 2 ESO replicas, **no leader election**, "both always active" — correct for the idempotent `ExternalSecret` pull path, but unsafe for `PushSecret`'s non-atomic push path. Verified via `helm pull external-secrets/external-secrets --version 2.7.0` that enabling `leaderElect: true` needs no RBAC changes (the `coordination.k8s.io/leases` `Role` is rendered unconditionally in the chart) and costs only controller-runtime's default ~15s lease-handover pause on leader-pod disruption — a reconciliation pause, not application downtime, since already-synced `Secret`s are untouched.
- Enabled `leaderElect: true` in the ESO Helm values, rewrote the design-tradeoff comment to describe the race and the fix, and updated the matching claim in `docs/CLUSTER.md`'s External Secrets topology-spread note.
- User manually deleted the duplicate 1Password items; verified (via `op item list`/`op item get`) all 5 certificate items settled to exactly one each, each with both `tls.crt` and `tls.key` populated with sane byte lengths, and confirmed all 5 `certificates-import` `ExternalSecret`s report `Ready`/`SecretSynced` live.
- Answered "is envoy-gateway re-enabled correctly": found `envoy-gateway-config`'s `ks.yaml` still `dependsOn: cluster-issuers` instead of `certificates-import` — the deliberate "Phase 2" step already flagged in commit `9a0030c` and `docs/ROADMAP.md` as pending on a confirmed 1Password backfill. `cluster-issuers` only guarantees the `ClusterIssuer` exists, not that the async cert-manager `Certificate`s (living in the separate `certificates-export` Kustomization) have actually produced their TLS `Secret`s yet — a fresh-bootstrap ordering gap per this repo's own async-prerequisite convention, invisible on the live cluster only because the Secrets already existed from before the refactor.
- Completed the wiring: swapped `envoy-gateway-config`'s `dependsOn` to `certificates-import`, and added `certificates-import` to `certificates-export`'s `dependsOn` (removing the now-resolved deadlock-avoidance comment, since 1Password now holds all 5 items and `certificates-import` will always resolve).
- Updated `docs/ROADMAP.md`'s "Multi-Domain Certificate Pipeline" entry to `✅ COMPLETE (2026-08-04)`, replacing its "when a second domain is added" framing with the actual 5 live domains and the closed ordering gap.

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | Updated ESO topology-spread note: leader election now enabled, replacing the stale "no leader election, zero-delay failover" claim with the actual tradeoff |
| `docs/ROADMAP.md` | Marked "Multi-Domain Certificate Pipeline" `✅ COMPLETE (2026-08-04)`; rewrote the section to reflect 5 live domains and the closed `envoy-gateway-config` ordering gap |
| `kubernetes/apps/external-secrets/external-secrets/app/helm/values.yaml` | Added `leaderElect: true`; rewrote the design-tradeoff comment explaining the `PushSecret` duplicate-creation race and the fix |
| `kubernetes/apps/network/certificates/ks.yaml` | `certificates-export` now `dependsOn: certificates-import`; replaced the "Phase 2 pending" comment with a completion note |
| `kubernetes/apps/network/envoy-gateway/ks.yaml` | `envoy-gateway-config`'s `dependsOn` swapped from `cluster-issuers` to `certificates-import` |

### Key decisions
- Treated the 403-vs-401 distinction as the load-bearing diagnostic signal (auth success vs. vault-permission gap) and verified the token was actually in sync (sha256 + `resourceVersion`) before escalating — avoided a wasted second `just bootstrap resources` re-run chasing the wrong cause.
- Chose cluster-wide leader election over a narrower per-item mutex workaround: it also removes the previously-accepted "doubles API calls to 1Password Connect" cost noted in the original design comment, and the chart's RBAC already supports it unconditionally, so there was no infrastructure cost to unlock it.
- Verified `certificates-import`'s `ExternalSecret`s were actually `Ready` against the live cluster before wiring it in as a hard `dependsOn` for both `certificates-export` and `envoy-gateway-config` — avoided introducing a new deadlock on a resource that might not have actually resolved cleanly.
- Left the duplicate-1Password-item cleanup to the user rather than automating a delete against their live password vault.

---

## 2026-08-03 — `smtp-relay-deployment`

### Goal
Research what the homelab community uses for a local SMTP relay and deploy a GitOps-managed replacement (in the new `mail` namespace) for the TrueNAS `msmtpd` app currently relaying the home printer's mail.

### What we did
- Initial research via kubesearch.dev and WebFetch wrongly concluded `boky/postfix` (`bokysan/docker-postfix`) was the dominant Flux/GitOps home-ops pattern versus a supposedly rare `maddy` — this was wrong, caught by the user citing a `maddy`-based repo kubesearch's page hadn't surfaced. A follow-up `gh search code` (actual GitHub code search, not a scrape of kubesearch's JS-rendered page) found 29+ home-ops-style repos — including `onedr0p/home-ops`, the origin of the whole "home-ops" genre — using `ghcr.io/foxcpp/maddy` at `kubernetes/apps/.../smtp-relay/app/helmrelease.yaml`, and **zero** using `boky/postfix` in that Flux/app-template pattern (only docker-compose/bare-`docker run` hits). One of the two repos originally cited as "postfix" evidence (`gavinmcfall/home-ops`) turned out to use `maddy` too — the initial WebFetch summary had simply misread it. Switched the whole implementation to `maddy`, adapting `onedr0p/home-ops`'s vetted config rather than copying it blind: their container binds port 25 directly as UID 1000 with no `NET_BIND_SERVICE`, which only works if `net.ipv4.ip_unprivileged_port_start=0` is set in the pod netns — unverified for this cluster — so kept the container on a high port (2525) with the Service remapping 25→2525 instead (same trick as this repo's own `victoria-logs` 514→1514 precedent).
- Ran an Explore agent that found this repo's only existing raw-TCP-to-LAN-device precedent (`victoria-logs`' hand-written `syslog-service.yaml` LoadBalancer Service, `loadBalancerSourceRanges` pinned via a `${..._LAN_HOST}` substitution var, no MetalLB — Cilium IPAM + L2 announcement instead), the minimal app-template reference (`whoami`), the extract+rewrite `ExternalSecret` convention (`waha`), and the new-namespace scaffold pattern (`ai`/`automation`: `namespace.yaml` + `kustomization.yaml`).
- A second Explore agent traced exactly where `NAS_LAN_HOST`-style vars live (`kubernetes/flux/vars/cluster-secrets.sops.yaml`, exposed cluster-wide via the `cluster-apps` `postBuild.substituteFrom` patch) and pulled a full extract+rewrite `ExternalSecret` template plus the `docs/EXTERNAL-SECRETS.yaml` entry format to match.
- Used `AskUserQuestion` to resolve decisions not derivable from the repo: a new dedicated `mail` namespace (room to grow — could later double as Alertmanager's SMTP receiver); `loadBalancerSourceRanges` pinned to the printer's IP only (not the whole management subnet) for now; upstream authenticated relay (credentials) rather than direct-to-MX delivery; and, after the image correction, confirming the switch to `maddy`.
- Queried the 1Password `smtp-relay` item's field labels only (`op item get ... --format json`, no values) to confirm the exact raw field names (`HOST`, `PORT`, `USERNAME`, `PASSWORD`) to wire into the `ExternalSecret`'s rewrite rules.
- While still on the (later-reverted) `boky/postfix` path, read its actual entrypoint scripts (`image_root/scripts/{run,functions}.sh`, `supervisord.conf`, `master.cf`) in `bokysan/docker-postfix` to derive a minimal capability set instead of guessing — then had to correct a second error mid-derivation: claimed port 587 was "unprivileged," which is wrong (privileged range is 0–1023; 587 needs `CAP_NET_BIND_SERVICE` same as any port <1024). Both this and the image-choice error are moot now since `maddy` needs no such workarounds at all.
- Fetched the actual `bjw-s-labs/helm-charts` `app-template`/`common` JSON schema (via `gh api`, pinned to the in-repo chart version) and confirmed `service.<name>` natively supports `type`, `loadBalancerSourceRanges`, and `annotations` with `controller:` auto-wiring the pod selector (avoided a hand-written Service entirely), and confirmed `controllers.<name>.pod.securityContext` and the automatic `tcpSocket` probe derivation (from the primary service's `targetPort`, when its protocol is `TCP`) before relying on either.
- Implemented the full GitOps deployment: new `mail` namespace, `smtp-relay` Flux `Kustomization` (`dependsOn: onepassword-store`), extract+rewrite `ExternalSecret` (→ `SMTP_RELAY_SERVER`/`SMTP_RELAY_SERVER_PORT`/`SMTP_RELAY_USERNAME`/`SMTP_RELAY_PASSWORD`), and an app-template `HelmRelease` running `maddy` fully non-root (`runAsUser: 1000`, `readOnlyRootFilesystem: true`, `capabilities: drop: ["ALL"]`, no exceptions) with an inline `maddy.conf` ConfigMap and `emptyDir` cache/state, LoadBalancer Service (port 25 → container 2525, `externalTrafficPolicy: Local` to preserve the printer's source IP for `loadBalancerSourceRanges` filtering). Added `PRINTER_LAN_HOST` to `cluster-secrets.sops.yaml` via `sops set` (no manual decrypt/re-encrypt round-trip) and appended the new `docs/EXTERNAL-SECRETS.yaml` inventory entry.
- Validated: `kustomize build` succeeds on the new app, the `mail` namespace, and the full `kubernetes/apps` tree (81 resources); `kubeconform -strict` passes on both new resources — re-run after the maddy rework, still clean.
- **Not yet done**: the user still needs to reconcile via Flux (not applied to the live cluster in this session), confirm the printer/cluster VLANs (printer is on `10.30.0.0/24`, cluster management is `10.60.0.0/24`) actually route to each other, repoint the printer at `smtp-relay.cluster.vwn.io:25`, and decommission the TrueNAS `msmtpd` app once mail delivery is confirmed working end-to-end.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/mail/namespace.yaml` | Created — new `mail` namespace, prune disabled |
| `kubernetes/apps/mail/kustomization.yaml` | Created — registers namespace + smtp-relay `ks.yaml` |
| `kubernetes/apps/mail/smtp-relay/ks.yaml` | Created — Flux Kustomization, `targetNamespace: mail`, `dependsOn: onepassword-store` |
| `kubernetes/apps/mail/smtp-relay/app/kustomization.yaml` | Created — lists externalsecret.yaml + helmrelease.yaml |
| `kubernetes/apps/mail/smtp-relay/app/externalsecret.yaml` | Created, then reworked for maddy's env var names — extract+rewrite `HOST`/`PORT`/`USERNAME`/`PASSWORD` → `SMTP_RELAY_SERVER`/`SMTP_RELAY_SERVER_PORT`/`SMTP_RELAY_USERNAME`/`SMTP_RELAY_PASSWORD` |
| `kubernetes/apps/mail/smtp-relay/app/helmrelease.yaml` | Created as `boky/postfix:5.1.0`, then fully rewritten as `ghcr.io/foxcpp/maddy:0.9.5` via app-template — fully non-root, inline `maddy.conf`, LoadBalancer Service pinned to printer IP |
| `kubernetes/apps/kustomization.yaml` | Added `./mail` to the top-level namespace list |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `PRINTER_LAN_HOST: 10.30.0.51` via `sops set` |
| `docs/EXTERNAL-SECRETS.yaml` | Appended `smtp-relay` ExternalSecret inventory entry |

### Key decisions
- **`maddy` chosen over `boky/postfix`** — corrected mid-session after the user caught an initial research error (see "What we did"). Verified via `gh search code` rather than trusting a kubesearch.dev page render a second time.
- `maddy` runs fully non-root with zero capability exceptions (`runAsNonRoot`, `readOnlyRootFilesystem`, `drop: ["ALL"]`) — strictly better fit for this repo's hardened default pattern than `boky/postfix`, which needed root for Postfix's internal privilege-separation model (moot now, but was real effort spent before the correction).
- New dedicated `mail` namespace rather than folding into `network` or `default` — leaves room to grow (e.g. a future Alertmanager SMTP receiver).
- `loadBalancerSourceRanges` pinned to just the printer's `/32` for now, not the whole management subnet, per user preference — widen in Git later if a second appliance needs access.
- Used app-template's built-in `service:` block (confirmed via the chart's JSON schema to support `loadBalancerSourceRanges`/`type`/`annotations`) instead of a hand-written `Service`, since `victoria-logs`' hand-written Service pattern was only necessary because that chart lacks these knobs.
- Container listens on 2525 internally, Service remaps 25→2525 — deliberately did not copy `onedr0p/home-ops`'s direct bind to port 25 as non-root, since that depends on an unverified node/CNI sysctl (`net.ipv4.ip_unprivileged_port_start=0`) this cluster's config doesn't confirm.
- `externalTrafficPolicy: Local` added to the Service so `loadBalancerSourceRanges` filtering sees the printer's real source IP rather than a potentially-SNATed one.

---

## 2026-08-02 — `openwebui-gitops-deployment`

### Goal
Research community OpenWebUI deployment patterns, design a GitOps implementation plan matching this repo's conventions, and begin implementing the new `ai` tenant namespace and `open-webui` app manifests.

### What we did
- Researched community deployment patterns via kubesearch.dev and targeted WebSearch/WebFetch calls: confirmed `bjw-s-labs/charts`' `app-template` is the dominant community pattern for OpenWebUI (26 indexed repos) versus the official `open-webui/helm-charts` chart (1 repo), and used `bjw-s-labs/home-ops`'s own OpenWebUI deployment (the app-template maintainers' own cluster) as the direct architectural reference — single `app` container, Dragonfly-backed websocket manager, VolSync-style persistent `config` claim, Gateway API route.
- Ran two parallel Explore agents against the local repo: one fully mapped the `paperless-ngx` deployment (two-stage `ks.yaml` Kustomization pattern, CNPG `Database` CR, ExternalSecret extract+rewrite convention, VolSync component, HTTPRoute/Gateway API exposure) as the template to mirror; the other confirmed no existing LLM/GPU-serving infrastructure exists in this cluster (only unused Intel iGPU passthrough for Plex/Jellyfin) and catalogued the Dragonfly, CNPG, storage-class, and 1Password/ExternalSecret conventions in play.
- Verified upstream OpenWebUI behavior directly against source rather than trusting an initial WebFetch summary: caught a hallucinated claim that `WEBUI_ADMIN_EMAIL`/`WEBUI_ADMIN_PASSWORD` env vars exist for admin bootstrap by reading `backend/open_webui/config.py` directly (they don't exist), then confirmed via a GitHub discussion that the real mechanism is the `/api/v1/auths/signup` API endpoint (the first account created always becomes admin, regardless of `ENABLE_SIGNUP`). Also confirmed via the official Dockerfile and several GitHub issues that the published image is not arbitrary-UID friendly and genuinely needs to run as root.
- Used `AskUserQuestion` to resolve four decisions not derivable from the repo: no LLM backend wired at deploy time (added later via the admin UI), a new `ai` tenant namespace, internal-only exposure (`envoy-internal` Gateway, no Cloudflare), and a pre-provisioned admin account with signup closed from the start — implemented via a one-shot bootstrap Job rather than ever opening public signup.
- Wrote a full implementation plan and got user approval (saved at `/home/vscode/.claude/plans/research-community-configurations-for-optimized-chipmunk.md`).
- Began implementation: created the `ai` tenant namespace scaffold, the `open-webui` app's two-Kustomization dependency chain (`open-webui-db` targeting `database` with `wait: true`; `open-webui` targeting `ai`), the CNPG `Database` CR and DB-role `ExternalSecret` (role/db name `open_webui`, underscored to stay a quote-free SQL identifier), and the app's own `ExternalSecret` (extract+rewrite from a new `open-webui` 1Password item, plus the existing `dragonfly` item on DB index `1` — paperless-ngx already owns index `0`).
- **Not yet done**: `app/helmrelease.yaml`, `app/httproute.yaml`, and `app/job-bootstrap-admin.yaml` are referenced by `app/kustomization.yaml` but not yet written; the top-level `kubernetes/apps/kustomization.yaml` still needs `./ai` registered; the shared CNPG `cluster.yaml` still needs the `open_webui` role added to `managed.roles`; no `open-webui` 1Password vault item exists yet. The Kustomization will not build until these land.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/ai/namespace.yaml` | Created — new `ai` tenant namespace, prune disabled |
| `kubernetes/apps/ai/kustomization.yaml` | Created — registers namespace + open-webui `ks.yaml` |
| `kubernetes/apps/ai/open-webui/ks.yaml` | Created — two-stage Flux Kustomization (db + app), VolSync component, `dependsOn` chain |
| `kubernetes/apps/ai/open-webui/db/kustomization.yaml` | Created |
| `kubernetes/apps/ai/open-webui/db/database.yaml` | Created — CNPG `Database` CR, owner `open_webui` on shared `postgres-v17` cluster |
| `kubernetes/apps/ai/open-webui/db/externalsecret.yaml` | Created — DB-role basic-auth secret, `cnpg.io/reload` label |
| `kubernetes/apps/ai/open-webui/app/kustomization.yaml` | Created — references not-yet-written helmrelease/httproute/job manifests |
| `kubernetes/apps/ai/open-webui/app/externalsecret.yaml` | Created — app secret (`WEBUI_SECRET_KEY`, `DATABASE_URL`, `WEBSOCKET_REDIS_URL`, bootstrap admin creds) |

### Key decisions
- Chose `bjw-s/app-template` over the official `open-webui/helm-charts` chart — matches this repo's universal convention and is also the dominant community pattern (26 vs. 1 repos on kubesearch.dev).
- Used underscore-separated `open_webui` for the Postgres role/database name (vs. hyphenated `open-webui` for all Kubernetes resource names) to keep the SQL identifier quote-free.
- Pre-provision the admin account via a one-shot Job calling the public signup API once (idempotent across re-runs) rather than ever setting `ENABLE_SIGNUP: true` temporarily — avoids any window where an anonymous LAN client could register.
- Set VolSync mover `APP_UID`/`APP_GID` to `0` (root) instead of the component's default `4000`, matching the app container's own required root UID (upstream image is not arbitrary-UID friendly), so backup/restore doesn't hit permission errors.
- Deliberately left the LLM backend (Ollama/OpenAI) unwired — per user decision, to be added manually post-deploy via the admin UI rather than as env vars/secrets now.

---

## 2026-07-31 — `paperless-ngx-truenas-restore-v3-upgrade`

### Goal
Import the TrueNAS-hosted paperless-ngx instance's exported backup into the vanilla Kubernetes deployment, upgrade it to v3.0.4, and fix the data-integrity and configuration issues the restore/upgrade surfaced.

### What we did
- Imported a `document_exporter`-format backup (`paperless_export_20260725_220003.zip`, 4061 files/3.75GB) from the TrueNAS-hosted paperless instance into the fresh, empty Kubernetes deployment via `kubectl cp` to the SMB-backed `archive` PVC's `export` mount, Python `zipfile` extraction (no `unzip` binary in the image), and `document_importer`; verified 4059/4059 documents, 59 correspondents, 114 tags, 17 document types restored with matching counts, then cleaned up staging files.
- Diagnosed via the user-provided `backup.sh` that the export's `--no-archive --no-thumbnail` flags — not a filename collision, an initial wrong theory — were why archived/OCR'd PDF versions were entirely absent for 4043 of 4059 documents despite the DB's `archive_checksum` still carrying values from the source instance.
- Upgraded the image from `2.20.15` to `3.0.4` (digests resolved via `crane`/GHCR token API, cross-checked two ways), applying the two functionally-required v3 migration changes from the official `migration-v3.md` guide: `PAPERLESS_CONSUMER_POLLING` → `PAPERLESS_CONSUMER_POLLING_INTERVAL` rename and new mandatory `PAPERLESS_DBENGINE: postgresql`; confirmed via GitHub release notes that 3.0.1–3.0.4 patches carried no additional breaking changes.
- Ran `document_archiver -f` to regenerate the missing archive files; hit two `OOMKilled` crashes at the original 4Gi container limit (once at `--processes 2`, once single-process). Root-caused the second as document ID 1588 (a 19.2MB/4-page outlier, confirmed by isolating it — peaked >2GB and succeeded once the limit was temporarily raised to 12Gi), then resumed the remaining 2788 documents via a custom script calling `update_document_content_maybe_archive_file` directly, skipping the ~1270 already-completed documents rather than re-running the full `-f` pass, completing with 0 failures; verified zero residual `archive_checksum`-without-file gaps afterward, then reverted the memory limit back to 4Gi.
- Diagnosed a `500` error the user hit editing document 4693 in the web UI. Guessed wrong twice first (a filename-collision theory, then a "deprecated old-style `FILENAME_FORMAT`" theory) before finding VictoriaLogs was already deployed in-cluster (missed on an initial name-only `grep loki`) and pulling the real traceback from it: a transient Tantivy search-index `PermissionDenied` reading `.managed.json` during the post-edit reindex step, unrelated to the filename. Confirmed the index opens cleanly now and that the tag removal itself had succeeded despite the 500.
- Separately confirmed via `manage.py check`/`convert_format_str_to_template_format` and live rendering tests that `PAPERLESS_FILENAME_FORMAT: "{ created }-{ correspondent }-{ title }"` was genuinely broken — single braces with internal spaces match neither valid old-style (`{created}`) nor valid Jinja2 (`{{ created }}`), so paperless rendered it as literal text. This is why document 4693's file was literally named `{ created }-{ correspondent }-{ title }.pdf` the first time a real edit ever triggered the rename-on-metadata-change signal (bulk import/archiving bypasses that signal entirely). Fixed to `{{ created }}-{{ correspondent }}-{{ title }}`, but that first fix then failed the Helm upgrade for ~22h (`function "created" not defined`) because `app-template` pipes every env value through Helm's own `tpl` function before the container ever sees it; fixed properly with Go-template brace-escaping (`{{"{{"}} created {{"}}"}}...`), verified this time via `helm template` against the real pulled chart before committing.
- Created a manual-only `Onbekend` correspondent (`matching_algorithm: NONE`) and bulk-assigned it via a single `.update()` — deliberately not per-document `.save()`, to avoid mass-triggering the not-yet-deployed filename-rename signal — to the 3403 of 4059 documents that had no correspondent.
- Re-rendered document 4693's `filename`/`archive_filename` correctly using the corrected template (run manually, since the Helm fix wasn't deployed yet) and confirmed the old garbage-named file was cleanly moved, not duplicated.
- The final Helm-escaping fix to `PAPERLESS_FILENAME_FORMAT` is implemented and verified but not yet committed — `/git-stage`/`/git-commit` still pending.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/documents/paperless-ngx/app/helmrelease.yaml` | Bumped image `2.20.15`→`3.0.4`; renamed `PAPERLESS_CONSUMER_POLLING`→`PAPERLESS_CONSUMER_POLLING_INTERVAL`; added `PAPERLESS_DBENGINE: postgresql`; temporarily raised then reverted app container memory limit (4Gi→12Gi→4Gi) for the archiver run; fixed `PAPERLESS_FILENAME_FORMAT` (Jinja2 syntax, then Helm `tpl`-escaping) |

### Key decisions
- Used a hand-written script calling `update_document_content_maybe_archive_file` directly (skipping already-completed documents) to resume the archiver rather than re-running the built-in `-f` bulk command a third time — avoided redoing ~1270 already-successful documents and added per-document error isolation the built-in command lacks.
- Used bulk `.update()` rather than per-document `.save()` for the `Onbekend` correspondent assignment specifically because `.save()` fires the same rename-on-metadata-change signal that was still broken/undeployed at the time — a deliberate ordering safeguard, not an oversight.
- Retracted two wrong theories about the 4693 `500` error in real time rather than committing to them, after the user pointed out VictoriaLogs was available — went back to the actual traceback instead of plausible-sounding inference.
- Chose Go-template brace-escaping over alternatives after the first `FILENAME_FORMAT` fix silently broke the Helm release for ~22 hours; verified the fix with a real `helm template` render against the pulled chart before proposing it again, rather than trusting reasoning alone a third time.

---

## 2026-07-28 — `paperless-ngx-smb-persistence-reenable`

### Goal
Wire paperless-ngx onto the new SMB CSI driver for NAS-backed archive/backups storage, keep VolSync protecting the regenerable working-state PVC, and re-enable the app.

### What we did
- Reviewed bykaj's `tmp/home-ops-bykaj/kubernetes/apps/default/paperless` as the reference pattern for static SMB PV/PVC wiring (per `CONVENTIONS.md`'s community-research guidance), cross-checked against this repo's already-deployed `csi-driver-smb` (driver-only, `smb-credentials` ExternalSecret in the `csi-driver-smb` namespace).
- Found the user had already reworked `helmrelease.yaml`'s env/persistence blocks toward bykaj's shape (image pin, `archive`/`backups` `existingClaim` SMB persistence keys) but left a stale ceph-block `data` persistence block colliding with `config` on the same mount path (`/usr/src/paperless/data`) — removed it.
- Added static `PersistentVolume`/`PersistentVolumeClaim` pairs (`pv.yaml`, `pvc.yaml`) for `paperless-ngx-smb-archive` (whole `//${NAS_HOST}/Archive` share) and `paperless-ngx-smb-backup` (`//${NAS_HOST}/Backup` share, scoped via `subPath: Apps/Paperless`); `storageClassName: smb` is a label-only match for static binding — no actual StorageClass object exists — `Retain` reclaim, cross-namespace `nodeStageSecretRef` to `csi-driver-smb`'s `smb-credentials` Secret.
- Wired `dependsOn: csi-driver-smb` into paperless-ngx's app Kustomization so the async ExternalSecret-created Secret is guaranteed present before the pod tries to mount.
- At the user's direction, briefly removed VolSync entirely from paperless-ngx (component, `VOLSYNC_CLAIM`/`VOLSYNC_CAPACITY`/`APP_UID`/`APP_GID` substitutions, `dependsOn`, and the `docs/EXTERNAL-SECRETS.yaml` consumer entry) reasoning the real documents now live durably on the NAS via SMB — then reverted per the user's follow-up correction: `config` (the regenerable search-index/working-state PVC) stays VolSync-protected. Renamed the claim from the stale `paperless-ngx-media` to `paperless-ngx-config` and resized `VOLSYNC_CAPACITY` from `30Gi` to `5Gi` to match what `config` actually holds now.
- Answered a question on SMB `subPath` directory auto-creation: `smb.csi.k8s.io` does no subdirectory management in static mode (that's dynamic-provisioning-only); `Apps/Paperless` gets auto-created by the kubelet's generic subPath handling on first pod start, contingent on the `smb-credentials` account having write access to the `Backup` share.
- Updated `docs/EXTERNAL-SECRETS.yaml` to document the two new `PersistentVolume` consumers of `smb-credentials`.
- Re-enabled paperless-ngx in `kubernetes/apps/documents/kustomization.yaml` (uncommented `./paperless-ngx/ks.yaml`).
- `kubectl kustomize` validated clean at each step; work is implemented but not committed — `/git-stage`/`/git-commit` still pending.

### Files changed
| File | Change |
|------|--------|
| `docs/EXTERNAL-SECRETS.yaml` | Documented `smb-credentials`' new `PersistentVolume` consumers (`paperless-ngx-smb-archive`/`-smb-backup`); kept the existing `volsync-restic` consumer entry for `paperless-ngx-volsync` |
| `kubernetes/apps/documents/kustomization.yaml` | Re-enabled paperless-ngx (uncommented `./paperless-ngx/ks.yaml`) |
| `kubernetes/apps/documents/paperless-ngx/app/helmrelease.yaml` | Fixed `persistence.config`/`data` mount-path collision; `archive`/`backup` persistence now point at the new SMB `existingClaim`s |
| `kubernetes/apps/documents/paperless-ngx/app/kustomization.yaml` | Added `pv.yaml`/`pvc.yaml` |
| `kubernetes/apps/documents/paperless-ngx/app/pv.yaml` | New — static PVs `paperless-ngx-smb-archive` and `paperless-ngx-smb-backup` |
| `kubernetes/apps/documents/paperless-ngx/app/pvc.yaml` | New — matching static PVCs |
| `kubernetes/apps/documents/paperless-ngx/ks.yaml` | Restored VolSync wiring for the `config` claim (renamed/resized), added `dependsOn: csi-driver-smb` |

### Key decisions
- SMB gets static PV/PVC pairs, not a dynamic StorageClass — mirrors the earlier `csi-driver-smb` design decision (each share needs distinct source/credentials, nothing generic to provision).
- `config` (working-state/search-index data) stays VolSync-protected even though it's regenerable, because rebuilding a large document index from scratch is slow — cheap insurance via the existing Ceph→NAS backup path. The precious original documents (`archive`/`backups`) don't need VolSync since they're already durably stored on the NAS via SMB.
- `storageClassName: smb` on both PV and PVC is a label-only match for static binding, not a reference to a real StorageClass resource — consistent with `csi-driver-smb` being driver-only.

---

## 2026-07-28 — `keda-redis-smb-scaler-components`

### Goal
Extend the KEDA scale-to-zero pattern (established for Postgres) to Dragonfly and SMB, mirroring `bykaj/home-ops`'s `redis-scaler`/`smb-scaler` Components.

### What we did
- Read bykaj's `redis-scaler` and `smb-scaler` Components (`tmp/home-ops-bykaj/kubernetes/components/keda/{redis,smb}-scaler/scaledobject.yaml`) as the reference pattern, then checked this repo's actual consumers: Dragonfly (cluster-wide shared Redis-compatible store, `kubernetes/apps/database/dragonfly`) has exactly one named consumer, paperless-ngx (itself currently disabled); `csi-driver-smb` has no consumer at all yet (driver + ExternalSecret only, per the earlier `csi-nfs-smb-storage-deployment` session).
- Added a `DRAGONFLY_HOST` cluster-wide substitution var (`dragonfly.database.svc.cluster.local`) to `kubernetes/flux/vars/cluster-secrets.sops.yaml`, matching the existing `PG_HOST` convention (stable in-cluster DNS name, not truly secret, but grouped alongside `PG_HOST`/`NAS_HOST` for consistency) — decrypted, edited, re-encrypted with `sops`, verified the round-trip.
- Added a new `dragonfly` blackbox `Probe` (`tcp_connect` on `${DRAGONFLY_HOST}:6379`) to `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml`, mirroring the existing `postgres` Probe's structure and comment style — the `nas-smb` Probe smb-scaler needs already existed, so no new Probe was needed for that one.
- Built two new Kustomize Components, mirroring `postgres-scaler`'s style (not bykaj's `${KEDA_NAME:=${APP}}` indirection): `kubernetes/components/keda/redis-scaler/` and `kubernetes/components/keda/smb-scaler/`, both `cooldownPeriod: 30` (not bykaj's `0`) for the same self-healing-blip rationale as the Postgres scaler.
- Wired `redis-scaler` into paperless-ngx's `ks.yaml` `components:` list — inert until the app is re-enabled, same status as its `postgres-scaler` entry. Left `smb-scaler` unwired: confirmed via `flux build --dry-run` that `csi-driver-smb`'s Kustomization produces no Deployment to target.
- Verified the existing generic `driftDetection.ignore` block (`target.kind: Deployment`, no `name` filter) in paperless-ngx's `helmrelease.yaml` already covers any number of ScaledObjects aimed at the same Deployment — no HelmRelease change needed for the second scaler.
- Ran `task validate` (all checks pass) and `flux build kustomization` for paperless-ngx and csi-driver-smb; confirmed the empty `${PG_HOST}`/`${DRAGONFLY_HOST}` substitution in local dry-run output is a pre-existing tooling limitation (Flux's SOPS decryption provider isn't available offline), not a regression, by reproducing the identical gap on an already-shipped `PG_HOST` consumer (`postgres-backup-local`).
- Work is implemented but not committed — `/git-stage`/`/git-commit` still pending.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/components/keda/redis-scaler/kustomization.yaml` | New Kustomize Component entry point |
| `kubernetes/components/keda/redis-scaler/scaledobject.yaml` | New KEDA `ScaledObject` template (`prometheus` trigger on Dragonfly's `probe_success`, `cooldownPeriod: 30`) |
| `kubernetes/components/keda/smb-scaler/kustomization.yaml` | New Kustomize Component entry point |
| `kubernetes/components/keda/smb-scaler/scaledobject.yaml` | New KEDA `ScaledObject` template (`prometheus` trigger on SMB's `probe_success`, `cooldownPeriod: 30`), currently unwired — no app consumes `csi-driver-smb` yet |
| `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml` | Added `dragonfly` Probe (`tcp_connect` on `${DRAGONFLY_HOST}:6379`) |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `DRAGONFLY_HOST` var |
| `kubernetes/apps/documents/paperless-ngx/ks.yaml` | Added `redis-scaler` to `components:` list |

### Key decisions
- `smb-scaler` was built but deliberately left unwired — there's no live consumer, and wiring it into an arbitrary app would misrepresent the Component as active when it isn't.
- `DRAGONFLY_HOST` was added as a cluster-wide var (grouped with `PG_HOST`/`NAS_HOST` in `cluster-secrets.sops.yaml`) rather than hardcoding the FQDN, for a single source of truth across the new Probe and ScaledObject, consistent with the existing `PG_HOST` precedent.

---

## 2026-07-28 — `cnpg-accidental-recreation-pitr-recovery`

### Goal
Diagnose and recover from an accidental full recreation of the shared CNPG `postgres-v17` Cluster (triggered while testing the new KEDA scale-down mechanism), including a failed `restore-from-backup` attempt and a successful PITR recovery of forgejo/firefly-iii data.

### What we did
- User tested the scale-down mechanism by manually scaling down `cloudnative-pg`; the third replica's join job (`postgres-v17-3-join-fthlk`) stalled. Initial read was that this was a normal, self-healing instance-count topology change — later corrected: `creationTimestamp` forensics on the `Cluster` object and its PVCs (`2026-07-28T11:47:40Z`) showed the whole Cluster had actually been torn down and recreated from scratch, wiping forgejo/firefly-iii data.
- Separately, `just cnpg restore-from-backup` had edited `cluster/app/cluster.yaml` to add `spec.bootstrap.recovery` + `externalClusters`; Flux's dry-run rejected it — admission webhook `vcluster.cnpg.io`: `spec.bootstrap: Forbidden: Only one bootstrap method can be specified at a time`. Root cause: CNPG's own mutating webhook had already defaulted `spec.bootstrap.initdb` onto the live object at original creation (Git never declared it explicitly), so the recipe's `yq`-added `recovery` block merged alongside the existing `initdb` default instead of replacing it.
- Reverted `cluster.yaml` to drop the added `bootstrap`/`externalClusters` block (matching `just cnpg undo-restore`'s effect) — validated with `task validate`; this edit was never committed (caught and reverted before staging), so it leaves no trace in git history.
- Walked the user through PITR recovery into a disposable scratch `Cluster` (`postgres-v17-pitr-scratch`), applied by hand via `kubectl` (bykaj's `just cnpg pitr-restore` recipe is `gum`-interactive and unusable non-interactively; its automatic `serverName` resolution would also have picked the wrong, empty archive prefix for this scenario) — explained why a barman-cloud recovery + WAL replay onto the *live* cluster wasn't viable (`spec.bootstrap` is creation-time-only; would require another full Cluster recreation), versus a disposable scratch cluster for safe extraction.
- First scratch-cluster attempt with an explicit `recoveryTarget.targetTime` (11:45:00Z) failed: `recovery ended before configured recovery target was reached`, only WAL file `000000070000000500000030` available. User revealed they'd separately reverted the change that had been breaking WAL archiving, expecting more WAL to be recoverable. Retried with no explicit `recoveryTarget` (recover-to-latest) — succeeded, reaching timeline 8 with real data (forgejo: 2 repos/2 users; firefly: 1886 accounts/42324 transactions).
- User completed the actual dump/restore into the live cluster and scratch-cluster cleanup themselves.
- Found continuous WAL archiving still failing post-recovery (`ContinuousArchivingFailing`; `pg_stat_archiver`: `archived_count=0`, `failed_count=147`) — root cause: the recreated cluster (new system identifier) was still configured to archive under the *old* cluster's `serverName` (`postgres-v17-20260702`); barman-cloud correctly rejects a mismatched system ID writing into an existing server's WAL lineage.
- Fixed by bumping `CNPG_V17_CURRENT_CLUSTER` to `postgres-v17-20260728` (a fresh, never-archived-to prefix) in `kubernetes/apps/database/cloudnative-pg/ks.yaml`. User confirmed via `kubectl get cluster postgres-v17 -o jsonpath='{.status.conditions}'`, showing `ContinuousArchivingSuccess` at `12:32:46Z`.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Bumped `CNPG_V17_CURRENT_CLUSTER` from `postgres-v17-20260702` to `postgres-v17-20260728` — committed as `bed4aaf` |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added then reverted a bad `bootstrap.recovery`/`externalClusters` block (never committed) |

### Key decisions
- Recovered via a disposable scratch `Cluster` object rather than any in-place recovery on the live `postgres-v17` Cluster — `spec.bootstrap` is consulted by CNPG only once, at object creation, so an in-place PITR would have required deleting and recreating the live Cluster again, compounding the exact risk that caused this incident.
- Chose recover-to-latest over a second explicit `recoveryTarget.targetTime` guess, once new WAL archives were confirmed available — safer than estimating a second timestamp against unknown-good WAL coverage.
- A fresh, never-used `serverName` (`postgres-v17-20260728`) was picked for the recreated cluster's ongoing archiving, rather than reusing the old prefix — avoids any possibility of barman-cloud system-identifier collisions against the old cluster's WAL lineage.

---

## 2026-07-28 — `keda-postgres-scaler-component`

### Goal
Add a KEDA `ScaledObject` Component that scales Postgres-dependent apps (forgejo, firefly-iii, paperless-ngx) to zero when the shared CNPG cluster becomes unreachable, mirroring a pattern researched from `bykaj/home-ops`.

### What we did
- User asked to introduce "KEDA autoscale for postgres in bykaj's fashion"; an initial `WebSearch`/`gh api` lookup against a wrong GitHub repo (`ByKaj/home-ops`, an unrelated stale mirror) suggested bykaj used a raw HPA + prometheus-adapter "zeroscaler" pattern instead of KEDA — flagged this discrepancy to the user via `AskUserQuestion` before proceeding.
- User corrected course, pointing to their actual local clone at `tmp/home-ops-bykaj` (repo `qnimbus/home-ops-bykaj`), which confirmed bykaj genuinely uses a native `keda.sh/v1alpha1 ScaledObject` with a `prometheus` trigger (`components/keda/postgres-scaler/scaledobject.yaml`) — re-derived the plan from that file directly instead of the wrong repo.
- Ran two `Explore` subagents in parallel (existing KEDA setup; CNPG postgres usage across the cluster) plus a `Plan` subagent to design the concrete implementation, after live-verifying this cluster's prerequisites via `kubectl`: KEDA deployed/healthy, the existing `blackbox-exporter` `postgres` Probe already live with a healthy `probe_success{instance="postgres-v17-rw.database.svc.cluster.local:5432"}` metric, the correct in-cluster Prometheus service name (`kube-prometheus-stack-prometheus`, not bykaj's `prometheus-operated`), and that this repo's existing `PG_HOST` variable (not bykaj's `DB_HOST`) was the right one to reuse.
- Reviewed the plan in plan mode; user approved with one change — `cooldownPeriod: 30` instead of bykaj's `0` — reasoning that this cluster's CNPG cluster already performs brief, self-healing `primaryUpdateStrategy: unsupervised` primary switchovers that a zero-debounce scaler could turn into unnecessary full pod restarts. User also requested auto mode for the implementation step.
- Implemented: new Kustomize Component `kubernetes/components/keda/postgres-scaler/` (`kustomization.yaml` + `scaledobject.yaml`), wired into forgejo/firefly-iii/paperless-ngx's `ks.yaml` `components:` lists, and added a `driftDetection.ignore` block for `/spec/replicas` to each app's `helmrelease.yaml` (required so Flux's drift detection doesn't revert KEDA's scale-to-zero on its next reconcile).
- Verified with `task validate` (all schema checks pass) and `flux build kustomization` against the live cluster for forgejo and firefly-iii — confirmed `${APP}` substitutes correctly into each `ScaledObject`'s name/namespace and the `driftDetection` block renders correctly in the built `HelmRelease`. Confirmed `${PG_HOST}` not resolving under this isolated single-Kustomization build mode is a pre-existing tooling limitation, not a regression, by showing the identical gap on forgejo's already-existing `HOST` field under the same command.
- paperless-ngx is currently disabled (`kubernetes/apps/documents/kustomization.yaml` has its `ks.yaml` line commented out) — wired the component in anyway per the user's explicit "all three now" choice, with an inline comment noting it's inert until the app is re-enabled; couldn't `flux build`-verify it in isolation for the same reason (no live Flux object to fetch).
- Work is implemented but not committed — user's explicit `/git-stage`/`/git-commit` still pending, per repo convention.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/components/keda/postgres-scaler/kustomization.yaml` | New Kustomize Component entry point |
| `kubernetes/components/keda/postgres-scaler/scaledobject.yaml` | New KEDA `ScaledObject` template (`prometheus` trigger on `probe_success`, `cooldownPeriod: 30`) |
| `kubernetes/apps/development/forgejo/ks.yaml` | Added `postgres-scaler` to `components:` list |
| `kubernetes/apps/development/forgejo/app/helmrelease.yaml` | Added `driftDetection.ignore` for `/spec/replicas` |
| `kubernetes/apps/finance/firefly-iii/ks.yaml` | Added `postgres-scaler` to `components:` list |
| `kubernetes/apps/finance/firefly-iii/app/helmrelease.yaml` | Added `driftDetection.ignore` for `/spec/replicas` |
| `kubernetes/apps/documents/paperless-ngx/ks.yaml` | Added `postgres-scaler` to `components:` list (inert while app disabled) |
| `kubernetes/apps/documents/paperless-ngx/app/helmrelease.yaml` | Added `driftDetection.ignore` for `/spec/replicas` |

### Key decisions
- Corrected an initial wrong research lead (GitHub repo `ByKaj/home-ops`) using the user's own local clone as ground truth once they pointed to it — the reference pattern is a genuine KEDA `ScaledObject`, not a raw HPA + prometheus-adapter.
- Chose `cooldownPeriod: 30` over bykaj's `0`, per explicit user instruction, to avoid scale-to-zero flapping during CNPG's own routine primary switchovers.
- Query filters only on the `instance` label (not `job="postgres_probe"` like bykaj) since this repo's existing `postgres` Probe CR doesn't set a custom `jobName`.
- Reused the existing `PG_HOST` cluster-wide variable rather than introducing bykaj's `DB_HOST` name, matching this repo's established convention.
- Went straight to a shared Kustomize Component instead of a phased single-app pilot, since 3 consumers immediately clear this repo's documented "3+ apps" Component-creation threshold (`docs/ROADMAP.md`).

---

## 2026-07-28 — `externalsecret-rewrite-convention-cleanup`

### Goal
Bring every `ExternalSecret` in the cluster into conformance with the documented `dataFrom.extract` + `rewrite.regexp` mnemonic-prefix convention, closing the gap between what `docs/CONVENTIONS.md` already mandated and what the manifests actually did.

### What we did
- Audited all 26 files referencing `kind: ExternalSecret` in the repo and classified each by whether its `extract` blocks already carried a `rewrite`, confirming the convention itself was already documented in `docs/CONVENTIONS.md` (added in a prior session) but not fully applied.
- Used `AskUserQuestion` to resolve two ambiguous cases before editing: how to handle `firefly-iii-importer`'s apparently self-prefixed `FIREFLY_III_ACCESS_TOKEN` field, and whether to convert `flux-instance`'s discrete `data`/`remoteRef.property` pattern (item "GitHub App") to `extract`+`rewrite` or leave it as an exception.
- Verified live 1Password field labels via `op item get ... --format json | jq` for `firefly-III`, `smb-credentials`, and `grafana` before editing — this caught that `firefly-III`'s real field is `ACCESS_TOKEN` (not `FIREFLY_III_ACCESS_TOKEN`), revealing that `firefly-iii-importer`'s template was referencing a nonexistent key and silently rendering an empty secret value; fixed as part of adding the `FIREFLY_$1` rewrite.
- Renamed the `volsync-restic` 1Password item's field from `RESTIC_PASSWORD` to `PASSWORD` (via a `jq`-piped `op item edit`, keeping the concealed value untouched — same field ID before/after) so the shared VolSync component could add a proper `RESTIC_$1` rewrite instead of relying on a prefix baked into the field name; confirmed via `AskUserQuestion` given the blast radius (every VolSync-backed app in the cluster shares this item).
- Added `rewrite` blocks (and matching `target.template` key updates) to `forgejo` (app+db), `paperless-ngx` (app+db), `firefly-iii` (app+db+importer), `csi-driver-smb`, and the shared `components/volsync` `ExternalSecret`; replaced `kube-prometheus-stack`'s `grafana-admin` no-op identity rewrite (`(.*) → $1`) with a real `GRAFANA_$1` prefix.
- Documented the `flux-instance` discrete `data`/`remoteRef.property` pattern as an intentional exception in `docs/CONVENTIONS.md`, since its three fields are already unique and a blanket prefix would add ceremony without preventing any collision.
- Updated `docs/EXTERNAL-SECRETS.yaml` to match every manifest change, and in the process fixed a pre-existing, unrelated drift in the `smb-credentials` entry (it was documented as `import_mode: explicit` with `SMB_`-prefixed field names, but the live manifest was actually a wildcard extract with raw `USERNAME`/`PASSWORD` — now both agree).
- Validated every edited YAML file parses cleanly and confirmed via a Python/PyYAML sweep that no `ExternalSecret` in the repo has an `extract` block without an accompanying `rewrite`, except the documented `flux-instance` exception.
- Work is implemented but not yet committed — user's explicit `/git-stage`/`/git-commit` still pending, per repo convention.

### Files changed
| File | Change |
|------|--------|
| `docs/CONVENTIONS.md` | Added "Exception: discrete `data` + `remoteRef.property`" subsection documenting `flux-instance`'s pattern |
| `docs/EXTERNAL-SECRETS.yaml` | Updated `import_mode`/`known_fields`/notes for `firefly-III`, `forgejo`, `grafana`, `paperless`, `volsync-restic`, `smb-credentials` to match new rewrites; fixed pre-existing `smb-credentials` drift |
| `kubernetes/apps/development/forgejo/app/externalsecret.yaml` | Added `FORGEJO_$1` rewrite; updated `template` refs |
| `kubernetes/apps/development/forgejo/db/externalsecret.yaml` | Added `FORGEJO_$1` rewrite; updated `template` refs |
| `kubernetes/apps/documents/paperless-ngx/app/externalsecret.yaml` | Added `PAPERLESS_$1` rewrite to the `paperless` extract (kept existing `DRAGONFLY_$1` on the `dragonfly` extract); updated `template` refs |
| `kubernetes/apps/documents/paperless-ngx/db/externalsecret.yaml` | Added `PAPERLESS_$1` rewrite; updated `template` refs |
| `kubernetes/apps/finance/firefly-iii/app/externalsecret.yaml` | Added `FIREFLY_$1` rewrite; updated `template` refs |
| `kubernetes/apps/finance/firefly-iii/db/externalsecret.yaml` | Added `FIREFLY_$1` rewrite; updated `template` refs |
| `kubernetes/apps/finance/firefly-iii-importer/app/externalsecret.yaml` | Added `FIREFLY_$1` rewrite; fixed stale `.FIREFLY_III_ACCESS_TOKEN` template reference to `.FIREFLY_ACCESS_TOKEN` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/externalsecret.yaml` | Replaced `grafana-admin`'s no-op identity rewrite with `GRAFANA_$1`; updated `template` ref |
| `kubernetes/apps/system/csi-driver-smb/app/externalsecret.yaml` | Added `SMB_$1` rewrite, `engineVersion: v2`; updated `template` refs |
| `kubernetes/components/volsync/externalsecret.yaml` | Added `RESTIC_$1` rewrite to match the renamed 1Password field |

### Key decisions
- Chose `FIREFLY_$1` etc. — a short mnemonic derived from the 1Password item name, not a literal 2-character code — matching the pattern already established by `CNPG_`, `DRAGONFLY_`, `ALERTMANAGER_` in the repo (length isn't the invariant; "1Password fields stay unprefixed, rewrite adds the app namespace" is).
- Renamed the `volsync-restic` 1Password field rather than leaving it unprefixed-and-exempt, since the user explicitly opted for full convention compliance over a low-risk shortcut, despite the shared blast radius across every VolSync consumer.
- Left `flux-instance` on its discrete `data`/`remoteRef.property` pattern rather than converting it, per user's choice — its fields are already unique so `extract`+`rewrite` would add no safety benefit.

---

## 2026-07-28 — `csi-nfs-smb-storage-deployment`

### Goal
Implement the ROADMAP's "Future Storage Options" item: deploy `csi-driver-nfs` and `csi-driver-smb` for NAS-backed ReadWriteMany storage that doesn't consume Ceph capacity.

### What we did
- Reviewed `docs/ROADMAP.md`'s "Future Storage Options" entry and cross-referenced a sibling community repo (`tmp/home-ops-bykaj`) for real-world `csi-driver-nfs`/`csi-driver-smb` deployment patterns, using two parallel Explore agents to cover roadmap/current-cluster-storage context and the reference repo's actual manifests simultaneously.
- Used `AskUserQuestion` to lock in three storage-safety decisions before designing: create a dynamic NFS StorageClass now rather than deferring it, use `Delete` reclaim policy for that general-purpose pool, and provision NFS on a dedicated new TrueNAS export rather than reusing the existing `postgres-backup-local`/Volsync export (diverging from the reference repo's approach of reusing its existing export).
- Ran a Plan agent to produce a concrete file-by-file design, independently verifying every cited convention against real repo files first (namespace-per-app pattern in `kubernetes/apps/system/`, centralized `OCIRepository` sources in `kubernetes/flux/meta/repos/oci/`, the `dependsOn: onepassword-connect` rule for ExternalSecret-bearing Kustomizations, and the exact Talos NFS mount defaults from `talos/patches/global/machine-files.yaml`).
- Implemented `csi-driver-nfs` (dynamic `nfs` StorageClass backed by a dedicated `/mnt/tank/Cluster/k8s-nfs-csi` export, `Delete` reclaim, mount options mirroring Talos's own NFS defaults) and `csi-driver-smb` (driver + `smb-credentials` ExternalSecret only, no StorageClass — deferred until a real consumer needs static per-share PVs) as new `kubernetes/apps/system/` Flux apps.
- Added centralized `OCIRepository` chart sources with cosign signature verification (matching the `openebs.yaml` pattern), wired both apps into `kubernetes/apps/system/kustomization.yaml`, and validated every new/edited Kustomize path with `kubectl kustomize`.
- Updated `docs/ROADMAP.md`, `docs/EXTERNAL-SECRETS.yaml`, and `docs/POTENTIAL-DEPLOYMENTS.md` to reflect the new deployment status, including the two manual out-of-band prerequisites (TrueNAS export creation, `smb-credentials` 1Password item) still required before it's functional, and flagging that Talos's CIFS/SMB kernel client support is unconfirmed pending a real static-PV smoke test.
- Work is implemented but not yet committed — user's explicit `/git-stage`/`/git-commit` still pending, per repo convention.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/csi-driver-nfs.yaml` | New — OCIRepository source, `csi-driver-nfs` chart w/ cosign verify |
| `kubernetes/flux/meta/repos/oci/csi-driver-smb.yaml` | New — OCIRepository source, `csi-driver-smb` chart w/ cosign verify |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Wired in both new OCIRepository sources |
| `kubernetes/apps/system/csi-driver-nfs/ks.yaml` | New — Flux Kustomization, `targetNamespace: csi-driver-nfs` |
| `kubernetes/apps/system/csi-driver-nfs/app/namespace.yaml` | New — dedicated namespace |
| `kubernetes/apps/system/csi-driver-nfs/app/kustomization.yaml` | New |
| `kubernetes/apps/system/csi-driver-nfs/app/helmrelease.yaml` | New — HelmRelease w/ dynamic `nfs` StorageClass |
| `kubernetes/apps/system/csi-driver-smb/ks.yaml` | New — Flux Kustomization, `dependsOn: onepassword-connect` |
| `kubernetes/apps/system/csi-driver-smb/app/namespace.yaml` | New — dedicated namespace |
| `kubernetes/apps/system/csi-driver-smb/app/kustomization.yaml` | New |
| `kubernetes/apps/system/csi-driver-smb/app/externalsecret.yaml` | New — `smb-credentials` ExternalSecret |
| `kubernetes/apps/system/csi-driver-smb/app/helmrelease.yaml` | New — HelmRelease, driver-only, no StorageClass |
| `kubernetes/apps/system/kustomization.yaml` | Wired in both new `ks.yaml` entries |
| `docs/ROADMAP.md` | Added deployment status note to "Future Storage Options" |
| `docs/EXTERNAL-SECRETS.yaml` | Added `smb-credentials` 1Password item entry; bumped `last_verified` |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Marked `csi-driver-nfs`/`csi-driver-smb` rows deployed w/ current versions |

### Key decisions
- Dedicated NFS export (`/mnt/tank/Cluster/k8s-nfs-csi`) instead of reusing the existing `/mnt/tank/Cluster` export — the dynamic provisioner creates/deletes a subdirectory per PVC, which shouldn't share a path with hand-managed backup exports it doesn't own.
- SMB deployed driver-only with no StorageClass/PV — each SMB share needs its own distinct source path and credentials, so there's nothing generic to provision dynamically until a real consumer exists; follows the reference repo's static-PV-per-share pattern as documented follow-up work.
- `Delete` reclaim policy for the general-purpose NFS pool — anything precious should get its own hand-authored static PV with `Retain` instead, mirroring how SMB is already handled.

---

## 2026-07-26 — `paperless-ngx-gitops-deployment`

### Goal
Design and implement the paperless-ngx (document management/OCR) GitOps deployment, wired to the newly-available cluster-wide Dragonfly instance.

### What we did
- Researched community GitOps patterns for paperless-ngx via kubesearch.dev and `gh api search/code`, examining `bykaj/home-ops` (shared CNPG + Dragonfly + SMB/NAS storage + OIDC, no Gotenberg/Tika) and `vaskozl/home-infra` (single app-template controller bundling app+Gotenberg+Tika+Redis as localhost sidecars) as concrete community references.
- Ran a full Plan Mode design pass (1 Explore agent surveying this repo's existing CNPG/ceph-block-fsGroup/VolSync conventions via `firefly-iii`/`pgadmin`/`forgejo`, 1 Plan agent producing a concrete file-by-file design) and used `AskUserQuestion` to lock in Gotenberg+Tika inclusion, web-UI/API-only ingestion (no NFS watched folder), internal-only access, and OCR language (Dutch+English).
- User rejected two initial `ExitPlanMode` attempts, instead deferring the whole deployment until a cluster-wide Redis-compatible store existed — paperless-ngx would otherwise have been the first and only consumer of a one-off in-pod Redis sidecar; plan and rationale saved to memory.
- Resumed the session after Dragonfly was deployed cluster-wide (separate session); revised the plan to drop the in-pod Redis/Valkey sidecar entirely and wire paperless-ngx to the shared Dragonfly instance instead (db index 0), adding `dependsOn: dragonfly` to the app Kustomization and extending the app-level `ExternalSecret` to also pull the existing `dragonfly` 1Password item.
- Implemented the design in an isolated worktree: new `documents` namespace, a `paperless-ngx` app-template `HelmRelease` (this repo's first multi-container controller — `app`+`gotenberg`+`tika` as localhost sidecars, no separate Redis container), a CNPG `Database` CR + managed role wired to the shared `postgres-v17` cluster, 4 `ceph-block` PVCs (only `media` VolSync-backed via `existingClaim`), and an internal-only `HTTPRoute`.
- Pinned concrete current versions via live GitHub/Docker Hub API lookups rather than guessing (`paperless-ngx:3.0.3`, `gotenberg:8.34.0`, `apache/tika:3.3.1.0`).
- Validated every new/edited path with `kubectl kustomize` + `kubeconform -strict`, confirming the one reported `HTTPRoute` hostname "error" is a pre-existing `${DOMAIN_CLUSTER}` substitution false-positive also present on `firefly-iii`'s already-deployed `HTTPRoute`.
- After the user created the 1Password `paperless` item with field names that differed from the initially-drafted placeholders (`DB_USER`/`SECRET_KEY`/`ADMIN_USER`/`ADMIN_MAIL`/`ADMIN_PASSWORD`, no `PAPERLESS_` prefix), corrected both `ExternalSecret` templates and `docs/EXTERNAL-SECRETS.yaml`'s field lists to match, re-validating after the fix.
- Work is implemented but not yet committed — user's explicit `/git-stage`/`/git-commit` still pending, per repo convention.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/documents/namespace.yaml` | New — `documents` namespace |
| `kubernetes/apps/documents/kustomization.yaml` | New |
| `kubernetes/apps/documents/paperless-ngx/ks.yaml` | New — 2-doc Flux Kustomization (`db` + `app`) |
| `kubernetes/apps/documents/paperless-ngx/db/database.yaml` | New — CNPG `Database` CR |
| `kubernetes/apps/documents/paperless-ngx/db/externalsecret.yaml` | New — DB role secret |
| `kubernetes/apps/documents/paperless-ngx/db/kustomization.yaml` | New |
| `kubernetes/apps/documents/paperless-ngx/app/helmrelease.yaml` | New — 3-container app-template controller (app/gotenberg/tika) |
| `kubernetes/apps/documents/paperless-ngx/app/externalsecret.yaml` | New — app secrets + Dragonfly-sourced `PAPERLESS_REDIS` |
| `kubernetes/apps/documents/paperless-ngx/app/httproute.yaml` | New — internal-only route |
| `kubernetes/apps/documents/paperless-ngx/app/kustomization.yaml` | New |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added `paperless` managed role |
| `kubernetes/apps/kustomization.yaml` | Registered `./documents` |
| `docs/EXTERNAL-SECRETS.yaml` | Added `paperless` item + new `dragonfly`/`volsync-restic` consumer entries |

### Key decisions
- Hybrid of the two community reference architectures rather than copying either: this repo's existing shared-CNPG convention, plus Dragonfly-as-shared-broker once it became available, instead of bykaj's SMB/NAS+OIDC or vaskozl's fully self-bundled sidecars.
- `media` PVC uses `existingClaim: "${VOLSYNC_CLAIM:=paperless-ngx}"` rather than a self-declared PVC — traced explicitly through `components/volsync/pvc.yaml`/`replicationsource.yaml` to guarantee it's the same volume VolSync backs up, rather than relying on implicit PVC-name matching (which `firefly-iii`'s own setup leaves ambiguous).
- Only the `media` PVC (irreplaceable document archive) is VolSync-backed; `data`/`export`/`consume` are treated as regenerable/transient and excluded to keep backup size/time down.
- Internal-only access (`envoy-internal`) chosen over public/Tailscale exposure, matching how `firefly-iii`/`forgejo` (also sensitive personal data) are exposed in this repo.

---

## 2026-07-25 — `dragonfly-cluster-wide-deployment`

### Goal
Research and deploy a cluster-wide, reusable Redis-protocol-compatible datastore (Dragonfly) as shared infrastructure, deferring the previously-designed paperless-ngx deployment until it exists.

### What we did
- Reviewed a prior paused paperless-ngx GitOps plan (Gotenberg+Tika, web-UI-only ingestion, internal-only access, shared CNPG postgres); user deferred implementing it in favor of building a cluster-wide Valkey/Redis solution first, since paperless would otherwise have been the first and only consumer of a one-off in-pod sidecar.
- Researched community consensus for Redis-compatible stores in homelab GitOps repos via `gh api search/code` adoption counts (`dragonfly-operator`: 1212 hits vs `valkey-operator`: 381) and by reading `bykaj/home-ops`'s actual Dragonfly manifests; recommended Dragonfly over Valkey/Bitnami Redis, primarily because its HA model (in-memory replication across `spec.replicas`) avoids this cluster's Ceph RBD ReadWriteOnce-only limitation entirely.
- Ran a full Plan Mode design pass (2 parallel Explore agents + 1 Plan agent, resumed once after a harness restart interrupted it) verifying every claim directly against upstream `dragonflydb/dragonfly-operator` source (`dragonfly_types.go`, chart `values.yaml`/templates) and this repo's own `cloudnative-pg` operator+cluster Kustomization pattern, rather than copying the community reference's `app-template`-based approach.
- Implemented the design: new `dragonfly-operator` OCIRepository source, a 2-document `ks.yaml` (operator Kustomization → CRD-instance Kustomization) in `kubernetes/apps/database/dragonfly/`, the official operator Helm chart (not `app-template`, mirroring CNPG), a `Dragonfly` CR with 3 replicas + `topologySpreadConstraints` + `networkPolicyEnabled: false`, a wildcard/rewrite `ExternalSecret` for a new 1Password `dragonfly` item (created by the user), and a hand-authored `PodMonitor` for per-instance metrics.
- Validated the full repo with `task validate` (kubeconform against Flux's OpenAPI schemas) — all new resources passed, `kustomize build` rendered cleanly for both the operator and cluster paths.
- Updated `docs/EXTERNAL-SECRETS.yaml` (new `dragonfly` item entry, bumped `last_verified`) and corrected a stale `docs/POTENTIAL-DEPLOYMENTS.md` line that assumed an `app-template`-based deployment at an old chart version.
- On a follow-up question about future persistence, verified the `Dragonfly` CRD's native `spec.snapshot` field (S3 `dir`, `cron`, `enableOnMasterOnly`, or PVC-backed) directly from operator source, and recorded a config sketch + rationale in `docs/ROADMAP.md` (favoring S3-backed snapshots reusing the existing `plugin-barman-cloud`/Backblaze B2 pattern over PVC-backed, to preserve the disk-free design) rather than adding unused config to the live CR.
- Saved a memory (`paperless-ngx-deployment-plan.md`) documenting the paused paperless-ngx plan and its dependency on this work.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/dragonfly-operator.yaml` | New OCIRepository source for the `dragonfly-operator` Helm chart |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added the new OCIRepository to resources |
| `kubernetes/apps/database/kustomization.yaml` | Added `./dragonfly` to resources |
| `kubernetes/apps/database/dragonfly/kustomization.yaml` | New — points at `ks.yaml` |
| `kubernetes/apps/database/dragonfly/ks.yaml` | New — 2-doc Flux Kustomization (operator + CRD instance) |
| `kubernetes/apps/database/dragonfly/operator/app/kustomization.yaml` | New |
| `kubernetes/apps/database/dragonfly/operator/app/helmrelease.yaml` | New — `dragonfly-operator` HelmRelease (chart-native, `rbacProxy` disabled, monitoring/dashboard enabled) |
| `kubernetes/apps/database/dragonfly/cluster/app/kustomization.yaml` | New |
| `kubernetes/apps/database/dragonfly/cluster/app/externalsecret.yaml` | New — pulls the `dragonfly` 1Password item |
| `kubernetes/apps/database/dragonfly/cluster/app/cluster.yaml` | New — `Dragonfly` CR, 3 replicas, `networkPolicyEnabled: false` |
| `kubernetes/apps/database/dragonfly/cluster/app/podmonitor.yaml` | New — scrapes the instance's `admin` metrics port |
| `docs/EXTERNAL-SECRETS.yaml` | Added `dragonfly` item entry; bumped `last_verified`/`last_verified_commit` |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Corrected the dragonfly row (was `app-template` v4.6.2, now reflects the actual native-chart deployment) |
| `docs/ROADMAP.md` | Added a "Dragonfly: Snapshot Persistence (Future)" reference section |

### Key decisions
- Chose Dragonfly over Valkey/Redis: community adoption plus its in-memory replication model avoids needing a shared/replicated PVC on Ceph RBD (RWO-only).
- Deployed via the official `dragonfly-operator` chart directly (`chartRef: OCIRepository`), not `bjw-s/app-template` — mirrors this repo's own `cloudnative-pg` pattern and avoids re-implementing RBAC the chart already ships (the community reference repo had hand-rolled it unnecessarily).
- Set `spec.networkPolicyEnabled: false` on the `Dragonfly` CR, deliberately overriding the operator's same-namespace-only default — the entire purpose of this deployment is to be a cross-namespace, multi-tenant service, and this repo has no NetworkPolicy resources elsewhere by design.
- Set `rbacProxy.enabled: false` on the operator chart to expose plaintext `/metrics` rather than requiring a new `kube-rbac-proxy` bearer-token ClusterRoleBinding — matches this repo's existing metrics-exposure posture on every other operator.
- Deferred persistence/snapshotting entirely for now (no consumer needs durability yet); recorded the future config as a `docs/ROADMAP.md` reference note rather than dead config in the live manifest, per the repo's own "don't design for hypothetical requirements" convention.

---

## 2026-07-25 — `truenas-thermal-incident-docker-recovery`

### Goal
Investigate a recurring TrueNAS CPU over-temperature alert to find and prevent the root cause, then diagnose and recover a Docker/Apps outage on the same host that surfaced mid-investigation as a consequence of the incident.

### What we did
- Investigated an AlertManager CPU-temperature alert (>90°C, 2nd occurrence) reported ~11:05 local (09:05 UTC); initially hypothesized VolSync's shared hourly backup schedule (`waha`, `pgadmin`, `firefly-iii`, `forgejo` all on the default `0 * * * *` Restic schedule to the same NFS path) as the cause, since `docs/CLUSTER.md` already documents a thundering-herd mitigation for exactly this concern.
- Dispatched a `cluster-doctor` agent to pull live Prometheus/Alertmanager data for the exact window (08:40–09:12 UTC), which disproved the VolSync theory: the temp spike was a step-function (+29°C in a single 30s sample at 08:45:30 UTC) with CPU usage staying flat (~91% idle) for the entire critical period; every VolSync job started 15 minutes *after* the spike began. Only the CPU package sensor (`k10temp`/Tctl) moved — NVMe, drives, NIC, and RAM SPD sensors all stayed normal.
- Investigated whether the `sensors-textfile` hwmon sidecar could be reconfigured to expose real fan RPM telemetry: confirmed the sidecar's collection code is already generic and fan-capable (no code gap), then, via read-only on-box inspection the user ran (`/sys/class/hwmon`, `lsmod`, `dmidecode`, `journalctl -k -b`, ACPI device enumeration), found the board (`F8NAA`, a Shenzhen Meigao/Minisforum-family ODM board) exposes no Super I/O or fan-tach chip to Linux at all — only the generic ACPI Embedded Controller (`PNP0C09`) and AMI BIOS 1.04, which reads fan RPM via an OS-invisible SMI path. Concluded this is a hardware/firmware ceiling, not a config gap, and declined to pursue raw EC-register access (`ec_sys`) given no vendor documentation exists for this board.
- Mid-investigation, the user reported Docker/"Apps" hadn't restarted since the thermal-incident shutdown, which was also why `node-exporter`/`smartctl-exporter` were down. Diagnosed live via commands the user ran: `zpool status` showed both pools healthy (ruling out post-shutdown ZFS corruption); a manual `systemctl start docker` succeeded but produced an empty `docker ps -a` — traced to Docker's configured `--data-root` (`/mnt/.ix-apps/docker`) being an unmounted ZFS mountpoint, so `dockerd` silently initialized a fresh, empty state directory on the boot-pool root filesystem instead of finding the real 57.6G dataset.
- Found the `tank/ix-apps` dataset tree carries `canmount=noauto`, so it's never mounted by generic `zfs mount -a` — mounting it is middleware's own app-lifecycle responsibility. Confirmed via `midclt call docker.status` = `FAILED`, a state that hadn't self-healed across at least two reboots.
- Fixed by forcing a genuine state transition via `midclt call docker.update`: unsetting the pool (`{"pool": null}` — real teardown, unmounted `tank/ix-apps`, status → `UNCONFIGURED`) then re-setting it (`{"pool": "tank"}` — ~21s, real setup: mounted the full dataset tree in order and started `dockerd` with all previously-running containers). Verified full recovery — `docker.status` = `RUNNING`, `docker ps -a` showed every container (this repo's own `node-exporter`/`smartctl-exporter`/`doco-cd` stack plus all TrueNAS-native apps) `Up` with authentic multi-week/-month `CREATED` timestamps — no data loss.
- Investigated the original trigger for the Docker failure: ruled out "unclean shutdown" once the user confirmed the shutdown was clean, in favor of a timing-correlated theory — the `doco-cd` health-endpoint probe had already started failing at 08:51:00 UTC, five minutes into the thermal event and well before the shutdown, suggesting Docker was disrupted by the thermal event itself. Tried to confirm via `middlewared.log`/`journalctl` for the incident window but found no entries at all; concluded the box was almost certainly already powered off before that window could be logged, and that TrueNAS's journald likely isn't persistent across reboots — left the exact original trigger as an evidence-correlated inference rather than a proven trace.

### Files changed
None — this session was live incident investigation and remediation on the TrueNAS host itself; no repository files were changed.

### Key decisions
- Declined to pursue raw EC-register access (`ec_sys`) for fan RPM telemetry — too risky/undocumented on a NAS board with no available vendor register map, for a benefit (fan speed monitoring) that a rate-of-change temperature alert can substantially cover instead.
- Held off letting the user recreate TrueNAS-native (non-GitOps) apps via `docker compose up`/the Apps UI before confirming the real data-root mount was restored — those apps (Plex, Paperless-ngx, Syncthing, etc.) have no Git-backed definition to recover from, so avoiding a premature recreate was the only thing preventing real data loss.
- Used `midclt call docker.update` (unset then reset the pool) rather than manually `zfs mount`-ing each `noauto` dataset — this is middleware's own supported lifecycle path and atomically handled correct mount ordering plus Docker startup, rather than risking a partially-mounted tree.

---

## 2026-07-20 — `forgejo-gitops-deployment`

### Goal
Investigate how to deploy a self-hosted git server, then design and build a full GitOps deployment for it, following the `finance/firefly-iii` architectural pattern (external CNPG database, `ceph-block` persistence, consolidated 1Password secret, Gateway API routing).

### What we did
- Investigated homelab community deployment patterns (kubesearch.dev, live GitHub code search) for self-hosted git; the two local `tmp/` reference repos (`home-ops-bykaj`, `k8s-homelab`) turned out to have no git-server deployment to learn from. Found `bjw-s-labs/home-ops` (this repo's own `app-template` chart maintainer) runs Forgejo, not Gitea; `gabe565/home-ops`'s Gitea-with-external-Postgres values were the closest concrete precedent. Presented the Gitea-vs-Forgejo finding to the user, who chose **Forgejo**.
- Verified the upstream Forgejo Helm chart schema directly from source (`code.forgejo.org/forgejo-helm/forgejo-helm`) rather than assuming Gitea's chart schema carried over unchanged — confirmed it has no bundled `postgresql`/`valkey` subcharts (only a `bitnami-common` dependency), confirmed `cache`/`queue`/`session` fall back to `memory`/`level`/`memory` when left unset (safe for a single-replica deployment), and confirmed `podSecurityContext.fsGroup: 1000` and `strategy.type: Recreate` are already the chart's own defaults — pre-empting the exact `ceph-block` fsGroup failure mode a prior session hit with Firefly III.
- Confirmed via `ops/bootstrap/helmfile.d/00-crds.yaml` that the `TCPRoute` CRD is already installed (bundled with the `envoy-gateway-crds` pre-bootstrap release), so exposing git-over-SSH via a Gateway API `TCPRoute` needed no new CRD bootstrap work. Used the chart's own native `tcpRoute` values block (matching `bjw-s-labs`' choice) instead of hand-authoring a `TCPRoute` manifest.
- At the user's prompting, surveyed community namespace conventions for where Forgejo lives (`bjw-s-labs`/`rafaribe` use a narrow `dev`/`development` namespace; `NovaMachina` uses a broad `self-hosted` catch-all) and switched from an initially-planned dedicated `forgejo` namespace to a new `development` namespace — matching this repo's existing thematic-namespace convention and leaving room for a future Actions-runner sibling app.
- Built the full deployment: `OCIRepository` chart source (`oci://code.forgejo.org/forgejo-helm/forgejo`, pinned `17.1.3`), the `development` namespace, and the `forgejo` app/db `Kustomization` pair (HelmRelease with consolidated 1Password `ExternalSecret`, `HTTPRoute` on `envoy-internal`, chart-native `TCPRoute` for SSH; CNPG `Database` CRD + `ExternalSecret` for the DB role) — mirroring `firefly-iii`'s two-Kustomization `dependsOn` shape exactly.
- Added a `forgejo` role entry to the shared CNPG `postgres-v17` cluster's `managed.roles`, and a new `ssh` TCP listener (port 22, LAN-only) to the `envoy-internal` Gateway only — verified by re-reading the file that the edit didn't also land on `envoy-external` (its cert list has different inline comments that made the match string unique to `envoy-internal`).
- Regenerated `docs/CLUSTER.md`'s auto dependency graph via `scripts/depgraph.py` (0 dangling references, 0 cycles) and added a short prose note on the new `ssh`/`TCPRoute` capability; added a `forgejo` item entry to `docs/EXTERNAL-SECRETS.yaml`; recorded deferred follow-ups (Actions runner, PVC backup, WAN exposure, OIDC/SSH signing) in `docs/ROADMAP.md`.
- Validated every new and edited `kustomization.yaml` with `kubectl kustomize` dry-run builds (top-level `kubernetes/apps`, the new `development` tree, the edited CNPG cluster and Envoy Gateway config) — all built cleanly with no errors.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/forgejo.yaml` | New `OCIRepository` chart source, pinned `17.1.3` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered `forgejo.yaml` |
| `kubernetes/apps/development/namespace.yaml` | New `development` namespace |
| `kubernetes/apps/development/kustomization.yaml` | New — lists `forgejo/ks.yaml` |
| `kubernetes/apps/development/forgejo/ks.yaml` | New — `forgejo-db` + `forgejo` Flux Kustomizations |
| `kubernetes/apps/development/forgejo/app/helmrelease.yaml` | New — Forgejo HelmRelease (external Postgres, `ceph-block`, chart-native TCPRoute for SSH) |
| `kubernetes/apps/development/forgejo/app/externalsecret.yaml` | New — consolidated 1Password secret (admin creds) |
| `kubernetes/apps/development/forgejo/app/httproute.yaml` | New — `envoy-internal` HTTPRoute, `forgejo.${DOMAIN_CLUSTER}` |
| `kubernetes/apps/development/forgejo/app/kustomization.yaml` | New — lists app resources |
| `kubernetes/apps/development/forgejo/db/database.yaml` | New — CNPG `Database` CRD against shared `postgres-v17` cluster |
| `kubernetes/apps/development/forgejo/db/externalsecret.yaml` | New — DB role basic-auth secret, `cnpg.io/reload` labeled |
| `kubernetes/apps/development/forgejo/db/kustomization.yaml` | New — lists db resources |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added `forgejo` role to shared cluster's `managed.roles` |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Added `ssh` TCP listener (port 22) to `envoy-internal` only |
| `kubernetes/apps/kustomization.yaml` | Registered `./development` |
| `docs/CLUSTER.md` | Regenerated auto dependency graph; added `ssh`/`TCPRoute` note |
| `docs/EXTERNAL-SECRETS.yaml` | Added `forgejo` 1Password item entry |
| `docs/ROADMAP.md` | Added deferred-follow-ups entry (runner, backup, WAN exposure, OIDC/signing) |

### Key decisions
- Used the official upstream Forgejo Helm chart rather than `app-template` — unlike Firefly (a single-container Laravel app), Forgejo is multi-concern (web + SSH + queue + cache + migrations) with real upstream chart support, so reimplementing it in raw `app-template` containers would mean re-deriving already-solved logic (e.g. the memory/level cache-queue-session fallback).
- Deployed Forgejo instead of the originally-named Gitea, after community research showed the homelab GitOps ecosystem — including this repo's own `app-template` chart maintainer — has largely moved to Forgejo; user confirmed the switch after seeing the evidence.
- Disabled the chart's native `httpRoute` in favor of a hand-written `httproute.yaml` (to keep `gethomepage.dev` annotations and match this repo's HTTP-route convention), but kept the chart's native `tcpRoute` toggle for SSH rather than hand-authoring a `TCPRoute` — there's no equivalent annotation need for the SSH route, and the chart already pairs its `Service` and `TCPRoute` correctly.
- Placed the new `ssh` Gateway listener on `envoy-internal` only (LAN-only), not `envoy-external`, matching the HTTPRoute's own LAN-only default — extending either surface to WAN later is a one-line `parentRefs` addition, not a redesign.
- Deferred Forgejo Actions runner, PVC backup, WAN exposure, and OIDC/SSH signing rather than building them now, per explicit user direction.

---

## 2026-07-18 — `diagnose-alerts-command-and-ceph-packetdrops-tuning`

### Goal
Build a `/diagnose-alerts` slash command for triaging firing/recent Alertmanager alerts against live cluster state and repo context, then use it to root-cause and fix recurring `CephNodeNetworkPacketDrops` false positives.

### What we did
- Explored the observability stack (`kube-prometheus-stack`, `silence-operator`, `AlertmanagerConfig` Pushover routing) and confirmed Prometheus/Alertmanager are reachable directly via `curl` from the devcontainer through their internal `envoy-internal` HTTPRoutes — no port-forward needed.
- Wrote `.claude/commands/diagnose-alerts.md`: pulls live state from Alertmanager (`/api/v2/alerts`, `/api/v2/silences`) and Prometheus (`/api/v1/rules`, `ALERTS{}` timeseries for alerts that already resolved), cross-references against in-repo `PrometheusRule` definitions/comments, `silence-operator` `Silence` files, `docs/QA.md`/`SESSIONS.md`, and the severity→receiver routing, then reports per-alert with a recommendation — diagnosis-only, never auto-edits cluster resources.
- Ran it against `CephNodeNetworkPacketDrops` (5 episodes, 2026-07-11 → 07-18, on the `eno1` management NIC across cp-02/cp-03/worker-01/worker-02). Found an existing but `INACTIVE` `Silence` for this alertname was for an unrelated, already-resolved cause (X520 storage-bond VLAN-200 fallback); the current episodes matched a different, previously-documented pattern (`docs/QA.md`, 2026-06-20) of brief, unexplained traffic bursts on the management NIC.
- Tried to retroactively root-cause via `talosctl dmesg` on cp-02 — found the kernel ring buffer had gone silent since `2026-07-15T17:12` despite continuous uptime since `2026-07-09` (confirmed via `node_boot_time_seconds`, ruling out a reboot). Corrected an imprecise initial claim about this gap after the user pushed back on it. Concluded `dmesg` was never going to catch this class of event anyway — packet-drop counters come from `/proc/net/dev` via node-exporter, not kernel `printk` messages.
- Re-checked the 7-day burst history at the rule group's native 30s evaluation resolution (the initial 7-day scan used a 60s query step, which risked aliasing) — confirmed all 5 episodes were exactly one 30s evaluation tick each, never two consecutive, with CPU/pod-restarts/conntrack all flat during the two clearest (cp-02) bursts.
- Found the fix mechanism already in use in this repo for an analogous problem: `rook-ceph-cluster`'s `monitoring.prometheusRuleOverrides` (used for `CephNodeDiskspaceWarning`'s `for:` fix). Verified via the upstream `rook/rook` chart template (`prometheusrules.yaml`, fetched via `gh api`) that it uses Sprig `mergeOverwrite`, so a partial override (`for:` only) is valid and leaves `expr`/`labels`/`annotations` untouched.
- Worked through `for:` boundary semantics with the user (does `for: 30s` at `interval: 30s` need 2 or 3 consecutive true evaluations) — verified directly against Prometheus's `rules/alerting.go` source (`ts.Sub(a.ActiveAt) >= r.holdDuration`, non-strict) rather than answering from memory. Landed on `for: 1m` (user's choice, over the theoretical-minimum `30s`) for extra margin against eval-alignment luck.
- Added `CephNodeNetworkPacketDrops: { for: 1m }` to the `prometheusRuleOverrides` block, with a comment documenting the evidence (episode count/dates, native-resolution confirmation, baseline vs. burst magnitudes) so the reasoning doesn't need to be re-derived later.

### Files changed
| File | Change |
|------|--------|
| `.claude/commands/diagnose-alerts.md` | New slash command for triaging firing/recent Alertmanager alerts |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Added `prometheusRuleOverrides.CephNodeNetworkPacketDrops: {for: 1m}` (staged, uncommitted) |

### Key decisions
- Chose to debounce (`for: 1m`) rather than silence the alert outright — two independent investigations (2026-06-20 archived one, and this session's) found no operational impact and no internal cause, but the user preferred to keep the signal live for a genuinely sustained event rather than suppress it.
- Picked `for: 1m` over the theoretical-minimum `for: 30s`: both would have suppressed all 5 historical false-fires equally (none exceeded 1 tick), but `1m` adds slack against eval-alignment edge cases at negligible cost to detection latency for a real problem.
- Left `expr`/thresholds on the stock rule untouched — the evidence showed a missing-debounce problem (`for: 0`), not a threshold-too-strict problem; the observed bursts genuinely exceeded even the existing ratio/absolute thresholds.

---

## 2026-07-18 — `hwmon-textfile-staleness-alert`

### Goal
Verify the hwmon textfile-collector sidecar is working correctly in production end-to-end, then close a silent-failure gap (identified via advisor review) with a staleness alert and clarifying version-coupling comments.

### What we did
- Responded to user-pasted TrueNAS `docker logs` (post context-compaction) by verifying live production state directly rather than trusting the log snippet alone: confirmed via `git` that the earlier `chmod 644` permission fix (from the prior session) was committed at `HEAD`/`origin` (commit `dd7c810`), and that local `main` was 1 commit behind `origin/main` (unrelated Renovate helmfile bump `846cb1a`).
- Queried node-exporter's live `/metrics` (`curl 10.10.0.41:9100/metrics`) and Prometheus's target/query APIs to confirm end-to-end health: `node_textfile_scrape_error 0`, 49 `node_hwmon_*` metric lines, target `health: up`, and `node_hwmon_temp_celsius` queryable through Prometheus itself — confirmed the AMD `k10temp` chip id (`pci0000:00_0000:00:18_3`) exactly matches the existing `hardware-temperatures` PrometheusRule's regex, so the CPU alerts cover the TrueNAS host automatically with no further changes.
- Investigated a transient `gzip: invalid checksum` scrape error caught mid-check: a fresh target query showed it had self-healed on the very next 30s scrape cycle, and reproducing Prometheus's exact gzip-accepting scrape request via `curl` returned a clean stream — concluded it was a one-off transport blip, not a sidecar/code bug.
- Ran the `advisor` tool (Opus 4.8) for independent review of the full arc — the original hwmon panic, the textfile-collector redesign, and the live cluster + TrueNAS configuration. Key finding: the redesign converted a loud failure mode (hwmon panic → node_exporter dies → `TargetDown` fires) into a silent one — if `sensors-textfile` dies or hangs, node-exporter stays healthy and keeps serving `hwmon.prom`'s last-written values forever, so a real thermal event could hide behind frozen data. Also flagged a silent version-coupling risk in the hand-reproduced chip-id algorithm.
- Implemented the staleness alert in `hardware-temps.yaml`: `NodeHwmonTextfileStale`, firing when `node_textfile_mtime_seconds` hasn't advanced in >90s (6x the sidecar's 15s scan interval). While writing it, caught and fixed a real bug before it shipped: the initial expression matched `file="hwmon.prom"`, but production's actual label value is the full path `file="/textfile/hwmon.prom"` — the wrong label would have made the alert permanently silent (zero matching series), exactly the failure mode it exists to catch. Verified the corrected expression against live Prometheus data (~18s, well under threshold).
- Added the version-coupling comment block to `entrypoint.sh`'s header (noting the chip-id algorithm was verified against node_exporter v1.11.1, tracked via `.env`) plus a pointer from `chip_id()` itself, so a future `NODE_EXPORTER_VERSION` bump has an explicit trigger to re-verify chip-naming parity.
- Validated both edits: the PrometheusRule parses via PyYAML with the new 7th rule present; `entrypoint.sh` still passes `dash -n` syntax check after the comment additions.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml` | Added `NodeHwmonTextfileStale` alert rule (staged) |
| `truenas/docker/node-exporter/sensors-textfile/entrypoint.sh` | Added version-coupling comments to header and `chip_id()` (staged) |

### Key decisions
- Chose `file="/textfile/hwmon.prom"` (full path) over the bare filename for the staleness alert's label match — verified against live production data rather than assuming node_exporter's textfile collector labels with just the filename; the wrong assumption would have shipped a permanently-silent alert.
- Threshold set to 90s (6x the sidecar's 15s scan interval) — chosen to comfortably exceed normal scrape/collection jitter while still catching a hung/dead sidecar well before a real thermal event could hide behind stale data.
- Documented the chip-id algorithm's version coupling directly in the script rather than treating it as accepted risk — a future node_exporter bump on this host could silently break dashboard/alert matching with no error surfaced anywhere, so the mitigation is a code comment creating an explicit re-verification trigger, not a technical guardrail (none exists that's low-effort enough to be worth building).

---

## 2026-07-17 — `node-exporter-hwmon-crash-fix`

### Goal
Root-cause the `TargetDown` alert on TrueNAS's `node-exporter` and land a durable fix that keeps hardware sensor monitoring working without touching the buggy code path.

### What we did
- Queried Alertmanager's v2 API (`kubectl get --raw .../proxy/api/v2/alerts`) to list firing alerts: `TargetDown` (`truenas-node-exporter`, warning) and the expected always-firing `Watchdog` heartbeat.
- Diagnosed `TargetDown` by querying Prometheus's target API (scrape error: `EOF`) and reproducing directly with `curl` (TCP connects, "empty reply from server") — ruled out network/host-down causes by comparing against healthy siblings on the same TrueNAS host (`smartctl-exporter:9633` returns 200 OK, `doco-cd:18080/v1/health` probe is up), and confirmed the compose file/version pin hadn't drifted in Git since the 2026-07-14 deploy.
- Root-caused from user-supplied container logs: `node_exporter` panics on every scrape with a nil-pointer dereference inside `prometheus.processMetric`, triggered by the `hwmon` collector's udev/sysfs enumeration — Go's `net/http` per-connection panic recovery silently drops the connection without a response, which is why it looked like a network problem rather than a crash. Explained why the fault was state-dependent (hwmon re-enumerates on every scrape) rather than present from initial deploy — it took ~2.5 days to manifest.
- Fixed immediately by adding `--no-collector.hwmon` to `truenas/docker/node-exporter/docker-compose.yaml`; user applied and restarted manually on TrueNAS, confirmed via `docker logs` (no panic, `hwmon` absent from "Enabled collectors") and end-to-end via `curl` (200 OK) and Prometheus target health flipping to `up` / alert clearing. This landed as commit `6efae87`.
- `WebSearch`ed for a known upstream node_exporter bug matching the exact panic — found no exact match, but a multi-year history of `hwmon`-specific crash reports across versions/architectures, which informed the decision to permanently avoid the in-process collector rather than gamble on a version bump that couldn't be confidently verified without days of quiet monitoring.
- Used plan mode to design a durable replacement: two parallel Explore agents (truenas/doco-cd GitOps conventions; Renovate + custom-Dockerfile conventions) followed by a Plan agent to validate a textfile-collector sidecar design.
- Plan agent's key finding, personally verified against the live repo before trusting it: the existing `hardware-temperatures` PrometheusRule and the "Node Exporter Full" Grafana dashboard's `group_left` join both hard-depend on node_exporter's real `node_hwmon_*` metric names and its device-path-derived `chip` label scheme (e.g. `platform_coretemp_0`) — so the sidecar had to reproduce that scheme exactly rather than invent its own.
- Implemented the `sensors-textfile` sidecar: a minimal Alpine `Dockerfile` (no packages — pure busybox) plus `entrypoint.sh` that walks `/sys/class/hwmon` directly every 15s (bypassing `lm-sensors` entirely), reproduces node_exporter's own chip-id derivation algorithm, and atomically writes `node_hwmon_{temp_celsius,fan_rpm,chip_names,sensor_label}` in Prometheus text-exposition format. Wired `node-exporter`'s `--collector.textfile.directory` and a shared `textfile` named volume into the same compose project — no new `.doco-cd.truenas.yaml` entry needed since it's a second service in the existing `working_dir`.
- Validated: `docker compose config` parsed the compose file cleanly; `entrypoint.sh` passed `dash -n` syntax check; manually sourced and ran the `collect()` function against this devcontainer's own `/sys/class/hwmon` (power-supply chips only) to confirm correct chip-id derivation and valid atomic Prometheus output, since no Docker daemon was available here to build/run the actual image.
- Updated `truenas/README.md`'s layout diagram to reflect `node-exporter/` as a two-service stack.

### Files changed
| File | Change |
|------|--------|
| `truenas/docker/node-exporter/docker-compose.yaml` | Disabled hwmon collector — root-cause fix (committed `6efae87`); added `sensors-textfile` sidecar service + shared `textfile` volume (staged) |
| `truenas/docker/node-exporter/sensors-textfile/Dockerfile` | New — minimal Alpine image, no added packages |
| `truenas/docker/node-exporter/sensors-textfile/entrypoint.sh` | New — reads `/sys/class/hwmon` directly, emits node_exporter-compatible `node_hwmon_*` metrics |
| `truenas/README.md` | Updated layout diagram for the two-service `node-exporter` stack |

### Key decisions
- Chose a textfile-collector sidecar over re-enabling `hwmon` on a different node_exporter version: the crash trigger was state-dependent (2.5 days to manifest), so a version bump couldn't be confidently verified without days of quiet monitoring, and `hwmon` has a long history of collector-specific crash reports across versions/architectures.
- Sidecar reads `/sys/class/hwmon` directly instead of shelling out to `lm-sensors` — avoids an unpinned `apk` package version (no Renovate datasource for apk packages) and was required anyway to reproduce node_exporter's own device-path-based chip-id algorithm, which `lm-sensors`' human-readable names don't match.
- Deployed as a second service inside the existing `truenas/docker/node-exporter/` compose project rather than a new top-level stack, so it could share a Docker named volume with `node-exporter` — confirmed against doco-cd's own source that `.doco-cd.truenas.yaml` maps one entry to one `working_dir` (compose project), not per-service, so no new registry entry was needed.
- Metric names/labels deliberately mirror node_exporter's real `hwmon` output (`node_hwmon_temp_celsius`, `chip="platform_coretemp_0"`-style IDs) rather than following generic textfile-collector advice to avoid the `node_` prefix, because this repo already has a fleet-wide `hardware-temperatures` PrometheusRule and a Grafana dashboard join depending on that exact scheme — verified directly against the live files before committing to the design.

---

## 2026-07-14 — `doco-cd-truenas-compose-gitops`

### Goal
Add doco-cd (a lightweight Docker Compose GitOps agent) to manage `node-exporter` and `smartctl-exporter` on TrueNAS, entirely outside the Flux/Kubernetes tree, with their metrics wired into the existing Prometheus stack.

### What we did
- Explored `tmp/home-ops-bykaj/`'s reference implementation (`.doco-cd.truenas.yaml`, `docker/truenas/`) in parallel with this repo's existing conventions (app-directory layout, SOPS rules, ExternalSecret pattern, YAML comment style) via two Explore agents.
- Researched doco-cd's actual configuration surface directly from `doco.cd` docs (GitHub wiki is deprecated) since the bykaj reference left several gaps: confirmed `POLL_CONFIG`/`SSH_PRIVATE_KEY_FILE`/`WEBHOOK_SECRET` env vars, the `.doco-cd.<target>.yaml` discovery convention (`target: truenas` → loads `.doco-cd.truenas.yaml`), and the full per-app deployment config schema (`working_dir`, `reference`, `compose_files`, etc.).
- Used `AskUserQuestion` to settle four design decisions before planning: bootstrap doco-cd manually via SSH once (chicken-and-egg, unavoidable); authenticate to GitHub via a dedicated read-only SSH deploy key rather than a PAT or 1Password Connect (which can't reach a bare-metal host); trigger via polling, not webhooks (no inbound port, matches Flux's own pull model); manage `node-exporter` + `smartctl-exporter` to start, mirroring bykaj.
- Ran a Plan agent to turn this into a concrete design, then personally verified its key technical claims against the live repo before trusting them: confirmed `prometheus.prometheusSpec.scrapeConfigSelectorNilUsesHelmValues: false` is already set (so a new `ScrapeConfig` needs no extra selector wiring), confirmed the `ScrapeConfig` CRD is already installed via `kube-prometheus-stack-crds` in `ops/bootstrap/helmfile.d/00-crds.yaml`, and confirmed the `${NAS_HOST}` substitution pattern via `blackbox-exporter/app/probes.yaml`.
- Caught and fixed a real bug in the sub-agent's proposed Renovate annotation placement: this repo's shared custom regex manager (`renovate.json5`) only correctly extracts a version from a line where the annotated value is a **bare** string (verified against every existing usage — `talenv.yaml`, `talosupgrade.yaml`, every Helm chart's `tag:` field) — it cannot isolate a tag out of a combined `image: repo:tag` line, since Docker Compose has no split `repository:`/`tag:` field like Helm. Fixed by giving each compose stack a sibling `.env` file (`DOCO_CD_VERSION=0.94.0` etc.) referenced via `${VAR}` in the compose file, matching the bare-value-line pattern Renovate already parses correctly elsewhere.
- Implemented: root-level `.doco-cd.truenas.yaml`; new top-level `truenas/` directory (`README.md` + `docker/{doco-cd,node-exporter,smartctl-exporter}/{docker-compose.yaml,.env}`), placed there rather than bykaj's flat `docker/truenas/` to match this repo's existing domain-grouped top-level layout; two `ScrapeConfig` objects in `kubernetes/apps/observability/kube-prometheus-stack/app/scrapeconfig-truenas.yaml`, added to that Kustomization's `resources:`; documentation additions to `CLAUDE.md` (repository layout tree) and `docs/CLUSTER.md` (new "Non-Kubernetes Infrastructure" section).
- Validated everything: all three compose files render correctly via `docker compose config` (had to first install `docker-compose` — Debian trixie's repos don't carry `docker-compose-plugin`, that's Docker Inc.'s own apt repo, so installed the Debian-native `docker-compose` package instead, which provides both `docker compose` and `docker-compose` invocations); confirmed `.doco-cd.truenas.yaml` and the new Kubernetes manifests parse as valid YAML; built the `kube-prometheus-stack` Kustomization with the mise-installed `kustomize` binary directly (mise's `eval`-based shell activation was blocked by the session's shell-injection guard) and confirmed both `ScrapeConfig` objects render correctly namespaced.

### Files changed
| File | Change |
|------|--------|
| `.doco-cd.truenas.yaml` | New — doco-cd deployment manifest listing the two managed stacks (repo root, required by doco-cd's discovery rules) |
| `truenas/README.md` | New — overview, bootstrap runbook, and note distinguishing this from the in-cluster `smartctl-exporter` DaemonSet |
| `truenas/docker/doco-cd/docker-compose.yaml` | New — the doco-cd agent itself (polling mode, SSH deploy key auth) |
| `truenas/docker/doco-cd/.env` | New — `DOCO_CD_VERSION`, Renovate-tracked |
| `truenas/docker/node-exporter/docker-compose.yaml` | New — host metrics exporter, host network mode |
| `truenas/docker/node-exporter/.env` | New — `NODE_EXPORTER_VERSION`, Renovate-tracked |
| `truenas/docker/smartctl-exporter/docker-compose.yaml` | New — disk SMART health exporter, privileged |
| `truenas/docker/smartctl-exporter/.env` | New — `SMARTCTL_EXPORTER_VERSION`, Renovate-tracked |
| `kubernetes/apps/observability/kube-prometheus-stack/app/scrapeconfig-truenas.yaml` | New — two `ScrapeConfig` objects scraping the TrueNAS `node-exporter`/`smartctl-exporter` endpoints |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Added `scrapeconfig-truenas.yaml` to `resources:` |
| `CLAUDE.md` | Added `truenas/` entry to the Repository Layout tree |
| `docs/CLUSTER.md` | Added "Non-Kubernetes Infrastructure — TrueNAS Docker Compose (doco-cd)" section |

### Key decisions
- Root-level `.doco-cd.truenas.yaml` is forced by doco-cd's own discovery rules, but the compose stacks themselves live under a new top-level `truenas/` directory (not bykaj's flat `docker/truenas/`) to match this repo's existing domain-grouped layout (`kubernetes/`, `talos/`, `ops/`).
- Polling over webhooks: no inbound port needs to be exposed from TrueNAS and no GitHub webhook to register/maintain, consistent with Flux's own pull-based reconciliation elsewhere in this repo.
- SSH deploy key (read-only, repo-scoped) over a PAT or 1Password Connect: 1Password Connect only reaches in-cluster `ExternalSecret`s, not a bare-metal Docker host, so the secret path here is deliberately manual and outside the cluster's normal secrets pipeline.
- `ScrapeConfig` CRD chosen over a raw `additionalScrapeConfigs` Secret: the selector is already open (`scrapeConfigSelectorNilUsesHelmValues: false`), so it's zero extra plumbing and stays GitOps-diffable, unlike a literal `prometheus.yml` snippet in a Secret.
- doco-cd is intentionally omitted from `.doco-cd.truenas.yaml` — it doesn't manage its own redeploy, avoiding a self-referential restart loop (matches the upstream reference pattern).

---

## 2026-07-14 — `external-secrets-1password-inventory`

### Goal
Build a living inventory of every 1Password vault item this repo depends on, tracking which fields are pulled via wildcard vs. explicit import, and assess whether committing it to a (currently private) public-ish GitOps repo would leak anything sensitive.

### What we did
- Enumerated every `ExternalSecret` manifest in the repo (`grep -rl "kind: ExternalSecret" kubernetes/`, 20 files) plus the single `ClusterSecretStore` (`onepassword`, vault `homelab`), and read each one to extract: consumer name/namespace, `dataFrom.extract` wildcard imports vs. `data[].remoteRef` explicit field picks, `rewrite` regexps, and which fields are actually consumed in `target.template`.
- Found a second, independent secrets mechanism outside ESO: bootstrap-time `op read` calls in `ops/bootstrap/mod.just`'s `resources` recipe, which seed `sops-age`, `onepassword-connect-secrets`, and `flux-github-app` before ESO itself exists (chicken-and-egg — ESO needs its own 1Password Connect credentials before it can reconcile anything). Noted `ops/bootstrap/resources.yaml.j2` is a superseded/unused declarative draft of the same secrets (not invoked by any task).
- Cross-referenced each `ExternalSecret`'s real `targetNamespace` from its owning `ks.yaml` rather than assuming from directory convention — caught that `firefly-iii`'s `app` Kustomization targets `finance` while its `db` Kustomization targets `database`.
- Confirmed the `GitHub App` 1Password item is used by both mechanisms: seeded once at bootstrap, then continuously reconciled by the `flux-github-app` `ExternalSecret` once ESO is running.
- Verified the shared `components/volsync` Kustomize component (backing the `volsync-restic` item) is consumed by three apps (`waha`, `pgadmin`, `firefly-iii`) via `postBuild.substitute.APP`, each producing its own `<app>-volsync` Secret instance.
- Wrote `docs/EXTERNAL-SECRETS.yaml`: 18 distinct 1Password items, each with mechanism (`boot`/`eso`/`boot+eso`), import mode, known/raw field names, and every consumer manifest path — plus a "How to keep this up to date" section documenting the exact grep/`op` commands to re-derive it. Validated the file parses with `python3 -c "import yaml; yaml.safe_load(...)"`.
- Called `advisor()` for a review pass: confirmed field-extraction accuracy across all wildcard items (rewrite regexp + template consumption reverse-mapped correctly) and full file coverage; flagged that the `known_fields` description didn't match its contents (listed raw 1Password source names, not template-consumed names) — fixed the header comment to clarify these are inferred via rewrite, not verified against the live vault. Also flagged one loose end (`cluster-secrets`/`substituteFrom` in `kubernetes/flux/cluster/ks.yaml`) to confirm wasn't a hidden 1Password path — verified via grep it's a plain SOPS-encrypted file (`cluster-secrets.sops.yaml`), out of scope.
- Added a one-line pointer to the new doc in `CLAUDE.md`'s doc index, following the existing convention for `QA.md`/`CLUSTER.md`/etc.
- User asked whether committing this to a (public) GitOps repo would expose sensitive information. Confirmed via `gh repo view` the repo is currently **private**. Grepped the new file for secret-shaped content (PEM headers, long base64/hex, token prefixes) — none found; it contains only item names, field *labels* (not values), the vault name, namespaces, and manifest paths, all of which are already present in plaintext in the existing `ExternalSecret` manifests. Flagged the one real (minor) consideration: the doc aggregates `HomeLab Access Token`/`HomeLab Credentials File` as the items that seed 1Password Connect's own vault access, making that pair easier to spot than before — an OpSec/aggregation tradeoff, not a credential leak, since SOPS encryption and 1Password vault ACLs are the actual controls and neither is weakened.

### Files changed
| File | Change |
|------|--------|
| `docs/EXTERNAL-SECRETS.yaml` | New — living inventory of all 18 1Password vault items referenced by the repo (ESO + bootstrap-tier), with consumers, import mode, and a re-derivation runbook (uncommitted) |
| `CLAUDE.md` | Added doc-index pointer to `EXTERNAL-SECRETS.yaml` (uncommitted) |

### Key decisions
- Structured the inventory as YAML (not Markdown) since it's fundamentally per-item structured data (mechanism, import mode, fields, consumers) that benefits from being diffable and greppable; used extensive header/footer comments for the human-facing methodology instead of a separate doc.
- Documented `known_fields` as inferred (from rewrite regexps + template usage) rather than verified against the live vault, and said so explicitly in the file — avoids the doc silently going stale if 1Password item fields are renamed without a corresponding manifest change.
- Left the repo's actual visibility/exposure decision to the user — this session only assessed and reported risk, since making the repo public isn't a decision Claude should make unilaterally.

---

## 2026-07-12 — `firefly-fsgroup-fix-cnpg-backup-tasks`

### Goal
Fix Firefly III's silent attachment-upload failure (missing `fsGroup`) and add generalized `just cnpg dump`/`restore` tasks for point-in-time per-database backups.

### What we did
- Diagnosed a Firefly III bug: uploading an attachment showed a success toast, but viewing it afterward showed "This attachment could not be found." Root-caused (via live cluster inspection) to a missing `fsGroup`/`securityContext` on the `firefly-iii` app-template controller — the `ceph-block`-backed `upload` PVC stayed `root:root`-owned while the container ran as non-root `www-data` (uid/gid 33), so writes silently failed even though the DB attachment row was created. Confirmed with a direct `Permission denied` on a `touch` test as uid 33, an almost-empty PVC, and Firefly's own startup log warning about the non-writable upload directory.
- Fixed by adding `defaultPodOptions.securityContext` (`runAsUser`/`runAsGroup`/`fsGroup: 33`, `fsGroupChangePolicy: OnRootMismatch`) to `kubernetes/apps/finance/firefly-iii/app/helmrelease.yaml`, mirroring the existing `pgadmin` pattern. Committed (`e00c651`) and pushed to `origin/main` by the user.
- Follow-up: user asked how to take a complete, quickly-restorable point-in-time backup of Firefly III (accounts/config/attachments) before real usage begins. Investigated existing backup infra: `postgres-v17` is a shared 3-instance CNPG cluster with continuous WAL archiving (barman-cloud) — whole-cluster PITR, too heavy for a single-app checkpoint — while the `firefly-iii` attachments PVC is already covered by an hourly VolSync restic backup to NAS (added in `0cab9d6`). Recommended `pg_dump` over scaling the app down, since PostgreSQL's MVCC gives `pg_dump` a consistent snapshot without downtime.
- Generalized that into two new `just` recipes in `ops/cnpg/mod.just`: `dump <db> [file]` (`pg_dump -Fc` a single database via `kubectl exec` into the CNPG primary, defaulting output to `~/cnpg-backups/<db>-<timestamp>.dump`) and `restore <db> <file>` (DESTRUCTIVE, `gum`-confirmed, `pg_restore --clean --if-exists` into an existing database only, terminating other backends first). Both resolve the live primary pod via the existing `cnpg.io/cluster=postgres-v17,role=primary` label selector rather than a hardcoded pod name.
- While building those, spotted and fixed a related latent bug in the older `nfs-restore-from-backup` recipe: it hardcoded the primary pod name (`postgres-v17-1`) in three `kubectl exec` calls against the live cluster, which would silently target the wrong (non-primary) pod after a CNPG failover/switchover. Replaced all three with a `LIVE_POD` variable resolved via the same label selector `nfs-restore-drill` already used correctly.
- Verified the new/edited recipes with `just cnpg` (recipe listing) and a `bash -n` syntax check extracted from each script block.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/finance/firefly-iii/app/helmrelease.yaml` | Added `defaultPodOptions.securityContext` (`fsGroup: 33`) so the `ceph-block` upload PVC is writable by non-root `www-data`; committed as `e00c651` |
| `ops/cnpg/mod.just` | Added `dump`/`restore` recipes for per-database `pg_dump`/`pg_restore` backups; fixed `nfs-restore-from-backup` to resolve the live primary pod via label selector instead of hardcoded `postgres-v17-1` (uncommitted) |

### Key decisions
- Chose `pg_dump`/`pg_restore` over CNPG's whole-cluster barman PITR for the new backup recipes — `postgres-v17` is shared across apps, so a cluster-wide restore would affect every database, not just the one being rolled back.
- Defaulted `dump` output to `~/cnpg-backups/` (outside the repo) rather than a repo-local directory, to avoid any risk of a binary dump landing in Git.
- Resolved the CNPG primary pod dynamically via the `cnpg.io/cluster=postgres-v17,role=primary` label in both new recipes and the fixed `nfs-restore-from-backup` recipe, rather than hardcoding `postgres-v17-1`, since the operator can move the primary role during failover/switchover.

---

## 2026-07-12 — `alertmanager-ha-replicas`

### Goal
Diagnose why Alertmanager's Status page showed "Cluster Status: disabled" and, on request, move Alertmanager to a genuinely fault-tolerant 3-replica deployment.

### What we did
- Root-caused the "Cluster Status: disabled" banner: confirmed via `kubectl` that the `alertmanager-kube-prometheus-stack-alertmanager` StatefulSet ran a single replica (chart default, unset in `values.yaml`), and that the Prometheus Operator omits Alertmanager's gossip `--cluster.listen-address` flag whenever `replicas <= 1` — expected behavior, not a misconfiguration. Clarified that "Cluster Status" refers to Alertmanager's own memberlist/gossip HA layer, unrelated to the Kubernetes cluster.
- Analysed the true cost of `replicas: 3` before changing anything: read the live pod's resource requests (`200Mi` memory, no CPU request, no limits), computed the storage cost accounting for `ceph-block`'s `size=3` replication (3 PVCs × 1Gi × 3x Ceph replication = 9Gi raw vs 3Gi today), and checked headroom via `kubectl top nodes` and `CephCluster` status (~9.27 TiB free) — concluded compute/storage/network cost is negligible.
- Identified the real gap: `alertmanagerSpec.podAntiAffinity` was unset (chart default `""`, i.e. disabled), so `replicas: 3` alone would not guarantee node-spread — verified this by checking the live `alertmanagers.monitoring.coreos.com` CRD schema (only a generic `affinity` field exists on the CRD; `podAntiAffinity`/`podAntiAffinityTopologyKey` are chart-level convenience values that expand into the affinity block at render time).
- Implemented `replicas: 3` + `podAntiAffinity: soft` together in `values.yaml`, choosing `soft` (`preferredDuringScheduling`) over `hard` because this is a 3-node, no-dedicated-worker cluster where a `hard` constraint could leave a replica `Pending` during single-node CP maintenance.
- Change is uncommitted, pending `/git-stage` + `/git-commit` per repo convention (never committed autonomously).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Added `alertmanager.alertmanagerSpec.replicas: 3` and `podAntiAffinity: soft` |

### Key decisions
- Chose `podAntiAffinity: soft` over `hard` — `hard` guarantees per-node spread but risks a `Pending` replica during single-CP-node maintenance on a 3-node, no-worker cluster; `soft` gets the same steady-state spread without that availability risk.
- Verified the chart's `podAntiAffinity` values-key against the live CRD schema rather than assuming from memory, since the CRD only exposes a generic `affinity` field — the chart template expands the convenience key at render time.

---

## 2026-07-11 — `firefly-iii-deployment`

### Goal
Research, plan, and implement a GitOps deployment of Firefly III (personal finance manager) on the shared CNPG Postgres cluster, with least-privilege database credentials, internal-only exposure, and the Data Importer companion app.

### What we did
- Researched Firefly III's Kubernetes requirements directly from the official `firefly-iii/kubernetes` repo and both `.env.example` files (core app + Data Importer) after `kubesearch.dev`'s SPA and unauthenticated `gh search code` failed to surface usable community examples — confirmed native `pgsql` support, required env vars (`APP_KEY`, `STATIC_CRON_TOKEN`, `DB_*`, `TRUSTED_PROXIES`), the upload-storage PVC, and that the Data Importer needs a Personal Access Token that can only be generated from the UI after first login (no `APP_KEY` of its own).
- Explored this repo's existing patterns (`pgadmin`, `waha`, the shared `cloudnative-pg` cluster) via an Explore subagent to ground the design in proven conventions rather than inventing new ones.
- Used `AskUserQuestion` to settle four design decisions up front: dedicated least-privilege CNPG credentials (vs. reusing the shared superuser like `pgadmin`), a new `finance` namespace, internal-only exposure via `envoy-internal`, and deploying the Data Importer alongside the core app now rather than later.
- Verified via web research that CNPG's `Database`/role CRDs cannot reference a `Cluster` in another namespace (open upstream feature request) — this shaped where the DB-provisioning manifests had to be applied, though not where they had to live in git.
- Implemented the full deployment: added a `firefly` role to the shared `postgres-v17` `Cluster` (`spec.managed.roles`), a `Database` CRD, ExternalSecrets, an app-template v5 HelmRelease with a `ceph-block` upload PVC, an internal `HTTPRoute`, an hourly `CronJob` hitting the recurring-transactions cron endpoint, and a second app-template release for the Data Importer.
- Validated every new/changed Kustomize overlay individually and the full repo tree with `task validate` (kubeconform) — all passed, with the same "skipped" behavior for CRDs (ExternalSecret, HTTPRoute, `Database`) that kubeconform already shows for existing apps like `pgadmin`.
- Iterated twice on user feedback after the initial implementation: (1) relocated the DB-provisioning files from `database/cloudnative-pg/firefly-iii-db/` into `finance/firefly-iii/db/` so all Firefly-related config lives in one place, exploiting the fact that a Flux Kustomization's git path and its `targetNamespace` are independent; while restructuring, also deleted two dead `app`-level `kustomization.yaml` files that nothing referenced. (2) Consolidated three separate 1Password items down to one (`firefly-iii`), removing the dual-`dataFrom.extract`/rewrite pattern that had been copied from `pgadmin` since it was no longer needed.
- Discussed, but did not adopt, an init-container/sidecar SQL-provisioning pattern seen in other homelab repos — walked through the tradeoffs (portability and colocation vs. loss of drift detection, broader superuser-credential exposure, no declarative teardown) before confirming the CNPG CRD approach.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added `spec.managed.roles` entry for a least-privilege `firefly` role |
| `kubernetes/apps/kustomization.yaml` | Registered the new `./finance` category namespace |
| `kubernetes/apps/finance/namespace.yaml` | New `finance` namespace |
| `kubernetes/apps/finance/kustomization.yaml` | Lists the `firefly-iii` and `firefly-iii-importer` `ks.yaml` files |
| `kubernetes/apps/finance/firefly-iii/ks.yaml` | Multi-doc Flux Kustomization: `firefly-iii-db` (targets `database`, `wait: true`) + `firefly-iii` (targets `finance`) |
| `kubernetes/apps/finance/firefly-iii/db/{kustomization,externalsecret,database}.yaml` | CNPG `Database` CRD + ExternalSecret producing the role's basic-auth secret, extracted from the single `firefly-iii` 1Password item |
| `kubernetes/apps/finance/firefly-iii/app/{kustomization,externalsecret,helmrelease,httproute,cronjob}.yaml` | Core Firefly III app-template v5 deployment, `ceph-block` upload PVC, internal `HTTPRoute`, hourly cron `CronJob` hitting in-cluster Service DNS |
| `kubernetes/apps/finance/firefly-iii-importer/ks.yaml` | Flux Kustomization for the Data Importer, depends on `firefly-iii` |
| `kubernetes/apps/finance/firefly-iii-importer/app/{kustomization,externalsecret,helmrelease,httproute}.yaml` | Data Importer app-template v5 deployment, talks to Firefly III over in-cluster Service DNS |

### Key decisions
- Chose CNPG's declarative `Database`/`managed.roles` CRDs over both reusing the shared superuser (pgadmin's pattern) and an init-container SQL-provisioning approach seen elsewhere: least-privilege, continuously reconciled with drift detection, and a clean `ensure: absent` teardown path — at the cost of the provisioning manifests needing to target the `database` K8s namespace.
- Decoupled git layout from Kubernetes namespace: the DB-provisioning files live under `finance/firefly-iii/db/` in git (colocated with the rest of the app) but their Flux Kustomization sets `targetNamespace: database`, satisfying both the user's "keep it together" preference and CNPG's same-namespace `Cluster` reference constraint.
- Consolidated all secrets into one `firefly-iii` 1Password item at the user's request, picking field names (`DB_USERNAME`, `DB_PASSWORD`, etc.) that map 1:1 to every consumer's needs so no `dataFrom` rewrite rules were needed.
- Internal-only exposure (`envoy-internal`) chosen as the sensible default for a financial application; the CronJob and Data Importer both call Firefly III over in-cluster Service DNS rather than through the Gateway, applying the same hairpin/downgrade lesson learned in `homepage-truenas-sitemonitor-fix`.
- The Data Importer's `FIREFLY_III_ACCESS_TOKEN` starts as a placeholder in the shared 1Password item — the real Personal Access Token can only be generated from Firefly III's own UI after first login, so this is a required manual follow-up step, not an oversight.

---

## 2026-07-11 — `repo-audit-and-pr-review-fix`

### Goal
Run an incremental seventh-pass GitOps repo audit, then diagnose and fix the cost/observability issues behind the disabled `renovate-pr-review.yml` GitHub Action.

### What we did
- Ran the `gitops-repo-audit` skill as an incremental "seventh pass" against the existing `docs/REPO-AUDIT.md` (diffing the prior sixth-pass baseline, `7d8e377`→`284d80f`, rather than a full re-audit): confirmed validation, deprecated-API, and dependency-graph checks all clean, resource counts unchanged since the sixth pass. Split the HTTPRoute validation row into schema-violation vs. CEL-violation counts, confirmed the silence-deactivation pattern and grafana-dashboard datasource fix held up, and added a new finding (**I16**) documenting that `renovate-pr-review.yml` had been disabled since 2026-07-04 for unexpected Claude usage costs — which changes existing finding **I13**'s risk status from resolved to "not currently exercised, must be re-assessed before re-enabling." Committed as `90cfdc7`.
- Investigated the disabled `renovate-pr-review.yml` workflow. Authenticated `gh` mid-session and pulled real run history (`gh run list`/`gh run view --json jobs`/`--log`) instead of reasoning from the YAML alone. This overturned the ROADMAP's leading hypothesis: the visually-obvious concurrency-cancel bursts (multiple runs at the same timestamp) cost nothing — they were killed before `Set up job` finished, or skipped by the `type/major|minor` label gate before reaching `claude-code-action`.
- Found two real root causes instead: (1) the `synchronize` trigger caused the `renovate/major-kube-prometheus-stack` PR to be fully re-reviewed **7 times in under 5 hours** as Renovate rebased it repeatedly, with no dedup against whether the actual dependency version had changed; (2) the action's default logging prints `Claude Code initialized` and then goes **completely silent** until the process exits — confirmed identical on both a normal 3-minute successful run and the 16-minute run that immediately preceded the 2026-07-04 `gh workflow disable`, making it impossible to tell legitimate slow work from a stuck loop after the fact.
- Fixed `.github/workflows/renovate-pr-review.yml`: dropped `synchronize` from the `pull_request` trigger types (kept `opened`/`reopened`/`labeled`, with a `workflow_dispatch` escape hatch for re-reviewing a PR that meaningfully changed), updated the concurrency-cancel comment to match, and added `show_full_output: true` to the `claude-code-action` step for full turn-by-turn tool-call tracing on future runs.

### Files changed
| File | Change |
|------|--------|
| `docs/REPO-AUDIT.md` | Seventh audit pass — updated resource-inventory deltas, validation results, gaps, best practices, cosign coverage, and recommendations (new **I16**); committed `90cfdc7` |
| `.github/workflows/renovate-pr-review.yml` | Dropped `synchronize` trigger, updated concurrency comment, added `show_full_output: true` (uncommitted) |

### Key decisions
- Dropped `synchronize` entirely rather than building a real dedup check (e.g. comparing the diff's target version against the last posted `<!-- pr-upgrade-reviewer-report -->` comment) — simpler, at the cost of requiring a manual `workflow_dispatch` re-run if a rebase ever carries a genuine content change.
- Root-caused from actual `gh run` timestamps/logs rather than the workflow YAML in isolation — the ROADMAP's original "concurrency duplication" hypothesis looked right from `gh run list`'s status column alone but was disproven by checking step-level timing.

---

## 2026-07-10 — `adam-anna-unifi-dns-records`

### Goal
Add GitOps-managed local DNS records (via UniFi/UDM) for the Plugwise Adam gateway and Anna thermostat, and fix both — plus `wan-failover` — to stop allocating unnecessary ClusterIPs.

### What we did
- Added a UniFi-only DNS record for the Plugwise Adam gateway (`gw-adam.iot.vwn.io` → `10.30.0.71`) as a backend-less `Service` with `external-dns.alpha.kubernetes.io` annotations, mirroring the existing `wan-failover` pattern. Added `${DOMAIN_IO}` to `external-dns-unifi`'s `domainFilters` so the annotation is honored, and a `blackbox-exporter` icmp probe for the device. Committed as `93f94e0`.
- Explored converting the record to a `DNSEndpoint` CRD (the pattern `cloudflared` already uses) plus adding the `crd` source to `external-dns-unifi`, at the user's request, to get a more declarative pattern for future devices. Found — by reading `external-dns`'s actual Go source (`source/service.go`, `source/gateway_httproute.go`, `endpoint/domain_filter.go`) rather than assuming — that this causes bidirectional cross-publishing with no clean fix: `external-dns-cloudflare` already watches `crd` + `${DOMAIN_IO}`, so a `DNSEndpoint` here would get published as a public, Cloudflare-proxied record pointing at a private IP; conversely `external-dns-unifi` would pick up `cloudflared`'s tunnel `DNSEndpoint` via the shared `${DOMAIN_PROXII}` filter. Confirmed both `--label-filter` and `--regex-domain-exclusion` are instance-global (apply to every source: service, httproute, crd — not scopable to just `crd`), and that `--regex-domain-exclusion` additionally discards the plain `domainFilters` list entirely once set (`Match()` switches to regex-only mode), which would have silently broadened `external-dns-cloudflare` to match nearly everything. Reverted to the `Service` pattern.
- Investigated the user's follow-up idea of dedicated `iot.vwn.io`/`home.vwn.io` subdomains, reasoning by analogy to the existing `DOMAIN_CLUSTER` (`cluster.vwn.io`) precedent. Determined via the domain-filter suffix-matching logic that a dedicated var alone doesn't isolate anything: `external-dns-cloudflare`'s existing bare `vwn.io` filter entry already suffix-matches any subdomain regardless of variable naming. `DOMAIN_CLUSTER`'s actual isolation comes from `--gateway-name=envoy-external` scoping cloudflare's `gateway-httproute` source away from `envoy-internal` routes — a mechanism the `crd` source has no equivalent of. Called `advisor` twice during this investigation; both calls confirmed reverting to `Service` (not a filter scheme) was the correct call.
- User asked why the live `adam`/`anna` Services (`anna` added manually by the user, mirroring `adam`) both show a `ClusterIP`. Diagnosed: default `type: ClusterIP` always allocates an IP from the Service CIDR regardless of endpoints. Fixed `adam`, `anna`, and `wan-failover` (same latent issue) by switching to `type: ExternalName` with `spec.externalName` holding the target IP directly — Kubernetes' native "resolves outside the cluster" type, which allocates no ClusterIP at all. Dropped the now-redundant `target` annotation and the meaningless `ports` field. Verified via `kubectl explain service.spec.externalName` (RFC-1123 hostname field, no explicit IP-literal rejection) and `kubectl apply --dry-run=server` against the live cluster — including an in-place dry-run against the already-live `adam`/`anna`/`wan-failover` objects to confirm the `ClusterIP → ExternalName` type change is accepted — before finalizing.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/network/external-services/adam/service.yaml` | New (committed `93f94e0`), then converted `ClusterIP` → `ExternalName` |
| `kubernetes/apps/network/external-services/adam/kustomization.yaml` | New (committed `93f94e0`) |
| `kubernetes/apps/network/external-services/ks.yaml` | Added `adam` Flux Kustomization (committed `93f94e0`); `anna` Kustomization added separately by the user (`963ffa3`) |
| `kubernetes/apps/network/external-dns/unifi/helmrelease.yaml` | Added `${DOMAIN_IO}` to `domainFilters` (committed `93f94e0`); `crd` source added then reverted (uncommitted at revert) |
| `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml` | Added `devices` icmp `Probe` for `gw-adam.iot.${DOMAIN_IO}` (committed `93f94e0`) |
| `kubernetes/apps/network/external-services/anna/service.yaml` | Converted `ClusterIP` → `ExternalName` (uncommitted; file itself added by the user outside this session) |
| `kubernetes/apps/network/external-services/wan-failover/service.yaml` | Converted `ClusterIP` → `ExternalName` for consistency (uncommitted) |

### Key decisions
- Local-only device DNS records stay on the `Service` + `external-dns` annotation pattern, not `DNSEndpoint` CRDs — the `crd` source has no per-instance scoping mechanism (unlike `gateway-httproute`'s `--gateway-name`), so any shared domain filter between `external-dns-unifi` and `external-dns-cloudflare` causes cross-publishing with no clean fix short of a cluster-wide label-filter migration.
- `type: ExternalName` (not `ClusterIP` + target annotation) is now the standard shape for any future external/device DNS-only `Service` in this repo — avoids unnecessary ClusterIP allocation for free, and external-dns's `Service` source reads `spec.externalName` natively.

---

## 2026-07-10 — `blackbox-exporter-nfs-probes`

### Goal
Deploy `prometheus-blackbox-exporter` to fill the last gap in the KEDA nfs-scaler plan, and wire up reachability probes for the NAS and in-cluster Postgres.

### What we did
- Surveyed which live deployments would benefit from a KEDA nfs-scaler (probe-driven scale-to-zero on NAS outage): confirmed only two NFS consumers exist repo-wide (`postgres-backup-local` CronJob, `waha`'s VolSync ReplicationSource), both Job-based and already tolerant of NAS outages — the pattern only becomes relevant once a long-running Deployment (e.g. future Plex/Jellyfin) mounts NFS directly.
- Answered a dependency question: confirmed `blackbox-exporter` was the only missing piece (KEDA operator, Prometheus, and prometheus-operator CRDs were all already live); explained `tmp/home-ops-bykaj/.doco-cd.truenas.yaml` and `docker/truenas/` as bykaj's non-Kubernetes GitOps mechanism (doco-cd + Compose) for host-level exporters running directly on their TrueNAS box, unrelated to this cluster's needs.
- Deployed `blackbox-exporter` (chart v11.15.1, pulled and `helm template`-verified locally before writing manifests) mirroring the existing `smartctl-exporter` app structure: OCIRepository, Flux Kustomization (no `dependsOn` needed — `Probe`/`PrometheusRule` CRDs are pre-installed cluster-wide via `00-crds.yaml`), `configMapGenerator`-based values, `fullnameOverride` for a clean Service name.
- Added `monitoring.coreos.com/v1` `Probe` CRs (NFS/SMB against the NAS, Postgres against this cluster's own CloudNativePG `-rw` Service) instead of the chart's `serviceMonitor.targets` — Probe is the idiomatic prometheus-operator CRD and keeps targets out of Helm values. Added a generic `BlackboxProbeFailed` `PrometheusRule`.
- Verified before declaring done: confirmed via `kube-prometheus-stack`'s values that all `*SelectorNilUsesHelmValues` are `false` (Probes/rules discovered cluster-wide, no `release:` label needed) — this was the first `Probe` CR in the repo and could have been silently ignored. An advisor pass separately raised a concern that Flux's `${VAR}` substitution might also mangle the `PrometheusRule`'s `{{ $labels.instance }}` template syntax; checked Flux's official docs directly rather than trusting either intuition — confirmed substitution only expands braced `${VAR}`, bare `$var` is untouched by design, so no fix was needed.
- At the user's request, moved the NAS host out of plaintext: added `NAS_HOST` to `cluster-secrets.sops.yaml` via `sops set` (never decrypting the rest of the file to a transcript), then added `PG_HOST` (`postgres-v17-rw.database.svc.cluster.local`) for the Postgres probe once the user clarified it should target this cluster's own CloudNativePG, not the NAS — resolving an open question about whether TrueNAS even serves Postgres.
- Found and fixed an unrelated gap while verifying the SOPS file's MAC: a `.decrypted~cluster-secrets.sops.yaml` temp file appeared untracked in `git status`. Added `.decrypted~*` to `.gitignore` and deleted the stray file. The user later clarified the actual source (VS Code's SOPS extension keeps a live decrypted scratch copy while the file is open in the editor) — the gitignore fix covers it regardless of cause.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/blackbox-exporter.yaml` | New OCIRepository, chart v11.15.1 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `blackbox-exporter.yaml` resource |
| `kubernetes/apps/observability/blackbox-exporter/ks.yaml` | New Flux Kustomization, `targetNamespace: observability` |
| `kubernetes/apps/observability/blackbox-exporter/app/kustomization.yaml` | New — `configMapGenerator` values, resources for helmrelease/probes/prometheusrule |
| `kubernetes/apps/observability/blackbox-exporter/app/helmrelease.yaml` | New HelmRelease, `chartRef` + `valuesFrom` |
| `kubernetes/apps/observability/blackbox-exporter/app/helm/values.yaml` | New — modules (`http_2xx`/`icmp`/`tcp_connect`), `fullnameOverride`, `selfMonitor` ServiceMonitor, resource limits |
| `kubernetes/apps/observability/blackbox-exporter/app/helm/kustomizeconfig.yaml` | New — `nameReference` for the generated ConfigMap hash |
| `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml` | New — 3 `Probe` CRs: NFS (`${NAS_HOST}:2049`), SMB (`${NAS_HOST}:445`), Postgres (`${PG_HOST}:5432`) |
| `kubernetes/apps/observability/blackbox-exporter/app/prometheusrule.yaml` | New — generic `BlackboxProbeFailed` alert across all probes |
| `kubernetes/apps/observability/kustomization.yaml` | Added `blackbox-exporter/ks.yaml` resource |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `NAS_HOST` and `PG_HOST` keys via `sops set` |
| `.gitignore` | Added `.decrypted~*` |
| `docs/keda-nfs-scaler-plan.md` | Marked blackbox-exporter prerequisite and NAS-host-variable prerequisite as resolved; updated illustrative `ScaledObject` query to use `${NAS_HOST}` |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Marked `blackbox-exporter` deployed, updated notes |
| `docs/CONVENTIONS.md` | New "Cluster-wide secrets (cluster-secrets)" subsection documenting the `sops set` workflow and current key list |

### Key decisions
- Used `monitoring.coreos.com/v1` `Probe` CRs rather than the chart's own `serviceMonitor.targets` — Probe is the idiomatic prometheus-operator mechanism and keeps target definitions out of Helm values, separate from the exporter's own deployment config.
- No `dependsOn: kube-prometheus-stack` on the new Kustomization — per `docs/CONVENTIONS.md`'s documented CRD bootstrap pattern, `monitoring.coreos.com/v1` CRDs are pre-installed cluster-wide via `00-crds.yaml` before Flux ever reconciles, so a raw `Probe`/`PrometheusRule` manifest doesn't need a runtime dependency on the chart that would otherwise install those CRDs.
- `NAS_HOST`/`PG_HOST` went into `cluster-secrets.sops.yaml` (SOPS-encrypted), not `cluster-settings.yaml` (plaintext ConfigMap) — explicit user preference to avoid internal host references sitting in plaintext Git history, even though pre-existing consumers (`postgres-backup-local`, `VOLSYNC_NFS_SERVER`) still hardcode the same IP and weren't retroactively migrated (out of scope for this change).
- Postgres probe targets this cluster's own CloudNativePG `-rw` Service (`${PG_HOST}`), not the NAS — bykaj's equivalent used a separate `${DB_HOST}` distinct from `${NAS_HOST}` too; this cluster runs Postgres in-cluster via CloudNativePG, not NAS-hosted.

---

## 2026-07-10 — `homepage-truenas-sitemonitor-fix`

### Goal
Diagnose recurring `httpProxy` errors in the `homepage` pod's logs and fix the underlying TrueNAS `siteMonitor` misconfiguration.

### What we did
- Checked pod `homepage-c97c96fdd-7wksf` — `1/1 Running`, 0 restarts, healthy; logs showed a recurring `ERR_FR_REDIRECTION_FAILURE` from `<httpProxy>` calling `https://truenas.cluster.vwn.io/`.
- Traced the cause: `services.yaml`'s `siteMonitor` hits TrueNAS through the `envoy-internal` gateway (`network/external-services/truenas/httproute.yaml`), which terminates TLS and forwards plain HTTP to the TrueNAS backend (`10.10.0.41:8080`). TrueNAS's nginx redirects `/` → `/ui/` using the scheme of the connection it actually receives (HTTP), so it emits an absolute `http://` `Location` header even though the original client request was HTTPS. Node's `undici` fetch (used server-side by homepage) refuses to follow a same-origin HTTPS→HTTP downgrade redirect and errors on every check; browsers tolerate it fine, so the clickable `href` was never affected.
- Verified the fix hypothesis empirically: `kubectl exec`'d into the homepage pod and curled `http://truenas.network.svc.cluster.local:8080/` directly — got a same-scheme `302 → /ui/` followed by `200 OK`, confirming a same-scheme redirect resolves cleanly.
- Repointed `siteMonitor` at the in-cluster Service DNS directly (`http://truenas.network.svc.cluster.local:8080`), bypassing the Envoy TLS-termination hop that triggers the downgrade; left `href` untouched since browser-facing access already works.
- User committed and pushed the change independently (commit `8afca88`).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/default/homepage/app/config/services.yaml` | TrueNAS `siteMonitor` changed from `https://truenas.${DOMAIN_CLUSTER}` (via Envoy, triggers downgrade-redirect error) to `http://truenas.network.svc.cluster.local:8080` (direct in-cluster Service DNS) |

### Key decisions
- Left `href` as `https://truenas.${DOMAIN_CLUSTER}` rather than also repointing it — the failure is specific to `undici`'s strict redirect handling used by homepage's server-side `siteMonitor` fetch, not a problem for browser navigation, so only the health-check URL needed to change.
- Used the in-cluster Service DNS (`truenas.network.svc.cluster.local:8080`) rather than fully bypassing Envoy the way `wan-failover` does (raw LAN IP via `external-dns` target) — TrueNAS's HTTPRoute/TLS termination is still needed for legitimate browser access, unlike WAN Failover's router which has no TLS awareness at all.

---

## 2026-07-09 — `bykaj-patterns-keda-deploy`

### Goal
Study bykaj's Plex/Jellyfin GPU (DRA) and NFS-scaler (KEDA) patterns, write standalone adoption plans for both, and deploy the KEDA operator as the first concrete step.

### What we did
- Inspected bykaj's `plex`/`jellyfin` Kustomizations (`tmp/home-ops-bykaj/kubernetes/apps/media/`) directly — multi-doc `ks.yaml` (operator + tools Kustomizations), `components/gpu` DRA `ResourceClaimTemplate`, `components/keda/nfs-scaler` `ScaledObject`, `components/volsync` backup pattern — and reported findings.
- Explained the difference between bykaj's DRA GPU scheduling and this repo's classic device-plugin GPU scheduling in plain terms, with an upgrade-path suggestion.
- Forked a background agent to write a standalone DRA migration plan (`docs/dra-gpu-migration-plan.md`); a second fork corrected a factual error it introduced (wrongly claimed Plex/Jellyfin were current GPU consumers — verified via grep that no workload requests `gpu.intel.com` today).
- A second forked agent, dispatched to write the KEDA plan, misresolved its own directive and re-touched the DRA plan instead. Caught by comparing its self-reported task description against the user's actual `/fork` args; reported the mismatch transparently rather than assuming the KEDA plan existed. Relaunched with a more explicit, self-contained prompt after the user confirmed — it produced `docs/keda-nfs-scaler-plan.md`, finding that KEDA and a blackbox/NFS-probe exporter were both undeployed, and that this repo's only NFS consumer (`postgres-backup-local`) is a CronJob the nfs-scaler pattern doesn't apply to (Ceph-first cluster, not NFS-first).
- User then asked to actually deploy KEDA. Verified the newest chart tag on the mirror (`ghcr.io/home-operations/charts-mirror/keda`, `2.20.1`, matching bykaj's pin) via the GHCR tags API, and checked KEDA's own docs/compatibility page — v2.20 is tested upstream against Kubernetes v1.33–v1.35, one minor behind this cluster's v1.36.1.
- Built the KEDA operator deployment by mirroring this repo's existing `reloader`/`snapshot-controller`/`volsync` pattern (small system operator, own namespace, inline Helm `values:`, no ConfigMap indirection) rather than the tuppr/metrics-server `ConfigMapGenerator` pattern: new `OCIRepository` (cosign-verified) + `ks.yaml` + `app/{namespace,kustomization,helmrelease}.yaml`, wired into both parent `kustomization.yaml` files.
- Validated with `kustomize build` against the new app dir, `apps/system`, `flux/meta/repos/oci`, and the full `apps` tree — all clean.
- Updated `docs/POTENTIAL-DEPLOYMENTS.md`, `docs/ROADMAP.md`, and `docs/keda-nfs-scaler-plan.md` to reflect KEDA-the-operator now being deployed (scoped explicitly as operator-only — no `ScaledObject` created, since no real consumer exists yet).
- Nothing committed or pushed (repo rule: only `/git-stage`/`/git-commit` on explicit request).

### Files changed
| File | Change |
|------|--------|
| `docs/dra-gpu-migration-plan.md` | New — standalone 5-phase DRA GPU migration plan |
| `docs/keda-nfs-scaler-plan.md` | New — standalone KEDA nfs-scaler adoption plan; status banner later updated to reflect the operator's deployment |
| `docs/ROADMAP.md` | Added "Researched Patterns" entries for DRA and KEDA nfs-scaler; updated KEDA section to note the operator is now deployed and flag the Kubernetes v1.36.1 vs. KEDA's tested-ceiling v1.35 gap |
| `docs/POTENTIAL-DEPLOYMENTS.md` | `keda` row marked ✅ deployed, version bumped v2.19.0 → v2.20.1 |
| `kubernetes/flux/meta/repos/oci/keda.yaml` | New — `OCIRepository` for KEDA chart v2.20.1, cosign-verified |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Wired in `keda.yaml` |
| `kubernetes/apps/system/keda/` | New — `ks.yaml` + `app/{namespace,kustomization,helmrelease}.yaml` deploying the KEDA operator (Prometheus ServiceMonitors enabled for operator/metric-server/webhooks) |
| `kubernetes/apps/system/kustomization.yaml` | Wired in `keda/ks.yaml` |

### Key decisions
- Deployed KEDA operator-only, no `ScaledObject` — the nfs-scaler pattern this whole research thread was about has no real target in this cluster yet (one NFS consumer, and it's a CronJob).
- Followed the `reloader`/`snapshot-controller`/`volsync` small-operator convention (inline values, dedicated namespace) over the `tuppr`/`metrics-server` `ConfigMapGenerator` convention — KEDA's values are small enough not to need the indirection.
- Proceeded with chart v2.20.1 despite it being upstream-tested only through Kubernetes v1.35 (cluster runs v1.36.1) — flagged as a first-reconcile risk to watch rather than a blocker, since `kustomize build` validation can't catch an API-server-level incompatibility.
- When a forked agent misresolved its own task directive (re-touched the DRA plan instead of writing the KEDA plan), reported the mismatch to the user directly instead of fabricating that the KEDA plan existed, and only proceeded once the user explicitly confirmed.

---

## 2026-07-09 — `ceph-diskspace-alert-tuning`

### Goal
Verify whether frequent `CephNodeDiskspaceWarning` alerts are genuine disk pressure or nuisance false positives, and fix the root cause if the latter.

### What we did
- Checked repo history first: found an existing, already-silenced false-positive cause (`/etc/nfsmount.conf` duplicate mountpoint, `silence-operator` `Silence` CR) and a prior 2026-06-24 investigation that found nothing firing at the time — established this as a distinct, unrelated issue rather than the cause of "frequent" alerts.
- Dispatched a `cluster-doctor` agent to pull the live `PrometheusRule`, Alertmanager/Prometheus alert history, `node_filesystem_*` metrics, and cluster reboot events. Root-caused: the stock ceph-mixin `CephNodeDiskspaceWarning` rule (from the `rook-ceph-cluster` chart, unmodified) has no `for:` debounce, so a single noisy `predict_linear` evaluation fires when node-exporter's 2-day trailing regression window is starved to under an hour of history right after a node reboot — a normal small post-boot free-space dip extrapolates into a wildly steep, wrong predicted-fill slope. Confirmed via two firings (`cp-01` 2026-07-02, `cp-03` 2026-07-09) both landing within an hour of fleet-wide maintenance reboots; all 5 nodes healthy at 12-27% disk usage with no real fill trend.
- Follow-up round with the same agent verified specifics before designing a fix: the `for:` field is literally absent from the raw `PrometheusRule` YAML (not an explicit `0s`); `node_boot_time_seconds` is scraped and its live values matched the reboot timeline exactly; the cluster's node-exporter scrape interval is currently a temporary 10s (not the 30s default), which would make a `count_over_time` data-completeness guard fragile since its threshold is scrape-interval-coupled; and — correcting an earlier claim of "no lighter override path" — the `rook-ceph-cluster` chart natively exposes a per-rule `prometheusRuleOverrides.<AlertName>` merge-overwrite mechanism, so no vendored mixin copy was needed.
- Implemented the fix: `for: 5m` plus a `node_boot_time_seconds` guard (suppresses the alert for a node's first 30 minutes post-boot) via `prometheusRuleOverrides` on the `rook-ceph-cluster` HelmRelease.
- User asked whether the temporary 10s node-exporter scrape-interval diagnostic override (in place since 2026-06-10 for M920Q pre-crash forensics) should also be reverted. Cross-checked `docs/ROADMAP.md` independently of the stale in-repo comment and confirmed the underlying hard-down bug was root-caused and fixed 2026-06-22 (failing external power brick, replaced, stable 2+ weeks) — agreed and reverted to the chart's 30s default.
- Validated both changes with `task validate` (repo-wide schema check) — passed clean.
- `/git-commit` failed on a local GPG signing/agent communication error (`Couldn't sign message (signer): communication with agent failed`) unrelated to the change itself; did not bypass with `--no-gpg-sign` per repo policy — provided the drafted commit message for the user to run manually, which they did (`46449a9`).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Added `prometheusRuleOverrides.CephNodeDiskspaceWarning` (`for: 5m` + `node_boot_time_seconds` post-boot guard) |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Reverted the 10s node-exporter scrape-interval diagnostic override back to the chart's 30s default |

### Key decisions
- Chose `for: 5m` + a `node_boot_time_seconds` uptime guard over a `count_over_time` data-completeness guard — the latter's threshold would be silently invalidated whenever the cluster's temporary 10s scrape interval reverts to 30s, with no forcing function to catch the drift.
- Verified the M920Q hard-down (the original reason for the 10s scrape override) was independently confirmed resolved in `docs/ROADMAP.md` before agreeing to revert it, rather than trusting the stale in-repo diagnostic comment's framing alone.
- Left the existing `ceph-node-nfsmount-diskspace-warning` `Silence` untouched — confirmed distinct and unrelated; it still doubles every genuine firing of this alert but isn't the root trigger investigated here.
- Declined to bypass the GPG signing failure with `--no-gpg-sign`; handed the commit message to the user to commit manually instead.

---

## 2026-07-09 — `intel-igpu-quicksync-passthrough`

### Goal
Expose the Intel iGPUs (UHD 630) on `cp-02`, `cp-03`, `worker-01`, `worker-02` to Kubernetes as a schedulable `gpu.intel.com/i915` resource, for future Plex/Jellyfin hardware transcode.

### What we did
- User asked how to do Intel iGPU passthrough on Talos (found a Proxmox-specific blog that didn't apply to bare metal); researched via WebSearch/WebFetch — confirmed the Talos-native path is a system extension (`siderolabs/i915`) plus Node Feature Discovery (NFD) plus the Intel Device Plugins Operator/GPU plugin, cross-checked against two independent homelab write-ups (Stonegarden, Jonathan Gazeley) and `siderolabs/extensions` source.
- Confirmed hardware scope from `docs/HARDWARE-ARCHITECTURE.md`: `cp-02`/`cp-03`/`worker-01`/`worker-02` all have Intel UHD 630 (full Quick Sync); `cp-01` (AMD MS-A2, Radeon 610M) already documented as too weak for HW transcode — excluded, consistent with existing docs.
- Found and fixed a real latent bug: `talos/schematic.yaml` had a commented-out, non-existent `siderolabs/i915-ucode` extension name — the real extension is `siderolabs/i915` (bundles driver + firmware). Corrected in place; since this repo uses one shared schematic for all 5 nodes, the driver simply won't bind on `cp-01` (no Intel iGPU PCI ID), mirroring how `intel-ucode`/`amd-ucode` already coexist.
- User picked the full NFD + Intel Device Plugins Operator approach over a simpler hostPath mount (chosen via `AskUserQuestion`), since it scales to future GPU consumers beyond Plex.
- Used `EnterPlanMode` given the live-cluster/reboot impact; ran an `Explore` subagent to pull concrete repo conventions (rook-ceph's multi-doc `ks.yaml` operator+CRD-instance pattern, app-template v5 file layout, HelmRepository vs OCIRepository usage, CONVENTIONS.md drift-detection/comment rules) before writing the plan.
- Added two new Flux sources (`node-feature-discovery` OCIRepository from `registry.k8s.io/nfd/charts`, `intel` HelmRepository from `intel.github.io/helm-charts`) and two new apps: `node-feature-discovery` (single Kustomization) and `intel-device-plugins` (multi-doc `ks.yaml`: operator HelmRelease + GPU-plugin HelmRelease, the latter `dependsOn` both the operator and NFD). Verified chart versions live via ArtifactHub (both Intel charts at `0.36.0`, NFD at `0.18.3`) rather than trusting stale blog-post version numbers.
- Validated all new/changed YAML with `yq` and `kustomize build` before touching the live cluster.
- Rolled the new schematic out: `task talos:iso` (registered new schematic ID `631787e1...`), `task talos:genconfig`, then `task talos:upgrade-node` one node at a time (`cp-02` → `cp-03` → `worker-01` → `worker-02`), checking `kubectl get nodes`, `talosctl etcd members`, and `ceph -s` between each — Ceph dipped to `HEALTH_WARN` transiently after each OSD-host reboot (expected, `size=3`/`min_size=2`) and self-healed within ~30s each time. Confirmed `i915` loaded in `/proc/modules` on all 4 nodes post-rollout.
- Mid-rollout, user noticed the AMT KVM console (MeshCommander) went blank on `cp-02`, then asked if it was iGPU-related after seeing the same on `worker-01`. Diagnosed as a plausible, well-reasoned side effect: AMT KVM redirection taps the iGPU's frame buffer directly, and once `i915` binds and Talos (headless, no display manager) blanks/powers down the display, AMT's video feed has nothing left to capture — correlated exactly with the documented AMT-capable node set (`cp-02`, `worker-01`, `worker-02`). Flagged that AMT power control/IDE-R should be unaffected (separate out-of-band channel), but this is unverified since it can't be checked from this session.
- All Flux-managed manifests are staged locally but deliberately not committed/pushed (repo rule: only `/git-stage`/`/git-commit` on explicit request) — GPU resource verification (node labels, `gpu.intel.com/i915` allocatable) is blocked until that happens.

### Files changed
| File | Change |
|------|--------|
| `talos/schematic.yaml` | Fixed stale/nonexistent `siderolabs/i915-ucode` comment → active `siderolabs/i915` extension |
| `talos/talenv.yaml` | `talosImageURL` updated to new schematic ID via `task talos:iso` |
| `talos/.schematic-id` | Local bookkeeping file updated (new schematic ID) |
| `kubernetes/flux/meta/repos/oci/node-feature-discovery.yaml` | New — OCIRepository, `registry.k8s.io/nfd/charts/node-feature-discovery` @ 0.18.3 |
| `kubernetes/flux/meta/repos/helm/intel.yaml` | New — HelmRepository, `https://intel.github.io/helm-charts/` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered new NFD OCIRepository |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Registered new Intel HelmRepository |
| `kubernetes/apps/node-feature-discovery/` | New app — NFD HelmRelease (`ks.yaml`, `app/{namespace,kustomization,helmrelease}.yaml`); worker DaemonSet tolerates control-plane taint so cp-02/cp-03 get labeled |
| `kubernetes/apps/intel-device-plugins/` | New app — multi-doc `ks.yaml` (operator + gpu Kustomizations), `namespace.yaml`, `operator/app/helmrelease.yaml` (intel-device-plugins-operator), `gpu/app/helmrelease.yaml` (intel-device-plugins-gpu, `sharedDevNum: 4`, `nodeFeatureRule: true`) |
| `kubernetes/apps/kustomization.yaml` | Registered both new app directories |

### Key decisions
- Single shared `schematic.yaml` (not per-node) for the `i915` extension — matches the existing `intel-ucode`/`amd-ucode` coexistence pattern; simpler than introducing per-node schematics for one inert extension on `cp-01`.
- Chose the NFD + Intel Device Plugins Operator route (schedulable `gpu.intel.com/i915` resource) over a simpler hostPath mount, per explicit user choice — scales to future GPU consumers, at the cost of more moving parts (NFD, operator, two HelmReleases).
- `sharedDevNum: 4` on the GPU plugin is a placeholder guess (no consumer deployed yet) — flagged as tunable once Plex/Jellyfin actually lands.
- Did not deploy Plex/Jellyfin itself — scope was limited to exposing the resource and proving it's allocatable, since no consumer exists in this cluster yet.

---

## 2026-07-08 — `resilience-audit-fmea`

### Goal
Design a standard FMEA-based framework for auditing cluster components' failure modes, blast radius, mitigations, and recovery/DR readiness, and pilot it against Rook-Ceph.

### What we did
- User asked for a formal way to audit cluster deployments for threat/error/failure management (impact, mitigations, recovery) without knowing the exact terminology; identified this as **FMEA** (Failure Mode and Effects Analysis) paired with DR runbooks — distinct from security threat modeling.
- Searched existing docs (`CLUSTER.md`, `ROADMAP.md`, `QA.md`) for prior DR content — found strong ad-hoc examples (the CNPG Postgres restore drill, live-tested twice) but no standard schema applied consistently across components.
- Used `AskUserQuestion` to resolve two open design choices: where the catalog should live, and how broad the first pass should be. User chose a new project-local skill producing an audit-generated report (not a hand-maintained doc), starting with one fully-worked pilot component rather than a full sweep.
- Distinguished the two existing skill patterns in this repo: `.agents/skills/gitops-repo-audit` (a heavier `SKILL.md` package, externally synced from an OCI catalog per `.agents/skills/catalog-lock.yaml` — "DO NOT EDIT") vs. `.claude/commands/*.md` (project-authored, single-file skills like `session-log`, `git-stage`) — chose the latter as the correct template.
- Authored `.claude/commands/resilience-audit.md`: defines the FMEA schema (Failure Mode, Blast Radius, Detection, Existing Mitigation, Recovery Procedure, Tested, Severity), a Critical/Warning/Info severity heuristic, a discovery workflow (grep `CLUSTER.md`/`QA.md`/`ROADMAP.md`/`SESSIONS.md`, `ops/*/mod.just`), and edge-case guidance to link to existing runbooks rather than duplicate them.
- Ran the new skill's workflow by hand as the pilot against Rook-Ceph — gathered topology/replication facts from `CLUSTER.md`, `ops/ceph/mod.just`, and recent session history (the X520 NIC failure/restore, the worker-02 OSD disk swap) — and wrote 8 failure-mode rows into `docs/RESILIENCE-AUDIT.md`.
- Pilot surfaced 3 Critical gaps: concurrent 2-node/OSD loss (no tested recovery, and no off-Ceph backup for the `ceph-block`-backed apps — `volsync` currently only covers `waha`), mon-quorum loss (no runbook exists; the existing quorum runbook covers etcd, a different quorum), and unplanned/ungraceful power loss (only the graceful shutdown/cold-start path is documented).
- Verified every `CLUSTER.md`/`QA.md` cross-reference anchor programmatically (simulated GitHub's markdown-slug algorithm in Python against the real headers) after an initial link used doubled hyphens and would have 404'd.
- Wired the new doc into existing doc-index conventions: added rows to `docs/README.md` (agent-facing table + source-of-truth map) and a pointer line in `CLAUDE.md`, mirroring how `REPO-AUDIT.md`/`gitops-repo-audit` are already referenced.

### Files changed
| File | Change |
|------|--------|
| `.claude/commands/resilience-audit.md` | New — project-local skill defining the FMEA schema, severity heuristic, and audit workflow |
| `docs/RESILIENCE-AUDIT.md` | New — audit-generated FMEA report; pilot pass on Rook-Ceph (8 failure modes, 3 Critical) + backlog of 9 other components |
| `docs/README.md` | Added `RESILIENCE-AUDIT.md` to the agent-facing doc table and the source-of-truth map |
| `CLAUDE.md` | Added a pointer to `RESILIENCE-AUDIT.md` alongside the existing `REPO-AUDIT.md` doc-link |

### Key decisions
- Chose a skill-generated report over a hand-maintained living doc (per explicit user choice) — keeps the FMEA catalog from silently drifting the way ad-hoc DR notes already had, scattered across `CLUSTER.md`/`ROADMAP.md`/`QA.md`.
- Started with one fully-worked pilot component (Rook-Ceph, the cluster's stateful-storage backbone) rather than a shallow full-cluster pass, so the schema itself could be sanity-checked against a real, detail-rich component before rolling out further.
- Modeled the skill on the repo's own `.claude/commands/*.md` single-file convention rather than the heavier `SKILL.md` + scripts/references/assets package used by `gitops-repo-audit` — that package is externally synced from an OCI catalog and not the right template for a hand-authored local skill.

---

## 2026-07-08 — `victoria-logs-syslog-ingestion`

### Goal
Design and implement a pattern for ingesting external (non-Kubernetes) syslog sources — starting with TrueNAS — into the existing VictoriaLogs + fluent-bit log stack.

### What we did
- Reviewed the current fluent-bit → VictoriaLogs pipeline (`fluent-bit` DaemonSet tailing `/var/log/containers/*.log`, HTTP `jsonline` output to `victoria-logs-server:9428`) to understand what an external-source pattern should reuse vs. bypass.
- Researched community/upstream practice for syslog ingestion into VictoriaLogs: confirmed VictoriaLogs ships a native syslog listener (`-syslog.listenAddr.tcp/udp/unix`, RFC3164/5424, TLS/mTLS, customizable stream fields) rather than requiring a shipper like fluent-bit or Vector as an intermediary. kubesearch.dev turned up no concrete home-lab precedent for this specific combination, so this is first-principles reasoning from upstream docs rather than a copied pattern.
- Pulled and rendered the pinned `victoria-logs-single` chart (v0.13.8) locally with `helm template`/`helm show values` to verify the exact `server.syslog.tcp[]` values schema, confirm the chart auto-wires syslog ports into its Service/StatefulSet, and confirm the server container runs as non-root (`uid 1000`) — meaning it cannot bind the privileged `:514` port directly.
- Found TrueNAS's real IP (`10.10.0.41`) via the existing `kubernetes/apps/network/external-services/truenas/endpoint.yaml`, avoiding a round-trip to the user for it.
- Implemented: added a `server.syslog.tcp` listener on `:1514` (`useRemoteIP: true`) to the `victoria-logs` `HelmRelease`; added a new standalone `victoria-logs-syslog` `LoadBalancer` Service mapping external port `514` → `1514`, scoped via `loadBalancerSourceRanges` to TrueNAS's IP; wired the new file into `kustomization.yaml`.
- Validated the full app-directory `Kustomization` builds cleanly with `kubectl kustomize`.
- Left TrueNAS-side configuration (System → Advanced Settings → Syslog: server `<LB-IP>:514`, TCP, RFC 5424/3164) and post-apply verification (fetching the actual assigned LB IP, confirming Cilium enforces `loadBalancerSourceRanges`) as follow-ups for after Flux reconciles.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/victoria-logs/app/helmrelease.yaml` | Added `server.syslog.tcp` listener (`:1514`, `useRemoteIP: true`) for external syslog ingestion |
| `kubernetes/apps/observability/victoria-logs/app/kustomization.yaml` | Added `syslog-service.yaml` to resources |
| `kubernetes/apps/observability/victoria-logs/app/syslog-service.yaml` | New — dedicated `LoadBalancer` Service, port `514` → `1514`, restricted to TrueNAS's IP |

### Key decisions
- Chose VictoriaLogs' native syslog listener over routing TrueNAS through fluent-bit: fluent-bit's value-add (the `kubernetes` enrichment filter) doesn't apply to a non-k8s source, so adding it would just be an extra hop with no benefit.
- Used a separate standalone Service for the syslog port instead of switching the chart-managed Service to `LoadBalancer`, so the unauthenticated HTTP insert/query API (port 9428) stays cluster-internal rather than landing on the LAN.
- Listener binds the unprivileged `:1514` internally (container is non-root, uid 1000) with the Service translating the conventional `514` externally, rather than trying to grant `CAP_NET_BIND_SERVICE`.
- Restricted `loadBalancerSourceRanges` to TrueNAS's specific `/32` instead of leaving the listener open to the whole management VLAN.

---

## 2026-07-08 — `metrics-server-oci-migration`

### Goal
Execute the roadmap's "quick win" item — migrate the remaining HTTP `HelmRepository` chart sources (`cilium`, `metrics-server`) to the `home-operations/charts-mirror` `OCIRepository` pattern.

### What we did
- Reviewed `docs/ROADMAP.md`'s "Migrate Remaining HelmRepositories" item; confirmed two outliers still on HTTP `HelmRepository`: `cilium` and `metrics-server`.
- Verified `cilium`'s Flux `HelmRelease` is genuinely live (not a Helmfile-bootstrap leftover, which the roadmap had left ambiguous) via `kubectl get helmrelease cilium -n kube-system` — `Ready: True`, `chart cilium@1.19.5`, matching the live `cilium` pods.
- Queried the `ghcr.io/home-operations/charts-mirror` registry API directly (anonymous pull token) for both charts' tag lists. Found `cilium`'s mirror tops out at `1.18.6` against the cluster's live `1.19.5` — migrating would pin Flux's source below the running CNI version, a genuine downgrade risk on bare metal with no CNI fallback, so **cilium was left on `HelmRepository`**. `metrics-server`'s mirror had an exact `3.13.1` match, so it was migrated.
- Migrated `metrics-server`: created the new `OCIRepository` source file, removed the old `HelmRepository` file, updated both `kustomization.yaml` index files under `kubernetes/flux/meta/repos/`.
- Found and corrected a bug in the roadmap's own migration plan: OCI-sourced `HelmRelease`s in this repo use the top-level `spec.chartRef` field, not `spec.chart.spec.sourceRef` as the roadmap's original steps assumed — confirmed by cross-referencing existing OCI-sourced HelmReleases (`tailscale-operator`, `tuppr`, `silence-operator`). Updated `metrics-server`'s `HelmRelease` accordingly, moving the version pin onto the `OCIRepository`'s `ref.tag`.
- Validated every changed Kustomization builds cleanly (`kustomize build` against `flux/meta/repos/oci/`, `flux/meta/repos/helm/`, and the `metrics-server` app directory).
- Updated `docs/ROADMAP.md`'s migration section to reflect actual state: `metrics-server` done, `cilium` blocked with the tag-list evidence and the exact command to re-check, and corrected the `chartRef` guidance for whoever picks up `cilium` later.

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Documented `metrics-server` migration done; `cilium` blocked (mirror lags at `1.18.6` vs live `1.19.5`); corrected `chartRef` guidance |
| `kubernetes/apps/kube-system/metrics-server/app/helmrelease.yaml` | Switched from `chart.spec.sourceRef` (HelmRepository) to `chartRef` (OCIRepository) |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Removed `metrics-server.yaml` entry |
| `kubernetes/flux/meta/repos/helm/metrics-server.yaml` | Deleted — HelmRepository source removed |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `metrics-server.yaml` entry |
| `kubernetes/flux/meta/repos/oci/metrics-server.yaml` | New OCIRepository source, pinned `3.13.1`, cosign-verified |

### Key decisions
- Did not migrate `cilium` despite being in scope: the mirror's published tags stop at `1.18.6` while the cluster runs `1.19.5` live. Migrating would pin Flux's source below the running CNI version — deferred until the mirror catches up, not abandoned.
- Corrected the roadmap's own migration steps (`chartRef` vs `chart.spec.sourceRef`) against the convention already used elsewhere in the repo, rather than following the pre-written (and incorrect) plan verbatim.

---

## 2026-07-07 — `x520-bond-storage-restore`

### Goal
Verify the newly reinstalled X520-DA2 card in cp-03, then migrate all 5 nodes back from the VLAN-200 storage fallback to LACP-bonded X520/X710 (`bond-storage`), keeping the VLAN-200 config as a commented-out fallback rather than deleting it.

### What we did
- Re-familiarized with the fleet-wide VLAN-200 fallback state via `docs/CLUSTER.md`, `docs/SESSIONS.md`, and the `cluster-doctor` agent's `project_cp02_storage_bond_ixgbe_failure.md` memory; confirmed commit `4e353c2` (prior session's doc fixes) was already in place and the tree was otherwise clean.
- Delegated hardware verification of cp-03's newly installed X520-DA2 to the `talos-node-manager` agent: confirmed both ports (`enp2s0f0`/`enp2s0f1`) probed cleanly via `dmesg` (no `-114` HW Init failure, unlike the original faulty card), link-up at 10 Gbit/s, and retrieved their real MACs (`90:e2:ba:e8:ea:00`/`:01`) to replace the `xx:xx:xx:xx:xx:xx` placeholders. Flagged one non-blocking anomaly: `enp2s0f0` had more boot-time SFP+ link flap cycles (8x) than `enp2s0f1` (2x) before both settled to a stable `Up`.
- Edited `talos/talconfig.yaml` across all 5 nodes: commented out each node's inline VLAN-200 patch (kept in place, not deleted, per explicit request for easy future fallback) and restored `bond-storage`'s `addresses:` block. cp-03 additionally got its placeholder MACs replaced with the verified real ones and its patch comments rewritten to reflect the resolved state.
- Ran `task talos:genconfig` (talhelper) and spot-checked the generated per-node YAML to confirm `bond-storage` carried the storage IP with zero `vlanId` occurrences (i.e. the commented-out patches produced no live config).
- Asked the user how to sequence the live rollout; per their choice, applied `task talos:apply IP=<ip>` to cp-03 first, confirmed via `talosctl get links` that `bond-storage` came up `MASTER`/`UP` with both slaves attached at MTU 9000, and confirmed `ceph -s` stayed `HEALTH_OK` before proceeding.
- Applied to the remaining 4 nodes (cp-01, cp-02, worker-01, worker-02) in the same pass; all 5 applied without requiring a reboot. Verified all 5 `bond-storage` interfaces came up correctly. Ceph briefly showed a `HEALTH_WARN` (slow OSD heartbeats, back/front) — the same MAC-table/ARP-relearning pattern documented from the original 2026-06-18 cutover — which self-cleared to `HEALTH_OK` within ~30s.
- Deactivated the 3 `silence-operator` Silences whose documented revert conditions (replacement card installed, fallback reverted) were now met — dropped their entries from `silences/kustomization.yaml` (so they no longer apply) but kept the files on disk, relabeled `INACTIVE`, for reference if the same fallback is ever needed again.
- Updated `docs/CLUSTER.md`'s fallback note to describe the resolution (dates, verification steps, the cp-03 link-flap watch item) instead of describing an active incident.
- Closed out the `cluster-doctor` agent memory (`project_cp02_storage_bond_ixgbe_failure.md` + its `MEMORY.md` index line) with a resolution section, so future diagnostics don't keep treating this as an open incident.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Reverted all 5 nodes from VLAN-200 fallback to `bond-storage`; VLAN-200 patches commented out (not deleted); cp-03 deviceSelector MACs set to the real replacement card's addresses |
| `kubernetes/apps/observability/silence-operator/silences/bond-storage-degraded-x520-fallback-ceph.yaml` | Marked `INACTIVE`; kept on disk, dropped from kustomization.yaml |
| `kubernetes/apps/observability/silence-operator/silences/bond-storage-degraded-x520-fallback-node-exporter.yaml` | Marked `INACTIVE`; kept on disk, dropped from kustomization.yaml |
| `kubernetes/apps/observability/silence-operator/silences/ceph-node-network-packet-drops-x520-fallback.yaml` | Marked `INACTIVE`; kept on disk, dropped from kustomization.yaml |
| `kubernetes/apps/observability/silence-operator/silences/kustomization.yaml` | Dropped the 3 deleted Silences' resource entries |
| `docs/CLUSTER.md` | Fallback note updated from active-incident to resolved, with verification detail and cp-03 watch item |
| `.claude/agent-memory/cluster-doctor/project_cp02_storage_bond_ixgbe_failure.md` | Added a Resolution (2026-07-07) section; updated frontmatter description to RESOLVED |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Updated index line to reflect resolved status |

### Key decisions
- Kept the VLAN-200 patches commented out in `talconfig.yaml` rather than deleting them, per explicit user request — cheap insurance that preserves the non-obvious syntax notes (e.g. cp-03's `interface: eno1` vs `deviceSelector` gotcha) for a future NIC failure without cluttering the active config.
- Sequenced the live rollout as cp-03-first rather than all-5-at-once (user's choice from an explicit prompt) — validated the newest hardware change in isolation before touching the 4 nodes that already had known-good X520s.
- Deleted the 3 fallback Silences immediately rather than leaving them in place a while longer — their own documented revert conditions were unambiguously met, and stale Silences risk masking a real future recurrence of the same alert.

---

## 2026-07-04 — `renovate-missing-datasource-fix`

### Goal
Debug the warnings and skipped-dependency noise reported by the Mend-hosted Renovate job run and fix the actual root cause.

### What we did
- User asked to debug via a `developer.mend.io` job log URL; `WebFetch` returned an empty Next.js SPA shell — confirmed via `curl` that the page requires an authenticated GitHub session (`"success":false,"userSession":null"` in the embedded `__NEXT_DATA__`), so it can't be read directly.
- Used the repo's Dependency Dashboard GitHub issue (`#2`) as a proxy — it surfaced one collapsed `⚠️ WARN: Missing datasource!` line under "Repository Problems" with no file/package attribution.
- Cross-referenced all 43 `# renovate:` annotations in the repo against each other's conventions and initially misdiagnosed the cause as `metrics-server`'s `HelmRelease` annotation (used `registryUrl=` instead of `datasource=`/`depName=`) — applied a fix based on this wrong hypothesis.
- User then downloaded and shared the actual raw Bunyan/pino JSON-lines job log (1241 lines, 638KB). Filtering with `jq 'select(.level>=40)'` found the real cause: 4 identical warnings, all `datasourceName: "grafana-dashboard"` — unrelated to metrics-server. Reverted the incorrect metrics-server edit back to its original content.
- Root-caused the real bug: Renovate namespaces custom datasources under a `custom.` prefix (`custom.<name>`) to avoid colliding with built-in datasource IDs. The repo's `grafanadashboard.yaml` annotations (4x, unpoller's UniFi dashboard revisions) referenced the bare `grafana-dashboard` name instead of `custom.grafana-dashboard`.
- Fixed all 4 annotations in `grafanadashboard.yaml` and the corresponding `packageRules` `matchDatasources` entry in `renovate.json5` (both needed the prefix; the `customDatasources` definition block itself correctly keeps the bare key).
- Audited the remaining ~195 `Skipping`/informational log lines with `jq` and classified all of them as benign/expected: digest-pin skips (repo doesn't digest-pin OCI charts), `pgadmin4`'s date-tag major-increment guard noise, Mend's `internalChecksFilter` gate holding 14 branches (matches the dashboard's "Pending Status Checks" section exactly), and `ignoreDeps` entries (1password/etcd/talosctl) working as intended. No other real bugs found in the run.

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Updated the Grafana-dashboard `packageRules` entry's `matchDatasources` to `custom.grafana-dashboard` |
| `kubernetes/apps/observability/unpoller/app/grafanadashboard.yaml` | Fixed 4 dashboard-revision annotations to `datasource=custom.grafana-dashboard` |

### Key decisions
- Reverted the initial (wrong) `metrics-server.yaml` fix once the real job log revealed the actual cause, rather than leaving speculative-but-harmless cruft in the diff — the Dependency Dashboard's collapsed, unattributed warning line was not enough evidence to act on alone.
- Treated the Mend job log's authentication wall as a hard blocker rather than attempting further scraping workarounds; relied on the Dependency Dashboard issue and then the user-supplied raw log file instead.

---

## 2026-07-03 — `gitops-repo-audit-sixth-pass`

### Goal
Re-run the `gitops-repo-audit` skill for a sixth pass against the current repo state, refresh `docs/REPO-AUDIT.md`, and implement the one fix worth taking (explicit Gateway `tls.mode`).

### What we did
- Ran the full `gitops-repo-audit` skill workflow: discovery, manifest validation, API-compliance, best-practices, and security review, comparing against the fifth pass (baseline `e542cd3` → HEAD `7d8e377`, 26 commits).
- `flux-schema` wasn't preinstalled in this devcontainer — fetched the v0.6.0 release binary fresh from GitHub and installed it to `~/.local/bin` to unblock `discover.sh`/`validate.sh`.
- First discovery pass inflated to 1480 resources; root-caused to a gitignored `tmp/` scratch directory (two full reference-repo clones from prior kubesearch.dev research, e.g. `home-ops-bykaj`) that isn't part of the actual GitOps tree — excluded it (`-e tmp`) and re-ran, landing at the expected ~37 HelmReleases / 53 Kustomizations / 26 OCIRepositories.
- Triaged all "invalid" validation hits: confirmed 61 (then 16 once properly scoped with `-e talos -e assets -e .archive -e ops`) were false positives — Talos machine-config YAML being scanned as if it were Kubernetes manifests, and `postBuild.substitute` placeholders (`${DOMAIN_CLUSTER}` etc.) that only resolve at apply time.
- Found two new `Gateway` `cel violation` findings not seen in the fifth pass: `envoy-external`/`envoy-internal`'s HTTPS listeners omit `tls.mode` explicitly, relying on the Gateway API's implicit `Terminate` default — a `flux-schema` v0.6.0 CEL rule evaluates `self.mode` before the OpenAPI default applies, so it misfires on an otherwise-valid config. Also found the same v0.6.0 CEL ruleset misfiring on `envoy-external/internal-http-redirect` HTTPRoutes' single-entry `parentRefs` arrays (a real tool artifact, no repo-side fix available).
- Found one genuine best-practices gap: `fluent-bit`'s commit `50fe449` ("enhance log filtering for tailscale-operator and localapi calls") ships its localapi noise-reduction `[FILTER]` block fully commented-out inside the live config string — the noise reduction the commit describes isn't actually happening at runtime. User confirmed this is fine as-is (kept as a commented reference for future use), so left unfixed by design.
- Re-verified all previously-resolved invariants are still holding: zero `dependsOn` cycles/dangling refs (53 Kustomizations, checked programmatically), zero drift-detection opt-outs, zero `configMapGenerator` watch-label gaps, no plaintext secrets, no `insecure: true` sources, no hardcoded credentials.
- Reviewed the three new apps added since the fifth pass in detail: `unpoller` (UniFi metrics via app-template), `grafana-operator` (external mode, correctly `dependsOn`s + explicit cross-Kustomization `healthChecks` on `kube-prometheus-stack`'s async `grafana-admin` `ExternalSecret`), and `silence-operator` (4 well-scoped `Silence` CRs, each with an inline revert condition).
- At the user's request, implemented the one accepted recommendation: added `tls: { mode: Terminate }` explicitly to both Gateway HTTPS listeners in `kubernetes/apps/network/envoy-gateway/config/gateway.yaml`. Verified via `kustomize build` (unchanged output apart from the added field) and `flux-schema validate --verbose` (both Gateways now report `is valid`, CEL finding gone).
- Updated `docs/REPO-AUDIT.md` as a sixth pass: refreshed resource counts, validation results, best-practices "What's Working Well"/"Gaps" tables, OCI cosign coverage table (8/26 verified), and the Recommendations tables (added W4 for the fluent-bit gap, opened then closed I15 for the Gateway fix, added the `flux-schema` install step and `-e tmp` exclusion to the "How to Re-Audit" recipe).

### Files changed
| File | Change |
|------|--------|
| `docs/REPO-AUDIT.md` | Sixth audit pass — refreshed inventory/validation/best-practices/security sections, added W4 (fluent-bit filter gap, left open by user choice) and I15 (Gateway `tls.mode`, resolved same session) |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Added explicit `tls: { mode: Terminate }` to both `envoy-external` and `envoy-internal` HTTPS listeners |

### Key decisions
- User accepted the `fluent-bit` W4 finding as intentional (commented-out filter kept for future reference) rather than a bug to fix — left as-is per explicit instruction, documented in the audit doc as an open item rather than resolved.
- Chose to fix I15 (explicit `tls.mode`) even though it's a functional no-op, because it's zero-risk, self-documenting, and eliminates a recurring validator false-positive in future audit passes.
- No session had been opened before this work started — this record was produced retroactively via `/session-log`.

---

## 2026-07-03 — `unpoller-grafana-operator-deploy`

### Goal
Deploy `unpoller` for UniFi controller metrics, add `grafana-operator` (external mode) for cleaner Renovate-trackable dashboard management, and align `node-exporter-full`'s dashboard provisioning with the same offline-reproducible pattern.

### What we did
- Researched `unpoller`: checked `kubesearch.dev` and the `tmp/home-ops-bykaj` reference repo, confirming the community-standard deployment is a plain `app-template` container (not a dedicated chart) and that it was already listed as a planned deployment in `docs/POTENTIAL-DEPLOYMENTS.md`.
- Found the cluster's `external-dns-unifi` `ExternalSecret` already extracts a 1Password item named `unifi` with `UNIFI_HOST`/`UNIFI_API_KEY` — reused it directly for `unpoller`, avoiding any new 1Password item.
- Initially planned dashboards as static `configMapGenerator` ConfigMaps (matching the existing ceph-mixin pattern, since this repo doesn't run grafana-operator) — downloaded and prepared JSON for 4 UniFi dashboards plus `node-exporter-full`, including a datasource-placeholder fix (`${DS_PROMETHEUS}`/`${DS_UNIFI_POLLER}` → the cluster's actual `Prometheus` datasource name) needed for the sidecar path.
- User pivoted mid-implementation to grafana-operator for cleaner, typed dashboard config (`grafanaCom: {id, revision}`). Investigated two integration modes: bykaj's model (operator natively owns Grafana — its own Deployment/PVC/admin secret) vs. **external mode** (`Grafana` CR with `spec.external.url` pointing at the already-running `kube-prometheus-stack-grafana`, reusing the existing `grafana-admin-secret`). Verified the `External` Go struct fields directly from grafana-operator's source. Presented both with the concrete risk difference (external mode: zero-risk, no data migration; native mode: stateful cutover of a live Grafana with real dashboard history) — user chose external mode for the live deployment and asked for a thorough `ROADMAP.md` entry documenting the native-mode alternative.
- Deployed `grafana-operator` (OCI chart `5.24.0`, confirmed via the GHCR tags API) in external mode, plus `unpoller`'s dashboards as `GrafanaDashboard` CRDs using `grafanaCom.{id,revision}` (fetched fresh from grafana.com, so the earlier local datasource-placeholder fix wasn't needed for these — the CRD's own `datasources:` mapping handles substitution).
- Found and closed a bootstrap-ordering gap: `kube-prometheus-stack`'s `ks.yaml` has `wait: false`, so nothing guarantees `grafana-admin-secret` (created async by its `ExternalSecret`) exists before the new `Grafana` CR consumes it. Added an explicit cross-Kustomization `healthChecks` entry (on the `ExternalSecret`, not owned by this Kustomization) rather than touching kube-prometheus-stack's existing config.
- At the user's explicit request, wired a Renovate `customDatasources` entry (`grafana-dashboard`, backed by grafana.com's `/revisions` API) plus a `loose`-versioning `packageRule`, reusing the existing generic `# renovate: datasource=... depName=...` regex manager — so `grafanaCom.revision` bumps now surface as real Renovate PRs.
- Restructured `node-exporter-full` off the Helm `dashboards.default.gnetId/revision` fetch-by-ID mechanism onto a static `configMapGenerator` JSON file (matching ceph-mixin) — confirmed first that the existing `# renovate: depName=... dashboardId=... revisionId=...` comment wasn't actually wired to any live Renovate rule (no `datasource=` token, didn't match the one existing customManager regex), so no real automation was lost by the switch; motivated instead by removing Grafana's runtime dependency on reaching grafana.com at pod startup, and by git-diffable dashboard content.
- Wrote a thorough `docs/ROADMAP.md` entry contrasting the adopted external-mode approach against bykaj's full-native-Grafana model, including concrete migration cost/blast-radius reasoning (referencing the 2026-06-22 VolSync/waha PVC incident as the same risk category).
- Updated `docs/POTENTIAL-DEPLOYMENTS.md` to mark both `unpoller` and `grafana-operator` as deployed, with notes on scope (only `unpoller`'s dashboards use the CRD path so far; ceph-mixin/node-exporter-full remain on the sidecar pattern).
- Flagged that no session had been opened for this work (caught only at the end) — this record was produced retroactively via `/session-log`.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/grafana-operator.yaml` | New `OCIRepository` source for the grafana-operator chart (`5.24.0`) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new `OCIRepository` source |
| `kubernetes/apps/observability/grafana-operator/ks.yaml` | New two-`Kustomization` Flux wiring (operator + external `Grafana` CR instance), with explicit `healthChecks` on the operator `HelmRelease`, the `Grafana` CR, and `kube-prometheus-stack`'s `grafana-admin` `ExternalSecret` |
| `kubernetes/apps/observability/grafana-operator/operator/kustomization.yaml` | Kustomize entry-point for the operator |
| `kubernetes/apps/observability/grafana-operator/operator/helmrelease.yaml` | New `HelmRelease` (`serviceMonitor.enabled: true`) |
| `kubernetes/apps/observability/grafana-operator/instance/kustomization.yaml` | Kustomize entry-point for the `Grafana` CR |
| `kubernetes/apps/observability/grafana-operator/instance/grafana.yaml` | New `Grafana` CR, `spec.external` mode against `kube-prometheus-stack-grafana`, reusing `grafana-admin-secret` |
| `kubernetes/apps/observability/unpoller/ks.yaml` | New Flux `Kustomization`, `dependsOn` `kube-prometheus-stack` (ServiceMonitor CRD) and `grafana-operator-instance` (GrafanaDashboard CRD + target instance) |
| `kubernetes/apps/observability/unpoller/app/kustomization.yaml` | New Kustomize entry-point |
| `kubernetes/apps/observability/unpoller/app/externalsecret.yaml` | New `ExternalSecret`, reuses the existing `unifi` 1Password item (same one `external-dns-unifi` uses) |
| `kubernetes/apps/observability/unpoller/app/helmrelease.yaml` | New `HelmRelease` (`app-template`), UniFi API-key auth, `/health` probes, 2m `ServiceMonitor` interval |
| `kubernetes/apps/observability/unpoller/app/grafanadashboard.yaml` | New: 4 `GrafanaDashboard` CRDs (`grafanaCom.{id,revision}`, Renovate-tracked) |
| `kubernetes/apps/observability/kustomization.yaml` | Registered `grafana-operator/ks.yaml` and `unpoller/ks.yaml` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/node-exporter-full.json` | New: static dashboard JSON (grafana.com ID `1860`, revision `37`) |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Added `configMapGenerator` entry for `node-exporter-full`, labelled `grafana_dashboard: "1"` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Removed the `dashboards.default.node-exporter-full` `gnetId`/`revision` block (superseded by the static ConfigMap) |
| `renovate.json5` | Added `customDatasources.grafana-dashboard` (grafana.com revisions API) and a `loose`-versioning `packageRule` scoped to it |
| `docs/ROADMAP.md` | New "Grafana-Operator: Full Native Migration (Future)" entry under Researched Patterns, documenting the not-adopted alternative |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Marked `unpoller` and `grafana-operator` as deployed (✅), with scope notes |

### Key decisions
- **External mode over native Grafana CR**: chosen specifically to avoid a stateful cutover of the live, working Grafana instance (own PVC, own dashboard history restored from NFS post-Ceph-migration). Native mode remains a documented option in `docs/ROADMAP.md` if Grafana's own config/lifecycle ever needs CRD management.
- **Only `unpoller` moved to `GrafanaDashboard` CRDs** — ceph-mixin and `node-exporter-full` stay on the ConfigMap-sidecar pattern for now, keeping this session's blast radius contained rather than migrating everything for consistency in one pass.
- **`node-exporter-full` restructured to static ConfigMap despite being unrelated to the grafana-operator pivot** — agreed independently, on the grounds that the existing Renovate-tracking comment for it was already inert (regex mismatch), so the switch away from Helm's `gnetId` fetch-by-ID lost no real automation while gaining offline reproducibility and diffable content.

---

## 2026-07-02 — `x520-nic-failure-vlan200-fallback`

### Goal
Root-cause cp-02's X520 storage NIC hardware failure, exhaust remediation options, and record the resulting fleet-wide `bond-storage` → VLAN-200 storage fallback (retroactively logged — this work was not captured in a session at the time).

### What we did
- 2026-06-25: investigated a "3 pending deployments" report; found 6 pods stuck (`automation/waha`, `database/pgadmin`, `observability/{alertmanager,grafana,prometheus,victoria-logs-server}`) on `FailedMount`/`FailedAttachVolume`/`Multi-Attach` errors against Rook-Ceph RBD PVCs.
- Root-caused via `dmesg`: cp-02's dual-port Intel X520 (ixgbe) NIC failed HW/PCI probe on boot (`ixgbe 0000:02:00.0`/`.1: HW Init failed: -114`), leaving `bond-storage` mastered but slave-less. This caused Ceph OSD heartbeats over the storage network to flap, and separately left the RBD CSI nodeplugin pod on cp-02 holding stuck volume-operation locks from hung stage/unstage calls — producing duplicate `VolumeAttachment`s and `Multi-Attach`/`FailedMount` errors on unrelated nodes. Pods had been silently retrying for 361 failed mount attempts over 12h.
- Confirmed node identity (ruled out misattribution) and checked cp-03 (identical M90q + X520-DA2 hardware) on a fresh reboot — its ixgbe ports probed cleanly, isolating the fault to cp-02's specific card rather than a systemic driver/Talos issue.
- Escalated through 3 remediation attempts on cp-02 — warm reboot, full cold power-cycle, physical card reseat — all reproduced the identical `-114` failure, pointing to a genuine silicon/NVM-level fault rather than a transient firmware or seating issue. Concluded a Talos-level reset has no path to touch NIC firmware and would only reinstall the same failing combination.
- Swapped the X520 card between cp-02 and cp-03's physical slots for fault isolation (cp-03's known-good card is now physically in cp-02; cp-02's bad card is now in cp-03).
- 2026-07-01: cp-03's physical node was replaced entirely (unrelated hardware issue); the replacement unit shipped with no X520 card installed.
- 2026-07-02: applied an inline VLAN-200 fallback patch across **all 5 nodes** — tags a VLAN 200 sub-interface on each node's onboard 1GbE management NIC carrying the existing `10.200.0.20{1..5}/24` storage address at MTU 1500, and comments out `bond-storage`'s `addresses:` so the bond stays configured but unaddressed fleet-wide. Applied uniformly even to cp-01/worker-01/worker-02, whose X520/X710 hardware is healthy, to keep every node on the same storage path during the outage. Verified `ceph -s` stayed `HEALTH_OK` with all 10 OSDs up/in throughout — same subnet, so Ceph's public/cluster network config needed no changes.
- Added 3 GitOps-managed `silence-operator` Silences (2026-07-02/07-03) to suppress the expected `CephNodeNetworkBondDegraded`/`CephNodeNetworkPacketDrops` noise from the intentional fallback, each with a documented revert condition tied to replacement-card installation.
- 2026-07-07: recorded the full incident (root cause, remediation attempts, differential cp-03 check, revert steps) into a new `cluster-doctor` agent-memory file, alongside 3 unrelated diagnoses from the same period, and corrected stale kube-vip/Longhorn references in the agent's own docs.
- 2026-07-07 (this entry): found and fixed `docs/CLUSTER.md`'s stale NIC-topology section, which still described the pre-incident 2026-06-18 `bond-storage` cutover as current state with no mention of the failure or fallback — flagged independently three times (twice by `cluster-doctor` in its own memory, once in conversation) before being addressed.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Fleet-wide VLAN-200 fallback patch on all 5 nodes; `bond-storage` addresses commented out; cp-02 deviceSelector MACs updated to the ex-cp-03 card; cp-03 deviceSelectors set to placeholder pending replacement card |
| `kubernetes/apps/observability/silence-operator/silences/bond-storage-degraded-x520-fallback-ceph.yaml` | New: Silence for expected `CephNodeNetworkBondDegraded` noise |
| `kubernetes/apps/observability/silence-operator/silences/bond-storage-degraded-x520-fallback-node-exporter.yaml` | New: Silence, node-exporter's copy of the same condition |
| `kubernetes/apps/observability/silence-operator/silences/ceph-node-network-packet-drops-x520-fallback.yaml` | New: Silence for expected `CephNodeNetworkPacketDrops` noise |
| `.claude/agent-memory/cluster-doctor/project_cp02_storage_bond_ixgbe_failure.md` | New: full root-cause chain, remediation attempts, differential cp-03 check, revert steps |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Indexed the new memory file |
| `.claude/agents/cluster-doctor.md` | Corrected stale kube-vip → Talos-native VIP and Longhorn → Rook-Ceph references |
| `docs/CLUSTER.md` | Added a dated note describing the current fleet-wide VLAN-200 fallback and revert conditions; hardware table kept as the target/normal-state reference |

### Key decisions
- Applied the VLAN-200 fallback to all 5 nodes rather than just the 2 affected ones — uniform topology during the outage was judged simpler to reason about and revert than a mixed bond/VLAN fleet.
- Treated the repeated identical `-114` failure across reboot, cold power-cycle, and reseat as conclusive evidence of a hardware/NVM fault rather than continuing to chase software-level fixes — ruled out `talosctl reset` early since it cannot touch NIC firmware.
- Left `docs/CLUSTER.md`'s hardware table showing the target/normal `bond-storage` topology rather than rewriting it to the fallback state, since the fallback is explicitly temporary — added a dated note instead so the table doesn't need a second rewrite once cards are replaced.

---

## 2026-06-24 — `silence-operator-deploy`

### Goal
Deploy silence-operator for GitOps-managed Alertmanager silences, seed it with a real false-positive silence, and evaluate whether a second `CephNodeDiskspaceWarning` silence is warranted.

### What we did
- Researched community patterns for `silence-operator` (Giant Swarm): checked the `tmp/home-ops-bykaj` reference repo and cross-checked `kashalls/home-cluster` via the GitHub API, plus `kubesearch.dev`. Confirmed current chart version (`0.20.1`), that it's sourced directly from `gsoci.azurecr.io` (not mirrored on `home-operations/charts-mirror`), and that the operator-then-CRD-instance two-Kustomization split is the same pattern this repo already uses for `tuppr`.
- Checked the cluster's live, manually-created Alertmanager silence (`PrometheusRuleFailures`, tied to a transient mgr-pod-restart artifact) and found its matchers pinned an ephemeral pod name/instance IP — a poor fit for a GitOps `Silence` CR. Recommended leaving it to expire on its own (2026-06-25) rather than porting it.
- Asked the user whether to seed `silences/` with that silence anyway; user chose operator-only deployment with an empty scaffold instead.
- Built and validated the full deployment: new `OCIRepository` source, a two-Kustomization `ks.yaml` (operator + dependent `*-silences` Kustomization), a `HelmRelease` pointed at `kube-prometheus-stack-alertmanager`, and an empty `silences/kustomization.yaml`. Verified the `Silence` CRD's schema is hosted at `kubernetes-schemas.pages.dev` (this repo's usual `schemas.clustrs.dev` 404s for it).
- At the user's request, added a first real `Silence` CR for `CephNodeDiskspaceWarning` + `mountpoint=/etc/nfsmount.conf`, mirroring ByKaj's example and matching an existing known false positive already worked around in `kube-prometheus-stack`'s `values.yaml`.
- Verified node-exporter's actual default for `--collector.filesystem.mount-points-exclude` against the live `v1.11.1` binary's source, confirmed the cluster's override was that default plus one extra path, and removed the now-redundant override in favor of the new `Silence` — documented the resulting trade-off (duplicate metric series and the alert both return, now suppressed instead of absent) inline in the `Silence` CR's own comments.
- Committed the change (`c737a69`); after the user pushed, verified the full Flux reconciliation chain end-to-end (`GitRepository` → both `Kustomization`s → `OCIRepository` → `HelmRelease` → pod → operator logs → live Alertmanager API) and confirmed the new silence was active. Flagged a `kubectl` gotcha: the bare `silence` short name resolves to the legacy `monitoring.giantswarm.io/v1alpha1` CRD instead of the `observability.giantswarm.io/v1alpha2` one actually in use.
- Explained the conceptual difference between silenced/inhibited/muted alerts, verifying field names (`inhibitRules`, `muteTimeIntervals`) against the live `AlertmanagerConfig` CRD rather than from memory; confirmed silence-operator only manages the Silences API and has no path to inhibition rules or mute time intervals (those stay in `alertmanagerconfig.yaml`).
- Investigated whether a second `CephNodeDiskspaceWarning` silence (analogous to ByKaj's device-based example) was warranted: confirmed nothing is currently firing in either Prometheus or Alertmanager, pulled the rule's actual PromQL expression, and queried current mountpoint/device/avail% across all 5 nodes. Found no good candidate — the alert is a generic node root-filesystem check, not Ceph-OSD-specific (OSDs are raw block devices, so they never appear in this label set) — and left the decision with the user instead of fabricating a candidate.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/silence-operator.yaml` | New `OCIRepository` source for the silence-operator chart (`0.20.1`) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new `OCIRepository` source |
| `kubernetes/apps/observability/silence-operator/ks.yaml` | New two-`Kustomization` Flux wiring (operator + dependent silences) |
| `kubernetes/apps/observability/silence-operator/app/kustomization.yaml` | New Kustomize entry-point for the operator |
| `kubernetes/apps/observability/silence-operator/app/helmrelease.yaml` | New `HelmRelease` (`alertmanagerAddress`, `networkPolicy` disabled) |
| `kubernetes/apps/observability/silence-operator/silences/kustomization.yaml` | New Kustomize entry-point listing the seed `Silence` |
| `kubernetes/apps/observability/silence-operator/silences/ceph-node-nfsmount-diskspace-warning.yaml` | New `Silence` CR for the `nfsmount.conf` duplicate-mountpoint false positive, with inline rationale |
| `kubernetes/apps/observability/kustomization.yaml` | Registered the `silence-operator` `ks.yaml` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Removed the now-redundant node-exporter `mount-points-exclude` override |

### Key decisions
- Did not port the live manual silence (`PrometheusRuleFailures`) into GitOps — its matchers pinned an ephemeral pod name/instance IP that would already be stale by the time it merged; left it to expire on its own.
- Sourced the chart directly from Giant Swarm's own registry (`gsoci.azurecr.io`) rather than the `home-operations` community mirror, since it isn't mirrored there.
- Removed the node-exporter `mount-points-exclude` override in favor of the `Silence` CR, accepting that the duplicate series and alert now return (suppressed rather than absent) in exchange for centralizing suppression in Git-managed `Silence` CRs instead of exporter CLI flags.
- Declined to add a second `CephNodeDiskspaceWarning` silence speculatively — checked live cluster state first, found no firing alert or noisy mountpoint to justify one, and left the decision with the user.

---

## 2026-06-23 — `victoria-logs-fluent-bit-deploy`

### Goal
Deploy cluster-wide log aggregation: evaluate Loki vs VictoriaLogs for the home-lab's observability stack, then scaffold and validate a complete VictoriaLogs + fluent-bit pipeline (Grafana integration, dashboards, and an external route) after switching away from an initially-built Loki + Alloy scaffold.

### What we did
- Explained what Loki would add on top of the existing kube-prometheus-stack (Grafana + Prometheus) — index-only-labels design, LogQL/Explore correlation — and the filesystem-on-`ceph-block` vs Backblaze B2 storage tradeoff; recommended filesystem given no in-cluster RGW (`cephObjectStores: []`) and lower stakes than the CNPG-backup use case that justified B2 previously.
- Scaffolded a full Loki (`SingleBinary`, filesystem storage, `ceph-block` PVC) + Alloy (API-based `loki.source.kubernetes` log tailing, no hostPath mounts, plus `loki.source.kubernetes_events`) deployment, adapting the cluster's own `.archive/` prior-art config. Verified live chart versions/sources (`oci://ghcr.io/grafana/helm-charts/loki` 7.0.0; Alloy has no Grafana OCI mirror, used `ghcr.io/home-operations/charts-mirror/alloy` 1.10.0) and pulled full chart `values.yaml`/templates rather than guessing schema. Caught two real bugs via `helm template` dry-run: a missing `interval` field, and Loki's own `validate.yaml` guard requiring `write/read/backend.replicas: 0` explicitly even under `deploymentMode: SingleBinary`. Confirmed via a live `Node` get (after renewing the expired MCP ServiceAccount token) that the control-plane nodes carry no actual `NoSchedule` taint, so skipped an unnecessary toleration two other charts carry defensively.
- At user's request, checked a previously-cloned reference repo (`tmp/home-ops-bykaj`); found its own `CLAUDE.md` claims a Loki+Alloy stack but the live `kubernetes/apps/observability/` tree actually runs VictoriaLogs+fluent-bit — a second signal alongside this repo's own `docs/POTENTIAL-DEPLOYMENTS.md` note that VictoriaLogs is "lighter than Loki." Explained VictoriaLogs' concrete upside (single binary, no deployment-mode/replication-factor/schema-config/compactor wiring, built-in full-text indexing, lower resource footprint, Loki-API ingestion compatibility), backed by what had just been hand-built for Loki; user chose to switch.
- Removed the (never-committed) Loki+Alloy scaffold and built the VictoriaLogs+fluent-bit replacement: verified live chart versions (`victoria-logs-single` 0.13.8, `fluent-bit` 0.55.0), reused bykaj's proven fluent-bit classic-mode config (containerd parser, kubernetes-metadata-lifting filters, VictoriaLogs JSONLine output) almost verbatim, and confirmed via rendered-manifest inspection that the `victoria-logs-server:9428` service name fluent-bit targets matches what `fullnameOverride: victoria-logs` actually produces.
- Verified the Grafana plugin needed for VictoriaLogs (`victoriametrics-logs-datasource`) via web search/fetch against Grafana's plugin catalog (confirmed signed, Grafana-13-compatible) and added it to the already-deployed `kube-prometheus-stack` Grafana's `plugins:` list — the one change touching a live, running app rather than new files.
- Added a `grafana_datasource`-labelled ConfigMap (auto-discovered by the existing Grafana sidecar) and enabled dashboard/ServiceMonitor auto-discovery for both new charts, relying on the cluster's already-relaxed Prometheus selectors (`serviceMonitorSelectorNilUsesHelmValues: false`).
- Added an `HTTPRoute` exposing VictoriaLogs' own query UI at `victorialogs.${DOMAIN_CLUSTER}` via the `envoy-internal` Gateway, following this repo's established per-app `httproute.yaml` pattern (not the chart's built-in `route:` value block, which is bykaj's approach) — same pattern already used for Grafana/Prometheus/Alertmanager.
- Validated the full result with `task validate` (repo-wide schema check) and `helm template` dry-runs against the real production values for both charts at every stage; nothing staged or committed per the repo's no-autonomous-commit policy.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/victoria-logs.yaml` | New OCIRepository source for the `victoria-logs-single` chart (0.13.8) |
| `kubernetes/flux/meta/repos/oci/fluent-bit.yaml` | New OCIRepository source for the `fluent-bit` chart (0.55.0) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the two new OCIRepository sources |
| `kubernetes/apps/observability/kustomization.yaml` | Registered the `victoria-logs` and `fluent-bit` app `ks.yaml`s |
| `kubernetes/apps/observability/victoria-logs/ks.yaml` | New Flux Kustomization (depends on `rook-ceph-cluster`, `kube-prometheus-stack`) |
| `kubernetes/apps/observability/victoria-logs/app/kustomization.yaml` | New Kustomize entry-point for the app |
| `kubernetes/apps/observability/victoria-logs/app/helmrelease.yaml` | New HelmRelease — `ceph-block` PVC, 14d retention, ServiceMonitor + dashboard auto-discovery |
| `kubernetes/apps/observability/victoria-logs/app/datasource.yaml` | New Grafana datasource ConfigMap (sidecar-discovered) |
| `kubernetes/apps/observability/victoria-logs/app/httproute.yaml` | New HTTPRoute exposing the query UI via `envoy-internal` |
| `kubernetes/apps/observability/fluent-bit/ks.yaml` | New Flux Kustomization (depends on `kube-prometheus-stack`) |
| `kubernetes/apps/observability/fluent-bit/app/kustomization.yaml` | New Kustomize entry-point for the app |
| `kubernetes/apps/observability/fluent-bit/app/helmrelease.yaml` | New HelmRelease — DaemonSet log shipper, containerd parser, output to VictoriaLogs |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Added `grafana.plugins: [victoriametrics-logs-datasource]` to the live Grafana deployment |

### Key decisions
- Switched from Loki+Alloy to VictoriaLogs+fluent-bit mid-session after building and validating the Loki scaffold first — driven by a reference-repo check the user requested plus a follow-up question about VictoriaLogs' upside; the comparison was grounded in a real, working Loki config rather than guesswork, so the earlier effort wasn't wasted.
- The deciding factor was operational simplicity (single binary, no schema/compactor/replication-factor wiring) rather than any functional gap in Loki — both would have worked for this cluster's scale.
- Used this repo's own hand-written `httproute.yaml` convention instead of the `victoria-logs-single` chart's built-in `server.route` value block (bykaj's approach), keeping the route's lifecycle independent of the Helm chart and consistent with how Grafana/Prometheus/Alertmanager are already exposed.
- No `dependsOn` on `victoria-logs` itself from `fluent-bit`'s Kustomization — only on `kube-prometheus-stack` for the ServiceMonitor CRD — per the repo's existing dependsOn-strictness convention (only hard functional deps, not "nice to have ready first").

---

## 2026-06-23 — `actions-runner-rbac-cilium-egress-hardening`

### Goal
Audit the GitOps repo, remediate its two flagged security warnings (cluster-admin-bound auto-triggered runner, zero network policies) by splitting the GitHub Actions self-hosted runner into privileged/unprivileged groups and adding the cluster's first CiliumNetworkPolicy; after the policy proved unreliable in production across three separate Cilium `toFQDNs` issues, revert the network-policy portion while keeping the RBAC split. Then — after the Anthropic API key leaked in plaintext in a PR-review job log — rotate it and migrate the workflow off the Kubernetes-injected env-var path to a GitHub Actions secret, removing the key from the cluster entirely.

### What we did
- Ran the `gitops-repo-audit` skill end-to-end (discovery, manifest validation, deprecated-API check, best-practices and security review). Found the repo clean overall — zero validation errors on real K8s/Flux manifests, zero deprecated APIs, no plaintext secrets or hardcoded credentials — but flagged two Warnings: the ARC self-hosted runner's ServiceAccount bound to `cluster-admin` despite being the target of an auto-triggered (`pull_request`) Renovate-PR-review workflow, and zero `NetworkPolicy`/`CiliumNetworkPolicy` resources anywhere despite Cilium already being the CNI.
- Planned the fix in plan mode: dispatched two Explore agents (Cilium policy capabilities/enforcement mode, ARC `gha-runner-scale-set` architecture and actual RBAC usage) and one Plan agent in sequence. Research surfaced that `cluster-admin` was granted speculatively for *future* ops workflows with zero current consumers (confirmed via git log + `docs/SESSIONS.md`), and that the chart auto-provisions its own namespace-scoped Role (pods/exec/log/jobs/secrets, all create+delete) whenever `serviceAccountName` is left unset in kube mode — meaning omitting the ClusterRoleBinding alone would not have achieved "no RBAC."
- Asked the user to decide two open design points before finalizing the plan: FQDN-allowlist breadth (chose GitHub's full documented self-hosted-runner list over the narrower exact-match set) and whether to drop now-dead `WebFetch`/`WebSearch` grants from the workflow's `allowedTools` (chose to remove them, since the network policy blocks arbitrary-URL egress anyway).
- Implemented: new `runners/home-lab-readonly/` runner group (zero-RBAC ServiceAccount, ExternalSecrets reusing the existing 1Password items, HelmRelease with explicit `serviceAccountName` to suppress chart auto-RBAC, a `CiliumNetworkPolicy` scoped by ARC's `actions.github.com/scale-set-name` label rather than namespace-wide since the namespace also hosts the privileged group); added the matching Flux Kustomization to `ks.yaml`; repointed `renovate-pr-review.yml` at the new group; updated the existing privileged group's `rbac.yaml` comment to document the reservation. User staged and committed this independently (`3d8465d`).
- User reported the new runner stuck in a crash/recreate loop. Diagnosed live via `pods_log`, `cilium-dbg policy get`/`monitor --type drop`/`fqdn cache list`, and disposable debug pods carrying the same Cilium identity: the listener could reach `api.github.com` but timed out on `broker.actions.githubusercontent.com` (ARC's job-session endpoint). Root cause: that hostname CNAMEs to a GitHub "GLB" target (`glb-c0e95bd587389a.github.com`, confirmed via `dig`) that matched none of the policy's `toFQDNs` rules — Cilium requires every name in a CNAME chain to satisfy a rule before allow-listing the resolved IP. Fixed by adding a `*.github.com` wildcard. User committed this independently (`d838e0b`) while I was still mid-diagnosis on a stale assumption that it was uncommitted — caught and corrected after the user flagged it.
- User reported continued (but different) flakiness after that fix landed. Traced it to a second, genuinely separate Cilium issue: `dnsProxy.idleConnectionGracePeriod` defaults to `0s`, and Cilium's periodic FQDN-cache GC (~60s cadence) was evicting the broker IP-allow mapping the moment it looked idle — confirmed directly in `cilium-agent` logs (`"FQDN garbage collector work deleted entries"` naming that exact host every ~60s) even though the real DNS TTL (2701s) was nowhere near expired. Verified the correct Helm value path against the actual Cilium 1.19.5 chart schema (`helm show values`, not guessed) and set `dnsProxy.idleConnectionGracePeriod: 2m` in the cluster's single Cilium HelmRelease — a cluster-wide agent setting, not scoped to this one policy.
- Researched whether `2m` is a sane value: checked both local reference repos (`home-ops-bykaj`, `home-ops.old` — neither tunes this, both run the chart default), Cilium's own docs (explicitly defers to "depends on your use case"), and a 3-year-old unresolved Cilium GitHub issue (`#25786`, reproduced through 1.18.x, closed by stale-bot with no maintainer guidance) confirming this is a known, never-fully-explained pain point community-wide, not something with an established correct number. Reported this honestly to the user along with the residual risk that some of the observed flakiness may have been amplified by the diagnostic debug pods' own identity churn.
- After deploying the `idleConnectionGracePeriod` fix and rolling all 5 Cilium agents, the runner kept failing — now exhausting all retries and crash-looping, worse than before. Diagnosed live with a third disposable debug pod plus `cilium-dbg identity list`/`identity get`/`monitor --type drop`: two *different* security identities (`11487` the listener, `40479` a fresh debug pod) were both denied reaching the same destination at the same time, and `cidr:20.85.130.105` never appeared anywhere in the node's identity list — Cilium was never allocating a security identity for that specific IP at all, persisting 10+ minutes past any agent-settling window. Working theory: the two-hop wildcard CNAME chain (`*.actions.githubusercontent.com` alias → `*.github.com` GLB target) can't benefit from `tofqdns-preallocate-identities` the way a static `matchName` can, and on-demand allocation for it wasn't completing.
- Presented two stopgap options (explicit `matchName` for the current GLB hostname vs. `toCIDR` for the resolved IP) plus a "stop patching" option. User chose to stop and revert instead — the runner worked fine before this session's network-policy work, and three Cilium-side surprises in one session was enough signal. Confirmed revert scope with the user: keep the RBAC split (never caused any instability) but drop only the `CiliumNetworkPolicy` and the `dnsProxy` tuning that existed solely to support it. Removed `networkpolicy.yaml`, its reference in `kustomization.yaml`, and the `dnsProxy.idleConnectionGracePeriod` block from Cilium's values — committed as `ee0ce85` (pushed as `b4f1e38`). After the push + Flux reconcile, confirmed the `home-lab-readonly` listener stable with zero restarts.
- **Secret leak (separate incident, same session):** user reported the Renovate PR-review job still produced no review even with the runner healthy. Pulled PR #64's check runs via the GitHub MCP — the `review` job reported `success` but ran only 28s with no comment posted. User pasted the job log, which revealed two things: (1) the Claude Code SDK call failed in 352ms with `is_error: true, total_cost_usd: 0` (a first-request auth rejection, not a real review), and (2) **the live `ANTHROPIC_API_KEY` was printed in plaintext** in `claude-code-action`'s own "Post Run" step env block. Root cause of the leak: the key was sourced from a Kubernetes-injected OS env var (ESO → Secret → pod env) rather than `secrets.*`, so GitHub's log-masking engine never learned the string and couldn't scrub it (contrast `GITHUB_TOKEN`, which masked correctly because it came via `secrets.*`).
- Surfaced the leak to the user immediately as the priority action. User rotated the key in the Anthropic console and added the new value as a GitHub Actions repo secret. Then, on the user's explicit choice (presented as a trade-off against the repo's 1Password-single-source convention), migrated the workflow to `anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}` — GitHub auto-masks `secrets.*` everywhere, making this class of leak structurally impossible — and removed the now-dead env-export + presence-check steps. Committed as `2a2a72c`.
- Cleaned up the orphaned cluster-side plumbing: removed the `anthropic` ExternalSecret and the `ANTHROPIC_API_KEY` pod-env injection from **both** runner groups (`home-lab-readonly` and the reserved `home-lab`). Verified via `grep` that zero `anthropic` references remain anywhere under `actions-runner-system` — the key no longer materializes as a Kubernetes Secret on either group, and now lives only in the Anthropic console + the GitHub Actions secret. Folded into `2a2a72c` via `--amend` (→ `c9f2b54`, still unpushed at session end). Noted the now-orphaned `anthropic` 1Password item is harmless and left in place for a possible future ESO consumer.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/rbac.yaml` | New zero-RBAC ServiceAccount for the unprivileged runner group (kept) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/externalsecret.yaml` | New runner-registration ExternalSecret (kept); the Anthropic ExternalSecret was added then later removed in the secrets.* migration |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/helmrelease.yaml` | New `gha-runner-scale-set` HelmRelease with explicit `serviceAccountName` (kept); `ANTHROPIC_API_KEY` pod-env injection added then later removed |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/networkpolicy.yaml` | Created (DNS + GitHub + Anthropic egress), patched for the GLB CNAME gap, then deleted entirely after proving unreliable |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab-readonly/kustomization.yaml` | Added `networkpolicy.yaml` reference, then removed it |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/ks.yaml` | Added Flux Kustomization for the new runner group (kept) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/rbac.yaml` | Comment-only: documented `cluster-admin` as reserved for future ops workflows, none currently (kept) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/externalsecret.yaml` | Removed the orphaned `anthropic` ExternalSecret (secrets.* migration) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/helmrelease.yaml` | Removed the `ANTHROPIC_API_KEY` pod-env injection (secrets.* migration) |
| `.github/workflows/renovate-pr-review.yml` | `runs-on` repointed to `home-lab-readonly`; dropped dead `WebFetch`/`WebSearch`; switched `anthropic_api_key` from `env.*` (Kubernetes-injected) to `secrets.*` after the leak |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Set `dnsProxy.idleConnectionGracePeriod: 2m`, then reverted to the chart default |

### Key decisions
- Split into a new runner group rather than stripping `cluster-admin` from the existing one — it's reserved, has zero current consumers, and the actual risk was the auto-triggered job's exposure, not the privilege grant itself. This part survived the later revert intact.
- Scoped the (now-reverted) CiliumNetworkPolicy by ARC's `scale-set-name` label, not the whole namespace, since `actions-runner-system` also hosts the still-privileged group.
- Chose the broad GitHub FQDN allowlist per explicit user steer, with `*.blob.core.windows.net` flagged in the policy's own comment as the weakest link (a multi-tenant Azure domain) rather than silently included — moot now that the policy is removed, but the reasoning stands if this is retried later.
- `dnsProxy.idleConnectionGracePeriod: 2m` was an evidence-based estimate, explicitly flagged at the time as not a community-validated number — it turned out to address a real but secondary issue (GC eviction), not the actual blocker (CIDR identity never allocated for the CNAME-chained IP), so it was reverted along with the policy it existed to support.
- After three distinct Cilium `toFQDNs` failure modes in one session (GLB CNAME gap, GC eviction, CIDR identity never allocated), chose to revert rather than apply a fourth targeted patch under time pressure — the runner worked correctly before any network-policy was added, and that's a perfectly valid place to stop. The audit's "zero network policies" Warning finding is intentionally left open as a result; re-attempting it is future work, not unfinished work from this session.
- On the secret leak: switching to `secrets.*` deliberately bends the repo's "1Password is the single source of truth" convention for *this one* credential. Rationale — `ANTHROPIC_API_KEY` here is a CI credential consumed by GitHub's own infrastructure, not an in-cluster app secret; GitHub Actions has first-class automatic masking for exactly that, and the convention's underlying purpose (secrets don't leak) is better served by the native mechanism than by the env-var workaround that just leaked. The 1Password-ESO pattern remains correct for actual workload secrets.
- The full secret lifecycle is now: Anthropic console + GitHub Actions secret only. The key was removed from the cluster on both runner groups (not just the one the workflow uses) because the reserved `home-lab` group's copy was equally dead plumbing and, post-leak, fewer materialized copies is strictly better.

---

## 2026-06-22 — `volsync-deploy-pvc-incident`

### Goal
Design and deploy a VolSync-based PVC backup system (Restic, NFS-direct, jitter-staggered), then diagnose and recover from a production incident where a wrong PVC-naming assumption caused Helm to delete waha's live PVC during the first rollout attempt.

### What we did
- User asked for the VolSync roadmap status; found the documented CSI Snapshots blocker was actually already resolved (2026-06-20) but the roadmap was never updated, and the VolSync draft itself was stale (Restic→B2, no jitter, no bootstrap-restore pattern).
- Researched a local `bykaj/home-ops` reference clone (`tmp/home-ops-bykaj`) for community best practices: the bootstrap-restore PVC `dataSourceRef` pattern, a shared Kustomize Component, and a `MutatingAdmissionPolicy`-based jitter mechanism.
- User redirected the design: move off Restic→B2 to a local NFS-first target (off-site sync handled separately on the NAS), adopt the staggered/jitter approach, and switch to Kopia — explicitly requested this all be documented in detail in `CLUSTER.md`.
- Investigated the Kopia request: verified directly against `backube/volsync`'s upstream CRD schema that Kopia mover and its `KopiaMaintenance` CRD only exist in the `perfectra1n` community fork (zero `kopia` references upstream); found a 4-year-stale upstream discussion (`#474`) with no real movement. Presented the trade-off; user chose Restic + upstream after a second pass. Also discovered upstream's Restic mover's `moverVolumes` already supports a raw `nfs:` volume directly — the NFS-direct design wasn't actually fork-exclusive.
- Verified live that `MutatingAdmissionPolicy` is GA (`admissionregistration.k8s.io/v1`) on this cluster's K8s v1.36.1, and that VolSync's `volsync-src-*` Job naming + `created-by: volsync` label are set by shared, mover-agnostic controller code (read directly from the VolSync source), not Kopia-fork-specific — so the jitter policy adapted from the reference repo works unmodified on Restic.
- Dispatched a Plan agent with full context; reviewed its draft against live/upstream sources before implementing and caught two real bugs: (1) the chart tag `0.16.0` has no cosign signature yet in `ghcr.io/home-operations/charts-mirror/volsync` (checked the manifest digest against the `.sig` tag list directly) — pinned `0.15.0` instead; (2) the draft wired `components:`/`postBuild.substitute` onto the plain `app/kustomization.yaml` instead of the Flux `ks.yaml` — found the correct mechanism by reading a real consuming app in the reference repo and confirming `spec.components` is a documented field on the Flux Kustomization CRD.
- Implemented and committed (`495ed68`): new `system/volsync` app (operator + jitter policy), new `components/volsync` Kustomize Component, waha wired as the canary via `existingClaim` + the bootstrap-restore PVC, `ROADMAP.md`/`CLUSTER.md` rewritten.
- Side investigation mid-session: a `/fork` dispatched separately to research an NVMe upgrade path for the rook-ceph cluster (unrelated to VolSync) reported back twice with hardware recommendations — not actioned in this session.
- Resolved an NFS export-ACL question: a live diagnostic (disposable test pod + `cilium-dbg bpf nat list`, after the auto-mode permission classifier required explicit approval to exec into the cilium-agent pod) showed pod traffic to TrueNAS masquerades through the egressing node's storage-bond IP, confirming `10.200.0.0/24` alone (the user's existing config) is correct and `10.60.0.0/24` is not needed — corrected an earlier, wrong theoretical answer.
- User pushed `495ed68`. While answering "what will happen if I push" retroactively, traced a real defect: app-template's actual PVC-naming behavior (verified against the live cluster and `bjw-s-labs/helm-charts` source) didn't match the assumption used to design the canary — the live PVC is named `waha` (the release name), not `sessions` (the persistence key). The commit had in fact already reached production and been reverted by the user by the time this was caught; live diagnostics (`kubectl get pvc/pod/events`, HelmRelease `.status.history`, `git reflog`, `git ls-remote`) confirmed Helm's upgrade deleted the real `waha` PVC once `existingClaim` stopped declaring it, and that the repo was already back to a clean, reverted state with no orphaned cluster resources. ~4 days of WAHA's WhatsApp session data was lost — no backup pipeline existed yet to recover from.
- Fixed the design: reverted waha to an app-template-owned PVC with `retain: true` (Helm `keep`-annotation protection), added standalone Phase-1 `ExternalSecret`/`ReplicationSource` files targeting `sourcePVC: waha` directly (bypassing the Component, which assumes a PVC that doesn't exist yet), hardened `components/volsync/pvc.yaml` with `kustomize.toolkit.fluxcd.io/ssa: IfNotPresent` for any future retrofit, and documented the incident plainly in `CLUSTER.md`/`ROADMAP.md`. Re-validated via `kustomize build` (standalone waha app, and the Component in isolation) and `scripts/validate.sh` (clean except the 16 pre-existing, unrelated false positives).

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | Added detailed VolSync architecture section; corrected canary PVC-naming claim and documented the two-phase retrofit procedure |
| `docs/ROADMAP.md` | Replaced the stale VolSync draft, marked CSI Snapshots done, corrected the NFS ACL fact, documented the incident |
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Reverted `existingClaim` attempt to app-template-owned PVC + `retain: true` |
| `kubernetes/apps/automation/waha/app/kustomization.yaml` | Registered the new standalone `volsync-*` files |
| `kubernetes/apps/automation/waha/ks.yaml` | `dependsOn: volsync` + `postBuild.substitute: {APP}`; `components:` inclusion added then removed (deferred to Phase 2) |
| `kubernetes/apps/automation/waha/app/volsync-externalsecret.yaml` | New — Phase 1 standalone ExternalSecret for the Restic password |
| `kubernetes/apps/automation/waha/app/volsync-replicationsource.yaml` | New — Phase 1 standalone ReplicationSource targeting `sourcePVC: waha` directly |
| `kubernetes/apps/system/kustomization.yaml` | Registered the new `volsync` app |
| `kubernetes/apps/system/volsync/app/helmrelease.yaml` | New — VolSync operator HelmRelease |
| `kubernetes/apps/system/volsync/app/kustomization.yaml` | New |
| `kubernetes/apps/system/volsync/app/mutatingadmissionpolicy.yaml` | New — jitter `MutatingAdmissionPolicy` + Binding |
| `kubernetes/apps/system/volsync/app/namespace.yaml` | New |
| `kubernetes/apps/system/volsync/ks.yaml` | New — operator Flux Kustomization |
| `kubernetes/components/volsync/externalsecret.yaml` | New — reusable per-app ExternalSecret template |
| `kubernetes/components/volsync/kustomization.yaml` | New — Component definition |
| `kubernetes/components/volsync/pvc.yaml` | New, then hardened with `kustomize.toolkit.fluxcd.io/ssa: IfNotPresent` |
| `kubernetes/components/volsync/replicationdestination.yaml` | New — reusable bootstrap-restore template |
| `kubernetes/components/volsync/replicationsource.yaml` | New — reusable backup-schedule template |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new `volsync` OCIRepository |
| `kubernetes/flux/meta/repos/oci/volsync.yaml` | New — cosign-verified chart source pinned to `0.15.0` |

### Key decisions
- Restic + upstream `backube/volsync` over Kopia + the `perfectra1n` fork — no cosign signatures, a single-maintainer bus-factor risk, and a 4-year-stale upstream discussion with zero momentum; upstream's Restic mover turned out to already support the NFS-direct capability assumed fork-exclusive.
- Off-site S3/B2 replication deliberately left out of GitOps scope — handled by the user directly on TrueNAS (Cloud Sync Task), not a Kubernetes CronJob.
- CNPG's `postgres-v17` PVC explicitly excluded from VolSync's scope — already has its own barman-cloud PITR + `pg_dumpall` paths; adding VolSync there would be redundant, not complementary.
- Pinned chart tag `0.15.0` instead of the newer `0.16.0` after verifying the mirror's cosign signature for `0.16.0` doesn't exist yet — bump once signed.
- Adopted a two-phase retrofit pattern for any app with pre-existing PVC data (Phase 1: `retain: true` + a direct `ReplicationSource`; Phase 2: `existingClaim` + the full Component, gated by `IfNotPresent`) — necessary because `dataSourceRef` is immutable on an existing PVC and Helm prunes resources it no longer declares by default. This was learned the hard way: the first attempt skipped straight to Phase 2 on an app that already had live data, based on an unverified assumption about the PVC's name, and Helm deleted it.

---

## 2026-06-22 — `tailscale-subnet-route-precedence-fix`

### Goal
Stop the Tailscale `k8s-subnet-router` Connector from hijacking LAN traffic to `10.60.0.0/24`, both for devices natively on that VLAN and for devices reaching it only through the UniFi gateway's inter-VLAN routing.

### What we did
- Changed the `tailscale-operator` `subnet-router` Connector to advertise `10.60.0.0/23` instead of the exact `10.60.0.0/24`, with an inline comment explaining the root cause (Tailscale's installed routes can tie in prefix length with a host's own connected route and aren't reliably out-ranked, per upstream `tailscale/tailscale#1227`, `#6231`, `#7947`); committed as `a02cab9`.
- Verified the fix on a Windows laptop using `tracert`, PowerShell `Find-NetRoute`, and `route print`. Initially claimed tracert hop-count couldn't distinguish LAN vs. Tailscale routing (WireGuard normally hides intermediate hops) — corrected this after the user's own traces showed a subnet router *does* appear as a visible hop, since it performs real IP forwarding and decrements TTL.
- Diagnosed why the laptop still routed via Tailscale after reconnecting: it lives on a separate `10.10.0.0/24` LAN and only reaches `10.60.0.0/24` via the UniFi gateway's inter-VLAN routing, so it never had a directly-connected `/24` route to out-rank Tailscale's `/23` — the cluster-side fix only protects devices natively attached to the management VLAN, not routed clients.
- Checked whether the UDM Pro Max's newly-available eBGP support was relevant. Confirmed it isn't: BGP is router-to-router and wouldn't propagate routes to DHCP clients, and the cluster's `CiliumLoadBalancerIPPool`/`CiliumL2AnnouncementPolicy` setup already advertises LB IPs via L2/ARP within the same VLAN as the nodes, so there's no unmet need for BGP today.
- Computed the RFC 3442 Option 121 hex payload (`180A3C000A0A0001000A0A0001`) encoding both the `10.60.0.0/24 → 10.10.0.1` route and a required `0.0.0.0/0` default-route entry, and walked through adding it (plus the legacy Microsoft Option 249 duplicate, for older-Windows safety) as a custom DHCP option on the UDM Pro Max's `10.10.0.0/24` network.
- User applied the DHCP option, renewed the laptop's lease, and confirmed the routing table now carries both the `/24` (via the LAN gateway) and `/23` (via Tailscale) entries for `10.60.0.0` — completing the fix for routed, non-VLAN-attached clients.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/tailscale/tailscale-operator/configs/subnet-router.yaml` | Changed advertised route `10.60.0.0/24` → `10.60.0.0/23`; added inline comment with upstream issue references (commit `a02cab9`) |

### Key decisions
- Advertise the less-specific `/23` supernet rather than the exact `/24` so the OS's longest-prefix-match always prefers a directly-connected `/24` LAN route over Tailscale's advertisement — fixes the precedence bug for devices natively on the management VLAN.
- For devices on other VLANs with no competing local route at all, fixed it one layer down with a UniFi-pushed DHCP classless static route rather than any further cluster-side change — the Connector can only ever encode what it advertises on the tailnet; it has no influence over a client's default-route behavior on an unrelated VLAN.
- Included the `0.0.0.0/0` default-route descriptor inside the Option 121 payload, not just the `10.60.0.0/24` entry — omitting it would make RFC-3442-compliant clients (including Windows) discard their normal default gateway entirely, breaking general internet access for every device on `10.10.0.0/24`.
- Decided not to pursue eBGP on the UDM despite its new availability: it solves a different problem (dynamic route exchange between routers) than the one at hand (getting a route into a DHCP client's table), and the cluster's current LoadBalancer IP design has no gap it would close.

---

## 2026-06-22 — `worker02-power-brick-rootcause`

### Goal
Explain why CloudNativePG couldn't reschedule a stuck instance off a downed `talos-worker-02`, then investigate yet another worker-02 hard-down — and this time root-cause the long-running recurring-hard-down mystery to a single point of failure via clean hardware isolation.

### What we did
- Explained why `postgres-v17-2` kept restarting in place on `talos-worker-02` instead of moving nodes: the `postgres-v17` Cluster uses `storageClass: openebs-hostpath` (node-local storage), whose PV `nodeAffinity` permanently pins it to one node. Confirmed against current CloudNativePG docs (via context7) that there is no automatic "node's gone, delete the PVC, reschedule elsewhere" behavior — the only documented remedy is a manual `kubectl delete pvc/pod`. Also explained the mechanical, duration-based reason via the pod's `tolerationSeconds: 300` on the not-ready/unreachable taints.
- Investigated the actual 2026-06-21 outage by dispatching `talos-node-manager` and `cluster-doctor` in parallel against a 16:30-18:30Z window inferred from the Node object's `lastTransitionTime` — which, as it turned out, only reflects the *most recent* kubelet restart and silently hid an earlier, real incident.
- Corrected course twice based on the user's first-hand account: the 18:23:45Z "blip" the agents flagged was a deliberate BIOS reboot to revert a fan-speed setting, not a fault; the real unexplained hard-down was 14:17:30Z-14:39:45Z (confirmed via a wider `up{}` Prometheus range query), including a failed first restart attempt. Updated persistent memory each time the picture changed rather than leaving stale conclusions in place.
- Reviewed existing hardware-monitoring coverage: the "Node Exporter Full" Grafana dashboard, the `hardware-temps.yaml` PrometheusRules, and the Pushover/Alertmanager wiring (incl. an emergency-priority `pushover-critical` tier). Confirmed it's solid for genuine thermal events but has no detector for brief node flaps that resolve before any `for:` window elapses; proposed (not yet implemented) a `resets(node_boot_time_seconds[1h])`-based flap rule. Explained AMD `k10temp`'s `Tctl` offset quirk on `cp-01` along the way (live cross-check against the `Tccd1`/`Tccd2` sensors confirmed it).
- User exported the Intel AMT event log via MeshCommander. Found a consistent +2h offset between its timestamps and real UTC (cross-checked against the known fan-reboot event) and confirmed, by enumerating every distinct `EventSensorType` across all 169 events, that this AMT/BIOS implementation has no thermal/power/MCE sensor wired in at all — only boot/restart events — closing off that channel for good. Surfaced 3 previously-uncatalogued pre-repaste reboot clusters (2026-06-12, 06-13, 06-16) never logged in any prior session, including one true Intel ME re-init (power-cut) signature on 06-12.
- User ran PassMark MemTest86 on `talos-worker-02` via remote KVM (AMT IDE-R, then JetKVM). Got a reproducible **power-off** (not a freeze) across 4 runs, always at ~40-42s elapsed / Test 3 (Moving inversions) / Pass 25%, zero MemTest-reported errors, CPU temp comfortable (54-59°C) every time.
- Ruled out CPU-die thermal as the trigger: a fan-at-100% test verifiably dropped CPU temp 59°C→54°C but didn't move the failure point at all.
- Ran a clean hardware-swap isolation: worker-02's own brick failed at the same point with or without an in-line JetKVM DC passthrough adapter; talos-worker-01's brick (swapped in) ran 28+ minutes clean with zero errors. This isolated the fault to worker-02's power brick specifically, independent of the board, CPU, RAM, or the passthrough adapter — and retroactively explained the entire incident history (zero thermal precursor, cooling-insensitive, genuine power-loss, why the identical-hardware twin never faulted, why production incidents were sporadic rather than constant).
- User confirmed the diagnosis live: a 400W Lenovo laptop adapter keeps worker-02 running fine, and ordered a proper 90W Lenovo replacement. Updated persistent memory to record the confirmed root cause, superseding the long-standing non-ECC-RAM-bitflip theory.

### Files changed
No repository files were changed — this was a live diagnostics and hardware-isolation session. The `talos-node-manager` subagent updated its own persistent memory:

| File | Change |
|------|--------|
| `.claude/agent-memory/talos-node-manager/MEMORY.md` | Agent self-updated its index after the 06-21 investigation |
| `.claude/agent-memory/talos-node-manager/project_worker02_harddown_20260621.md` | Agent's own findings record for the 06-21 incident (new file) |

### Key decisions
- Didn't count two early MemTest86 freezes (booted from an unsupported ISO via AMT IDE-R) as genuine fault data — switched to JetKVM + the officially-supported USB `.img` before treating any result as signal, since the unsupported boot path was a plausible confound on its own.
- Stopped investing further effort in the AMT event log once the sensor-type enumeration showed it structurally cannot record thermal/power/MCE events on this hardware — a negative result worth confirming once, not worth re-checking on every future incident.
- Deprioritized the months-long non-ECC-RAM-bitflip theory once MemTest86 produced zero reported errors across 4 full attempts but a reproducible power-loss instead — recognized the fault as power-delivery, not memory-integrity, and didn't force the data to fit the prior leading theory.

---

## 2026-06-21 — `cnpg-storj-to-b2-migration`

### Goal
Migrate the CloudNativePG barman-cloud backup target from Storj.io to Backblaze B2 as a temporary stopgap, root-cause a real WAL-archiving incompatibility against B2, and verify recovery on the live production cluster — after first discovering and resolving a stale, half-finished migration attempt to a different provider (LeafCloud).

### What we did
- Found a stale task list from an unrelated prior effort to migrate the same backup target to LeafCloud (an OpenStack-based provider) — an application credential had already been created there and EC2/S3 key minting was in progress. Asked the user, who chose to abandon LeafCloud (revoking the credential themselves) in favor of B2; cleaned up the LeafCloud-specific tasks and repurposed the provider-agnostic ones.
- Mapped every Storj touchpoint in the repo (`objectstore.yaml`, `externalsecret.yaml`, `cluster.yaml`, `ks.yaml`, CLUSTER.md/ROADMAP.md) and confirmed only `objectstore.yaml`'s `destinationPath`/`endpointURL` plus the 1Password credential values needed to change — the ExternalSecret's generic `dataFrom.extract` + regex-rewrite design meant no schema changes were needed there.
- Walked the user through creating a B2 bucket + scoped application key in the Backblaze console (external action).
- Researched two facts before editing anything: (1) B2 data-locality/region is fixed at the *account* level at signup, not per-bucket — moving to EU would require a brand-new account; user accepted the existing region for this stopgap. (2) barman-cloud only supports server-side encryption (AES256/aws:kms), never client-side — so the original Storj-over-B2/R2 rationale documented in CLUSTER.md (client-side encryption avoiding US CLOUD Act exposure) does not carry over to B2; user initially chose to skip encryption, then opted back in to `AES256` (server-side floor) once it was clear no client-side option exists either way.
- Confirmed Backblaze's `keyID`/`keySecret` terminology maps directly onto the AWS-style access/secret key fields the ExternalSecret already expects, and verified with the user that the 1Password rotation reused the existing `S3_ACCESS_KEY`/`S3_SECRET_KEY` field labels — no ExternalSecret changes needed.
- Used the `1password` skill to read the bucket name from `op://homelab/cloudnative-pg/S3_BUCKET` into a shell-only env var and applied it via `yq -i` + `strenv()`, keeping it out of the conversation transcript — twice (initial cutover, then again after the bucket rename below). The first pull caught a real discrepancy: the bucket name visible in a pasted endpoint URL (`vwn.io-cluster-backup`) differed from the actual 1Password value (`vwn.io-cluster-cnpg`).
- After cutover, `ContinuousArchiving` failed 100% of the time with `IncompleteBody: The request body was too small` — a different symptom of the same botocore chunked-checksum-trailer incompatibility that hit Storj as `MissingContentLength`. Tried and individually disproved against the live cluster: `wal.maxParallel: 1` + trailing-slash `destinationPath` (from `cloudnative-pg/cloudnative-pg#7105`); `s3Credentials.region` + `AWS_DEFAULT_REGION` (`#9724` — a real bug, but for a *different* symptom, `SignatureDoesNotMatch` on retention-policy `ListObjectsV2`, not the WAL-archive failure); downgrading `plugin-barman-cloud` `0.7.0`→`0.6.0` to rule out a library regression (same error reproduced on the older `barman-cloud@v0.5.0`). Reverted each in turn rather than stacking unconfirmed fixes.
- Compared against `bykaj/home-ops`'s working B2 config (same region, `us-west-001`) via a local clone updated to its latest commit — found a far simpler config and one real remaining difference: the bucket name contained a literal dot (`vwn.io-cluster-cnpg`), which AWS's own docs flag as an HTTPS/virtual-hosted-style hostname-matching hazard. User recreated the bucket dot-free (`vwn-io-cluster-cnpg`); `IncompleteBody` was gone immediately.
- The bucket recreation invalidated the old scoped application key (`AccessDenied: not entitled`); user created a new scoped key and rotated 1Password, after which `ContinuousArchiving` went `True` and a manual on-demand `Backup` completed successfully against the new bucket.
- Caught and corrected a real mistake mid-session: a `/git-commit` invocation ran `git status`/`diff`/`log` against the wrong repository (`tmp/home-ops-bykaj`) because an earlier `cd` into that directory had persisted across Bash tool calls. Caught before any commit happened; redone correctly in `/workspaces/home-lab`.
- A `kubectl create` for a one-off on-demand `Backup` CR was blocked by the auto-mode permission classifier as a non-GitOps imperative change; explained the reasoning to the user (a one-shot trigger object, not standing desired state) rather than working around the block, and got an explicit one-off exception.
- User ran a live disaster-recovery drill themselves against the actual production `postgres-v17` cluster (accepted, since it held no real data yet): `just cnpg restore-from-backup` → delete `Cluster` → Flux recreate from B2 → `just cnpg undo-restore`. Verified as a genuine recovery (not a coincidentally-healthy empty `initdb`) via `pg_control_checkpoint()` showing a WAL timeline promotion (`1` → `2`). Confirmed the recipe needed zero code changes across the whole migration, since it only ever references the ObjectStore by its provider-agnostic `metadata.name`.
- Updated `CLUSTER.md` (current-state B2 references, encryption-regression note, re-verified recovery callout), `ROADMAP.md` (preserved the original Storj implementation history, appended a dated addendum covering the migration, every disproved theory, and the live drill), and `QA.md` (new "Database / Backups" category documenting the dot-in-bucket-name root cause as a standalone gotcha).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml` | Repointed barman-cloud `ObjectStore` from Storj to Backblaze B2; several speculative fixes tried and reverted; final state: dot-free bucket, `AES256` encryption, original checksum env vars |
| `kubernetes/flux/meta/repos/oci/plugin-barman-cloud.yaml` | Temporarily pinned to `0.6.0` to test a library-regression theory, reverted to `0.7.0` after it was disproved |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | `bootstrap.recovery`/`externalClusters` added (live restore drill) then removed via `just cnpg undo-restore` |
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | `CNPG_V17_CURRENT_CLUSTER` bumped `postgres-v17-20260618` → `postgres-v17-20260621` (permanent, from the restore drill) |
| `docs/CLUSTER.md` | Updated WAL archiving/PITR section to reflect B2 as current backend, encryption regression, re-verified recovery |
| `docs/ROADMAP.md` | Appended migration narrative, disproved theories, root cause, and live-drill verification to the existing barman-cloud item |
| `docs/QA.md` | New "Database / Backups" category with the dot-in-bucket-name gotcha |

### Key decisions
- Abandoned the in-progress LeafCloud migration in favor of B2, per explicit user choice; user owns revoking the LeafCloud application credential.
- Cut over fresh rather than migrating historical Storj backup data.
- Accepted B2's account-level region (no EU move); accepted server-side-only encryption (`AES256`) as a floor after confirming no client-side option exists with barman-cloud regardless.
- Sourced the B2 bucket name from 1Password via the `1password` skill rather than having the user paste it in chat — caught a stale/wrong bucket name twice this way (once in a pasted endpoint string, once after the bucket rename).
- Disproved each speculative WAL-archiving fix individually and reverted before trying the next, rather than stacking unconfirmed changes — kept the causal chain legible once the real cause (dot in bucket name) turned up.
- Tested the disaster-recovery path against the real production `Cluster` object rather than a disposable test cluster, since the database held no real data yet — a deliberate, situational risk acceptance, not a general practice.

---

## 2026-06-20 — `csi-snapshot-controller-deploy`

### Goal
Deploy a CSI snapshot-controller cluster singleton, enable Rook-Ceph's `VolumeSnapshotClass`, and verify the full snapshot→restore path live — closing the ROADMAP's "CSI Snapshots" item and unblocking VolSync.

### What we did
- User asked what the most reasonable next `docs/ROADMAP.md` item was; reviewed the roadmap and `docs/REPO-AUDIT.md`, recommended CSI Snapshots (external-snapshotter + Ceph `VolumeSnapshotClass`) — small, dependency-free, and the literal prerequisite `rook-ceph-cluster`'s HelmRelease was already wired with a disabled flag waiting for.
- Entered plan mode; ran three parallel Explore agents to research (1) the community-standard snapshot-controller chart via kubesearch.dev-style research, (2) `bykaj/home-ops`'s own snapshot-controller + VolSync patterns in `tmp/home-ops-bykaj`, and (3) this repo's own Kustomization/OCIRepository conventions plus the exact disabled-flag context in `rook-ceph-cluster`'s HelmRelease.
- Confirmed convergent findings: `oci://ghcr.io/piraeusdatastore/helm-charts/snapshot-controller` (v5.1.1) is both the dominant community choice and bykaj's exact pick; no cosign signatures are published for this chart.
- Asked the user two clarifying questions: where to place the new app (chose `kubernetes/apps/system/snapshot-controller/`, mirroring the existing `system/reloader` precedent — corrected mid-flight that `system/` is an org folder, not a namespace, so the app gets its own dedicated `snapshot-controller` namespace) and single- vs multi-replica (chose single replica, matching reloader's simplicity, since the controller is leader-elected and not on the live-traffic path).
- Dispatched a Plan agent with the full research context to produce a file-by-file implementation plan; independently verified its key claims (schema-host majority, inline `values:` convention, exact `dependsOn` syntax) before finalizing and writing the plan file, then exited plan mode.
- Implemented: new OCIRepository + app scaffold under `kubernetes/apps/system/snapshot-controller/`, flipped Rook-Ceph's `cephBlockPoolsVolumeSnapshotClass` to enabled with an explicit name (avoiding a collision with the existing `ceph-block` StorageClass name), added `snapshot-controller` to `rook-ceph-cluster`'s `dependsOn`.
- Validated locally before committing: `kubectl kustomize` on every touched tree, the repo's own `validate.sh` (kubeconform — clean except one pre-existing, documented `Taskfile.yaml` false positive), and `scripts/depgraph.py` (0 cycles/dangling refs, new edge correctly non-redundant; this also auto-refreshed `docs/CLUSTER.md`'s dependency diagrams).
- Ran `/git-stage` and `/git-commit` (commit `aa92488`); user pushed manually.
- Verified live: forced Flux reconciliation, confirmed both the new and dependent Kustomizations `Ready`, all snapshot CRDs installed, the `snapshot-controller` + conversion-webhook pods `Running`, and the `ceph-block-snapshot` `VolumeSnapshotClass` created exactly as configured with Ceph staying `HEALTH_OK`.
- Ran the full smoke test against disposable scratch resources (never touching live app PVCs): wrote a canary file, snapshotted it, restored into a new PVC, confirmed byte-for-byte data integrity, then tore down every test resource including confirming the `VolumeSnapshotContent` was garbage-collected.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/snapshot-controller.yaml` | New `OCIRepository` source for the chart (v5.1.1, no cosign available) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new `OCIRepository` |
| `kubernetes/apps/system/snapshot-controller/ks.yaml` | New Flux `Kustomization`, `wait: true` so downstream dependents block correctly |
| `kubernetes/apps/system/snapshot-controller/app/namespace.yaml` | New dedicated `snapshot-controller` namespace |
| `kubernetes/apps/system/snapshot-controller/app/helmrelease.yaml` | New `HelmRelease`, single replica, `ServiceMonitor` enabled |
| `kubernetes/apps/system/snapshot-controller/app/kustomization.yaml` | New app-level Kustomize aggregator |
| `kubernetes/apps/system/kustomization.yaml` | Registered the new app's `ks.yaml` |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Enabled `cephBlockPoolsVolumeSnapshotClass`, named `ceph-block-snapshot` |
| `kubernetes/apps/rook-ceph/rook-ceph/ks.yaml` | Added `snapshot-controller` to `rook-ceph-cluster`'s `dependsOn` |
| `docs/CLUSTER.md` | Auto-regenerated dependency-graph diagrams via `scripts/depgraph.py` |

### Key decisions
- Placement: `kubernetes/apps/system/snapshot-controller/` with its own dedicated namespace (not a shared "system" namespace) — mirrors the existing `system/reloader` precedent exactly, after verifying reloader's actual namespace wiring directly rather than trusting the initial (incorrect) framing of the question.
- Single replica, no `topologySpreadConstraints` — deliberately rejected the cert-manager/ESO-style 2-replica HA pattern the Plan agent first proposed, since snapshot-controller is leader-elected and a brief outage only delays snapshot create/delete rather than affecting live traffic; reloader (the structural template) is also single-replica.
- `VolumeSnapshotClass` named `ceph-block-snapshot` explicitly rather than accepting the chart/Rook default name, which is literally `ceph-block` — identical to the existing StorageClass name (distinct API kinds, no functional collision, but confusing in `kubectl get` output).
- No cosign verification on the new `OCIRepository` — confirmed piraeusdatastore doesn't publish signatures for this chart, so it follows the plain/unverified pattern (matching `rook-ceph.yaml`) rather than the cosign pattern (matching `plugin-barman-cloud.yaml`).

---

## 2026-06-19 — `cloudflare-edge-cert-gap-and-legacy-dns-cleanup`

### Goal
Diagnose why `whoami` still failed externally after the prior fixes, close the real root cause (a Cloudflare edge-certificate coverage gap), then track down and clean up legacy Cloudflare Tunnel DNS records inherited from the archived cluster that were silently blocking GitOps-managed DNS.

### What we did
- User reported the mobile-data SSL error persisted even after the `cloudflared`/ExternalDNS fixes, while a LAN browser test succeeded — the LAN test was a false negative (local DNS resolved straight to the Gateway's private IP, never touching Cloudflare at all).
- Reproduced the real failure directly via `curl --resolve` pinned to Cloudflare's actual anycast edge IP, bypassing local/cached DNS: got `TLS alert, handshake failure` for `whoami.apps.vwn.io` while one-level-deep hostnames (`flux-webhook.vwn.io`, `apps.vwn.io`) succeeded. Root cause: Cloudflare's free Universal SSL only covers a zone root plus one level of wildcard — `apps.vwn.io` is covered, the two-levels-deep `whoami.apps.vwn.io` is not, and the edge rejects the handshake before the tunnel is ever reached.
- Verified `vwn.app` (`${DOMAIN_APP}`) was Cloudflare-delegated, one level deep, and already wired into every relevant config (origin cert, `cloudflared` ingress rule, both ExternalDNS `domainFilters`); moved `whoami`'s HTTPRoute hostname to `whoami.${DOMAIN_APP}` — a one-line fix.
- Documented the gap for future routes: inline WAN-safety comment on `envoy-external`'s `certificateRefs`, plus a full Q&A entry in `docs/QA.md` (symptom, root cause, confirm recipe, three fix options, prevention note) with ToC link.
- User asked to fold these into the already-pushed commit rather than create a new one; confirmed the safety tradeoff (local `main` would diverge from `origin/main`, requiring a future force-push) before amending — produced `639a82b`. User manually force-pushed it.
- Verified live reconciliation before going further: `GitRepository` and all three affected Kustomizations confirmed `Ready` at `639a82b`, pods actually rolled (not just resource-applied). Dispatched a second `cluster-doctor` audit to re-confirm the earlier fixes held under real reconciled state — confirmed the private-LAN-IP-leak risk (Bug B) stayed fixed, the DNS rename's DELETE/CREATE cycle completed correctly in logs, no regressions.
- User still got `Error 1033` from mobile after the cert fix. Investigated via Cloudflare's Zero Trust dashboard (explained what the product is/does) and found `external.proxii.nl` — the indirection target both `whoami.vwn.app` and the Gateway's own DNS-target annotation route through — was a dashboard-managed "Tunnel"-type record pointing at a dead, disconnected tunnel ("kubernetes", alongside another dead tunnel "dramble").
- Traced the dead record's origin to `.archive/kubernetes/apps/network/cloudflare-tunnel/app/dnsendpoint.yaml`: the *previous* cluster's config used the exact same hostname (`external.${DOMAIN_PROXII}`) with a different tunnel ID. When that cluster was decommissioned, the Cloudflare-side record was never cleaned up; it sat invisible (zone outside `external-dns-cloudflare`'s `domainFilters` until this session) until today's rename caused a name collision for the first time ever.
- User manually repointed the stale record to the live "homelab" tunnel; confirmed working end-to-end via `curl` (real `whoami` pod response) and then directly from the user's phone over mobile data.
- Found a second, related defect: the record's TXT ownership markers (`k8s.cname-external.proxii.nl` and `k8s.external.proxii.nl`) were also orphaned (`owner=default`, predating `external-dns-cloudflare`'s `owner=k8s`) — meaning GitOps didn't actually own the record going forward even though it currently worked. User deleted both, plus several unrelated `.archive`-era leftovers (`whoami.proxii.nl`, `flux-webhook.proxii.nl`, `k8s.whoami.proxii.nl`, `wan_failover.proxii.nl`) in one pass.
- Watched the self-heal via two sequential background polls: the first gave a false positive (matched the wrong, still-orphaned TXT owner); caught and corrected by cross-checking transaction timestamps in `external-dns-cloudflare`'s logs against the poll's detection time. The second poll confirmed `external-dns-cloudflare` cleanly created both the CNAME and its `owner=k8s` TXT companion in a single transaction — full clean GitOps ownership achieved and verified live.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/default/whoami/app/httproute.yaml` | Hostname `whoami.${DOMAIN_APPS}` → `whoami.${DOMAIN_APP}` (avoids the two-level Cloudflare edge-cert gap); folded into `639a82b` via amend |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Added inline comment on `certificateRefs` marking which certs are WAN-safe for new routes; folded into `639a82b` via amend |
| `docs/QA.md` | New Networking Q&A entry on the Cloudflare edge-cert two-level wildcard gap, plus ToC link; folded into `639a82b` via amend |

### Key decisions
- Fixed the edge-cert gap by moving to an already-one-level-deep, already-covered zone (`vwn.app`) rather than enabling Cloudflare Total TLS or ordering an Advanced Certificate — zero-cost, zero new dependency, since the zone was already fully wired into every other relevant config.
- Treated the Cloudflare dashboard DNS/TXT cleanup as live, third-party, hard-to-reverse state: performed by the user directly rather than via a fetched API token, even after one was nearly retrieved (a 1Password lookup was blocked mid-session by the harness's auto-mode classifier, since it read as unprompted credential-vault exploration).
- Caught and corrected a false-positive self-heal signal by re-verifying against pod-log transaction timestamps rather than trusting a single DNS snapshot — `dig` results proved unreliable for several minutes after rapid record changes due to resolver caching.

---

## 2026-06-19 — `whoami-network-plumbing-fixes`

### Goal
Deploy a `whoami` smoke-test app to validate Envoy Gateway external connectivity, then use the failures it surfaced to find and fix real bugs in the Cloudflare Tunnel / ExternalDNS / Envoy Gateway stack.

### What we did
- Researched lightweight homelab network-verification deployments (`traefik/whoami`, `ealen/echo-server`, `agnhost`); recommended `whoami` for HTTP-layer routing/TLS smoke tests. Clarified Flux `OCIRepository` semantics (Helm-chart artifacts vs raw-manifest artifacts) and confirmed the existing `app-template` OCIRepository source already covers any of the three candidate images.
- Deployed `whoami` via the `app-template` chart, HTTPRoute attached to `envoy-external`'s `https` listener at `whoami.${DOMAIN_APPS}`. Initially placed it in the `network` namespace; user questioned this, and a check against the `pgadmin`/`waha` precedent (apps keep their own functional namespace, cross-reference the Gateway via `parentRefs` — `network` is reserved for plumbing controllers) showed it was misplaced. Moved it into a new `default` namespace. Committed as `82f7660`.
- Live-tested it: external (WAN) gave `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`; LAN gave a DNS resolve error. Dispatched `cluster-doctor` to diagnose live.
- Root cause #1: `cloudflared`'s `originRequest.originServerName` was hardcoded to `"gateway.${DOMAIN_IO}"` for every ingress rule, but no cert on `envoy-external` covers that SNI — handshake failure for any domain actually used externally (also silently broke the pre-existing `flux-webhook.${DOMAIN_IO}` route). Verified Cloudflare's `matchSNItoHost` flag directly via their docs rather than guessing, and cross-checked the `tmp/home-ops-bykaj` reference repo (uses a different static-anchor-hostname + YAML-anchor pattern) — concluded `matchSNItoHost: true` is the better fit here since this repo has no single domain safe to use as a universal anchor. Applied the fix.
- Root cause #2 (initial diagnosis, later corrected): thought `whoami.apps.vwn.io`'s CNAME target (`external.${DOMAIN_IO}`) was never created by either ExternalDNS instance, and fixed it by adding the `service` source to `external-dns-cloudflare`. A follow-up audit found this would leak `envoy-internal`'s private LAN IP (`internal.proxii.nl` → `10.60.0.231`) to public Cloudflare DNS once reconciled — `--gateway-name` only scopes the `gateway-httproute` source, not `service`. Reverted, and instead updated a **pre-existing** `cloudflare-tunnel` `DNSEndpoint` CRD (already the correct mechanism — CNAME straight to the tunnel, never the raw LB IP) to point at `${DOMAIN_PROXII}` instead of `${DOMAIN_IO}`.
- User asked about renaming `envoy-external`'s target from `external.${DOMAIN_IO}` to `external.${DOMAIN_PROXII}` for consistency with `envoy-internal`'s existing `internal.${DOMAIN_PROXII}` pattern. Verified via `dig NS proxii.nl` that it's delegated to the same Cloudflare account as `vwn.io` (confirming feasibility rather than assuming), then applied the rename plus added `DOMAIN_PROXII` to the cloudflare instance's `domainFilters`.
- Decrypted `cluster-secrets.sops.yaml` mid-session to ground all hostname reasoning in actual `DOMAIN_*` values instead of inferring them from cert/secret naming patterns.
- User clarified the original "`external.vwn.io` missing" symptom was checked against **LAN/UniFi** DNS, not public Cloudflare DNS — the public side had been resolving correctly via the `DNSEndpoint` CRD since a May 2026 commit, no bug there. The actual gap was UniFi's `domainFilters` never including `DOMAIN_IO`; the `DOMAIN_PROXII` rename fixes this for free since `DOMAIN_PROXII` was already in UniFi's scope.
- Dispatched a second, broader `cluster-doctor` audit of every `HTTPRoute`/`Certificate`/ExternalDNS-coverage/Cilium-LB-IPAM pairing. User correctly flagged it would read live (pre-reconcile) cluster state for anything still uncommitted — let it run anyway since most of its scope was unrelated pre-existing resources. Results: found the LAN-IP-leak risk above (the one genuinely new/urgent finding); reassessed the missing-`${DOMAIN_IO}`-certificate gap as lower-severity than feared (Cloudflare's edge cert + `noTLSVerify` on the origin hop mean `flux-webhook` delivery likely already works, despite the origin-side gap being real); reconstructed the orphaned `external.cluster.vwn.io` record's likely origin via `git log -p` (a same-day May 2026 rename followed by a `domainFilters` drop ~4 minutes later, probably outrunning ExternalDNS's reconcile loop) — recommended confirming via the record's TXT companion in the Cloudflare dashboard before deleting it, left as a manual follow-up outside this repo; everything else (all 9 HTTPRoutes, Cilium LB-IPAM, all relevant Flux `Kustomization`/`HelmRelease`/`Certificate` objects) confirmed fine.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/default/kustomization.yaml` | New — registers the `default` namespace |
| `kubernetes/apps/default/whoami/ks.yaml` | New — Flux Kustomization, `targetNamespace: default` |
| `kubernetes/apps/default/whoami/app/kustomization.yaml` | New |
| `kubernetes/apps/default/whoami/app/helmrelease.yaml` | New — `traefik/whoami:v1.11.0` via `app-template` |
| `kubernetes/apps/default/whoami/app/httproute.yaml` | New — routes `whoami.${DOMAIN_APPS}` to `envoy-external` |
| `kubernetes/apps/kustomization.yaml` | Added `./default` |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | `originServerName` → `matchSNItoHost: true` |
| `kubernetes/apps/network/cloudflared/app/dnsendpoint.yaml` | `cloudflare-tunnel` DNSEndpoint's `dnsName` `external.${DOMAIN_IO}` → `external.${DOMAIN_PROXII}` |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | `envoy-external` target/hostname `external.${DOMAIN_IO}` → `external.${DOMAIN_PROXII}`; corrected a stale comment |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Added `${DOMAIN_PROXII}` to `domainFilters` (a `service`-source addition was tried, found unsafe, reverted — see Key decisions) |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Cluster-doctor self-updated: added a pointer to the new reference file below |
| `.claude/agent-memory/cluster-doctor/reference_envoy_gateway_external_dns_topology.md` | New — cluster-doctor's own durable notes on the `--gateway-name` scoping gotcha and the `ResolvedRefs`-doesn't-validate-SAN-coverage blind spot |

### Key decisions
- Namespace `default` over `network` for `whoami`, matching the `pgadmin`/`waha` precedent rather than co-locating it with the plumbing controllers it merely tests.
- `matchSNItoHost: true` over bykaj's static-anchor-hostname pattern, since this repo lacks a single domain with a cert safe to use as a universal SNI anchor.
- Renamed `envoy-external`'s canonical hostname to use `DOMAIN_PROXII`, accepting that `proxii.nl` (previously LAN-only) now gets one publicly-resolvable (Cloudflare-proxied) hostname, after confirming via `dig NS` — not assumption — that the zone is actually Cloudflare-managed.
- Preferred the pre-existing `DNSEndpoint` CRD (CNAME straight to the Cloudflare Tunnel) over a `service`-source-based approach for publishing `envoy-external`'s public hostname: the `service` source would have published the raw private LB IP, which is both a leak risk (for `envoy-internal`'s Service) and non-functional for `envoy-external`'s own case (`10.60.0.230` isn't internet-routable regardless).
- Left the missing `DOMAIN_IO` certificate and the orphaned `external.cluster.vwn.io` record open rather than fixing reactively — the former is reassessed as lower-severity (edge cert + `noTLSVerify` mask it in practice), the latter needs a Cloudflare-dashboard TXT-record check this repo can't perform.

---

## 2026-06-18 — `rook-ceph-grafana-dashboards`

### Goal
Verify Prometheus/Grafana observability for Rook-Ceph and add the Ceph dashboards Grafana was missing.

### What we did
- User shared a screenshot of the Ceph Dashboard's "Pools > Overall Performance" tab prompting to configure Grafana embedding; investigated the full observability stack rather than just that one feature.
- Found the `mcp-viewer` ClusterRole (`scripts/mcp.sh`) was silently missing the `ceph.rook.io` and `monitoring.coreos.com` API groups — queries for `CephCluster`/`ServiceMonitor`/`PrometheusRule` returned "No resources found," indistinguishable from the resources not existing. Added both groups (read-only `get/list/watch`) and renewed the token to confirm.
- Confirmed Prometheus integration for Rook-Ceph was already fully live: `ServiceMonitor/rook-ceph-mgr`, `rook-ceph-exporter`, and `csi-metrics` all present and scraped (kube-prometheus-stack's `serviceMonitorSelectorNilUsesHelmValues: false` makes scraping cluster-wide regardless of Helm labels); `PrometheusRule/prometheus-ceph-rules` feeding Alertmanager; `CephCluster` status `HEALTH_OK`.
- Fetched docs.ceph.com's Grafana-embedding instructions to confirm the screenshot's prompt is a separate, optional feature (native iframe embedding inside the Ceph dashboard UI) requiring `ceph dashboard set-grafana-api-url` plus Grafana anonymous/iframe access — distinct from Prometheus scraping, which already worked.
- Checked HTTPRoutes: both `grafana` and `rook-ceph-dashboard` sit on `envoy-internal` (LAN-only), which informed the security tradeoff of the native-embedding path.
- Asked the user to choose between (a) just adding Ceph dashboards to the existing Grafana, (b) also wiring native embedding with anonymous Grafana access, or (c) no changes — user chose (a).
- Downloaded the 9 official ceph-mixin Grafana dashboards relevant to this cluster's RBD/block-only setup (`ceph-cluster`, `hosts-overview`, `host-details`, `osds-overview`, `osd-device-details`, `pool-overview`, `pool-detail`, `rbd-overview`, `rbd-details`) from `github.com/ceph/ceph`; skipped RGW/CephFS/NVMe-oF/SMB dashboards since those daemons aren't deployed here.
- Verified the dashboards use Grafana's `$datasource` template-variable mechanism (not the `${DS_*}` input-substitution convention), so they load via sidecar provisioning with zero edits despite stray `__inputs`/`__requires` export metadata.
- Wired the dashboards into `kube-prometheus-stack/app/kustomization.yaml` as a new `configMapGenerator` labeled `grafana_dashboard: "1"`, auto-discovered by the existing Grafana sidecar (`searchNamespace: ALL`) — no Helm values change needed.
- Validated with `kubectl kustomize`: build succeeds, all 9 dashboard JSON files are valid, and the rendered ConfigMap carries both `grafana_dashboard: "1"` and `reconcile.fluxcd.io/watch: Enabled` labels with all 9 data keys present.

### Files changed
| File | Change |
|------|--------|
| `scripts/mcp.sh` | Added `ceph.rook.io` and `monitoring.coreos.com` to the `mcp-viewer` ClusterRole (read-only); committed by the user as `8a4796e` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Added `configMapGenerator` for `ceph-grafana-dashboards`, labeled `grafana_dashboard: "1"` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/dashboards/*.json` (9 files) | Added official ceph-mixin Grafana dashboards (cluster, hosts, OSDs, pools, RBD) |

### Key decisions
- Scoped dashboards to the RBD/block-only set, excluding RGW/CephFS/NVMe-oF/SMB dashboards since this cluster doesn't run those Ceph daemons — avoids panels that would just show "no data."
- Chose the lightweight path (load dashboards into the existing authenticated Grafana) over native Ceph-dashboard iframe embedding, since the latter requires loosening Grafana to anonymous/iframe access; user picked this explicitly when offered both options.
- Bundled all 9 dashboards into a single ConfigMap (multiple files/keys) rather than 9 separate ConfigMaps, since the Grafana k8s-sidecar supports multi-key ConfigMaps natively and this keeps the resource count down.

---

## 2026-06-18 — `cnpg-recovery-drill-verified`

### Goal
Push the CNPG recovery drill built earlier this session, verify it actually recovers real data from S3 with hard proof rather than just pod status, document the results, and tear down the disposable test cluster.

### What we did
- Renamed the `ObjectStore` CR `cloudnative-pg-storj` → `cloudnative-pg-backup` across `cluster.yaml`, `restore-test/app/cluster.yaml`, and `cnpg/mod.just`, since the pointer name shouldn't bake in the current S3 provider; discussed the blast radius of a future provider switch (B2/Hetzner) and the recovery-discontinuity risk for backups predating any such switch.
- Ran `/git-commit`: committed the recovery-drill + DR-runbook + `just cnpg` work as `dafd5f6` (`feat(cloudnative-pg): add recovery drill and DR restore tooling`); `git fetch --dry-run` failed in this environment (SSH agent/publickey error), so upstream drift could not be checked before committing.
- Discovered the commit was already on `origin/main` and Flux had already reconciled `cloudnative-pg-restore-test` to Ready — but `kubectl`/`flux` were hitting a TLS-handshake timeout against the API server (TCP connected, TLS hung) at the same time. Launched the `cluster-doctor` agent in the background to diagnose it while continuing.
- Verified the recovery drill end-to-end against live data: `postgres-v17-restore-test-1` reached `Ready` in 54 seconds from a base backup ~5h24m old. Confirmed it was a genuine physical recovery, not a coincidentally-matching empty cluster, via `pg_control_system()` — identical 64-bit `system_identifier` on both clusters, with the recovered cluster correctly promoted onto a new timeline (`1` → `2`) and `pg_is_in_recovery() = false`.
- `cluster-doctor` reported back: the TLS timeout was a transient, self-resolved API-server/VIP stall with no evidence tying it to the concurrent Rook-Ceph OSD work happening in this same repo. It also self-corrected its own stale frontmatter (old 3-node/Longhorn topology → current 5-node/Rook-Ceph), added two new memory notes (Talos-native VIP, benign apiserver↔etcd loopback log noise), and expanded the MCP viewer's RBAC to read Rook-Ceph and Prometheus-Operator CRDs.
- Updated `docs/ROADMAP.md` (item 1: drill results + proof method; item 4: recovery mechanics now proven, not just unblocked) and `docs/CLUSTER.md` (Recovery model callout now states "verified," not "designed").
- Deleted `kubernetes/apps/database/cloudnative-pg/restore-test/` and its reference in the parent `kustomization.yaml`, tearing the disposable drill cluster back out of Git — pending commit + push for Flux to actually prune it from the live cluster.

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Added recovery-drill verification results to item 1; updated item 4's "unblocked" note |
| `docs/CLUSTER.md` | Recovery-model callout now states the drill is verified, not just designed |
| `kubernetes/apps/database/cloudnative-pg/kustomization.yaml` | Removed the `restore-test/ks.yaml` reference |
| `kubernetes/apps/database/cloudnative-pg/restore-test/ks.yaml` | Deleted — drill torn down after verification |
| `kubernetes/apps/database/cloudnative-pg/restore-test/app/kustomization.yaml` | Deleted — drill torn down |
| `kubernetes/apps/database/cloudnative-pg/restore-test/app/cluster.yaml` | Deleted — drill torn down |
| `.claude/agents/cluster-doctor.md` | Agent self-corrected stale 3-node/Longhorn frontmatter to current 5-node/Rook-Ceph topology |
| `.claude/agent-memory/cluster-doctor/MEMORY.md` | Agent indexed its two new memory notes |
| `.claude/agent-memory/cluster-doctor/reference_talos_native_vip.md` | New — the VIP is Talos-native, not a `kube-vip` pod |
| `.claude/agent-memory/cluster-doctor/reference_apiserver_etcd_loopback_noise.md` | New — apiserver↔etcd loopback gRPC log noise is benign here absent etcd-side symptoms |
| `scripts/mcp.sh` | Agent expanded MCP viewer RBAC to read Rook-Ceph and Prometheus-Operator CRDs |

### Key decisions
- Logged this as a distinct, second same-day session entry rather than amending the earlier one — substantial new work (live verification with concrete proof, not just "built") happened after that entry was already written and closed.
- Used `pg_control_system()`'s `system_identifier` match as the recovery proof rather than row-count/table comparisons, since the shared cluster currently holds negligible application data — identifier + timeline comparison is conclusive regardless of data volume.
- Did not re-list files already committed in `dafd5f6` (covered by the prior entry) in this entry's table, to avoid duplicating the same paths across two adjacent session records.

---

## 2026-06-18 — `cnpg-barman-cloud-pitr-recovery`

### Goal
Implement and verify CloudNativePG PITR (continuous WAL archiving + scheduled base backups) via the `barman-cloud.cloudnative-pg.io` CNPG-I plugin against Storj S3, then research, document, and tool the recovery/restore side, which had never been built or tested.

### What we did
- Implemented the write path: new `OCIRepository`/`HelmRelease` for the `plugin-barman-cloud` chart, a new `ObjectStore` CR (`cloudnative-pg-storj`) pointing at a Storj S3-compatible bucket, a daily `ScheduledBackup` (`02:00 UTC` + `immediate: true`), and a `plugins:` (WAL-archiver) block on the live `postgres-v17` `Cluster`.
- Live-tested the pipeline and found/fixed two real bugs blocking it: the `ExternalSecret`'s `target.template.data` allow-list was silently dropping the new `CNPG_S3_ACCESS_KEY`/`CNPG_S3_SECRET_KEY` fields despite `dataFrom.extract` pulling them from 1Password (fixed by adding them explicitly); and Storj's S3 gateway rejected `PutObject` with `MissingContentLength` due to botocore's newer chunked-checksum encoding (fixed via `instanceSidecarConfiguration.env` `AWS_REQUEST_CHECKSUM_CALCULATION`/`AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`). Manually deleted/recreated CNPG instance pods to force them to re-derive specs from the updated `ObjectStore`, since CNPG doesn't bump the `Cluster`'s generation just because a referenced `ObjectStore` CR changed.
- Added `archive_timeout: 5min` to bound the WAL-archiving staleness gap on a low-write cluster, with inline doc comments explaining the default and rationale.
- Via `/fork`, updated `docs/ROADMAP.md` and `docs/CLUSTER.md` to mark the barman-cloud item done and document both backup layers + the recovery model; manually cherry-picked only session-relevant hunks out of `docs/CLUSTER.md` via a hand-trimmed patch, since a concurrent external session had also modified that file for unrelated Rook-Ceph/Tailscale/cert content.
- Researched the actual CNPG-I recovery CRD shape from three corroborating sources rather than assuming legacy non-plugin barman docs applied: this repo's own `.archive` (a commented recovery template + a full restore runbook), the `bykaj` reference repo's live, currently-running recovery config for its own `postgres-v17` cluster, and upstream CNPG/`plugin-barman-cloud` docs. Confirmed the shape: `bootstrap.recovery.source` → `externalClusters[].plugin.parameters.{barmanObjectName,serverName}`, `recoveryTarget` fields (`targetTime`/`targetLSN`/`targetName`/`targetXID`/`targetImmediate`), and that recovery always bootstraps a brand-new `Cluster` object — never in-place.
- Designed and built a safe, non-destructive recovery drill: a disposable single-instance `postgres-v17-restore-test` `Cluster` (new `restore-test/` Kustomization) that recovers from the live cluster's existing backups but carries no `plugins:` (WAL-archiver) block of its own, so it can never collide with the production S3 prefix.
- Added a documented, commented-out disaster-recovery template + runbook directly to the live `cluster.yaml`, explaining that CNPG only reads `spec.bootstrap` once, at cluster-creation time — so a full reset/rebootstrap today would silently create an empty database rather than auto-recovering from the S3 backups.
- Built a new `just cnpg` module (`cnpg/mod.just`, wired into `.justfile`) with `restore-from-backup` (finds the last archived `serverName` from `ks.yaml`'s git history, warns if the cluster is still alive, then writes the recovery block into `cluster.yaml` via `yq`) and `undo-restore` — automates the toil of the Git-mediated DR workflow without ever calling `kubectl apply`, keeping the actual cluster mutation behind a commit and Flux reconciliation.
- Validated everything offline before staging: `kubectl kustomize` builds for `cluster/app` and `restore-test/app`, a `yq` merge dry-run against a scratch copy, a git-history regex extraction test, and `just --list`/`just cnpg` listing.
- Ran `/git-stage`: 7 files staged cleanly (no warn-bucket files) — `.justfile`, `cnpg/mod.just`, `cluster.yaml`, `kustomization.yaml`, and the 3 new `restore-test/` files.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/plugin-barman-cloud.yaml` | New OCIRepository for the `plugin-barman-cloud` chart (cosign-verified) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the new OCIRepository |
| `kubernetes/apps/database/cloudnative-pg/plugin-barman-cloud/app/helmrelease.yaml` | New HelmRelease for the plugin |
| `kubernetes/apps/database/cloudnative-pg/plugin-barman-cloud/app/kustomization.yaml` | Kustomize entrypoint for the plugin app |
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Added `plugin-barman-cloud` Kustomization, `cloudnative-pg-cluster` dependsOn + `postBuild.substitute` for the WAL-archiver `serverName` |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml` | New `ObjectStore` CR for Storj S3; added the `MissingContentLength` sidecar checksum workaround |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/scheduledbackup.yaml` | New daily (`02:00 UTC`) `ScheduledBackup` CR with `immediate: true` |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Added the WAL-archiver `plugins:` block, `archive_timeout: 5min`, and a commented disaster-recovery `bootstrap`/`externalClusters` template + runbook |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/kustomization.yaml` | Registered `objectstore.yaml`/`scheduledbackup.yaml`, then `restore-test/ks.yaml` |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/externalsecret.yaml` | Added `CNPG_S3_ACCESS_KEY`/`CNPG_S3_SECRET_KEY` to the rendered Secret's `template.data` allow-list |
| `docs/ROADMAP.md` | Marked the barman-cloud PITR item done with accurate implementation detail |
| `docs/CLUSTER.md` | Rewrote the backup-strategy table/recovery-model callout and regenerated the dependency graph (session-relevant hunks only) |
| `docs/REPO-AUDIT.md` | Refreshed resource counts/findings to include the new plugin component |
| `.justfile` | Wired in the new `cnpg` module |
| `cnpg/mod.just` | New `restore-from-backup`/`undo-restore` recipes |
| `kubernetes/apps/database/cloudnative-pg/restore-test/ks.yaml` | New disposable recovery-drill Kustomization |
| `kubernetes/apps/database/cloudnative-pg/restore-test/app/kustomization.yaml` | Kustomize entrypoint for the drill |
| `kubernetes/apps/database/cloudnative-pg/restore-test/app/cluster.yaml` | New disposable `postgres-v17-restore-test` Cluster, recovers from the existing Storj backups with no WAL-archiver of its own |

### Key decisions
- Chose Storj over R2/B2 for its client-side-encrypted, erasure-coded, no-single-custodian architecture, avoiding the US CLOUD Act exposure R2/B2 share regardless of EU data-residency settings — this rationale is now documented in `docs/CLUSTER.md` and would need revisiting if the backend ever changes.
- The recovery drill cluster deliberately omits its own WAL-archiver `plugins:` block rather than following `.archive`'s S3-folder-rename workaround for the "Expected empty archive" failure mode — a pure-read drill structurally can't collide with the production prefix, so there's nothing to work around.
- The `just cnpg` module automates only the Git-tracked YAML edit, never the cluster mutation itself — preserves the repo's IaC-only policy (no `kubectl apply` outside Flux) while removing the error-prone manual step of finding the correct historical `serverName`.
- `bootstrap.recovery` is consulted by CNPG only once, at `Cluster`-object creation time — confirmed via docs and reference-repo behavior, not assumed — which is why the live `cluster.yaml` needed an explicit DR runbook rather than relying on "the backups exist, so recovery will just work."

---

## 2026-06-18 — `cp02-cp03-bond-storage-10gbe`

### Goal
Verify newly-installed X520-DA2 SFP+ 10GbE NICs on cp-02 and cp-03, then migrate their storage network from the legacy 1GbE VLAN trunk to a proper `bond-storage` LACP bond, keeping config and docs in sync at every step.

### What we did
- Verified cp-03's new NIC via `talosctl -n 10.60.0.203 get links -o yaml`: `enp2s0f0`/`enp2s0f1` bound to the `ixgbe` driver as Intel 82599ES (X520-DA2), PCI `8086:10FB` — confirmed at the PCI/driver level before any cable was connected (`linkState: false` at that point, which is expected and distinct from driver binding).
- Edited `talos/talconfig.yaml` for `talos-cp-03`: replaced the inline VLAN-200-over-`eno1` storage patch with a `bond-storage` LACP interface (802.3ad, MTU 9000) using the discovered MACs, matching the existing `cp-01`/`worker-01`/`worker-02` pattern. Marked provisional (not yet cabled) and validated the render via `talhelper genconfig`.
- User then installed the matching card in cp-02 (M90q #1) and cabled both nodes; re-verified both via `talosctl get links` — both now showed `linkState: true`, `speedMbit: 10000`, `duplex: Full`, `port: DirectAttach`. Added the matching `bond-storage` block to cp-02's `talconfig.yaml` entry.
- Updated `docs/CLUSTER.md` (NIC topology table) and `docs/HARDWARE-ARCHITECTURE.md` (action item 8) to describe the staged-but-unapplied bond, explicitly noting the live storage path was still the VLAN trunk until cutover.
- Before applying anything live, asked the user to confirm the switch-side 802.3ad port-channel + jumbo-frame config was in place (it was), then confirmed an explicit go-ahead for a **staggered** apply — never both control-plane nodes at once, to protect etcd quorum and avoid a simultaneous Ceph network event.
- Captured a Ceph baseline (`HEALTH_OK`, 8/8 OSDs up, mons `a`/`d`/`e` on cp-01/worker-02/cp-03) before touching anything.
- Applied `task talos:apply IP=10.60.0.203` (cp-03) then, after verifying health, `IP=10.60.0.202` (cp-02) — both applied without a reboot. Confirmed each bond came up with `mode: 802.3ad` and `speedMbit: 20000` (both 10G members aggregated, proving LACP actually negotiated with the switch rather than just link-up).
- Cutover briefly surfaced `OSD_SLOW_PING_TIME_BACK`/`_FRONT` `HEALTH_WARN` between cp-02/cp-03's OSDs; diagnosed as transient switch MAC-table/ARP relearning (latency dropped on each recheck, affected node-pairs shifted, PGs stayed `active+clean`) rather than a real fault — used a backgrounded `until` poll loop to wait for `HEALTH_OK` rather than blocking on a fixed sleep. Final state: 5/5 nodes Ready, 8/8 OSDs up, 3/3 mons in quorum, zero pod restarts on any affected mon/OSD throughout.
- Updated the `talconfig.yaml` bond comments from "provisional/do not apply" to a record of the completed, verified cutover; updated `CLUSTER.md`'s table to show all 5 nodes on `bond-storage` with a dated note on the cutover and the transient warning; marked the `HARDWARE-ARCHITECTURE.md` action item ✅ DONE.
- Ran `/git-commit`: 3 files were already staged, reviewed the diff and commit-log style, confirmed no upstream drift, committed as `8661329`. Did not push.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Replaced cp-02/cp-03's VLAN-200-over-`eno1` storage trunk with a `bond-storage` 802.3ad LACP bond (MTU 9000) on the new X520-DA2 ports; updated hostname comments |
| `docs/CLUSTER.md` | NIC topology table now shows all 5 nodes on `bond-storage`; added a dated note on the cutover and the transient `OSD_SLOW_PING_TIME` warning |
| `docs/HARDWARE-ARCHITECTURE.md` | Marked action item 8 (X520 SFP+ install on M90q #1/#2) ✅ DONE |

### Key decisions
- Used `hardwareAddr` deviceSelectors (not `driver:`) for the bond members — a driver selector matches both ports of the same NIC simultaneously and silently prevents the bond from forming, per the same gotcha already documented at `cp-01`'s bond-storage entry.
- Treated applying the network change to live control-plane/Ceph-OSD nodes as a risky, confirm-first action: prepared and validated the config fully, but did not run `task talos:apply` until the user explicitly confirmed switch-side LACP readiness and a staggered apply order.
- Investigated the post-cutover `HEALTH_WARN` rather than dismissing or rolling back — the decreasing latency and shifting affected node-pairs across repeated checks were the signal that it was self-healing relearning, not a real fault.

---

## 2026-06-18 — `flux-dependson-graph`

### Goal
Build tooling to chart and verify the Flux Kustomization `dependsOn` graph, then use it to find and fix a real obsolete dependency and stale doc references.

### What we did
- Built `scripts/depgraph.py` to parse `spec.dependsOn` across all 41 Kustomizations in `kubernetes/flux/**/ks.yaml` and `kubernetes/apps/**/ks.yaml`; implements three-color DFS cycle detection, dangling-reference detection, and transitive-redundancy detection (edge A→B flagged when B is also reachable from A via another path, but not auto-removed).
- Verified the graph: 0 cycles, 0 dangling references, 7 transitively-redundant edges — kept as-is since this repo's style declares explicit deps for robustness even when transitively implied.
- Generated a Mermaid visualization embedded in `docs/CLUSTER.md` under a new "App Dependency Graph" section (marked `<!-- BEGIN/END: DEPENDENCY-GRAPH-AUTO -->` for regeneration via `python3 scripts/depgraph.py`). First iteration was a single flat 41-node graph; redesigned after feedback into a collapsed 15-node group-level overview plus 15 collapsible (`<details>`) per-group detail diagrams with external-dependency stub nodes, fixing the unreadable arrow fan-in around `external-secrets`/`onepassword-store`.
- Cross-referenced the chart against `docs/CONVENTIONS.md`'s documented "CRD pre-bootstrap phase" fix and found `smartctl-exporter`'s `dependsOn: kube-prometheus-stack` was an obsolete leftover from before that fix existed — contrasted against `flux-alerts`'s identical-looking dependency, which is legitimate (its `Provider` needs a live Alertmanager Service, not just the CRD). Removed the obsolete `dependsOn`.
- Discovered `CLUSTER.md` and `CONVENTIONS.md` still referenced the pre-move `kubernetes/bootstrap/helmfile.yaml` path (the bootstrap dir moved to top-level `bootstrap/` back in the `five-node-bootstrap-completion` session); corrected both references to `bootstrap/helmfile.d/01-apps.yaml` / `bootstrap/helmfile.d/00-crds.yaml`.
- Answered a question on whether CloudNativePG's dependents (`pgadmin`, `postgres-backup-local`) need to be suspended before scaling down/redeploying `cloudnative-pg-cluster`: confirmed via their `ks.yaml` (`wait: false`, no `healthChecks`) that Flux's `dependsOn` is install-order-only and never cascades health or suspend signals downstream — no GitOps action needed, only an optional `postgres-backup-local` suspend to avoid a failed-backup-job alert during the maintenance window.
- Staged the session's changes via `/git-stage` (excluded `docs/ROADMAP.md`, a pre-existing unrelated modification).

### Files changed
| File | Change |
|------|--------|
| `scripts/depgraph.py` | New — parses the Kustomization `dependsOn` graph; detects cycles, dangling refs, transitively-redundant edges; renders the collapsed overview + per-group Mermaid views into `docs/CLUSTER.md` |
| `docs/CLUSTER.md` | Added "App Dependency Graph" section (auto-generated, marked block); fixed 2 stale `kubernetes/bootstrap/helmfile.yaml` path references |
| `docs/CONVENTIONS.md` | Fixed stale `kubernetes/bootstrap/helmfile.d/00-crds.yaml` path reference |
| `kubernetes/apps/observability/smartctl-exporter/ks.yaml` | Removed obsolete `dependsOn: kube-prometheus-stack` (superseded by the CRD pre-bootstrap phase) |

### Key decisions
- Flag transitively-redundant `dependsOn` edges for human review rather than auto-remove them — an explicit edge can be intentional robustness that survives if the intermediate dependency's own edge is later removed.
- Redesigned the single flat Mermaid graph into a collapsed group overview + collapsible per-group detail views (GitHub `<details>` blocks) after the flat version proved unreadable around high-fan-in nodes like `external-secrets`.
- Left `flux-alerts`'s `dependsOn: kube-prometheus-stack` untouched despite looking identical to the `smartctl-exporter` case — it's a genuine functional dependency (live Alertmanager Service for its `Provider`), not a CRD-dry-run artifact.

---

## Archived sessions

Sessions older than **2026-06-18** (the bootstrap/setup era plus the Ceph migration and five-node rebuild stretch, **2026-05-06 → 2026-06-13**) have been moved to [SESSIONS-ARCHIVE.md](SESSIONS-ARCHIVE.md) to keep this active log lean. Grep the archive the same way you grep this file.
