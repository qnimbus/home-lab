# Home Lab — Cluster Roadmap <!-- omit from toc -->

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

## Contents  <!-- omit from toc -->

- [In Progress](#in-progress)
  - [WAN Failover Router: Host Header Rewrite](#wan-failover-router-host-header-rewrite)
  - [Renovate PR-Review Workflow: Cost/Bug Investigation, Re-enable](#renovate-pr-review-workflow-costbug-investigation-re-enable)
  - [CloudNativePG: Backup, PITR, and Per-App Provisioning](#cloudnative-pg-backup-pitr-and-per-app-provisioning)
  - [Postgres NFS Backup: Restore Drill](#postgres-nfs-backup-restore-drill)
  - [~~Longhorn Storage Network (Multus + Storage VLAN)~~ — ABANDONED](#longhorn-storage-network-multus--storage-vlan--abandoned-superseded-by-rook-ceph)
  - [Rook-Ceph Migration](#rook-ceph-migration)
  - [Future Storage Options](#future-storage-options)
  - [Grafana](#grafana)
  - [Alertmanager Receiver](#alertmanager-receiver)
  - [Prometheus Metric Hygiene: Drop Static and Low-Value Series](#prometheus-metric-hygiene-drop-static-and-low-value-series)
  - [Scheduling Topology: Follow-up Fixes](#scheduling-topology-follow-up-fixes)
  - [Kubernetes Descheduler](#kubernetes-descheduler)
  - [Talos Config, Image Extensions \& Patch Audit](#talos-config-image-extensions--patch-audit)
  - [Migrate Remaining HelmRepositories to `home-operations/charts-mirror`](#migrate-remaining-helmrepositories-to-home-operationscharts-mirror)
  - [Tailscale kubectl Authentication (RBAC)](#tailscale-kubectl-authentication-rbac)
  - [Cilium BGP Control Plane (replace L2 Announcement)](#cilium-bgp-control-plane-replace-l2-announcement)
  - [CSI Snapshots (external-snapshotter + Ceph VolumeSnapshotClass)](#csi-snapshots-external-snapshotter--ceph-volumesnapshotclass)
  - [VolSync (PVC Backup)](#volsync-pvc-backup)
  - [Researched Patterns (bykaj/home-ops)](#researched-patterns-bykajhome-ops)
- [Completed](#completed)

---

## In Progress

### WAN Failover Router: Host Header Rewrite

**Status: fix committed (2026-07-08), pending live verification.** `wan-failover.${DOMAIN_CLUSTER}` proxied a physical router's web UI at a raw IP via `HTTPRoute` + a manually-managed `EndpointSlice`. The router's firmware validates the inbound `Host` header against its own IP and rejects/misbehaves on the proxied hostname.

Two Gateway-API-level fixes were tried and both failed in ways that made things worse, not just ineffective:
- `URLRewrite.hostname` rejects IP literals outright (`"cannot be an ip address"`).
- `RequestHeaderModifier` silently strips `Host` from its `set` list as a disallowed header, leaving the filter with nothing to apply.

Either failure leaves the `HTTPRoute` `Accepted: False`, which has a second-order effect: `external-dns-unifi` (`sources: [gateway-httproute, service]`, `policy: sync`) only advertises DNS records for `Accepted` routes and actively deletes them otherwise — so a rejected filter doesn't just fail to fix the Host-header problem, it also takes down DNS resolution for the hostname entirely (this happened live, twice).

**Resolved differently, at the user's direction**: bypass Envoy Gateway for this hostname entirely rather than fight its Host-rewrite restrictions. `kubernetes/apps/network/external-services/wan-failover/service.yaml` is now a single `Service` with no real endpoints, carrying `external-dns.alpha.kubernetes.io/target: 192.168.8.1` — this makes `external-dns-unifi`'s `service` source point the DNS record straight at the router's LAN IP instead of the Gateway's LB IP. The browser then connects directly to the router over plain HTTP (`http://wan-failover.${DOMAIN_CLUSTER}`, not `https://`) exactly as if it had typed `http://192.168.8.1` — no proxy, no TLS termination, no Host-header rewrite needed since there's no hop that changes it. `HTTPRoute`/`EndpointSlice` removed; the `envoy-gateway-config` `dependsOn` in `ks.yaml` removed too since this app no longer touches the Gateway at all. Considered and rejected: a small reverse-proxy sidecar (nginx/Caddy) that would do the rewrite itself — works, but judged too heavy for what this is.

### Renovate PR-Review Workflow: Cost/Bug Investigation, Re-enable

**Status: disabled (2026-07-04).** `.github/workflows/renovate-pr-review.yml` (invokes the `pr-upgrade-reviewer` agent via `claude-code-action` on Renovate PRs) was racking up unexpected Claude usage costs. Disabled with `gh workflow disable renovate-pr-review.yml -R qnimbus/home-lab` while the cause is investigated — re-enable with `gh workflow enable renovate-pr-review.yml -R qnimbus/home-lab` once resolved.

One contributing bug already found and fixed in the same session: on `workflow_dispatch` (manual) runs, the agent had no way to tell "local checkout" (the PR's own head commit) apart from live `main`, and on PR #71 falsely declared the PR "superseded" purely from local file contents already matching the PR's own change. Fixed in commit `f522e97` by grounding the agent explicitly — both the workflow's `prompt:` and the `pr-upgrade-reviewer` agent's own operational constraints now state that a local file read is never sufficient evidence about `main`'s state.

**Still to investigate before re-enabling:**
- What is actually driving the cost overrun — re-runs triggered per PR update, large `WebFetch`/`WebSearch` volume (fetching full release notes/changelogs per run), an unbounded retry loop, or something else not yet identified.
- Whether the `f522e97` grounding fix is sufficient on its own, or should be paired with tighter guardrails (e.g. narrower `--allowedTools`, capping WebFetch/WebSearch calls per run, gating manual `workflow_dispatch` runs the same way automatic runs are label-gated).

### CloudNativePG: Backup, PITR, and Per-App Provisioning

The `cloudnative-pg-deploy` session deployed the CNPG operator and a shared `postgres-v17` cluster (3 instances, `openebs-hostpath`). Three follow-on items were explicitly deferred:

#### 1 — Barman-cloud plugin + S3 WAL archiving (PITR) ✅

Deployed 2026-06-18. The cluster previously had HA via streaming replication but no point-in-time
recovery; barman-cloud now provides continuous WAL archiving plus daily base backups to a Storj.io
S3-compatible bucket, closing that gap.

**What was implemented:**

1. **OCIRepository** `kubernetes/flux/meta/repos/oci/plugin-barman-cloud.yaml` — `oci://ghcr.io/cloudnative-pg/charts/plugin-barman-cloud` (cosign-verified, same publisher pipeline as the CNPG operator chart)
2. **plugin-barman-cloud Kustomization** `kubernetes/apps/database/cloudnative-pg/plugin-barman-cloud/app/` — HelmRelease only. The chart is fully self-contained (creates its own cert-manager `Issuer`/`Certificate`s and a pre-annotated `Service` for plugin discovery) — no manual TLS resources needed, simpler than originally scoped below
3. **ObjectStore CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml` — targets an existing Storj.io bucket (`https://gateway.storjshare.io`), not Cloudflare R2/Backblaze B2 as originally planned. Storj's client-side-encrypted, erasure-coded architecture (no single custodian holds a complete decryptable copy) avoids the US CLOUD Act exposure that R2/B2 share regardless of EU data-residency settings
4. **ScheduledBackup CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/scheduledbackup.yaml` — daily `02:00 UTC` base backup, `method: plugin`, `backupOwnerReference: self`, `immediate: true`
5. **Cluster CR** — `plugins: [{isWALArchiver: true, name: barman-cloud.cloudnative-pg.io}]`; `serverName` parameterized via `postBuild.substitute.CNPG_V17_CURRENT_CLUSTER` in `ks.yaml`

**1Password fields added** to the existing `cloudnative-pg` item: `S3_ACCESS_KEY`, `S3_SECRET_KEY` (Storj access key ID / secret key).

**Two non-obvious bugs found during live testing** (fixed in commits `ff4c48d` / `9c883a6`):
- The existing ExternalSecret's `target.template.data` block is an explicit key allow-list — `dataFrom.extract` + `rewrite.regexp` only populates the *template's* variable namespace, it does **not** automatically add new keys to the rendered Secret. Adding the 1Password fields alone did nothing until `CNPG_S3_ACCESS_KEY`/`CNPG_S3_SECRET_KEY` were added explicitly to `template.data`.
- Storj's S3 gateway rejects `PutObject` calls using botocore's newer chunked-trailer checksum encoding (`MissingContentLength`). Fixed via `ObjectStore.spec.instanceSidecarConfiguration.env`, setting `AWS_REQUEST_CHECKSUM_CALCULATION`/`AWS_RESPONSE_CHECKSUM_VALIDATION` to `when_required` — the only override point the plugin exposes for the per-instance sidecar that runs both WAL archiving and base backups.

**Verified working:** `ContinuousArchiving` and `LastBackupSucceeded` Cluster conditions both `True`; a manual test `Backup` completed end-to-end (hot/online, ~4s) with objects confirmed landing in the Storj bucket.

**Recovery verified via live drill (2026-06-18):** a disposable `postgres-v17-restore-test` Cluster (`kubernetes/apps/database/cloudnative-pg/restore-test/`, removed again after the drill) recovered via `bootstrap.recovery.source` + `externalClusters[].plugin` pointing at the same `cloudnative-pg-backup` ObjectStore — `Cluster` object created to `Ready` in **54 seconds**, replaying ~5h24m of WAL forward from the most recent base backup. Confirmed as a genuine physical recovery (not a coincidentally-matching empty cluster) via `pg_control_system()`: identical `system_identifier` on source and recovered cluster, with the recovered cluster correctly promoted onto a new timeline (`1` → `2`). The renamed `cloudnative-pg-backup` ObjectStore (was `cloudnative-pg-storj`, made provider-agnostic since the CR name shouldn't bake in the current S3 backend) and a commented `bootstrap.recovery`/`externalClusters` template + runbook now live directly in `cluster.yaml` for the real disaster-recovery case — since CNPG only consults `spec.bootstrap` once, at `Cluster`-object creation, a full reset/rebootstrap today would otherwise silently `initdb` an empty database instead of recovering. Automated via `just cnpg restore-from-backup`/`undo-restore` (`ops/cnpg/mod.just`).

**Dependency chain:** `cloudnative-pg-operator → plugin-barman-cloud → cloudnative-pg-cluster` (`ks.yaml` `dependsOn`).

**Migrated to Backblaze B2 (2026-06-21):** Storj replaced as a temporary stopgap, not a permanent provider decision. Only `objectstore.yaml`'s `destinationPath`/`endpointURL` changed — no ExternalSecret/Cluster changes needed, since the ExternalSecret's `dataFrom.extract` + regex rewrite already exposes whatever `S3_ACCESS_KEY`/`S3_SECRET_KEY` values live in 1Password, and B2's `keyID`/`keySecret` map directly onto those AWS-style fields. Two regressions accepted knowingly: B2's region is fixed at the *account* level (not per-bucket), so EU data locality would need a separate account; and barman-cloud only supports server-side encryption (`AES256`/`aws:kms`), never client-side, so Backblaze itself can technically decrypt these backups — Storj's no-custodian-decrypt property is gone.

**The actual bug, after a lot of misdirection:** WAL archiving failed 100% of the time with `IncompleteBody: The request body was too small` against B2. Several plausible fixes were tried and individually disproven against the live cluster: `wal.maxParallel: 1` + trailing-slash `destinationPath` (from `cloudnative-pg/cloudnative-pg#7105`), `s3Credentials.region` + `AWS_DEFAULT_REGION` (`#9724` — a real bug, but for a different symptom, `SignatureDoesNotMatch` on retention-policy `ListObjectsV2`, not the WAL-archive failure), and downgrading `plugin-barman-cloud` `0.7.0` → `0.6.0` to rule out a library regression (same error reproduced on the older `barman-cloud@v0.5.0`). The actual cause: **the bucket name contained a literal dot** (`vwn.io-cluster-cnpg`) — AWS's own S3 docs warn against periods in bucket names because of HTTPS/virtual-hosted-style hostname-matching issues, and Backblaze's S3-compatible API broke the same way. Renaming to a dot-free bucket (`vwn-io-cluster-cnpg`) fixed `IncompleteBody` immediately, found by comparing against `bykaj/home-ops`'s working B2 config in the same region (`us-west-001`) with none of the speculative fixes applied.

**Re-verified live on the actual production cluster (2026-06-21):** ran the full `just cnpg restore-from-backup` → delete `Cluster` → Flux recreate → `just cnpg undo-restore` cycle for real, rather than a disposable test cluster (the database had no real data yet, so the risk was accepted). Confirmed genuine recovery via WAL timeline promotion (`1` → `2`) in `pg_control_checkpoint()`, not a coincidentally-healthy empty `initdb`.

---

#### 2 — Local NFS backup (postgres-backup-local) ✅

Deployed. `pg_dumpall` CronJob running daily at midnight (Europe/Amsterdam) writing to `10.200.0.41:/mnt/tank/Cluster/cloudnative-pg` (storage VLAN). Retention: 7 days / 4 weeks / 6 months. Runs as UID 4000 (non-root).

**Gotchas discovered during deployment:**
- TrueNAS NFS service must be explicitly bound to the storage VLAN interface (`bond1`) — it does not auto-bind to new interfaces
- `POSTGRES_DB: "*"` glob-expands to the NFS mount directory name (`backups`) in the script's working directory — use `POSTGRES_CLUSTER: "TRUE"` instead
- `pg_dumpall` does not support `-Z` (compression) or `-C` (create database) flags — use `POSTGRES_EXTRA_OPTS: "-c"` only
- TrueNAS dataset must be `chown 4000:4000` before the pod runs; numeric UID works fine without a named user on TrueNAS

**Restore workflow:** see roadmap item [Postgres NFS Backup: Restore Drill](#postgres-nfs-backup-restore-drill).

---

#### 3 — Per-app database and user provisioning

Apps that need PostgreSQL connect to the shared `postgres-v17` cluster. Two patterns exist:

**Option A — CNPG managed resources (preferred):** Use the `Database` and `Pooler` CRDs that CNPG installs. Each app gets its own `Database` CR (creates the database), a `ClusterRoleBinding` for the app's service account, and optionally a `Pooler` CR (PgBouncer sidecar for connection pooling). Credentials surface as a Secret that the app mounts.

**Option B — Manual provisioning:** `kubectl exec` into the primary pod and run `CREATE DATABASE` / `CREATE USER` / `GRANT`. Fast but not GitOps — avoids CRD complexity for one-off databases.

For the first app needing Postgres, use Option B to unblock quickly; migrate to Option A once the pattern is clear.

**Connection string format** (within cluster):
```
postgresql://<user>:<password>@postgres-v17-rw.database.svc.cluster.local:5432/<dbname>
```
The `postgres-v17-rw` Service is created automatically by CNPG and always points to the current primary.

---

#### 4 — Major version upgrade path (17 → 18)

CNPG supports in-place major version upgrades by creating a new cluster from a backup of the old one. The `postBuild.substitute` + `CNPG_V17_CURRENT_CLUSTER` / `CNPG_V17_PREVIOUS_CLUSTER` variables in `ks.yaml` (see bykaj reference `cluster/ks.yaml`) encode the active and previous cluster names so the `recovery.source` in the Cluster CR can be managed without editing YAML.

**When to implement:** barman-cloud (item 1 above) is now done, and its `bootstrap.recovery`/`externalClusters` mechanics have been proven end-to-end via a live drill — not just theoretically unblocked. Pick up when a 17 → 18 upgrade is actually needed.

---

### Postgres NFS Backup: Restore Drill

The `postgres-backup-local` CronJob writes a daily `pg_dumpall` backup to TrueNAS (`/mnt/tank/Cluster/cloudnative-pg`). A backup that has never been tested for restore is not a backup. This item tracks the restore workflow and periodic drills.

**Why not restore straight into `postgres-v17-rw`:** `postgres-backup-local` dumps with `POSTGRES_EXTRA_OPTS: "-c"` (clean), so the dump is a single linear script containing `DROP DATABASE`/`DROP ROLE`/`CREATE DATABASE` statements ahead of each database's data. There is no way to selectively replay that "into a temporary database" on the same live server — piping it into `postgres-v17-rw` as superuser would drop and recreate every database on the production cluster. The only way to honor "never touch live data" is a fully disposable scratch Postgres server that never contacts `postgres-v17-rw`, mirroring the barman-cloud restore drill ([item 1 above](#1--barman-cloud-plugin--s3-wal-archiving-pitr-)).

**Restore drill:** automated via `just cnpg nfs-restore-drill` (`ops/cnpg/mod.just`). The recipe:
1. Starts a disposable `postgres:17` pod (official image, not the `prodrigestivill/postgres-backup-local` client wrapper) with the NFS backup share mounted **read-only**
2. Discovers the latest backup filename dynamically from `/backups/last/*.sql.gz` inside that pod (never assumes a fixed filename)
3. Restores the dump into the scratch instance only, via plain `psql` (deliberately **without** `ON_ERROR_STOP`), timing the operation. A `pg_dumpall --clean` dump replayed by connecting as the very role it drops/recreates (`postgres`) always throws a handful of harmless, well-documented self-referential errors for that one role — can't drop your own current role, so the role "already exists" on the subsequent `CREATE ROLE`, so the dump's recorded `GRANTED BY postgres` can't be replayed until that role holds admin on the granted role. The recipe scans the output and fails only on errors **outside** that known/tolerated set — there is no `pg_restore_log` to check (that's `pg_restore`/custom-format terminology; this is a plain-text dump restored via `psql`)
4. Verifies by comparing database list (`pg_database`) and role list (`pg_roles`) between the scratch (restored) instance and the live `postgres-v17` primary — the live-side check is read-only, via `kubectl exec` into the existing CNPG primary pod (local trust auth as the `postgres` OS user), so the production superuser password is never extracted from `cloudnative-pg-secret`
5. Tears the scratch pod down unconditionally (`trap ... EXIT`), so a failed run never leaves an orphaned pod. Set `KEEP_SCRATCH=1` to skip auto-teardown for manual inspection (used for the canary check below)

**Bug found and fixed by the first drill run:** `postgres-backup-local`'s `POSTGRES_EXTRA_OPTS` was `"-c"` only, which makes `pg_dumpall` emit *unconditional* `DROP DATABASE`/`DROP ROLE` statements. Restoring onto a fresh/empty target (exactly the disaster-recovery scenario this backup exists for) failed immediately on the first `DROP DATABASE app` — the database that never existed there. Fixed by adding `--if-exists` (commit `18a053a`, pushed) — the standard pairing for `--clean` that makes those drops conditional.

**Restore drill checklist:**
- [x] Confirm the drill restored into the disposable scratch pod only — `postgres-v17-rw` was never contacted (structural: the recipe never references that Service)
- [x] Confirm database list and role list match between scratch and live (modulo the scratch pod's own bootstrap defaults)
- [x] Confirm no *unexpected* `ERROR`/`FATAL` lines in `psql` output (the tolerated self-referential `postgres`-role errors above are expected on every run, not a failure signal)
- [x] Document the time taken (RTO) — printed by the recipe on completion
- [x] Confirm the scratch pod was deleted (`kubectl get pod -n database` shows it gone)

**Scope note:** no per-app data exists on `postgres-v17` yet — [item 3, per-app provisioning](#3--per-app-database-and-user-provisioning), is still pending — so the first drill run seeded a throwaway canary database/table on production (then deleted it) purely to give the row-count check something real to verify. Going forward, re-run this drill after item 3 lands real app data and extend the verification step to compare row counts for the app's key tables.

**When to drill:** after first successful backup, then every 3 months or after any major Postgres version upgrade. Each run is recorded below:

| Date | Duration (RTO) | Pass/Fail | Notes | Next due |
|------|-----------------|-----------|-------|----------|
| 2026-06-18 | 4s | ✅ Pass | First run. Found+fixed a real restore-blocking bug (missing `--if-exists`, commit `18a053a`). Canary dataset (50 rows) restored intact, matching live exactly; database/role lists matched | 2026-09-18 |

**Real disaster-recovery restore (production-touching):** automated via `just cnpg nfs-restore-from-backup` (`ops/cnpg/mod.just`) — the actual incident-recovery procedure, distinct from the disposable drill above. **Only safe when `postgres-v17` has no data worth losing** (verified live by the recipe before it asks for confirmation) — it restores **directly into `postgres-v17-rw`**, dropping and recreating every database. The recipe:
1. Prints the current database list on `postgres-v17-rw` and warns explicitly before asking to proceed
2. Starts a helper pod (official `postgres:17` image, command overridden to `sleep infinity` so it never runs its own `initdb`) with the NFS share mounted read-only and `PGHOST`/`PGUSER`/`PGPASSWORD` wired from `cloudnative-pg-secret` via `secretKeyRef` — credentials never pass through a shell or this tool's context
3. Discovers the latest backup file and prints its mtime for visual confirmation, behind a second confirm gate
4. **Terminates all other active backend connections** to `postgres-v17-rw` (`pg_terminate_backend`) immediately before restoring — `DROP DATABASE` refuses to run while *any* session, even idle, is connected, and pgAdmin keeps a persistent connection open per database it has browsed
5. Restores via `gunzip | psql` (no `ON_ERROR_STOP`), timing the run, and tolerates the same self-referential role errors as the drill plus one CNPG-specific case: `streaming_replica` (CNPG's permanent replication role) can't be dropped because it permanently holds `EXECUTE` grants on file-access functions used by CNPG's instance manager — that role is reconciled by the CNPG operator independently of this dump, so leaving it untouched is correct
6. Prints the database list again and tears the helper pod down unconditionally

**First real run (2026-06-19):** validated end-to-end against live production with no per-app data at risk (`app` had zero user tables at the time). Two real, previously-undiscovered issues surfaced and were fixed before the run that finally passed cleanly:
- A `gum log` formatting bug: passing a multi-line message as several separate quoted strings (used purely for source readability) followed by a trailing `stage <value>` pair caused `gum` to mis-pair the extra strings as bogus key/value fields, garbling the rendered warning. Fixed by collapsing each multi-string message into one string — also retroactively fixed in `nfs-restore-drill`'s verify-warning and `restore-from-backup`'s existing-cluster warning, which had the same latent bug.
- `streaming_replica`'s standing function grants blocking `DROP ROLE` (see step 5) — added to the tolerated-error filter.
- pgAdmin's idle per-database connections blocking `DROP DATABASE` (see step 4) — fixed by terminating other backends immediately before the restore.

| Date | Duration (RTO) | Pass/Fail | Notes | Next due |
|------|-----------------|-----------|-------|----------|
| 2026-06-19 | 1s | ✅ Pass | First real run against `postgres-v17-rw` (no per-app data at risk). Two attempts failed and were fixed in-flight (`streaming_replica` grant-dependency tolerance, pgAdmin connection termination) before a clean pass; also fixed a latent `gum log` formatting bug found along the way | 2026-09-19 |

**Dependencies:** `postgres-backup-local` ✅ (backup running)

---

### ~~Longhorn Storage Network (Multus + Storage VLAN)~~ — ABANDONED, superseded by Rook-Ceph

> **Status: ABANDONED (2026-06-05).** After 5 attempts, routing Longhorn engine↔replica traffic onto
> the storage VLAN via Multus + whereabouts (ipvlan-L3) was abandoned on an unsolvable **same-host iSCSI**
> blocker. The full attempt log, root-cause analysis, and the whereabouts PR #703 finding are preserved in
> [history/longhorn-storage-network.md](history/longhorn-storage-network.md); the distilled root cause is in
> [QA.md](QA.md#why-was-routing-longhorn-replica-traffic-onto-the-storage-vlan-abandoned). The storage-VLAN
> isolation goal now moves to **Rook-Ceph**, whose native `cluster_network` on `hostNetwork` OSDs sidesteps
> the same-host problem — see [Rook-Ceph Migration](#rook-ceph-migration) below and
> [HARDWARE-ARCHITECTURE.md](HARDWARE-ARCHITECTURE.md).
>
> All Multus/whereabouts/NAD scaffolding + the Cilium `cni.exclusive` override + cross-node `/28` Talos
> routes were removed in the rollback (commit `299904e`). `bond-storage` + jumbo MTU are **kept** (Ceph
> reuses the fabric).

**~~Still-valid tuning lifted from the abandoned plan~~ — VOID (Longhorn removed):** the carried-over
suggestion to raise Longhorn's `replicaReplenishmentWaitInterval` (`600`→`900` s) no longer applies —
the `kubernetes/apps/longhorn-system/` tree was deleted in the Rook-Ceph migration. Ceph's analogous
behaviour (delaying recovery after a node loss so the network can converge) is governed by the OSD's
`mon_osd_down_out_interval` (default 600 s), which is already conservative; no change needed.

---

### Rook-Ceph Migration

The committed replacement for both Longhorn (interim) and the abandoned storage-VLAN isolation effort.
Target topology, drive placement, failure-domain design, and the 5-node expansion context are specified in
**[HARDWARE-ARCHITECTURE.md](HARDWARE-ARCHITECTURE.md)** (Rook-Ceph `size=3`/`min_size=2`, `host` failure
domain, OSDs on the `10.200.0.0/24` bond). Detail intentionally lives in the hardware doc — do not duplicate
it here.

**✅ COMPLETE (2026-06-10).** Rook-Ceph v1.19.6 deployed via Flux under `kubernetes/apps/rook-ceph/`
(operator + cluster split, host networking with `cluster_network` on the storage bond, OSDs pinned by
`/dev/disk/by-id`); `HEALTH_OK` with 3 host-spread OSDs. `ceph-block` is the **default StorageClass**.

- **Phase 4** — operator + cluster deployed; storage-fabric benchmarked (~19.3 Gbit/s aggregate, drive-bound).
- **Phase 5** — all consumers re-pointed from longhorn → `ceph-block`: **pgadmin** (canary, disposable),
  **waha** (WhatsApp `gows/` session restored from NFS, reconnected `WORKING` no QR re-scan), and
  **kube-prometheus-stack** (grafana `grafana.db` restored from NFS; prometheus/alertmanager fresh). The
  prometheus+alertmanager StatefulSets were deleted out-of-band first (immutable `volumeClaimTemplates`).
  Stale longhorn PVC/PV zombies (never deleted, only backed up) were force-cleared. Longhorn fully gone.

#### Toolbox deployment style (current: chart built-in)

Phase 4 enables the **chart-supplied** toolbox (`toolbox.enabled: true` in the `rook-ceph-cluster`
HelmRelease) — a single `rook/ceph` Deployment giving the `ceph` CLI in-cluster
(`kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status`). Lowest-maintenance option;
sufficient for status/debugging.

**Possible future switch — standalone `app-template` toolbox** (ByKaj pattern,
`tmp/home-ops-bykaj/.../rook-ceph-tools/`): a separate `bjw-s/app-template` HelmRelease with the chart's
built-in toolbox turned off. Worth adopting only for extras the built-in lacks — an NFS `Transfer` mount for
exporting/importing RBD images or `ceph` dumps to the NAS, explicit resource limits + Reloader annotations,
or a toolbox image pinned by digest independent of the chart. Cost: one more HelmRelease + OCIRepository to
maintain. Defer until a concrete need (e.g. offline image export) appears.

---

### ~~cp-02 Thermal Stability (Lenovo M920Q)~~ — RESOLVED

> **Status: RESOLVED.** Two distinct fault patterns on this M920Q unit (now `talos-worker-02`,
> 10.60.0.205) — a 2026-06-01 board/VRM thermal shutdown, and a series of recurring silent
> hard-downs spanning 2026-06-02 → 2026-06-21 — are both closed. The thermal fault was fixed by
> a heatsink clean + repaste (2026-06-17); the hard-downs were root-caused (2026-06-22) to a
> failing external power brick via MemTest86 hardware-isolation, which has since been replaced
> and confirmed stable. Full investigation timeline, diagnostics, and tooling:
> [history/cp02-worker02-hardware-faults.md](history/cp02-worker02-hardware-faults.md).

---

### Future Storage Options

Replicated block storage is covered by the committed [Rook-Ceph Migration](#rook-ceph-migration) (Ceph also
provides RWX block volumes and S3-compatible object storage natively). The remaining optional item:

- **NFS/SMB CSI**: Deploy `csi-driver-nfs` and/or `csi-driver-smb` for ReadWriteMany file workloads (photo libraries, shared media) backed by the NAS. Wire credentials via ExternalSecret from 1Password (ESO + 1Password Connect already deployed — no blocker). Optional even after Rook-Ceph, for NAS-backed RWX where Ceph capacity should be conserved.

---

### Storage VLAN Performance Benchmarking

A repeatable benchmark suite for the storage VLAN fabric. Run after any network change (MTU, bonding config, switch firmware, node add/replace) and periodically as a regression check. Methodology developed during the `jumbo-frames-storage-vlan` session.

All tests use host-network pods bound to the storage VLAN IP (`-B 10.200.x.x`) to bypass Cilium and measure the raw bond path. The iperf3 server on TrueNAS must be running (`iperf3 -s -D`; for the bond test also `iperf3 -s -p 5202 -D`).

#### Test 1 — Single-stream link health (run per node)

```bash
kubectl run iperf3-raw --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-01"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.201 -t 10
# Repeat with cp-02 (10.200.0.202) and cp-03 / -B 10.200.0.203 / bond1
```

**Pass:** ≥9.8 Gbps, ≤100 retransmits. Failure indicates link degradation, MTU mismatch, or CC misconfiguration.

#### Test 2 — MTU end-to-end verification (MSS 8960 = MTU 9000 − 40)

```bash
kubectl run iperf3-raw --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 5 -M 8960
```

**Pass:** connection succeeds, Cwnd reaches ≥2 MB. Failure means a hop is still at 1500 MTU.

#### Test 3 — Bond utilization (bidirectional simultaneous)

```bash
kubectl run iperf3-send --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 12 -P 8 -p 5201 &
kubectl run iperf3-recv --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 12 -P 8 -p 5202 -R &
```

**Pass:** combined send + receive ≥25 Gbps (proves both bond members active). ≤10 Gbps total means one bond member is down or the switch is distributing incorrectly.

#### Prometheus metrics to monitor

Node-exporter exposes per-interface byte counters. Wire into Grafana once deployed:

```promql
# Per-bond-member throughput on storage NICs
rate(node_network_receive_bytes_total{device=~"enp1s0f[01]|enp5s0f[01]np[01]"}[5m]) * 8
rate(node_network_transmit_bytes_total{device=~"enp1s0f[01]|enp5s0f[01]np[01]"}[5m]) * 8
# TCP retransmit rate (cluster-wide)
rate(node_netstat_Tcp_RetransSegs[5m])
```

Bond member devices: cp-01/02 bond0 → `enp1s0f0` / `enp1s0f1`; cp-03 bond1 → `enp5s0f0np0` / `enp5s0f1np1`.

#### Baselines (2026-05-30 — MTU 9000 + BBR)

| Test | Result |
|------|--------|
| Single stream cp-01 → TrueNAS | 9.90 Gbps, 0 retx |
| Single stream cp-03 → TrueNAS | 9.91 Gbps, 0 retx |
| TrueNAS → cp-03 reverse | 9.87 Gbps, 0 retx |
| MTU verify (MSS 8960) | ✅ Cwnd 2.36 MB |
| Bidirectional 8+8 streams (cp-03) | 13.1 + 13.9 = **27.0 Gbps** — both bond members confirmed |

**Dependencies:** storage VLAN jumbo frames ✅ (`jumbo-frames-storage-vlan`), BBR + fq ✅. Independent of all other roadmap items.

---

### Grafana

**✅ Done.** Deployed via kube-prometheus-stack (`grafana.enabled: true`). Persistence on a `ceph-block` PVC
(`strategy: Recreate`, RWO); `grafana.db` was restored from the NFS backup during the Phase 5 storage
migration. `sidecar.dashboards`/`sidecar.datasources` enabled (auto-discovers ConfigMaps labelled
`grafana_dashboard: "1"` cluster-wide); served at `https://grafana.${DOMAIN_CLUSTER}` via an
`envoy-internal` HTTPRoute; admin password from 1Password via ExternalSecret.

> Remaining polish (optional, not blocking): confirm `forceDeployDashboards` coverage and prune the
> bundled **Longhorn** dashboards (dead — Longhorn removed) to reduce dashboard clutter.

---

### Alertmanager Receiver

**✅ Done (2026-06-20, commits `878b7d1`, `0d51e10`).** A root `AlertmanagerConfig` (`alertmanagerSpec.alertmanagerConfiguration.name`) routes by `severity` label — `critical` → emergency-priority Pushover (retry/expire, persistent sound), `warning|error` → normal Pushover, default `null`. The `error` value also catches Flux's own `notification-controller` `Alert`/`Provider` forwarding. Credentials via a new `alertmanager` ExternalSecret from 1Password. Live-tested; a message-truncation bug (Pushover's 1024-rune cap, blown past by the per-alert label dump multiplying across grouped alerts) was found and fixed in the same pass.

> Residual, unverified: whether each "alerting rule to add at minimum" below already exists as a bundled rule (Rook-Ceph ships its own Ceph-mixin `PrometheusRule`s; kube-prometheus-stack ships default rule groups) or still needs to be authored — the routing now exists either way, but coverage hasn't been confirmed metric-by-metric.
> - `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod accumulation
> - `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
> - `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure
> - `ceph_health_status != 0` — Ceph not `HEALTH_OK` (warn on `1`/`HEALTH_WARN`, page on `2`/`HEALTH_ERR`)
> - `ceph_osd_up < ceph_osd_in` — a Ceph OSD is `in` the CRUSH map but `down` (degraded redundancy)

---

### Prometheus Metric Hygiene: Drop Static and Low-Value Series

Some scraped metrics carry no useful information because their value never changes — hardware sensors stuck at a constant (e.g. a floating thermistor input), counters that never increment on this cluster, or labels that exist only on hardware this cluster doesn't have. These series consume TSDB storage and cardinality budget without benefit.

**How to identify candidates:**

Run this query in Prometheus to find series whose value did not change at all over the past 24 hours:

```promql
count by (__name__, instance) (
  changes(scrape_series_added[24h]) == 0
)
```

Or target specific metric families directly:

```promql
# hwmon sensors with a constant reading over 6 hours (likely stuck/phantom)
count by (chip, sensor, instance) (
  changes(node_hwmon_temp_celsius[6h]) == 0
)
```

For cardinality analysis, the Grafana **Prometheus** data source has a built-in **Cardinality Explorer** (Explore → Metrics → `prometheus_tsdb_head_series_not_created_total` or use the cardinality management page at `/-/tsdb-status`).

**Already addressed:**
- `nct6686.*;temp5` — M920Q floating thermistor input (~128°C constant); dropped via `metricRelabelings` on the node-exporter ServiceMonitor

**Candidates to evaluate:**
- Other `nct6686` high-numbered sensors (temp6+) if they appear on cp-02 with constant readings
- `node_hwmon_*` label combinations for sensors not present in the cluster hardware (e.g. `chip=~"acpitz.*"` if those are always 0 or identical to coretemp)
- Any `node_cpu_*` per-mode breakdowns for modes that are always zero on these nodes (e.g. `steal`, `guest` on bare-metal)

**How to drop a series:**

Add a `metricRelabelings` entry to the relevant ServiceMonitor in `helm/values.yaml`:

```yaml
prometheus-node-exporter:
  prometheus:
    monitor:
      metricRelabelings:
        - sourceLabels: [chip, sensor]
          regex: "nct6686.*;temp[6789]"
          action: drop
```

**Dependencies:** Grafana ✅ (Cardinality Explorer), kube-prometheus-stack ✅

---

### Scheduling Topology: Follow-up Fixes

Two gaps identified during the 2026-05-21 cluster audit that were not fully resolved by the `topology-spread` session.

#### kustomize-controller: both replicas co-located on talos-cp-02

Both `kustomize-controller` replicas currently run on `talos-cp-02`. The Flux spread uses `ScheduleAnyway` (soft) because 4 controllers × 2 replicas = 8 pods across 3 nodes forces an uneven 3/3/2 split — hard `DoNotSchedule` would permanently block the 8th pod. With a soft constraint the scheduler may still co-locate two replicas of the same controller when it scores that placement higher.

**Impact:** If `talos-cp-02` goes down, Flux loses both `kustomize-controller` replicas simultaneously. Leader election re-runs on surviving nodes within ~35 s, but `Kustomization` reconciliation pauses until a new leader is elected.

**Options to investigate:**
- Add `podAntiAffinity` (preferred, not required) scoped to `app.kubernetes.io/name: kustomize-controller` to discourage co-location of the same controller without blocking scheduling
- Use `matchLabelKeys: [pod-template-hash]` on the spread constraint so rolling restarts don't fight the constraint
- Accept as-is: `ScheduleAnyway` was chosen intentionally; the ~35 s failover window is acceptable for a homelab

#### envoy-gateway: single-replica control plane

The `envoy-gateway` pod (the Gateway API controller) is single-replica on `talos-cp-03`. The three Envoy proxy pods (`envoy-external`, `envoy-internal`) are correctly spread 1-per-node and are unaffected. If `talos-cp-03` goes down:
- Live traffic continues — proxy pods on cp-01 and cp-02 keep serving from their last received xDS snapshot
- **No new `HTTPRoute`, `Gateway`, or TLS changes take effect** until the control plane pod reschedules (~30–60 s)

**Options:**
- Set `deployment.replicas: 2` (or equivalent) in the envoy-gateway HelmRelease values and add a `podAntiAffinity` or `topologySpreadConstraint` to spread across nodes
- Accept as-is: brief control-plane unavailability on cp-03 loss does not drop live traffic; homelab risk tolerance is high

**Dependencies:** None — both fixes are independently implementable.

---

### Kubernetes Descheduler

Investigate deploying the [Kubernetes Descheduler](https://github.com/kubernetes-sigs/descheduler) to actively evict pods that violate spread constraints — a gap the scheduler alone cannot close.

**Why this matters:**
The Kubernetes scheduler enforces topology spread constraints and anti-affinity rules only at pod *creation* time. Once a pod is running, it is never moved — even if the constraint is later violated (e.g. after a node recovers, a rolling upgrade shifts replicas, or a pod is manually rescheduled). The Descheduler runs periodically, identifies violations, and evicts the offending pods so the scheduler can rebalance them.

This cluster has at least two known scheduling imbalances that the Descheduler could self-heal:
- Both `kustomize-controller` replicas co-located on `talos-cp-02` (see Scheduling Topology follow-up above)
- ESO pods post-upgrade landing on cp-02 and cp-03 only, leaving cp-01 light

**Key strategies to evaluate:**
- `RemovePodsViolatingTopologySpreadConstraint` — evicts pods that violate `topologySpreadConstraints`; the primary target for this cluster
- `RemovePodsViolatingInterPodAntiAffinity` — evicts pods that violate anti-affinity rules after the fact
- `LowNodeUtilization` — optional; redistributes pods from underutilised nodes; evaluate whether the cp-03 bias warrants this

**Deployment notes:**
- Helm chart via `kubernetes-sigs/descheduler` OCIRepository (`ghcr.io/kubernetes-sigs/charts/descheduler`)
- Deploy in `kube-system` (standard placement for scheduling infrastructure)
- Run as a `CronJob` on a short interval (e.g. every 5 min) rather than as a continuous `Deployment` — lower blast radius, easier to reason about eviction bursts
- The `RemovePodsViolatingTopologySpreadConstraint` strategy should be scoped to namespaces with `DoNotSchedule` constraints to avoid evicting workloads with soft (`ScheduleAnyway`) constraints unexpectedly

**Dependencies:** None — independently implementable. Existing topology spread constraints are already in place; the Descheduler is purely additive.

---

### Talos Config, Image Extensions & Patch Audit

Review the current Talos configuration end-to-end to identify missing extensions, suboptimal patches, and any node-specific tuning gaps. The schematic currently ships `intel-ucode` and `amd-ucode` with several extensions commented out; patches exist for kubelet, network, sysctls, NFS defaults, and machine features — but these were written incrementally and have not been audited holistically.

Areas to investigate:

**Image extensions (`talos/schematic.yaml`)**
- `siderolabs/iscsi-tools` — required if Rook/Ceph or TrueNAS iSCSI is added (storage roadmap item)
- `siderolabs/util-linux-tools` — provides `lsblk`, `blkid`, etc.; useful for storage debugging
- `siderolabs/drbd` — needed if DRBD-backed HA storage is considered
- `siderolabs/nfs-utils` (or confirm kernel NFS client suffices for NFS mounts)
- `siderolabs/i915-ucode` / `siderolabs/amd-gpu-firmware` — relevant if any node is repurposed to run GPU workloads
- `siderolabs/stargz-snapshotter` — lazy image pulling; worth evaluating for large workloads
- Check [factory.talos.dev](https://factory.talos.dev) for any new official extensions added since cluster was built

**Global patches (`talos/patches/global/`)**
- `machine-sysctls.yaml` — verify values are tuned for 10 GbE bonds (e.g. `net.core.rmem_max`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`)
- `machine-kubelet.yaml` — check `maxPods`, `evictionHard`, `kubeReserved` / `systemReserved` are appropriate for the hardware
- `machine-network.yaml` — confirm bond MTU TODO is addressed (jumbo frames / 9000 MTU for storage VLAN)
- `machine-network.yaml` — **[low/cosmetic]** bond member alias selectors on all three nodes use `glob(driver)` (e.g. `glob("ixgbe", link.driver)`) which matches both ports on the same NIC; Talos skips the alias silently. Tighten to `hardwareAddr` or exact interface `name` so per-member aliases actually resolve if ever needed.
- `machine-files.yaml` — audit NFS mount defaults; verify `nfsvers=4.2` and `nconnect=16` are still best practice
- `machine-time.yaml` — confirm NTP servers and stratum are appropriate for home lab

**Controller-plane patches (`talos/patches/controller/`)**
- `admission-controller-patch.yaml` — review enabled admission plugins against current Kubernetes best practices
- `cluster.yaml` — re-check etcd subnet advertising, Talos API + kubelet subnet restrictions
- `machine-features.yaml` (controller) — confirm KubePrism, `hostDNS`, and any other beta features are intentional

**Per-node considerations**
- cp-03 (MS-A2, 32c/92GB) may benefit from NUMA-aware kubelet configuration
- Confirm `installDisk` is consistent with actual disk layout (nvme0n1 vs nvme1n1) post-wipe

**Talos v1.14 — native LVM wipe commands (upgrade motivation):**
Talos v1.14.0 (in alpha as of 2026-06) adds `talosctl wipe lv <name>`, `talosctl wipe vg <name>`, and `talosctl wipe pv <name>` plus `LVMPhysicalVolumeStatus` / `LVMVolumeGroupStatus` / `LVMLogicalVolumeStatus` resources. These go through the controller's own deactivation path rather than fighting the `block.LVMActivationController` lock.

**Impact on `live-osd-cleanup`:** once v1.14 is stable, the `task talos:wipe-ceph-osds-live` step in `ops/bootstrap/mod.just` can be simplified from deploying privileged wipe pods (which fight the LVMActivationController and may require a node reboot) to a direct `talosctl wipe vg <ceph-vg-name>` call. Update `ops/bootstrap/mod.just` and `.taskfiles/talos/Taskfile.yaml` at that point.

Until then, the workaround (dd to zero the LVM PV header + node reboot) is documented in [QA.md → Why does task talos:wipe-ceph-osds-live fail after a cluster reset?](QA.md#why-does-task-taloswipe-ceph-osds-live-fail-after-a-cluster-reset).

Deliverable: a PR updating `schematic.yaml` and the relevant patch files with reasoned changes; update `talenv.yaml` if the schematic ID changes (re-register at factory.talos.dev).

---

### Migrate Remaining HelmRepositories to `home-operations/charts-mirror`

> **Status: partially done (2026-07-08).** `metrics-server` migrated — mirror had a matching `3.13.1`
> tag. `cilium` is **blocked**: the mirror's newest published tag is `1.18.6`, while this cluster runs
> `1.19.5` live (confirmed via `ghcr.io/v2/.../cilium/tags/list`, no pagination trick — that's genuinely
> the full tag list). Migrating now would pin Flux's source below the running CNI version — on a
> bare-metal cluster with no separate CNI fallback, that's a real downgrade risk, not a cosmetic
> source-kind change. Re-check `charts-mirror`'s tag list next time cilium is bumped; migrate once a
> tag ≥ the then-current version exists.

Two of our Flux chart sources still use the traditional `HelmRepository` kind (HTTP `index.yaml` polling). Every other chart source in the cluster has already been converted to `OCIRepository`. Migrating the two remaining outliers makes the source strategy uniform and unlocks cosign verification.

**Background — what the mirror is:**

`ghcr.io/home-operations/charts-mirror` is a community-maintained GitHub Actions pipeline ([home-operations/charts-mirror](https://github.com/home-operations/charts-mirror)) that:
- Re-publishes upstream Helm charts as OCI artifacts under a consistent `ghcr.io` namespace
- Signs every artifact with **cosign** (same key as the rest of the `home-operations` project)
- Tags charts with the same semver as upstream — `1.21.1`, `4.4.0`, etc. — so Renovate can track them with `datasource=docker` instead of `datasource=helm`

**Why OCI > HTTP `HelmRepository`:**

| Dimension | HTTP `HelmRepository` | OCI `OCIRepository` (mirror) |
|-----------|----------------------|-------------------------------|
| Flux polling | Downloads the full `index.yaml` on every interval | Fetches only the tagged digest — no index |
| Renovate datasource | `datasource=helm` (fetches index, brittle) | `datasource=docker` (registry API, reliable) |
| Supply-chain | No verification | `verify.provider: cosign` available |
| Upstream availability | Chart unavailable if upstream repo is down | Mirror caches last-pushed artifact |
| Source kind uniformity | Breaks the all-OCI convention | All sources become `OCIRepository` |

**Current state:**

| Chart | Current source | Current kind | Mirror equivalent |
|-------|---------------|--------------|-------------------|
| `cilium` | `https://helm.cilium.io` | `HelmRepository` | `oci://ghcr.io/home-operations/charts-mirror/cilium` — **blocked, mirror lags at `1.18.6` vs our live `1.19.5`** |
| `metrics-server` | ✅ migrated 2026-07-08 | `OCIRepository` | `oci://ghcr.io/home-operations/charts-mirror/metrics-server` |

Already on the mirror (no action needed): `external-dns`, `openebs`, `metrics-server`.
Already on their own OCI registries (fine as-is): `cert-manager` (quay.io/jetstack), `kube-prometheus-stack` (ghcr.io/prometheus-community), `coredns` (ghcr.io/coredns), `spegel` (ghcr.io/spegel-org), `envoy-gateway` (mirror.gcr.io/envoyproxy).

**Steps taken for `metrics-server` (same steps apply to `cilium` once its mirror tag catches up):**

1. Replaced `kubernetes/flux/meta/repos/helm/metrics-server.yaml` with an `OCIRepository` at
   `kubernetes/flux/meta/repos/oci/metrics-server.yaml`:
   ```yaml
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: OCIRepository
   metadata:
     name: metrics-server
     namespace: flux-system
   spec:
     interval: 1h
     layerSelector:
       mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
       operation: copy
     ref:
       # renovate: datasource=docker depName=ghcr.io/home-operations/charts-mirror/metrics-server
       tag: "3.13.1"
     url: oci://ghcr.io/home-operations/charts-mirror/metrics-server
     verify:
       provider: cosign
       matchOIDCIdentity:
         - issuer: https://token.actions.githubusercontent.com
           subject: ^https://github.com/home-operations/
   ```
2. **Important — this repo's OCI-sourced HelmReleases use `spec.chartRef`, not `spec.chart.spec.sourceRef`.**
   The original plan here assumed the same `chart.spec.sourceRef.kind: OCIRepository` shape used for
   `HelmRepository` sources, but every existing OCI-sourced `HelmRelease` in this cluster (e.g.
   `tailscale-operator`, `tuppr`, `silence-operator`) uses the top-level `chartRef` field instead — and
   the version pin lives entirely on the `OCIRepository`'s `ref.tag`, not on the `HelmRelease`:
   ```yaml
   spec:
     chartRef:
       kind: OCIRepository
       name: metrics-server
       namespace: flux-system
     interval: 1h
     valuesFrom: [...]
   ```
3. Updated `kustomization.yaml` in `flux/meta/repos/helm/` to drop the old file; added the new file to
   `flux/meta/repos/oci/kustomization.yaml`.
4. Validated with `kustomize build` against both repo dirs and the app's own kustomization — all built
   cleanly before committing.

**cilium — why it's genuinely blocked, not just deferred:** confirmed live that the `cilium` Flux
`HelmRelease` (`kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`) is real and active — not a
Helmfile-bootstrap leftover — via `kubectl get helmrelease cilium -n kube-system` showing
`Ready: True, "Helm upgrade succeeded ... chart cilium@1.19.5"` against live `cilium` pods. So this
source is genuinely in use and migrating it is a live-CNI version change, not a no-op source swap.
Queried `ghcr.io/v2/home-operations/charts-mirror/cilium/tags/list` directly (with an anonymous pull
token) and confirmed the full, unpaginated tag list stops at `1.18.6` — no `1.19.x` published yet.

**Dependencies:** None — each migration is independently deployable. Low risk for `metrics-server`
(done). `cilium` specifically carries live-CNI-downgrade risk until the mirror catches up — do not
migrate by copying the version-mismatch pattern above; re-verify the mirror's tag list first.

---

### Tailscale kubectl Authentication (RBAC)

Extend the deployed Tailscale operator so that Tailscale identity doubles as a `kubectl` credential. With this in place, running `tailscale configure kubeconfig home-lab` on any tailnet device writes a kubeconfig that authenticates via Tailscale — no kubeconfig file distribution, no service account tokens to rotate.

**How it works:**
The Tailscale Kubernetes operator exposes an OIDC-compatible identity endpoint. A `ClusterRoleBinding` maps the Tailscale user identity to a Kubernetes RBAC role. `kubectl` then authenticates transparently using the active Tailscale session.

**Deployment notes:**
- Add `rbac.yaml` to `kubernetes/apps/network/tailscale-operator/app/`:
  ```yaml
  apiVersion: rbac.authorization.k8s.io/v1
  kind: ClusterRoleBinding
  metadata:
    name: tailscale-user
  roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: ClusterRole
    name: cluster-admin
  subjects:
    - apiGroup: rbac.authorization.k8s.io
      kind: User
      name: "${TAILSCALE_USER}"   # Tailscale login email or identity
  ```
- Wire `TAILSCALE_USER` via `cluster-secrets` SOPS or a dedicated ExternalSecret (the bykaj reference used `substituteFrom` on the Kustomization)
- Reference: `bykaj/home-ops` `kubernetes/apps/network/tailscale-operator/app/rbac.yaml`

**On any tailnet device after deployment:**
```sh
tailscale configure kubeconfig home-lab
kubectl get nodes   # authenticated via Tailscale identity
```

**Dependencies:** `tailscale-operator` ✅ (deployed in this session)

---

### Cilium BGP Control Plane (replace L2 Announcement)

#### Incident background — how this was found

During the rook-ceph phase-2 rollout (`rook-ceph-bgp-investigation` session), neither
`https://grafana.${DOMAIN_CLUSTER}` nor the freshly-deployed `https://ceph.${DOMAIN_CLUSTER}` dashboard
were reachable from a real browser on the LAN, despite every layer looking healthy in-cluster: Gateway
`Programmed`, `HTTPRoute` `Accepted`/`ResolvedRefs`, TLS cert `Ready`, DNS resolving to the correct VIP,
and a direct in-cluster curl to the Service returning `200`.

**Root cause (confirmed, not guessed):** both affected `LoadBalancer` Services —
`kube-system/kube-api` (`10.60.0.230`) and `network/envoy-internal` (`10.60.0.231`) — had
`externalTrafficPolicy: Local`. `Local` policy means a node will *only* forward traffic to a backend pod
running on itself, never redirect to a pod on another node (this is what lets it preserve the real client
IP without SNAT in a traditional kube-proxy setup). Cilium's `CiliumL2AnnouncementPolicy` leader election
has **no awareness of which nodes actually run a backend pod for a given service** — it elects *any*
node matching `nodeSelector` as the ARP-announcing leader. At the time of the incident:

| Service | Backend nodes | L2-announcement leader | Leader has a local backend? |
|---|---|---|---|
| `kube-api` | cp-01, cp-02, cp-03 (the 3 actual control-plane nodes) | `talos-worker-02` | **No** |
| `envoy-internal` | cp-02, worker-01, worker-02 (3 of 5 envoy replicas) | `talos-cp-03` | **No** |

Both elected leaders had zero local backend for their respective service. Traffic arriving there had
nowhere to go and was silently dropped — while ARP and ICMP to the node still looked completely normal
(pinging the VIP correctly returns "Destination Host Unreachable" *from the announcing node's real IP*,
which is itself expected/healthy behaviour for an L2-announced VIP — ICMP isn't part of what Cilium's
eBPF LB hook redirects). This is exactly why the cluster looked fully healthy from every angle except the
one that mattered.

This is a **documented, known Cilium limitation**, not a misconfiguration unique to us — see
[Cilium L2 Announcements docs](https://docs.cilium.io/en/stable/network/l2-announcements/)
("incompatible with `externalTrafficPolicy: Local`... fix: set the policy to `Cluster`") and
[cilium/cilium#27800](https://github.com/cilium/cilium/issues/27800). A cross-check against
`tmp/home-ops-bykaj` showed the **identical** `Local` + `loadBalancer.mode: dsr` + L2-announcement pattern
— it doesn't break for them only because their `CLAUDE.md` states *"3-node control plane: All nodes are
control plane"*, so for their `kube-api` service every L2-eligible node is trivially also a backend node.
Our heterogeneous topology (3 CP + 2 pure workers) is exactly what exposes the gap their topology happens
to hide.

#### ✅ Immediate fix applied (commit pending)

Changed `externalTrafficPolicy: Local` → `Cluster` on both affected resources:

- `kubernetes/apps/kube-system/cilium/config/service.yaml` (`kube-api`)
- `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` (`envoyService`, shared by `envoy-internal` +
  `envoy-external`)

This loses nothing here specifically: `loadBalancer.mode: dsr` (already set in `kube-system/cilium`'s
Helm values) preserves the real client source IP regardless of traffic policy — DSR's whole purpose is to
let the backend reply directly to the client using the VIP as source, bypassing the entry node. `Cluster`
policy only changes *which backends are eligible* (any node, not just the locally-receiving one); it
doesn't reintroduce SNAT the way it would under classic kube-proxy/iptables.

This is sufficient to fix the immediate bug. The remaining motivation below is about a **structurally
better mechanism**, not a follow-up bug fix.

#### Why go further than the `Cluster`-policy fix

L2 announcement still has two properties worth removing even with the policy bug fixed:

1. **Single point of announcement.** Exactly one node ARP-claims each VIP at a time (a Kubernetes
   `Lease`, "first come, first served"). If that node goes down, there's a re-election gap before another
   node claims the IP — and the chosen "leader" is still just whichever node won the lease race, with no
   load-spreading across multiple healthy nodes simultaneously.
2. **Confusing failure mode.** As this incident showed, when something *is* wrong, the symptoms look like
   a generic network outage (ARP/ICMP fine, TCP silently dropped) rather than pointing at the actual
   cause. A protocol that's aware of its own routing state surfaces failures more legibly.

Cilium's BGP Control Plane solves both: it's correctly endpoint-aware (a node automatically **withdraws**
its route the moment it has no local ready endpoint — no leader election, no blind spots), and multiple
nodes can advertise the same VIP **simultaneously**, with the router doing real load-balancing
(ECMP) across all of them.

#### eBGP primer — for readers new to BGP

This section exists because BGP is unfamiliar territory going in. The goal is to have enough vocabulary
to read the CRDs below and reason about what they do, not to become a BGP expert.

**What BGP actually is.** BGP (Border Gateway Protocol) is the routing protocol that holds the entire
public internet together — it's how every Autonomous System (every ISP, cloud provider, large company)
tells its neighbours "I know how to reach these IP ranges." It is a **path-vector** protocol: routers
don't share a full network map, they just tell each neighbour "send traffic for prefix X to me," and
that announcement propagates outward. Crucially for us, the same protocol scales down perfectly fine to
"one router and five Kubernetes nodes on a home LAN" — it's just a much smaller AS-to-AS relationship.

**AS numbers (ASN).** Every BGP speaker belongs to an Autonomous System, identified by a number. Public
ASNs are globally registered (e.g. Cloudflare is AS13335); for anything internal/private — which is
exactly our case — there are reserved private ranges that will never collide with anything on the real
internet: the 16-bit range `64512–65534`, or the much larger 32-bit private range
`4200000000–4294967294`. We'll use small 16-bit numbers since the UniFi BGP UI is built around that range
(real-world UDM Pro Max BGP setups commonly use `65000`/`65001`-style numbers).

**eBGP vs iBGP.** This is the one distinction that actually matters for understanding our setup:
- **iBGP** (interior): peers share the *same* ASN — typically routers inside one organization's network.
- **eBGP** (exterior): peers have *different* ASNs — typically routers belonging to different
  organizations, peering at a boundary.

In our design, the UDM Pro Max gets its own ASN (e.g. `65000`) and all five Talos nodes share a different
ASN (e.g. `65001`). Since the UDM's ASN differs from the nodes' ASN, **every node-to-UDM session is
eBGP** — even though it's all inside one home network, BGP doesn't care about physical topology, only
about the AS relationship you define. (The nodes never peer with *each other* in this design — only with
the UDM — so there's no iBGP mesh to worry about at all.)

**Peering / neighbor sessions.** Two BGP speakers establish a **session** over plain TCP on port 179.
Each side is configured with the other's IP and expected ASN ahead of time (BGP doesn't auto-discover
peers the way, say, mDNS does — you tell each side explicitly who its neighbour is). Once the TCP
connection is up, the speakers exchange `OPEN` messages to confirm the ASN/capabilities match, then start
exchanging routes. `keepalive`/`hold` timers detect a dead peer (default hold time is 90s in most
implementations; Cilium's example config above shows a much faster `holdTimeSeconds: 9` /
`keepAliveTimeSeconds: 3`, more appropriate for fast failover on a LAN).

**Route advertisement.** Once peered, a speaker can announce "I can reach prefix `10.60.0.231/32`" to its
neighbour. The neighbour adds that to its routing table with the announcing speaker as the next hop. This
is the BGP equivalent of what Cilium's L2 announcement does with ARP — except it's an explicit routing
table entry, not a "whoever answers the ARP request wins" race, and it can span more than one physical L2
segment (not relevant for our flat home LAN, but it's *why* BGP doesn't have the L2-adjacency fragility
that came up earlier in this same investigation around DSR + routed clients).

**ECMP (Equal-Cost Multi-Path).** If the UDM learns the *same* prefix (`10.60.0.231/32`) from **multiple**
neighbours at once — because multiple Talos nodes are all simultaneously advertising it — it installs
multiple equal-cost routes and load-balances traffic across all of them (typically by hashing the
flow/5-tuple, so a given TCP connection consistently takes one path). This is the mechanism that gives
true redundancy: lose any one node, the UDM simply stops seeing a route via that neighbour and shifts
traffic to the survivors — no election, no lease, no gap.

#### How Cilium implements this

There is no separate BGP daemon to run. **Each node's existing Cilium agent embeds a [GoBGP](https://github.com/osrg/gobgp)
instance** that activates once BGP Control Plane is enabled and a config matches that node. Three CRDs
(Cilium v2 API — use this for all new config, not the deprecated v2alpha1 `CiliumBGPPeeringPolicy`):

- **`CiliumBGPClusterConfig`** — the "who peers with whom" config: which nodes run a BGP instance
  (`nodeSelector`), their local ASN, and the list of peers (remote address + remote ASN) each one
  connects to.
- **`CiliumBGPPeerConfig`** — referenced by a peer entry above; holds session-level tuning (timers,
  graceful restart, authentication) and — critically — a label selector (`families[].advertisements.matchLabels`)
  that decides *which* `CiliumBGPAdvertisement` resources actually get sent over that peering relationship.
- **`CiliumBGPAdvertisement`** — the "what to advertise" config: `Service` (LoadBalancer/ClusterIP/
  ExternalIP), `PodCIDR`, or `Interface` advertisement types, each with an optional `selector` to scope
  which Services qualify (mirrors what `loadBalancerIPs: true` does unconditionally in the current
  `CiliumL2AnnouncementPolicy`).

#### Concrete plan for this cluster

**UniFi side** — `Settings → Routing → BGP` on the UDM Pro Max (requires UniFi OS ≥ 4.1.13, confirmed
present on UDM Pro Max/Pro/SE/UXG-Enterprise):

| Field | Value |
|---|---|
| Local AS | `65000` |
| Router ID | `10.60.0.1` (UDM's own LAN IP) |
| Neighbors | all 5 node IPs: `10.60.0.201`–`.205` |
| Remote AS (each neighbor) | `65001` |
| Address family | IPv4 unicast |
| Max-paths | ≥5 (enables ECMP across all nodes, not just 2) |

Also required: a LAN firewall rule permitting TCP/179 between the UDM and the management subnet — easy
to miss, and called out by the one real-world UDM+BGP writeup found during research
([archy.net](https://www.archy.net/from-keepalived-to-haproxy-clustering-a-practical-guide/)).

**Cilium side** — enable the feature (`bgpControlPlane.enabled: true` in
`kubernetes/apps/kube-system/cilium/app/helm/values.yaml`; verify the exact flag against the installed
chart version's `values.schema.json` at implementation time), then add a new config directory
`kubernetes/apps/kube-system/cilium/config/bgp.yaml`:

```yaml
---
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: bgp-cluster
spec:
  nodeSelector:
    matchLabels:
      kubernetes.io/os: linux   # all 5 nodes — full ECMP coverage, unlike the L2 policy's leader-only model
  bgpInstances:
    - name: "instance-65001"
      localASN: 65001
      peers:
        - name: "udm-pro-max"
          peerASN: 65000
          peerAddress: 10.60.0.1
          peerConfigRef:
            name: "udm-peer"
---
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: udm-peer
spec:
  timers:
    holdTimeSeconds: 9
    keepAliveTimeSeconds: 3
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: "bgp"
---
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: lb-advertisements
  labels:
    advertise: bgp
spec:
  advertisements:
    - advertisementType: "Service"
      service:
        addresses:
          - LoadBalancerIP
      selector:
        matchLabels: {}   # advertise every LoadBalancer Service, matching today's loadBalancerIPs: true behaviour
```

(Field names verified against the [Cilium BGP Control Plane Resources docs](https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-configuration/)
at the time this was written — re-check against the installed Cilium version's CRD schema before applying,
since the BGP Control Plane is a comparatively young Cilium feature and field names have shifted between
minor versions.)

**What this replaces:** once BGP is confirmed working (all 5 nodes peered, `kube-api` and
`envoy-internal`/`envoy-external` VIPs reachable via ECMP), the `CiliumL2AnnouncementPolicy` and
`CiliumLoadBalancerIPPool`'s reliance on ARP leader election become unnecessary — though the IP pool
itself (`kubernetes/apps/kube-system/cilium/config/networks.yaml`) stays, since BGP still needs Cilium to
allocate the LoadBalancer IPs, it just changes *how those IPs get announced to the network*.

#### Trade-offs — be honest about the cost

This trades "works on any dumb switch via ARP, zero router config" for "a real routing protocol session
to operate and troubleshoot." Concretely: BGP sessions can flap (rapidly go up/down) if timers are
misconfigured; route policies/communities are an extra layer of indirection if ever needed; and debugging
"why isn't this VIP reachable" now involves checking BGP session state (`cilium bgp peers`,
`cilium bgp routes`) in addition to everything already in the Cilium/Gateway toolbox. None of this is
hard, but it is new surface area for a home lab. Given this session already covered a full rook-ceph
rollout plus the L2/traffic-policy investigation, treat this as a deliberate, separate follow-up rather
than something to rush.

#### Steps to implement

1. Confirm UDM Pro Max BGP UI is available (`Settings → Routing → BGP`) and add the LAN firewall rule for
   TCP/179 between the UDM and `10.60.0.0/24`.
2. Configure the UDM side per the table above.
3. Enable `bgpControlPlane.enabled: true` in Cilium's Helm values; verify the agent pods restart cleanly.
4. Add `kubernetes/apps/kube-system/cilium/config/bgp.yaml` with the three CRDs above (re-verify schema
   against the live cluster's installed Cilium CRD version first).
5. Verify peering: `cilium bgp peers` (via `cilium-dbg` in an agent pod, or the Cilium CLI) should show
   `ESTABLISHED` for all 5 nodes.
6. Verify route advertisement: `cilium bgp routes` should list the `kube-api` and `envoy-internal`/
   `envoy-external` VIPs, advertised only from nodes with a ready local backend.
7. Test reachability + failover: confirm dashboards load, then drain/cordon the node currently handling
   traffic and confirm the UDM's ECMP table converges to the survivors without a user-visible gap.
8. Once confirmed stable, remove `kubernetes/apps/kube-system/cilium/config/networks.yaml`'s
   `CiliumL2AnnouncementPolicy` section (keep the `CiliumLoadBalancerIPPool`) and update
   `l2announcements.enabled` to `false` in Cilium's Helm values.

**Dependencies:** None blocking — independently implementable. Builds on the `externalTrafficPolicy:
Cluster` fix already applied above (BGP Control Plane handles `Local` policy correctly, but there's no
reason to revert the `Cluster` fix once BGP lands — it remains the simpler, equally-correct choice and
keeps DSR's client-IP preservation either way).

---

### CSI Snapshots (external-snapshotter + Ceph VolumeSnapshotClass)

> **Status: ✅ DONE (2026-06-20).** Deployed `piraeusdatastore/snapshot-controller` (v5.1.1) as a
> cluster-singleton in its own `snapshot-controller` namespace
> (`kubernetes/apps/system/snapshot-controller/`), installing the controller Deployment and the
> three CRDs (`VolumeSnapshot`, `VolumeSnapshotContent`, `VolumeSnapshotClass`). Rook's
> `cephBlockPoolsVolumeSnapshotClass` is enabled in
> `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml`, producing a
> VolumeSnapshotClass named **`ceph-block-snapshot`** (named explicitly rather than accepting the
> chart's own default of `ceph-block` — identical to the StorageClass name; distinct API kinds,
> no functional collision, but confusing in `kubectl get` output) backed by
> `rook-ceph.rbd.csi.ceph.com`. Not the cluster-default snapshot class — consumers (e.g. VolSync)
> reference it by name explicitly. Verified live via a full smoke test on disposable scratch
> resources (canary file → snapshot → restore into a new PVC → byte-for-byte integrity confirmed,
> then full teardown including `VolumeSnapshotContent` garbage collection).

**What "backup" buys that `ceph-block` replication does not:** `size=3`/`min_size=2` keeps three
*live, synchronously-updated* copies — it survives a **node/disk hardware failure** but a
`kubectl delete pvc`, a corrupt write, or an `rbd rm` propagates to all three replicas instantly.
Snapshots give local point-in-time rollback; VolSync (below) gives off-cluster, portable recovery.
This closes the 3-2-1 gap that replication alone leaves open.

**Unblocked VolSync's `copyMethod: Snapshot`** — see [VolSync (PVC Backup)](#volsync-pvc-backup),
now also live.

**Dependencies:** Rook-Ceph ✅.

---

### VolSync (PVC Backup)

> **Status: ✅ DONE.** VolSync backs up every stateful app's `ceph-block` PVC (except CNPG's —
> see below) to a local, NFS-direct Restic repository on TrueNAS. Canary `waha`
> (`kubernetes/apps/automation/waha/`) is fully cut over: its PVC (named **`waha`**, not
> `sessions`) was deliberately deleted and recreated by `components/volsync` from a
> verified-restorable backup, restoring real WhatsApp session data with no re-link needed.
>
> **Incident, 2026-06-22:** a first attempt wired waha straight to `existingClaim` +
> `dataSourceRef` on the wrong assumption that app-template names an unnamed PVC after the
> persistence map key (`sessions`); it actually names it after the release (`waha`). That
> commit reached production briefly before being reverted, and Helm's upgrade deleted the
> live, undeclared-by-the-new-template `waha` PVC in the process — the original ~4 days of
> WhatsApp session data was lost (recoverable only via re-linking the WhatsApp session, not a
> backup, since no backup pipeline existed yet at the time). Root cause and the corrected
> two-phase retrofit procedure are in
> [CLUSTER.md → VolSync → Canary](CLUSTER.md#volsync-pvc-backup).

**Why Restic + upstream `backube/volsync`, not Kopia + the `perfectra1n` fork:** Kopia mover and
its decoupled `KopiaMaintenance` CRD only exist in a community fork — verified directly against
upstream's CRD schema, which has zero `kopia` references anywhere. Adopting the fork would trade
the officially-maintained, cosign-eligible chart for a single-maintainer fork with no signatures
and a 4-year-stale upstream discussion (`backube/volsync#474`) about Kopia support with zero
momentum — for a feature whose only real edge (coordinated repo maintenance) Restic's own
`pruneIntervalDays` mostly covers. The NFS-direct design below was assumed fork-exclusive going
in; it isn't — upstream's Restic mover's `moverVolumes` already supports mounting a raw `nfs:`
volume directly (verified against the CRD schema), so there was no capability actually traded
away by staying on upstream.

**Why NFS-direct, not S3/B2:** backups land on `10.200.0.41:/mnt/tank/Cluster/volsync` directly
over the storage VLAN — restore time is bounded by LAN throughput, not internet upload/download,
which matters for the common case (accidental delete, bad deploy). Off-site protection against a
full NAS loss is handled **on TrueNAS itself** (e.g. a Cloud Sync Task mirroring that directory to
S3/B2) — deliberately out of Kubernetes/GitOps scope, since it's NAS-native functionality, not a
cluster concern.

**Jitter / staggering:** a `MutatingAdmissionPolicy`
(`kubernetes/apps/system/volsync/app/mutatingadmissionpolicy.yaml`, native CEL-based admission,
GA in `admissionregistration.k8s.io/v1` on this cluster) injects a random 0–30s sleep
`initContainer` into every backup Job — CEL match on the `volsync-src-` name prefix +
`app.kubernetes.io/created-by: volsync` label, verified upstream-genuine in VolSync's own shared
controller code, not fork-specific. Spreads backup start times so a growing number of apps on the
same schedule doesn't spike NFS/CPU load simultaneously. Deliberately scoped to backup (`src`)
Jobs only — restore (`dst`) Jobs are rare, one-shot events (manual trigger or bootstrap), not a
recurring thundering-herd risk, so jittering them would only delay getting data back with no
offsetting benefit.

**Bootstrap-restore pattern:** every app's PVC carries `dataSourceRef` pointing at its own
`${APP}-bootstrap` `ReplicationDestination` (manual `restore-once` trigger) — see
`kubernetes/components/volsync/pvc.yaml`. This makes restore-or-start-empty automatic on every
deploy or redeploy, with no manual step. **Bootstrap window caveat:** there's a gap between first
deploy and first completed backup where a deleted app has nothing to restore from — trigger a
manual backup immediately after deploying a new VolSync-enabled app:
```sh
kubectl patch replicationsource <app> -n <namespace> --type=merge \
  -p='{"spec":{"trigger":{"manual":"initial-'$(date +%s)'"}}}'
```

**CNPG exclusion:** `postgres-v17`'s PVC is **not** covered by VolSync — it already has dedicated
barman-cloud PITR (B2) + local `pg_dumpall` (NFS) backup paths, see
[CLUSTER.md → CloudNativePG → Backup strategy](CLUSTER.md#backup-strategy). Adding VolSync there
would be redundant, competing backup machinery for the same data, not complementary coverage.

**1Password:** one shared item, `volsync-restic`, holding a single `RESTIC_PASSWORD` field —
every app's Restic repository uses the same password; per-app isolation comes entirely from the
repository sub-path (`local:/mnt/repository/${APP}`), not from separate credentials. Losing this
password is permanent data loss for every app's backups.

**Manual TrueNAS-side prerequisite** (not GitOps): create dataset `tank/Cluster/volsync`, `chown
4000:4000`, and confirm the NFS export ACL allows `10.200.0.0/24` (the storage bond) — same as
the existing `postgres-backup-local` share. Verified live via Cilium's BPF NAT table that pod
traffic to TrueNAS masquerades through the egressing node's storage-bond IP, not its management
IP (`cilium-dbg bpf nat list` showed `10.42.x.x:port -> 10.200.0.41:2049 XLATE_SRC
10.200.0.20x:port`) — Cilium's masquerade follows the kernel's per-destination routing decision
here, not a single hardcoded device, so `10.60.0.0/24` is not needed in the export ACL.

**Files:** `kubernetes/apps/system/volsync/` (operator + jitter policy),
`kubernetes/components/volsync/` (per-app Kustomize Component: ExternalSecret + PVC +
ReplicationSource + ReplicationDestination, wired via `spec.components` +
`spec.postBuild.substitute` on the consuming app's `ks.yaml`). See
[CLUSTER.md → VolSync](CLUSTER.md#volsync-pvc-backup) for full architecture detail.

**Decided: Prometheus's `prometheus-db` PVC is explicitly excluded from VolSync scope.** Its real
PVC (`prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-
prometheus-0`, 20 Gi, `ceph-block`) is StatefulSet-generated via `volumeClaimTemplate` — confirmed
live that `dataSourceRef` is a schema-valid field there (`kubectl explain
prometheus.spec.storage.volumeClaimTemplate.spec`), so a bootstrap-restore mechanism is technically
buildable, but it would be inert on this already-running cluster (Kubernetes never retroactively
applies `volumeClaimTemplate` changes to PVCs that already exist) and only pays off on a genuine
from-scratch rebuild. Weighed against that: Prometheus's TSDB is short-term operational data, not
an archive (`retention: 14d` / `retentionSize: 18GB`, well under the 20 Gi PVC), continuously
regenerated, already protected day-to-day by 3× Ceph replication, and restoring a stale snapshot
into a live TSDB is operationally messy (block-compaction overlap). The restore complexity isn't
worth it for data this disposable — `waha` remains VolSync's only consumer, by design, not a
stepping stone to more.

**Dependencies:** CSI Snapshots ✅, external-secrets ✅, onepassword-connect ✅. (Historical —
this item is now closed.)

---

### Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository worth adopting. Each is independently implementable — ordered roughly by value vs. effort.

#### Kustomize Components (`kubernetes/components/`)

Reusable Kustomize Components (`apiVersion: kustomize.config.k8s.io/v1alpha1 / kind: Component`)
that apps include via **`spec.components` on the Flux `Kustomization` (`ks.yaml`)**, not the
plain `app/kustomization.yaml` — `postBuild.substitute` (for any `${VAR}` tokens the Component's
templates use) only exists on the Flux CRD, so declaring `components:` anywhere else leaves those
tokens unsubstituted. bykaj ships:
- `components/namespace/` — bundles namespace creation + `cluster-secrets` Secret per-app
  namespace + Flux alerts
- `components/keda/*-scaler/` — KEDA ScaledObject templates for Postgres, Redis, NFS, SMB
- `components/gpu/` — ResourceClaimTemplate for GPU workloads

**`components/volsync/` is built** — see [VolSync (PVC Backup)](#volsync-pvc-backup) above, the
first Component in this repo and the reference implementation for the `ks.yaml`-level wiring
pattern described above (see `kubernetes/apps/automation/waha/ks.yaml` for a concrete example).

**Steps to implement further Components:**
- The `namespace` Component is next highest priority: bundles namespace creation + cluster-secrets
  per-app, so apps never need separate namespace manifests or per-namespace secret wiring
- Add a Component only when the same boilerplate appears in 3+ apps — don't create early
- KEDA scalers if/when KEDA is deployed

---

#### Multi-Domain Certificate Pipeline (`certificates-export` / `certificates-import`)

A two-phase push-pull pattern that makes TLS certificates resilient across cluster rebuilds and avoids Let's Encrypt rate limits when managing multiple domains. Sourced from `bykaj/home-ops` (`kubernetes/apps/network/certificates/`).

**Why this matters for us:**
Currently we have one domain (`${CLUSTER_DOMAIN}`) and one wildcard cert issued directly by cert-manager in `envoy-gateway/config/certificate.yaml`. That is fine for one domain. As soon as a second domain is added, each rebuild risks hitting the Let's Encrypt [duplicate certificate rate limit](https://letsencrypt.org/docs/rate-limits/) (5 identical certs per 7 days). With this pattern, certs are issued once and persisted in 1Password — rebuilds restore from 1Password in seconds.

**How it works:**

```
cert-manager issues Certificate
    ↓ creates TLS Secret in cluster
PushSecret (ESO) → writes Secret into 1Password as base64-encoded item
    (certificates-export Kustomization)

    ↑ on cluster rebuild / new node
ExternalSecret (ESO) ← reads item from 1Password, recreates TLS Secret
    refreshPolicy: CreatedOnce   — ESO won't overwrite once created
    creationPolicy: Orphan       — cert-manager retains ownership; rotations flow naturally
    (certificates-import Kustomization)
```

`envoy-gateway-config` gains `dependsOn: certificates-import`, ensuring the Gateway listeners never apply before the TLS Secrets exist.

**Directory layout:**

```
kubernetes/apps/network/certificates/
├── ks.yaml                        # two-doc: certificates-import (wait: true) → certificates-export
├── export/
│   ├── kustomization.yaml
│   ├── certificates.yaml          # cert-manager Certificate CRs (one per domain)
│   └── pushsecrets.yaml           # ESO PushSecret CRs (one per domain)
└── import/
    ├── kustomization.yaml
    └── externalsecrets.yaml       # ESO ExternalSecret CRs (one per domain)
```

**Flux ordering:**

```
certificates-import (wait: true)
    ↓ produces TLS Secrets
certificates-export (dependsOn: certificates-import)
    ↓ keeps 1Password in sync
envoy-gateway-config (dependsOn: certificates-import, cert-manager)
```

**Steps to implement (when adding a second domain):**

1. Create `kubernetes/apps/network/certificates/` with the layout above
2. For each domain, add one `Certificate` + one `PushSecret` (export) and one `ExternalSecret` (import)
3. Add `certificates` to `kubernetes/apps/network/kustomization.yaml`
4. Move `wildcard-production` `Certificate` from `envoy-gateway/config/` into `certificates/export/certificates.yaml`; remove `certificate.yaml` from `envoy-gateway/config/`
5. Update `envoy-gateway/ks.yaml`: replace `dependsOn: cluster-issuers` with `dependsOn: certificates-import`
6. Update `envoy-gateway/config/gateway.yaml` listeners to reference per-domain Secret names (e.g. `vwn-io-tls`) instead of `wildcard-production-tls`
7. Seed 1Password: on first deploy, `certificates-export` runs first and writes the certs; subsequent rebuilds restore from 1Password before cert-manager even runs

**Note on `creationPolicy: Orphan`:** The ExternalSecret creates the Secret but immediately releases ownership. cert-manager then annotates and manages it normally — renewal writes a new cert into the same Secret, which ESO's `refreshPolicy: CreatedOnce` leaves untouched. `PushSecret` picks up the renewed cert and writes it back into 1Password, keeping the vault copy current.

**Dependencies:** `external-secrets` + `onepassword-connect` ✅ (already deployed), `cert-manager` ✅. Defer until a second domain is added — the single-domain wildcard approach is correct and simpler for now.

---

#### Split Renovate Configuration (`.renovate/` directory)

Instead of a single `renovate.json5`, split config into files by concern so each section
is independently reviewable in PRs. Reference pattern: `bykaj/home-ops` uses
`allowedVersions.json5`, `autoMerge.json5`, `groups.json5`, `customManagers.json5`,
`labels.json5`, `semanticCommits.json5`, etc.

**When to do this:** defer until `renovate.json5` feels unwieldy — roughly 400+ lines, or
when adding KEDA scalers, VolSync rules, or complex `allowedVersions` blocks. As of 2026-05-22
the file is ~282 lines and well-structured; the split adds overhead without much benefit yet.

**How it actually works — important:**
This is NOT a simple file-cut. Each split file must be a valid **Renovate local preset**,
not a raw JSON5 fragment. Renovate loads them via `extends`, not by auto-scanning the directory.

**Steps to implement:**
1. Create `.renovate/` directory with one file per concern, each structured as a preset:
   ```json5
   // .renovate/groups.json5
   {
     description: "Package grouping rules",
     packageRules: [ /* grouping rules only */ ],
   }
   ```
   Suggested split for this repo:
   - `.renovate/renovate.json5` — root config: `$schema`, `extends`, `schedule`, `ignorePaths`, `ignoreDeps`, manager file-pattern overrides
   - `.renovate/groups.json5` — all `groupName` rules
   - `.renovate/autoMerge.json5` — all `automerge: true` rules
   - `.renovate/semanticCommits.json5` — commit message formatting + scope rules
   - `.renovate/labels.json5` — label rules
   - `.renovate/customManagers.json5` — regex custom manager

2. Update the root config to reference each split file via `extends`:
   ```json5
   extends: [
     "config:recommended",
     // ... other presets ...
     "local:.renovate/groups.json5",
     "local:.renovate/autoMerge.json5",
     "local:.renovate/semanticCommits.json5",
     "local:.renovate/labels.json5",
     "local:.renovate/customManagers.json5",
   ],
   ```

3. Delete the original `renovate.json5` once the root config lives at `.renovate/renovate.json5`.

**No cluster-level impact** — purely a repository ergonomics improvement. Validate by
triggering a Renovate dry-run after the split (check the Dependency Dashboard issue for errors).

---

#### Grafana-Operator: Full Native Migration (Future)

**Context:** the `unpoller` deployment (2026-07-03 session) needed a cleaner way to manage
grafana.com-sourced dashboards than the `sidecar.dashboards` ConfigMap-label pattern, and evaluated
`grafana-operator` (as bykaj's repo uses it) as the fix. Two integration modes exist; **this
cluster adopted the low-risk one** — see below — and this entry documents the road not taken.

**Mode adopted (done):** `grafana-operator` in **external mode** — a `Grafana` CR with
`spec.external.url` pointing at the *existing* `kube-prometheus-stack-grafana` Service, reusing the
existing `grafana-admin-secret` for auth. The operator only pushes `GrafanaDashboard`/
`GrafanaDatasource` CRs into the already-running Grafana over its HTTP API — the Grafana
Deployment, its `ceph-block` PVC, and its `grafana.db` (restored from NFS during the Phase 5
storage migration — see [Grafana](#grafana) above) are completely untouched. See
`kubernetes/apps/observability/grafana-operator/` and `kubernetes/apps/observability/unpoller/`.

**Mode NOT adopted — bykaj's model:** bykaj runs Grafana **natively** under the operator — a
`Grafana` CR that owns its own Deployment, its own PVC (`10Gi ceph-block` in their repo), its own
`GF_SECURITY_ADMIN_USER`/`PASSWORD` secret, and the Grafana `config` (`grafana.ini`-equivalent)
inline in `spec.config`. This is strictly more capable — the operator manages Grafana's full
lifecycle, not just dashboard content pushed over an API — but adopting it here means:

1. Disabling `kube-prometheus-stack`'s bundled Grafana (`grafana.enabled: false` in
   `kube-prometheus-stack/app/helm/values.yaml`) — the *currently running* instance goes away.
2. A brand-new Grafana comes up with an empty PVC. Anything only ever created via the Grafana UI
   (as opposed to GitOps-managed ConfigMaps/CRDs) does not come back automatically — this includes
   whatever drove the original NFS `grafana.db` restore. GitOps-managed content (ceph-mixin
   dashboards, `node-exporter-full`, unpoller's `GrafanaDashboard` CRs) migrates cleanly since it's
   already declarative.
3. Re-pointing everything that currently targets `kube-prometheus-stack-grafana` — the
   `envoy-internal` HTTPRoute (`grafana.${DOMAIN_CLUSTER}`), the Grafana `ServiceMonitor`, and any
   `NetworkPolicy`/firewall rule scoped to that Service name — at the new operator-owned Service.
4. A genuine stateful cutover on a live, working service, in the same risk class as the 2026-06-22
   VolSync/waha PVC incident (session log) — a wrong assumption about what Helm does to an existing
   PVC on a values change destroyed a live volume that time. Same blast-radius category here.

**When to revisit:** if Grafana's own config/plugins/lifecycle ever need to be GitOps-managed as
CRDs rather than Helm values — e.g. wanting `spec.config` drift-detection on `grafana.ini`, or
needing more `Grafana` CRs for a second isolated instance. Nothing today requires this; external
mode already satisfies the goal that prompted the evaluation (clean, Renovate-trackable dashboard
management).

**Migration cost:** high — stateful cutover, manual dashboard/datasource reconciliation for
anything not already GitOps-managed, re-pointing 2+ existing resources at a new Service name, and a
maintenance window (Grafana briefly unavailable during the swap).

**Reference:** `bykaj/home-ops` `kubernetes/apps/observability/grafana/instance/grafana.yaml`
(native `Grafana` CR) and `kubernetes/apps/observability/grafana/operator/helmrelease.yaml`.

---

#### Dedicated `envoy-services` Gateway (Future)

A third Gateway alongside `envoy-external` and `envoy-internal`, purpose-built for LAN infrastructure proxying (Proxmox, PBS, NAS, home appliances). Currently deferred — all LAN services route through `envoy-internal` with TLS terminated at the gateway (see [CLUSTER.md → Scenario 4](CLUSTER.md#scenario-4--lan-resource-proxy-external-services)).

**When to revisit:**
- You need IP-level ACLs: a dedicated CiliumLB IP lets UniFi firewall rules restrict Proxmox/PBS to the admin VLAN without affecting `envoy-internal` cluster-app traffic
- A LAN host requires TLS passthrough (e.g. Proxmox with its own ACME cert via a `TLSRoute`): adding a `TLS: Passthrough` listener to `envoy-internal` widens its surface area; a dedicated gateway contains the change to a separate resource
- `envoy-internal` HTTPRoutes grow too large and you want independent observability/audit surfaces per gateway

**Migration cost:** low — HTTPRoutes only need `parentRefs.name` changed from `envoy-internal` to `envoy-services`. Claim one IP from the `10.60.0.230–249` Cilium pool, create the `Gateway` resource in `envoy-gateway/config/gateway.yaml`, and add an ExternalDNS annotation targeting `services.${DOMAIN_CLUSTER}`.

**Overhead:** one additional Envoy proxy Deployment (3 replicas × ~256 Mi each) and one IP from the Cilium pool.

**Reference:** `bykaj/home-ops` `kubernetes/apps/network/external-services/` uses this pattern with an `envoy-services` gateway on a dedicated IP.

---

## Completed

| Area                          | Notes                                           |
|-------------------------------|-------------------------------------------------|
| Persistent Storage (OpenEBS + Rook-Ceph) | OpenEBS LocalPV live; **Longhorn removed**, superseded by Rook-Ceph v1.19.6 (`ceph-block` default SC, `size=3`/`min_size=2`); the per-node dedicated disks (cp-01/cp-02: Kingston SNV3S1000G, cp-03: Crucial CT2000P310SSD8) are now wiped-to-raw Ceph OSDs on the `10.200.0.0/24` storage bond. Longhorn 3-replica ran 2026-05-23 → 2026-06-08 |
| Pod Topology: scheduling concentration on cp-03   | Fixed imbalance; CoreDNS + Envoy proxies spread to 3 replicas 1/node (`DoNotSchedule`); Flux/cert-manager/ESO at 2 replicas + topology spread; stateful workloads (Prometheus/Alertmanager) accepted on cp-03 |
| Talos machine configs         | 3 CP nodes, patches, schematic registered       |
| Bootstrap go-task Taskfile    | Replaces scripts/bootstrap.sh                   |
| SOPS age key + rules          | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | All bootstrap steps complete                    |
| kubernetes/ directory         | Helmfile + Flux structure in place              |
| Cilium                        | Running via Helmfile bootstrap                  |
| CoreDNS                       | Running via Helmfile bootstrap                  |
| cert-manager                  | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | Reconciling from private repo via GitHub App auth (`provider: github`, `flux-github-app` ExternalSecret) — migrated off SSH deploy key |
| Renovate                      | `renovate.json5` in place; GitHub App installed; Talos/k8s tracked via `separateMinorPatch` rules (PRs target tuppr CRDs) |
| Talos + Kubernetes upgrades   | tuppr deployed; Talos v1.13.2; Kubernetes v1.36.1; upgrades now fully automated via Renovate PRs + tuppr |
| OpenEBS OCIRepository fix     | Transient timing race (HelmRelease checked source 30s before artifact was stored); forced reconcile cleared it; added `crds: CreateReplace` to HelmRelease |
| External Secrets + 1Password Connect | ESO + 1Password Connect deployed; `ClusterSecretStore` live; `external-secrets`, `onepassword-connect`, `onepassword-store` Kustomizations all Ready |
| Cluster-Level Variable Substitution | `cluster-vars` Kustomization live; `cluster-settings` ConfigMap + `cluster-secrets` SOPS Secret in `flux-system`; `substituteFrom` patch on `cluster-apps` covers all child Kustomizations |
| Global HelmRelease Defaults Patch   | Nested patch on `cluster-apps` injects `crds: CreateReplace`, `timeout: 10m`, and upgrade remediation into all HelmReleases; `CLAUDE.md` convention note updated |
| Envoy Gateway + Cilium L2 LoadBalancer | Envoy Gateway v1.8.0; `envoy-external` (10.60.0.230) + `envoy-internal` (10.60.0.231); wildcard production cert via DNS-01; HTTP→HTTPS redirect on both Gateways |
| Cloudflare Tunnel (cloudflared)        | 2-replica HA deployment in `network` namespace; `*.vwn.io` + `vwn.io` → `envoy-external`; token via ExternalSecret from 1Password |
| Flux GitHub Webhook Receiver           | `flux-receiver` Kustomization in `flux-system`; ExternalSecret token from 1Password; HTTPRoute on `envoy-external`; GitHub webhook configured — reconcile latency ~5 min → seconds |
| ExternalDNS (Split-DNS)                | `external-dns-cloudflare` (watches `envoy-external`, `--cloudflare-proxied`, `txtOwnerId: k8s`) + `external-dns-unifi` (webhook sidecar, watches all gateways + services, `txtOwnerId: k8s-internal`); shared OCIRepository `ghcr.io/home-operations/charts-mirror/external-dns` v1.21.1; CF token mapped from `API_TOKEN` → `CF_API_TOKEN` via ESO `data[]` |
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi `ceph-block` PVCs (migrated off Longhorn in Phase 5; grafana `grafana.db` restored from NFS); node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; Pushover receiver live (see Alertmanager Receiver) |
| metrics-server                         | `kube-system`; HelmRelease `v3.13.0` (HelmRepository `https://kubernetes-sigs.github.io/metrics-server`); `kubectl top` and HPA resource metrics enabled; `--kubelet-insecure-tls` flag set; migration to `home-operations/charts-mirror` OCIRepository tracked in roadmap |
| GitHub Actions Self-Hosted Runners (ARC + Claude PR Review) | ARC `gha-runner-scale-set-controller@0.14.1` + `home-lab` scale set deployed in `actions-runner-system`; Flux HelmReleases Ready; listener pod active; Renovate PR auto-review via `claude-code-action` wired |
| ExternalSecrets `dataFrom` + `rewrite` migration | All 9 ExternalSecrets migrated to `dataFrom.extract` + `rewrite.regexp` pattern; 1Password field renames completed; all 12 cluster ExternalSecrets `SecretSynced: True` |

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8, now a Ceph OSD disk) logs `nvme nvme1: using unchecked data buffer`. This is a one-time boot message — the Crucial P310 does not advertise the NVMe "metadata-in-data-buffer" feature; the driver falls back to a simpler DMA path silently. Confirmed count of 1, no I/O errors. Watch for additional occurrences or any `I/O error` / `nvme reset` lines: `talosctl dmesg --nodes 10.60.0.201 | grep -i nvme`. Also watch for OSD faults on cp-03 specifically: `kubectl -n rook-ceph get pods -l app=rook-ceph-osd -o wide | grep cp-03` (and `ceph osd tree` in the toolbox).
