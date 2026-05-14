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
- `external-secrets` + `onepassword-connect` — ✅ already running; alertmanager receiver credentials can be wired immediately via ExternalSecret
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

### ExternalDNS (Split-DNS: Cloudflare + Internal)

**Dependency**: Cilium Gateway API item above (provides `gateway-httproute` source CRDs)

ExternalDNS watches Kubernetes Gateway HTTPRoutes, Services, and `DNSEndpoint` CRDs and automatically creates/deletes DNS records in the configured provider. Split-DNS runs two instances: **Cloudflare** for public records and an **internal provider** for LAN / `home.arpa` resolution.

**Why this matters:**
- Today, Cloudflare DNS records are managed manually — every new service requires a manual CNAME/A entry
- Once Cloudflare Tunnel is deployed, ExternalDNS auto-creates `*.${DOMAIN} → <tunnel-id>.cfargotunnel.com` CNAMEs from HTTPRoute annotations
- Internal instance allows LAN clients to resolve cluster services without hairpinning through Cloudflare

**Architecture: two HelmReleases in `network` namespace**

| Instance | Provider | Sources | Manages |
|----------|----------|---------|---------|
| `external-dns-cloudflare` | Cloudflare API | `gateway-httproute`, `crd` (DNSEndpoint) | Public domain records |
| `external-dns-unifi` | UniFi UDM Pro Max (webhook) | `gateway-httproute`, `service` | LAN / internal records |

**Internal DNS provider: UniFi UDM Pro Max**

Uses `ghcr.io/kashalls/external-dns-unifi-webhook` as a sidecar container in the same Pod. ExternalDNS talks to it over `localhost:8080` via the generic webhook provider protocol; the sidecar translates to the UDM API. Both bykaj/home-ops and home-ops.old use this pattern.

**Implementation steps — Cloudflare instance (do first):**

1. Add `external-dns` HelmRepository to `kubernetes/flux/meta/repos/helm/`:
   ```yaml
   url: https://kubernetes-sigs.github.io/external-dns
   ```
2. Create directory layout under `kubernetes/apps/network/external-dns/`:
   ```
   external-dns/
   ├── ks.yaml                     # two Kustomizations: cloudflare + internal (multi-doc)
   ├── cloudflare/
   │   ├── kustomization.yaml
   │   ├── helmrelease.yaml        # chart: external-dns, namespace: network
   │   ├── externalsecret.yaml     # pulls CF_API_TOKEN from 1Password → external-dns-cloudflare-secret
   │   └── helm/values.yaml
   └── internal/
       └── ...                     # add when provider is decided
   ```
3. `externalsecret.yaml`: pull `cloudflare` item from 1Password vault, output key `CF_API_TOKEN` into secret `external-dns-cloudflare-secret`
4. `helm/values.yaml` for Cloudflare:
   - `provider: cloudflare`; `cloudflare.proxied: true`; `cloudflare.dnsRecordsPerPage: 1000`
   - `sources: [gateway-httproute, crd]`
   - `domainFilters: ["${DOMAIN}"]`
   - `policy: sync`; `registry: txt`; `txtOwnerId: k8s`; `txtPrefix: k8s.`
   - `gatewayNamespace: kube-system` (adjust to wherever the Cilium Gateway lands)
   - `serviceMonitor.enabled: true` (enable once kube-prometheus-stack is deployed)
5. In `ks.yaml`, `external-dns-cloudflare` Kustomization `dependsOn: [cilium, onepassword-connect]`
6. Add `network` namespace to `kubernetes/apps/kustomization.yaml` if not already present

**Implementation steps — UniFi instance:**

1. Create directory `kubernetes/apps/network/external-dns/unifi/` with same structure as `cloudflare/`
2. `externalsecret.yaml`: pull `unifi` item from 1Password → secret `external-dns-unifi-secret` with keys `UNIFI_HOST` and `UNIFI_API_KEY`
3. `helm/values.yaml` for UniFi:
   - `provider: webhook`
   - `extraArgs: [--webhook-provider-url=http://localhost:8080]`
   - `sources: [gateway-httproute, service]`
   - `domainFilters: ["${DOMAIN}", "home.arpa"]`
   - `policy: sync`; `registry: txt`; `txtOwnerId: k8s-internal`; `txtPrefix: k8s.`
     (distinct `txtOwnerId` avoids TXT record collisions with the Cloudflare instance)
   - `sidecars:` block for the webhook container:
     ```yaml
     - name: unifi-webhook
       image: ghcr.io/kashalls/external-dns-unifi-webhook:v0.8.2  # pin by digest in prod
       env:
         - name: UNIFI_HOST
           valueFrom: {secretKeyRef: {name: external-dns-unifi-secret, key: UNIFI_HOST}}
         - name: UNIFI_API_KEY
           valueFrom: {secretKeyRef: {name: external-dns-unifi-secret, key: UNIFI_API_KEY}}
         - name: UNIFI_SKIP_TLS_VERIFY
           value: "true"   # UDM Pro Max self-signed cert
       ports: [{name: webhook, containerPort: 8080}]
       livenessProbe: {httpGet: {path: /healthz, port: webhook}, initialDelaySeconds: 10}
       readinessProbe: {httpGet: {path: /readyz, port: webhook}, initialDelaySeconds: 10}
     ```
4. Store in 1Password: `unifi` item with `UNIFI_HOST` = `https://<udm-ip>` and `UNIFI_API_KEY` = UDM local API key

**Prerequisites to verify at implement-time:**
- `gateway-httproute` source requires CRD `httproutes.gateway.networking.k8s.io` — installed by Cilium when `gatewayAPI.enabled: true`
- Cloudflare API token needs **Zone:DNS:Edit** + **Zone:Zone:Read** permissions scoped to the domain zone
- Store token in 1Password as `cloudflare` item with field `CF_API_TOKEN`

**Dependencies:**
```
cert-manager ✅ → external-secrets ✅ → onepassword-connect ✅   ← credentials ready now
Cilium Gateway API (roadmap item above)                          ← gateway-httproute source
UniFi UDM Pro Max (LAN)                                          ← internal instance; always present
```

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
