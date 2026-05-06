---
# Cluster Overview

Three-node bare-metal Talos Linux cluster (all control-plane, scheduling allowed). All state is declared in Git; nothing is applied imperatively post-bootstrap.

| Node | Hardware | Mgmt IP |
|------|----------|---------|
| talos-cp-01 | Minisforum MS-A2 (32c, 92GB) | 10.60.0.201 |
| talos-cp-02 | Lenovo M920Q (i5-8500T, 16GB) | 10.60.0.202 |
| talos-cp-03 | Lenovo M920Q (i5-8500T, 16GB) | 10.60.0.203 |

**VIP**: `10.60.0.2` (kube-vip) | **CNI**: Cilium (kube-proxy replacement) | **DNS**: CoreDNS via HelmRelease

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

## Secrets

| Secret type | Mechanism | Location |
|-------------|-----------|----------|
| Talos secrets | SOPS + age | `talos/talsecret.sops.yaml` |
| Flux SSH deploy key | Kubernetes secret (imperative) | `flux-system/flux-system` |
| Application secrets | External Secrets Operator + 1Password Connect | `kubernetes/apps/` |

See `CLAUDE.md` for full secrets management detail and SOPS rules.
