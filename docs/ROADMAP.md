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

### Monitoring — kube-prometheus-stack

Deploy [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) to provide cluster-wide observability: Prometheus (metrics), Alertmanager (routing), Grafana (dashboards), and kube-state-metrics (Kubernetes object metrics).

**Why this matters for this cluster:**
- Stale `Failed` pods accumulate silently — the `PodGCController` only triggers at 12,500 terminated pods, so manual sweeps (`task purge-failed-pods`) are currently the only detection mechanism
- Longhorn, Flux, and tuppr all expose Prometheus metrics; without a scraper they go unobserved
- Alertmanager can route to Discord/Slack/email so cluster health issues surface without requiring active dashboard monitoring

**Alerting rules to add at minimum:**
- `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod detection (the gap identified during the PSA incident)
- `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
- `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure on storage nodes
- `longhorn_volume_robustness == 2` — degraded volume (Longhorn metric, requires `serviceMonitor`)

**Rough deployment steps:**
- Add `prometheus-community` HelmRepository to `kubernetes/flux/meta/repos/helm/`
- HelmRelease in `kubernetes/apps/monitoring/kube-prometheus-stack/`
- Longhorn `ServiceMonitor` already supported — enable via `monitoring.enabled: true` in Longhorn values
- Alertmanager receiver config (Discord webhook or SMTP) via ExternalSecret from 1Password

**Dependencies:**
- `cert-manager` — ✅ already running (needed for webhook TLS)
- `external-secrets` + `onepassword-connect` — needed for alertmanager receiver credentials (can deploy stack first with a placeholder receiver and wire credentials later)
- Longhorn — ✅ already running (enables `ServiceMonitor` integration immediately)

**Resource note:** kube-prometheus-stack is the most resource-intensive item on this roadmap. Prometheus default retention is 10 days in-memory + on-disk. Use a Longhorn PVC for Prometheus storage (`longhorn-retain` StorageClass) and size the retention window conservatively for a 3-node cluster.

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

### Ingress Infrastructure: Cilium Gateway API + L2 LoadBalancer

**Dependency**: cert-manager ✅ already running

Prerequisite for Cloudflare Tunnel and all future HTTP(S) ingress (dashboards, webhook receiver,
apps). Cilium already has `l2announcements.enabled: true` (L2 ARP mode); enabling Gateway API
on top gives a standard `GatewayClass` / `Gateway` / `HTTPRoute` abstraction without installing
MetalLB or a separate ingress controller.

**Steps:**
- Add `gatewayAPI.enabled: true` and `gatewayAPI.hostNetwork.enabled: true` to Cilium Helm values
- Create `CiliumLoadBalancerIPPool` — allocate a small range from the management subnet (e.g. `10.60.0.200/29`); avoid the VIP `10.60.0.2` and node IPs `.201–.203`
- Create `CiliumL2AnnouncementPolicy` — announce the pool on the management interface so ARP resolves correctly
- Cilium auto-installs the `cilium` `GatewayClass` when Gateway API is enabled
- Create an external `Gateway` resource pinned to a static IP from the pool (e.g. `10.60.0.200`)
- Create a cert-manager `ClusterIssuer` — Let's Encrypt DNS-01 via Cloudflare API token (requires domain in Cloudflare)

Resources live in `kubernetes/apps/kube-system/cilium/` (Cilium values + CRDs) and a new
`kubernetes/apps/cert-manager/cluster-issuers/` app.

---

### Cloudflare Tunnel (cloudflared)

**Dependency**: Cilium Gateway API item above

The cluster is behind home NAT; Cloudflare Tunnel provides an outbound-only encrypted connection
to Cloudflare's edge with no port forwarding or static external IP required. All external traffic
(`*.yourdomain.com`) routes through the tunnel to the cluster Gateway.

**Steps:**
- Create a tunnel: `cloudflared tunnel create home-lab` (or via Cloudflare dashboard) — outputs a credentials JSON
- Encrypt the credentials JSON as `secret.sops.yaml` and commit to `kubernetes/apps/network/cloudflared/`
- Deploy `cloudflared` as a Deployment (2 replicas for HA) in a new `network` namespace
- Configure tunnel ingress rules: `*.yourdomain.com` → `http://10.60.0.200` (Gateway cluster IP)
- DNS: add a CNAME `*.yourdomain.com` → `<tunnel-id>.cfargotunnel.com` in Cloudflare (or manage via ExternalDNS later)

---

### Flux GitHub Webhook Receiver

**Dependency**: Cloudflare Tunnel item above (needs externally reachable HTTPS endpoint)

