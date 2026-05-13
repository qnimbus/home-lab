# Home Lab — Cluster Configuration

> **Session log**: see [SESSIONS.md](SESSIONS.md) for full details. Recent sessions (newest first):
>
> | Date | Session | Summary |
> |------|---------|---------|
> | 2026-05-13 | `kubernetes-upgrade-v1.35-v1.36` | Upgraded K8s v1.34.7→v1.35.4 (staggered apiserver patch mc + upgrade-k8s); v1.35.4→v1.36.0 via tuppr/Renovate native path (validated safe); documented gRPC flood / KubernetesUpgrade mismatch patterns; added Q&A entries; removed TROUBLESHOOTING.md; updated scripts/mcp.sh for reliable MCP |
> | 2026-05-13 | `kubernetes-upgrade-v1.34-crash-recovery` | Recovered v1.34.7 crash loop (gRPC→etcd flood, rbac/bootstrap-roles fatal timeout); staggered apiserver revert to v1.33.11 then re-upgrade to v1.34.7 with feature gates removed; documented root cause |
> | 2026-05-13 | `mcp-rbac-fix` | Replaced built-in `view` ClusterRoleBinding in `scripts/mcp.sh` with a custom `mcp-viewer` ClusterRole covering nodes, PVs, StorageClasses, Flux CRDs, and tuppr upgrade CRDs; made RBAC idempotent via `kubectl apply`; `renew-token` now re-applies RBAC before minting; added roleRef migration guard for immutable field |
> | 2026-05-13 | `longhorn-psa-fix` | Diagnosed Longhorn fully broken (0/3 CSI pods) due to missing `pod-security.kubernetes.io/enforce: privileged` on `longhorn-system` namespace; added PSA labels to namespace.yaml; added Storage QA entry |
> | 2026-05-12 | `talos-upgrade-v1.10-to-v1.13` | Upgraded Talos v1.10.6→v1.11.6→v1.12.7→v1.13.0; fixed upgrade-node Taskfile duplicate-`--image` bug; converted JSON 6902 admission patch to strategic merge (v1.12 multi-doc requirement); v1.13.1 is unreleased tag — targeted v1.13.0 |
> | 2026-05-12 | `purge-failed-pods-script` | Created `scripts/purge-failed-pods.sh` + `task purge-failed-pods`; owner-health-checked dry-run/live cleanup for Failed pods after unclean shutdown; extended QA.md |
| 2026-05-12 | `tuppr-upgrade-controller-deployment` | Deployed tuppr as GitOps upgrade controller; fixed cosign + CRD chicken-and-egg rollout errors; updated Renovate for separateMinorPatch; added 5 QA entries |
> | 2026-05-12 | `crash-recovery-ghost-pods` | Diagnosed 91 ContainerStatusUnknown ghost pods after simultaneous 3-node power-off; deleted stale Failed pods; added unclean-shutdown diagnosis + cleanup section to QA.md |
> | 2026-05-12 | `qa-log-and-eth0-rename` | Created QA.md operational Q&A log; explained eth0 rename kernel messages (normal Cilium CNI behaviour) |
> | 2026-05-12 | `storage-storageclasses-and-conventions` | Added longhorn-retain + longhorn-single StorageClasses; added doc-comment convention to CLAUDE.md |
> | 2026-05-12 | `persistent-storage-deploy-and-fix` | Deployed OpenEBS + Longhorn; fixed missing Namespace resources and ConfigMap namespace; both HelmReleases live; 3-replica upgrade deferred to cp-02 drive arrival |
> | 2026-05-07 | `persistent-storage-k8s-app-layer` | Full Flux app layer for OpenEBS LocalPV + Longhorn committed; 2-replica provisional config until cp-02 drive arrives; Flux Kustomization CRs in flux-system namespace |
> | 2026-05-07 | `persistent-storage-talos-prereqs` | iscsi-tools + util-linux-tools in schematic; per-node by-id disk patches for cp-01/cp-03; rolling upgrade all 3 nodes; fixed bootstrap:cluster doubled-path bug |
> | 2026-05-07 | `etcd-learner-recovery-and-toolchain` | Fixed cp-03 stuck etcd LEARNER (dual peer URLs from DHCP during LACP-off ISO boot); manual `etcdctl member promote`; added `etcd` to mise; excluded `talosctl`+`etcd` from Renovate |
> | 2026-05-07 | `cp03-nvme-swap-and-disk-migration` | Migrated cp-03 Talos to 128GB AirDisk via ISO boot; all nodes switched to `installDiskSelector` by model; 2TB Crucial now free for storage; `talos:apply` refactored with `INSECURE=true` flag |
> | 2026-05-07 | `persistent-storage-roadmap` | Added Persistent Storage entry to ROADMAP.md; researched Talos system-disk partitioning (not viable); discovered cp-01 also has free nvme1n1; corrected CLUSTER.md disk inventory; staged Longhorn rollout plan |
> | 2026-05-06 | `renovate-setup` | Added `renovate.json5`; installed Mend Renovate GitHub App; configured Helm/Flux/mise tracking; excluded Talos+k8s (managed separately); fixed 1password lookup failure |
> | 2026-05-06 | `node-hw-correction-and-runbook-updates` | Corrected node hardware assignments in talconfig.yaml (cp-01/cp-02 = M920Q, cp-03 = MS-A2); added `talos:wait-bootstrap` task; added Day-2 Config Changes section to CLUSTER.md |
| 2026-05-06 | `cp02-disk-cleanup` | Wiped Proxmox LVM (nvme1n1) from talos-cp-02 via `talosctl reset --wipe-mode=user-disks`; documented cluster disk inventory in CLUSTER.md |
> | 2026-05-06 | `cluster-bootstrap-runbook` | Full bootstrap validated end-to-end; added `talos:wait-maintenance` task; Bootstrap Runbook in CLUSTER.md; fixed flux-secret.sh cleanup trap bug; auto-reconcile after flux-secret |
> | 2026-05-06 | `devcontainer-secret-management` | Created `scripts/flux-secret.sh` (fetch Flux SSH deploy key from 1Password); `bootstrap:flux-secret` task |
> | 2026-05-06 | `mcp-server-rbac-scripts` | Created `scripts/mcp.sh` (setup/cleanup/renew-token); connected kubernetes-mcp-server MCP tool |
> | 2026-05-06 | `flux-ssh-secret-setup` | Fixed FluxInstance values (SSH URL, pullSecret, refs/heads/main); Flux now fully reconciling |
> | 2026-05-06 | `add-sops-plaintext-hook` | Added PreToolUse hook blocking git add/commit on plaintext `*.sops.yaml` files |
> | 2026-05-06 | `setup-sops-age-key-devcontainer` | Created CLAUDE.md; set `SOPS_AGE_KEY_FILE` via `devcontainer.json` `remoteEnv` |

