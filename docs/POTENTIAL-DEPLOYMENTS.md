# Potential Deployments

Reference: [`home-ops-bykaj`](../tmp/home-ops-bykaj/kubernetes) — a community home-ops repo used as a pattern reference.

Apps are grouped by functional area. Entries marked **✅ deployed** are already live in this cluster; all others are candidates to adopt.

---

## Core Infrastructure

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **cilium** ✅ | `cilium` v1.18.6 | `ghcr.io/home-operations/charts-mirror` | eBPF networking, kube-proxy replacement |
| **coredns** ✅ | `coredns` v1.45.2 | `ghcr.io/coredns/charts` | Cluster DNS |
| **cert-manager** ✅ | `cert-manager` v1.20.2 | `quay.io/jetstack/charts` | TLS certificate automation |
| **metrics-server** ✅ | `metrics-server` v3.13.0 | `HelmRepository: kubernetes-sigs.github.io/metrics-server` | Kubernetes resource metrics; `kubectl top` and HPA enabled |
| **flux-operator** ✅ | `flux-operator` v0.50.0 | `ghcr.io/controlplaneio-fluxcd/charts` | Flux v2 GitOps operator |
| **flux-instance** ✅ | `flux-instance` v0.50.0 | `ghcr.io/controlplaneio-fluxcd/charts` | Flux v2 instance |

---

## Secrets & Identity

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **external-secrets** ✅ | `external-secrets` v2.5.0 | `ghcr.io/external-secrets/charts` | Secret injection from external providers |
| **onepassword-connect** ✅ | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | 1Password Connect server |
| **authentik** | `authentik` v2026.5.0 | `ghcr.io/goauthentik/helm-charts` | Identity provider, SSO/OIDC — replaces or supplements any ad-hoc auth |
| **oidc-provider-debugger** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Debug OIDC flows — useful when deploying Authentik |

---

## Networking

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **envoy-gateway** ✅ | `gateway-helm` v1.8.0 | `mirror.gcr.io/envoyproxy/gateway-helm` | API Gateway (GatewayAPI) |
| **external-dns-cloudflare** ✅ | `external-dns` v1.21.1 | `ghcr.io/home-operations/charts-mirror` | DNS sync to Cloudflare |
| **external-dns-unifi** ✅ | `external-dns` v1.21.1 | `ghcr.io/home-operations/charts-mirror` | DNS sync to UniFi |
| **cloudflared** ✅ | `app-template` | — | Cloudflare Tunnel for secure ingress |
| **tailscale-operator** | `tailscale-operator` v1.96.5 | `ghcr.io/home-operations/charts-mirror` | Mesh VPN via Tailscale; gives zero-trust remote access |
| **echo-server** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Debug endpoint that echoes request headers/body |
| **whoami** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Minimal debug service for gateway/routing tests |
| **certificates** | (raw manifests) | — | Cluster-level Certificate objects and CA imports |
| **external-services** | (raw manifests) | — | ExternalName Services for out-of-cluster endpoints (KVM, Proxmox) |

---

## Storage

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **longhorn** ✅ | `longhorn` | — | Replicated block storage (our primary) |
| **openebs** ✅ | `openebs` v4.4.0 | `ghcr.io/home-operations/charts-mirror` | LocalPV `openebs-hostpath` StorageClass |
| **rook-ceph operator** | `rook-ceph` v1.19.5 | `ghcr.io/rook/rook-ceph` | Ceph distributed storage operator — alternative to Longhorn for large clusters |
| **rook-ceph cluster** | `rook-ceph-cluster` v1.19.5 | `ghcr.io/rook/rook-ceph-cluster` | Ceph cluster instance |
| **rook-ceph-tools** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Ceph admin toolbox pod |
| **csi-driver-nfs** | `csi-driver-nfs` v4.13.2 | `ghcr.io/home-operations/charts-mirror` | NFS dynamic provisioning (NAS integration) |
| **csi-driver-smb** | `csi-driver-smb` v1.20.1 | `ghcr.io/home-operations/charts-mirror` | SMB/CIFS dynamic provisioning |
| **snapshot-controller** | `snapshot-controller` v5.0.4 | `ghcr.io/piraeusdatastore/helm-charts` | VolumeSnapshot CRD controller (prerequisite for volsync) |
| **volsync** | `volsync` v0.18.5 | `ghcr.io/home-operations/charts-mirror` | PVC replication and off-cluster backup (restic, rclone) |