Without a webhook, Flux discovers new commits only on its 5-minute poll interval. A GitHub webhook
cuts reconcile latency from ~5 minutes to seconds.

**Implementation** (design fully researched — see `.claude/plans/` for details):
- New app folder `kubernetes/apps/flux-system/flux-receiver/` with:
  - `ks.yaml` — Flux Kustomization (targets `flux-system` namespace, depends on `cluster-meta`)
  - `app/receiver.yaml` — `Receiver` resource, type `github`, events `[ping, push]`, targets `GitRepository/flux-system` and `Kustomization/flux-system`
  - `app/secret.sops.yaml` — SOPS-encrypted Secret, key `token` (random hex; used as GitHub webhook secret for HMAC verification)
  - `app/httproute.yaml` — HTTPRoute routing `flux-webhook.yourdomain.com/hook/*` → `webhook-receiver:80` in `flux-system`
- Add `./flux-system` to `kubernetes/apps/kustomization.yaml`
- Configure GitHub repo webhook: URL = `https://flux-webhook.yourdomain.com/hook/<generated-path>`, content-type `application/json`, secret = token value
- After deploy: retrieve generated path via `kubectl get receiver -n flux-system github-webhook -o jsonpath='{.status.webhookPath}'`

**Prerequisites to verify at implement-time:**
- `sops-age` secret exists in `flux-system` namespace (create from `age.key` if not)
- `cluster-settings` ConfigMap exists (needed for postBuild variable substitution in child Kustomizations)

---

## Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository that are worth adopting in this cluster. Each is independently implementable — ordered roughly by value vs. effort.

---

### Cluster-Level Variable Substitution (`postBuild.substituteFrom`)

A `cluster-settings` ConfigMap (non-sensitive values: timezone, CIDRs) and a `cluster-secrets`
SOPS-encrypted Secret (domain names, host addresses) deployed in `flux-system`. A patch on the
root `cluster-apps` Kustomization injects `postBuild.substituteFrom` referencing both into every
child Kustomization automatically. Apps then use `${VAR_NAME}` tokens in HelmRelease values,
Ingress hostnames, env vars, etc. without any per-app wiring.

**Status of wiring in this repo:**
`kubernetes/flux/cluster/ks.yaml` already has the `substituteFrom` patch; the ConfigMap and
Secret do not exist yet.

**Steps to implement:**
- Create `kubernetes/flux/vars/` with `cluster-settings.yaml` (ConfigMap) and
  `cluster-secrets.sops.yaml` (Secret, SOPS-encrypted)
- Add a `cluster-vars` Flux Kustomization pointing to that path, with `targetNamespace: flux-system`
  and SOPS decryption enabled, deployed before `cluster-apps` (`dependsOn`)
- Add `optional: true` to both `substituteFrom` sources in the existing patch (safety valve
  during initial bootstrap before `sops-age` secret exists)
- Add `task bootstrap:sops-age` — creates the `sops-age` Secret in `flux-system` from the
  local `age.key` file (one-off bootstrap step; same pattern as `bootstrap:onepassword-connect-secret`)
- Uncomment the SOPS decryption block on `cluster-apps` itself

**Chicken-and-egg note:** Using ESO/1Password to source `cluster-secrets` would be circular —
ESO must be deployed before the Secret can exist, but Flux needs the Secret to deploy apps
(including ESO). SOPS avoids this entirely: `cluster-vars` decrypts before any apps reconcile.

---

### Global HelmRelease Defaults Patch

An additional patch in `cluster-apps` that targets **all** `HelmRelease` resources cluster-wide
and injects `crds: CreateReplace`, a default `timeout`, and upgrade remediation settings
(`cleanupOnFail: true`, `retries: 2`, `remediateLastFailure: true`). Apps no longer declare these
individually.

**Steps to implement:**
- Add to the `patches:` list in `cluster-apps` in `kubernetes/flux/cluster/ks.yaml`:
  ```yaml
  - patch: |-
      apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      metadata:
        name: not-used
      spec:
        install:
          crds: CreateReplace
        timeout: 10m
        upgrade:
          cleanupOnFail: true
          crds: CreateReplace
          remediation:
            remediateLastFailure: true
            retries: 2
    target:
      group: helm.toolkit.fluxcd.io
      kind: HelmRelease
  ```
- Per-release `crds: CreateReplace` blocks become redundant (harmless to leave — they merge
  idempotently)
- Update the `crds: CreateReplace` convention note in `CLAUDE.md` to clarify it is now a
  cluster-wide default, not a per-chart requirement

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
