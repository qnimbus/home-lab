# Home Lab — Cluster Configuration

> **Session log**: see [SESSIONS.md](docs/SESSIONS.md) for full details. Recent sessions (newest first):
>
> | Date | Session | Summary |
> |------|---------|---------|
> | 2026-05-13 | `eso-onepassword-connect-fix` | Fixed ClusterSecretStore/onepassword: credentials double-encoding bug (base64(base64(json)) required) + wrong vault name Kubernetes→homelab; fixed bootstrap task |
> | 2026-05-13 | `bootstrap-components-gitops` | Port Cilium/CoreDNS/Spegel/cert-manager/flux-operator/flux-instance to Flux HelmReleases; add OCIRepository sources to meta layer; remove Renovate comments from Helmfile |
> | 2026-05-13 | `cert-manager-cluster-issuer` | Deployed ESO + 1Password Connect + ClusterSecretStore; letsencrypt-staging/production ClusterIssuers via Cloudflare DNS-01; Cloudflare token sourced from 1Password ExternalSecret |
> | 2026-05-13 | `cp01-disk-role-swap` | Swapped cp-01 disk roles: GoodRam→system, Kingston→Longhorn storage; updated talconfig.yaml + docs; worked around talhelper 3.1.9 not supporting Talos v1.13.2; ISO-boot migration completed successfully |
> | 2026-05-13 | `longhorn-1.11.2-upgrade` | Upgraded Longhorn 1.9.0→1.11.2 via staged hops (1.10.2 intermediate); added crds:CreateReplace; direct 1.9→1.11 rejected by manager binary |
> | 2026-05-13 | `pr-19-review` | Reviewed PR #19 (Longhorn 1.9.0→1.11.2); 🚨 do not merge — missing `crds: CreateReplace` + v1beta1 storedVersions migration required |
> | 2026-05-13 | `openebs-4.4.0-upgrade` | Merged PR #18; force-reconciled Flux chain; confirmed HelmRelease upgraded to openebs@4.4.0 (UpgradeSucceeded) |
> | 2026-05-13 | `openebs-oci-source-fix` | Diagnosed timing race (HelmRelease checked source 30s early); forced reconcile; added `crds: CreateReplace` to HelmRelease |
 | 2026-05-13 | `claude-md-session-lifecycle` | Added mandatory session open/close workflow to CLAUDE.md |
> | 2026-05-13 | `kubernetes-upgrade-v1.35-v1.36` | Upgraded K8s v1.34.7→v1.35.4 (staggered apiserver patch mc + upgrade-k8s); v1.35.4→v1.36.0 via tuppr/Renovate native path (validated safe); documented gRPC flood / KubernetesUpgrade mismatch patterns; added Q&A entries; removed TROUBLESHOOTING.md; updated scripts/mcp.sh for reliable MCP |
> | 2026-05-13 | `kubernetes-upgrade-v1.34-crash-recovery` | Recovered v1.34.7 crash loop (gRPC→etcd flood, rbac/bootstrap-roles fatal timeout); staggered apiserver revert to v1.33.11 then re-upgrade to v1.34.7 with feature gates removed; documented root cause |
> | 2026-05-13 | `mcp-rbac-fix` | Replaced built-in `view` ClusterRoleBinding in `scripts/mcp.sh` with a custom `mcp-viewer` ClusterRole covering nodes, PVs, StorageClasses, Flux CRDs, and tuppr upgrade CRDs; made RBAC idempotent via `kubectl apply`; `renew-token` now re-applies RBAC before minting; added roleRef migration guard for immutable field |
> | 2026-05-13 | `longhorn-psa-fix` | Diagnosed Longhorn fully broken (0/3 CSI pods) due to missing `pod-security.kubernetes.io/enforce: privileged` on `longhorn-system` namespace; added PSA labels to namespace.yaml; added Storage QA entry |
> | 2026-05-12 | `talos-upgrade-v1.10-to-v1.13` | Upgraded Talos v1.10.6→v1.11.6→v1.12.7→v1.13.0; fixed upgrade-node Taskfile duplicate-`--image` bug; converted JSON 6902 admission patch to strategic merge (v1.12 multi-doc requirement); v1.13.1 is unreleased tag — targeted v1.13.0 |
> | 2026-05-12 | `purge-failed-pods-script` | Created `scripts/purge-failed-pods.sh` + `task purge-failed-pods`; owner-health-checked dry-run/live cleanup for Failed pods after unclean shutdown; extended QA.md |
> | 2026-05-12 | `tuppr-upgrade-controller-deployment` | Deployed tuppr as GitOps upgrade controller; fixed cosign + CRD chicken-and-egg rollout errors; updated Renovate for separateMinorPatch; added 5 QA entries |
> | 2026-05-12 | `crash-recovery-ghost-pods` | Diagnosed 91 ContainerStatusUnknown ghost pods after simultaneous 3-node power-off; deleted stale Failed pods; added unclean-shutdown diagnosis + cleanup section to QA.md |

This repository provisions and manages a bare-metal Talos Linux Kubernetes cluster using GitOps (FluxCD). Infrastructure-as-Code only: no manual `kubectl apply`, no imperative changes that are not reflected in Git.

> For a log of operational Q&A — behaviour that looked wrong but wasn't, diagnosis tips, cluster-specific gotchas — see [QA.md](docs/QA.md).

> For YAML comment style rules and community research guidance, see [CONVENTIONS.md](docs/CONVENTIONS.md).

