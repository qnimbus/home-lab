# Home Lab — Cluster Roadmap

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

---

## In Progress

### Persistent Storage

The cluster has no persistent storage layer. Without one, stateful workloads (databases, media
apps, monitoring stacks) cannot run reliably. This item tracks the decision and rollout.

#### Hardware snapshot

| Node  | System disk              | Dedicated storage disk                  |
|-------|--------------------------|-----------------------------------------|
| cp-01 | nvme0n1 1 TB Kingston SNV3S1000G   | **nvme1n1 1 TB GoodRam IRDM PRO NANO** (IRP-SSDPR-P44N-01T-30, via M.2 A/E adapter) — by-id pinned in talconfig |
| cp-02 | nvme0n1 1 TB Kingston SNV3S1000G   | **Crucial P310 1TB 2230 + M.2 A/E adapter — on order, not yet installed** |
| cp-03 | nvme0n1 128 GB AirDisk (system)    | **nvme1n1 2 TB Crucial CT2000P310SSD8** — by-id pinned in talconfig |

All nodes have dedicated 10 GbE storage bonds (`10.200.0.0/24`). Jumbo frames are a separate TODO.
**cp-01 and cp-03 ready** — by-id disk patches in `talconfig.yaml`, Talos schematic updated with `iscsi-tools` + `util-linux-tools`. **cp-02 blocked** — storage drive (Crucial P310 1TB 2230) on order.

#### Talos system-disk partitioning — researched, not viable

Talos creates a fixed partition layout on the install disk: `EFI / BIOS-BOOT / META / STATE /
EPHEMERAL`. The `EPHEMERAL` partition grows to consume **all remaining disk space** — there is
no free tail to reclaim. Key findings:

- `machine.disks` only targets non-system disks (e.g. cp-02's nvme1n1); cannot repartition the install disk.
- The `UserVolume` API (Talos 1.9+) targets additional disks by selector; it does not carve space from `EPHEMERAL`.
- Mounting a hostpath *within* `EPHEMERAL` (e.g. `/var/mnt/longhorn-storage`) is possible but shares IOPS and capacity with container images — risky for stateful data and not recommended.
- cp-03's 2 TB system disk has notional slack (~1.9 TB after OS use) but it is inside `EPHEMERAL`; Kubernetes workloads cannot claim it cleanly without a dedicated disk.

**Verdict**: all three nodes now have free nvme1n1 drives (verified live; cp-03's 2 TB Crucial freed after migrating Talos to a 128 GB AirDisk). `machine.disks` in `talconfig.yaml` is the correct mechanism for all three storage drives. No hardware purchases needed.

#### Storage options

| Option | HA? | Works today? | Notes |
|--------|-----|-------------|-------|
| **OpenEBS LocalPV** | No (node-local) | ✅ yes | Hostpath provisioner; zero hardware; good for cache/CI volumes |
| **Longhorn** | ✅ 3-replica | ✅ yes | Archive precedent; GUI; VolSync integration; simpler than Ceph |
| **Rook/Ceph** | ✅ full | ✅ yes | RWO + RWX + S3 object store; production-grade; ~2–3 GB RAM/OSD node |
| **NFS/SMB CSI** | External | If NAS exists | ReadWriteMany; offloads storage to external NAS; archive has full patterns |
| **TopoLVM** | With LVM VG | With dedicated VG | Thin provisioning; less home-lab traction |

**All three nodes now have a free dedicated disk** — full 3-replica Longhorn or 3-OSD Ceph is achievable with no hardware purchases. cp-03's 2 TB Crucial (freed by migrating Talos to a 128 GB AirDisk) gives that node considerably more OSD capacity than cp-01/cp-02.

#### Recommended staged rollout

**Stage 1 — ✅ Done**
**OpenEBS LocalPV** deployed and running in `openebs` namespace. `openebs-hostpath` StorageClass
(non-default) live, base path `/var/mnt/openebs/local` (EPHEMERAL).

**Stage 2 — ✅ Deployed (2-replica interim); one step remaining when cp-02 drive arrives**
Talos prerequisites complete: `iscsi-tools` + `util-linux-tools` in schematic; per-node
`machine.disks` patches applied for cp-01 (GoodRam IRDM PRO NANO, serial `G4E004578`) and
cp-03 (Crucial CT2000P310SSD8, serial `252450B1A33B`); cp-02 upgraded to new schematic but
no disk patch yet (Crucial P310 1TB 2230 on order).

**Longhorn** deployed and running in `longhorn-system` namespace. Currently configured with
`defaultClassReplicaCount: 2` (provisional — only cp-01 and cp-03 have storage disks).
talos-cp-02 node-config has `allowScheduling: false`. When cp-02's drive arrives:
- `talosctl get disks --nodes 10.60.0.202` → grab serial; add `machine.disks` inline patch for cp-02; `task talos:apply IP=10.60.0.202`
- Set `allowScheduling: true` in `node-configs/talos-cp-02.yaml`
- Bump `defaultClassReplicaCount` and `defaultReplicaCount` to `3` in `helm/values.yaml`

**Stage 3 — Evaluate Rook/Ceph if object storage or RWX block is needed**
Once Longhorn is stable, consider migrating to **Rook/Ceph** for S3-compatible object storage,
`ReadWriteMany` block volumes, or more granular replication controls. The 3-disk hardware layout
supports it directly. Not required if Longhorn meets all workload needs.

**Stage 4 — If/when a NAS is added**
Deploy **NFS CSI** (`csi-driver-nfs`) and/or **SMB CSI** (`csi-driver-smb`) for ReadWriteMany
workloads (photo libraries, shared media). Wire SMB/NFS credentials via ExternalSecret from
1Password once ESO is deployed (dependency on the External Secrets item below).

#### Dependency chain

```
cert-manager → external-secrets → onepassword-connect   ← needed for NFS/SMB credentials (Stage 4)
OpenEBS LocalPV                                ← ✅ Stage 1 — deployed, running
cp-02 disk installed → allowScheduling: true + replicaCount: 3 → Longhorn 3x ← Stage 2, Longhorn live (2-replica), cp-02 drive pending
Longhorn stable → evaluate Rook-Ceph                    ← Stage 3, optional
```

---

### External Secrets + 1Password Connect

Deploy [External Secrets Operator](https://external-secrets.io/) and a [1Password Connect](https://developer.1password.com/docs/connect/) server so that application secrets can be pulled from 1Password at runtime without ever touching Git.

Rough steps:
- Deploy 1Password Connect server (HelmRelease in `kubernetes/apps/`)
- Deploy External Secrets Operator (HelmRelease, likely `external-secrets` namespace)
- Create a `ClusterSecretStore` pointing to the Connect server
- Validate with a test `ExternalSecret` before wiring up real app secrets

Dependency chain: `cert-manager` → `external-secrets` → `onepassword-connect` → apps

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

## Completed

| Area                          | Notes                                           |
|-------------------------------|-------------------------------------------------|
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
| Talos + Kubernetes upgrades   | tuppr deployed; Talos manually upgraded v1.10.6→v1.13.0 (3 incremental hops); `TalosUpgrade` CRD updated to v1.13.0; Kubernetes still at v1.33.4 — pending upgrade |