This repository provisions and manages a bare-metal Talos Linux Kubernetes cluster using GitOps (FluxCD). Infrastructure-as-Code only: no manual `kubectl apply`, no imperative changes that are not reflected in Git.

> For a log of operational Q&A — behaviour that looked wrong but wasn't, diagnosis tips, cluster-specific gotchas — see [QA.md](QA.md).

> For a high-level overview of the cluster and FluxCD structure, see [CLUSTER.md](CLUSTER.md).
> Keep `CLUSTER.md` up to date as the cluster evolves: when adding new components, changing core infrastructure (CNI, DNS, storage, secrets strategy), or completing major bootstrap phases, update the relevant section. Keep entries concise and high-level — implementation details belong in code or `CLAUDE.md`.
>
> For pending and in-progress work items, see [ROADMAP.md](ROADMAP.md). Update it when tasks are started, completed, or reprioritized.

---

## Repository Layout

```
📁 /
├── 📁 .archive/          # Previous cluster config — reference only, do not replicate wholesale
├── 📁 .devcontainer/     # VS Code dev container (Python base, mise toolchain)
├── Taskfile.yaml         # Root go-task entry-point — run `task` to list all tasks
├── 📁 .taskfiles/
│   ├── talos/            # Talos node tasks (iso, genconfig, apply, bootstrap, upgrade, reset…)
│   └── bootstrap/        # Cluster bootstrap sequence (cluster, apps)
├── 📁 scripts/
│   └── mcp.sh            # MCP server ServiceAccount lifecycle (setup/cleanup/renew-token)
├── 📁 talos/             # Talos machine configs managed by talhelper
│   ├── talconfig.yaml    # Node definitions, network, patches references
│   ├── talenv.yaml       # Variables injected into talconfig (versions, IPs) — Renovate-tracked
│   ├── schematic.yaml    # Image Factory extensions (ucode, etc.)
│   ├── talsecret.sops.yaml  # Cluster secrets — SOPS-encrypted, never commit plaintext
│   ├── patches/
│   │   ├── global/       # Applied to every node
│   │   └── controller/   # Applied to control-plane nodes only
│   └── clusterconfig/    # Generated by talhelper — gitignored except talosconfig
├── 📁 kubernetes/        # (PLANNED) FluxCD-managed workloads — not yet created
│   ├── bootstrap/        # Helmfile: bootstraps Cilium → CoreDNS → Spegel → cert-manager → Flux
│   ├── flux/             # Flux system config, GitRepository, Kustomizations
│   │   └── meta/repos/   # HelmRepository, OCIRepository, GitRepository sources
│   └── apps/             # Application deployments, one sub-directory per namespace
│       └── <namespace>/
│           └── <app>/
│               ├── ks.yaml          # Flux Kustomization
│               └── app/
│                   ├── kustomization.yaml
│                   ├── helmrelease.yaml
│                   └── helm/values.yaml
└── 📁 assets/            # Downloaded ISOs (gitignored)
```

