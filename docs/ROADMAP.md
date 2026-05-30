# Home Lab — Cluster Roadmap <!-- omit from toc -->

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

## Contents  <!-- omit from toc -->

- [In Progress](#in-progress)
  - [CloudNativePG: Backup, PITR, and Per-App Provisioning](#cloudnative-pg-backup-pitr-and-per-app-provisioning)
  - [Postgres NFS Backup: Restore Drill](#postgres-nfs-backup-restore-drill)
  - [Longhorn Storage Network (Multus + Storage VLAN)](#longhorn-storage-network-multus--storage-vlan)
  - [Future Storage Options](#future-storage-options)
  - [Grafana](#grafana)
  - [Alertmanager Receiver](#alertmanager-receiver)
  - [Prometheus Metric Hygiene: Drop Static and Low-Value Series](#prometheus-metric-hygiene-drop-static-and-low-value-series)
  - [Scheduling Topology: Follow-up Fixes](#scheduling-topology-follow-up-fixes)
  - [Kubernetes Descheduler](#kubernetes-descheduler)
  - [Talos Config, Image Extensions \& Patch Audit](#talos-config-image-extensions--patch-audit)
  - [Migrate Remaining HelmRepositories to `home-operations/charts-mirror`](#migrate-remaining-helmrepositories-to-home-operationscharts-mirror)
  - [FluxInstance: Migrate Sync to GitHub App Authentication](#fluxinstance-migrate-sync-to-github-app-authentication)
  - [Tailscale kubectl Authentication (RBAC)](#tailscale-kubectl-authentication-rbac)
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

### Longhorn Storage Network (Multus + Storage VLAN)

**Background — why this matters:**
The incident on 2026-05-30 revealed that all Longhorn engine↔replica communication flows over the Cilium pod network (`10.42.x.x`). When cp-02 went down, Cilium's eBPF route convergence (~10 min) transiently broke the path from the Longhorn engine (running on cp-03) to cp-01's replica pod, causing a false fault with `connect: no route to host`. This created a scheduling deadlock that left the pgadmin volume on a single replica until cp-02 returned.

Moving Longhorn to the dedicated storage VLAN eliminates this class of failure entirely: storage VLAN IPs (`10.200.x.x`) are routed by the kernel's physical routing table — Cilium does not touch them, so no CNI convergence event can disrupt replica connectivity. As a bonus, all replica I/O, snapshots, and rebuilds move from the 1 GbE management link onto the 2× 10 GbE SFP+ LACP bond (`bond0` on cp-01/cp-02, `bond1` on cp-03).

---

#### Quick win — raise `replica-replenishment-wait-interval` (implement now, independently)

Increase the Longhorn setting from 600 s to 900 s. This delays the first rebuild-scheduling attempt after a node failure, giving Cilium more time to finish converging before Longhorn touches the replica graph. It does **not** prevent a false fault, but it reduces the chance of a second replica being caught mid-convergence and compounding the first.

In `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml`:

```yaml
defaultSettings:
  replicaReplenishmentWaitInterval: "900"
```

No cluster downtime required — the setting takes effect on next Longhorn manager reconcile.

---

#### Phase 1 — Verify and standardise storage bond interface names

The Multus `NetworkAttachmentDefinition` must reference the same interface name on every node. Current hardware layout uses different bond names:

| Node | Storage bond | Driver | Speed |
|------|-------------|--------|-------|
| cp-01 | `bond0` | ixgbe (X520) | 2× 10 GbE SFP+ |
| cp-02 | `bond0` | ixgbe (X520) | 2× 10 GbE SFP+ |
| cp-03 | `bond1` | i40e (X710) | 2× 10 GbE SFP+ |

A single NAD cannot reference two different interface names. Resolve this before deploying Multus — two options:

**Option A (recommended) — use the Talos VLAN sub-interface name** (if Talos already creates a consistent named link for the storage VLAN on all nodes, e.g., `storage` or `bond0.200`):
```bash
talosctl --nodes 10.60.0.201,10.60.0.202,10.60.0.203 get links \
  | grep -i "200\|storage\|bond"
```
If a consistent VLAN interface name exists across all three nodes, use that as `master` in the NAD.

**Option B — rename cp-03's storage bond in `talconfig.yaml`** to `bond0` so all three nodes match. This requires a Talos config apply + controlled reboot of cp-03. Adjust the `bond1` reference in the storage VLAN patch to `bond0`, regenerate configs, apply.

Deliverable: confirm or establish a single interface name (`<storage-iface>`) to use in the NAD.

---

#### Phase 2 — Deploy Multus CNI

Multus is a meta-CNI plugin that allows pods to attach additional network interfaces. It does not replace Cilium — it wraps it, delegating the primary interface to Cilium and attaching extras via NADs.

```
kubernetes/apps/kube-system/multus/
├── ks.yaml          # dependsOn: cilium (Multus wraps Cilium; Cilium must be healthy first)
├── app/
│   ├── kustomization.yaml
│   ├── namespace.yaml       # kube-system already exists; omit if deploying there
│   └── helmrelease.yaml
```

Source — check `ghcr.io/home-operations/charts-mirror/multus-cni` first; fall back to upstream:
```yaml
# kubernetes/flux/meta/repos/oci/multus.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: multus-cni
  namespace: flux-system
spec:
  interval: 1h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  url: oci://ghcr.io/k8snetworkplumbingwg/multus-cni-chart
  ref:
    # renovate: datasource=docker depName=ghcr.io/k8snetworkplumbingwg/multus-cni-chart
    tag: "<latest>"
```

Key HelmRelease values:
```yaml
cni:
  confDir: /etc/cni/net.d
  binDir: /opt/cni/bin    # verify against Talos CNI bin path
multus:
  defaultCniConfFile: ""  # let Cilium remain the default CNI
```

> **Talos note:** Verify that Talos exposes `/opt/cni/bin` (or the equivalent path) as writable for the Multus DaemonSet. Talos's immutable rootfs may require a specific `hostPath` mount or an extension. Check [factory.talos.dev](https://factory.talos.dev) for a `cni-plugins` extension if Multus cannot write its binary.

---

#### Phase 3 — Deploy whereabouts IPAM

Whereabouts provides cluster-wide IP address management for secondary interfaces — essential for assigning non-overlapping storage VLAN IPs to Longhorn pods across all three nodes.

Deploy alongside Multus in the same Kustomization or as a companion DaemonSet. Source: `ghcr.io/k8snetworkplumbingwg/whereabouts`.

Plan a dedicated IP range within `10.200.0.0/24` that does not conflict with existing allocations:

| Range | Used by |
|-------|---------|
| `10.200.0.201–203` | Node storage VLAN IPs (talos-cp-01/02/03) |
| `10.200.0.41` | TrueNAS NFS server |

Suggested Longhorn pod range: **`10.200.0.64/26`** (`10.200.0.64–127`) — 64 addresses, comfortably clear of nodes and NAS. For a 3-node cluster, Longhorn needs at most ~6–9 instance-manager + engine pods on the storage network.

---

#### Phase 4 — Create NetworkAttachmentDefinition

Once Phase 1 has confirmed a consistent interface name, create the NAD in `longhorn-system`:

```yaml
# kubernetes/apps/longhorn-system/longhorn/app/storage-nad.yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: longhorn-storage
  namespace: longhorn-system
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "longhorn-storage",
      "type": "macvlan",
      "master": "<storage-iface>",
      "mode": "bridge",
      "mtu": 9000,
      "ipam": {
        "type": "whereabouts",
        "range": "10.200.0.64/26",
        "exclude": []
      }
    }
```

> `mtu: 9000` matches the jumbo frames already configured on the storage VLAN bonds. If `macvlan bridge` mode does not work with the bonded interface (some drivers reject it), try `ipvlan` with `mode: l2` as an alternative.

Add `storage-nad.yaml` to `app/kustomization.yaml`.

---

#### Phase 5 — Configure Longhorn to use the storage network

1. Ensure **all volumes are healthy** (no rebuilding, degraded, or detached) before proceeding.
2. Set the `storage-network` Longhorn setting. In `helm/values.yaml`:
   ```yaml
   defaultSettings:
     storageNetwork: "longhorn-system/longhorn-storage"
   ```
3. Commit and let Flux reconcile. Longhorn will:
   - Detect the `storage-network` change
   - Perform a **rolling restart of all instance-manager pods** — each pod receives an additional network interface from Multus on the storage VLAN
   - Update replica communication to use `10.200.x.x` IPs

**Schedule this during a maintenance window.** The rolling restart means all volumes briefly lose their engine connection as each node's instance-manager restarts. Longhorn handles this gracefully (volumes reattach automatically), but there will be a short I/O pause per node.

---

#### Verification

After Phase 5 completes, confirm:

```bash
# 1. Replica pods should now report storage VLAN IPs (10.200.0.x)
kubectl -n longhorn-system get pods -l longhorn.io/component=instance-manager -o wide

# 2. Longhorn Volume status should show storageIP in 10.200.0.x range
kubectl -n longhorn-system get volumes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.currentNodeID}{"\n"}{end}'

# 3. Check a replica object's storageIP field
kubectl -n longhorn-system get replicas -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.storageIP}{"\n"}{end}'
# Expected: all non-empty and in 10.200.0.64/26

# 4. Simulate a node-down event: cordon cp-02, wait for Cilium convergence (10 min),
#    confirm no replica faults on cp-01 or cp-03 — the definitive end-to-end test
```

---

#### Risks and caveats

| Risk | Mitigation |
|------|-----------|
| Talos CNI bin path not writable by Multus DaemonSet | Check Talos docs / factory.talos.dev for CNI plugins extension before deploying |
| `macvlan bridge` rejected by ixgbe/i40e driver | Fall back to `ipvlan l2` mode in the NAD |
| Interface name inconsistency across nodes | Resolve in Phase 1 before any other phase |
| Instance-manager rolling restart causes I/O pause | Schedule in a maintenance window; no data loss risk |
| whereabouts IP range overlaps with future NAS expansion | Reserve `10.200.0.64/26` in network docs; leave `10.200.0.128–200` for infrastructure |

---

**Dependencies:** Longhorn ✅, Cilium ✅ (Multus wraps it), storage VLAN jumbo frames ✅ (`jumbo-frames-storage-vlan` session). Independent of VolSync — implement this first to harden the storage layer that VolSync will back up.

---

### Future Storage Options

Both stages are optional — Longhorn covers all current workload needs. Implement only if requirements emerge.

- **Stage 3 — Rook/Ceph**: S3-compatible object storage, `ReadWriteMany` block volumes, or more granular replication controls. The 3-disk hardware layout supports a 3-OSD Ceph cluster directly. Costs ~2–3 GB RAM per OSD node. Not required unless Longhorn's RWO-only model becomes a blocker.
- **Stage 4 — NFS/SMB CSI**: Deploy `csi-driver-nfs` and/or `csi-driver-smb` for ReadWriteMany workloads (photo libraries, shared media) when a NAS is added. Wire credentials via ExternalSecret from 1Password (ESO + 1Password Connect already deployed — no blocker).

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

Deploy Grafana as a follow-up to kube-prometheus-stack. Grafana is currently disabled in the kube-prometheus-stack HelmRelease (`grafana.enabled: false`) to keep the initial deployment scope small.

**Deployment notes:**
- Enable via `grafana.enabled: true` in `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml`, or deploy as a standalone chart with Prometheus as a data source
- Add a Longhorn PVC for dashboard persistence
- Wire the admin password via ExternalSecret from 1Password
- HTTPRoute on `envoy-internal` (LAN-only)
- Pre-built dashboards exist for Longhorn, Flux, and node-exporter in the kube-prometheus-stack chart (`forceDeployDashboards: true` once Grafana is enabled)

**Dependencies:** kube-prometheus-stack ✅

---

### Alertmanager Receiver

Wire an Alertmanager notification receiver so cluster alerts reach a human. Alertmanager is deployed and running; it currently has no routes configured so all alerts are silently dropped.

**Alerting rules to add at minimum:**
- `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod accumulation
- `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
- `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure
- `longhorn_volume_robustness == 2` — degraded Longhorn volume

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

### FluxInstance: Migrate Sync to GitHub App Authentication

The FluxInstance currently syncs via an SSH deploy key (`ssh://git@github.com/qnimbus/home-lab`). Migrating to GitHub App authentication removes a long-lived credential in favour of short-lived tokens that the Flux operator mints automatically, and enables fine-grained repository permissions without a machine account.

**Why GitHub App > SSH deploy key:**

| Dimension | SSH deploy key | GitHub App |
|---|---|---|
| Token lifetime | Long-lived; manual rotation required | Short-lived (1 h); auto-rotated by Flux operator |
| Scope granularity | Repo-level only | Per-repo, per-permission (contents: read) |
| Audit trail | Key identity only | App + installation ID in GitHub audit log |
| Revocation | Delete key from repo settings | Suspend/delete App installation |

**Deployment notes:**

1. Create a GitHub App on the account/org:
   - Permissions: `Contents: Read-only`, `Metadata: Read-only`
   - Install the App on the `home-lab` repository only
   - Note the `App ID` and `Installation ID`; generate and download a private key (`.pem`)

2. Create the sync Secret in `flux-system` (replace the current SSH key Secret):
   ```yaml
   apiVersion: v1
   kind: Secret
   metadata:
     name: flux-system      # must match sync.pullSecret in FluxInstance
     namespace: flux-system
   stringData:
     githubAppID: "<app-id>"
     githubAppInstallationID: "<installation-id>"
     githubAppPrivateKey: |
       -----BEGIN RSA PRIVATE KEY-----
       ...
       -----END RSA PRIVATE KEY-----
   ```
   Encrypt with SOPS (`sops --encrypt --in-place`) before committing — matches the existing `kubernetes/**/*.sops.yaml` rule.

3. Update `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml`:
   ```yaml
   sync:
     kind: GitRepository
     provider: github          # add this line
     url: "https://github.com/qnimbus/home-lab"   # change ssh:// → https://
     ref: refs/heads/main
     path: ./kubernetes/flux/cluster
     pullSecret: flux-system
   ```
   Note: `provider: github` requires the `url` to be HTTPS, not SSH.

4. Apply the updated FluxInstance values and verify the GitRepository transitions from `ssh` to token-based auth: `flux get sources git -n flux-system`.

5. Remove the old SSH deploy key from the GitHub repository settings once Flux is confirmed healthy on the new auth.

**Dependencies:** None — independently implementable. The existing `flux-system` Secret name (`pullSecret: flux-system`) can be reused; only its content changes.

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

### VolSync (PVC Backup)

Deploy VolSync to back up Longhorn PVCs to an off-cluster Restic repository. VolSync takes a CSI snapshot of a running volume and transfers it to a remote Restic backend — producing crash-consistent, encrypted, deduplicated point-in-time backups that are restorable on *any* Kubernetes cluster or locally via the `restic` CLI.

**Why VolSync over Longhorn's built-in backup:**
Longhorn's backup feature produces Longhorn-native volume snapshots that can only be restored into another Longhorn cluster. VolSync produces standard Restic repositories — portable, inspectable with `restic snapshots`, restorable anywhere, and verifiable offline without a running cluster.

**Recommended backup target — Backblaze B2:**
Restic supports any S3-compatible backend. B2 is the cost-effective choice: ~$0.006/GB/month storage, no per-request fees above the free tier, and Cloudflare-peered so egress from cluster → B2 is free. Self-hosted MinIO is the alternative if no egress cost or offline access is preferred — but adds another stateful workload to maintain.

**Dependencies:** Longhorn ✅ (provides `longhorn-snapshot-vsc` VolumeSnapshotClass), external-secrets ✅, onepassword-connect ✅.

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
   - `ks.yaml` — `dependsOn: [longhorn]` (the `longhorn-snapshot-vsc` VolumeSnapshotClass must exist before any `ReplicationSource` is created)

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

#### Phase 3 — Wire first workload: Prometheus PVC

Prometheus has a 20 Gi Longhorn PVC (`prometheus-db`) — the obvious first backup target since it's already deployed. Add to `kubernetes/apps/observability/kube-prometheus-stack/app/`:

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
      copyMethod: Snapshot            # take a Longhorn CSI snapshot first; read from snapshot PVC
      volumeSnapshotClassName: longhorn-snapshot-vsc
      storageClassName: longhorn
      retain:
        daily: 7
        weekly: 4
        monthly: 12
      pruneIntervalDays: 7
  ```
- The `ExternalSecret` for `volsync-secret` in the `observability` namespace (see Phase 2).
- Reference both files in `app/kustomization.yaml`.

**`copyMethod: Snapshot` is the key choice:** VolSync takes a Longhorn CSI snapshot, creates a temporary PVC from it, and backs up from *that* — the live Prometheus volume stays mounted and continues writing without interruption. Direct copy (`copyMethod: Direct`) would require the volume to be unmounted, which is not viable for a running Prometheus.

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
| Persistent Storage (OpenEBS + Longhorn 3-replica) | OpenEBS LocalPV live; Longhorn 3-replica active since 2026-05-23; all 3 nodes have dedicated storage disks (cp-01/cp-02: Kingston SNV3S1000G, cp-03: Crucial CT2000P310SSD8); cp-02 Crucial P310 installed via M.2 A/E adapter |
| Pod Topology: scheduling concentration on cp-03   | Fixed imbalance; CoreDNS + Envoy proxies spread to 3 replicas 1/node (`DoNotSchedule`); Flux/cert-manager/ESO at 2 replicas + topology spread; stateful workloads (Prometheus/Alertmanager) accepted on cp-03 |
| Talos machine configs         | 3 CP nodes, patches, schematic registered       |
| Bootstrap go-task Taskfile    | Replaces scripts/bootstrap.sh                   |
| SOPS age key + rules          | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | All bootstrap steps complete                    |
| kubernetes/ directory         | Helmfile + Flux structure in place              |
| Cilium                        | Running via Helmfile bootstrap                  |
| CoreDNS                       | Running via Helmfile bootstrap                  |
| cert-manager                  | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | Reconciling from private repo via SSH           |
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
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi Longhorn PVCs; node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; Grafana + receiver deferred |
| metrics-server                         | `kube-system`; HelmRelease `v3.13.0` (HelmRepository `https://kubernetes-sigs.github.io/metrics-server`); `kubectl top` and HPA resource metrics enabled; `--kubelet-insecure-tls` flag set; migration to `home-operations/charts-mirror` OCIRepository tracked in roadmap |
| GitHub Actions Self-Hosted Runners (ARC + Claude PR Review) | ARC `gha-runner-scale-set-controller@0.14.1` + `home-lab` scale set deployed in `actions-runner-system`; Flux HelmReleases Ready; listener pod active; Renovate PR auto-review via `claude-code-action` wired |
| ExternalSecrets `dataFrom` + `rewrite` migration | All 9 ExternalSecrets migrated to `dataFrom.extract` + `rewrite.regexp` pattern; 1Password field renames completed; all 12 cluster ExternalSecrets `SecretSynced: True` |

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8 Longhorn disk) logs `nvme nvme1: using unchecked data buffer`. This is a one-time boot message — the Crucial P310 does not advertise the NVMe "metadata-in-data-buffer" feature; the driver falls back to a simpler DMA path silently. Confirmed count of 1, no I/O errors, XFS mount clean. Watch for additional occurrences or any `I/O error` / `nvme reset` lines: `talosctl dmesg --nodes 10.60.0.203 | grep -i nvme`. Also watch for Longhorn replica faults on cp-03 specifically: `kubectl -n longhorn-system get replicas -o wide | grep cp-03`.
