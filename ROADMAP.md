# Home Lab — Cluster Roadmap

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

---

## In Progress

_(nothing currently in progress)_

---

## Pending

### Persistent Storage

The cluster has no persistent storage layer. Without one, stateful workloads (databases, media
apps, monitoring stacks) cannot run reliably. This item tracks the decision and rollout.

#### Hardware snapshot

| Node  | System disk              | Dedicated storage disk                  |
|-------|--------------------------|-----------------------------------------|
| cp-01 | nvme0n1 1 TB Kingston    | **nvme1n1 1 TB** (blank, no GPT, free)  |
| cp-02 | nvme0n1 1 TB Kingston    | **nvme1n1 1 TB** (wiped, free)          |
| cp-03 | nvme0n1 2 TB Crucial     | — (none; one additional NVMe needed)    |

All nodes have dedicated 10 GbE storage bonds (`10.200.0.0/24`). Jumbo frames are a separate TODO.

#### Talos system-disk partitioning — researched, not viable

Talos creates a fixed partition layout on the install disk: `EFI / BIOS-BOOT / META / STATE /
EPHEMERAL`. The `EPHEMERAL` partition grows to consume **all remaining disk space** — there is
no free tail to reclaim. Key findings:

- `machine.disks` only targets non-system disks (e.g. cp-02's nvme1n1); cannot repartition the install disk.
- The `UserVolume` API (Talos 1.9+) targets additional disks by selector; it does not carve space from `EPHEMERAL`.
- Mounting a hostpath *within* `EPHEMERAL` (e.g. `/var/mnt/longhorn-storage`) is possible but shares IOPS and capacity with container images — risky for stateful data and not recommended.
- cp-03's 2 TB system disk has notional slack (~1.9 TB after OS use) but it is inside `EPHEMERAL`; Kubernetes workloads cannot claim it cleanly without a dedicated disk.

**Verdict**: cp-01 and cp-02 already have free nvme1n1 drives (verified live via `talosctl get discoveredvolumes`). Only cp-03 needs an additional NVMe before full 3-replica storage is achievable. `machine.disks` in `talconfig.yaml` is the correct mechanism for both existing free disks.

#### Storage options

| Option | HA? | Works today? | Notes |
|--------|-----|-------------|-------|
| **OpenEBS LocalPV** | No (node-local) | ✅ yes | Hostpath provisioner; zero hardware; good for cache/CI volumes |
| **Longhorn** | With 3 disks | Partial (cp-02, 1 replica) | Archive precedent; GUI; VolSync integration; simpler than Ceph |
| **Rook/Ceph** | ✅ full | ❌ needs 2 more drives | RWO + RWX + S3 object store; production-grade; ~2–3 GB RAM/OSD node |
| **NFS/SMB CSI** | External | If NAS exists | ReadWriteMany; offloads storage to external NAS; archive has full patterns |
| **TopoLVM** | With LVM VG | With dedicated VG | Thin provisioning; less home-lab traction |

**Rook/Ceph requires one OSD per failure domain** — with 3 nodes that means 3 dedicated disks.
Until cp-01 and cp-03 have additional drives, full Ceph replication is not achievable.

#### Recommended staged rollout

**Stage 1 — Now (no hardware required)**
Deploy **OpenEBS LocalPV** (`openebs-hostpath` storage class, base path `/var/mnt/openebs/local`).
Unlocks stateful apps immediately. Archive pattern: `oci://ghcr.io/home-operations/charts-mirror/openebs`.

**Stage 2 — Short term (cp-01 + cp-02 nvme1n1, 2 OSDs)**
Add `machine.disks` entries for both cp-01 and cp-02's nvme1n1 in `talconfig.yaml`; partition
and mount at `/var/mnt/longhorn-storage`. Deploy **Longhorn** with `defaultClassReplicaCount: 2`
(2-replica HA across two nodes). This gives real replicated block storage before cp-03 gets a disk.

**Stage 3 — Medium term (purchase 1 NVMe drive for cp-03)**
One additional NVMe (Kingston SNV3S 1 TB or equivalent M.2 NVMe) on cp-03 completes the
3-node set. Add `machine.disks` for cp-03; promote Longhorn to `defaultClassReplicaCount: 3`
for full HA, or evaluate migrating to **Rook/Ceph** if S3 object storage or RWX block
volumes are needed. Add `siderolabs/iscsi-tools` + `siderolabs/util-linux-tools` to
`talos/schematic.yaml` at this point (overlaps with the Talos Config Audit item).

**Stage 4 — If/when a NAS is added**
Deploy **NFS CSI** (`csi-driver-nfs`) and/or **SMB CSI** (`csi-driver-smb`) for ReadWriteMany
workloads (photo libraries, shared media). Wire SMB/NFS credentials via ExternalSecret from
1Password once ESO is deployed (dependency on the External Secrets item below).

#### Dependency chain

```
cert-manager → external-secrets → onepassword-connect   ← needed for NFS/SMB credentials (Stage 4)
OpenEBS LocalPV                                          ← Stage 1, no deps
machine.disks (cp-02) → Longhorn                        ← Stage 2
hardware → machine.disks (all nodes) → Longhorn 3x / Rook-Ceph ← Stage 3
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

### Talos + Kubernetes Upgrade Strategy

Research and implement a repeatable upgrade path for Talos Linux and Kubernetes. Renovate intentionally does not track these versions — a dedicated mechanism is needed.

Options to evaluate:
- **[system-upgrade-controller](https://github.com/rancher/system-upgrade-controller)** (SUC) — runs as a DaemonSet; applies Talos upgrades node-by-node via `Plan` CRDs; already referenced in `CLAUDE.md` as the intended upgrade path
- **Manual `talosctl upgrade` + `talosctl upgrade-k8s`** — imperative, full control, lower automation; suitable until SUC is deployed
- **Renovate + `allowedVersions` fence** — re-enable Talos/k8s tracking in Renovate but gate on a `allowedVersions` constraint so PRs are informational only; operator still applies the upgrade manually

Rough steps (if going SUC route):
- Deploy `system-upgrade-controller` as a HelmRelease in `system-upgrade` namespace
- Grant the controller Talos API access (ServiceAccount + RBAC in `system-upgrade` namespace — already noted in `CLAUDE.md`)
- Define `Plan` CRDs for Talos upgrades (referencing `factory.talos.dev` installer image) and Kubernetes upgrades
- Test single-node cordon/drain/upgrade cycle before rolling out to all three CPs

Dependency chain: cluster stable → `system-upgrade-controller` → Talos `Plan` → k8s `Plan`

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
| Renovate                      | `renovate.json5` in place; GitHub App installed; Talos/k8s versions intentionally excluded (managed separately) |