---

## Toolchain

All tools are pinned in `.mise.toml` and installed via `mise install`. Never install tools globally or via apt — use mise.

| Tool         | Purpose                                      |
|--------------|----------------------------------------------|
| `task`       | Task runner — replaces scripts/bootstrap.sh  |
| `talosctl`   | Talos node control                           |
| `talhelper`  | Renders talconfig.yaml → machine configs     |
| `kubectl`    | Kubernetes cluster control                   |
| `sops`       | Encrypts/decrypts secrets in-repo            |
| `age`        | Encryption backend for SOPS                  |

To activate: `eval "$(~/.local/bin/mise activate bash)"` (done automatically in devcontainer).

Version bumps are handled by **Renovate** via the `# renovate: datasource=...` comments in `talenv.yaml` and Helmfile lock files.

---

## Cluster Hardware

Three bare-metal control-plane nodes; no dedicated workers (`allowSchedulingOnControlPlanes: true`).

| Hostname       | Hardware                              | Mgmt IP       | Storage IP     | Notes                        |
|----------------|---------------------------------------|---------------|----------------|------------------------------|
| talos-cp-01    | Lenovo M920Q #1 (i5-8500T, 64GB)     | 10.60.0.201   | 10.200.0.201   | mgmt: e1000e, bond0: 2x ixgbe (X520) |
| talos-cp-02    | Lenovo M920Q #2 (i5-8500T, 64GB)     | 10.60.0.202   | 10.200.0.202   | mgmt: e1000e, bond0: 2x ixgbe (X520) |
| talos-cp-03    | Minisforum MS-A2 (AMD, 32c, 92GB)    | 10.60.0.203   | 10.200.0.203   | bond0: 2x RTL8125+igc, bond1: 2x i40e (X710) |

- **VIP**: `10.60.0.2` (kube-vip via ARP, all three CPs compete)
- **Pod CIDR**: `10.42.0.0/16` | **Service CIDR**: `10.43.0.0/16`
- **Storage network**: `10.200.0.0/24` (SFP+, LACP) — jumbo frames (9000 MTU) TODO
- **CNI**: Cilium (kube-proxy replacement, no built-in CNI)
- **DNS**: CoreDNS deployed via Helm (built-in disabled in Talos)

---

## Networks