---

## System Utilities

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **spegel** | `spegel` v0.7.1 | `ghcr.io/spegel-org/helm-charts` | P2P container image mirror between nodes — reduces external pulls |
| **reloader** | `reloader` v2.2.11 | `ghcr.io/stakater/charts` | Rolls pods automatically on ConfigMap/Secret change |
| **reflector** | `reflector` v10.0.45 | `ghcr.io/emberstack/helm-charts` | Mirrors Secrets/ConfigMaps across namespaces (e.g. wildcard TLS cert) |
| **descheduler** | `descheduler` v0.36.0 | `ghcr.io/home-operations/charts-mirror` | Rebalances pods across nodes after drift |
| **keda** | `keda` v2.19.0 | `ghcr.io/home-operations/charts-mirror` | Event-driven autoscaling (Kafka, RabbitMQ, cron, etc.) |
| **intel-gpu-resource-driver** | `intel-gpu-resource-driver` v0.10.1 | `ghcr.io/intel/intel-resource-drivers-for-kubernetes` | GPU resource allocation for Intel iGPUs (transcoding) |
| **tuppr** ✅ | `tuppr` v0.1.35 | `ghcr.io/home-operations/charts` | Talos upgrade planner/automation |

---

## Observability

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **kube-prometheus-stack** | `kube-prometheus-stack` v85.2.2 | `ghcr.io/prometheus-community/charts` | Prometheus + Alertmanager + node-exporter + kube-state-metrics |
| **grafana-operator** | `grafana-operator` v5.23.0 | `ghcr.io/grafana/helm-charts` | Manages Grafana dashboards/datasources as CRDs |
| **victoria-logs** | `victoria-logs-single` v0.12.5 | `ghcr.io/victoriametrics/helm-charts` | Lightweight log aggregation; lighter than Loki |
| **fluent-bit** | `fluent-bit` v0.55.0 | `ghcr.io/home-operations/charts-mirror` | Log forwarder (node → victoria-logs or Loki) |
| **blackbox-exporter** | `prometheus-blackbox-exporter` v11.10.0 | `ghcr.io/prometheus-community/charts` | HTTP/DNS/TCP/ICMP probing for external endpoints |
| **gatus** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Status page with health checks; user-facing uptime dashboard |
| **kromgo** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Prometheus metric badges for README/dashboards |
| **unpoller** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Scrapes UniFi controller metrics into Prometheus |
| **goldilocks** | `goldilocks` | `charts.fairwinds.com/stable` | Analyses actual usage and suggests resource requests/limits |
| **goldilocks-vpa** | `vpa` | `charts.fairwinds.com/stable` | Vertical Pod Autoscaler (required by Goldilocks) |
| **robusta** | `robusta` | `robusta-charts.storage.googleapis.com` | Kubernetes alert enrichment and automated remediation |
| **silence-operator** | `silence-operator` v0.20.1 | `gsoci.azurecr.io/charts/giantswarm` | Manage Alertmanager silences as CRDs |

---

