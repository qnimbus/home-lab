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
| cp-01 | 1 TB GoodRam IRDM PRO NANO (IRP-SSDPR-P44N-01T-30) | **1 TB Kingston SNV3S1000G** (`nvme-KINGSTON_SNV3S1000G_50026B7686F8B787`) — live at `/var/mnt/longhorn-storage` |
| cp-02 | 1 TB Kingston SNV3S1000G (sole disk until Crucial arrives) | **Crucial P310 1TB 2230 + M.2 A/E adapter — on order, not yet installed** |
| cp-03 | 128 GB AirDisk (system)    | **2 TB Crucial CT2000P310SSD8** (`nvme-CT2000P310SSD8_252450B1A33B`) — live |

All nodes have dedicated 10 GbE storage bonds (`10.200.0.0/24`). Jumbo frames are a separate TODO.
**cp-01** and **cp-03**: fully live. **cp-02 blocked** — storage drive (Crucial P310 1TB 2230) on order; once installed, ISO-boot cp-02 and swap Kingston to Longhorn storage (same procedure as cp-01).

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8 Longhorn disk) logs:
> ```
> nvme nvme1: using unchecked data buffer
> ```
> **What this means:** The Crucial P310 does not advertise support for the NVMe "metadata-in-data-buffer" feature (an optional NVMe 1.2+ spec capability). The Linux `nvme` driver detects this during controller initialisation and falls back to a simpler DMA path that skips the associated buffer integrity check. This is a one-time boot message — confirmed count of 1, no I/O errors, no resets, XFS mount clean. The disk is behaving normally at idle.
>
> **Why to keep watching:** As of 2026-05-13 no Longhorn PVCs have been provisioned, so the disk has not yet been under sustained replication I/O load. Monitor once real workloads start using Longhorn storage on cp-03:
> - Check `talosctl dmesg --nodes 10.60.0.203 | grep -i nvme` — the count should stay at 1; additional occurrences or any `I/O error` / `nvme reset` / `timeout` lines are a red flag.
> - Watch for Longhorn replica faults on cp-03 specifically: `kubectl -n longhorn-system get replicas -o wide | grep cp-03`.

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
1Password (ESO + 1Password Connect are already deployed — no blocker).

#### Dependency chain

```
cert-manager ✅ → external-secrets ✅ → onepassword-connect ✅   ← ✅ all deployed; unblocks NFS/SMB credentials (Stage 4)
OpenEBS LocalPV                                ← ✅ Stage 1 — deployed, running
cp-02 disk installed → allowScheduling: true + replicaCount: 3 → Longhorn 3x ← Stage 2, Longhorn live (2-replica), cp-02 drive pending
Longhorn stable → evaluate Rook-Ceph                    ← Stage 3, optional
```

---

### metrics-server