| VLAN / Subnet       | Purpose                          |
|---------------------|----------------------------------|
| `10.60.0.0/24`      | Management / Kubernetes API      |
| `10.200.0.0/24`     | Storage (Ceph/Rook, NFS, iSCSI)  |
| `10.42.0.0/16`      | Pod network (Cilium)             |
| `10.43.0.0/16`      | Service network                  |

---

## Secrets Management

Two-tier strategy — do not conflate them:

1. **Talos secrets** (`talos/talsecret.sops.yaml`): Encrypted with SOPS+age. Age private key lives in `age.key` (gitignored). Public key is in `.sops.yaml`. Back up `age.key` to 1Password immediately after generation.

2. **Application secrets** (inside `kubernetes/`): Managed by External Secrets Operator pulling from **1Password Connect**. HelmReleases reference `ExternalSecret` objects; the actual values never touch Git.

SOPS creation rules (`.sops.yaml`):
- `talos/**/*.sops.yaml` → full-file encryption, `mac_only_encrypted: true`
- `kubernetes/**/*.sops.yaml` → `encrypted_regex: "^(data|stringData)$"` (only secret values, not keys)

**Required env vars** — both must be present for secrets tooling to work:

| Variable | Purpose | Where to set |
|----------|---------|--------------|
| `SOPS_AGE_KEY_FILE` | Points SOPS at the age private key | `devcontainer.json` `remoteEnv` (already configured) |
| `OP_SERVICE_ACCOUNT_TOKEN` | Authenticates the `op` CLI as a service account | WSL2 host environment — forwarded into the container via `${localEnv:...}` |

`SOPS_AGE_KEY_FILE` is set automatically by the devcontainer. `OP_SERVICE_ACCOUNT_TOKEN` must be exported in your **WSL2 host shell** (e.g. `~/.bashrc` or `~/.profile`) before the devcontainer starts — Docker reads `localEnv` at container creation time and passes an empty string if the variable is absent, causing `op whoami` to fail with a misleading auth error.

```sh
# WSL2 host ~/.bashrc (or ~/.profile)
export OP_SERVICE_ACCOUNT_TOKEN="<your-service-account-token>"
```

Tasks that depend on `OP_SERVICE_ACCOUNT_TOKEN`: `bootstrap:flux-secret`, `bootstrap:age-key`.

**Never commit plaintext secrets. Always run `sops --encrypt --in-place <file>` before staging.**

---

## Bootstrap Workflow

All bootstrap operations go through `task`. Run `task` with no args to list available tasks.

```
1.  Edit talos/talconfig.yaml — verify MACs, IPs, installDisk per node
2.  task talos:iso          → register schematic, download ISO, auto-update talenv.yaml
3.  Flash ISO: dd if=assets/talos-*.iso of=/dev/sdX bs=4M status=progress
4.  Boot nodes → enter maintenance mode (DHCP)
5.  task talos:genconfig    → generate machine configs + cluster secrets
6.  sops --encrypt --in-place talos/talsecret.sops.yaml
7.  task talos:apply-all    → push configs to all nodes (--insecure, maintenance mode only)
    # Day-2 on running nodes: task talos:apply IP=<node-ip>  (authenticated, no INSECURE flag)
    # Disk migration: boot from Talos ISO → task talos:apply IP=<node-ip> INSECURE=true
    #   (talosctl upgrade always reinstalls to the CURRENT system disk — use ISO to change disks)
    # talosctl version mismatch (ENHANCE_YOUR_CALM): mise exec talosctl@<server-ver> -- talosctl ...
8.  Nodes reboot with static IPs + Talos fully installed
9.  task talos:bootstrap    → initialise etcd on first control plane
10. task talos:kubeconfig   → fetch kubeconfig
11. kubectl get nodes -o wide → verify all nodes Ready
12. task bootstrap:apps     → install CNI, DNS, Flux via helmfile (use helmfile sync, not apply —
    apply pre-diffs all releases in parallel and fails on flux-instance because FluxInstance CRD
    doesn't exist until flux-operator installs it)
12a. kubectl create secret generic flux-system -n flux-system --from-file=identity=flux-deploy-key --from-file=identity.pub=flux-deploy-key.pub --from-file=known_hosts=known_hosts
    → SSH deploy key secret (must exist before Flux can pull the repo; only imperative step post-bootstrap)
13. git push → Flux takes over and reconciles kubernetes/apps/
```