> For a high-level overview of the cluster and FluxCD structure, see [CLUSTER.md](docs/CLUSTER.md).
> Keep `docs/CLUSTER.md` up to date as the cluster evolves: when adding new components, changing core infrastructure (CNI, DNS, storage, secrets strategy), or completing major bootstrap phases, update the relevant section. Keep entries concise and high-level — implementation details belong in code or `CLAUDE.md`.
>
> For pending and in-progress work items, see [ROADMAP.md](docs/ROADMAP.md). Update it when tasks are started, completed, or reprioritized.

---

## Repository Layout

```
📁 /
├── 📁 .archive/          # Previous cluster config — reference only, do not replicate wholesale
├── 📁 .claude/
│   └── agents/           # Specialized Claude Code agents (cluster-doctor, talos-node-manager)
├── 📁 .devcontainer/     # VS Code dev container (Python base, mise toolchain)
├── Taskfile.yaml         # Root go-task entry-point — run `task` to list all tasks
├── 📁 .taskfiles/
│   ├── talos/            # Talos node tasks (iso, genconfig, apply, bootstrap, upgrade, reset…)
│   └── bootstrap/        # Cluster bootstrap sequence (cluster, apps)
├── 📁 docs/              # Cluster documentation (CLUSTER.md, QA.md, ROADMAP.md, CONVENTIONS.md, SESSIONS.md)
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
├── 📁 kubernetes/        # FluxCD-managed workloads (Helmfile bootstrap + Flux GitOps)
│   ├── bootstrap/        # Helmfile: bootstraps Cilium → CoreDNS → Spegel → cert-manager → Flux
│   ├── flux/             # Flux system config, GitRepository, Kustomizations
│   │   └── meta/repos/   # HelmRepository, OCIRepository, GitRepository sources
│   └── apps/             # Application deployments — see GitOps Conventions for layout
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

Complete — all phases done, Flux fully reconciling. See **[CLUSTER.md → Bootstrap Runbook](docs/CLUSTER.md#bootstrap-runbook)** for the step-by-step guide (Phase 0–4), Day-2 config changes, and troubleshooting table (disk migration, version skew, etcd recovery).

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

See **[CONVENTIONS.md](docs/CONVENTIONS.md#documentation-comments-in-yaml-resources)** — what to comment, what not to, with examples.

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

Search **[kubesearch.dev](https://kubesearch.dev/)** before writing a new Kustomization. See **[CONVENTIONS.md](docs/CONVENTIONS.md#community-research-before-new-deployments)** for guidance on evaluating results.

---

## Key Architectural Decisions

See **[CLUSTER.md → Key Architectural Decisions](docs/CLUSTER.md#key-architectural-decisions)** for design decisions: Cilium (no kube-proxy), CoreDNS via HelmRelease, etcd on management subnet only, NFS defaults, and upgrade path.

---

## What is Complete vs. Planned

| Area                          | Status     | Notes                                           |
|-------------------------------|------------|-------------------------------------------------|
| Core infrastructure           | ✅ Done    | Talos configs, bootstrap, SOPS, Cilium, CoreDNS, cert-manager, Flux — all operational |
| OpenEBS LocalPV               | ✅ Done    | `openebs-hostpath` StorageClass live (non-default)           |
| Longhorn (2-replica interim)  | 🔄 Running | Live in 2-replica mode; bump to 3-replica when cp-02 drive installed |
| External Secrets + 1Password  | 🔲 TODO    | First GitOps apps                               |
| Split DNS (ExternalDNS)       | 🔲 TODO    | Internal (home.arpa) + external (Cloudflare)    |
| Renovate                      | ✅ Done    | `renovate.json5` + GitHub App; tracks Talos + K8s via `separateMinorPatch`; `talosctl` + `etcd` excluded (must match server version) |
| Talos + Kubernetes upgrades   | ✅ Done    | tuppr deployed in `system-upgrade`; `TalosUpgrade` + `KubernetesUpgrade` CRDs at current running versions; upgrades triggered by Renovate PRs |

---

## Claude Code Agents

Two specialized agents live in `.claude/agents/` and are invoked automatically by the harness when the task matches their description:

| Agent | When to use |
|-------|-------------|
| `cluster-doctor` | Diagnosing Kubernetes workload, networking, CNI, DNS, storage, scheduling, or GitOps/Flux issues. Talos-aware: escalates to node-layer diagnostics when K8s symptoms suggest a substrate problem. Prefers MCP tools over raw kubectl. |
| `talos-node-manager` | Inspecting or managing Talos Linux nodes directly: health checks, service logs, dmesg, etcd state, upgrade monitoring, disk/network diagnosis at the OS layer. Uses `talosctl` exclusively. |

Both agents maintain a `<!-- BEGIN/END: CLUSTER-STATE-AUTO -->` block in their own file that they self-update when live cluster state drifts from the recorded context.

---

## Session Lifecycle

These steps are **mandatory** — not optional hygiene. Do them at the boundaries of every session.

### Opening a session (first action, before any other work)

1. Choose a kebab-case slug that names the work (e.g. `external-secrets-deploy`, `longhorn-3-replica-bump`).
2. Prepend a stub entry to `docs/SESSIONS.md` immediately after the opening `---` separator:

   ```markdown
   ## YYYY-MM-DD — `session-slug`

   ### Goal
   One or two sentences describing the planned work.

   ---
   ```

3. Prepend a matching row to the CLAUDE.md session log table at the top of this file (use a short placeholder summary — fill it in properly when closing).

### Closing a session (last action, before stopping)

1. Complete the open stub in `docs/SESSIONS.md`:
   - Replace `### Goal` content (or keep it) and add `### What we did` (bullet list of actual work done)
   - Add `### Files changed` table
   - Add `### Key decisions` if any non-obvious choices were made
2. Replace the placeholder summary in the CLAUDE.md session log table with a real one-liner.

> If a session is interrupted mid-work, the stub is still useful — it records intent. Complete it in the next session under the same slug.

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