## Database & Data Stores

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **cloudnative-pg** | `cloudnative-pg` v0.28.2 | `ghcr.io/cloudnative-pg/charts` | PostgreSQL cluster operator (CNPG) — powers Authentik, Paperless, etc. |
| **cloudnative-pg-dashboard** | `cloudnative-pg-dashboard` v0.0.5 | `ghcr.io/cloudnative-pg/grafana-dashboards` | Grafana dashboards for CNPG clusters |
| **dragonfly** | `dragonfly-operator` v4.6.2 | `app-template` | Redis-compatible in-memory store; faster than Redis |
| **emqx** | `emqx-operator` | `repos.emqx.io/charts` | MQTT broker — IoT/home-automation integration |
| **barman-cloud** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | PostgreSQL WAL archiving to object storage |
| **postgres-backup-local** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Local PostgreSQL backup job |
| **meilisearch** | `meilisearch` | `meilisearch.github.io/meilisearch-kubernetes` | Fast full-text search engine |

---

## CI/CD & Development

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **actions-runner-controller** ✅ | `gha-runner-scale-set-controller` v0.14.1 | `ghcr.io/actions/actions-runner-controller-charts` | GitHub Actions ARC controller |
| **runners (home-ops)** ✅ | `gha-runner-scale-set` v0.14.1 | `ghcr.io/actions/actions-runner-controller-charts` | ARC runner scale set |
| **coder** | `coder` v2.33.5 | `ghcr.io/coder/chart` | Browser-based cloud development environments |
| **publish-schemas** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | CRD schema publishing job (feeds IDE validation) |

---

## Media

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **jellyfin** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Open-source media server (Plex alternative) |
| **plex** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Plex Media Server |
| **tautulli** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Plex usage statistics and monitoring |
| **plex-image-cleanup** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Removes orphaned Plex image cache |
| **audiobookshelf** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Audiobook and podcast server |
| **calibre-web-automated** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | eBook library with auto-import |
| **komga** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Comics and manga server |
| **stash** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Video library organizer |
| **your-spotify** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Personal Spotify listening history and stats |

---

## Downloads (*arr stack)

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **sonarr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | TV series automation |
| **radarr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Movie automation |
| **bazarr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Subtitle management for *arr |
| **prowlarr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Indexer aggregator/proxy |
| **autobrr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | IRC/RSS-based torrent automation |
| **sabnzbd** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Usenet downloader |
| **configarr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Centralized *arr configuration management |
| **whisparr** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Adult content automation (*arr-compatible) |

---

## Self-hosted Applications

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **homepage** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Application dashboard with service discovery |
| **paperless** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Document management with OCR (requires CNPG) |
| **n8n** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | No-code/low-code workflow automation |
| **atuin** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Encrypted shell history sync server |
| **changedetection** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Website change monitoring with alerts |
| **it-tools** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Collection of browser-based IT utilities |
| **kopia** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Backup tool with deduplication (pairs with volsync) |
| **opencloud** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | File sync and cloud storage (ownCloud fork) |
| **pgadmin** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | PostgreSQL web UI |
| **wallos** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Subscription and recurring expense tracker |
| **wastebin** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Fast minimal pastebin |
| **thelounge** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Always-on self-hosted IRC client |
| **karakeep** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Bookmark and read-it-later manager |
| **filabridge** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | 3D printer filament bridge/sync |
| **spoolman** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | 3D printer filament spool inventory |
| **nutify** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | UPS/NUT monitoring and notifications |

---

## Scheduled Jobs

| App | Chart | Source | Notes |
|-----|-------|--------|-------|
| **mailbackup** | `app-template` v4.6.2 | `ghcr.io/bjw-s-labs/helm/app-template` | Periodic email archive backup |

---

## Deployment Priority Notes

The following have natural dependencies and should be deployed in order if adopting the observability or application stacks:

```
snapshot-controller → volsync          (PVC backup pipeline)
cloudnative-pg → authentik             (CNPG backs Authentik's DB)
cloudnative-pg → paperless             (CNPG backs Paperless's DB)
kube-prometheus-stack → grafana-operator → cloudnative-pg-dashboard
authentik → any app needing SSO        (OIDC provider)
reflector → wildcard TLS sharing       (mirrors cert-manager certs across namespaces)
reloader → any app using ConfigMaps    (auto-roll on config change)
```

Chart versions listed are from the reference snapshot and will drift — always check the latest before deploying.
