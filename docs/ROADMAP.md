# Home Lab — Cluster Roadmap <!-- omit from toc -->

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

## Contents  <!-- omit from toc -->

- [In Progress](#in-progress)
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

### CloudNativePG: Backup, PITR, and Per-App Provisioning

The `cloudnative-pg-deploy` session deployed the CNPG operator and a shared `postgres-v17` cluster (3 instances, `openebs-hostpath`). Three follow-on items were explicitly deferred:

#### 1 — Barman-cloud plugin + S3 WAL archiving (PITR)

The cluster currently has HA via streaming replication but **no point-in-time recovery**. If all 3 replicas lose their `openebs-hostpath` volumes simultaneously (node failures, accidental PVC deletion), data is gone. Adding barman-cloud provides continuous WAL archiving to S3-compatible storage and enables PITR.

**What to add** (following `tmp/home-ops-bykaj` reference):

1. **OCIRepository** `kubernetes/flux/meta/repos/oci/barman-cloud.yaml` — `oci://ghcr.io/cloudnative-pg/charts/plugin-barman-cloud`
2. **barman-cloud Kustomization** `kubernetes/apps/database/cloudnative-pg/barman-cloud/` — HelmRelease + cert-manager Certificates for plugin mTLS (the plugin communicates with the operator over a mutual-TLS gRPC channel)
3. **ObjectStore CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml` — points at Cloudflare R2 (or Backblaze B2); S3 credentials via ExternalSecret
4. **ScheduledBackup CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/scheduledbackup.yaml` — daily base backup, `method: plugin`, `backupOwnerReference: self`
5. **Cluster CR updates** — add `plugins:` (WAL archiver) and `externalClusters:` (recovery source) entries; introduce `postBuild.substitute` with `CNPG_V17_CURRENT_CLUSTER` in `ks.yaml` so recovery `serverName` can be managed without editing the manifest

**1Password fields to add** to the existing `cloudnative-pg` item:

| Field | Value |
|-------|-------|
| `S3_ACCESS_KEY` | R2 / B2 access key ID |
| `S3_SECRET_KEY` | R2 / B2 secret key |

Update `cluster/app/externalsecret.yaml` to include these in the superuser secret template (`CNPG_S3_ACCESS_KEY`, `CNPG_S3_SECRET_KEY`).

**Dependency chain update:**
```
cloudnative-pg-operator → barman-cloud → cloudnative-pg-cluster
```
The cluster ks.yaml `dependsOn` must gain `barman-cloud` once the plugin is wired in.

**Reference:** `tmp/home-ops-bykaj/kubernetes/apps/database/cloudnative-pg/barman-cloud/` and `cluster/app/objectstore.yaml`.

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

**When to implement:** after barman-cloud backup is wired in (item 1 above) — the upgrade path depends on a working WAL archive and base backup to restore from.

---

### Postgres NFS Backup: Restore Drill

The `postgres-backup-local` CronJob writes a daily `pg_dumpall` backup to TrueNAS (`/mnt/tank/Cluster/cloudnative-pg`). A backup that has never been tested for restore is not a backup. This item tracks the restore workflow and periodic drills.

**Restore procedure (full cluster restore):**

1. Locate the latest backup on TrueNAS:
   ```sh
   ls -lh /mnt/tank/Cluster/cloudnative-pg/last/
   # e.g. postgres-20260529-203903.sql.gz
   ```

2. Copy the dump to a pod with `psql` access (or use a temporary pod):
   ```sh
   kubectl run -n database restore-shell --rm -it \
     --image=docker.io/prodrigestivill/postgres-backup-local:17 \
     --overrides='{"spec":{"volumes":[{"name":"backups","nfs":{"server":"10.200.0.41","path":"/mnt/tank/Cluster/cloudnative-pg"}}],"containers":[{"name":"restore-shell","image":"docker.io/prodrigestivill/postgres-backup-local:17","command":["bash"],"volumeMounts":[{"name":"backups","mountPath":"/backups"}]}]}}' -- bash
   ```

3. Run the restore inside the pod:
   ```sh
   gunzip -c /backups/last/postgres-latest.sql.gz | \
     psql -h postgres-v17-rw.database.svc.cluster.local \
          -U postgres \
          --set ON_ERROR_STOP=on
   ```
   The dump includes `DROP`/`CREATE` statements (`-c` flag), so re-importing into an existing cluster is idempotent.

**Restore drill checklist:**
- [ ] Restore into a temporary database (`CREATE DATABASE restore_test`) rather than overwriting live data
- [ ] Confirm row counts match between source and restored DB for key tables
- [ ] Confirm `pg_restore_log` has no errors
- [ ] Document the time taken (sets expectations for RTO)
- [ ] Delete the test database when done

**When to drill:** after first successful backup, then every 3 months or after any major Postgres version upgrade.

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

> **Status: RESOLVED (2026-06-17).** Two distinct fault patterns on this M920Q unit — the
> 2026-06-01 board/VRM thermal shutdown below, and a series of recurring *silent* hard-downs
> (leading theory: non-ECC RAM bit-flip, never confirmed via MemTest86+) — both stopped recurring
> after the unit was opened, the heatsink cleaned, and thermal paste reapplied. No recurrence since.
> Full incident timeline and diagnostic detail: `docs/incidents/2026-06-10-cp02-harddown.md`.
>
> **Naming note:** this physical unit (X520 storage bond, `nct6683` board sensor) is now
> `talos-worker-02` (`10.60.0.205`) in the current 5-node topology — it was demoted from
> control-plane during the 5-node expansion, when a Minisforum MS-A2 was promoted to `cp-01` and a
> Lenovo M90q became the new `cp-02`. The `NodeVRMTemperatureHigh` / `NodeVRMTemperatureCritical`
> PrometheusRules proposed in the monitoring-enhancement section below are live in
> `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml`.
> `scripts/cp02-watch.sh` / `scripts/cp-thermal-compare.sh` still hardcode the old cp-01/cp-02
> hostnames for `.204`/`.205` — harmless (IPs unchanged) but mislabeled if ever reused as a template.

**Incident — 2026-06-01:** cp-02 shut down twice under hardware thermal protection, causing a 124-minute outage (09:29–11:33 UTC). This blocked the Cilium `cni.exclusive=false` HelmRelease upgrade (Helm timed out because the Cilium DaemonSet health check failed on the stuck pod) and delayed the Longhorn storage network rollout.

#### Root cause — findings from Prometheus

Captured at 30 s resolution from `node_hwmon_temp_celsius`:

```
09:26:55  CPU cores: 47–48°C   nct6683/temp2 (VRM/board): 53°C  — normal
09:27:25  CPU cores: 64–66°C   nct6683/temp2: 64°C               — all 6 cores +15–18°C in one scrape
09:27:55  CPU cores: 48–53°C   nct6683/temp2: 68°C               — cores recover via TCC throttle
09:28:25  CPU cores: 48–52°C   nct6683/temp2: 71°C               — board keeps heating
09:29:25  CPU cores: 47–52°C   nct6683/temp2: 72°C               — last reading; BIOS cuts power
```

**Key finding:** CPU cores recovered (throttling kicked in) but the nct6683/temp2 sensor — the NCT6683D system monitor IC's board/VRM temperature channel — continued rising even after load dropped. The BIOS thermal protection tripped on the **board/VRM temperature**, not the CPU die. ACPI trip points confirm: fan first activates at 50°C (barely above idle), active trip at 71°C, critical at 119°C — but the BIOS has an unlisted hardware VRM threshold around 72–75°C.

**The pattern** (all cores spike simultaneously + board keeps heating after core recovery) is consistent with a **degraded thermal path causing poor airflow over the VRM area** — dried thermal paste and/or a dust-clogged fan reducing airflow over both the CPU heatsink and the motherboard components behind it.

#### Required physical actions

- [x] **Open the M920Q and blow out the fan/heatsink assembly** with compressed air — done 2026-06-17
- [x] **Reapply thermal paste** — done 2026-06-17; this resolved both fault patterns (see resolution note above)
- [x] **Verify the fan spins up under load** — confirmed stable post-repaste, no recurrence since

#### Update — recurring *silent* hard-downs (distinct from the 06-01 thermal trip)

cp-02 has since gone **hard-down at least 3 more times** (2026-06-02 ×2, 2026-06-10) with a *different*
signature from the thermal incident above: **no thermal trip, 100% packet loss on BOTH NICs at once
(mgmt e1000e + storage X520), apid unreachable, nothing in `dmesg`** — and current idle temps are normal
(~28°C). cp-01 is **identical** hardware on **identical** config and has never done this, which rules out
software and points to a **cp-02 unit-specific fault**.

**Leading diagnosis: non-ECC RAM fault.** The M920Q has no ECC, and a bit-flip wedging the kernel fits the
"silent, no logs, both NICs gone" signature. **New corroborating evidence (2026-06-10):** `kube-state-metrics`
crashlooped with `exec format error` **only while scheduled on cp-02** — on an all-amd64 cluster with a
correct multi-arch image, that means the **binary bytes were corrupted** (mangled ELF), exactly what a
RAM/containerd-content-store bit-flip produces; it ran cleanly the moment it moved to cp-03.

- [ ] ~~Run MemTest86+ on cp-02~~ **MOOT** — never executed; the silent hard-downs stopped recurring
      after the 2026-06-17 heatsink/repaste fix, so the non-ECC-RAM theory was never confirmed but the
      investigation is closed (see resolution note at the top of this section).
- [x] **Off-node vitals armed** (2026-06-10, commit `bca4cee`): node-exporter scrape tightened to 10s,
      Prometheus durable on `ceph-block` (already was), board/VRM (`platform_nct6683_2592/temp2`) +
      fixed CPU-temp alerts added. This is the primary pre-crash record — see [observability commit].
      Reusable tooling: `scripts/cp02-watch.sh` (live board/CPU/up alerter — run via the Monitor tool in a
      session), `scripts/cp-thermal-compare.sh` + [`docs/cp02-thermal-measurements.md`](cp02-thermal-measurements.md)
      (cp-01-vs-cp-02 board delta — re-run at fans-100% and post-repaste).
- [x] **Thermal-path fault CONFIRMED cp-02-specific** (2026-06-10): under a Ceph benchmark at standard
      cooling cp-02's board hit 70°C vs cp-01's 62°C under identical load (Δ +8°C peak) while cp-02's CPU
      ran *cooler* and lighter — degraded VRM airflow, not extra heat. Distinct from the silent idle
      hard-downs. → physical fix below (clean + repaste); target post-fix Δ within ~1–2°C of cp-01.
- [ ] ~~netconsole over the mgmt NIC~~ **NOT VIABLE**: cp-02 boots systemd-boot + UKI
      (`bootedWithUKI: true`), and Talos ignores `machine.install.extraKernelArgs` under UKI
      (breaking change since v1.10 — siderolabs/talos#11145). Would require baking `netconsole=` into a
      cp-02-specific UKI via an Image Factory schematic + a UKI-reinstall upgrade on the flaky node, for
      low yield against a *silent* hang (no `dmesg` output ⇒ kernel too wedged to emit over UDP anyway).
      Deprioritized in favour of the off-node vitals above. Revisit only if vitals + MemTest don't crack it.
- [ ] ~~Reseat X520 + RAM; if it recurs after MemTest passes, swap the X520 card or the whole unit.~~
      **MOOT** — no recurrence since the repaste fix; no further hardware action planned.

#### Monitoring enhancement

Add a PrometheusRule for the board temperature sensor so future thermal stress is caught before shutdown:

```yaml
# in kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml
# additionalPrometheusRulesMap:
- alert: NodeVRMTemperatureHigh
  expr: node_hwmon_temp_celsius{chip="platform_nct6683_2592", sensor="temp2"} > 65
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "cp-{{ $labels.instance }} board/VRM temperature above 65°C"
- alert: NodeVRMTemperatureCritical
  expr: node_hwmon_temp_celsius{chip="platform_nct6683_2592", sensor="temp2"} > 72
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "cp-{{ $labels.instance }} board/VRM near thermal shutdown threshold"
```

> Note: `chip` label uses the nct6683 designation. Verify against live `node_hwmon_temp_celsius` labels — cp-01 confirmed `platform_nct6683_2592`. Exclude the phantom `temp5` sensor (always 127.5°C) which is already filtered via `metricRelabelings` in the node-exporter ServiceMonitor.

#### BIOS fan curve (optional)

If the thermal paste reapplication does not stabilise temperatures, the BIOS fan curve may be too conservative. The active trip at 50°C means the fan should ramp at idle — but the *speed* at that trip may be too low. Enter BIOS → Hardware Monitor → Fan Control and lower the target temp or raise the fan speed percentage at the 50°C trip point.

**Dependencies:** none — both the physical fix and the PrometheusRule addition are done (see resolution note at the top of this section).

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

Wire an Alertmanager notification receiver so cluster alerts reach a human. Alertmanager is deployed and running; it currently has no routes configured so all alerts are silently dropped.

**Alerting rules to add at minimum:**
- `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod accumulation
- `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
- `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure
- `ceph_health_status != 0` — Ceph not `HEALTH_OK` (warn on `1`/`HEALTH_WARN`, page on `2`/`HEALTH_ERR`)
- `ceph_osd_up < ceph_osd_in` — a Ceph OSD is `in` the CRUSH map but `down` (degraded redundancy)

**Deployment notes:**
- Receiver options: Discord webhook, SMTP, or Pushover (archive precedent)
- Receiver credentials via ExternalSecret from 1Password (ESO already running)
- Add `alertmanager.config` to `helm/values.yaml` with routes + receiver; keep the secret itself in 1Password

**Dependencies:** kube-prometheus-stack ✅, onepassword-connect ✅

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

**Impact on `live-osd-cleanup`:** once v1.14 is stable, the `task talos:wipe-ceph-osds-live` step in `bootstrap/mod.just` can be simplified from deploying privileged wipe pods (which fight the LVMActivationController and may require a node reboot) to a direct `talosctl wipe vg <ceph-vg-name>` call. Update `bootstrap/mod.just` and `.taskfiles/talos/Taskfile.yaml` at that point.

Until then, the workaround (dd to zero the LVM PV header + node reboot) is documented in [QA.md → Why does task talos:wipe-ceph-osds-live fail after a cluster reset?](QA.md#why-does-task-taloswipe-ceph-osds-live-fail-after-a-cluster-reset).

Deliverable: a PR updating `schematic.yaml` and the relevant patch files with reasoned changes; update `talenv.yaml` if the schematic ID changes (re-register at factory.talos.dev).

---

### Migrate Remaining HelmRepositories to `home-operations/charts-mirror`

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

**Current state — two HTTP sources remain:**

| Chart | Current source | Current kind | Mirror equivalent |
|-------|---------------|--------------|-------------------|
| `cilium` | `https://helm.cilium.io` | `HelmRepository` | `oci://ghcr.io/home-operations/charts-mirror/cilium` |
| `metrics-server` | `https://kubernetes-sigs.github.io/metrics-server` | `HelmRepository` | `oci://ghcr.io/home-operations/charts-mirror/metrics-server` |

Already on the mirror (no action needed): `external-dns`, `openebs`.  
Already on their own OCI registries (fine as-is): `cert-manager` (quay.io/jetstack), `kube-prometheus-stack` (ghcr.io/prometheus-community), `coredns` (ghcr.io/coredns), `spegel` (ghcr.io/spegel-org), `envoy-gateway` (mirror.gcr.io/envoyproxy).

**Steps to implement:**

For each of the two charts (`cilium`, `metrics-server`):

1. Delete (or replace) `kubernetes/flux/meta/repos/helm/<chart>.yaml` with an `OCIRepository`:
   ```yaml
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: OCIRepository
   metadata:
     name: cilium          # (or metrics-server)
     namespace: flux-system
   spec:
     interval: 1h
     layerSelector:
       mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
       operation: copy
     url: oci://ghcr.io/home-operations/charts-mirror/cilium
     ref:
       # renovate: datasource=docker depName=ghcr.io/home-operations/charts-mirror/cilium
       tag: "<current-version>"
     verify:
       provider: cosign
   ```
2. Update the chart's `HelmRelease` to reference the new `OCIRepository` source kind:
   ```yaml
   spec:
     chart:
       spec:
         sourceRef:
           kind: OCIRepository   # was: HelmRepository
           name: cilium
   ```
3. Update the `kustomization.yaml` in `flux/meta/repos/helm/` to remove the old file; add the new file to `flux/meta/repos/oci/`.
4. Verify Flux reconciles cleanly: `flux get helmreleases -A | grep cilium`
5. Confirm Renovate picks up the new `datasource=docker` annotation on the next Dependency Dashboard refresh.

**Important — cilium is bootstrapped via Helmfile:**  
`cilium` is deployed during `task bootstrap:cluster` via `kubernetes/bootstrap/helmfile.yaml` — not by Flux. The `HelmRepository` in `flux/meta/repos/helm/cilium.yaml` is only used if cilium is also reconciled by Flux post-bootstrap. Check whether the cilium HelmRelease in `kube-system` references this source before touching it; if the Flux HelmRelease is active, migrate it. If only the Helmfile bootstrap uses cilium, the `HelmRepository` source is effectively unused and can be removed outright.

**Dependencies:** None — each migration is independently deployable. Low risk: Flux will switch the source on next reconcile; no pod restarts required.

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

**Prerequisite for VolSync and for any point-in-time rollback.** The cluster currently has **no
snapshot capability at all** — there is no snapshot-controller and the `snapshot.storage.k8s.io`
CRDs are not installed. Rook's `cephBlockPoolsVolumeSnapshotClass` is therefore explicitly
**disabled** in `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` (enabling it
with no CRDs present would fail the Flux dry-run). Until this is fixed, *not a single CSI snapshot
can be taken*, and VolSync's `copyMethod: Snapshot` (the only viable method for live Prometheus /
Postgres volumes) cannot work.

> **Why this is a separate item from VolSync:** the snapshot-controller + CRDs are *cluster-singleton
> infrastructure* — deployed once, like a CSI driver, not per-app. Kubernetes upstream ships the
> controller + CRDs; Rook ships only the `VolumeSnapshotClass` that *consumes* them. Talos bundles
> neither. Longhorn used to pull its own VolumeSnapshotClass — that left with the Rook-Ceph migration,
> so the gap is new.

**What "backup" buys that `ceph-block` replication does not:** `size=3`/`min_size=2` keeps three
*live, synchronously-updated* copies — it survives a **node/disk hardware failure** but a
`kubectl delete pvc`, a corrupt write, or an `rbd rm` propagates to all three replicas instantly.
Snapshots give local point-in-time rollback; VolSync (below) gives off-cluster, portable recovery.
This closes the 3-2-1 gap that replication alone leaves open.

**Steps to implement:**

1. Deploy the **external-snapshotter** as a cluster-singleton. Two common paths:
   - `piraeusdatastore/snapshot-controller` (or the `kubernetes-csi/external-snapshotter`
     manifests) via a Helm chart + OCIRepository — installs the snapshot-controller Deployment
     **and** the three CRDs (`VolumeSnapshot`, `VolumeSnapshotContent`, `VolumeSnapshotClass`).
   - Place in its own namespace (e.g. `volume-snapshotter` or alongside `rook-ceph`). Most
     home-ops repos use a dedicated `kubernetes/apps/storage/snapshot-controller/`.
   - Verify against [kubesearch.dev](https://kubesearch.dev) for the prevailing community chart
     before writing the Kustomization (per CONVENTIONS — community research first).
2. Once the CRDs exist, flip `cephBlockPoolsVolumeSnapshotClass.enabled: true` in the Rook cluster
   HelmRelease (`rook-ceph/cluster/app/helmrelease.yaml:146`) and drop the explanatory `enabled:
   false` comment. This produces a `csi-rbdplugin-snapclass` VolumeSnapshotClass backed by
   `rook-ceph.rbd.csi.ceph.com`. Optionally set it as the default snapshot class.
3. Smoke-test: create a `VolumeSnapshot` of a small live PVC, confirm a `VolumeSnapshotContent`
   binds and `readyToUse: true`, then restore it into a new PVC and verify the data.

**Dependencies:** Rook-Ceph ✅. Independent of external-secrets. **Blocks:** VolSync (below).

---

### VolSync (PVC Backup)

Deploy VolSync to back up **Ceph RBD (`ceph-block`)** PVCs to an off-cluster Restic repository.
VolSync takes a CSI snapshot of a running volume and transfers it to a remote Restic backend —
producing crash-consistent, encrypted, deduplicated point-in-time backups that are restorable on
*any* Kubernetes cluster or locally via the `restic` CLI.

**Why VolSync (Restic) over a storage-native snapshot export:**
Ceph's own `rbd export` / mirror produces Ceph-native images that only restore into another Ceph
cluster. VolSync produces standard Restic repositories — portable, inspectable with `restic
snapshots`, restorable anywhere, and verifiable offline without a running cluster. It is also
storage-backend-agnostic: the same `ReplicationSource` works regardless of whether the source PVC
is on Ceph, NFS-CSI, or a future backend.

**Recommended backup target — Backblaze B2 (or Cloudflare R2):**
Restic supports any S3-compatible backend. B2 is the cost-effective choice: ~$0.006/GB/month
storage, no per-request fees above the free tier, and Cloudflare-peered so egress from cluster → B2
is free. **R2 is worth considering for consistency** — the CloudNativePG PITR item already targets
R2/B2 for WAL archiving, so sharing one provider/credential surface reduces moving parts.
Self-hosted MinIO is the alternative if no egress cost or offline access is preferred — but adds
another stateful workload to maintain.

**Dependencies:** **[CSI Snapshots](#csi-snapshots-external-snapshotter--ceph-volumesnapshotclass)** ⛔
(must land first — provides the `csi-rbdplugin-snapclass` VolumeSnapshotClass that `copyMethod:
Snapshot` requires), external-secrets ✅, onepassword-connect ✅.

---

#### Phase 1 — Deploy the VolSync operator

1. Add `kubernetes/flux/meta/repos/oci/volsync.yaml`:
   ```yaml
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: OCIRepository
   metadata:
     name: volsync
     namespace: flux-system
   spec:
     interval: 1h
     layerSelector:
       mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
       operation: copy
     url: oci://ghcr.io/backube/helm-charts/volsync
     ref:
       # renovate: datasource=docker depName=ghcr.io/backube/helm-charts/volsync
       tag: "<latest>"
   ```
   > Check `ghcr.io/home-operations/charts-mirror/volsync` first — if mirrored, prefer the mirror URL and add `verify.provider: cosign`. The upstream backube registry does not publish cosign signatures.

2. Create `kubernetes/apps/volsync/volsync/`:
   - `app/namespace.yaml` — `volsync-system` namespace
   - `app/helmrelease.yaml` — `chartRef: kind: OCIRepository, name: volsync`; no special values needed beyond metrics
   - `app/helm/values.yaml` — `metrics.enabled: true` so Prometheus auto-discovers the VolSync metrics endpoint
   - `app/kustomization.yaml`
   - `ks.yaml` — `dependsOn: [snapshot-controller]` (the `csi-rbdplugin-snapclass` VolumeSnapshotClass must exist before any `ReplicationSource` is created)

3. Add `volsync` to `kubernetes/apps/kustomization.yaml`.

---

#### Phase 2 — Seed backup credentials in 1Password

VolSync's Restic mover reads credentials from a `Secret` with these exact keys. Create a 1Password item (e.g. `volsync-b2-restic`) with the following fields:

| Secret key | Value |
|------------|-------|
| `RESTIC_REPOSITORY` | `s3:https://s3.<region>.backblazeb2.com/<bucket>/<path>` |
| `RESTIC_PASSWORD` | strong random passphrase — **loss = backups permanently unrecoverable** |
| `AWS_ACCESS_KEY_ID` | B2 application key ID |
| `AWS_SECRET_ACCESS_KEY` | B2 application key secret |

Steps:
1. In the Backblaze console: create a private bucket and a dedicated application key scoped to that bucket only.
2. Add the four fields above to the `volsync-b2-restic` 1Password item.
3. For each namespace that needs backup, create an `ExternalSecret` that pulls these fields into a `Secret` named `volsync-secret`:
   ```yaml
   apiVersion: external-secrets.io/v1
   kind: ExternalSecret
   metadata:
     name: volsync-secret
     namespace: <target-namespace>
   spec:
     refreshInterval: 1h
     secretStoreRef:
       name: onepassword
       kind: ClusterSecretStore
     target:
       name: volsync-secret
     data:
       - secretKey: RESTIC_REPOSITORY
         remoteRef: { key: volsync-b2-restic, property: RESTIC_REPOSITORY }
       - secretKey: RESTIC_PASSWORD
         remoteRef: { key: volsync-b2-restic, property: RESTIC_PASSWORD }
       - secretKey: AWS_ACCESS_KEY_ID
         remoteRef: { key: volsync-b2-restic, property: AWS_ACCESS_KEY_ID }
       - secretKey: AWS_SECRET_ACCESS_KEY
         remoteRef: { key: volsync-b2-restic, property: AWS_SECRET_ACCESS_KEY }
   ```

---

#### Phase 3 — Wire first workload

Pick a **small, stateful, annoying-to-rebuild** canary first (e.g. waha's session volume or pgadmin)
to validate the snapshot→restic→prune loop end-to-end before pointing it at Prometheus's 20 Gi
`prometheus-db` (the larger, but already-deployed, eventual target). Add a `volsync.yaml` to the
app's `app/` directory:

- `volsync.yaml` — the `ReplicationSource`:
  ```yaml
  apiVersion: volsync.backube/v1alpha1
  kind: ReplicationSource
  metadata:
    name: prometheus-db-backup
    namespace: observability
  spec:
    sourcePVC: prometheus-db
    trigger:
      schedule: "0 2 * * *"          # daily at 02:00 UTC
    restic:
      repository: volsync-secret
      copyMethod: Snapshot            # take a Ceph RBD CSI snapshot first; read from snapshot PVC
      volumeSnapshotClassName: csi-rbdplugin-snapclass
      storageClassName: ceph-block
      retain:
        daily: 7
        weekly: 4
        monthly: 12
      pruneIntervalDays: 7
  ```
- The `ExternalSecret` for `volsync-secret` in the target namespace (see Phase 2).
- Reference both files in `app/kustomization.yaml`.

**`copyMethod: Snapshot` is the key choice:** VolSync takes a Ceph RBD CSI snapshot, creates a
temporary PVC from it, and backs up from *that* — the live volume stays mounted and continues
writing without interruption. Direct copy (`copyMethod: Direct`) would require the volume to be
unmounted, which is not viable for a running Prometheus or database.

---

#### Phase 4 — `components/volsync/` Kustomize Component (deferred)

Once 3+ apps have VolSync `ReplicationSource` + `ExternalSecret` manifests, extract the boilerplate into `kubernetes/components/volsync/` following the pattern described in the [Researched Patterns](#researched-patterns-bykajhome-ops) section. Until then, add per-app manifests directly.

---

### Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository worth adopting. Each is independently implementable — ordered roughly by value vs. effort.

#### Kustomize Components (`kubernetes/components/`)

Reusable Kustomize Components (`apiVersion: kustomize.config.k8s.io/v1alpha1 / kind: Component`)
that apps include in their `app/kustomization.yaml` via `components:` references. bykaj ships:
- `components/namespace/` — bundles namespace creation + `cluster-secrets` Secret per-app
  namespace + Flux alerts
- `components/volsync/` — VolSync backup PVC + ReplicationSource/Destination templates
- `components/keda/*-scaler/` — KEDA ScaledObject templates for Postgres, Redis, NFS, SMB
- `components/gpu/` — ResourceClaimTemplate for GPU workloads

**Steps to implement:**
- Create `kubernetes/components/` as app count grows
- The `namespace` Component is highest priority: bundles namespace creation + cluster-secrets
  per-app, so apps never need separate namespace manifests or per-namespace secret wiring
- Add a Component only when the same boilerplate appears in 3+ apps — don't create early
- Natural order: `components/namespace/` first (after cluster-vars lands), then
  `components/volsync/` when backup is added, then KEDA scalers if KEDA is deployed

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
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi `ceph-block` PVCs (migrated off Longhorn in Phase 5; grafana `grafana.db` restored from NFS); node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; receiver deferred |
| metrics-server                         | `kube-system`; HelmRelease `v3.13.0` (HelmRepository `https://kubernetes-sigs.github.io/metrics-server`); `kubectl top` and HPA resource metrics enabled; `--kubelet-insecure-tls` flag set; migration to `home-operations/charts-mirror` OCIRepository tracked in roadmap |
| GitHub Actions Self-Hosted Runners (ARC + Claude PR Review) | ARC `gha-runner-scale-set-controller@0.14.1` + `home-lab` scale set deployed in `actions-runner-system`; Flux HelmReleases Ready; listener pod active; Renovate PR auto-review via `claude-code-action` wired |
| ExternalSecrets `dataFrom` + `rewrite` migration | All 9 ExternalSecrets migrated to `dataFrom.extract` + `rewrite.regexp` pattern; 1Password field renames completed; all 12 cluster ExternalSecrets `SecretSynced: True` |

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8, now a Ceph OSD disk) logs `nvme nvme1: using unchecked data buffer`. This is a one-time boot message — the Crucial P310 does not advertise the NVMe "metadata-in-data-buffer" feature; the driver falls back to a simpler DMA path silently. Confirmed count of 1, no I/O errors. Watch for additional occurrences or any `I/O error` / `nvme reset` lines: `talosctl dmesg --nodes 10.60.0.201 | grep -i nvme`. Also watch for OSD faults on cp-03 specifically: `kubectl -n rook-ceph get pods -l app=rook-ceph-osd -o wide | grep cp-03` (and `ceph osd tree` in the toolbox).