Steps 1–13 are complete. Flux is fully operational and reconciling from the private GitHub repo.

---

## GitOps Conventions

Follow the archive's proven pattern (`/.archive/kubernetes/`) adapted for this cluster:

### Kustomization pattern

Each application has:
- `ks.yaml` — Flux `Kustomization` at the namespace level (defines source, path, deps, health checks)
- `app/kustomization.yaml` — standard Kustomize entry-point listing resources
- `app/helmrelease.yaml` — HelmRelease pointing to a source defined in `flux/meta/repos/`
- `app/helm/values.yaml` — Helm values (kept separate so Renovate can track chart versions)

### Naming conventions

- Namespaces match the directory name under `kubernetes/apps/` (e.g. `cert-manager`, `kube-system`)
- Flux Kustomization names match the app name (e.g. `cert-manager`, `cilium`)
- HelmRelease names match the chart name
- SOPS-encrypted files are always named `*.sops.yaml`

### Dependency ordering

Use `spec.dependsOn` in `ks.yaml` to enforce ordering. Typical order:
```
cilium → coredns → cert-manager → external-secrets → onepassword-connect → <app>
```

### Helm sources

Define all `HelmRepository` / `OCIRepository` sources in `kubernetes/flux/meta/repos/helm/` or `.../oci/`. HelmReleases reference these by name; never embed chart URLs inline.

### Deployment strategy for stateful apps

Use `strategy: Recreate` for any workload with `ReadWriteOnce` PVCs. Use `RollingUpdate` only for stateless workloads or those with `ReadWriteMany` storage.

### Documentation comments in YAML resources

All cluster YAML files (Talos patches, HelmRelease values, StorageClasses, Kustomizations, node configs) should carry comments that explain the *why*, not the *what*. The resource name and field names already say what — comments are for context that would otherwise be lost.

**Always comment:**
- Non-default values, especially when deviating from upstream chart defaults — explain the reason
- Provisional settings that need to change later (e.g. replica counts awaiting hardware) — include the trigger condition: `# 2 replicas until talos-cp-02 storage disk installed; bump to 3 when ready`
- Workarounds for known bugs or cluster-specific constraints — include a reference if one exists
- StorageClass and PersistentVolume resources — explain the intended use case and any operational implications (e.g. manual PV cleanup required for Retain policy)
- Values that look wrong but are intentional (e.g. `allowScheduling: false` on a node, `isDefaultClass: false` on a provisioner)

**Do not comment:**
- Fields whose purpose is self-evident from the field name and value
- Boilerplate that every Kubernetes resource has (`apiVersion`, `kind`, `metadata.name`)
- Comments that restate the YAML in prose ("sets the replica count to 2")

### Multi-document ks.yaml for operator + CRD instances

When an operator installs CRDs and you also want to deploy instances of those CRDs via Git, split
into two Kustomizations in a **single multi-document `ks.yaml`** file:

1. **Operator Kustomization** — deploys the HelmRelease; has explicit `healthChecks` for the HelmRelease
2. **CRD-instance Kustomization** — deploys CRD instances; has `dependsOn` pointing at the operator Kustomization

This is required because Flux dry-runs every resource in a Kustomization before applying any. If
instances and the HelmRelease are in the same Kustomization, the dry-run fails — the CRD types
don't exist yet. `dependsOn` + `healthChecks` ensures the operator is fully installed before the
instance Kustomization's dry-run runs.

Single file keeps the dependency relationship visible in one place (archive convention).

### `crds: CreateReplace` on operator HelmReleases

Add `crds: CreateReplace` to both `install` and `upgrade` blocks on any HelmRelease for a chart
that owns CRDs (operators, admission controllers, storage drivers). Helm's default is to never
update CRDs on upgrade — without this, a chart upgrade that ships a new CRD schema leaves the old
schema in the cluster, silently breaking resources that use new fields.

```yaml
install:
  crds: CreateReplace
upgrade:
  crds: CreateReplace
```

