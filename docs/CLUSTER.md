# Cluster Overview

Three-node bare-metal Talos Linux cluster (all control-plane, scheduling allowed). All state is declared in Git; nothing is applied imperatively post-bootstrap.

| Node | Hardware | Mgmt IP |
|------|----------|---------|
| talos-cp-01 | Lenovo M920Q (i5-8500T, 64GB) | 10.60.0.201 |
| talos-cp-02 | Lenovo M920Q (i5-8500T, 64GB) | 10.60.0.202 |
| talos-cp-03 | Minisforum MS-A2 (32c, 92GB) | 10.60.0.203 |

**VIP**: `10.60.0.2` (kube-vip) | **CNI**: Cilium (kube-proxy replacement) | **DNS**: CoreDNS via HelmRelease

---

## Running Components

**Talos v1.13.2 / Kubernetes v1.36.1.** All Helm-deployed components are installed via Helmfile during bootstrap (`kubernetes/bootstrap/helmfile.yaml`); version pins are tracked by Renovate.

### Kubernetes control plane · `kube-system`

Managed by Talos as **static pods** — one instance per control-plane node, no Helm chart involved. Talos regenerates these pods from `talconfig.yaml`; never edit their manifests directly.

| Component | Version | Replicas | Role |
|-----------|---------|----------|------|
| `kube-apiserver` | v1.36.1 | 3 (one/node) | REST gateway for all cluster operations; the authoritative source of cluster state |
| `kube-controller-manager` | v1.36.1 | 3 (one/node) | Runs built-in reconciliation loops — Deployments, ReplicaSets, node lifecycle, service accounts |
| `kube-scheduler` | v1.36.1 | 3 (one/node) | Assigns pending Pods to nodes based on resources, affinity rules, and taints |
| `etcd` | v3.6.11 (Talos-managed) | 3 (one/node) | Distributed key-value store holding all cluster state; runs as a Talos service, not a pod |

> **kube-proxy is not running.** Cilium replaces it entirely (`kubeProxyReplacement: true`).

---

### Cilium · `v1.17.6` · `kube-system`

**CNI (Container Network Interface)** — the cluster's network data-plane. Installed via Helmfile; values in `kubernetes/apps/kube-system/cilium/app/helm/values.yaml`.

| Pod | Type | Replicas | Role |
|-----|------|----------|------|
| `cilium` | DaemonSet | 3 (one/node) | Per-node agent that programs eBPF maps for pod networking, kube-proxy replacement, and network policy enforcement |
| `cilium-envoy` | DaemonSet | 3 (one/node) | Envoy proxy sidecar used by Cilium for L7-aware network policies and observability |
| `cilium-operator` | Deployment | 1 | Cluster-wide control-plane for Cilium — manages IP allocation (IPAM), CiliumNode objects, and Helm lifecycle |
| `cilium-secrets` namespace | — | — | Holds TLS material for Cilium's mutual-auth features; created and owned by the Cilium Helm chart |

---

### CoreDNS · `v1.43.0` (chart) · `kube-system`

**Cluster DNS.** Resolves `<service>.<namespace>.svc.cluster.local` names for all pods. Installed via Helmfile with image pulled from `mirror.gcr.io/coredns/coredns` (avoids Docker Hub rate limits). Talos's built-in CoreDNS is disabled — this Helm-managed instance is the sole DNS server.

| Pod | Type | Replicas | Role |
|-----|------|----------|------|
| `coredns` | Deployment | 2 | DNS server; handles in-cluster service discovery and forwards external queries upstream |

---

### Spegel · `v0.4.0` · `kube-system`

**P2P container image mirror.** Each node runs a Spegel agent that advertises locally-cached image layers to the other nodes via a peer-to-peer registry protocol. When a node pulls an image already present on a sibling node, it fetches layers locally over the cluster network instead of from the public registry — reducing pull latency and external bandwidth, and making the cluster resilient to registry outages.

