# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

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

## 2026-06-13 — `five-node-bootstrap-completion`

### Goal
Complete the 5-node cluster bootstrap by fixing talconfig.yaml for cp-01/cp-03, correcting Rook OSD assignments, and resolving bootstrap pipeline issues encountered during the first full `just bootstrap` run.

### What we did
- **Fixed `talos/talconfig.yaml` for cp-01 and cp-03** — added `serial: "50026B7686F8B787"` to cp-01's installDiskSelector to prevent collision with cp-02 (both have Kingston NV3 1TB as boot disk); filled in `hardwareAddr: "88:a4:c2:cc:ce:ac"` and `model: "WD PC SN740 SDDQNQD-256G-1001"` for cp-03 via maintenance-mode `talosctl get LinkStatus` and disk enumeration; confirmed WD SN740 SDDQNQD is 2230 form factor in WLAN slot, proving M90q WLAN slot is PCIe/NVMe-capable.
- **Fixed `talos/mod.just` default recipe** — `just talos` ran the module's default recipe which called `just --list`, but that spawned a child process that walked up to the root justfile and listed its recipes instead of the module's. Fixed with `--justfile {{ source_file() }}` so the module lists its own recipes.
- **Corrected Rook-Ceph OSD assignments in helmrelease** — removed stale `talos-worker-02` entry (M920q #2's Kingston NV3 1TB is its boot disk, not an OSD); corrected `talos-worker-01` from `nvme-KINGSTON_SNV3S1000G_50026B7686F8B787` (MS-A2's boot disk serial — wrong) to `nvme-CT2000P310SSD8_252450B1A33B` (M920q #1's actual P310 2TB OSD); added `talos-cp-03` with T500 2TB `254053487747`.
- **Updated `docs/HARDWARE-ARCHITECTURE.md`** — confirmed cp-03 WD SN740 2230 form factor in WLAN slot; updated MS-A2 drive inventory (AirDisk physically removed, Phison E15T model string `YSR256GHLCA1-E5C-2` confirmed); marked open decisions as done.
- **Bootstrapped 5-node cluster** — etcd reached 3-member quorum (cp-01 leader, cp-02/cp-03 joined as learners then graduated); all 5 nodes joined Kubernetes; kube-apiserver/scheduler/controller-manager running on all 3 CPs.
- **Ran remaining bootstrap stages manually** — cluster was past `check-maintenance` so `just bootstrap` would abort; ran `just bootstrap namespaces → resources → crds → apps` individually.
- **Fixed bootstrap `resources` stage (two separate issues)** — (1) `op inject` placed the multi-line age key inline in YAML; `# created:` comment after `: ` became a YAML comment making the value null. Fixed by updating 1Password to store bare `AGE-SECRET-KEY-1…` at new path `op://homelab/sops/SOPS_PRIVATE_KEY`. (2) `op inject`'s "secret provisioning" API reported the 1Password credentials item as deleted/archived despite `op read` succeeding — a known `op inject` quirk for Document-type items. Rewrote `resources` recipe to use `kubectl create secret --from-literal + op read` directly; bypasses `op inject` entirely and handles multi-line/JSON values correctly.
- **Moved `helmfile.d/` from `kubernetes/bootstrap/` to `bootstrap/`** — aligns with bykaj's repo structure where all bootstrap tooling lives at repo root under `bootstrap/`; updated values paths from `../../apps/` to `../../kubernetes/apps/`.
- **Adopted bykaj's `values.yaml.gotmpl` pattern** — created `bootstrap/helmfile.d/templates/values.yaml.gotmpl` that uses `readFile (printf "../../../kubernetes/apps/%s/%s/app/helm/values.yaml" .Release.Namespace .Release.Name)` to derive the values path from release context; updated `01-apps.yaml` so all releases use `./templates/values.yaml.gotmpl` instead of hard-coded per-release paths. Validated with `helmfile template --quiet` — all 6 charts rendered correctly.
- **Flux fully reconciling** — 30+ Kustomizations `True` at `refs/heads/main@sha1:6ed5461`; `kube-prometheus-stack` in progress (large chart, normal).

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Added serial to cp-01 installDiskSelector; filled cp-03 MAC address and disk model |
| `talos/mod.just` | Fixed default recipe: `just --list --justfile {{ source_file() }}` |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Corrected OSD nodes: added cp-03 T500 2TB, fixed worker-01 to P310 2TB, removed worker-02 |
| `docs/HARDWARE-ARCHITECTURE.md` | cp-03 WD SN740 WLAN slot confirmed; AirDisk removed from inventory; Phison model string added; open decisions closed |
| `bootstrap/mod.just` | `resources` recipe replaced `op inject` template with `kubectl create secret + op read`; fixed helmfile path |
| `bootstrap/resources.yaml.j2` | Updated sops op:// path to `op://homelab/sops/SOPS_PRIVATE_KEY`; added `\|` block scalars |
| `bootstrap/helmfile.d/00-crds.yaml` | Moved from `kubernetes/bootstrap/helmfile.d/` |
| `bootstrap/helmfile.d/01-apps.yaml` | Moved + `../../kubernetes/apps/` paths + all releases use `./templates/values.yaml.gotmpl` |
| `bootstrap/helmfile.d/templates/values.yaml.gotmpl` | Created: derives `helm/values.yaml` path from `.Release.Namespace/.Release.Name` |
| `kubernetes/bootstrap/helmfile.d/00-crds.yaml` | Deleted (moved to `bootstrap/helmfile.d/`) |
| `kubernetes/bootstrap/helmfile.d/01-apps.yaml` | Deleted (moved to `bootstrap/helmfile.d/`) |

### Key decisions
- **`op read` over `op inject` for bootstrap secrets** — `op inject`'s secret provisioning API reported the 1Password credentials item as deleted/archived while `op read` succeeded (known quirk for Document-type items). `kubectl create secret --from-literal` with `op read` is more robust and handles multi-line/JSON values without YAML injection hazards.
- **`readFile`-based gotmpl over bykaj's `spec.values`-based gotmpl** — our HelmReleases use `valuesFrom: ConfigMap` rather than inline `spec.values`; reading `helm/values.yaml` directly preserves our existing structure while providing the same "single template for all releases" ergonomic benefit.
- **Moved helmfile.d to `bootstrap/` not `kubernetes/bootstrap/`** — aligns with bykaj's structure; bootstrap tooling (mod.just, resources.yaml.j2, helmfile.d) lives under `bootstrap/` at repo root, separate from the GitOps-managed `kubernetes/` tree.

---

## 2026-06-13 — `just-bootstrap-talos-config-improvements`

### Goal
Migrate the bootstrap phase from go-task to a `just` module pipeline, add a `talos/mod.just` for day-2 operations, and improve Talos machine config patches with security and reliability features identified by comparing against the bykaj reference implementation.

### What we did
- **Compared home-lab vs bykaj bootstrap workflows** — bykaj uses `just` modules throughout (`bootstrap/mod.just`, `talos/mod.just`) with `gum` logging and `minijinja-cli` templating; our repo used go-task for everything including bootstrap orchestration. Identified that bykaj doesn't use talhelper (uses Jinja2 + `talosctl machineconfig patch`); kept talhelper for our hardware complexity and Renovate version tracking.
- **Created `bootstrap/mod.just`** — 11-stage pipeline: `gensecret → genconfig → wipe-osds → apply-talos → bootstrap-k8s → kubeconfig → wait → namespaces → resources → crds → apps`. Delegates complex Talos bash to `task talos:*` rather than rewriting 400+ lines of nmap/disk-fingerprint logic. Added `|| { just log fatal ... }` error handling to `resources`, `crds`, and `apps` stages.
- **Created `bootstrap/resources.yaml.j2`** — single declarative secret template for all 3 bootstrap secrets (sops-age, onepassword-connect-secrets, flux-github-app) rendered via `minijinja-cli | op inject`. Secrets never touch disk; `op://` references resolved in the pipe.
- **Created `.justfile`** — root module loader: `mod bootstrap "bootstrap"`, `mod talos "talos"`, plus private `log` (gum) and `template` (minijinja-cli + op inject) helpers.
- **Created `.minijinja.toml`** — minijinja-cli config (autoescape none, env vars enabled, trim/lstrip blocks).
- **Updated `.mise.toml`** — added `just = "1.52.0"`, `gum = "0.17.0"`, `"aqua:mitsuhiko/minijinja" = "2.20.0"` (aqua backend required — not in mise native registry); added `[env]` block for `JUST_UNSTABLE = "1"` and `MINIJINJA_CONFIG_FILE`.
- **Deleted `.taskfiles/bootstrap/Taskfile.yaml`** and removed its include from `Taskfile.yaml`; bootstrap orchestration fully replaced by `bootstrap/mod.just`.
- **Rewrote `docs/CLUSTER.md` bootstrap runbook** — Phase 0-4 condensed to Phase 0-2; all `task bootstrap:*` references replaced with `just bootstrap *`; stages table added.
- **Created `talos/mod.just`** — day-2 operations surfaced under `just talos *`: `reset-cluster` (delegates to `task talos:reset` which chains wait+wipe), `reset-node`, `reboot-node`, `shutdown-node`, `upgrade-node`, `health`. Wired into `.justfile` as `mod talos "talos"`.
- **Fixed two bugs in `gensecret` stage** — (1) `talhelper gensecret -c talos/talconfig.yaml` failed: `-c` is not a valid flag for `gensecret` (only for `genconfig`). (2) `talos/talsecret.sops.yaml` path failed because module recipes run with CWD = module directory (`bootstrap/`), not repo root — fixed by using `justfile_dir()` for all cross-directory paths.
- **Diagnosed `just bootstrap *` shell glob error** — `*` expands to all files in CWD before `just` runs; `age.key` in repo root caused `just` to receive `age.key` as a recipe name. Always use `just bootstrap age-key` explicitly.
- **Added Talos machine config improvements** — compared `machineconfig.yaml.j2` (bykaj) against our patch files; added missing features to `machine-features.yaml` (`apidCheckExtKeyUsage`, `diskQuotaSupport`, `kubePrism`, `rbac`) and `machine-kubelet.yaml` (`defaultRuntimeSeccompProfileEnabled`, `disableManifestsDirectory`, `featureGates: { ImageVolume, ResourceHealthStatus }`); added `KubeSchedulerConfiguration` to `controller/cluster.yaml` with `PodTopologySpread` defaults and `ImageLocality` score disabled.
- **Wrote full inline documentation** for all new patch entries — explains the mechanism, the failure mode avoided, and cluster-specific rationale (same style as existing sysctls docs).
- **Validated all changes** with `talhelper genconfig --dry-run` — no errors; dry-run diff confirms all new fields apply correctly across all 4 nodes.
- **Added `VolumeConfig` + `UserVolumeConfig` to 1 TB nodes** — created `talos/patches/node/machine-volumes-1tb.yaml` with two Talos document kinds: `VolumeConfig` caps `EPHEMERAL` at 120 GiB (prevents container layer cache from consuming the full system disk); `UserVolumeConfig` creates a `local-hostpath` partition with `minSize: 100GiB` + `grow: true` (fills remaining ~810 GiB on 1 TB drives). Applied to worker-01, worker-02, and cp-02 via per-node `patches:` in `talconfig.yaml`. cp-01 (128 GB AirDisk) excluded with an inline comment showing exactly what to add when the 1 TB disk arrives. Re-validated with dry-run.

### Files changed
| File | Change |
|------|--------|
| `.justfile` | Created — root module loader with `mod bootstrap`, `mod talos`, `log`, `template` helpers |
| `.minijinja.toml` | Created — minijinja-cli configuration |
| `.mise.toml` | Added `just`, `gum`, `aqua:mitsuhiko/minijinja`; added `[env]` block for `JUST_UNSTABLE`, `MINIJINJA_CONFIG_FILE` |
| `bootstrap/mod.just` | Created — 11-stage bootstrap pipeline + `age-key` recipe; error handling on `resources`, `crds`, `apps`; CWD-safe paths via `justfile_dir()` |
| `bootstrap/resources.yaml.j2` | Created — declarative secret template (sops-age, 1password-connect, flux-github-app) |
| `talos/mod.just` | Created — day-2 ops: `reset-cluster`, `reset-node`, `reboot-node`, `shutdown-node`, `upgrade-node`, `health` |
| `.taskfiles/bootstrap/Taskfile.yaml` | Deleted — superseded by `bootstrap/mod.just` |
| `Taskfile.yaml` | Removed `bootstrap:` include |
| `docs/CLUSTER.md` | Rewrote bootstrap runbook (Phase 0–4 → Phase 0–2); `task bootstrap:*` → `just bootstrap *` throughout |
| `CLAUDE.md` | Updated bootstrap workflow section and phase references |
| `talos/patches/global/machine-features.yaml` | Added `apidCheckExtKeyUsage`, `diskQuotaSupport`, `kubePrism`, `rbac` with full inline documentation |
| `talos/patches/global/machine-kubelet.yaml` | Added `defaultRuntimeSeccompProfileEnabled`, `disableManifestsDirectory`, `featureGates: { ImageVolume, ResourceHealthStatus }` with full inline documentation |
| `talos/patches/controller/cluster.yaml` | Added `KubeSchedulerConfiguration`: `PodTopologySpread` defaults, `ImageLocality` score disabled |
| `talos/patches/node/machine-volumes-1tb.yaml` | Created — `VolumeConfig` (EPHEMERAL ≤ 120 GiB) + `UserVolumeConfig` (local-hostpath, minSize 100 GiB, grow to fill) |
| `talos/talconfig.yaml` | Added `machine-volumes-1tb` patch to worker-01, worker-02, cp-02; added 1 TB upgrade comment to cp-01 |

### Key decisions
- **`just` + `task` coexist by design**: `bootstrap/mod.just` delegates to `task talos:*` rather than rewriting nmap discovery, disk-fingerprint deduplication, and OSD wipe logic; `just` owns orchestration, go-task owns the heavy bash.
- **`aqua:mitsuhiko/minijinja` not `minijinja-cli`**: mise's native registry has no entry for `minijinja-cli`; the aqua backend (`aqua:mitsuhiko/minijinja`) is the correct installation path.
- **`justfile_dir()` required for all cross-directory paths in modules**: module CWD is the module file's directory, not the root justfile directory — bare relative paths silently resolve to wrong locations.
- **`stableHostname` not added**: talhelper errors with "already set in v1alpha1 config" — it's a Talos v1.13 default that cannot be explicitly set again via a patch.
- **Talhelper approach unchanged vs bykaj Jinja2**: bykaj's `machineconfig.yaml.j2` approach requires `talosctl machineconfig patch` and loses Renovate version tracking; our talhelper + SOPS setup handles the LACP bond/VLAN topology correctly and keeps `# renovate:` annotations in `talenv.yaml`.

---

## 2026-06-12 — `ceph-osd-wipe-prometheus-deps`

### Goal
Diagnose and fix Ceph HEALTH_WARN (stale LVM on worker OSDs) and kube-prometheus-stack deploy failure (CSI infeasible race), then harden bootstrap against both issues recurring.

### What we did
- **Diagnosed kube-prometheus-stack not deploying** — cluster-doctor confirmed Kustomization was timing out at health-check phase; three PVCs (grafana, prometheus-db, alertmanager-db) stuck `Pending` due to CSI `InvalidArgument` error classified as `infeasible`, triggering exponential backoff (30+ minute retry delay). Root cause: no `dependsOn: rook-ceph-cluster`, so kube-prometheus-stack raced Ceph on bootstrap.
- **Diagnosed Ceph HEALTH_WARN** — `ceph osd tree` showed only 2 host buckets (talos-cp-01, talos-cp-02); worker-01 and worker-02 were absent. OSD prepare logs showed `skipping: running on a different ceph cluster "78887373-..."` — the Kingston NVMe drives still carried LVM VG metadata from the prior cluster (current FSID `19a578da-...`). 33% degraded PGs, 33 `active+undersized+degraded`.
- **Wiped stale LVM via privileged pods** — `talosctl wipe disk dm-0 dm-1` cleared LV data but kernel DM remained active; raw nvme wipe blocked with "in use by dm-0". Deployed privileged alpine pods with host `/dev` mount to each worker; ran `vgchange -an` + `wipefs -a /dev/nvme0n1` inside. VGs `ceph-2a7da365-...` (worker-01) and `ceph-3f01d6cc-...` (worker-02) removed cleanly.
- **Reprovisioned OSDs** — restarted `rook-ceph-operator`; new prepare jobs ran on all 4 nodes; OSDs 4–7 joined the cluster. Waited for all 8 OSDs to report `up`. Cluster reached `HEALTH_OK`, all 33 PGs `active+clean`, 5.5 TiB usable.
- **kube-prometheus-stack self-healed** — HelmRelease remediation (from `remediateLastFailure: true`) had already uninstalled and reinstalled the release; by the time Ceph was healthy the PVCs rebound and all pods came up Running.
- **Added `dependsOn: rook-ceph-cluster`** — patched `kube-prometheus-stack/ks.yaml` so Flux waits for the CephCluster Kustomization before starting observability stack on future bootstraps.
- **Added `wipe-ceph-osds` to `bootstrap:cluster`** — inserted `task: :talos:wipe-ceph-osds` between `genconfig` and `apply-all` so OSD disks are always wiped while nodes are in maintenance mode; no-ops cleanly on fresh installs with no prior LVM.
- **Confirmed postgres-v17 unrelated** — `postgres-v17-3` pod absent because CNPG join job was actively streaming base backup from primary; uses `openebs-hostpath` not `ceph-block`, so Ceph degradation had no effect.

### Files changed
| File | Change |
|------|--------|
| `.taskfiles/bootstrap/Taskfile.yaml` | Added `wipe-ceph-osds` step between `genconfig` and `apply-all` in `bootstrap:cluster` |
| `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml` | Added `dependsOn: rook-ceph-cluster` to prevent CSI race on bootstrap |

### Key decisions
- **Privileged pod + host /dev mount over `talosctl wipe disk`** — `talosctl wipe disk` zeroed LV data but didn't remove the kernel DM mappings; the only way to call `dmsetup`/`vgchange` on a running Talos node is a privileged container with the host's `/dev` explicitly mounted, since Talos has no root shell.
- **Wipe via `vgchange -an` + `wipefs -a` rather than `pvremove`** — deactivating the VG first (`vgchange -an`) cleanly removes the DM devices; `wipefs -a` then erases the LVM PV signature from the raw device. This is safer than `pvremove --force` which errors if the VG is still active.
- **`dependsOn: rook-ceph-cluster` qualifies under repo's strict policy** — kube-prometheus-stack genuinely cannot bind `ceph-block` PVCs without the StorageClass existing; this is a hard functional dependency, not an optional "wait for monitoring" coupling.

---

## 2026-06-12 — `bootstrap-retest-helm4-fixes`

### Goal
Validate the CRD pre-bootstrap workflow by resetting and re-bootstrapping the cluster from scratch, fixing all bugs discovered during the live run.

### What we did
- **Reset cluster to maintenance mode** — ran `task talos:reset --yes`; the `wait-maintenance` task failed immediately due to a jq exit-code bug (mid-reboot nodes return partial/garbage output causing jq to exit non-zero, which killed the `while true` loop). Diagnosed from the timing of the failure (after printing "Waiting…" but before any `sleep 15` retry).
- **Fixed `wait-maintenance` robustness** — added `|| true` after `talosctl get disks`, the FP `jq` pipeline, and the MODELS `jq` pipeline so transient failures from mid-reboot nodes don't kill the loop.
- **Confirmed all 4 nodes in maintenance** — `nmap` showed 5 IPs on port 50000 (cp-01 has two NICs, appears as `.15` and `.16`); fingerprint deduplication handled it correctly. Mapped each IP to hostname via `talosctl get disks`.
- **Fixed `bootstrap:cluster` cross-namespace task references** — `bootstrap:cluster` calls `task: talos:genconfig` etc., but Taskfile resolves these relative to the `bootstrap` namespace as `bootstrap:talos:genconfig` (not found). Fixed by using absolute refs: `task: :talos:genconfig`.
- **Fixed `bootstrap:secrets` namespace ordering** — `sops-age` runs first and needs `flux-system` to exist, but only `flux-github-app` (runs last) creates it. Added `kubectl create namespace flux-system` to `sops-age`.
- **Fixed Helm 4 `--post-renderer` incompatibility** — `00-crds.yaml` used `postRenderer: bash` with `postRendererArgs: [-c, "yq ea ..."]`, which worked in Helm 3 but Helm 4 requires post-renderers to be registered plugins (`postrenderer/v1`). Removed `postRenderer`/`postRendererArgs` from helmDefaults; moved the `yq ea 'select(.kind == "CustomResourceDefinition")'` filter into the task pipeline. Updated `CONVENTIONS.md` to document the change and rationale.
- **Successfully bootstrapped**: Phase 0 applied 30 CRDs (10 `monitoring.coreos.com/v1`, 20 `gateway.networking.k8s.io/v1`+envoy). Phase 1 installed Cilium → CoreDNS → Spegel → cert-manager → flux-operator → flux-instance. Flux reconciled from `badd5ed`.
- **Diagnosed cloudflared bootstrap race** — cluster-doctor confirmed cloudflared self-healed (2-minute retry) after a `DNSEndpoint` (`externaldns.k8s.io/v1alpha1`) CRD race: cloudflared's dry-run ran 1 second before external-dns installed its CRD. Fixed by adding `dependsOn: external-dns-cloudflare` to `cloudflared/ks.yaml`.

### Files changed
| File | Change |
|------|--------|
| `.taskfiles/talos/Taskfile.yaml` | Fixed `wait-maintenance`: added `|| true` guards to `talosctl` and `jq` commands |
| `.taskfiles/bootstrap/Taskfile.yaml` | Fixed absolute task refs (`:talos:`); added namespace pre-creation to `sops-age`; moved yq CRD filter to task pipeline |
| `kubernetes/bootstrap/helmfile.d/00-crds.yaml` | Removed `postRenderer`/`postRendererArgs` (Helm 4 incompatible); updated pipeline comment |
| `docs/CONVENTIONS.md` | Updated CRD bootstrap pipeline docs: yq filter now in shell pipeline, not Helm post-renderer |
| `kubernetes/apps/network/cloudflared/ks.yaml` | Added `dependsOn: external-dns-cloudflare` to fix DNSEndpoint CRD race |

### Key decisions
- **Moved yq filter to shell pipeline instead of Helm post-renderer**: Helm 4 broke the `postRenderer: bash` approach without a clean migration path. Shell pipeline is simpler, more portable, and doesn't require Helm plugin infrastructure.
- **`dependsOn` for DNSEndpoint, not `00-crds.yaml`**: The `00-crds.yaml` pre-bootstrap pattern is for CRDs used by many unrelated apps (Prometheus, Gateway API). `DNSEndpoint` is only used by apps that embed it directly; those apps have a clear provider (external-dns) they can depend on, making per-app `dependsOn` the right tool.

---

## 2026-06-12 — `crd-prebootstrap-helmfile-split`

### Goal
Replace the flawed `dependsOn: kube-prometheus-stack` workaround with a proper CRD pre-bootstrap phase that pre-installs monitoring and Gateway API CRDs before Flux reconciles anything, eliminating all bootstrap-ordering dry-run failures.

### What we did
- **Diagnosed cascade of further CRD failures** — `envoy-gateway` Kustomization failing (`ServiceMonitor`/`PodMonitor` in `observability.yaml`), `flux-instance` failing (`PodMonitor` in app path), `flux-receiver` failing (`HTTPRoute` — Gateway API CRDs absent because `envoy-gateway` never reconciled). All stem from the same root: CRDs not present at Flux first-reconcile.
- **Identified the architectural flaw** — adding `dependsOn: kube-prometheus-stack` to every affected Kustomization is wrong: a cluster without Prometheus would permanently block `envoy-gateway`, `flux-instance`, and `metrics-server`. Researched bykaj/home-ops to confirm the community pattern.
- **Discovered and implemented the `00-crds.yaml` pattern** — bykaj uses `helmfile template --quiet | kubectl apply --server-side` with a `yq` post-renderer that filters all chart output to `kind: CustomResourceDefinition` only. The pipeline installs zero controllers; just schema registrations. Split `kubernetes/bootstrap/helmfile.yaml` into `helmfile.d/00-crds.yaml` (CRD-only) and `helmfile.d/01-apps.yaml` (apps, unchanged content).
- **Validated against bykaj's source** — diff review found three bugs in the initial implementation: (1) used `helmfile sync` instead of `helmfile template` (would write Helm release Secrets, require namespaces to exist); (2) missing `--exit-status` on yq (silent success if chart has no CRDs); (3) wrong namespace `monitoring` instead of `observability` for kube-prometheus-stack release. All fixed.
- **Reverted all `dependsOn: kube-prometheus-stack` additions** — `metrics-server` (from previous session), `flux-instance`, `envoy-gateway` (added and reverted this session). These deps are now unnecessary with CRD pre-bootstrap.
- **Added `dependsOn: envoy-gateway-config`** to `flux-receiver/ks.yaml` — receiver needs both the Gateway API CRDs (from envoy-gateway chart) AND the `envoy-external` Gateway object (created by envoy-gateway-config). Depending on the config Kustomization (which itself depends on envoy-gateway) covers both.
- **Documented the pattern** in `docs/CONVENTIONS.md` — full section covering the pipeline mechanics, which charts to add, version pinning, and what NOT to add.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/bootstrap/helmfile.d/00-crds.yaml` | Created — CRD-only pre-bootstrap phase with yq post-renderer |
| `kubernetes/bootstrap/helmfile.d/01-apps.yaml` | Created — moved from `helmfile.yaml`; updated relative values paths |
| `kubernetes/bootstrap/helmfile.yaml` | Deleted — superseded by `helmfile.d/` |
| `.taskfiles/bootstrap/Taskfile.yaml` | Updated `apps` task: two-phase bootstrap; `helmfile template \| kubectl apply --server-side` for CRDs |
| `kubernetes/apps/kube-system/metrics-server/ks.yaml` | Reverted: removed `dependsOn: kube-prometheus-stack` (no longer needed) |
| `kubernetes/apps/flux-system/flux-receiver/ks.yaml` | Added `dependsOn: envoy-gateway-config` |
| `docs/CONVENTIONS.md` | New section: CRD bootstrap pattern with mechanics, rules, version-pinning guidance |

### Key decisions
- **`helmfile template | kubectl apply --server-side` not `helmfile sync`** — `template` produces raw manifests piped to kubectl: no Helm release Secret written, no namespace required to exist, fully idempotent on re-bootstrap. `sync` would track a release and require the namespace first.
- **`--exit-status` on yq** — makes yq exit non-zero if a chart produces no CRDs, surfacing a misconfigured entry immediately rather than silently applying nothing.
- **Only two charts in `00-crds.yaml`** — `kube-prometheus-stack` (monitoring CRDs) and `envoy-gateway` (Gateway API CRDs). Other chart CRDs are already correctly ordered via `dependsOn` chains (rook-ceph, external-secrets, cloudnative-pg) and don't need pre-bootstrap.

---

## 2026-06-12 — `servicemonitor-bootstrap-deadlock`

### Goal
Fix circular Flux bootstrap deadlock where `rook-ceph-operator` failed to install (missing `ServiceMonitor` CRD) and `kube-prometheus-stack` was blocked waiting on `rook-ceph-cluster`, which was blocked waiting on the operator.

### What we did
- **Diagnosed `metrics-server` reconciliation failure** — `serviceMonitor.enabled: true` in Helm values caused the HelmRelease to fail with `no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"` because the `kube-prometheus-stack` CRDs weren't installed yet. Fixed by adding `dependsOn: kube-prometheus-stack` to `metrics-server/ks.yaml`, matching the existing `smartctl-exporter` pattern.
- **Diagnosed `rook-ceph-operator` bootstrap deadlock** — cluster-doctor confirmed a three-way cycle: operator HelmRelease failing (ServiceMonitor CRD absent) → `kube-prometheus-stack` blocked on `dependsOn: rook-ceph-cluster` → `rook-ceph-cluster` blocked on `dependsOn: rook-ceph-operator`. Zero pods running in `rook-ceph` namespace after 6 install attempts.
- **Resolved cycle with `dependsOn` restructure** — removed `rook-ceph-cluster` from `kube-prometheus-stack`'s `dependsOn` (leaving only `onepassword-store`); re-enabled `monitoring.enabled: true` and `csi.serviceMonitor.enabled: true` in the operator HelmRelease. Bootstrap chain is now: `onepassword-store` → `kube-prometheus-stack` (CRDs land) → `rook-ceph-operator` (monitoring flags safe) → `rook-ceph-cluster` (Ceph up, ceph-block binds Prometheus PVCs).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/metrics-server/ks.yaml` | Added `dependsOn: kube-prometheus-stack` |
| `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml` | Removed `dependsOn: rook-ceph-cluster` |
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/helmrelease.yaml` | Re-enabled `monitoring.enabled` and `csi.serviceMonitor.enabled` (both `true`) |

### Key decisions
- **Remove `rook-ceph-cluster` dep from kube-prometheus-stack rather than adding kube-prometheus-stack dep to rook-ceph-operator** — adding the dep to the operator would have just relocated the cycle: kube-prometheus-stack still waits on rook-ceph-cluster (PVC binding) which still waits on the operator. Breaking at the kube-prometheus-stack end is the only non-circular cut. Helm install succeeds with pending PVCs; pods bind once ceph-block comes up.
- **Re-enable monitoring permanently, not as a two-commit disable→re-enable** — disabling was a temporary workaround discussed but not committed. The correct fix is structural so monitoring stays enabled in Git and works on every fresh bootstrap.

---

## 2026-06-12 — `vlan-detagging-bootstrap-recovery`

### Goal
Remove VLAN 60 tags from all node management interfaces (switch now sends VLAN 60 native/untagged), then diagnose and fix a chain of bugs uncovered during the apply/bootstrap sequence to bring the cluster back to a fully reconciling Flux state.

### What we did
- **Removed VLAN 60 from all 4 nodes in `talos/talconfig.yaml`** — switch now sends VLAN 60 as native/untagged; management IPs/routes/VIPs moved directly onto physical interfaces (`e1000e` for M920q nodes, `bond0` for MS-A2, `eno1` for M90q). All per-node `patches:` blocks that configured VLAN 60 subinterfaces were removed. Only VLAN 200 (storage) remains tagged on cp-02; other nodes use dedicated `bond-storage` SFP+ interfaces for storage.
- **Fixed `Taskfile.yaml` YAML parse error** — `echo "...then: /git-commit"` in the `validate:update` task was parsed as a YAML key-value pair (colon-space). Wrapped in a `- |` block scalar to make it a shell string.
- **Fixed `apply-all` `set -e` truncation bug** — go-task v3.51.1's `set: [pipefail]` adds `set -e` to all tasks; `VAR=$(talosctl get disks --insecure ...)` exits the task when a just-rebooted node is transiently unreachable. Added `|| true` to the two affected command substitutions so the loop continues to the next node.
- **Added `talos:etcd-validate` task** — reads expected CP IPs from `talconfig.yaml`, queries `talosctl etcd members`, and removes any member whose peer URL contains a transient/wrong IP. Documents the recommended post-bootstrap safety step.
- **Diagnosed and fixed etcd crash loop on cp-01** — after `talos:bootstrap`, cp-01 was registered as a learner with peer URL `https://10.60.0.15:2380` (transient maintenance-mode DHCP IP captured before bond0 settled on static `10.60.0.201`). Used `talosctl etcd remove-member` to remove the bad learner and rebooted cp-01; it rejoined cleanly and was promoted to full voting member within ~2 minutes.
- **Diagnosed and fixed cp-02 Cilium failure** — Cilium on cp-02 logged `vlan filter macros: allowed VLAN list is too big — 7 entries`. Root cause: the inline patch used `deviceSelector: hardwareAddr` to configure VLAN 200, which creates a *second* `LinkAliasConfig` alongside the one talhelper generates from `networkInterfaces`. Each network controller retry with a different alias name produced a new VLAN subinterface (`eno1054d39.200`, `eno10edb8b.200`, etc.), accumulating 7+ stale interfaces that survived reboots. Fixed by switching patch to `interface: eno1` (explicit kernel name, no alias creation) and reducing VLAN 200 MTU from 9000 to 1500 (1GbE parent cannot exceed 1500).
- **Completed cluster bootstrap** — ran `task bootstrap:apps` (Cilium 1.19.4 → CoreDNS 1.45.2 → Spegel 0.7.1 → cert-manager v1.20.2 → flux-operator 0.50.0 → flux-instance 0.50.0); pushed `sops-age` secret; all 4 nodes Ready, Flux reconciling ~40 kustomizations.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Removed VLAN 60 from all 4 nodes; cp-02 VLAN 200 MTU 9000→1500; cp-02 patch switched to `interface: eno1`; updated comments |
| `Taskfile.yaml` | Fixed YAML parse error in `validate:update` echo command |
| `.taskfiles/talos/Taskfile.yaml` | Added `|| true` to `apply-all` command substitutions; added new `etcd-validate` task |

### Key decisions
- **VLAN 200 MTU 1500 on cp-02** — cp-02 has a single 1GbE RJ45 shared by management (VLAN 60 native) and storage (VLAN 200 tagged); Linux forbids a VLAN subinterface MTU exceeding the parent's 1500. The 9000 MTU only applies to the dedicated 10GbE `bond-storage` SFP+ interfaces on the other three nodes.
- **`interface: eno1` over `deviceSelector` in patch** — `deviceSelector: hardwareAddr` in `machine.network.interfaces` creates a new `LinkAliasConfig` alongside the one talhelper already generates from `networkInterfaces`, causing duplicate VLAN subinterfaces per controller retry. Explicit `interface: eno1` avoids alias creation entirely.
- **`etcd-validate` as post-bootstrap safety net** — the race between Talos's etcd controller and bond interface formation (controller fires before bond0 has the static IP, capturing a transient DHCP address as the peer URL) is hard to prevent architecturally. The task provides an explicit check-and-repair step without requiring DHCP reservations or config changes.

---

## 2026-06-12 — `cluster-reset-task-overhaul`

### Goal
Execute post-rename OSD wipes across all 4 nodes and overhaul `wait-maintenance` + `wipe-ceph-osds` tasks with dynamic IP discovery, hardware deduplication, and helmrelease-sourced OSD targeting.

### What we did
- **Node reset to maintenance mode** — `task talos:reset` failed with i/o timeout on M90q (10.60.0.202, never had a working config applied) and MS-A2 (10.60.0.201, LACP bond dropped when maintenance mode sent no PDUs). Worked around by running targeted `talosctl reset` on the three reachable nodes; M90q manually booted into maintenance mode. User reconfigured switch to remove LACP from MS-A2's ports; both NICs came up as DHCP on 10.100.0.x. Final maintenance IPs: M90q 10.100.0.211, MS-A2 10.100.0.215+216, M920q #1 10.100.0.231, M920q #2 10.100.0.237.
- **Rewrote `wait-maintenance`** — replaced fixed-IP polling with nmap subnet scan (10.60.0.0/24 + 10.100.0.0/24); deduplicated by disk serial fingerprint so multi-NIC hosts (MS-A2 with 2 IPs) count as one; added per-node display showing IP + disk models (`|`-joined).
- **Rewrote `wipe-ceph-osds`** — sources the authoritative OSD list from the Rook HelmRelease YAML (no hardcoded model strings); identifies each target disk by constructing the udev by-id basename (`nvme-<MODEL_underscored>_<SERIAL>`) and matching against talosctl disk output; deduplicates by OSD by-id so duplicate IPs for the same host are skipped cleanly.
- **Fixed MS-A2 OSD device in Rook helmrelease** — was `nvme-CT2000P310SSD8_252450B1A33B` (never installed); user clarified 3× new Crucial T500 2TB SSDs were installed (one per node replacing spares). Corrected to `nvme-CT2000T500SSD8_2545543A2190`. P310 will be added to a future node TBD.
- **OSD wipes executed**: cp-01 T500 `2545543A2190` ✅ wiped; cp-02 T500 `25405348D601` ✅ wiped; M920q #1 + #2 Kingston NV3 OSD NVMes ⚠️ blocked by LVM (`dm-0`/`dm-1` auto-assembled from prior Ceph PV metadata in maintenance mode). Confirmed Rook `ceph-volume lvm zap --destroy` handles these on first OSD provisioning.
- **Bug fixes**: (a) `wait-maintenance` `vars.NODE_COUNT` ran `yq` from repo root, not `dir:`; fixed to use `{{.TALOS_DIR}}/talconfig.yaml` full path. (b) Embedded literal newline in YAML block scalar broke YAML parse at `SUMMARY=...` assignment; replaced with `printf '%s\n...'` to keep the newline in the shell layer.

### Files changed
| File | Change |
|------|--------|
| `.taskfiles/talos/Taskfile.yaml` | Rewrote `wait-maintenance` (nmap scan, disk-fingerprint deduplication, informative output) and `wipe-ceph-osds` (helmrelease-sourced OSD list, serial matching, by-id deduplication) |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | Fixed MS-A2 OSD device: P310 → T500 serial `2545543A2190` |

### Key decisions
- **Disk serial fingerprint for deduplication** — Talos maintenance mode API surface is limited to `Disks`, `Version`, `ApplyConfiguration`, `Reset`, `Upgrade`; no machine UUID endpoint available. Sorted disk serials are a reliable hardware identity proxy for multi-NIC hosts.
- **OSD list sourced from Rook helmrelease** — eliminates hardcoded model strings as technical debt; `by-id` basename matching (model + serial → udev symlink format) is stable across NVMe enumeration instability (MS-A2 NVMe kernel names flip between reboots).
- **LVM-blocked wipe accepted as non-issue** — Talos maintenance kernel auto-assembles Ceph LVM VGs from PV metadata; the Talos API intentionally blocks writes to dm-slave devices and cannot be bypassed in maintenance mode. Rook's `ceph-volume lvm zap --destroy` is the designed path for reclaiming prior-Ceph devices on first OSD provisioning.
- **nmap over fixed-IP polling** — maintenance mode nodes may boot on DHCP IPs (VLAN 100 native, 10.100.0.0/24) if their management VLAN config was never applied (M90q) or if switch-side LACP forces a different port mode (MS-A2).

---

## 2026-06-11 — `rook-ceph-dashboard-secret`

### Goal
Wire the Rook-Ceph dashboard password via ESO (1Password → `rook-ceph-dashboard-password` Secret), placed for correct re-bootstrap ordering and compliant with CONVENTIONS.md ExternalSecret rules.

### What we did
- **Created `operator/app/externalsecret.yaml`** — ExternalSecret pulling from the `rook-ceph` 1Password item; rewrite `ROOK_CEPH_$1`; template maps `ROOK_CEPH_DASHBOARD_PASSWORD` → `password` key. Target Secret name `rook-ceph-dashboard-password` is auto-discovered by the Rook operator (hardcoded convention, no HelmRelease changes needed).
- **Initial placement in `cluster/app/`** was corrected after discussing re-bootstrap safety: with the ExternalSecret in `cluster/app/`, the CephCluster could start before ESO creates the Secret (race condition). Moving it to `operator/app/` (which has `wait: true`) means Flux blocks the cluster Kustomization until the Secret is confirmed Ready.
- **Rewrite corrected** from no-op `$1` → `ROOK_CEPH_$1` after checking CONVENTIONS.md; template variable updated to `{{ .ROOK_CEPH_DASHBOARD_PASSWORD }}`.
- **Added bootstrap ordering principle to CLAUDE.md** under GitOps Conventions — generalised rule: async-produced prerequisites (ExternalSecrets, Certificates, etc.) belong in the earlier Kustomization so `wait: true` enforces the ordering guarantee.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/externalsecret.yaml` | Created — ExternalSecret for dashboard password |
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/kustomization.yaml` | Added `externalsecret.yaml` to resources |
| `CLAUDE.md` | Added "Bootstrap ordering" subsection under GitOps Conventions |

### Key decisions
- **ExternalSecret in `operator/app/` not `cluster/app/`** — the operator Kustomization has `wait: true`; ESO must create the Secret (ExternalSecret Ready) before Flux starts the cluster Kustomization. Without this, fresh bootstraps race; live clusters mask the problem because ESO is already warm.
- **No HelmRelease changes** — Rook auto-discovers the `rook-ceph-dashboard-password` Secret by name in the same namespace; no `spec.dashboard.passwordSecret` or similar chart value exists.
- **`ROOK_CEPH_$1` prefix** over ByKaj's passthrough `$1` — CONVENTIONS.md mandates a prefix rewrite to namespace intermediate keys and prevent field collisions across multiple `dataFrom.extract` entries.

---

## 2026-06-11 — `node-reshape-rebootstrap-prep`

### Goal
Promote M90q #1 to control plane, demote M920q #2 to worker, rename all nodes to their final-target identities (Option B), expand Ceph to 4 OSD hosts, and add a `wipe-ceph-osds` task — preparing the cluster for a clean rebootstrap.

### What we did
- **Promoted M90q #1 (formerly `talos-worker-01`) to control plane** as `talos-cp-04` — configured VLAN 60 (`10.60.0.202/24`, MTU 1500, VIP) and VLAN 200 (`10.200.0.202/24`, MTU 9000) on its single 1GbE NIC using the patch approach to avoid the talhelper VLANConfig doc conflict. Applied via direct `talosctl apply-config` targeting old IP `10.60.0.206` (talhelper lookup fails when the IP in talconfig has already changed).
- **Demoted M920q #2 (`talos-cp-02`) to worker** — flipped `controlPlane: false`, removed VIP, and removed the stale `machine.install.wipe: true` patch (one-time migration artifact from the Ceph disk wipe; dangerous to leave in persistent config as it triggers ephemeral wipe on every future upgrade). Confirmed cp-04 was in etcd before applying. Applied via `task talos:apply IP=10.60.0.205`.
- **Reviewed hardware architecture** against M920q #2 instability (3 hard-downs, suspected thermal/PSU root cause) and corrected prior mis-claim that etcd and OSD co-tenant on a single device on M920q #1 (two separate NVMe drives). Final CP set: MS-A2 + M90q #1 + M920q #1.
- **Renamed all nodes to Option B final-target scheme**: `talos-cp-03` (MS-A2) → `talos-cp-01`; `talos-cp-04` (M90q #1) → `talos-cp-02`; `talos-cp-01` (M920q #1) → `talos-worker-01` (temporary CP until M90q #2 joins); `talos-cp-02` (M920q #2) → `talos-worker-02`. IPs unchanged.
- **Updated Ceph OSD topology** — renamed node entries to new names and added `talos-cp-02` (M90q #1, T500 2TB, device ID `nvme-CT2000T500SSD8_25405348D601` discovered live before reset via `talosctl get disks`). Cluster now configured for 4 OSD hosts, enabling self-heal under `size=3`.
- **Added `wipe-ceph-osds` task** — uses `talosctl get disks --insecure -o json | jq` to find each OSD disk by model prefix at runtime (avoids nvme0/1 enumeration instability), then `talosctl wipe disk --insecure`. Chained into `reset` task after `wait-maintenance`. All 4 OSD nodes covered (10.60.0.201, .202, .204, .205).
- **Updated CLAUDE.md, tuppr comment** to reflect 4-node cluster and new node names.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Four node renames + zone labels; VLAN 60+200 patch for M90q #1; wipe patch removed from M920q #2 |
| `CLAUDE.md` | Hardware table updated (4 nodes, Option B names), AMT list, VIP note |
| `.taskfiles/talos/Taskfile.yaml` | Added `wipe-ceph-osds` task; `reset` now sequences reset→wait-maintenance→wipe; M90q #1 added to wipe list |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | OSD nodes renamed to Option B names; M90q #1 T500 2TB added as 4th OSD host |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/talosupgrade.yaml` | Comment corrected to 4-node cluster |

### Key decisions
- **VLAN 200 MTU 9000 on single 1GbE NIC**: Linux auto-lifts the parent interface MTU to match the highest child VLAN; VLAN 60 stays 1500. Switch port must be a trunk carrying VLANs 60, 200, native 100.
- **Option B naming (final-target state)**: names reflect the intended final role when M90q #2 arrives and M920q #1 is eventually demoted; avoids another rename cycle at that point. `talos-worker-01` is temporarily a CP — the zone label and name accurately predict its future role, not its current one.
- **M920q #2 permanently a worker**: 3 hard-downs with suspected thermal/PSU root cause overrides the HARDWARE-ARCHITECTURE.md disk-budget argument for putting it in etcd. M920q #1 temporarily anchors the third CP slot despite OSD co-tenancy — two separate NVMe drives, no shared device.
- **Wipe in maintenance mode, not on live cluster**: Rook-Ceph holds exclusive raw block device ownership; wiping an OSD disk while Ceph is running destroys BlueStore metadata live. The `wipe-ceph-osds` task runs after `wait-maintenance` ensures nodes are in Talos maintenance (Ceph not running) before any disk wipe.

---

## 2026-06-10 — `ceph-osd-lacp-tuning`

### Goal
Tune Rook-Ceph for LACP bond utilization by identifying the `osdsPerDevice: 2` lever, committing the config change, working through the raw-mode BlueStore complication, and validating the improvement with a live benchmark after the user completed the staggered OSD migration.

### What we did
- **Research** — reviewed community findings on LACP + Ceph: RADOS opens one TCP connection per OSD peer pair, so a single OSD per node pins all replication traffic to one bond link. Primary lever: `osdsPerDevice: 2` creates independent TCP flows per peer and allows both 10GbE members to carry traffic.
- **Decided on 2 OSDs per device** (not 3 or 4): QLC NAND on cp-03 (Crucial CT2000P310) has limited write endurance (~300 TBW); 2 OSDs per NVMe is the Ceph-recommended sweet spot and provides sufficient flow diversity for a 2-member LACP bond. 3+ gives no additional LACP benefit and adds wear + daemon overhead.
- **Config changes committed (`3e23baf`)** — `osdsPerDevice: "1"→"2"` and added `cephConfig.osd.ms_async_op_threads: "5"` (default 3; bumped for NVMe messenger parallelism) in `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml`.
- **Raw-mode BlueStore complication discovered** — after Flux reconcile, OSD prepare jobs ran but produced 0 new OSDs. Analysed prepare job logs: existing OSDs occupy the full device in raw BlueStore mode (no GPT partitions); `osdsPerDevice: 2` is not additive on raw devices — it requires OSD purge + device wipe + reprovision. Initial claim that the change was "additive" was wrong and was corrected.
- **Staggered migration procedure** documented: mark OSD out → wait active+clean → purge → delete deployment → wipe device (privileged pod, `sgdisk --zap-all`) → delete stale prepare job → Rook reprovisions 2 OSDs. One node at a time, min_size=2 maintained throughout.
- **cp-02 risk flag** — cp-02 has had 3 unexplained hard-downs (non-ECC RAM suspected); advised holding the migration until cp-02 is stable. User proceeded with the migration independently.
- **Validation benchmark** — after user confirmed 6 OSDs live: ran `rados bench -p ceph-blockpool 60 write` (4MB objects, 16 concurrent); measured per-bond-member interface counters pre/post via `/proc/net/dev` on an OSD pod (host-networked). Results: **324 MB/s sustained write**, both `enp1s0f0` (0.67 Gbps RX) and `enp1s0f1` (0.52 Gbps RX + 1.18 Gbps TX) active — confirms LACP is distributing across both 10GbE members.
- **Future 2nd NVMe guidance** — when adding a 2nd physical NVMe per node, revert `osdsPerDevice` to `"1"`: 1 OSD per device = 2 OSDs per node naturally, no device splitting needed, each OSD owns a full drive.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` | `osdsPerDevice: "1"→"2"`; added `cephConfig.osd.ms_async_op_threads: "5"` |

### Key decisions
- **`osdsPerDevice: 2` not 3 or 4** — beyond 2 the LACP gain is negligible (still only 2 physical links), and the Crucial CT2000P310 QLC drive on cp-03 would see accelerated wear from the additional BlueStore metadata writes of extra OSD daemons.
- **`ms_async_op_threads` is startup-only** — the config-store value was confirmed written (`ceph config get osd ms_async_op_threads` → 5), but existing OSD daemons keep 3 threads until next restart; the 3 new OSDs provisioned during migration start with 5.
- **Held migration until cp-02 stable** — the degraded-redundancy window during per-node OSD reprovisioning is unacceptably risky while cp-02 is exhibiting unexplained hard-downs.

---

## 2026-06-10 — `rook-ceph-phase5-consumers`

### Goal
Phase 5 of the Longhorn→Rook-Ceph migration: re-point all suspended consumers onto `ceph-block`, restore the waha + grafana data from NFS, and triage a recurring cp-02 hard-down that surfaced mid-migration.

### What we did
- **pgadmin (canary, `c4321f4`)** — `storageClass: longhorn`→`ceph-block`, removed `suspend: true`, added `rook-ceph-cluster` dependsOn (it had no storage dep). Verified fresh ceph-block PVC bound + pod Ready, 0 restarts. No data restore (disposable).
- **Discovered the recorded migration state was wrong** — the suspended consumers' longhorn PVCs were *backed up but never deleted*. Found **4 zombie PVCs** (pgadmin, grafana, prometheus, alertmanager) still `Bound` to dead `driver.longhorn.io` PVs. Force-cleared all 4: `kubectl delete pvc` (0 pods) + **stripped PV finalizers** (`patch ... finalizers:null`) since the longhorn CSI controller is gone and reclaim=Delete would wedge them in Terminating.
- **waha (`9eac476`)** — SC swap + un-suspend + dependsOn. Restored the WhatsApp `gows/` session from `waha-20260608.tgz` via the out-of-band dance (suspend HR → scale 0 → restore pod uid 65534 → scale 1). Session reconnected `WORKING`, **no QR re-scan** (`gows connected:true`).
- **kube-prometheus-stack (`e339232`)** — 3× SC→ceph-block (grafana/prometheus/alertmanager), un-suspend, dependsOn. **Deleted the prometheus+alertmanager StatefulSets first** (immutable `volumeClaimTemplates`) so Helm recreated them on ceph-block. Restored full `/var/lib/grafana` (incl. 8.9 MB `grafana.db`) from `grafana-20260608.tgz` as uid 472 → `database:ok`, 28 dashboards, 2 datasources. Prometheus/alertmanager left fresh (disposable).
- **cp-02 hard-down (mid-session)** — user rebooted it; it caused a Flux dependency cascade that self-cleared. Confirmed full recovery (etcd 3 members, Ceph HEALTH_OK after osd-0/mon-c bounce). Pulled diagnostics: reboot wiped dmesg, **pstore empty** (no capture armed) — root cause undeterminable post-hoc. **3rd recurrence**, cp-02-specific (cp-01 identical hw never fails).
- **kube-state-metrics `exec format error`** — found crashlooping (49 restarts) **only on cp-02**; self-resolved when the kps reconcile rescheduled it to cp-03 (clean image, 0 restarts, `kube_pod_info`=154 series). On an all-amd64 cluster that means a **corrupted binary** → corroborating evidence for a cp-02 RAM fault.
- **Docs/memory** — marked Rook-Ceph + Phase 5 complete in CLAUDE.md + ROADMAP.md; recorded the cp-02 recurrence, the non-ECC-RAM leading diagnosis, and a pre-crash capture plan (netconsole + off-node vitals + MemTest86+).

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/pgadmin/app/helmrelease.yaml` | SC longhorn→ceph-block; removed `suspend: true` |
| `kubernetes/apps/database/pgadmin/ks.yaml` | Added `rook-ceph-cluster` dependsOn |
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | SC longhorn→ceph-block; removed `suspend: true` |
| `kubernetes/apps/automation/waha/ks.yaml` | Added `rook-ceph-cluster` dependsOn |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | 3× SC longhorn→ceph-block (grafana/prometheus/alertmanager); refreshed stale Longhorn comments |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` | Removed `suspend: true` |
| `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml` | Added `rook-ceph-cluster` dependsOn |
| `CLAUDE.md` | Complete-vs-Planned table: Longhorn→Removed, Rook-Ceph→Done (Phase 5) |
| `docs/ROADMAP.md` | Rook-Ceph Migration marked complete (Phase 4+5); cp-02 recurring-hard-down update + leading diagnosis |

### Key decisions
- **Canary-first ordering** (pgadmin → waha → kube-prometheus-stack): proves the ceph-block provisioning path on a disposable workload before any real data is at risk.
- **Delete-then-reprovision, not patch**: both PVC `storageClassName` and StatefulSet `volumeClaimTemplates` are immutable — the only way to switch SC is to delete the object and let Helm/CSI recreate it fresh.
- **Restore out-of-band, not via Git**: restored data lives inside RBD images (node state), not GitOps-managed; `flux suspend` during the restore window stops drift-detection reverting the manual scale-to-0.
- **Continued the migration despite the cp-02 crash** (user choice): Ceph `size=3` demonstrably survives a cp-02 loss with zero data impact, so the migration is safe to proceed while cp-02 stabilization is deferred.

---

## 2026-06-10 — `ceph-dashboard-ingress`

### Goal
Expose the Rook-Ceph mgr dashboard through the cluster's `envoy-internal` Gateway by adding an HTTPRoute to the existing `rook-ceph-cluster` Kustomization.

### What we did
- **Confirmed dashboard is live but internal-only:** queried `rook-ceph` Services (after renewing expired MCP token) — `rook-ceph-mgr-dashboard` ClusterIP `10.43.117.254:7000` exists, no Ingress or HTTPRoute present.
- **Studied existing HTTPRoute pattern** across the cluster (`pgadmin`, `kube-prometheus-stack`, `waha`) — all use `envoy-internal / https / ${DOMAIN_CLUSTER}` with no per-route TLS or ExternalDNS annotations.
- **Created `httproute.yaml`** in the cluster app directory: routes `ceph.${DOMAIN_CLUSTER}` → `rook-ceph-mgr-dashboard:7000` via the `envoy-internal` gateway `https` section.
- **Registered the route** in `cluster/app/kustomization.yaml` resources list.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/httproute.yaml` | New — HTTPRoute: `ceph.${DOMAIN_CLUSTER}` → `rook-ceph-mgr-dashboard:7000` |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/kustomization.yaml` | Added `httproute.yaml` to resources |

---

## 2026-06-10 — `rook-ceph-deploy`

### Goal
Phase 4 of the Rook-Ceph migration: scaffold and deploy the operator + `CephCluster` via Flux with host-networking `cluster_network` on the storage bond, reaching HEALTH_OK with three host-spread OSDs on the raw spares freed in Phase 3.

### What we did
- **Research + design benchmark:** verified the Rook v1.20 chart defaults and the CephCluster network/storage CRD syntax against the official docs (host networking + `addressRanges`, by-id device selection), then diff'd our intended design against the **ByKaj reference** (`tmp/home-ops-bykaj/kubernetes/apps/rook-ceph`). Adopted ByKaj's OCI source + health-gating + monitoring/resource patterns; **deliberately diverged** on two points (by-id OSD pinning, host networking — see decisions).
- **Chart-tag pinning:** anonymously HEAD-checked the GHCR OCI tags — confirmed `v1.19.4/.5/.6` and `v1.20.0` all exist (the `tags/list` page was just truncated). Pinned **`v1.19.6`** (ByKaj-proven on near-identical Talos hardware) over the 8-day-old `v1.20.0`.
- **Live disk re-confirmation:** `talosctl get disks` on all 3 nodes to lock the exact `by-id` strings + re-confirm the cp-03 enumeration flip before baking them into the OSD list.
- **Scaffolded the GitOps tree** under `kubernetes/apps/rook-ceph/` following this repo's operator/CRD-instance split (mirrors `cloudnative-pg`): two OCIRepository sources in `flux/meta/repos/oci/`, a multi-doc `ks.yaml` (operator `wait:true` + cluster `dependsOn` with CEL `healthCheckExprs`), operator + cluster HelmReleases, namespace with PSA `enforce: privileged`. All paths `kubectl kustomize`-build clean.
- **Network decision** surfaced via `AskUserQuestion` (ByKaj runs pod-net; we had scar tissue from the Longhorn storage-VLAN saga) → user chose **host networking with `cluster_network` on the storage bond**.
- **Namespace reasoning:** kept `rook-ceph` (not a generic `storage`) — argued from the existing `openebs` precedent and Rook's canonical-namespace assumption.
- **Committed `4e51a01`**, user pushed, then **watched the reconcile** with a background poller: operator `InstallSucceeded` → 3 mons quorum → 3 OSD-prepare jobs → 3 OSDs up/in → **HEALTH_OK in ~2.5 min**.
- **Verified end-to-end:** `ceph -s` HEALTH_OK (3 mon / 2 mgr / 3 osd, PGs active+clean); `ceph osd tree` shows `failureDomain: host` with one OSD per host (cp-03's 2TB at CRUSH weight 1.82); **`ceph osd dump` confirms each OSD's `cluster_addr` on `10.200.0.20X` (storage bond) + `public_addr` on `10.60.0.20X`** — the bond-storage design goal achieved. CSI smoke test: a throwaway `ceph-block` PVC bound <1s, created an RBD image, and reclaimed it on delete.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/rook-ceph/namespace.yaml` | New — `rook-ceph` namespace, PSA `enforce: privileged` |
| `kubernetes/apps/rook-ceph/kustomization.yaml` | New — namespace-level kustomize (namespace + `./rook-ceph`) |
| `kubernetes/apps/rook-ceph/rook-ceph/kustomization.yaml` | New — wraps `./ks.yaml` |
| `kubernetes/apps/rook-ceph/rook-ceph/ks.yaml` | New — operator + cluster Flux Kustomizations (CEL health gate) |
| `kubernetes/apps/rook-ceph/rook-ceph/operator/app/{kustomization,helmrelease}.yaml` | New — operator HelmRelease (RBD-only, monitoring on) |
| `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/{kustomization,helmrelease}.yaml` | New — CephCluster: host-net, by-id OSDs, `ceph-block` SC |
| `kubernetes/flux/meta/repos/oci/rook-ceph.yaml` | New — operator chart OCIRepository (`v1.19.6`) |
| `kubernetes/flux/meta/repos/oci/rook-ceph-cluster.yaml` | New — cluster chart OCIRepository (`v1.19.6`) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Registered the two rook OCI sources |
| `kubernetes/apps/kustomization.yaml` | Registered the `./rook-ceph` namespace |
| `docs/ROADMAP.md` | Phase 4 status + toolbox-deployment-style note |

### Key decisions
- **Host networking at greenfield** (`public=10.60.0.0/24`, `cluster=10.200.0.0/24`): puts OSD replication on the 10G jumbo bond. Done at cluster creation specifically to avoid Rook's mon-failover dance that converting a live cluster would require. ByKaj leaves this commented out (runs pod-net) — our deliberate divergence, justifying the whole bond-storage fabric.
- **OSD devices pinned by `/dev/disk/by-id/…`, not kernel names:** cp-03's enumeration is flipped (system=`nvme0n1`, spare=`nvme1n1`) vs cp-01/02, so a `/dev/sdb`-style selector (ByKaj's) would be a data-loss footgun here.
- **Chart pinned `v1.19.6`** (proven) over `v1.20.0` (released 8 days prior) — proven-on-similar-hardware beats newest for a first-light storage migration; Renovate can PR the bump later.
- **Namespace `rook-ceph`, not `storage`:** consistent with the existing implementation-named `openebs` storage namespace and Rook's canonical convention; isolates a uniquely-privileged (host-net, raw-device) subsystem with its own RBAC/PSA.
- **Built-in chart toolbox** (`toolbox.enabled: true`) over ByKaj's standalone app-template toolbox — lowest maintenance; switch documented in ROADMAP if NAS export/pinned-digest features are ever needed.
- **`cephBlockPoolsVolumeSnapshotClass.enabled: false`** — no external-snapshotter CRDs deployed yet; leaving it on would fail the Flux dry-run.
- **`ceph-block` set as the default StorageClass** — no default existed (openebs-hostpath was non-default); unqualified PVCs now land on redundant storage.
- **CEL `healthCheckExprs` treating `HEALTH_WARN` as healthy** — a fresh cluster legitimately sits in WARN during PG/OSD bring-up; without this Flux would mark the Kustomization failed.

---

## 2026-06-10 — `rook-ceph-free-disks`

### Goal
Phase 3 of the Rook-Ceph migration: free the three per-node spare disks at the Talos layer (remove the `/var/mnt/longhorn-storage` userVolume) and wipe each to raw so they are eligible as Ceph OSDs.

### What we did
- **Pre-flight:** confirmed cp-02 had passed a 23h stability soak (the gating condition from last session); verified 3/3 nodes Ready, etcd 3 members healthy on all, and talosctl skew safe (client `v1.13.0` vs server `v1.13.2`, same minor). Inspected `talosctl get disks` / `get discoveredvolumes`: each spare carried a leftover GPT + full-disk `xfs` partition from Longhorn.
- **Config edit:** removed the `machine.disks` userVolume patch (mountpoint `/var/mnt/longhorn-storage`) from all 3 nodes in `talconfig.yaml`; **kept** cp-02's separate `machine.install.wipe: true` patch (system-disk concern, out of scope). `task talos:genconfig` + verified the generated machineconfigs no longer carry any `disks:` stanza and that install disks/bond-storage are unchanged.
- **Staggered apply (one node at a time):** each `task talos:apply IP=…` returned *"can't be applied in immediate mode"* and **rebooted** — userVolume mounts are early-boot static volume topology. Each node rejoined `Ready` + etcd `OK` in **43–77s**; the kube-vip VIP failed over via ARP so `kubectl` (→ VIP) never dropped. Verified etcd quorum (3 members) held between every step.
- **Wipe to raw:** `talosctl wipe disk <dev>` (FAST) per node after confirming the userVolume was unmounted (`mountstatus` showed no longhorn mount). Each spare collapsed from `gpt`+`xfs` to a bare `disk` row — the state `ceph-volume` requires to adopt a device.
- **Enumeration near-miss:** mapped **serial→device** on every node rather than assuming `nvme0n1`. cp-01/cp-02 spare = `nvme0n1`, but **cp-03 is flipped** — `nvme0n1` is the system disk (AirDisk 128GB), spare = `nvme1n1` (Crucial 2TB). A blind `nvme0n1` wipe on cp-03 would have destroyed the OS.
- **Housekeeping:** reaped 4 stale `Error`/`Completed` tombstone pods left from the 2026-06-09 outage (cilium-operator, kube-state-metrics, reloader, onepassword-connect) — node-reboot orphans; deployments self-healed, KSM respawned. Final state: 3/3 Ready, etcd 3/3 OK, **0** non-Running pods, **3 raw spares**.
- **Not done (next session):** Phase 4 (deploy Rook-Ceph operator + `CephCluster`, 3 OSDs, `cluster_network` on the storage bond, size=3/failureDomain host) and Phase 5 (re-point apps to `ceph-block`, un-suspend, restore from NFS). The `talconfig.yaml` change remains **uncommitted** in the working tree.

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Removed the `/var/mnt/longhorn-storage` userVolume patch from cp-01/cp-02/cp-03 (kept cp-02 `install.wipe:true`) |

### Key decisions
- **Map serial→device per node, never assume the name.** cp-03's NVMe enumeration is reversed vs cp-01/cp-02; matching the WWID/serial to the device removed from config is the only safe way to pick the wipe target.
- **FAST wipe is sufficient** — it zeroes only the GPT + filesystem superblocks (disk head/tail), which is exactly what `ceph-volume` inspects; no need to zero the full 1–2 TB.
- **Kept cp-02's `machine.install.wipe: true`** — a system-disk/reinstall concern orthogonal to freeing the spare; removing it would have widened the change surface for no Phase-3 benefit.
- **Reaped the outage tombstones** even though they predate Phase 3 — they surfaced during health verification, were safely terminated, and three owning deployments already had healthy replicas.

---

## 2026-06-08 — `rook-ceph-migration`

### Goal
Migrate cluster replicated storage from Longhorn to Rook-Ceph via a big-bang cutover: quiesce and remove the 5 Longhorn-backed PVCs (OpenEBS hostpath PVCs out of scope), remove Longhorn, free the per-node spare disks at the Talos layer, and stand up a size=3 Rook-Ceph cluster on the existing disks with cluster_network on the storage VLAN.

### What we did
- **Phase 0 (plan):** established the migration strategy. Confirmed via `talosctl get discoveredvolumes` that there is **no free raw disk** — each node's spare (cp-01/cp-02 Kingston NV3 1TB, cp-03 Crucial P310 2TB) is a Talos `userVolume` at `/var/mnt/longhorn-storage`, so big-bang (remove Longhorn to free OSD devices) is forced. Decided initial OSDs = the 3 existing DRAM-less spares (size=3 / failureDomain=host = redundancy today); **hold** the lone Crucial T500 until the 2 M90q nodes arrive (1 OSD on 1 host adds no redundancy). Mapped consumers→PVCs→Kustomizations and the `dependsOn: longhorn` edges (waha, kube-prometheus-stack; pgAdmin was missing a storage dep entirely).
- **Backups:** only grafana (22 MB, incl. `grafana.db`) + waha (242 KB, WhatsApp `gows/` session) needed keeping; prometheus/alertmanager/pgadmin data accepted as disposable; postgres is on openebs (untouched). User created a dedicated rw NFS dataset `10.200.0.41:/mnt/tank/Cluster/migration`. Backup pods ran as **uid 4000 (NFS owner) + `supplementalGroups: [app-gid]`** to bridge read(app-owned data)/write(NFS) ownership; both tarballs `gzip -t`-verified.
- **Phase 1 (quiesce + delete):** suspended the 3 consumer HRs + scaled to 0; Prometheus/Alertmanager via CR `replicas: 0` (operator, not STS); deleted all 5 Longhorn PVCs → every volume drained (reclaimPolicy Delete).
- **Phase 2 (remove Longhorn, commit `8b27593`, pushed):** did a **controlled manual uninstall** — set `deleting-confirmation-flag=true` first (else the chart pre-delete hook hangs), then `kubectl delete helmrelease longhorn` with the namespace alive (avoids the Flux-prune namespace-race). Git: deleted `apps/longhorn-system/` + the helm repo source, removed the two `dependsOn: longhorn` edges, added `suspend: true` to the 3 consumer HRs (durable quiesce).
- **Mid-session outage (~12h):** chased as a cluster-down event; root cause was **two stacked faults, neither from the migration** — (1) a **Tailscale subnet-route hijack** on the Windows/WSL host (lab subnets routed via a dead tailscale-operator subnet router; tell = the devcontainer route showing **MTU 1280**), and (2) **cp-02 left cordoned** after a drain-for-reboot. Recovered: closed Tailscale + `wsl --shutdown`; uncordoned cp-02. Cluster verified healthy (3/3 Ready, etcd 3 members, all static pods True).
- **Resurrection debris cleanup:** Longhorn briefly reinstalled itself at 19:53 (the imperative `suspend` on the Flux Kustomization was reverted by `cluster-apps` re-applying it before the push pruned it), leaving orphan CRDs + ~150 CRs + both admission webhooks and a stuck-`Terminating` namespace. Cleaned in order: delete webhook configs → strip all finalizers → delete CRDs → delete orphan `longhorn`/`longhorn-static` SCs → namespace drained. Re-parked the suspended apps at 0 replicas.
- **Docs/memory:** added a `docs/QA.md` Networking entry for the Tailscale route-hijack (MTU-1280 signature + `wsl --shutdown` fix); checkpointed full progress to the `project_rook_ceph_migration.md` memory.
- **Not done (next session):** Phase 3 (free disks via talconfig + staggered Talos reboots), Phase 4 (deploy Rook-Ceph), Phase 5 (re-point apps to `ceph-block`, un-suspend, restore from NFS). Recommended a stability soak before Phase 3's reboots.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/longhorn-system/**` | Deleted entire Longhorn app (13 files) |
| `kubernetes/apps/kustomization.yaml` | Removed `./longhorn-system` include |
| `kubernetes/flux/meta/repos/helm/longhorn.yaml` | Deleted HelmRepository source |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Removed longhorn repo reference |
| `kubernetes/apps/automation/waha/ks.yaml` | Removed `dependsOn: longhorn` |
| `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml` | Removed `dependsOn: longhorn` |
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Added `suspend: true` (migration quiesce) |
| `kubernetes/apps/database/pgadmin/app/helmrelease.yaml` | Added `suspend: true` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` | Added `suspend: true` |
| `docs/QA.md` | New Networking entry: Tailscale subnet-route hijack (unstaged) |

### Key decisions
- **Big-bang over coexist** — there is no free disk; each node's spare is a Longhorn userVolume, so Longhorn must go to free OSD devices. Freeing all 3 at once still yields size=3 across 3 hosts (not a downgrade).
- **Hold the lone T500** — redundancy is gated on host count, not disk count; a single OSD on one host adds nothing. Add all 3 T500s as a matched set when the M90q nodes land.
- **Controlled manual Longhorn uninstall, not plain Flux prune** — pruning deletes the namespace and HelmRelease together, and a Terminating namespace rejects the helm pre-delete hook job → wedged uninstall. Uninstall with the namespace alive first.
- **`suspend: true` in Git for the quiesce** — an imperative scale/suspend gets reverted by Flux reconcile; durable parking must live in source. **Lesson learned the hard way:** the same applies to a Kustomization — the imperative `suspend` on the `longhorn` Kustomization was reverted and let Longhorn briefly reinstall (the resurrection debris). Push the Git removal first, don't rely on an imperative suspend surviving.
- **Tailscale + accept-routes on a LAN-local client is a footgun** — when the cluster/subnet-router is down, the advertised lab-subnet routes blackhole and masquerade as a total cluster outage. Documented in QA.md.

---

## 2026-06-08 — `docs-consolidation`

### Goal
Audit and consolidate the project documentation — fix stale facts, separate agent-facing from human-facing docs, de-duplicate repeated facts, archive the abandoned Longhorn storage-VLAN doc, and cap the ever-growing SESSIONS.md by splitting off an archive.

### What we did
- **Audited the full doc surface** (12 tracked docs + the `.claude/` agent corpus). Confirmed `tmp/`, `.agents/`, and `.claude/skills/` are all gitignored/vendored and out of scope. Classified every doc by primary audience (🤖 agent / 👤 human / 🗄️ history) and found the root problem: the same facts (hardware, "what's deployed", versions) live in 3–4 docs and drift independently with no designated source of truth.
- **Fixed 4 high-severity staleness items.** CLAUDE.md: jumbo-frames `TODO` → "live on all 3 nodes"; cp-03 RAM `92GB` → `96GB ECC`; Longhorn `2-replica interim` → `3-replica` + a new **Rook-Ceph (storage pivot)** row. ROADMAP.md: collapsed the 199-line abandoned *Longhorn Storage Network (Multus + Storage VLAN)* section into a ~30-line **ABANDONED** stub + a new first-class **Rook-Ceph Migration** item — lifting out the still-valid `replicaReplenishmentWaitInterval` tuning and leaving the untouched *cp-02 Thermal Stability* section intact. Reconciled the *Future Storage Options* framing (Rook/Ceph no longer "optional Stage 3").
- **De-duplicated facts.** Made CLUSTER.md the declared source of truth for current-state hardware/networks (CLAUDE.md now links out); reframed POTENTIAL-DEPLOYMENTS.md as an explicitly-secondary *candidate backlog* and fixed its broken `../tmp/home-ops-bykaj` reference → canonical `github.com/bykaj/home-ops`.
- **Created `docs/README.md`** — an audience-labelled index with statuses and a **source-of-truth map** assigning ownership of each shared fact. Fleshed out the root `README.md` stub with a real overview + documentation map (kept the accurate Getting Started section).
- **Archived `docs/longhorn-storage-network.md` → `docs/history/`** (plain `mv`, not `git mv`, to stay unstaged) and distilled its same-host-iSCSI + whereabouts PR #703 root cause into a new QA.md entry, whose heading is anchored to the links placed in CLAUDE.md/ROADMAP. Repointed the inbound links in HARDWARE-ARCHITECTURE.md and REPO-AUDIT.md; left SESSIONS.md's historical path-mentions untouched.
- **Split SESSIONS.md (2871 → 1026 lines, −64%)** at the 2026-05-22 bootstrap/day-2 boundary: the 51 older bootstrap-era sessions (2026-05-06 → 05-21) moved to a new `docs/SESSIONS-ARCHIVE.md` via a lossless character-index cut (32 + 51 = all 83 sessions preserved). Wired cross-pointers in both files, `docs/README.md`, and CLAUDE.md (new sessions always append to the active file; roll the oldest off when it grows again).

### Files changed
| File | Change |
|------|--------|
| `CLAUDE.md` | Hardware SoT pointer + jumbo/RAM fixes; Longhorn 3-replica + Rook-Ceph rows; SESSIONS-archive note |
| `README.md` | Replaced stub banner with project overview + documentation map |
| `docs/README.md` | **New** — audience-labelled doc index + source-of-truth map |
| `docs/ROADMAP.md` | Collapsed abandoned Longhorn-VLAN section → stub; added Rook-Ceph Migration item; reconciled Future Storage Options + TOC |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Reframed as candidate backlog; fixed broken `tmp/` ref → `github.com/bykaj/home-ops` |
| `docs/QA.md` | Added distilled "why storage-VLAN was abandoned" root-cause entry (same-host iSCSI, whereabouts PR #703) + TOC row |
| `docs/REPO-AUDIT.md` | Repointed longhorn-doc path mention to `docs/history/` |
| `docs/HARDWARE-ARCHITECTURE.md` | Repointed broken longhorn-doc link to `history/` |
| `docs/longhorn-storage-network.md` → `docs/history/` | Moved (abandoned topic; full post-mortem preserved) |
| `docs/SESSIONS.md` | Split: kept 2026-05-22→06-05 (32 sessions); archive footer pointer |
| `docs/SESSIONS-ARCHIVE.md` | **New** — bootstrap-era sessions 2026-05-06 → 05-21 (51 sessions) |

### Key decisions
- **Adapted the "2 months" archive heuristic to a 2026-05-22 bootstrap/day-2 boundary** — the whole log spans only ~1 month, so a literal 2-month cutoff would archive nothing. The chosen line is semantically meaningful (setup era vs operations) and yields a clean ~35/65 split.
- **Used Python splices (not the Edit tool) for the 199-line ROADMAP collapse and the SESSIONS split** — exact multi-hundred-line matches are error-prone; anchoring on unique header strings is robust and guarantees the lossless partition.
- **Presented the audit and asked the user to set execution scope before editing** — doc consolidation spans many files and some moves are hard to reverse; the repo's strict no-autonomous-change culture warranted a green light first.
- **Left nothing staged or committed** — per repo rules; the longhorn-doc move surfaces as delete + untracked `history/` until `/git-stage` detects it as a rename.

---

## 2026-06-05 — `longhorn-storagevlan-rollback`

### Goal
Abandon the Longhorn-on-storage-VLAN effort after 5 failed attempts and cleanly remove all of its scaffolding (Multus/whereabouts/NAD/Cilium override + the dead Talos `/28` routes), pivoting storage-VLAN replication to a future Rook-Ceph deployment.

### What we did
- **Mapped the full storage-VLAN footprint** and split it along a GitOps-vs-machine-config seam: everything under `kubernetes/` is self-pruning (delete file → Flux GCs the live object), while the `talconfig.yaml` routes are baked into each node's machine config and only leave via `genconfig` + apply.
- **Part A — GitOps teardown (commit `299904e`).** Deleted the entire `kube-system/multus/` stack (incl. the `448ed24` PR #703 whereabouts backport), the whereabouts OCIRepository source, the `longhorn-storage` NAD + its `longhorn-nad` Kustomization document, and reverted Cilium `cni.exclusive: false`. Refreshed the now-permanent `storageNetwork: ""` comment to point at the Ceph decision. Validated all touched kustomizations with `kubectl kustomize` before committing (+40/−504, overwhelmingly removal).
- **Part B — Talos route removal.** Stripped the cross-node `/28` static routes from all three `bond-storage` blocks in `talconfig.yaml` (kept the bond, `/24` addresses, jumbo MTU — Ceph reuses them). `genconfig` regenerated clean configs; a `--dry-run` apply proved each change is **"Applied configuration without a reboot"** — a live route withdrawal, overturning the doc's inherited assumption that route changes need reboots. Applied cp-01 → cp-03 → cp-02, each verified reboot-free with only the `/24` route remaining.
- **Monitored the reconcile.** Flux picked up `299904e`: multus DaemonSets gone, whereabouts HelmRelease Helm-uninstalled, NodeSlicePool GC'd (the `net-attach-def` CRD itself removed). Cilium Helm upgrade succeeded and rolled its agents to reclaim CNI exclusivity.
- **cp-02 hard-down (2nd occurrence) during the Cilium agent rollout.** cp-02 went `NotReady` — kubelet heartbeat stopped, 100% mgmt-network packet loss, Talos `apid` unreachable; same signature as 2026-06-02. cp-01/cp-03 took the identical Cilium restart cleanly. Confirmed etcd quorum held (2/3), recovered via user power-cycle, then watched all 5 Longhorn volumes rebuild cp-02 replicas back to `healthy` 3/3. Notably, the later reboot-free route apply did **not** trigger another down — narrowing the suspect to agent-restart/eBPF-reload stress.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/**` (9 files) | Deleted the entire Multus + whereabouts stack (incl. PR #703 backport) |
| `kubernetes/apps/kube-system/kustomization.yaml` | Dropped `./multus/ks.yaml` resource |
| `kubernetes/flux/meta/repos/oci/whereabouts-chart.yaml` | Deleted the whereabouts OCIRepository source |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Dropped `./whereabouts-chart.yaml` resource |
| `kubernetes/apps/longhorn-system/longhorn/nad/**` (2 files) | Deleted the `longhorn-storage` NAD |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | Removed the `longhorn-nad` Kustomization document |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Reverted `cni.exclusive: false` → exclusive default |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Refreshed `storageNetwork: ""` comment (abandoned → Ceph) |
| `talos/talconfig.yaml` | Removed cross-node `/28` routes; kept bond/addrs/MTU; updated comments |
| `docs/longhorn-storage-network.md` | Added "⛔ ABANDONED → Rook-Ceph" banner (history preserved) |

### Key decisions
- **Abandoned Longhorn-on-storage-VLAN rather than pursue Attempt 6.** The whereabouts chroot blocker was solved, but same-host iSCSI over ipvlan-L3 is structurally unsolvable here; Rook-Ceph's native `cluster_network` on `hostNetwork` OSDs sidesteps it entirely with no CNI.
- **Kept the `bond-storage` fabric (interface, `/24` addresses, jumbo MTU).** Removing only the ipvlan-L3-specific `/28` routes leaves the storage VLAN clean and Ceph-ready.
- **Dry-ran the Talos apply before committing to it.** Confirming the route removal was reboot-free eliminated the staggered-reboot ceremony and, crucially, the exposure to cp-02's reboot fragility.
- **Recorded the cp-02 recurrence as a real data point** (now 2-for-2 with network-stack reconciles, both during agent churn, never during a live config edit) in the open `cp02-outage-investigation`.

---

## 2026-06-02 — `longhorn-storagenetwork-attempt5`

### Goal
Backport the unreleased upstream whereabouts fix to break the multus-chroot node-name blocker, validate per-node `node_slice_size` IPAM in isolation, then attempt the Longhorn `storageNetwork` flip — which failed on the same-host iSCSI path and was rolled back, restoring service.

### What we did
- **Pinned the Attempt-4 blocker to upstream.** Read the v0.9.3 whereabouts source: `getNodeName` resolves node identity as `$NODENAME` env → `<configuration_path>/nodename` file → `/etc/hostname`. The CNI plugin runs in the multus `chroot:/hostroot`, so it never inherits the daemon's `NODENAME` env and Talos has no `/etc/hostname` → nil-pointer panic. Exact match for open upstream issue **#518**; the fix is PR **#703**, which **merged to `master` on 2026-06-02 but is unreleased** (latest release v0.9.3 predates it) — so no chart bump was available.
- **Backported PR #703 (`448ed24`, KEPT).** Replaced the insufficient `/etc/hostname` emptyDir postRenderer with a DaemonSet `args` override that, after `install-cni.sh`, injects `"configuration_path": "/etc/cni/net.d/whereabouts.d"` into the flatfile `whereabouts.conf` and writes `$NODENAME` to `/host/etc/cni/net.d/whereabouts.d/nodename`. Both land in the host CNI dir (writable on Talos, unlike `/etc/hostname`). Sharp edge confirmed from source: `configuration_path` must live in the flatfile, **not** the NAD — `GetFlatIPAM` treats a NAD value as a *file* and `io.ReadAll`s a directory.
- **Validated in isolation (gate passed).** All 3 whereabouts pods rolled clean (no panic); verified the on-host `nodename` + `configuration_path` files via `talosctl read`; throwaway probe pods pinned per node each pulled their `/28` slice's first IP through the chroot — cp-01 `10.200.0.65`, cp-02 `.81`, cp-03 `.97` — the exact path that panicked in Attempts 3–4.
- **Quiesced + flipped (`d6be5da`).** Suspended HelmReleases `pgadmin`/`waha`/`kube-prometheus-stack`, scaled Deployments to 0, patched Prometheus/Alertmanager **CR** replicas to 0; all 5 volumes detached. Set `storageNetwork: "kube-system/longhorn-storage"`. Flux reconciled; instance-managers recreated with `lhnet1` attached at the correct per-node `/28` IPs (`.65`/`.81`/`.97`).
- **FAILED on same-host iSCSI.** All 5 engines co-located on cp-03 stuck `starting`; volumes cycled `attaching ↔ detaching`. Host routing showed the plan's load-bearing assumption was wrong: the kernel does **not** add a `/32` route to a local pod's ipvlan IP (the slave lives in the pod netns), and ipvlan L3 suppresses ARP — so a node cannot reach a pod's storage IP on its **own** host. Cross-node `/28` routes worked; same-host is structurally broken in this design (same wall as Attempts 1–2).
- **Rolled back (`f719cef`) and recovered service.** `git revert d6be5da` + push set `storageNetwork: ""`. Longhorn cleared the setting (`value=""`, `applied=false`) but deadlocked — the old IMs kept `lhnet1` and volumes never cleanly detached. Broke the deadlock by deleting the instance-manager pods (user-run; the classifier blocked agent attempts at the live setting patch / HR suspend / IM deletion as out-of-band infra changes). Recreated IMs came up clean; all 5 volumes re-attached on the pod network (2 `healthy`, 3 `degraded` rebuilding at session end); consumers recovered.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | Replaced `/etc/hostname` emptyDir postRenderer with PR #703 backport — `configuration_path` in flatfile + `nodename` file via DaemonSet `args` override — `448ed24` (**kept**) |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Enabled then reverted `storageNetwork` — `d6be5da`, `f719cef` (net unchanged) |
| `docs/longhorn-storage-network.md` | Added Attempt 5 section then reverted with the flip — `d6be5da`, `f719cef` (net unchanged; **re-add pending**) |

### Key decisions
- **Backported the unreleased PR #703** (~5 lines via postRenderer) rather than wait for a whereabouts release or jump to Ceph — it was the sole blocker. Tracked to remove when a release > 0.9.3 ships it.
- **Two-phase gated rollout** — validating IPAM in isolation before the disruptive flip is exactly why the flip's failure was unambiguously attributable to same-host routing, not the CNI fix.
- **Rolled back via Git, not a live patch** — the classifier (correctly) blocked out-of-band mutation of shared Longhorn infra; the user ran the IM-pod deletion to break Longhorn's detach deadlock.
- **same-host iSCSI over ipvlan L3 remains unsolved** — the `/28`+static-routes scheme only fixes cross-node. Next options: host-side ipvlan shim (route to local pod IPs), ipvlan L3S, or Rook-Ceph (native dual-network). The Attempt-5 writeup must be re-added to `docs/longhorn-storage-network.md` (lost in the revert).

---

## 2026-06-02 — `longhorn-storagenetwork-attempt4`

### Goal
Re-enable Longhorn `storageNetwork` over the ipvlan-L3 storage VLAN (attempt 4) by fixing the whereabouts `/etc/hostname` panic and the multus OOM crash-loop — ultimately blocked by a multus-chroot root cause and reverted, with recovery from a mid-migration cp-02 hard-down.

### What we did
- **whereabouts `/etc/hostname` fix (`3c624a8`)**: the chart has no `initContainers` hook, so injected one via a Flux **`postRenderers`** Kustomize patch on the HelmRelease. First cut wrote to a hostPath host `/etc` and failed (`Read-only file system`); reworked to an `emptyDir` + `subPath` populating the daemon pod's own `/etc/hostname`. Verified all 3 whereabouts pods healthy with correct per-node hostname (v3 deployed).
- Unstuck a Flux/Helm deadlock: the first render wedged the release in `pending-upgrade` (helm `--wait` on a crash-looping pod); restarting the helm-controller pod cleared the stale operation and applied the corrected render.
- **multus OOM fix (`49ea52c`)**: discovered `kube-multus-ds` on cp-02 in `CrashLoopBackOff` (22 restarts, `OOMKilled` exit 137) — the 50Mi limit couldn't service the burst of queued CNI ADD requests, blocking ALL pod sandbox creation on the node and degrading every Longhorn volume. Raised limit to 256Mi, dropped the CPU limit. cp-02 recovered, instance-manager started, all 5 volumes rebuilt to `healthy` 3/3.
- **storageNetwork re-enable (`0edb316`) + quiesce**: suspended the consuming workloads' HelmReleases and scaled consumers to 0 (patched Prometheus/Alertmanager **CR** `replicas`, not the operator-managed StatefulSets); volumes detached cleanly.
- **Definitive blocker found**: re-enabling made instance-managers request `lhnet1` and IP allocation **still panicked** on `/etc/hostname`. Root cause: the whereabouts **CNI plugin** (not the daemon pod) runs inside the multus thick-daemon's **`chroot:/hostroot`**, so it reads the **host's** `/etc/hostname` — absent on Talos, read-only `/etc`. The daemon-pod fix never reaches that context.
- **Reverted (`ad1666a`)** to restore service. Cleared the setting, deleted wedged instance-manager pods carrying the stale `lhnet1` annotation, resumed HelmReleases.
- **cp-02 hard-down incident**: during the migration thrash cp-02 went unreachable on BOTH NICs (talosctl `no route to host`, kubelet heartbeat stopped 15:32:45). User power-cycled; cp-02 rejoined cleanly and volumes rebuilt to `healthy` 3/3. Post-reboot `dmesg` held only the current boot — pre-crash logs lost (ring buffer reset). Root cause deferred to a tracked follow-up; multus held at 256Mi through the reboot with only 1 restart.
- Updated `docs/longhorn-storage-network.md` with the Attempt 4 outcome, chroot root cause, recovery procedure, and Attempt 5 research direction; saved an open cp-02-outage investigation note to persistent memory.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | Added `postRenderers` patch injecting `/etc/hostname` initContainer (emptyDir + subPath) — `3c624a8` |
| `kubernetes/apps/kube-system/multus/app/multus-daemonset.yaml` | Raised daemon memory limit 50Mi→256Mi, dropped CPU limit — `49ea52c` |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Re-enabled then reverted `storageNetwork`; comment documents the multus-chroot blocker — `0edb316`, `ad1666a` |
| `docs/longhorn-storage-network.md` | Documented Attempt 4 outcome, chroot root cause, cp-02 incident, recovery procedure, Attempt 5 direction (uncommitted) |

### Key decisions
- Used Flux `postRenderers` rather than chart values — the whereabouts chart exposes no `initContainers`/`extraVolumes` hooks.
- Targeted the daemon pod's own `/etc/hostname` (emptyDir+subPath) because the host `/etc` is read-only on Talos and `hostNetwork` shares only the net namespace — though this later proved insufficient for the CNI-plugin allocation path.
- Sequenced as separate pushes (multus OOM fix validated to full health *before* the storageNetwork re-enable) so a risky change wasn't coupled to a still-recovering node.
- Reverted rather than pushing forward: the chroot blocker is design-level (needs Option B node-identity-without-host-hostname or Option C per-node IPPools), not a live-cluster guess — restore service first.
- cp-02 root cause deliberately deferred: pre-crash kernel logs were unrecoverable post-reboot, so investigation is tracked separately rather than blocking recovery.

---

## 2026-06-02 — `postgres-backup-monitoring`

### Goal
Add a liveness probe and Prometheus alerting rules to the postgres-backup-local CronJob for container-level health enforcement and cluster-level failure detection.

### What we did
- Added `HEALTHCHECK_PORT: "8080"` env var to the backup container so it exposes an HTTP health endpoint on port 8080
- Wired a custom liveness probe (`httpGet /` on port 8080) with `initialDelaySeconds: 7200` (2h) to match the backup window, `failureThreshold: 1`, `periodSeconds: 60` — tight dead-man's switch at the container layer
- Created `prometheusrule.yaml` with two alerts:
  - `PostgresBackupMissed` — dead-man's switch using `kube_cronjob_status_last_successful_time`; fires (critical) if no successful backup in 25h or the CronJob disappears entirely
  - `PostgresBackupJobFailed` — fires (warning) when any `postgres-backup-local-*` Job records a failure; auto-resolves when the failed Job is GC'd
- Registered the new PrometheusRule in `kustomization.yaml`
- Committed as `8d12e96`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/helmrelease.yaml` | Added `HEALTHCHECK_PORT: "8080"` env var and custom liveness probe |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/kustomization.yaml` | Added `prometheusrule.yaml` as a resource |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/prometheusrule.yaml` | New file — PrometheusRule with `PostgresBackupMissed` and `PostgresBackupJobFailed` alerts |

### Key decisions
- `initialDelaySeconds: 7200` matches the backup duration window; setting it shorter would kill the pod mid-backup
- Alert threshold is 90000s (25h not 24h) to absorb slight CronJob scheduling drift without false positives
- Used `kube_cronjob_status_last_successful_time` from kube-state-metrics (already present) rather than adding custom metrics to the backup container — zero instrumentation overhead

---

## 2026-05-31 — `multus-nad-talos-setup`

### Goal
Deploy Multus CNI + whereabouts IPAM, create a macvlan NAD on the storage VLAN, rename storage bonds to `bond-storage` across all 3 Talos nodes, and enable Longhorn's `storageNetwork` setting to move engine↔replica traffic off the Cilium pod network.

### What we did
- Continued from compacted context (previous session hit context limit mid-implementation); completed all Phase 2 manifests — vendored Multus thick DaemonSet v4.2.4 split into 4 files (CRD, RBAC, ConfigMap, DaemonSet), whereabouts HelmRelease with `chartRef` → new `whereabouts-chart` OCIRepository (tag `0.9.3`), configMapGenerator + kustomizeconfig for values
- Extended `longhorn/ks.yaml` to multi-doc: added `longhorn-nad` Kustomization with `dependsOn: [multus, longhorn]`; added `nad/storage-nad.yaml` macvlan NAD on master `bond-storage`, whereabouts range `10.200.0.64/26`, MTU 9000
- Committed and pushed `82bc07a` (feat(longhorn): deploy Multus CNI and storage VLAN network isolation); monitored Flux reconciliation live via MCP tools
- **Three consecutive image fixes** during live reconciliation monitoring:
  - `docker.io/containernetworking/plugins:v1.9.1` — tag does not exist; `containernetworking/plugins` never publishes to Docker Hub
  - `ghcr.io/k8snetworkplumbingwg/plugins:v1.6.2` — pulled successfully but image only contains k8snetworkplumbingwg extra plugins (no macvlan/ipvlan)
  - `ghcr.io/siderolabs/cni:v1.13.0` directly — correct binaries confirmed via `crane export`; image is distroless (no shell), `sh -c "cp ..."` fails with `exec: "sh": not found`
  - **Final fix** (`8301702`): used K8s `imageVolume` (beta in 1.36, confirmed available via dry-run) to mount `siderolabs/cni:v1.13.0` as read-only volume + `busybox` init container to copy macvlan/ipvlan; binary paths `/opt/cni/bin/macvlan` and `ipvlan` confirmed via `crane export`
- Monitored full reconciliation to green: whereabouts 3/3, Multus DaemonSet 3/3 Running, NAD `longhorn-storage` created in `longhorn-system`, Kustomizations `multus` and `longhorn-nad` both `Applied revision: 8301702`
- Verified macvlan + ipvlan + multus-shim binaries present in `/opt/cni/bin/` on all nodes via `talosctl ls`
- Applied Talos machine configs to all 3 nodes (`task talos:apply IP=10.60.0.20X`) — all applied live without reboot; `bond-storage` with `10.200.0.201/202/203` confirmed live on all nodes via `talosctl get addresses`
- Phase 4: added `storageNetwork: "longhorn-system/longhorn-storage"` to Longhorn values; verified all 8 PVCs are RWO (no RWX detach constraint); ready to commit/push

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Renamed storage bonds: bond0→bond-storage (cp-01, cp-02), bond1→bond-storage (cp-03) |
| `kubernetes/flux/meta/repos/oci/whereabouts-chart.yaml` | New OCIRepository for `ghcr.io/k8snetworkplumbingwg/whereabouts-chart:0.9.3` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added whereabouts-chart entry |
| `kubernetes/apps/kube-system/kustomization.yaml` | Added `./multus/ks.yaml` |
| `kubernetes/apps/kube-system/multus/ks.yaml` | New Kustomization; dependsOn cilium; healthChecks DaemonSet + whereabouts HelmRelease |
| `kubernetes/apps/kube-system/multus/app/kustomization.yaml` | New; configMapGenerator for whereabouts values |
| `kubernetes/apps/kube-system/multus/app/multus-crd.yaml` | New; vendored NetworkAttachmentDefinition CRD from Multus v4.2.4 |
| `kubernetes/apps/kube-system/multus/app/multus-rbac.yaml` | New; vendored ClusterRole/ClusterRoleBinding/ServiceAccount |
| `kubernetes/apps/kube-system/multus/app/multus-configmap.yaml` | New; vendored multus-daemon-config ConfigMap |
| `kubernetes/apps/kube-system/multus/app/multus-daemonset.yaml` | New; vendored DaemonSet v4.2.4-thick; imageVolume pattern for CNI plugin install |
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | New; HelmRelease using chartRef OCIRepository |
| `kubernetes/apps/kube-system/multus/app/helm/whereabouts-values.yaml` | New; NoExecute toleration + resource limits |
| `kubernetes/apps/kube-system/multus/app/helm/kustomizeconfig.yaml` | New; nameReference for ConfigMap hash propagation |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | Extended to multi-doc; added longhorn-nad Kustomization |
| `kubernetes/apps/longhorn-system/longhorn/nad/kustomization.yaml` | New |
| `kubernetes/apps/longhorn-system/longhorn/nad/storage-nad.yaml` | New macvlan NAD; master bond-storage; whereabouts 10.200.0.64/26 |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Added replicaReplenishmentWaitInterval 900s (committed); storageNetwork setting (pending commit) |

### Key decisions
- **imageVolume pattern for distroless source**: K8s 1.36 `imageVolume` (beta) mounts a container image filesystem as read-only; lets `busybox` copy specific binaries from `siderolabs/cni` without needing a shell in the source image — cleaner than runtime GitHub downloads
- **siderolabs/cni as CNI plugin source**: Talos's own CNI bundle matches running Talos version; `crane export` confirmed macvlan+ipvlan at `/opt/cni/bin/`; `containernetworking/plugins` never publishes images; `k8snetworkplumbingwg/plugins` is extra plugins only
- **macvlan over ipvlan**: Both work on bare metal; macvlan is the Longhorn-documented default; ipvlan is preferred for cloud/hypervisor environments with MAC spoofing enforcement (not applicable here)
- **`storageNetwork` affects more than RWX**: Longhorn chart comment says "mounting RWX volumes" but the setting also attaches secondary interfaces to instance-manager pods (all volume I/O); all cluster PVCs are RWO so no RWX detach constraint applies
- **No reboot required for bond rename**: Talos applies network interface name changes live via its network controller; all 3 nodes accepted the bond-storage rename without rebooting

---

## 2026-05-30 — `hardware-monitoring`

### Goal
Audit hardware sensor coverage, then deploy Grafana (with pre-built dashboards), a privileged `smartctl-exporter` DaemonSet for SMART disk health, and PrometheusRules for hardware temperature alerting.

### What we did
- Audited hardware monitoring coverage: confirmed `prometheus-node-exporter` DaemonSet already collects CPU/mem/disk/network; queried `talosctl ls /sys/class/hwmon` across all 3 nodes — all key temperature drivers already auto-loaded (`coretemp` on cp-01/cp-02, `k10temp` on cp-03 MS-A2, `nvme` × 2 per node, `nct6686` super-I/O on M920Q, `ixgbe` NIC on cp-02)
- Sampled live sensor readings: cp-01 CPU 49°C, cp-02 CPU 38°C, cp-03 AMD Tctl 69°C (elevated — mini-PC chassis), NVMe composite 44–53°C; identified `nct6686` Thermistor 7 at 127°C as a phantom (unconnected thermistor input, not a real alert)
- Researched bykaj reference: their `smartctl-exporter` ScrapeConfig points to `${NAS_HOST}:9633` — not a K8s DaemonSet; bykaj runs Talos VMs on Proxmox so the hypervisor layer covers disk health; bare-metal deployment requires an in-cluster DaemonSet instead
- Enabled Grafana in kube-prometheus-stack: 5 Gi Longhorn PVC, `Recreate` strategy, admin password via ExternalSecret from 1Password `grafana` item, `forceDeployDashboards: true`, sidecar searching all namespaces, `root_url` set for proper redirect handling
- Added `grafana.${DOMAIN_CLUSTER}` HTTPRoute on `envoy-internal` pointing at `kube-prometheus-stack-grafana:80`
- Deployed `prometheus-smartctl-exporter` as a privileged DaemonSet (chart `0.16.1`, app `v0.14.0`): chart hardcodes `privileged: true` + `/dev` hostPath mount, auto-scans NVMe devices, `observability` namespace already has `pod-security.kubernetes.io/enforce: privileged`; built-in SMART health PrometheusRules enabled (media errors, critical warning, spare threshold, device status), SMART temperature rule disabled in favour of hwmon
- Created `hardware-temps` PrometheusRule: CPU warning >80°C / critical >90°C scoped to `coretemp.*|k10temp.*` (naturally excludes nct6686 phantom); NVMe warning >65°C / critical >75°C via `nvme.*` hwmon chip

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/smartctl-exporter.yaml` | New OCIRepository for `prometheus-community/charts/prometheus-smartctl-exporter:0.16.1` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `smartctl-exporter.yaml` resource |
| `kubernetes/apps/observability/smartctl-exporter/ks.yaml` | New Kustomization; `dependsOn: kube-prometheus-stack` |
| `kubernetes/apps/observability/smartctl-exporter/app/kustomization.yaml` | New; ConfigMapGenerator for values |
| `kubernetes/apps/observability/smartctl-exporter/app/helmrelease.yaml` | New HelmRelease using smartctl-exporter OCIRepository |
| `kubernetes/apps/observability/smartctl-exporter/app/helm/values.yaml` | New; ServiceMonitor + SMART health rules enabled, temperature rule disabled |
| `kubernetes/apps/observability/kustomization.yaml` | Added `smartctl-exporter/ks.yaml` resource |
| `kubernetes/apps/observability/kube-prometheus-stack/app/externalsecret.yaml` | New; pulls `ADMIN_PASSWORD` from 1Password `grafana` → `grafana-admin-secret` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Grafana enabled; persistence, admin secret, dashboard sidecar, tolerations, `root_url` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml` | Added `grafana.${DOMAIN_CLUSTER}` HTTPRoute |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Added `externalsecret.yaml` and `prometheusrules` directory |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml` | New PrometheusRule: CPU + NVMe temperature alerts |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/kustomization.yaml` | New; resources the hardware-temps rule |

### Key decisions
- **Chip-scoped temperature alerts (`coretemp.*|k10temp.*`)** rather than a broad `node_hwmon_temp_celsius > N` — avoids nct6686 Thermistor 7 phantom reading (127°C) triggering false critical alerts on M920Q nodes without needing an explicit exclusion filter
- **SMART temperature rule disabled** in smartctl-exporter PrometheusRules — NVMe SMART temperatures are sampled by the drive firmware and less precise than kernel hwmon; hwmon composite temp (`nvme.*`) is more representative for alerting
- **`Recreate` deployment strategy for Grafana** — Longhorn PVC is `ReadWriteOnce`; a rolling update would try to attach the volume to two pods simultaneously and stall

---

## 2026-05-30 — `jumbo-frames-storage-vlan`

### Goal
Benchmark storage VLAN throughput between Talos nodes and TrueNAS, then implement MTU 9000 jumbo frames across all storage bonds and Cilium to reduce switch incast retransmits.

### What we did
- Ran iperf3 benchmarks from Kubernetes pods (pod-network and host-network) against TrueNAS (10.200.0.41); demonstrated LACP layer3+4 hashing behaviour and why all 4 `-P 4` streams hash-collided onto one bond member (port numbers differing only in low 6 bits, discarded by `>> 6` shift)
- Established that host-network pods bound to the storage VLAN IP (`-B 10.200.0.201`) bypass Cilium overlay and measure the raw bond path: single stream 9.42 Gbps vs 5.49 Gbps through Cilium (40% overhead from encapsulation suppressing CUBIC cwnd growth)
- Showed 16-stream test at MTU 1500 yielded 13.4 Gbps with 181,203 retransmits — identified switch incast (too many packets per second overflowing port buffers) as the binding constraint, not LACP distribution
- Implemented MTU 9000: updated `talconfig.yaml` storage bonds (cp-01 `bond0`, cp-02 `bond0`, cp-03 `bond1`) from `mtu: 1500` to `mtu: 9000`, removed TODO comments; added `MTU: 9000` to Cilium values and corrected wrong interface-name comment (had cp-01/cp-03 layout swapped); ran `talhelper genconfig`
- Applied configs node-by-node with MTU and Ready verification between each; cp-01 live with no reboot; cp-02 rebooted unexpectedly (M920Q thermal protection, BIOS hard power-cut leaving no dmesg trace — unrelated to config change), recovered and MTU confirmed; cp-03 applied without reboot
- Held cp-03 apply while cp-02 was offline to preserve 2/3 etcd quorum; diagnosed link-selector warnings as cosmetic (LACP bond MAC propagates to both slaves, alias controller skips — bond operational)
- Post-MTU 16-stream test: 14.2 Gbps, 40,086 retransmits (−78%); single stream 9.90 Gbps; identified BBR congestion control as next step to reduce remaining CUBIC incast backoff

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Changed storage bond mtu 1500→9000 on cp-01 (bond0), cp-02 (bond0), cp-03 (bond1); removed TODO comments |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Added `MTU: 9000`; corrected interface layout comment (had cp-01 and cp-03 swapped) |

### Key decisions
- **Host-network pods with `-B <storage-IP>`** for raw bond measurements — pod-network path through Cilium suppresses CUBIC cwnd growth and is not representative of NFS storage performance
- **Explicit `MTU: 9000` in Cilium values** — Cilium native-routing mode auto-detects MTU from the default-route interface (management NIC, 1500 MTU), so pod veth interfaces would remain at 1500 even after bond change without an explicit override
- **Node-by-node apply with etcd quorum guard** — never applied cp-03 while cp-02 was down; a second simultaneous failure would have dropped etcd to 1/3 and made the cluster API read-only

---

## 2026-05-29 — `postgres-nfs-backup`

### Goal
Deploy and verify a daily `pg_dumpall`-based NFS backup CronJob for the `postgres-v17` cluster, writing to TrueNAS over the storage VLAN.

### What we did
- Confirmed ExternalSecret `dataFrom+rewrite` migration was fully complete: verified all 12 cluster ExternalSecrets `SecretSynced: True` via `kubectl get externalsecrets -A`; updated ROADMAP.md to move the item to Completed
- Designed TrueNAS NFS configuration: dedicated dataset `/mnt/tank/Cluster/cloudnative-pg` on `tank` pool; NFS share on storage VLAN via `bond1` (10.200.0.41/24); dataset `chown 4000:4000` for non-root container; `maproot: root` not needed since UID 4000 passes through numerically without a named user
- Built `postgres-backup-local` app-template v5 CronJob: `POSTGRES_CLUSTER: "TRUE"` for `pg_dumpall`, `POSTGRES_DB: postgres` to satisfy image validation, `POSTGRES_EXTRA_OPTS: "-c"` only (pg_dumpall doesn't accept `-Z` or `-C`); daily schedule with 7d/4w/6m retention; runs as UID 4000 (`runAsNonRoot: true`); `enableServiceLinks: false`; `ttlSecondsAfterFinished: 43200`
- Added Flux Kustomization to `cloudnative-pg/ks.yaml` as third doc with `dependsOn: cloudnative-pg-cluster`; reuses existing `cloudnative-pg-secret` rather than a new ExternalSecret
- Debugged three live failures: (1) `SYN_SENT` — TrueNAS NFS not bound to bond1 interface; (2) `database "backups" does not exist` — `POSTGRES_DB: "*"` glob-expands to `/backups` mount dir in script working dir; (3) `invalid option -- 'Z'` — pg_dumpall doesn't accept `-Z6`
- Fixed all three issues iteratively via live `kubectl patch cronjob` + manual job triggers; verified `Completed` pod with correct symlinks (`daily/`, `weekly/`, `monthly/`, `last/`) on TrueNAS
- Added restore drill roadmap entry with step-by-step `pg_dumpall` restore procedure and drill checklist

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Added `postgres-backup-local` Kustomization as third doc |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/helmrelease.yaml` | Created: app-template v5 CronJob with NFS persistence, UID 4000, pg_dumpall config |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/kustomization.yaml` | Created: Kustomize entry-point |
| `docs/ROADMAP.md` | Marked ExternalSecret migration complete; marked NFS backup item ✅ with gotchas; added restore drill entry |

### Key decisions
- **Storage VLAN (10.200.0.41) over management VLAN** — TrueNAS has bond1 on the same storage fabric as the node storage bonds; isolates backup traffic from kube-apiserver/etcd on the management NIC
- **UID 4000 (non-root) over root** — matches both reference implementations; requires one `chown 4000:4000` on TrueNAS but eliminates rootless-root in the database namespace; numeric UID works without a named user on TrueNAS
- **`POSTGRES_CLUSTER: "TRUE"` over `POSTGRES_DB: "*"`** — `*` glob-expands to the NFS mount directory name in the script's working directory; `pg_dumpall` is also future-proof for new databases added to the shared cluster
- **Reuse `cloudnative-pg-secret`** over a new ExternalSecret — credentials already present in the `database` namespace; avoided duplicating the same 1Password fields

---

## 2026-05-29 — `pgadmin-deploy`

### Goal
Deploy pgAdmin as a web-based admin UI for the shared `postgres-v17` CNPG cluster, living in the `database` namespace alongside the cluster it manages.

### What we did
- Discussed CNPG pod distribution: established that `podAntiAffinityType: required` prevents initial co-location but does not change node-failure recovery behaviour because `openebs-hostpath` PVCs are node-local regardless; the PVC's own node-affinity is the binding scheduling constraint on failure
- Discussed CNPG automatic failover: confirmed the operator promotes the most up-to-date standby (synchronous standby preferred), re-targets the `postgres-v17-rw` Service, and rejoins the old primary as standby via `pg_rewind` once its node recovers — no manual intervention
- Researched pgAdmin patterns on kubesearch.dev and studied both `tmp/home-ops-bykaj` and `tmp/home-ops.old` reference implementations; chose the `dpage/pgadmin4` image with `ghcr.io/home-operations/k8s-sidecar` initContainer pattern
- Created pgAdmin Kustomization with `dependsOn: cloudnative-pg-cluster + onepassword-store`; kept in `database` namespace alongside CNPG (single namespace simpler for future NetworkPolicy rules)
- HelmRelease (app-template v5): initContainer creates per-user storage folder and seeds `.pgpass` with correct permissions (chmod 600); Longhorn 2Gi PVC for config data so pod can reschedule across nodes after failure; startup + liveness/readiness probes on `/misc/ping`; `PGADMIN_REPLACE_SERVERS_ON_STARTUP: "True"` makes server config declarative
- ExternalSecret pulls from two 1Password items: `pgadmin` (→ `PA_` prefix, email + password) and `cloudnative-pg` (→ `DB_` prefix, reusing existing superuser fields); template produces `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`, `pgpass`, and `servers.json` keys in a single Secret
- `servers.json` hardcodes `postgres-v17-rw.database.svc.cluster.local` as the connection target with `sslmode: prefer` and `passfile: /.pgpass`; no Flux substitution variables needed
- Compared old reference initContainer (function-based, multi-user, backup symlink, `/tmp/secrets/pgpass`) vs current implementation (inline, single-user, `/tmp/secrets/.pgpass` via subPath); all differences are intentional simplifications for single-admin home lab without backup volumes
- HTTPRoute on `envoy-internal` → `pgadmin.${DOMAIN_CLUSTER}` (LAN-only); standalone `httproute.yaml` following cluster convention

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/pgadmin/ks.yaml` | Created: Flux Kustomization; dependsOn cloudnative-pg-cluster + onepassword-store |
| `kubernetes/apps/database/pgadmin/app/kustomization.yaml` | Created: Kustomize entry-point |
| `kubernetes/apps/database/pgadmin/app/helmrelease.yaml` | Created: app-template v5 with initContainer, Longhorn PVC, probes, envFrom |
| `kubernetes/apps/database/pgadmin/app/externalsecret.yaml` | Created: pulls pgadmin + cloudnative-pg items; produces pgpass + servers.json |
| `kubernetes/apps/database/pgadmin/app/httproute.yaml` | Created: HTTPRoute on envoy-internal for pgadmin.${DOMAIN_CLUSTER} |
| `kubernetes/apps/database/kustomization.yaml` | Added `./pgadmin` resource |

### Key decisions
- **`database` namespace over `tools`**: co-location simplifies future NetworkPolicy allow-rules (pgAdmin is inside the namespace it talks to); easy to move later if a general `tools` namespace emerges
- **Longhorn PVC (not openebs-hostpath)**: pgAdmin is a single-pod stateless-ish app — Longhorn allows pod to reschedule to any node after a node failure, unlike openebs-hostpath which is node-local
- **No OIDC/OAuth2**: dropped from references (requires Authentik, not deployed); `internal` auth only; can be layered on later
- **Hardcoded DB hostname in ExternalSecret template**: avoids Flux substitution variables in the ESO template layer; `postgres-v17-rw.database.svc.cluster.local` is stable and doesn't need to be parameterised
- **`podAntiAffinityType: required` on CNPG cluster** (committed in previous session): hard placement guarantee at initial scheduling; no effect on recovery since openebs-hostpath PVC node-affinity is the real binding constraint

---

## 2026-05-29 — `cloudnative-pg-deploy`

### Goal
Deploy CloudNativePG operator and a shared 3-instance PostgreSQL 17 cluster as new database infrastructure for the home-lab cluster.

### What we did
- Researched CNPG community patterns on kubesearch.dev and studied the `tmp/home-ops-bykaj` reference (operator/cluster/barman-cloud/postgres-backup-local structure, ObjectStore CR, ExternalSecret pattern, PrometheusRules, variable-substituted cluster naming for major-version upgrades)
- Decided on a single shared `postgres-v17` cluster (not per-app) and deferred S3/barman-cloud backup to a future session; cluster has HA via 3-replica streaming replication with no PITR until backup is wired in
- Verified current chart version `0.28.2` via `gh api` GHCR query; added OCIRepository to `flux/meta/repos/oci/`
- Created `database` namespace and top-level kustomization; wired into `kubernetes/apps/kustomization.yaml`
- Created multi-doc `ks.yaml` following CLAUDE.md operator+CRD pattern: `cloudnative-pg-operator` (wait+healthChecks, dependsOn cert-manager) and `cloudnative-pg-cluster` (dependsOn operator + onepassword-store)
- CNPG operator HelmRelease: `crds.create: true`, `monitoring.podMonitorEnabled: true`, Grafana dashboard enabled; PrometheusRule with 7 alert rules (replication lag, XID age, WAL archiver failure, deadlocks, backend waits, long transactions, replica WAL receiver down)
- `postgres-v17` Cluster CR: 3 instances, `openebs-hostpath` 20Gi, `initdb` bootstrap (fresh cluster), `enablePodMonitor: true`, synchronous replication (any 1 standby), `enablePDB: false` (CNPG issue #2570)
- ExternalSecrets updated to CONVENTIONS.md pattern: `dataFrom.extract` + `rewrite: CNPG_$1` + `template` mapping to CNPG's expected `username`/`password` keys; 1Password fields prefix-free (`SUPER_USER`, `SUPER_PASS`, `BOOTSTRAP_USER`, `BOOTSTRAP_PASS`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/cloudnative-pg.yaml` | Created: OCIRepository for CNPG chart, tag 0.28.2, Renovate-tracked |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added cloudnative-pg.yaml resource |
| `kubernetes/apps/kustomization.yaml` | Added `./database` resource |
| `kubernetes/apps/database/namespace.yaml` | Created: Namespace database |
| `kubernetes/apps/database/kustomization.yaml` | Created: aggregates namespace.yaml + cloudnative-pg |
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Created: multi-doc Kustomizations (operator + cluster) |
| `kubernetes/apps/database/cloudnative-pg/kustomization.yaml` | Created: includes ks.yaml |
| `kubernetes/apps/database/cloudnative-pg/operator/app/helmrelease.yaml` | Created: CNPG operator HelmRelease with monitoring |
| `kubernetes/apps/database/cloudnative-pg/operator/app/prometheusrule.yaml` | Created: 7 PrometheusRule alert rules |
| `kubernetes/apps/database/cloudnative-pg/operator/app/kustomization.yaml` | Created |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Created: postgres-v17 Cluster CR, 3 instances, openebs-hostpath |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/externalsecret.yaml` | Created: superuser + bootstrap ExternalSecrets, rewrite+template pattern |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/kustomization.yaml` | Created |

### Key decisions
- `openebs-hostpath` over Longhorn for PostgreSQL storage: CNPG replicates data across 3 pods itself; Longhorn would add double-replication with I/O amplification and no reliability benefit
- S3 backup (barman-cloud plugin) deferred: user chose HA-only for initial deployment; PITR can be layered on without recreating the cluster
- `enablePDB: false` following bykaj reference (CNPG issue #2570): default PDB can block Talos node drain during upgrades on a 3-control-plane-only cluster
- Chart pinned at `0.28.2` (verified via `gh api` GHCR query) rather than guessing a version; Renovate tracks future releases via `datasource=docker` comment

---

## 2026-05-29 — `external-services-truenas`

### Goal
Audit bykaj's external-services pattern, evaluate envoy-internal reuse vs a dedicated envoy-services gateway, document the decision, and implement the pattern for TrueNAS as the first LAN resource proxy.

### What we did
- Audited `bykaj/home-ops` external-services: identified three routing variants (plain HTTP via `HTTPRoute`, TLS passthrough via `TLSRoute`, FQDN-based via Envoy `Backend` CRD with ConsistentHash LB for Proxmox session affinity); noted EndpointSlice label requirements (`kubernetes.io/service-name`, `endpointslice.kubernetes.io/managed-by`) and a port mismatch in `proxmox-backup-server`
- Evaluated dedicated `envoy-services` gateway vs reusing `envoy-internal`; decided on reuse — no TLS passthrough or IP-level ACL requirements at this stage, and adding a `TLS: Passthrough` listener to `envoy-internal` would widen its surface area unnecessarily
- Added Scenario 4 (LAN resource proxy) to `docs/CLUSTER.md` with a complete 3-file YAML example and `external-services/` directory convention; added forward reference to ROADMAP.md for TLS passthrough path
- Added "Dedicated `envoy-services` Gateway (Future)" to `docs/ROADMAP.md` under Researched Patterns with three concrete migration triggers (IP-level ACLs, TLS passthrough, scale) and cost estimate (+3 Envoy pod replicas, +1 CiliumLB IP)
- Created `kubernetes/apps/network/external-services/truenas/`: `EndpointSlice` → `10.10.0.41:8080`, headless `Service` (no selector), `HTTPRoute` on `envoy-internal` → `truenas.${DOMAIN_CLUSTER}`; top-level `ks.yaml` with `targetNamespace: network` and `dependsOn: envoy-gateway-config`
- Wired `./external-services/ks.yaml` into `kubernetes/apps/network/kustomization.yaml`

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | Added Scenario 4: LAN resource proxy with 3-file YAML example and envoy-services cross-reference |
| `docs/ROADMAP.md` | Added Dedicated envoy-services Gateway (Future) under Researched Patterns |
| `kubernetes/apps/network/kustomization.yaml` | Added `./external-services/ks.yaml` resource |
| `kubernetes/apps/network/external-services/ks.yaml` | Created: Flux Kustomization, `targetNamespace: network`, `dependsOn: envoy-gateway-config` |
| `kubernetes/apps/network/external-services/truenas/endpoint.yaml` | Created: EndpointSlice pointing to 10.10.0.41:8080 |
| `kubernetes/apps/network/external-services/truenas/service.yaml` | Created: headless Service (no selector), port 8080 |
| `kubernetes/apps/network/external-services/truenas/httproute.yaml` | Created: HTTPRoute `truenas.${DOMAIN_CLUSTER}` → envoy-internal |
| `kubernetes/apps/network/external-services/truenas/kustomization.yaml` | Created: Kustomize entry-point listing 3 resources |

### Key decisions
- Reuse `envoy-internal` over a dedicated `envoy-services` gateway — avoids extra Envoy pod fleet and CiliumLB IP; migration triggers and cost documented in ROADMAP.md for when IP-level ACLs or TLS passthrough are needed
- Use `${DOMAIN_CLUSTER}` (internal-only, absent from cloudflared config) for all LAN resource hostnames; TLS terminates at `envoy-internal` with the pre-loaded wildcard — no per-service cert needed
- `ks.yaml` declares `targetNamespace: network` explicitly rather than relying on namespace fields in manifests, keeping the individual resource YAMLs namespace-agnostic

---

## 2026-05-29 — `waha-hook-auth-fix`

### Goal
Debug and fix persistent 401s from the WAHA postStart hook — traced through WAHA bcrypt-verify mode, Flux PostBuild variable substitution silently emptying `${VAR}` patterns, and hardened by moving the plain API key to a file mount to keep it out of the process environment.

### What we did
- Observed consistent 401s from the postStart hook across multiple pod restarts despite the manual `curl` from inside the pod returning 422 (authenticated); confirmed `WAHA_API_KEY_PLAIN` was set and non-empty in the running pod
- Diagnosed root cause 1: `WAHA_API_KEY` is a bcrypt hash; WAHA auto-detects this and switches to bcrypt-verify mode — the hook was sending the hash, not the plain key; switched hook to `$WAHA_API_KEY_PLAIN`
- Diagnosed root cause 2: Flux PostBuild substitution (active on the `waha` Kustomization) matched `${WAHA_API_KEY_PLAIN}` and silently replaced it with an empty string (undefined cluster variable); confirmed by inspecting the rendered HelmRelease in-cluster — `"X-Api-Key: "` in the applied spec; fixed by switching to bare `$WAHA_API_KEY_PLAIN` (no braces), which Flux's `${VAR}` pattern does not match
- Hook succeeded after fix: `POST /api/sessions` → 422 (session exists, authenticated) → fallback `POST /api/sessions/default/start` → 201; `[Client] Successfully authenticated` in logs
- Implemented file-mount approach to keep plain key out of process environment: replaced `envFrom: secretRef: waha-secret` with explicit `env` entries per key (excluding `WAHA_API_KEY_PLAIN`); added `waha-secret` volume mount at `/run/secrets/waha`; hook reads key via `$(cat /run/secrets/waha/WAHA_API_KEY_PLAIN)` (shell command substitution — immune to Flux `${VAR}` substitution)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Three iterations: switched to `WAHA_API_KEY_PLAIN`, fixed Flux substitution with bare `$VAR`, switched to file-mount auth with explicit env entries |

### Key decisions
- Used bare `$VAR` not `${VAR}` to defeat Flux PostBuild substitution — Flux only matches the braced form; bare `$VAR` is left untouched and the shell expands it at runtime. This is a reusable pattern for any hook script referencing values that are not cluster-level substitution variables
- Used `$(cat /run/secrets/waha/WAHA_API_KEY_PLAIN)` (shell command substitution) rather than a bare env var — this is also immune to Flux `${VAR}` substitution since it's not that syntactic pattern
- Chose explicit `env` entries over `envFrom` to selectively exclude `WAHA_API_KEY_PLAIN` from the environment; `envFrom` maps all secret keys to env vars with no exclusion mechanism

---

## 2026-05-29 — `waha-session-autostart`

### Goal
Add a `postStart` lifecycle hook to the WAHA HelmRelease to auto-start the default WhatsApp session via the REST API on pod start, replacing non-functional PLUS-only env vars.

### What we did
- Diagnosed that `WHATSAPP_START_SESSION`, `WHATSAPP_RESTART_ALL_SESSIONS`, and `WAHA_WORKER_RESTART_SESSIONS` are PLUS-only and are no-ops in the CORE image currently deployed
- Evaluated Kubernetes options for post-start API calls: `postStart` lifecycle hook vs sidecar container; chose `postStart` as the cleaner pattern (no idle container, well-defined timing before readiness probes fire)
- Confirmed `curl` availability in the WAHA container by exec-ing into the running pod (`waha-5f59684d8b-lgf64`): Debian 12 Bookworm base with `curl 7.88.1` at `/usr/bin/curl`
- Added `postStart` hook to the `app` container: polls `/ping` until the app responds, then calls `POST /api/sessions` with `{"name":"default","start":true}`; falls back to `POST /api/sessions/default/start` for the case where the session already exists on the PVC (409 conflict on create)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Added `lifecycle.postStart` hook (15 lines) to auto-start the default WhatsApp session via REST API |

### Key decisions
- Chose `postStart` over a sidecar: `curl` confirmed present in the Debian 12 base image, so no external image needed; sidecar would require `sleep infinity` to keep the pod alive, consuming resources permanently
- Two-step fallback (`POST /api/sessions` → `POST /api/sessions/default/start`): handles both fresh PVC (session must be created) and restart with existing session data (create returns 409, start-only call succeeds)
- `|| true` at the end prevents a non-zero hook exit (e.g. session already started) from triggering a container restart loop

---

## 2026-05-29 — `externalsecret-migration`

### Goal
Audit and migrate all ExternalSecrets to the `dataFrom.extract` + `rewrite.regexp` + `template` pattern per CONVENTIONS.md, and fix a pre-existing `flux-receiver` breakage caused by stale 1Password Connect cache.

### What we did
- Audited all 10 ExternalSecrets: identified 6 needing migration, confirmed 2 already compliant (`tailscale-operator`, `waha`), found `flux-receiver` partially migrated with a wrong template output key (`FLUX_GITHUB_WEBHOOK_TOKEN` vs the required `token`)
- Inspected all 5 relevant 1Password items (`cloudflared`, `unifi`, `flux`, `actions-runner`, `anthropic`) for field names, types, and shape — confirmed `cloudflared` item is shared by 3 ExternalSecrets, requiring `template` scoping on all three to prevent field leakage
- Diagnosed `flux-receiver` `Ready: False`: root cause was 1Password Connect cache staleness, not a missing item — `flux` item existed with both field names but Connect hadn't synced it; item has been accessible in the vault since ~2026-05-15
- Restarted 1Password Connect (`kubectl rollout restart deployment/onepassword-connect -n external-secrets`) → all 10 ExternalSecrets returned to `SecretSynced: True`
- Fixed `flux-receiver` ExternalSecret template key: `FLUX_GITHUB_WEBHOOK_TOKEN` → `token`; annotated Receiver to force reconcile → `Ready: True`, webhook URL restored
- Migrated `cert-manager/cluster-issuers`: added `rewrite: CF_$1` + scoping template exposing exactly `API_TOKEN` key (cert-manager `apiTokenSecretRef` requirement)
- Migrated `network/external-dns/cloudflare`: switched from `data[]` to `dataFrom.extract` + `rewrite: CF_$1` + template
- Migrated `network/cloudflared`: switched to `dataFrom.extract` + `rewrite: CF_$1` + template (`TUNNEL_TOKEN: "{{ .CF_TUNNEL_TOKEN }}"`) — staged, requires `TUNNEL_TOKEN` → `TOKEN` 1P rename before commit
- Migrated `network/external-dns/unifi`: `dataFrom.extract` + `rewrite: UNIFI_$1` + template — staged, requires `UNIFI_HOST` → `HOST` and `UNIFI_API_KEY` → `API_KEY` renames
- Migrated both `actions-runner-system` ExternalSecrets: `dataFrom.extract` + rewrite + template — staged, requires `ACTIONS_RUNNER_*` → short names and `ANTHROPIC_API_KEY` → `API_KEY` renames
- Provided `op item edit --template` commands for user to run for all four 1P items; auto-mode classifier correctly blocked write operations as production-secrets mutations

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-receiver/app/externalsecret.yaml` | Fixed template output key to `token` (Flux Receiver CRD requirement) |
| `kubernetes/apps/cert-manager/cluster-issuers/app/externalsecret.yaml` | Added `rewrite: CF_$1` + scoping template; was partially migrated (no rewrite) |
| `kubernetes/apps/network/external-dns/cloudflare/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: CF_$1` + template |
| `kubernetes/apps/network/cloudflared/app/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: CF_$1` + template (staged; needs 1P rename) |
| `kubernetes/apps/network/external-dns/unifi/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: UNIFI_$1` + template (staged; needs 1P rename) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/externalsecret.yaml` | Both ExternalSecrets migrated to `dataFrom.extract` + rewrite + template (staged; needs 1P renames) |

### Key decisions
- Added `template` scoping to ALL migrations regardless of roadmap's "no template needed" notes — the shared `cloudflared` item has 3 fields; without scoping, all three app secrets would receive unrelated keys (e.g. tunnel `cert-manager-secret` would also contain `CF_TUNNEL_TOKEN`)
- Used `CF_$1` rewrite for `cloudflared` tunnel (roadmap proposed `TUNNEL_$1`) — keeps all three cloudflared-derived ExternalSecrets on a consistent `CF_` prefix, matching `external-dns-cloudflare` and `cert-manager` which were already established; the template then maps `CF_TUNNEL_TOKEN` → `TUNNEL_TOKEN` for the consumer
- The staged cloudflared/unifi/actions-runner manifests reference post-rename field names; they **must not be committed before the 1P renames complete** or all three ExternalSecrets will immediately enter `SecretSyncError`

---

## 2026-05-25 — `flux-alertmanager-notifications`

### Goal
Implement Flux alerting by wiring notification-controller to Alertmanager for event-driven resource failure alerts, and adding a Prometheus PodMonitor and PrometheusRules for controller-level health monitoring.

### What we did
- Reviewed `docs/REPO-AUDIT.md` W1 (no Flux Alert/Provider configured); used `gitops-knowledge` skill to enumerate all supported Flux Provider types
- Decided on `alertmanager` Provider: in-cluster, integrates with existing kube-prometheus-stack, no extra infrastructure
- Cross-referenced with bykaj's home-ops repo: they use PrometheusRules + PodMonitor (metric-based) rather than Flux Alert/Provider; identified that their approach misses individual HelmRelease/Kustomization failure alerting — the two approaches are complementary
- Created `flux-alerts` app with Flux `Provider` (type: `alertmanager`, in-cluster Service URL) and `Alert` (`eventSeverity: error`, watches all `Kustomization` + `HelmRelease` resources, three noise-exclusion patterns)
- Added `PodMonitor` (scrapes all 4 Flux controllers via `http-prom`) and `PrometheusRule` (`FluxInstanceAbsent` + `FluxInstanceNotReady`, 5m threshold) to the `flux-instance` app
- Confirmed `flux-system` is correct for all resources: `kube-prometheus-stack` has `*SelectorNilUsesHelmValues: false`, enabling cluster-wide PodMonitor/PrometheusRule discovery from any namespace

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-alerts/ks.yaml` | Created — Flux Kustomization, dependsOn kube-prometheus-stack |
| `kubernetes/apps/flux-system/flux-alerts/app/kustomization.yaml` | Created |
| `kubernetes/apps/flux-system/flux-alerts/app/notifications.yaml` | Created — Provider (alertmanager) + Alert (flux-errors, error severity) |
| `kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml` | Created — scrapes helm/source/kustomize/notification controllers |
| `kubernetes/apps/flux-system/flux-instance/app/prometheusrule.yaml` | Created — FluxInstanceAbsent + FluxInstanceNotReady rules |
| `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml` | Updated — added podmonitor and prometheusrule resources |
| `kubernetes/apps/flux-system/kustomization.yaml` | Updated — added flux-alerts entry |

### Key decisions
- Used in-cluster Service URL (`svc.cluster.local:9093`) for the alertmanager Provider address — avoids a gateway hop and keeps alerting functional even when external ingress is down
- Co-located PodMonitor + PrometheusRule in `flux-instance` app (not `observability`) — "app owns its observability" pattern; `*SelectorNilUsesHelmValues: false` enables Prometheus to discover them from any namespace
- Implemented both Flux Alert/Provider AND PrometheusRules as complementary layers: event-driven covers individual resource failures; metric-based covers controller-level health and absence detection

---

## 2026-05-25 — `drift-detection-global-default`

### Goal
Enable `driftDetection: enabled` as a cluster-wide default for all HelmReleases via the `cluster-apps` global patch, with a label-based opt-out mechanism and full documentation.

### What we did
- Reviewed `docs/REPO-AUDIT.md`; identified W2 (drift detection on only 5/20 HelmReleases) as the primary work item
- Explained drift detection: Flux detects and reverts out-of-band mutations to Helm-owned resources (via server-side apply field ownership) on every reconciliation interval; `mode: warn` detects without reverting, `mode: enabled` detects and corrects
- Audited all 15 HelmReleases missing drift detection (`grep -rL driftDetection`); confirmed none have HPA, VPA, or other controllers that write back to `.spec` fields — all are safe to enable
- Identified non-HPA risk cases: VPA (resources.requests), Service `nodePort` auto-assignment, mutating admission webhooks adding annotations to Helm-managed resources, operators that write to CRD `.spec` (not just `.status`)
- Confirmed `spec.driftDetection.ignore` rules survive the global patch (strategic merge on object sub-fields; global patch only writes `mode`), but `mode: disabled` does not survive (global patch is last writer on scalar fields)
- Added a **separate** drift detection patch block to `kubernetes/flux/cluster/ks.yaml` (kept separate from install/upgrade defaults so the label selector doesn't accidentally exclude other defaults)
- Implemented opt-out label selector `driftDetection.flux.home.arpa/disabled notin (true)` on the inner HelmRelease target — same pattern as `substitution.flux.home.arpa/disabled`
- Updated `CLAUDE.md` HelmRelease defaults section: added `driftDetection: enabled` to the defaults YAML, added note that `ignore` rules survive the global patch (the exception to "last writer wins")
- Added "Drift Detection" section to `docs/CONVENTIONS.md`: opt-out label, `ignore` rules pattern, table of common ignore scenarios (HPA, VPA, nodePort, mutating webhooks), note on what drift detection doesn't watch
- Marked W2 resolved in `docs/REPO-AUDIT.md`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/cluster/ks.yaml` | Added drift detection patch block with `driftDetection.flux.home.arpa/disabled` opt-out label selector |
| `CLAUDE.md` | Updated HelmRelease defaults section with drift detection default and ignore-rules survival note |
| `docs/CONVENTIONS.md` | Added Drift Detection section: opt-out label, ignore rules, risk table, ownership scope |
| `docs/REPO-AUDIT.md` | Marked W2 resolved; updated audit note |

### Key decisions
- **Separate patch block** rather than folding `driftDetection` into the existing install/upgrade defaults patch — the existing patch has no label selector and applies universally; mixing them would mean the opt-out label accidentally excludes install/upgrade defaults too
- **`ignore` rules in HelmRelease YAML survive the global patch** because `driftDetection` is an object field and strategic merge only writes `mode`; this allows per-release path exclusions without needing a local Kustomize patch
- **Full opt-out requires the label on the HelmRelease** (not the Kustomization) because the inner patch target operates at the HelmRelease level

---

## 2026-05-24 — `gitops-repo-audit`

### Goal
Perform a full GitOps best-practices and security audit of the cluster repository, then implement Cosign supply-chain verification for all OCIRepositories where publishers confirmed signed artifacts.

### What we did
- Invoked the `/gitops-repo-audit` skill; ran discovery script revealing 14 OCIRepositories, 20 HelmReleases, 30 Kustomizations across 14 app namespaces; classified repo as single-cluster GitOps monorepo (Flux Operator pattern)
- Added `kustomize` and `kubeconform` to `.mise.toml` (missing tools); ran manifest validation — no Flux/Kubernetes manifest errors; non-Flux files (Talos patches, Taskfile) produced expected schema-skip results
- Checked for deprecated Flux APIs — none found
- Assessed best practices: dependency chains sound, SOPS encryption in place, global HelmRelease patch covers crds/remediation; identified gaps: no `driftDetection`, no `reconcile.fluxcd.io/watch` labels on cluster-vars ConfigMaps, no Flux Alert/Provider notification resources
- Performed security review: OCIRepositories missing Cosign verification was the highest-priority finding
- Investigated each OCI publisher for signature presence using registry API curl calls (`/v2/<repo>/manifests/sha256-<digest>.sig`) — confirmed 7 of 14 OCIRepositories are signed; 7 (tuppr, kube-prometheus-stack, coredns, spegel, gha-runner-scale-set*, envoy-gateway) are unsigned
- Confirmed signing method per publisher: cert-manager uses key-based RSA (published PEM); flux-operator, flux-instance, external-dns, openebs, app-template, tailscale-operator all use keyless OIDC via GitHub Actions (`cosign sign --yes`)
- Confirmed OIDC identities by reading each publisher's GitHub Actions workflows; used org-level subject regexp (`^https://github.com/<org>/`)
- Added `verify:` blocks to 6 OCIRepositories (keyless OIDC); created `cert-manager-cosign-key.yaml` Secret with RSA public key for key-based verification; upgraded `openebs.yaml` from bare `provider: cosign` to include `matchOIDCIdentity`
- Validated all changes with `kustomize build kubernetes/flux/meta/repos/oci/` — 15 resources output (14 OCIRepositories + 1 Secret), no errors

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/app-template.yaml` | Added keyless cosign verify (bjw-s-labs org) |
| `kubernetes/flux/meta/repos/oci/cert-manager-cosign-key.yaml` | New: Secret with cert-manager RSA public key |
| `kubernetes/flux/meta/repos/oci/cert-manager.yaml` | Added key-based cosign verify referencing cert-manager-cosign-key |
| `kubernetes/flux/meta/repos/oci/external-dns.yaml` | Added keyless cosign verify (home-operations org) |
| `kubernetes/flux/meta/repos/oci/flux-instance.yaml` | Added keyless cosign verify (controlplaneio-fluxcd org) |
| `kubernetes/flux/meta/repos/oci/flux-operator.yaml` | Added keyless cosign verify (controlplaneio-fluxcd org) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added cert-manager-cosign-key.yaml to resources list |
| `kubernetes/flux/meta/repos/oci/openebs.yaml` | Upgraded bare `provider: cosign` to include `matchOIDCIdentity` (home-operations org) |
| `kubernetes/flux/meta/repos/oci/tailscale-operator.yaml` | Added keyless cosign verify (home-operations org) |

### Key decisions
- Detected signatures without `cosign` CLI by querying the registry API for `.sig` manifest tags; initial `curl -sv` mixed stderr/stdout causing false 404s — switched to `curl -s -D - -o /dev/null` to properly separate headers from body
- Stored cert-manager public key in a plain (non-SOPS) Secret — it is a published RSA public key, not a private credential, so encryption adds no security benefit
- Used org-level regexp for `subject` (`^https://github.com/<org>/`) rather than pinning to a specific repo or branch — tolerates future repo reorganisation within the trusted org while keeping trust tightly scoped

---

## 2026-05-24 — `tailscale-connector-crd-fix`

### Goal
Debug and fix the failing `tailscale-configs` Kustomization by tracing the missing `connectors.tailscale.com` CRD to a Helm chart values flag (`installCRDs: true`) and hardening the dependency ordering.

### What we did
- Used `/gitops-cluster-debug` skill (Workflow 3) to diagnose the failing `tailscale-configs` Kustomization; called `get_flux_instance` to confirm all 4 Flux controllers healthy with exactly 1 failing Kustomization
- Fetched `tailscale-configs` Kustomization via MCP — error: `the server could not find the requested resource (patch connectors.tailscale.com subnet-router)`; confirmed `tailscale-operator` Kustomization was `Ready` and HelmRelease (v1.96.5) had installed successfully
- Verified `connectors.tailscale.com` CRD absent via `kubectl get crd`; installed Tailscale CRDs were `dnsconfigs`, `proxyclasses`, `proxygrouppolicies`, `proxygroups`, `recorders`, `tailnets`
- Checked `ProxyGroup` CRD schema — types: `egress`, `ingress`, `kube-apiserver`; no `subnet-router` type, ruling out a 1:1 swap
- Queried Tailscale docs via context7 — confirmed `Connector` with `subnetRouter.advertiseRoutes` is still the official API for subnet routing in v1.96.x
- Pulled Helm chart `tailscale-operator@1.96.5` tarball and read `templates/connector.yaml` — entire CRD gated behind `{{ if .Values.installCRDs }}`; root cause: `installCRDs` not set in HelmRelease values, silently skipping the CRD
- Added `installCRDs: true` to HelmRelease values; changed `wait: false` → `wait: true` on the `tailscale-operator` Kustomization to eliminate the CRD registration race condition

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/tailscale/tailscale-operator/app/helmrelease.yaml` | Added `installCRDs: true` to values — enables `connectors.tailscale.com` CRD |
| `kubernetes/apps/tailscale/tailscale-operator/ks.yaml` | `wait: false` → `wait: true` on `tailscale-operator` Kustomization |

### Key decisions
- Root-caused by pulling and inspecting the chart tarball directly — `connector.yaml` is a regular Helm template (not in `crds/`), making it opt-in and silently skippable; the ProxyGroup schema check and context7 lookup confirmed `Connector` is not deprecated, just opt-in
- `wait: true` applied to `tailscale-operator` (not `tailscale-configs`) because the race is in the operator's CRD registration step, not in configs deployment

---

## 2026-05-24 — `setup-flux-mcp-server`

### Goal
Install fluxcd/agent-skills (gitops-knowledge, gitops-cluster-debug, gitops-repo-audit) and wire up flux-operator-mcp as a new MCP server so the gitops-cluster-debug skill has live cluster access.

### What we did
- Installed 3 Flux skills from OCI image `ghcr.io/fluxcd/agent-skills` via `flux-operator skills install --agent claude-code`: `gitops-knowledge`, `gitops-cluster-debug`, `gitops-repo-audit`; artifact signature verified by cosign
- Explored the `.claude/skills/` vs `.claude/commands/` distinction: installed OCI packages land in `skills/` (directory with `SKILL.md`, `assets/`, `evals/`, `references/`); hand-authored slash commands stay as flat `.md` files in `commands/`
- Explored `.agents/skills/` structure: agent-agnostic registry with `catalog.yaml` (OCI source + cosign OIDC policy + target agents) and `catalog-lock.yaml` (pinned digest); `flux-operator skills install` projects skill content into `.claude/skills/` for Claude Code
- Compared `cluster-doctor.md` against `gitops-cluster-debug`: confirmed not redundant — cluster-doctor covers full-stack Talos+K8s+CNI+storage diagnosis with live topology context; gitops-cluster-debug is Flux-only and requires `flux-operator-mcp` (not previously configured)
- Added `flux-operator-mcp = "0.50.0"` to `.mise.toml` with Renovate datasource comment; added `flux-operator-mcp` server entry to `.mcp.json` (gitignored) with `--read-only` and pointing at existing `mcp-viewer.kubeconfig`
- Ran `mise install flux-operator-mcp`; verified binary via `mise exec -- flux-operator-mcp --version`
- Confirmed MCP connection after shell refresh: `get_flux_instance` returned full FluxInstance + FluxReport; all 4 controllers healthy; identified 1 failing Kustomization (32 total) and Flux v2.6.4 outdated notice (latest v2.8.8)

### Files changed
| File | Change |
|------|--------|
| `.mise.toml` | Added `flux-operator-mcp = "0.50.0"` with renovate comment |
| `.mcp.json` | Added `flux-operator-mcp` server entry (gitignored — not tracked) |

### Key decisions
- Used `--read-only` for flux-operator-mcp to preserve GitOps discipline (no imperative cluster changes via AI tools)
- Pinned flux-operator-mcp at `0.50.0` to match `flux-operator` already in `.mise.toml`; shared Renovate datasource comment keeps both in sync

---

## 2026-05-23 — `arc-runner-deploy`

### Goal
Deploy GitHub Actions Runner Controller (ARC) with a self-hosted runner scale set and wire up claude-code-action to automatically review Renovate PRs using the pr-upgrade-reviewer agent.

### What we did
- Prioritised ARC + Claude PR review above other roadmap items; user created GitHub App and added credentials to 1Password
- Created two OCIRepository sources for `gha-runner-scale-set-controller` and `gha-runner-scale-set` ARC charts under `flux/meta/repos/oci/`
- Built multi-document `ks.yaml` (controller Kustomization → `dependsOn` → scale-set Kustomization) with `substitution.flux.home.arpa/disabled: "true"` on both to prevent cluster-apps postBuild expanding GitHub URLs as Flux variables
- Created controller HelmRelease with explicit `serviceAccount.name: actions-runner-controller`; runner HelmRelease with kubernetes containerMode; ExternalSecrets for GitHub App creds (`home-lab-runner-secret`) and Anthropic API key (`anthropic-secret`)
- Created RBAC: Kubernetes SA `actions-runner` + `cluster-admin` ClusterRoleBinding (intentional — runner workflows need full kubectl/flux access)
- Created `.github/workflows/renovate-pr-review.yml` using `anthropic-ai/claude-code-action@v1` with `ANTHROPIC_API_KEY` injected via runner environment (ExternalSecret → pod env)
- Fixed typo `anthropics/` → `anthropic-ai/` in action reference; fixed ExternalSecret `key:` for anthropic-secret (user corrected to `key: anthropic`)
- Diagnosed Talos SA `ErrNamespaceNotAllowed`: `actions-runner-system` blocked by Talos SA namespace allowlist; removed Talos SA and its volume mounts — commit `fb3767e`
- Observed two Renovate PRs (#39 actions/checkout, #40 kube-prometheus-stack) triggering simultaneously; runners created but cycling every ~5 minutes — initially misdiagnosed as openebs-hostpath node-locality PVC issue; applied Longhorn fix (`d2b5cb0`) — later found incorrect
- Resumed next day: renewed MCP token; re-triggered run `26332793877` to test Longhorn fix; observed new failure mode: rapid create/destroy cycle at ~15 s intervals
- Analysed ARC controller logs: `"exitCode": 0` at the exact same millisecond as `"ready": true` — runner binary not executing at all; no hook pods created
- Consulted reference implementation `bykaj/home-ops`; identified missing `command: [/home/runner/run.sh]` — the `home-operations/actions-runner` image does not wire `run.sh` as Docker CMD, causing the container to exit immediately (exit 0) and producing the create/destroy loop
- Added `command: [/home/runner/run.sh]` to runner container spec
- User challenged Longhorn choice: confirmed `openebs-hostpath` uses `WaitForFirstConsumer` which records node affinity on the PV, automatically constraining ARC hook pods to the same node as the runner — Longhorn was unnecessary; reverted to `openebs-hostpath` with 10 Gi work volume
- Hardened workflow: added `timeout-minutes: 15` (job) + per-step timeouts, `concurrency` group with `cancel-in-progress: true`, `synchronize` event type, explicit `github_token`
- Reviewed `pr-upgrade-reviewer` agent: user added unattended operation constraints, PR number intake from CLI arg / `PR_NUMBER` env, Step 6 (mandatory PR comment posting with idempotent HTML-marker-based update-or-create logic)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/gha-runner-scale-set-controller.yaml` | Created OCIRepository source |
| `kubernetes/flux/meta/repos/oci/gha-runner-scale-set.yaml` | Created OCIRepository source |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added two new OCI repo entries |
| `kubernetes/apps/kustomization.yaml` | Added `actions-runner-system` resource |
| `kubernetes/apps/actions-runner-system/kustomization.yaml` | Created namespace kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/ks.yaml` | Created two-doc Kustomization (controller + scale set) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/app/helmrelease.yaml` | Created controller HelmRelease |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/app/kustomization.yaml` | Created app kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/kustomization.yaml` | Created runners kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/helmrelease.yaml` | Created; fixed with `command: run.sh`, reverted to openebs-hostpath 10 Gi |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/externalsecret.yaml` | Created two ExternalSecrets (runner creds + anthropic key) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/rbac.yaml` | Created SA + cluster-admin CRB (Talos SA added then removed) |
| `.github/workflows/renovate-pr-review.yml` | Created; improved with timeout, concurrency, synchronize event, github_token |
| `.claude/agents/pr-upgrade-reviewer.md` | Enhanced: unattended mode, PR number intake, Step 6 mandatory comment posting |

### Key decisions
- `substitution.flux.home.arpa/disabled: "true"` on both ARC Kustomizations — GitHub URLs and secret names contain `${...}` patterns that cluster-apps postBuild would expand as Flux variables
- Multi-doc `ks.yaml` required — runner scale set CRDs must exist before instances; `dependsOn` + separate Kustomization prevents Flux dry-run failure at deploy time
- Talos SA removed entirely — `actions-runner-system` is not in the Talos SA namespace allowlist; accessing Talos API from CI requires a different approach not yet implemented
- `cluster-admin` intentionally granted — runner workflows need full cluster write access; homelab risk is accepted and documented in a `rbac.yaml` comment
- `command: [/home/runner/run.sh]` required — `home-operations/actions-runner` does not use `run.sh` as Docker CMD; without it the container exits immediately (exit 0), creating an infinite rapid create/destroy loop indistinguishable from a passing run
- openebs-hostpath with `WaitForFirstConsumer` over Longhorn — `WaitForFirstConsumer` records node affinity on the PV, constraining hook pods to the same node as the runner; Longhorn adds unnecessary network overhead; the earlier Longhorn switch was based on a misdiagnosis of the 5-minute timeout cycle

---

## 2026-05-23 — `cloudflare-ssl-webhook-fix`

### Goal
Fix the broken GitHub Flux webhook by diagnosing and resolving Cloudflare Universal SSL's one-level wildcard limitation, an external-dns zone-filter misconfiguration, and a stale cloudflared in-process config.

### What we did
- Continued from `debug-flux-dns-tunnel` — the big multi-domain commit was applied but external-dns-cloudflare logged only 4 lines and never synced
- Diagnosed the silence using a debug pod (`--once --dry-run --log-level=debug`): Cloudflare external-dns v0.21.0 requires the exact Cloudflare zone name in `domainFilters`; `cluster.vwn.io` doesn't match the `vwn.io` zone — it was silently skipping all desired records
- User added `DOMAIN_IO: vwn.io` to `cluster-secrets.sops.yaml`; amended `64844f0` to add `${DOMAIN_IO}` to external-dns-cloudflare `domainFilters` (preserving original commit subject)
- External-dns created `external.cluster.vwn.io` and `flux-webhook.cluster.vwn.io` Cloudflare CNAME records
- GitHub webhook delivery failed with `tls: handshake failure` — root cause: cloudflared pods were 17-20h old and still running config with `originServerName: gateway.vwn.io` (the old CLUSTER_DOMAIN); restarted cloudflared
- Second failure: Cloudflare Universal SSL covers `vwn.io` + `*.vwn.io` only (one wildcard level); `flux-webhook.cluster.vwn.io` is two levels deep — not covered by any cert at Cloudflare's edge
- Investigated Option A (NS delegation for `cluster.vwn.io` sub-zone) — Cloudflare rejected it: "should not delegate subdomain to the same nameserver as current zone"
- Chose Option C: move all public-facing endpoints to first-level `vwn.io` subdomains (covered by Universal SSL, no cost/complexity)
- Changed `flux-webhook.${DOMAIN_CLUSTER}` → `flux-webhook.${DOMAIN_IO}`, `external.${DOMAIN_CLUSTER}` → `external.${DOMAIN_IO}` across httproute, dnsendpoint, gateway annotations, and cloudflared ingress; committed as `c98664c`
- Waited for external-dns `policy: sync` to delete the old `cluster.vwn.io` CNAME + TXT records before removing the zone from `domainFilters` — removing early would have orphaned the ownership records
- Confirmed cleanup in external-dns logs; removed `${DOMAIN_CLUSTER}` from cloudflare domainFilters and updated `originServerName` to `gateway.${DOMAIN_IO}`; committed as `67275b9`
- cloudflared pods hadn't restarted after the ConfigMap update (process reads config only at startup); rolled deployment; webhook redeliver returned 200 OK
- Deleted orphaned `wildcard-production-tls` Secret from `network` namespace (cert had been removed in Phase B but Secret persisted)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `DOMAIN_IO: vwn.io` (amended into `64844f0`) |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Added `${DOMAIN_IO}` to domainFilters; later removed `${DOMAIN_CLUSTER}` |
| `kubernetes/apps/flux-system/flux-receiver/app/httproute.yaml` | Hostname `DOMAIN_CLUSTER` → `DOMAIN_IO` |
| `kubernetes/apps/network/cloudflared/app/dnsendpoint.yaml` | `external.DOMAIN_CLUSTER` → `external.DOMAIN_IO` |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | Removed `*.DOMAIN_CLUSTER` ingress; added `*.DOMAIN_IO`; updated `originServerName` |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Both `external-dns` annotations → `external.DOMAIN_IO` |

### Key decisions
- Option C (first-level `vwn.io` subdomains) chosen over NS delegation (rejected by Cloudflare) and Advanced Certificate Manager (paid) — Universal SSL already covers `*.vwn.io` without additional setup
- `${DOMAIN_CLUSTER}` kept in external-dns-cloudflare `domainFilters` until `policy: sync` cleaned up owned records; removing it earlier would have left orphan CNAME + TXT records in Cloudflare with no owner to clean them up
- cloudflared `originServerName` uses `gateway.${DOMAIN_IO}` as TLS SNI for the tunnel → Envoy backend connection; Envoy routes using the HTTP Host header, not SNI — the mismatch is intentional and harmless with `noTLSVerify: true`

---

## 2026-05-23 — `debug-flux-dns-tunnel`

### Goal
Add multi-domain TLS support, remove legacy `CLUSTER_DOMAIN`, harden Envoy Gateway, and fix a Cloudflare tunnel routing bug where `external.proxii.nl` (private DNS) was used as the external-dns target instead of the cloudflared tunnel endpoint.

### What we did
- Compared envoy-gateway deployment against bykaj reference repo; identified gaps: no BackendTrafficPolicy (compression/retry), no observability, no memory limits, no drainTimeout
- Added `BackendTrafficPolicy` (zstd/brotli/gzip compression, retry on TCP reset, tcpKeepalive, `requestTimeout: 0s`), `ClientTrafficPolicy` (http3, tcpKeepalive), `drainTimeout: 180s`, memory 256Mi request / 1Gi limit (Burstable QoS)
- Added `PodMonitor` + `ServiceMonitor` for Envoy proxy pods and control-plane metrics
- Added four domain variables (`DOMAIN_APP`, `DOMAIN_CASA`, `DOMAIN_CLUSTER`, `DOMAIN_APPS`) to `cluster-secrets.sops.yaml`; removed legacy `CLUSTER_DOMAIN` (`vwn.io`) entirely
- Created four per-domain wildcard Certificate CRs (`vwn.app`, `vwn.casa`, `cluster.vwn.io`, `apps.vwn.io`); removed `wildcard-production` Certificate; updated both gateway `certificateRefs`; removed `hostname:` restriction from HTTPS listeners (SNI-based cert selection)
- Migrated `prometheus`, `alertmanager` HTTPRoutes to `DOMAIN_CLUSTER` / `envoy-internal`; migrated `flux-webhook` to `DOMAIN_CLUSTER` / `envoy-external`
- Removed `CLUSTER_DOMAIN` from cert-manager ClusterIssuers, cloudflared ingress rules, and external-dns domainFilters
- Added static `DNSEndpoint` for `kube-vip.cluster.vwn.io → 10.60.0.2` and `external-dns-endpoints` Kustomization (later replaced)
- **Diagnosed tunnel routing bug:** `flux-webhook.cluster.vwn.io` resolved to `external.proxii.nl → 10.60.0.230` (private IP); Cloudflare's edge can't reach private IPs, so tunnel was never engaged. Root cause: `external.proxii.nl` is in private UniFi DNS, not a Cloudflare-managed zone
- **Fixed:** Added `DNSEndpoint` CR in cloudflared app creating `external.cluster.vwn.io CNAME <tunnel-id>.cfargotunnel.com`; changed gateway target annotation from `external.${DOMAIN_PROXII}` → `external.${DOMAIN_CLUSTER}`; added `CLOUDFLARE_TUNNEL_ID` to cluster-secrets
- Removed `crd` from `external-dns-unifi` sources to prevent CNAME/A conflict (both instances would have created conflicting record types for the same intermediate hostname)
- Replaced `kube-vip` `DNSEndpoint` CR with a real `kube-api` `LoadBalancer` Service in `cilium/config/`; Cilium LB IPAM pins it to `10.60.0.2`; `external-dns-unifi` `service` source creates `kube-vip.cluster.vwn.io A 10.60.0.2` without needing the `crd` source
- Removed `external-dns-endpoints` Kustomization and `endpoints/` directory
- Installed `dnsutils` in devcontainer (added to `postCreateCommand.sh`); added prominent no-commit directive to `CLAUDE.md`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `DOMAIN_APP/CASA/CLUSTER/APPS/PROXII`, `CLOUDFLARE_TUNNEL_ID`; removed `CLUSTER_DOMAIN` |
| `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` | BackendTrafficPolicy, ClientTrafficPolicy, memory limits, drainTimeout 180s |
| `kubernetes/apps/network/envoy-gateway/config/certificate.yaml` | Replaced `wildcard-production` with 4 per-domain wildcard Certificates |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Removed hostname restriction; multi-cert refs; tunnel target fixed |
| `kubernetes/apps/network/envoy-gateway/app/observability.yaml` | New — PodMonitor + ServiceMonitor |
| `kubernetes/apps/network/envoy-gateway/app/kustomization.yaml` | Added `observability.yaml` |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | Removed `CLUSTER_DOMAIN` ingress entries; added all 4 new domains; fixed `originServerName` |
| `kubernetes/apps/network/cloudflared/app/dnsendpoint.yaml` | New — `external.cluster.vwn.io CNAME <tunnel-id>.cfargotunnel.com` |
| `kubernetes/apps/network/cloudflared/app/kustomization.yaml` | Added `dnsendpoint.yaml` |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Updated `domainFilters` |
| `kubernetes/apps/network/external-dns/unifi/helmrelease.yaml` | Updated `domainFilters`; removed `crd` source |
| `kubernetes/apps/network/external-dns/ks.yaml` | Removed `external-dns-endpoints` Kustomization |
| `kubernetes/apps/network/external-dns/endpoints/` | Deleted — replaced by `kube-api` Service |
| `kubernetes/apps/kube-system/cilium/config/service.yaml` | New — `kube-api` LoadBalancer Service for `kube-vip.cluster.vwn.io` |
| `kubernetes/apps/kube-system/cilium/config/kustomization.yaml` | Added `service.yaml` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-production.yaml` | Removed `CLUSTER_DOMAIN` from `dnsZones` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-staging.yaml` | Removed `CLUSTER_DOMAIN` from `dnsZones` |
| `kubernetes/apps/flux-system/flux-receiver/app/httproute.yaml` | Hostname → `flux-webhook.${DOMAIN_CLUSTER}` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml` | Hostnames → `${DOMAIN_CLUSTER}` |
| `docs/ROADMAP.md` | Added multi-domain cert pipeline pattern (deferred) |
| `CLAUDE.md` | Prominent no-commit directive blockquote |
| `.devcontainer/postCreateCommand.sh` | Added `dnsutils` |

### Key decisions
- Domain vars go in encrypted `cluster-secrets.sops.yaml`, not plaintext `cluster-settings.yaml` — these values are considered infrastructure secrets
- `hostname:` restriction removed from gateway HTTPS listeners — SNI-based cert selection handles routing; HTTP virtual hosting is still controlled by HTTPRoute `hostnames:` field
- `external.cluster.vwn.io` chosen as the cloudflared tunnel intermediary hostname (not `external.proxii.nl`) because it lives in a Cloudflare-managed zone; both external-dns instances resolve it differently via split DNS (Cloudflare: CNAME → tunnel; UniFi: A → 10.60.0.230)
- `crd` source removed from UniFi external-dns (mirrors bykaj pattern); static LAN records handled via `service` source instead, avoiding CNAME/A conflicts
- `kube-vip.cluster.vwn.io` hardcoded in `service.yaml` (not a variable) because `cilium-config` Kustomization has substitution disabled (`substitution.flux.home.arpa/disabled: "true"`) — changing this would be a broader risk than hardcoding a stable infrastructure hostname

---

## 2026-05-23 — `uncordon-cp-02-node`

### Goal
Diagnose and fix the cp-02 persistent boot loop (JetKVM EFI boot entry root cause), then repair Longhorn's stale disk UUID record to bring cp-02's storage disk fully online.

### What we did
- Continued from `nvme-disk-config-talos` — cp-02 was configured but kept booting to ISO/maintenance mode instead of Talos after every power cycle
- Diagnosed masking issue: `talosctl reboot` uses Linux kexec by default (bypasses BIOS entirely), so the boot failure was invisible until `--mode powercycle` was used
- Booted Alpine Linux via JetKVM virtual media to inspect UEFI state; `apk add efibootmgr` was unavailable (no network), BusyBox `strings -e l` unsupported; decoded UTF-16LE boot entry labels using `tr -d '\000' < /sys/firmware/efi/efivars/Boot####-<GUID>`
- Identified root cause: **JetKVM Virtual Media (Boot0016)** had higher UEFI priority than Talos Linux (Boot0000); with Alpine ISO mounted in JetKVM, every boot went to maintenance mode
- Deleted all UEFI boot entries except Boot0000 via direct efivars manipulation (`chattr -i` + `rm`); ejected Alpine ISO from JetKVM virtual media; power-cycled
- cp-02 booted Crucial P310 successfully (Lenovo logo visible via JetKVM); all 3 nodes Ready (Talos v1.13.2, K8s v1.36.1); mounts confirmed: `nvme1n1=EPHEMERAL/system`, `nvme0n1p1=/var/mnt/longhorn-storage`
- Ran cluster-doctor diagnostic: cp-02 already uncordoned; Longhorn disk `default-disk-1030500000000` had `DiskFilesystemChanged` UUID mismatch, `allowScheduling: false`
- Fixed stale `node.longhorn.io/default-disks-config` annotation on Node object (`allowScheduling: false → true`, aligning with Git manifest)
- Removed stale Longhorn disk entry via `kubectl patch`; controller re-discovered disk with fresh UUID `3becac06-4aac-499c-a8de-a49badaefaaa`; disk now `Ready: True, Schedulable: True`, ~913 GiB available
- Confirmed existing volumes remain at 2 replicas (pre-cp-02); new volumes will use 3-replica default; manual UI bump or `Replicas Auto Balance` setting needed to expand existing volumes
- Created `docs/BOOT-ISSUE-TROUBLESHOOTING.md` documenting M920Q A/E slot boot behavior, EFI entry manipulation workaround, and required BIOS settings

### Files changed
| File | Change |
|------|--------|
| `docs/BOOT-ISSUE-TROUBLESHOOTING.md` | New — M920Q A/E slot UEFI boot troubleshooting guide (efivars manipulation, JetKVM gotcha, BIOS settings) |

### Key decisions
- Direct efivars `chattr -i` + `rm` used instead of `efibootmgr` — Alpine on JetKVM had no network; efivars manipulation is equivalent from any Linux live environment
- Deleted all non-Talos UEFI entries (including JetKVM virtual media entry) rather than reordering — prevents any external boot source overriding Talos on future power cycles
- Longhorn disk UUID reset via imperative `kubectl patch` (not GitOps) — stale UUID is a live controller-state problem, not representable in Git; Longhorn re-adds disk with correct UUID within seconds

---

## 2026-05-22 — `nvme-disk-config-talos`

### Goal
Install the Crucial P310 1TB NVMe drive in cp-02, reconfigure Talos to boot from it and use the Kingston as Longhorn storage, and promote Longhorn to 3-replica mode.

### What we did
- Shut down cp-02 with `talosctl shutdown` (note: `halt` command removed in Talos 1.9+; `shutdown` is the equivalent)
- User installed Crucial P310 1TB 2230 NVMe in cp-02 and booted into Talos maintenance mode
- Ran `talosctl get disks --insecure` to identify both drives: Crucial (`nvme1n1`, model `CT1000P310SSD2`, serial `25174FD70E4D`) as new drive; Kingston (`nvme0n1`, model `KINGSTON SNV3S1000G`, serial `50026B7383B9D0CC`) as former system disk
- Updated `talos/talconfig.yaml`: changed `installDiskSelector.model` from `KINGSTON SNV3S1000G` → `CT1000P310SSD2`; added `machine.disks` patch mounting Kingston (`/dev/disk/by-id/nvme-KINGSTON_SNV3S1000G_50026B7383B9D0CC`) at `/var/mnt/longhorn-storage`; removed all cp-02 TODO comments
- Ran `task talos:genconfig` to regenerate all three node configs from updated talconfig
- Applied config in maintenance mode: `task talos:apply IP=10.60.0.202 INSECURE=true`; Talos installed to Crucial and rebooted cleanly
- Verified mount layout post-reboot: `nvme1n1p4 → /var` (Crucial = system disk), `nvme0n1p1 → /var/mnt/longhorn-storage` (Kingston = Longhorn storage, XFS auto-formatted)
- Waited for cp-02 to rejoin Kubernetes cluster as Ready control-plane node (all 3 nodes Ready, v1.36.1)
- Updated `node-configs/talos-cp-02.yaml`: `allowScheduling: false → true`
- Updated `helm/values.yaml`: `defaultClassReplicaCount` and `defaultReplicaCount` 2 → 3 (pending Flux reconciliation)

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | cp-02 `installDiskSelector` → Crucial P310; `machine.disks` patch added for Kingston; TODO comments removed |
| `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-02.yaml` | `allowScheduling: false → true`; holding comment removed |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | `defaultClassReplicaCount` and `defaultReplicaCount` 2 → 3; TODO comments removed |

### Key decisions
- `installDiskSelector.model: "CT1000P310SSD2"` used for Crucial — matches exact model string from `talosctl get disks`, consistent with cp-03's AirDisk selector pattern
- Kingston device path uses `nvme-KINGSTON_SNV3S1000G_<serial>` form (not EUI WWID) — matches cp-01's existing Kingston disk patch for readability and consistency
- Longhorn replica bump left as uncommitted GitOps change — takes effect via Flux reconciliation after push; no in-cluster emergency

---

## 2026-05-22 — `cluster-doc-sync`

### Goal
Run a cluster-doctor health diagnostic and sync CLUSTER.md component versions and ROADMAP.md completion status against live cluster state.

### What we did
- Spawned cluster-doctor agent for a full health audit; cluster all-green: 3 nodes Ready (Talos v1.13.2, K8s v1.36.1), all 27 Kustomizations and 17 HelmReleases Ready, all PVCs Bound, wildcard cert valid
- Agent identified 8 component versions in CLUSTER.md drifted ahead of documentation via Renovate auto-merges since last doc sync
- Updated CLUSTER.md section headings: Cilium (v1.17.6 → v1.19.4), CoreDNS (v1.43.0 → v1.45.2), Spegel (v0.4.0 → v0.7.1), cert-manager (v1.17.2 → v1.20.2), ESO (v0.18.2 → v2.5.0), FluxCD operator (v0.23.0 → v0.50.0), kube-prometheus-stack (v75.10.0 → v85.2.1), tuppr (v0.1.28 → v0.1.35)
- Agent confirmed metrics-server is fully deployed (HelmRelease v3.13.0, pod 1/1 Running 29h); removed from ROADMAP "In Progress" and added to Completed table
- Answered cert-manager-startupapicheck: Completed Job (7d old, no running pods); auto-cleaned on next cert-manager Helm upgrade via hook cleanup; no manual action needed; v1.17.2-labelled Job from initial install coexists with live v1.20.2 chart harmlessly

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | 8 component version headings bumped to match live cluster |
| `docs/ROADMAP.md` | metrics-server section removed from In Progress; row added to Completed table |

---

## 2026-05-22 — `renovate-oci-tag-fix`

### Goal
Review PRs #32 and #38 (cloudflared and Envoy Gateway upgrades); identify and fix Renovate OCI tag series drift in envoy-gateway and cert-manager annotations.

### What we did
- Reviewed PR #32 (cloudflared 2025.9.0 → 2026.5.0) via `pr-upgrade-reviewer` agent; confirmed two v2026.x breaking changes (proxy-dns removal in v2026.2.0, edge-ip-version default changed to "auto" in v2026.4.0) do not apply to this cluster's config (tunnel run only, no proxy-dns, no IP version pinning); verdict: safe to merge
- Reviewed PR #38 (Envoy Gateway v1.7.3 → 1.8.0) via `pr-upgrade-reviewer` agent; six v1.8.0 breaking changes documented (CRD sub-chart split, Gateway API v1.5.1, DirectResponse interpolation, SecurityPolicy timeout semantics, samplingFraction scale, OIDC filter restructure), none intersecting with this cluster's config
- Spotted that Renovate proposed tag `1.8.0` (no `v` prefix) despite current OCIRepository tag being `v1.7.3` — verified via Docker Hub API that both `v1.8.0` and `1.8.0` exist as separate OCI artifacts with different digests; unprefixed tag is the wrong upgrade path
- Added `extractVersion=^v(?<version>.*)$` to Renovate annotation in `oci/envoy-gateway.yaml` to lock Renovate to the `v`-prefixed tag series going forward
- Audited all 11 OCI repository annotation files; found `oci/cert-manager.yaml` also tracks a `v`-prefixed tag (`v1.20.2`) with the same dual-tag pattern on quay.io; applied the same `extractVersion` fix
- Recommended closing PR #38 and letting Renovate re-open with the corrected `v1.8.0` tag (or manually patching the tag in the PR before merging)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/envoy-gateway.yaml` | Added `extractVersion=^v(?<version>.*)$` to Renovate annotation |
| `kubernetes/flux/meta/repos/oci/cert-manager.yaml` | Added `extractVersion=^v(?<version>.*)$` to Renovate annotation |

### Key decisions
- `extractVersion=^v(?<version>.*)$` chosen as the fix — it filters Renovate's tag candidates to only `v`-prefixed ones so non-prefixed tags are invisible, rather than just relying on the current tag's format to guide updates
- Audit extended proactively to all OCI repo annotation files (not just envoy-gateway) to prevent the same tag-series drift from affecting cert-manager on its next Renovate PR

---

## 2026-05-22 — `app-template-v5-review`

### Goal
Review and merge PR #33 (app-template 4.6.2 → 5.0.1 major bump) and document the v5 breaking-change schema rules across the cluster documentation.

### What we did
- Used `pr-upgrade-reviewer` agent to assess PR #33 (Renovate-generated, app-template 4.6.2 → 5.0.1)
- Agent identified 5 breaking changes in v5.0.0: `rawResources` must wrap manifests under `manifest:` key; default ServiceAccount auto-created per controller; `automountServiceAccountToken` defaults to `false`; `NetworkPolicy` `controller`/`podSelector` are mutually exclusive; `ServiceMonitor`/`PodMonitor` `jobLabel` default changed to `app.kubernetes.io/name`
- Confirmed cloudflared (the only current app-template consumer) uses none of the affected features — no values changes required pre-merge; verdict: safe to merge
- Documented v5 schema rules: full authoring reference added to `docs/CONVENTIONS.md`; brief pointer added under GitOps Conventions in `CLAUDE.md`; version inventory entry added to `docs/CLUSTER.md`
- Decided CONVENTIONS.md was the correct home for detailed schema rules, consistent with the existing pattern where CLAUDE.md holds summary pointers and CONVENTIONS.md holds detailed authoring reference material

### Files changed
| File | Change |
|------|--------|
| `docs/CONVENTIONS.md` | Added app-template v5 section with 5 breaking rules, code examples, and upstream docs link |
| `CLAUDE.md` | Added brief app-template v5 pointer under GitOps Conventions |
| `docs/CLUSTER.md` | Added app-template shared chart library inventory entry under Running Components |

### Key decisions
- Schema details placed in `CONVENTIONS.md` rather than `CLAUDE.md` — CONVENTIONS.md is explicitly the "Extended Reference" supplement; keeping CLAUDE.md as a pointer index avoids bloating it with per-chart schema reference material

---

## 2026-05-22 — `connect-upgrade-fix`

### Goal
Review PRs #29 and #30, fix a pre-existing double-encoding bug in the 1Password Connect credentials secret, merge the Connect upgrade, and recover from a post-merge ClusterSecretStore outage.

### What we did
- Reviewed PR #29 (cert-manager v1.17.2→v1.20.2) and PR #30 (1Password Connect 2.0.1→2.4.1) using parallel `pr-upgrade-reviewer` agents
- PR #29 flagged CAUTION: `RotationPolicy` default flipped `Never→Always` in v1.18, and `issuerRef` API defaults re-introduced in v1.20 — provided two `kubectl` audit commands to run before merging
- PR #30 flagged CAUTION: chart v2.3.0 removed the double-base64 workaround for the credentials file — verified secret encoding to confirm impact
- Confirmed the live `onepassword-connect-secrets` secret was double-encoded (`base64(base64(json))`) — the bootstrap task explicitly piped `| base64 -w 0`, then Kubernetes added a second layer; old chart stripped one layer internally
- Explained the issue in depth: old chart read credentials via env var (expected base64 string, decoded it); new chart mounts as a plain file (no decode — single encoding required)
- Fixed the secret before merging: extracted inner JSON via double-decode, deleted and re-created the secret with single encoding, restarted Connect, confirmed `ClusterSecretStore` was `Ready=True` on chart v2.0.1
- Merged PR #30; Helm upgrade to connect@2.4.1 succeeded cleanly (`v3` release)
- Post-merge: `ClusterSecretStore` went `NotReady` with `cannot find secret data for key: "token"` — the Connect API token used by ESO had been dropped when the secret was re-created
- Diagnosed: original secret held two keys (`1password-credentials.json` + `token`); re-creation only restored the credentials file
- Recovery: read token from `op://homelab/HomeLab Access Token/credential`, patched the live secret, force-annotated `ClusterSecretStore` to trigger immediate ESO reconciliation — `Ready=True` within 10 seconds
- Updated the bootstrap task to remove `| base64 -w 0` so future re-bootstrap creates a correctly single-encoded secret

### Files changed
| File | Change |
|------|--------|
| `.taskfiles/bootstrap/Taskfile.yaml` | Removed `\| base64 -w 0` from credentials read in `onepassword-connect-secret` task |

### Key decisions
- Fixed and validated the secret encoding on the *old* chart first, before merging — proved Connect still worked with single-encoding under v2.0.1, reducing risk of a combined encoding + upgrade failure
- After the missing `token` was found post-upgrade, patched the existing secret rather than deleting-and-recreating to avoid dropping the credentials file a second time
- Used a `force-sync` annotation on the `ClusterSecretStore` to trigger immediate ESO reconciliation rather than waiting up to the natural polling interval

---

## 2026-05-22 — `renovate-pr-triage`

### Goal
Triage all open Renovate minor/patch PRs using parallel pr-upgrade-reviewer agents and harden the Renovate soak policy to close a gap where container image minors had no minimumReleaseAge.

### What we did
- Queried GitHub for all open Renovate PRs labelled `type/minor` or `type/patch` — found 9 PRs (#21, #22, #23, #24, #25, #26, #28, #29, #30)
- Launched 9 `pr-upgrade-reviewer` agents in parallel, one per PR, to assess upgrade risk
- Consolidated results: **4 SAFE** (#21 flux, #25 app-template, #26 coredns, #28 spegel), **3 CAUTION** (#22 cilium, #29 cert-manager, #30 1Password Connect), **2 HOLD** (#23 cloudflared, #24 envoy gateway)
- HOLD details: #23 stale — target `2025.11.1` is 6 months old, latest is `2026.5.0`; #24 — no release notes published, tag format anomaly (`1.8.0` vs `v1.7.3`), CRD sub-chart split, K8s v1.36 outside documented support matrix
- CAUTION details: #22 cilium requires 3 pre-merge kubectl checks (BGPv1 removal, v2alpha1 apiVersion, `FromRequires`/`ToRequires` CNP fields); #29 cert-manager `rotationPolicy` default flipped `Never→Always` in v1.18; #30 1Password Connect v2.3.0 fixed double-base64 encoding — verify secret was single-encoded
- Identified gap: container image minor/patch updates (non-Talos/K8s) had no `minimumReleaseAge` — only protected by the weekly schedule (0–7 day window), allowing PRs to open against incompletely-published releases
- Added a 3-day soak gate to `renovate.json5` for all container minor/patch updates excluding `siderolabs/installer` and `siderolabs/kubelet`; committed `4df7f84`

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Added `minimumReleaseAge: "3 days"` gate rule for container image minor/patch updates |

### Key decisions
- Used 9 parallel `pr-upgrade-reviewer` agents rather than a `/loop` — more efficient for a fixed known list; `/loop` is designed for time-based recurrence, not list iteration
- New soak rule uses `matchPackageNames` negation exclusions to avoid interfering with the existing 5-day soak rules for Talos/K8s, which are higher-priority and more restrictive

---

## 2026-05-22 — `kps-upgrade-85`

### Goal
Review, plan, and execute the kube-prometheus-stack upgrade from 75.10.0 to 85.2.1 (Renovate PR #34), safely sequencing CRD updates across 6 prometheus-operator minor bumps.

### What we did
- Ran `pr-upgrade-reviewer` agent on PR #34; identified 10 chart-major / 6 prometheus-operator-minor jump (v0.84.1 → v0.90.1) requires chart-native `crds.upgradeJob` pre-upgrade hook rather than relying solely on the global `crds: CreateReplace` Flux patch
- Verified `allowSchedulingOnControlPlanes: true` (in `talos/patches/controller/cluster.yaml`) removes the control-plane taint entirely — nodes have no taints; initial plan's `tolerations` block for `upgradeJob` was dropped
- Added `crds.enabled: true` + `crds.upgradeJob.enabled: true` to `values.yaml`; committed `7136a02` and pushed to main ahead of the PR merge
- Confirmed Flux reconciled the values change at 75.10.0 (HelmRelease advanced to release v2, "Helm upgrade succeeded"); ConfigMap verified to contain new `crds:` block
- Merged PR #34; upgrade completed to 85.2.1 — all 7 pods healthy, Prometheus CR `Reconciled: True` (distroless `v3.11.3`), Alertmanager CR `Reconciled: True` (`v0.32.1`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Added `crds.upgradeJob.enabled: true` block at top of file |

### Key decisions
- Dropped `crds.upgradeJob.tolerations` from the plan after live verification: `allowSchedulingOnControlPlanes: true` removes the taint outright; existing tolerations throughout `values.yaml` are redundant artefacts from chart defaults
- Committed values change to main before merging the OCIRepository tag PR so Flux could verify the Job wiring at the current version before the 10-version jump landed; treats the upgrade as forward-only (CRD downgrade not feasible after)

---

## 2026-05-22 — `renovate-improvements`

### Goal
Review the Renovate configuration and implement five targeted improvements: auto-merge rules for Helm patches and image digests, a kustomize manager regex fix, package grouping for major stacks, and release soak periods for Talos and Kubernetes.

### What we did
- Reviewed `renovate.json5` against `docs/ROADMAP.md` to identify 6 improvement opportunities
- Fixed a silent bug in the kustomize manager: regex `^kustomization` only matched the root-level file; changed to `(^|/)kustomization` so all `kustomization.yaml` files under `kubernetes/apps/` are now scanned by Renovate
- Added auto-merge for Helm chart patch updates after a 3-day community soak — eliminates the majority of patch PRs silently via `automergeType: "branch"`
- Added auto-merge for container image digest updates after a 1-day soak (digest = same tag, new SHA; no version change); excluded `siderolabs/installer` and `siderolabs/kubelet` which go through tuppr
- Added `minimumReleaseAge: "5 days"` to Talos and Kubernetes rules so PRs don't open until the community has had time to surface regressions in OS/runtime releases
- Added grouping rules for 5 previously ungrouped stacks: Longhorn, kube-prometheus-stack, Envoy Gateway, ExternalDNS, External Secrets
- Evaluated `.renovate/` config split (improvement 6) — determined it requires proper Renovate local preset format (not a raw file drop), adds real complexity at the current file size (~282 lines); deferred with a threshold of ~400 lines
- Expanded the existing ROADMAP stub for the Renovate config split with correct preset mechanics, exact `extends` syntax, concrete per-file split plan, and trigger threshold

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Auto-merge rules (Helm patch + digest), kustomize regex fix, 5 new group rules, 5-day soak on Talos/K8s |
| `docs/ROADMAP.md` | Expanded Renovate config split entry with local preset mechanics and step-by-step implementation guide |

### Key decisions
- Excluded `siderolabs/installer` and `siderolabs/kubelet` from digest auto-merge — even a same-SHA digest refresh on those images warrants awareness given they go through tuppr's upgrade machinery
- Chose 5-day soak for Talos/K8s (vs 3-day for charts) — OS and runtime regressions are harder to recover from and community reports tend to appear later than chart issues
- Deferred `.renovate/` split: the key non-obvious blocker is that split files must be valid Renovate presets referenced via `extends`, not raw fragments auto-scanned from the directory — the refactor has real cost and the file is still manageable

---

## 2026-05-22 — `talos-audit-ntp`

### Goal
Cluster health check and Talos config/schematic audit via cluster-doctor; implement the NTP server expansion (Finding 2.6) with 4 EU/NL-prioritised sources applied live across all nodes.

### What we did
- Reviewed cluster status and roadmap after a 2-day gap; confirmed Green health and identified Talos config/schematic audit as the top priority before proceeding with new deployments
- Ran cluster-doctor agent for combined live cluster health audit + full Talos config/schematic review:
  - All 3 nodes Ready (Talos v1.13.2, K8s v1.36.1); all 26 Kustomizations + 17 HelmReleases True; both Longhorn volumes Healthy on cp-01 + cp-03
  - Elevated restart counts on several pods identified as historical artefacts from the 2026-05-15 recovery incident, not ongoing instability
  - Schematic verified clean: `iscsi-tools`, `util-linux-tools`, `intel-ucode`, `amd-ucode` all present; no missing extensions for the hardware profile
  - Sysctls (10 GbE socket buffers), NFS defaults, etcd subnet restrictions, cluster.yaml, machine-features all verified correct
  - 6 findings produced: 2.1 (bond driver-glob selectors on cp-01/cp-02), 2.6 (only 2 NTP sources), 2.3/2.5 deferred, 3.x acceptable-as-is
- Planned and implemented Finding 2.6 — expanded NTP from 2 to 4 sources with EU/NL preference:
  - Added `ntp.time.nl` (SIDN/NLNOG Dutch stratum 1) and `nl.pool.ntp.org` (NL zone pool) to replace generic `pool.ntp.org`; kept `time.cloudflare.com`; added `time.google.com` for AS diversity
  - Applied staggered (cp-01 → cp-02 → cp-03); all nodes applied without reboot and stayed Ready throughout
  - Verified: `TimeServerStatus` shows all 4 servers on all 3 nodes; `TimeStatus SYNCED: true` on all nodes

### Files changed
| File | Change |
|------|--------|
| `talos/patches/global/machine-time.yaml` | Expanded NTP servers from 2 to 4 (EU/NL preference) |

### Key decisions
- Chose `ntp.time.nl` (operated by SIDN + NLNOG) as the primary NL-specific source — the most authoritative Dutch stratum-1 server available publicly, not a generic pool alias
- Replaced `pool.ntp.org` with `nl.pool.ntp.org` for geographic locality; kept `time.cloudflare.com` (AS13335) and added `time.google.com` (AS15169) so the two anycast sources come from independent autonomous systems
- 4 distinct sources unlocks chrony's Marzullo algorithm for falseticker detection; with only 2 sources chrony can detect disagreement but cannot identify which server is wrong

---

## Archived sessions

Sessions older than **2026-05-22** (the bootstrap/setup era, **2026-05-06 → 2026-05-21**) have been moved to [SESSIONS-ARCHIVE.md](SESSIONS-ARCHIVE.md) to keep this active log lean. Grep the archive the same way you grep this file.
