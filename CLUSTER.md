---
# Cluster Overview

Three-node bare-metal Talos Linux cluster (all control-plane, scheduling allowed). All state is declared in Git; nothing is applied imperatively post-bootstrap.

| Node | Hardware | Mgmt IP |
|------|----------|---------|
| talos-cp-01 | Lenovo M920Q (i5-8500T, 16GB) | 10.60.0.201 |
| talos-cp-02 | Lenovo M920Q (i5-8500T, 16GB) | 10.60.0.202 |
| talos-cp-03 | Minisforum MS-A2 (32c, 92GB) | 10.60.0.203 |

**VIP**: `10.60.0.2` (kube-vip) | **CNI**: Cilium (kube-proxy replacement) | **DNS**: CoreDNS via HelmRelease

---

## Node Disk Inventory

| Node | Device | Size | Model | Role |
|------|--------|------|-------|------|
| talos-cp-01 | nvme0n1 | 1.0 TB | Kingston SNV3S1000G | Talos system disk |
| talos-cp-02 | nvme0n1 | 1.0 TB | Kingston SNV3S1000G | Talos system disk |
| talos-cp-02 | nvme1n1 | 1.0 TB | IRP-SSDPR-P44N-01T-30 | **Free** — available for storage (wiped 2026-05-06) |
| talos-cp-03 | nvme0n1 | 2.0 TB | Crucial CT2000P310SSD8 | Talos system disk |

Only `talos-cp-02` has a second disk today. For Rook/Ceph to run across all three nodes, `talos-cp-01` and `talos-cp-03` will need additional drives designated as OSDs.

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
| 3 | `task talos:apply-all` | Pushes configs to all nodes (insecure / maintenance mode) |
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

# 2a. Push to all nodes at once:
task talos:apply-all

# 2b. Or push to a single node only:
task talos:apply IP=10.60.0.201
```

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
| `kubeconfig` accidentally deleted | File is gitignored, not in repo | Run `task talos:kubeconfig` — fetches it live from the Talos API (requires `talos/clusterconfig/talosconfig` and a reachable control-plane node) |

---

## Secrets

| Secret type | Mechanism | Location |
|-------------|-----------|----------|
| Talos secrets | SOPS + age | `talos/talsecret.sops.yaml` |
| Flux SSH deploy key | Kubernetes secret (imperative) | `flux-system/flux-system` |
| Application secrets | External Secrets Operator + 1Password Connect | `kubernetes/apps/` |

**Talos secret generation (`talsecret.sops.yaml`)** — generated once via `talhelper gensecret` and encrypted in-flight through `sops` before touching disk. This file must never be regenerated on a running cluster: the CA certificates and bootstrap tokens it contains are baked into every node's machine config. Regenerating invalidates all nodes and requires re-applying configs. The `bootstrap:cluster` task guards against accidental regeneration with `[ -f talsecret.sops.yaml ] || ...`. To intentionally start fresh, `rm talos/talsecret.sops.yaml` explicitly first.

See `CLAUDE.md` for full secrets management detail and SOPS rules.