### Community research before new deployments

Before planning any new application deployment or writing a new Kustomization, search **[kubesearch.dev](https://kubesearch.dev/)** for the chart or app name. This indexes public home-lab GitOps repos and surfaces real-world `HelmRelease`, `values.yaml`, and `ExternalSecret` patterns used by other home labbers running the same stack (Talos + Flux + Cilium).

Use what you find as **research input only** — not a template to copy. For every pattern encountered:
- Understand *why* a value is set the way it is before adopting it
- Cross-check against the chart's official docs and upstream defaults
- Evaluate whether it applies to this cluster's specific hardware, network layout, and secrets strategy
- Prefer the simplest configuration that satisfies the actual requirements over one that mirrors what others have done

Community configs reflect their authors' constraints, mistakes, and historical baggage. Treat them as data points, not ground truth. The goal is to arrive at a well-reasoned configuration for *this* cluster — not to reproduce someone else's.

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

---

## What is Complete vs. Planned

| Area                          | Status     | Notes                                           |
|-------------------------------|------------|-------------------------------------------------|
| Talos machine configs         | ✅ Done    | 3 CP nodes, patches, schematic registered       |
| Bootstrap script              | ✅ Done    | go-task Taskfile replaces scripts/bootstrap.sh  |
| SOPS age key + rules          | ✅ Done    | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | ✅ Done    | All 14 bootstrap steps complete                 |
| kubernetes/ directory         | ✅ Done    | Helmfile + Flux structure in place              |
| Cilium                        | ✅ Done    | Running via Helmfile bootstrap                  |
| CoreDNS                       | ✅ Done    | Running via Helmfile bootstrap                  |
| cert-manager                  | ✅ Done    | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | ✅ Done    | Reconciling from private repo via SSH           |
| External Secrets + 1Password  | 🔲 TODO    | First GitOps apps                               |
| OpenEBS LocalPV               | ✅ Done    | `openebs-hostpath` StorageClass live (non-default)           |
| Longhorn (2-replica interim)  | 🔄 Running | Live in 2-replica mode; bump to 3-replica when cp-02 drive installed |
| External Secrets + 1Password  | 🔲 TODO    | First GitOps apps                               |
| Split DNS (ExternalDNS)       | 🔲 TODO    | Internal (home.arpa) + external (Cloudflare)    |
| Renovate                      | ✅ Done    | `renovate.json5` in place; GitHub App installed; Talos (`installer`) + k8s (`kubelet`) tracked via `separateMinorPatch` rules; `talosctl` + `etcd` still excluded (must match running server version) |
| Talos + Kubernetes upgrades   | ✅ Done    | tuppr deployed in `system-upgrade`; `TalosUpgrade` + `KubernetesUpgrade` CRDs at current running versions; upgrades triggered by Renovate PRs |

---

## Working in This Repo

- **Do not** add `Co-Authored-By:` trailers to git commit messages.
- **Do not** `git push` automatically — always ask for explicit confirmation before every push, no exceptions.
- **Do not** `git fetch` or `git pull` automatically — before any `git commit`, check whether remote changes exist (`git fetch --dry-run` or `git log HEAD..origin/<branch>`) and ask for explicit confirmation before fetching or pulling.
- **Do not** run `kubectl apply` directly — all changes go through Git → Flux
- **Do not** edit generated files in `talos/clusterconfig/` — edit `talconfig.yaml` and re-run `genconfig`
- **Do** consult `.archive/` for patterns and prior art but adapt rather than copy wholesale
- **Do** keep `talenv.yaml` as the single source of truth for versions and network variables; patch files reference these
- **Do** add `# renovate: datasource=...` comments when pinning versions so Renovate can track them
- Secrets files: always encrypt before committing; verify with `sops --decrypt <file> | head`
- **Do** use `task` (no args) to list available tasks; use `task talos:genconfig`, `task talos:iso`, etc. instead of the retired `scripts/bootstrap.sh`
- The `kubeconfig` file (repo root, gitignored) is written by `task talos:kubeconfig`; set `KUBECONFIG=$(pwd)/kubeconfig`