Deploy [metrics-server](https://github.com/kubernetes-sigs/metrics-server) to serve the `metrics.k8s.io` API. This is a separate, lightweight component from kube-prometheus-stack — Prometheus stores metrics internally but does not register as a `metrics.k8s.io` provider.

**Why this matters:**
- `kubectl top nodes` / `kubectl top pods` require it — currently both return `error: Metrics API not available`
- FreeLens node CPU and Memory columns show `N/A` without it (disk metrics come from Prometheus directly)
- Horizontal Pod Autoscaler (HPA) resource-based scaling (`cpu`/`memory` metrics) requires it
- Vertical Pod Autoscaler (VPA) also depends on it

**Deployment notes:**
- OCIRepository source: `ghcr.io/kubernetes-sigs/charts/metrics-server`
- HelmRelease in `kubernetes/apps/kube-system/metrics-server/`; target namespace `kube-system` (standard placement)
- Talos does not serve a fully trusted kubelet TLS cert by default — add `--kubelet-insecure-tls` arg or configure proper cert verification via Talos machine config

**Dependencies:** none beyond a running cluster.

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

### Pod Topology: Scheduling Concentration on cp-03 ✅

The cluster had a structural imbalance: **41 pods on cp-03 vs. 18/16 on cp-01/cp-02**. This
section documents the root cause, what was implemented, and what remains accepted as-is.

#### Root cause

cp-03 (AMD 32c/92 GB) wins almost every scheduling contest against the two M920Qs (i5-8500T/64 GB).
Because no `topologySpreadConstraints` were set at deploy time, all major controllers — Flux,
ESO, cert-manager, kube-prometheus-stack — landed there. Longhorn's `WaitForFirstConsumer`
binding then pins each PVC to the node where its pod was first scheduled, making stateful
workloads permanently sticky.

#### What was implemented

Two strategies were applied depending on the workload type:

**Multi-replica services — scaled to 3 replicas, 1-per-node (`DoNotSchedule`)**

| Deployment | Before | After | Constraint |
|---|---|---|---|
| `coredns` | 2 replicas, cp-02+cp-03 | 3 replicas, 1 per node | `DoNotSchedule` |
| `envoy-external` | 2 replicas, cp-01+cp-03 | 3 replicas, 1 per node | `DoNotSchedule` + `matchLabelKeys` |
| `envoy-internal` | 2 replicas, cp-01+cp-03 | 3 replicas, 1 per node | `DoNotSchedule` + `matchLabelKeys` |

A 3rd replica on a 3-node cluster means any single node loss leaves two healthy pods across
the other two nodes. `matchLabelKeys: [pod-template-hash]` on the Envoy proxies scopes the
spread calculation to the current ReplicaSet, preventing rolling upgrades from blocking.

**Stateless controllers — scaled to 2 replicas, spread across nodes**

The key insight: topology spread alone does nothing for single-replica deployments (no other
pods to spread against). The fix is `replicas: 2` — pre-placing one pod on each of two
different nodes. When a node fails, the standby pod is already running; no scheduling delay.

| Stack | Failover mechanism | Failover time | Constraint |
|---|---|---|---|
| Flux controllers (4×) | Leader election (`leaseDuration: 35s`) | ~35 s | `ScheduleAnyway` |
| cert-manager controller + cainjector | Leader election (`leaseDuration: 60s`) | ~60 s | `DoNotSchedule` |
| cert-manager webhook | HTTP server (all replicas active) | ~0 s | `DoNotSchedule` |
| ESO controller | Concurrent mode (no leader election) | ~0 s | `DoNotSchedule` |
| ESO webhook + certController | HTTP server (all replicas active) | ~0 s | `DoNotSchedule` |

Flux uses `ScheduleAnyway` (soft) because 8 pods (4 controllers × 2 replicas) on 3 nodes
target a 3/3/2 split — hard enforcement would block the 8th pod. cert-manager and ESO use
`DoNotSchedule` (hard) because 6 pods (3 components × 2 replicas) on 3 nodes achieves a
perfect 2/2/2 split.

Flux required an additional kustomize patch to inject a shared pod label
(`app.kubernetes.io/part-of: flux`) because `commonMetadata.labels` in the flux-instance
values does not propagate to pod templates — verified live.

#### Stateful workloads (Prometheus/Alertmanager — accept current state)

Migrating existing Longhorn volumes between nodes requires VolSync or a manual backup/restore
cycle — not worth the disruption for a homelab. The practical path:

1. **Accept current placement** for existing Prometheus + Alertmanager volumes (both on cp-03).
2. **When Grafana is deployed**, configure its PVC + pod to land on cp-01 or cp-02 using
   `nodeAffinity` or a `topologySpreadConstraint` scoped to the `observability` namespace.
3. **For all future stateful deployments**, set `topologySpreadConstraints` *before* the PVCs
   are created — once `WaitForFirstConsumer` binds the volume to a node, the pod is sticky.

#### What was not changed

- `cloudflared` (stays at 2): Cloudflare tunnel redundancy is handled at the edge; 3rd replica adds no benefit.
- `onepassword-connect` (stays at 1): server with local cache state; HA requires 1Password-specific config.
- `flux-operator` (stays at 1): manages the FluxInstance CR only; HA adds no operational benefit.
- Prometheus + Alertmanager: PVC-bound to cp-03 via Longhorn `WaitForFirstConsumer`; migration deferred until VolSync is deployed.

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

## Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository that are worth adopting in this cluster. Each is independently implementable — ordered roughly by value vs. effort.

---

---

### Kustomize Components (`kubernetes/components/`)

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

### Split Renovate Configuration (`.renovate/` directory)

Instead of a single `renovate.json5`, bykaj splits Renovate config into files by concern:
`allowedVersions.json5`, `autoMerge.json5`, `groups.json5`, `changelogs.json5`,
`customManagers.json5`, `labels.json5`, `semanticCommits.json5`, etc. Each file is independently
reviewable in PRs and can be enabled/disabled without touching the root config.

**Steps to implement:**
- Rename `renovate.json5` → `.renovate/renovate.json5` (or split by concern)
- Renovate supports this natively — the `.renovate/` directory is auto-discovered
- Defer until `renovate.json5` grows unwieldy; current file is modest
- No cluster-level impact; purely a repository ergonomics improvement

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
| Talos + Kubernetes upgrades   | tuppr deployed; Talos v1.13.2; Kubernetes v1.36.1; upgrades now fully automated via Renovate PRs + tuppr |
| OpenEBS OCIRepository fix     | Transient timing race (HelmRelease checked source 30s before artifact was stored); forced reconcile cleared it; added `crds: CreateReplace` to HelmRelease |
| External Secrets + 1Password Connect | ESO + 1Password Connect deployed; `ClusterSecretStore` live; `external-secrets`, `onepassword-connect`, `onepassword-store` Kustomizations all Ready |
| Cluster-Level Variable Substitution | `cluster-vars` Kustomization live; `cluster-settings` ConfigMap + `cluster-secrets` SOPS Secret in `flux-system`; `substituteFrom` patch on `cluster-apps` covers all child Kustomizations |
| Global HelmRelease Defaults Patch   | Nested patch on `cluster-apps` injects `crds: CreateReplace`, `timeout: 10m`, and upgrade remediation into all HelmReleases; `CLAUDE.md` convention note updated |
| Envoy Gateway + Cilium L2 LoadBalancer | Envoy Gateway v1.7.3; `envoy-external` (10.60.0.230) + `envoy-internal` (10.60.0.231); wildcard production cert via DNS-01; HTTP→HTTPS redirect on both Gateways |
| Cloudflare Tunnel (cloudflared)        | 2-replica HA deployment in `network` namespace; `*.vwn.io` + `vwn.io` → `envoy-external`; token via ExternalSecret from 1Password |
| Flux GitHub Webhook Receiver           | `flux-receiver` Kustomization in `flux-system`; ExternalSecret token from 1Password; HTTPRoute on `envoy-external`; GitHub webhook configured — reconcile latency ~5 min → seconds |
| ExternalDNS (Split-DNS)                | `external-dns-cloudflare` (watches `envoy-external`, `--cloudflare-proxied`, `txtOwnerId: k8s`) + `external-dns-unifi` (webhook sidecar, watches all gateways + services, `txtOwnerId: k8s-internal`); shared OCIRepository `ghcr.io/home-operations/charts-mirror/external-dns` v1.21.1; CF token mapped from `API_TOKEN` → `CF_API_TOKEN` via ESO `data[]` |
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi Longhorn PVCs; node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; Grafana + receiver deferred |