| Pod | Type | Replicas | Role |
|-----|------|----------|------|
| `spegel` | DaemonSet | 3 (one/node) | Per-node OCI registry mirror; participates in P2P layer distribution |

---

### cert-manager · `v1.17.2` · `cert-manager`

**Certificate lifecycle manager.** Issues and renews X.509 certificates inside the cluster via `Certificate` and `Issuer`/`ClusterIssuer` CRDs. Not yet wired to any issuers (Let's Encrypt, internal CA) — present at bootstrap because it is a dependency for several planned add-ons (ingress controllers, external-secrets, etc.).

| Pod | Role |
|-----|------|
| `cert-manager` | Core controller — watches `Certificate` objects, triggers issuance/renewal via the configured issuer |
| `cert-manager-cainjector` | Injects CA bundles into `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration` objects so Kubernetes trusts cert-manager's own webhooks |
| `cert-manager-webhook` | Admission webhook that validates and mutates cert-manager CRD objects at creation time |

---

### FluxCD · operator `v0.23.0` · `flux-system`

**GitOps engine.** Continuously reconciles the cluster state against this Git repository. Installed in two layers: `flux-operator` (Helm chart, manages the Flux controllers) and `flux-instance` (a `FluxInstance` CR that wires Flux to the repo). After bootstrap, Flux owns its own Helm values files — the operator re-reconciles itself from Git.

| Pod | Role |
|-----|------|
| `flux-operator` | Lifecycle manager for Flux — installs, upgrades, and health-checks the four core Flux controllers |
| `source-controller` | Fetches sources (GitRepository, HelmRepository, OCIRepository) and makes their content available to other controllers |
| `kustomize-controller` | Applies Kustomization objects — renders and `kubectl apply`s manifests from Git paths |
| `helm-controller` | Reconciles `HelmRelease` objects — installs/upgrades Helm charts from sources |
| `notification-controller` | Handles `Alert` and `Receiver` objects for event-driven reconciliation triggers and outbound notifications |

---

### Longhorn · `v1.9.0` · `longhorn-system`

**Distributed block storage.** Provides replicated `ReadWriteOnce` PVCs across nodes using dedicated storage drives. Managed by Flux HelmRelease; values in `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml`.

| Pod | Type | Role |
|-----|------|------|
| `longhorn-manager` | DaemonSet | Core Longhorn agent on every node — manages volumes, replicas, and node health |
| `longhorn-driver-deployer` | Deployment | Deploys and manages the CSI driver components |
| `longhorn-ui` | Deployment | Web UI for volume and backup management |
| CSI components (`attacher`, `provisioner`, `resizer`, `snapshotter`) | Deployments | Standard CSI sidecar controllers that bind the Longhorn driver to the Kubernetes CSI framework |

> **Replica count**: currently 2 (cp-02 storage drive not yet installed). Bump to 3 once `talos-cp-02`'s Crucial P310 1TB is installed and the by-id path is patched into `talconfig.yaml`.

---

### OpenEBS · `v4.3.2` · `openebs`

**Local hostpath storage.** Provides the `openebs-hostpath` StorageClass for single-node `ReadWriteOnce` PVCs backed by local NVMe (non-replicated). Managed by Flux HelmRelease.

| Pod | Type | Role |
|-----|------|------|
| `openebs-localpv-provisioner` | Deployment | Dynamically provisions hostpath PVs on the local node |

---

### tuppr · `v0.1.28` · `system-upgrade`

**GitOps upgrade controller.** Watches `TalosUpgrade` and `KubernetesUpgrade` CRDs and performs rolling upgrades node-by-node. Triggered by Renovate PRs that bump version fields in `talenv.yaml` and `kubernetesupgrade.yaml`. Managed by Flux HelmRelease.

| CRD | Current | Role |
|-----|---------|------|
| `TalosUpgrade/cluster` | v1.13.2 | Tracks target Talos version; drives `talosctl upgrade` per node |
| `KubernetesUpgrade/kubernetes` | v1.36.1 | Tracks target Kubernetes version; drives `talosctl upgrade-k8s` |

---

## Node Disk Inventory

| Node | Device | Size | Model | Role |
|------|--------|------|-------|------|
| talos-cp-01 | — | 1.0 TB | GoodRam IRDM PRO NANO (IRP-SSDPR-P44N-01T-30) via M.2 A/E adapter | Talos system disk |
| talos-cp-01 | — | 1.0 TB | Kingston SNV3S1000G (`/dev/disk/by-id/nvme-KINGSTON_SNV3S1000G_50026B7686F8B787`) | Longhorn storage (`/var/mnt/longhorn-storage`) |
| talos-cp-02 | nvme0n1 | 1.0 TB | Kingston SNV3S1000G | Talos system disk (sole disk until Crucial P310 arrives) |
| talos-cp-02 | — | — | — | **Pending** — Crucial P310 1TB 2230 + M.2 A/E adapter on order; once installed Kingston moves to Longhorn storage |
| talos-cp-03 | nvme0n1 | 128 GB | AirDisk 128GB SSD | Talos system disk |
| talos-cp-03 | nvme1n1 | 2.0 TB | Crucial CT2000P310SSD8 | Longhorn storage (`/dev/disk/by-id/nvme-CT2000P310SSD8_252450B1A33B`) |

`talos-cp-01` and `talos-cp-03` are fully configured — storage disks live and mounted. `talos-cp-02`'s Crucial P310 1TB 2230 is on order — once installed, run `talosctl get disks --nodes 10.60.0.202`, update `talconfig.yaml` (change `installDiskSelector` to Crucial model, add `machine.disks` patch for Kingston), then ISO-boot cp-02 and apply in maintenance mode.

#### System-disk swap migration procedure (cp-01 / cp-02)

> Use this when the `installDiskSelector` has been changed to a different physical disk than the currently running system disk.

1. **Longhorn safety check** — confirm all volumes are `Healthy` before touching the node:
   ```bash
   kubectl -n longhorn-system get volumes
   ```
2. **Temporarily add wipe patch** — the old storage disk has non-Talos partitions; the installer will refuse to overwrite them without this. Add to the node's inline patch in `talconfig.yaml`:
   ```yaml
   machine:
     install:
       wipe: true
   ```
   Run `task talos:genconfig` to regenerate configs.
3. **Boot node from Talos ISO** — maintenance mode.
4. **Apply config in maintenance mode**:
   ```bash
   task talos:apply IP=10.60.0.20x INSECURE=true
   ```
   Talos installs on the new system disk and reboots.
5. **Remove wipe patch** — edit `talconfig.yaml`, remove `machine.install.wipe: true`, re-run `task talos:genconfig`, apply normally:
   ```bash
   task talos:apply IP=10.60.0.20x
   ```
6. **Kingston cleanup** — on first boot Talos will partition the old system disk (Kingston) for Longhorn via `machine.disks`. If it fails because old Talos partitions are present, add a temporary `wipeDisk: true` to the `machine.disks` entry and re-apply.

---

## FluxCD

Flux is bootstrapped via Helmfile (`kubernetes/bootstrap/helmfile.yaml`), not `flux bootstrap`. Two charts from the [flux-operator](https://fluxcd.control-plane.io/operator/) are used:

| Chart | Role |
|-------|------|
| `flux-operator` | Installs and manages Flux controllers |
| `flux-instance` | `FluxInstance` CR that wires Flux to this repository |

Values for both live under `kubernetes/apps/flux-system/*/app/helm/values.yaml` — the bootstrap Helmfile references these same files, so there is a single source of truth.

### Repository Sync

| Setting | Value |
|---------|-------|
| URL | `ssh://git@github.com/qnimbus/home-lab` |
| Ref | `refs/heads/main` |
| Path | `./kubernetes/flux/cluster` |
| Auth | `flux-system` secret in `flux-system` namespace (SSH deploy key) |
| Poll interval | 5 minutes |

The `flux-system` secret must be created imperatively during bootstrap (it cannot come from Git). Store the private key in 1Password.

### Kustomization Tree

```
kubernetes/flux/cluster/        ← FluxInstance sync root
├── cluster-meta                → kubernetes/flux/meta/      (HelmRepository, OCIRepository sources)
└── cluster-apps                → kubernetes/apps/           (all workloads)
```

- **Drift correction**: every 1 hour (Kustomization interval)
- **Change detection**: within 5 minutes of a `git push` (GitRepository poll)

### Bootstrap Order

```
Helmfile: cilium → coredns → spegel → cert-manager → flux-operator → flux-instance
          (then create flux-system SSH secret)
GitOps:   cluster-meta → cluster-apps → <individual app Kustomizations>
```

---

## Bootstrap Runbook

Step-by-step guide for bootstrapping the cluster from scratch or after a full reset. All commands run from the repo root inside the devcontainer.

### Phase 0 — Reset (re-bootstrap only)

> Skip on first bootstrap — nodes are already in maintenance mode after OS installation.

```bash
task talos:reset
```

Confirm the interactive prompt. The task wipes the `STATE` and `EPHEMERAL` Talos partitions on all three nodes and reboots them. The OS installation is preserved; no re-flashing is required.

Wait ~3–5 minutes, then poll until all nodes respond in maintenance mode:

```bash
task talos:wait-maintenance
```

Exits automatically once all three nodes return their Talos version.

> **Important**: `talsecret.sops.yaml` must **not** be regenerated on a running or previously-bootstrapped cluster. The CA certificates and bootstrap tokens it contains are baked into every node's machine config. The `bootstrap:cluster` task guards against accidental regeneration — it only generates the file if it does not already exist.

### Phase 1 — Bootstrap the cluster

```bash
task bootstrap:cluster
```

Runs these steps in sequence, with retries on the network-sensitive ones:

| Step | Command | Notes |
|------|---------|-------|
| 1 | `gensecret` guard | Skipped if `talsecret.sops.yaml` already exists |
| 2 | `task talos:genconfig` | Renders `talconfig.yaml` → machine configs in `clusterconfig/` |
| 3 | `task talos:apply-all` | Pushes configs to all nodes (`--insecure`, maintenance mode only) |
| 4 | `task talos:bootstrap` | Bootstraps etcd on the first control-plane node (retries until ready) |
| 5 | `task talos:kubeconfig` | Fetches `kubeconfig` to repo root (retries until API server responds) |

**Expected duration**: ~5–10 minutes

Verify the API server is reachable and all nodes are registered (they will be `NotReady` at this point — no CNI yet):

```bash
kubectl get nodes
```

> **Why `NotReady` here?** Kubernetes requires a CNI plugin before the kubelet will report a node as `Ready`. Without one, the node's `NetworkPluginNotReady` condition is set and it stays in `NotReady` indefinitely. Cilium is this cluster's CNI and is installed in Phase 2 — so nodes only become `Ready` after `bootstrap:apps` completes, not after `bootstrap:cluster`. This is expected behaviour, not a failure.

### Phase 2 — Bootstrap apps (Helmfile)

```bash
task bootstrap:apps
```

Installs charts in strict dependency order via `helmfile sync`:

| # | Chart | Namespace | Purpose |
|---|-------|-----------|---------|
| 1 | `cilium` | `kube-system` | CNI + kube-proxy replacement |
| 2 | `coredns` | `kube-system` | Cluster DNS |
| 3 | `spegel` | `kube-system` | P2P container image mirror |
| 4 | `cert-manager` | `cert-manager` | Certificate management |
| 5 | `flux-operator` | `flux-system` | Flux controller lifecycle manager |
| 6 | `flux-instance` | `flux-system` | `FluxInstance` CR — wires Flux to this repo |

> **Note**: the task uses `helmfile sync`, not `helmfile apply`. The `apply` subcommand pre-diffs all releases in parallel and fails on `flux-instance` because the `FluxInstance` CRD does not exist until `flux-operator` finishes installing.

**Expected duration**: ~5–10 minutes

Once helmfile completes, Cilium is running and nodes will transition to `Ready`. Poll until all three nodes are `Ready` (prints `kubectl get nodes -o wide` on exit):

```bash
task talos:wait-bootstrap
```

### Phase 3 — Flux SSH deploy key secret

This is the only imperative step post-bootstrap. The secret cannot come from Git because Flux needs it to pull from Git in the first place.

```bash
task bootstrap:flux-secret
```

Fetches the SSH deploy key from 1Password (`homelab` vault → `flux-deploy-key` item), creates the `flux-system` secret in the `flux-system` namespace with keys `identity`, `identity.pub`, and `known_hosts`, then immediately reconciles the `flux-system` GitRepository so Flux picks up the new secret without waiting for the next poll interval.

To verify the secret independently:

```bash
scripts/flux-secret.sh verify
```

### Phase 4 — Hand off to GitOps

```bash
git push    # push any uncommitted changes first
```

Flux polls the repository every 5 minutes. Verify reconciliation:

```bash
flux get all -A
kubectl get gitrepository,kustomization -A
```

All sources and Kustomizations should show `Ready = True`. The full sync path is:

```
flux-system GitRepository → cluster-meta Kustomization → cluster-apps Kustomization → <per-app Kustomizations>
```

### Day-2 Config Changes

Use this when modifying `talconfig.yaml` on a running cluster (patch changes, node settings, version bumps) — **not** a full re-bootstrap.

```bash
# 1. Edit talos/talconfig.yaml as needed, then regenerate machine configs:
task talos:genconfig

# 2a. Push to all running nodes (repeat per node):
task talos:apply IP=10.60.0.201
task talos:apply IP=10.60.0.202
task talos:apply IP=10.60.0.203

# 2b. Or push to a single running node:
task talos:apply IP=10.60.0.201
```

> `talos:apply` defaults to authenticated mode (mutual TLS via talosconfig) for **running** nodes.
> Pass `INSECURE=true` only during **bootstrap/maintenance mode**: `task talos:apply IP=x INSECURE=true`.
> `talos:apply-all` always uses `--insecure` and is for **bootstrap only**.
> `talos:genconfig` is run automatically inside `bootstrap:cluster` (Phase 1, Step 2). For day-2 edits you call it directly — `bootstrap:cluster` is for first-boot only.

---

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `talosctl version --insecure` times out | Node still rebooting | Wait and retry |
| `apply-all` fails with `connection refused` | Node not yet in maintenance mode | Wait and retry |
| `bootstrap:apps` fails on `flux-instance` | Running `helmfile apply` instead of `sync` | Always use `task bootstrap:apps` |
| Flux shows `Secret not found` | `flux-system` secret missing | Run `task bootstrap:flux-secret` |
| Flux shows `unable to clone` | SSH key not in GitHub deploy keys | Add `identity.pub` to repo deploy keys |
| `talosctl upgrade` installs to wrong disk | `upgrade` always targets the current system disk — `installDiskSelector` is ignored | Boot from Talos ISO → `task talos:apply IP=x INSECURE=true` |
| Installer refuses to touch disk with existing partitions | `wipe: false` (default) — installer skips non-Talos disks | Add temporary `machine: install: wipe: true` node patch; remove after migration |
| `talosctl upgrade` fails with `too_many_pings` / `ENHANCE_YOUR_CALM` | Client version newer than server — gRPC keepalive rate-limited | `mise install talosctl@<server-version>` then `mise exec talosctl@<version> -- talosctl upgrade ...` |
| NVMe device names swap after adding a drive (`nvme0n1` ↔ `nvme1n1`) | PCIe enumeration order changes with number of drives | Use `installDiskSelector: model: "<model>"` instead of `installDisk: /dev/nvme*` |
| `kubeconfig` accidentally deleted | File is gitignored, not in repo | Run `task talos:kubeconfig` — fetches it live from the Talos API (requires `talos/clusterconfig/talosconfig` and a reachable control-plane node) |
| Node stuck `STAGE: Booting READY: False` after ISO maintenance boot; etcd shows dual peer URLs (`<dhcp-ip>:2380` + `<static-ip>:2380`) | Switch ports in LACP mode during ISO boot → node gets temporary DHCP IP and records it as etcd peer URL; once LACP restored the DHCP IP vanishes and learner promotion stalls | 1. `talosctl etcd remove-member <stale-id> --nodes <other-node>` — node re-adds itself with correct peer URL only; 2. Wait for raft indexes to converge (`talosctl etcd status`); 3. Download etcdctl matching etcd version; extract certs via `talosctl read /system/secrets/etcd/{ca,admin}.{crt,key} --nodes <leader>`; 4. `ETCDCTL_API=3 etcdctl --endpoints https://<leader>:2379 --cacert ca.crt --cert admin.crt --key admin.key member promote <member-id-hex>` |

---

## Secrets

| Secret type | Mechanism | Location |
|-------------|-----------|----------|
| Talos secrets | SOPS + age | `talos/talsecret.sops.yaml` |
| Flux SSH deploy key | Kubernetes secret (imperative) | `flux-system/flux-system` |
| Application secrets | External Secrets Operator + 1Password Connect | `kubernetes/apps/` |

**Talos secret generation (`talsecret.sops.yaml`)** — generated once via `talhelper gensecret` and encrypted in-flight through `sops` before touching disk. This file must never be regenerated on a running cluster: the CA certificates and bootstrap tokens it contains are baked into every node's machine config. Regenerating invalidates all nodes and requires re-applying configs. The `bootstrap:cluster` task guards against accidental regeneration with `[ -f talsecret.sops.yaml ] || ...`. To intentionally start fresh, `rm talos/talsecret.sops.yaml` explicitly first.

See `CLAUDE.md` for full secrets management detail and SOPS rules.

---

## Key Architectural Decisions

- **No kube-proxy**: Cilium replaces it entirely (`proxy.disabled: true` in cluster patch)
- **No built-in CoreDNS**: Talos `coreDNS.disabled: true`; CoreDNS is a HelmRelease in `kube-system`
- **etcd on management subnet only**: `advertisedSubnets: ["10.60.0.0/24"]` keeps etcd off storage VLAN
- **NFS defaults**: `nfsvers=4.2`, `nconnect=16`, `hard=True`, `noatime=True` (set in machine files patch)
- **Container runtime**: unprivileged ports + ICMP enabled; image layers not discarded (cache efficiency)
- **Upgrade path**: tuppr (home-operations/tuppr) — `TalosUpgrade` + `KubernetesUpgrade` CRDs in `system-upgrade` namespace; Renovate opens PRs per minor version; tuppr performs rolling node-by-node upgrades via `talosctl upgrade-k8s` (sequential, safe for v1.35+)
  - **Preferred method**: merge the Renovate PR; tuppr handles the full upgrade automatically — no manual steps required and avoids the `KubernetesUpgrade` CRD mismatch problem (see QA.md)
  - **Pre-upgrade check**: always run `talosctl upgrade-k8s --to <version> --dry-run` before merging; flags removed feature gates and deprecated API versions before any change is made
  - **If upgrading manually** (apiserver only, via `talosctl patch mc`): use strategic merge form (`{"cluster":{"apiServer":{"image":"..."}}}`) — JSON RFC 6902 patches are rejected for multi-doc machine configs (talhelper v1.12+); wait for 2-minute stable PID per node before patching the next
  - **After any manual `upgrade-k8s`** that advances the cluster ahead of Git: delete the `KubernetesUpgrade` resource before Flux reconcile (`kubectl delete kubernetesupgrade kubernetes -n system-upgrade`) — otherwise tuppr sees CURRENT > TARGET and starts failing downgrade jobs
