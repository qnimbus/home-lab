# Home Lab — Cluster Configuration

> **Session log**: see [SESSIONS.md](docs/SESSIONS.md) for full details. Recent sessions (newest first):
>
> | Date | Session | Summary |
> |------|---------|---------|
> | 2026-09-05 | `image-pull-workflow` | Added image pre-pull CI (talosctl on a new no-RBAC runner via Talos ServiceAccount cert); rolled out live to 3 CP nodes |
> | 2026-09-05 | `renovate-self-hosted-actions` | Replaced Mend-hosted Renovate app with a self-hosted `renovate.yaml` workflow (bot App, every 6h); parked in-cluster runner on RBAC/uid findings |
> | 2026-09-05 | `flux-render-ci-flate-eval` | Added flux-render CI (flux-local test + post-render kubeconform + diff comment); flate 0.6.5 hangs on this tree (#828) |
> | 2026-09-05 | `ceph-tentacle-upgrade` | Upgraded Ceph 19.2.6 → 20.2.4 Tentacle in 4.5 min (rook mgr module off first, #18124); fixed open-webui Job TTL flap |
> | 2026-09-04 | `rook-post-upgrade-hygiene-configkey-audit` | Dropped dead csi-metrics ServiceMonitor (root-caused upstream), audited config-key store for CVE-2026-50152, rotated jwt |
> | 2026-09-04 | `ceph-cve-2025-30156-key-rotation` | Landed Ceph 19.2.6 + AES256K daemon key rotation (CVE-2025-30156) in one change; 10-min HEALTH_ERR window as designed |
> | 2026-09-04 | `rook-v120-upgrade-csi-drivers-draft` | Upgraded Rook to v1.20.7 with new ceph-csi-drivers chart + lockstep HR gates; caught hidden Ceph 19→20 bump, pinned 19.2.3 |
> | 2026-09-04 | `bifrost-image-tag-misfire` | Traced bifrost UpgradeFailed to Renovate mistaking a Helm chart artifact for an image; pinned v2.0.0, added guard rule |

This repository provisions and manages a bare-metal Talos Linux Kubernetes cluster using GitOps (FluxCD). Infrastructure-as-Code only: no manual `kubectl apply`, no imperative changes that are not reflected in Git.

> For a log of operational Q&A — behaviour that looked wrong but wasn't, diagnosis tips, cluster-specific gotchas — see [QA.md](docs/QA.md).

> For YAML comment style rules and community research guidance, see [CONVENTIONS.md](docs/CONVENTIONS.md).

> For a high-level overview of the cluster and FluxCD structure, see [CLUSTER.md](docs/CLUSTER.md).

> For a periodic audit of Flux configuration quality, manifest validation, security posture, and open recommendations, see [REPO-AUDIT.md](docs/REPO-AUDIT.md). Re-run `gitops-repo-audit` skill after significant changes to refresh findings.
>
> For a per-component failure-mode/disaster-recovery catalog (FMEA: blast radius, detection, mitigation, recovery, tested status), see [RESILIENCE-AUDIT.md](docs/RESILIENCE-AUDIT.md). Run `/resilience-audit <component>` to audit a new component or refresh an existing one.
>
> For a living inventory of every 1Password vault item this repo depends on (ExternalSecret consumers, wildcard vs. explicit field imports, bootstrap-time `op read` calls), see [EXTERNAL-SECRETS.yaml](docs/EXTERNAL-SECRETS.yaml). Re-derive it after adding/removing an ExternalSecret using the grep commands documented at the bottom of that file.
> Keep `docs/CLUSTER.md` up to date as the cluster evolves: when adding new components, changing core infrastructure (CNI, DNS, storage, secrets strategy), or completing major bootstrap phases, update the relevant section. Keep entries concise and high-level — implementation details belong in code or `CLAUDE.md`.
>
> For pending and in-progress work items, see [ROADMAP.md](docs/ROADMAP.md). Update it when tasks are started, completed, or reprioritized.

---

## Repository Layout

```
📁 /
├── 📁 .archive/          # Previous cluster config — reference only, do not replicate wholesale
├── 📁 .claude/
│   ├── agents/           # Specialized Claude Code agents (cluster-doctor, talos-node-manager)
│   └── commands/         # Project-local skills (/git-commit, /session-open, /session-close)
├── 📁 .devcontainer/     # VS Code dev container (Python base, mise toolchain)
├── Taskfile.yaml         # Root go-task entry-point — run `task` to list all tasks
├── 📁 .taskfiles/
│   ├── talos/            # Talos node tasks (iso, genconfig, apply, bootstrap, upgrade, reset…)
│   └── sops/             # SOPS/age key helper tasks
├── 📁 docs/              # Cluster documentation (CLUSTER.md, QA.md, ROADMAP.md, CONVENTIONS.md, SESSIONS.md)
├── 📁 ops/               # just-module tooling, invoked via `just <module> <recipe>`
│   ├── bootstrap/        # Helmfile bootstrap ladder (Cilium → CoreDNS → cert-manager → Flux) + `just bootstrap all` pipeline (bare `just bootstrap` lists subtasks)
│   ├── ceph/             # Rook-Ceph toolbox wrappers — status, crash-archive, ok-to-stop (`just ceph ...`)
│   └── cnpg/             # CloudNativePG restore/DR recipes (`just cnpg ...`)
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
├── 📁 kubernetes/        # FluxCD-managed workloads (GitOps tree; Helmfile bootstrap lives in ops/bootstrap/)
│   ├── flux/             # Flux system config, GitRepository, Kustomizations
│   │   └── meta/repos/   # HelmRepository, OCIRepository, GitRepository sources
│   └── apps/             # Application deployments — see GitOps Conventions for layout
├── 📁 truenas/           # Docker Compose stacks run on TrueNAS via doco-cd — NOT Flux-managed, see truenas/README.md
│   └── docker/           # One subdir per compose stack; listed in .doco-cd.truenas.yaml (repo root)
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

**MeshCommander** (Intel AMT web UI) runs as a docker-compose sidecar (`meshcommander` service, built from `.devcontainer/Dockerfile.meshcommander`). Port 3000 is bound directly to the host via `ports: "3000:3000"`, so it is accessible at `http://localhost:3000` as soon as the devcontainer stack starts — no VS Code forwarding needed. Open `http://localhost:3000` to access KVM, IDE-r (ISO boot), and power control for any node with Intel AMT configured. AMT nodes (`worker-01`, `worker-02`, `cp-02`) use native/untagged VLAN 100 (`10.100.0.0/24`) for AMT; Talos management rides tagged VLAN 60 on the same NIC.

Version bumps are handled by **Renovate** via the `# renovate: datasource=...` comments in `talenv.yaml` and Helmfile lock files.

---

## Cluster Hardware

Five bare-metal nodes — 3 control-plane + 2 workers, scheduling allowed on all
(`allowSchedulingOnControlPlanes: true`). This table is a quick agent-reference for node identity,
IPs, and management NIC chipset. **Source of truth for current-state hardware, NIC topology, and
disk inventory is [CLUSTER.md](docs/CLUSTER.md#cluster-overview)** — keep detail there, not here.
The 5-node build itself is complete; see [HARDWARE-ARCHITECTURE.md](docs/HARDWARE-ARCHITECTURE.md)
for the original sizing rationale and tier breakdown.

| Hostname        | Hardware                              | Mgmt IP     | Storage IP   | Mgmt NIC                     |
|-----------------|----------------------------------------|-------------|--------------|-------------------------------|
| talos-cp-01     | Minisforum MS-A2 (AMD Ryzen 9 9955HX, 16c/32t, 96GB ECC) | 10.60.0.201 | 10.200.0.201 | `enp4s0` Intel I225/I226 (`igc`) |
| talos-cp-02     | Lenovo M90q #1 (i5-10500T, 64GB)      | 10.60.0.202 | 10.200.0.202 | `eno1` Intel I219-LM (`e1000e`) |
| talos-cp-03     | Lenovo M90q #3 (i5-10500T, 64GB)      | 10.60.0.203 | 10.200.0.203 | `eno1` Intel I219-LM (`e1000e`) |
| talos-worker-01 | Lenovo M920Q #1 (i5-8500T, 32GB)      | 10.60.0.204 | 10.200.0.204 | `eno1` Intel I219-LM (`e1000e`) |
| talos-worker-02 | Lenovo M920Q #2 (i5-8600T, 64GB)      | 10.60.0.205 | 10.200.0.205 | `eno1` Intel I219-LM (`e1000e`) |

All 5 nodes carry Ceph storage traffic over a dedicated `bond-storage` LACP bond (802.3ad, MTU
9000) on `10.200.0.0/24` — see CLUSTER.md for per-node SFP+ card/driver detail. The `e1000e` vs
`igc` management-NIC split above matters operationally: `CephNodeNetworkPacketDrops` fires
recurringly on the four `e1000e` nodes and never on cp-01 — see
[QA.md](docs/QA.md#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan).

- **VIP**: `10.60.0.2` (Talos-native VIP via ARP, configured on each control-plane node's mgmt
  interface — not the separate kube-vip project/pod. cp-01, cp-02, cp-03 are eligible; workers do
  not participate)
- **Pod CIDR**: `10.42.0.0/16` | **Service CIDR**: `10.43.0.0/16`
- **Storage network**: `10.200.0.0/24` (SFP+, LACP) — jumbo frames (9000 MTU) live on all 5 nodes

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

Tasks that depend on `OP_SERVICE_ACCOUNT_TOKEN`: `just bootstrap age-key`, `just bootstrap resources`.

**Never commit plaintext secrets. Always run `sops --encrypt --in-place <file>` before staging.**

---

## Bootstrap Workflow

Complete — all phases done, Flux fully reconciling. See **[CLUSTER.md → Bootstrap Runbook](docs/CLUSTER.md#bootstrap-runbook)** for the step-by-step guide (Phase 0–2), Day-2 config changes, and troubleshooting table (disk migration, version skew, etcd recovery).

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

### Bootstrap ordering — place async prerequisites in the earlier Kustomization

The cluster must be fully bootstrapable from scratch, not just operational when already running.
A live cluster tolerates race conditions (controllers are already up, async resources resolve
quickly); a fresh bootstrap does not.

**Rule:** when a later Kustomization consumes a resource that is created *asynchronously* by a
controller — an `ExternalSecret` that causes ESO to create a `Secret`, a `Certificate` that causes
cert-manager to issue a TLS secret, etc. — place that resource in the **earlier** Kustomization's
path, not in the consuming Kustomization.

Why this works: `wait: true` on a Flux Kustomization blocks the dependent Kustomization until
every resource in the earlier one is **Ready**. An `ExternalSecret` is only Ready after ESO has
successfully created the target `Secret`. This turns an operator-level sequencing concern into a
Flux-enforced guarantee:

```
Kustomization A  (wait: true)
  └── ExternalSecret → ESO creates Secret → Ready ✓
        ↓  Flux will not start B until A is fully Ready
Kustomization B
  └── workload that reads the Secret — guaranteed present
```

Without this placement, Kustomizations A and B start simultaneously (or B begins before the async
resource in A completes), and the workload in B may start before its Secret exists — silent on a
live cluster, broken on a fresh bootstrap.

**Example:** `rook-ceph-dashboard-password` ExternalSecret lives in `operator/app/` (the operator
Kustomization, which has `wait: true`) rather than `cluster/app/` (the cluster Kustomization),
so the Secret is guaranteed present before the CephCluster is configured.

### HelmRelease cluster-wide defaults (via `cluster-apps` patch)

`cluster-apps` injects the following defaults into every HelmRelease via a nested patch on all
child Kustomizations. You do **not** need to declare these per-chart:

```yaml
install:
  crds: CreateReplace
  strategy:
    name: RetryOnFailure   # retry in-place (no uninstall between attempts)
  remediation:
    retries: 1             # 1 retry after first failure, then give up
    remediateLastFailure: true  # uninstall the failed release so next reconcile starts clean
timeout: 15m
upgrade:
  cleanupOnFail: true
  crds: CreateReplace
  strategy:
    name: RetryOnFailure   # retry upgrade in-place before rolling back
  remediation:
    remediateLastFailure: true
    retries: 3             # 3 retries, then rollback to previous revision
    strategy: rollback
driftDetection:
  mode: enabled   # opt out per-release — see below
```

`crds: CreateReplace` ensures CRD schemas are updated on chart upgrades (Helm's default is to
never update CRDs).

`driftDetection: enabled` detects and reverts any out-of-band changes to Helm-managed resources
on every reconciliation interval. See **[CONVENTIONS.md → Drift Detection](docs/CONVENTIONS.md#drift-detection)**
for the opt-out label and `ignore` rules pattern.

**Important — the global patch is the last writer.** Because the patch is injected as a nested
`spec.patches` entry appended to every child Kustomization, it always runs after any local
patches. This means **setting `timeout:` (or any other patched scalar field) directly in a
HelmRelease has no effect** — the global patch overwrites it. To change the timeout cluster-wide,
edit `kubernetes/flux/cluster/ks.yaml`. For per-chart overrides, see the `timeout` entry in
[QA.md](docs/QA.md).

Exception: `spec.driftDetection.ignore` rules set directly in a HelmRelease **do survive** the
global patch — the patch only writes `mode`, leaving the `ignore` list untouched (strategic merge
on object sub-fields).

### app-template v5 (bjw-s/app-template)

Most application HelmReleases use `bjw-s/app-template` (`ghcr.io/bjw-s-labs/helm/app-template`, currently `5.x`). Write all new app values against the v5 schema — it has breaking changes from v4. See **[CONVENTIONS.md → app-template v5](docs/CONVENTIONS.md#app-template-v5-bjw-s-app-template)** for the full schema rules.

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
| Longhorn (3-replica)          | ❌ Removed | Fully removed during the Rook-Ceph migration (big-bang, commit `8b27593`); all longhorn PVCs/PVs cleared. Superseded by Rook-Ceph |
| Rook-Ceph (`ceph-block`)      | ✅ Done    | Replicated-storage target; Rook v1.20.x (operator + cluster charts) + `ceph-csi-drivers` chart (owns the CSI driver since v1.20), Ceph image pinned in the cluster HR; `size=3`/`min_size=2`, host-net `cluster_network` on the `10.200.0.0/24` bond, `HEALTH_OK` with 3 host-spread OSDs. **`ceph-block` is the default StorageClass.** All consumers migrated (Phase 5: pgadmin, waha, kube-prometheus-stack — grafana+waha data restored from NFS). See [HARDWARE-ARCHITECTURE.md](docs/HARDWARE-ARCHITECTURE.md) |
| External Secrets + 1Password  | ✅ Done    | ESO + 1Password Connect deployed; `ClusterSecretStore` live |
| Split DNS (ExternalDNS)       | ✅ Done    | `external-dns-cloudflare` (envoy-external, proxied) + `external-dns-unifi` (all gateways + services, webhook sidecar); chart v1.21.1 |
| Renovate                      | ✅ Done    | `renovate.json5` + self-hosted `renovate.yaml` workflow (bot App, every 6 h; replaced the Mend app 2026-09-05); tracks Talos + K8s via `separateMinorPatch`; `talosctl` + `etcd` excluded (must match server version) |
| Image pre-pull (`image-pull.yaml`) | ✅ Done | Diffs container images between `main` and a PR, `talosctl image pull`s new ones on `home-lab` (Talos ServiceAccount cert, `os:admin`), Spegel fans the layer out cluster-wide before merge |
| Talos + Kubernetes upgrades   | ✅ Done    | tuppr deployed in `system-upgrade`; `TalosUpgrade` + `KubernetesUpgrade` CRDs at current running versions; upgrades triggered by Renovate PRs |
| Open WebUI                    | ✅ Done    | `ai` namespace; CNPG-backed (not SQLite), Dragonfly websocket manager, pre-provisioned admin (no open signup window), KEDA scales to 0 on Postgres/Dragonfly outage. No LLM backend wired — added manually post-deploy. See [CLUSTER.md → Running Components](docs/CLUSTER.md) |

---

## Claude Code Agents

Two specialized agents live in `.claude/agents/` and are invoked automatically by the harness when the task matches their description:

| Agent | When to use |
|-------|-------------|
| `cluster-doctor` | Diagnosing Kubernetes workload, networking, CNI, DNS, storage, scheduling, or GitOps/Flux issues. Talos-aware: escalates to node-layer diagnostics when K8s symptoms suggest a substrate problem. Prefers MCP tools over raw kubectl. |
| `talos-node-manager` | Inspecting or managing Talos Linux nodes directly: health checks, service logs, dmesg, etcd state, upgrade monitoring, disk/network diagnosis at the OS layer. Uses `talosctl` exclusively. |

Both agents maintain a `<!-- BEGIN/END: CLUSTER-STATE-AUTO -->` block in their own file that they self-update when live cluster state drifts from the recorded context.

### MCP server credentials

The MCP server uses a time-limited ServiceAccount token (default 8h). When the token expires, MCP tool calls fail with `"has asked for the client to provide credentials"`. **Renew immediately with:**

```sh
bash scripts/mcp.sh renew-token 8h
```

This re-applies RBAC (idempotent) and mints a fresh token into `~/.kube/mcp-viewer.kubeconfig`. No restart of the MCP server is needed — the kubeconfig is re-read on the next request.

---

## Session Lifecycle

Sessions are opened and closed via user-initiated skills — Claude cannot invoke these autonomously.

- **Opening**: The user should run `/session-open <slug>` before starting work. At the start of each conversation, check whether an open stub exists in `docs/SESSIONS.md`; if not, remind the user to run `/session-open` before proceeding.
- **Closing**: The user should run `/session-close` when done. When wrapping up, remind the user if no `### What we did` section exists yet in the current session stub.

> If a session is interrupted mid-work, the open stub is still useful — complete it in the next session using `/session-close`.

> **Never read `docs/SESSIONS.md` in full.** It is a large, ever-growing document that will fill the context window. Instead, grep or search for only what is needed — e.g. `grep -A 50 "slug-name" docs/SESSIONS.md` to extract a specific session block, or `grep -n "keyword" docs/SESSIONS.md` to locate relevant lines before reading a narrow range. The summary table in this file (`CLAUDE.md`) is the right starting point for recent session context.
>
> `SESSIONS.md` holds sessions from **2026-06-18 onward**; older sessions (**2026-05-06 → 2026-06-13**, the bootstrap/setup era plus the Ceph migration and five-node rebuild stretch) live in `docs/SESSIONS-ARCHIVE.md` (grep it the same way). When `SESSIONS.md` grows unwieldy again, roll the oldest sessions into the archive. New sessions are always appended to `SESSIONS.md`, never the archive.

---

## Working in This Repo

> **STOP — read before touching git:**
> Never run `git add` or `git commit` directly. Only the `/git-commit` skill may stage or commit, and only in one of two ways:
> 1. **User-invoked** — the user's message this turn explicitly typed `/git-commit` (or otherwise explicitly asked to stage/commit right now).
> 2. **Claude-invoked, worktree exception** — Claude may run `/git-commit` on its own initiative (e.g. to leave work committed before a task or session ends) **only** when all hold: the working directory is a git worktree Claude itself entered (path under `.claude/worktrees/`), the current branch is that worktree's own feature branch (never `main`), *and* that worktree/branch was actually created for the current task — not a pre-existing worktree the session merely happened to be launched into (its name and commit history describe unrelated, earlier work).
>
> Outside that exception — the primary checkout, any worktree currently on `main`, or a worktree/branch that turns out to be for a different task — completing a task does **not** imply permission to commit. Wait for the user to type `/git-commit` explicitly, or ask before committing into the wrong branch. The `/git-commit` skill itself re-checks this gate (its Step 0) before touching the index, so it is the safety net if this rule is ever misapplied.

- **Do not** stage or commit outside of `/git-commit` — use that skill only, respecting the authorization gate above. Finishing a task is not permission to commit in the primary checkout or on `main`.
- **Do not** `git push` automatically — always ask for explicit confirmation before every push, no exceptions.
- **Do not** `git fetch` or `git pull` automatically — ask for explicit confirmation before fetching or pulling.
- **Do not** run `kubectl apply` directly — all changes go through Git → Flux
- **Do not** edit generated files in `talos/clusterconfig/` — edit `talconfig.yaml` and re-run `genconfig`
- **Do** consult `.archive/` for patterns and prior art but adapt rather than copy wholesale
- **Do** keep `talenv.yaml` as the single source of truth for versions and network variables; patch files reference these
- **Do** add `# renovate: datasource=...` comments when pinning versions so Renovate can track them
- Secrets files: always encrypt before committing; verify with `sops --decrypt <file> | head`
- **Do** use `task` (no args) to list available tasks; use `task talos:genconfig`, `task talos:iso`, etc. instead of the retired `scripts/bootstrap.sh`
- The `kubeconfig` file (repo root, gitignored) is written by `task talos:kubeconfig`; set `KUBECONFIG=$(pwd)/kubeconfig`
