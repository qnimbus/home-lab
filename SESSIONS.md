# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

---

## 2026-05-07 — `persistent-storage-roadmap`

### What we did
- Added a comprehensive **Persistent Storage** entry to `ROADMAP.md` covering: hardware snapshot,
  Talos system-disk partitioning research, storage option comparison, and a 4-stage rollout plan
- Ran `talosctl get discoveredvolumes` against all three nodes to get ground-truth disk inventory
- Discovered **cp-01 also has a free nvme1n1 (1 TB, no partition table)** — not previously documented;
  only cp-03 still lacks a secondary drive
- Corrected `CLUSTER.md` disk inventory and updated the storage row in `CLAUDE.md`'s status table

### Files created / modified
| File | Change |
|------|--------|
| `ROADMAP.md` | New "Persistent Storage" section added before External Secrets; covers hardware, Talos partitioning verdict, option table, and 4-stage rollout |
| `CLUSTER.md` | Disk inventory table updated — cp-01 nvme1n1 added; closing note corrected |
| `CLAUDE.md` | Storage row in "What is Complete vs. Planned" updated; session log row added |

### Decisions made / researched

**Talos system-disk partitioning — not viable**
The `EPHEMERAL` partition grows to fill 100% of remaining disk space at install time (confirmed
live: cp-01 nvme0n1p4 = 999 GB, cp-03 nvme0n1p4 = 2.0 TB). `machine.disks` only targets
non-system disks; the `UserVolume` API (Talos 1.9+) does not carve space from `EPHEMERAL` either.
Hostpath-inside-EPHEMERAL is possible but shares IOPS/capacity with the OS — avoid for stateful data.

**Recommended storage path (staged)**
1. **OpenEBS LocalPV** — deploy now, no hardware needed, hostpath storage class for cache/CI
2. **Longhorn on cp-01 + cp-02** — use both free nvme1n1 drives; 2-replica HA immediately
3. **One NVMe for cp-03** — completes 3-node set; promote to 3 replicas or evaluate Rook/Ceph
4. **NFS/SMB CSI** — if/when a NAS is added; ReadWriteMany workloads, wired via ExternalSecret

**Longhorn handles asymmetric disk sizes fine**
Longhorn is replica-based (not pool-based), so a 2 TB OSD on cp-03 vs 1 TB on the others is a
non-issue. Each volume replica is sized to the volume, not the disk. The larger disk simply
absorbs more replicas/volumes and has more scheduling headroom.

### Learned / noted
- `talosctl disks` is deprecated in Talos 1.10+; use `talosctl get discoveredvolumes` instead
- The live node inventory contradicted the documented disk inventory — worth verifying hardware
  state with `talosctl` rather than relying solely on documentation from prior sessions

---

## 2026-05-07 — `bootstrap-task-params-and-age-key`

### What we did
- Added optional `VAULT` and `ITEM` parameters to `bootstrap:flux-secret` — previously the task silently accepted `OP_VAULT`/`OP_ITEM` env vars (known only to the script), now they are first-class Taskfile parameters with defaults shown in the task description
- Created `scripts/age-key.sh` — fetches the SOPS age private key from 1Password and writes it to `age.key`; mirrors the structure of `flux-secret.sh` exactly (same colour helpers, `op whoami` check, `--force` guard, `trap cleanup EXIT`, validation before write)
- Added `bootstrap:age-key` task wiring `VAULT`, `ITEM`, `FIELD` as optional task parameters

### Files created / modified
| File | Change |
|------|--------|
| `.taskfiles/bootstrap/Taskfile.yaml` | `flux-secret`: added `vars:` + `env:` for `VAULT`/`ITEM`; updated `desc` to advertise params. Added new `age-key` task with `VAULT`/`ITEM`/`FIELD` params |
| `scripts/age-key.sh` | Created — `fetch` / `verify` subcommands; fetches age key from 1Password, validates `AGE-SECRET-KEY-1` prefix, writes to `$SOPS_AGE_KEY_FILE`, `chmod 600` |

### Decisions made
- **`vars:` + `env:` two-step** — Taskfile `vars:` resolves the `| default` template; `env:` then sets the shell environment variable the script reads. This is the only way to apply Taskfile template functions and still have the result visible to a subprocess
- **Param names `VAULT`/`ITEM`/`FIELD`** (not `OP_VAULT` etc.) — task parameters follow the project convention of short uppercase names (cf. `IP=required` in talos tasks); the `OP_` prefix is the script's internal convention
- **Validate before write** — script checks the retrieved value starts with `AGE-SECRET-KEY-1` before moving the temp file to `age.key`; a wrong field name (e.g. pointing at the public key comment) would otherwise silently corrupt the key file
- **Defaults `ITEM="SOPS age key"`, `FIELD="text"`** — updated to match the actual 1Password item structure; overridable at call site for portability

### Learned / noted
- `trap cleanup EXIT` fires at *script* exit, not at function return — any variable the `cleanup` function references must be in scope at process exit. A `local` variable inside the function that sets the trap is out of scope by that point; with `set -u` this kills the script with `unbound variable`. Fix: omit `local` for temp-file vars that the trap handler touches (same pattern already used in `flux-secret.sh`)
- `task bootstrap:age-key -- verify` does not forward the subcommand to the script; extra args after `--` in go-task CLI syntax are passed as `CLI_ARGS`, not appended to `cmds`. Call the script directly for subcommands that are not wired as separate tasks

---

## 2026-05-06 — `renovate-setup`

### What we did
- Added `renovate.json5` at the repo root to configure the Mend Renovate GitHub App
- Installed the Mend Renovate GitHub App on `qnimbus/home-lab` (browser step, user-performed)
- Fixed a lookup failure for the `1password` mise tool — added to `ignoreDeps` because the CLI is distributed via AgileBits' own servers, not GitHub; Renovate defaults to `github-tags` for unknown mise tools and finds nothing
- Disabled Talos + Kubernetes version tracking in Renovate at user request — those versions will be managed via a separate upgrade mechanism; added both `ghcr.io/siderolabs/installer` and `ghcr.io/siderolabs/kubelet` to `ignoreDeps`

### Files created / modified
| File | Change |
|------|--------|
| `renovate.json5` | Created — full Renovate config (see decisions below) |

### Decisions made
- **`ignoreDeps` over `packageRules[enabled:false]`** for manually-managed packages: `ignoreDeps` is an early filter evaluated before any manager or `packageRule`, making the intent ("don't touch these") explicit and up-front rather than buried in a rule
- **`docker:enableMajor` preset included** — without it Renovate silently skips major Docker image bumps; Talos and Kubernetes use `datasource=docker`, so this would suppress major version notifications for those packages (and any future ones tracked the same way)
- **`schedule: ["every weekend"]`** — avoids weekday PR noise on a home lab; can be changed to `"at any time"` for continuous scanning
- **`automergeType: "branch"` for mise and GitHub Actions** — Renovate merges directly to the branch when clean, no PR required; `ignoreTests: true` needed because this repo has no CI
- **`minimumReleaseAge: "3 days"` on GitHub Actions auto-merge** — gives the community a soak window to catch regressions before an update lands automatically
- **Grouped `Talos + Kubernetes`, `Flux`, `cert-manager`, `CoreDNS`, `Spegel`** — components that always ship together or should be reviewed together produce a single PR rather than one each
- **Custom regex manager** uses `datasource=` annotation format (e.g. in `talenv.yaml`); the native helmfile manager uses the `registryUrl=` annotation format — they look similar but feed different Renovate subsystems
- **`ignorePaths: ["**/*.sops.*"]`** — prevents Renovate from treating encrypted ciphertext as version strings

### Learned / noted
- Two annotation styles coexist in the repo: `# renovate: registryUrl=... chart=...` (read by the native `helmfile` manager from `helmfile.yaml`) and `# renovate: datasource=... depName=...` (read by the custom regex manager from `talenv.yaml`). They are not interchangeable
- Renovate's `mise` manager reads `.mise.toml` natively but falls back to `github-tags` for any tool it doesn't recognise. The `1password` tool resolves via `aqua:1password/cli` in the mise registry (an AgileBits download, not GitHub), so the `github-tags` lookup returns no results
- The `$schema` URL in `renovate.json5` triggers a VS Code JSON language-server warning in the devcontainer ("location untrusted") because the container cannot reach `docs.renovatebot.com` at schema-load time — the config is valid and Renovate itself reads the schema correctly when running remotely; the warning is a false positive

---

## 2026-05-06 — `node-hw-correction-and-runbook-updates`

### What we did
- Corrected a node hardware mix-up in `talconfig.yaml` and `CLAUDE.md`: `talos-cp-01` had been configured with MS-A2 NIC drivers (RTL8125 / i40e) and a two-NIC LACP bond on management, but is actually a Lenovo M920Q with a single e1000e management NIC and ixgbe storage bond; `talos-cp-03` is the Minisforum MS-A2
- Updated network interface config for `talos-cp-01` to use `deviceSelector: driver: e1000e` (single NIC, no bond on management) and `bond0` with `driver: ixgbe` (storage, X520-DA2)
- Fixed the node order in the CLAUDE.md hardware table to match physical assignments (cp-01 = M920Q #1, cp-02 = M920Q #2, cp-03 = MS-A2)
- Added `talos:wait-bootstrap` task — polls `kubectl get nodes` until all nodes (count derived from `talconfig.yaml`) show `Ready`, then prints `kubectl get nodes -o wide` and exits
- Added a **Day-2 Config Changes** section to the Bootstrap Runbook in `CLUSTER.md` documenting the standalone `genconfig` → `apply-all` / `apply IP=` pattern for post-bootstrap config edits
- Updated Phase 1 of the Bootstrap Runbook to use `task talos:wait-bootstrap` instead of a bare `kubectl get nodes -o wide`

### Files created / modified
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Corrected `talos-cp-01` hardware: e1000e mgmt NIC (no bond), ixgbe storage bond (X520-DA2); fixed node hostname comments |
| `CLAUDE.md` | Fixed hardware table: cp-01/cp-02 = M920Q, cp-03 = MS-A2 |
| `.taskfiles/talos/Taskfile.yaml` | Added `talos:wait-bootstrap` task |
| `CLUSTER.md` | Added Day-2 Config Changes section; Phase 1 verification now uses `task talos:wait-bootstrap` |

### Decisions made
- `wait-bootstrap` derives expected node count from `yq '.nodes | length' talconfig.yaml` rather than hardcoding 3 — stays correct if nodes are added
- `awk '$2 == "Ready"'` used for node status check (exact column match) rather than `grep Ready`, which would also match "NotReady"
- Day-2 config change section placed immediately before Troubleshooting in the runbook — it answers a "what do I run after editing talconfig?" question which naturally precedes debugging

### Learned / noted
- `bootstrap:cluster` embeds `talos:genconfig` as step 2 — it is not visible as a top-level runbook step, which makes it easy to miss when doing day-2 config edits outside of a full re-bootstrap
- Node hardware assignments were transposed from a previous session: the MS-A2 (cp-03) config had been applied to cp-01's stanza, causing it to reference i40e and RTL8125 drivers that don't exist on the M920Q hardware

---

## 2026-05-06 — `cp02-disk-cleanup`

### What we did
- Identified and wiped a legacy Proxmox LVM installation from `nvme1n1` on `talos-cp-02` (10.60.0.202)
- Discovered the disk inventory across all three nodes via `talosctl get disks` and `talosctl get discoveredvolumes`
- Documented disk inventory in `CLUSTER.md`

### Problem and resolution
The Proxmox install had left an LVM2 Physical Volume on `nvme1n1p3`, with the volume group activating 8 `dm-*` logical volumes at every boot. The kernel's device mapper stack (`dm-0` through `dm-7`) blocked all `talosctl wipe` attempts with `FailedPrecondition: blockdevice in use`. Wiping the LV content (`dm-*` devices) did not release the mappings because LVM re-activates based on PV metadata, not LV content. The fix was `talosctl reset --graceful=false --reboot --wipe-mode=user-disks --user-disks-to-wipe=/dev/nvme1n1`, which wiped `nvme1n1` during Talos's own shutdown path before LVM re-activated.

### Files created / modified
| File | Change |
|------|--------|
| `CLUSTER.md` | Added Node Disk Inventory section |

### Decisions made
- `--wipe-mode=user-disks` was the correct flag — it wipes only the specified user disk and preserves the system disk (`nvme0n1`), so the node retained its Talos machine config and rejoined the cluster immediately after reboot without requiring `apply-config`

### Learned / noted
- `talosctl disks` is deprecated; use `talosctl get disks`, `talosctl get systemdisk`, `talosctl get discoveredvolumes` instead
- `talosctl wipe disk` takes a bare device ID (e.g. `nvme1n1`), **not** a `/dev/` path — but `talosctl reset --user-disks-to-wipe` takes the full `/dev/nvme1n1` path on Talos 1.10.6
- `talosctl get discoveredvolumes` shows filesystem/volume-manager signatures per partition (e.g. `lvm2-pv`, `ext4`, `swap`) — the most useful command for identifying foreign disk layouts
- LVM PV header lives on the partition (`nvme1n1p3`), not the LV content; wiping `dm-*` devices zeroes LV data but leaves the PV metadata intact — LVM will re-activate the VG on every reboot until the PV header itself is destroyed
- `talosctl reset` wipes disks during its own shutdown sequence, bypassing the userspace "in use" guard that blocks live wipe commands

---

## 2026-05-06 — `cluster-bootstrap-runbook`

### What we did
- Performed a full end-to-end cluster bootstrap from reset through Flux operational: `talos:reset` → `talos:wait-maintenance` → `bootstrap:cluster` → `bootstrap:apps` → `bootstrap:flux-secret` → verified `flux get all -A` shows all resources `Ready`
- Added `talos:wait-maintenance` task — polls TCP port 50000 per node (sequential, prints dots) and exits once all nodes accept connections
- Added a comprehensive **Bootstrap Runbook** to `CLUSTER.md` covering all four phases with tables, timing estimates, and a troubleshooting section
- Fixed `scripts/flux-secret.sh` — removed `local` from temp file variable declarations so the `trap cleanup EXIT` handler can reference them at script exit
- Updated `bootstrap:flux-secret` task to chain `flux reconcile source git flux-system` immediately after secret creation, eliminating the manual reconcile step that was otherwise needed

### Files created / modified
| File | Change |
|------|--------|
| `CLUSTER.md` | Added Bootstrap Runbook section (Phases 0–4, troubleshooting table) |
| `.taskfiles/talos/Taskfile.yaml` | Added `talos:wait-maintenance` task |
| `.taskfiles/bootstrap/Taskfile.yaml` | `flux-secret` task: `cmd` → `cmds` + `flux reconcile`; added `flux` precondition |
| `scripts/flux-secret.sh` | Removed `local` from `tmp_identity`, `tmp_pub`, `tmp_known_hosts` declarations |
| `ROADMAP.md` | Created — pending work items in priority/dependency order |

### Decisions made
- `nc -z -w 3 <ip> 50000` over `talosctl version --insecure` for maintenance mode detection — `talosctl version` returns a gRPC "not implemented" error in maintenance mode (non-zero exit), making it useless as a readiness signal; port 50000 being open is the correct proxy for "node will accept `apply-config --insecure`"
- `silent: true` on `wait-maintenance` suppresses go-task's command echo; `>/dev/null 2>&1` on the `nc` call suppresses its per-connection success message — both needed for clean output
- Flux reconcile belongs in the Taskfile (not in `flux-secret.sh`) — the script owns secret lifecycle, the task owns workflow orchestration; adding `flux` as a dependency to the script would be a layering violation

### Learned / noted
- Flux's source-controller caches a "secret not found" state from before the secret was created; it does not immediately re-check on secret creation — `flux reconcile source git` forces an instant retry rather than waiting up to 5 minutes for the next poll
- `trap cleanup EXIT` fires at *script* exit, not *function* return — `local` variables declared inside the function are out of scope by that point; with `set -u` active, referencing them is fatal (`unbound variable`). Fix: drop `local` for any variable the `trap` handler references
- `talosctl bootstrap` reliably returns `grpc: the client connection is closing` on the first attempt because the node restarts after receiving its machine config; the `until … do sleep 10; done` wrapper in the task handles this correctly — it is not an error

---

## 2026-05-06 — `devcontainer-secret-management`

### What we did
- Created `scripts/flux-secret.sh` — automates step 12a of the bootstrap workflow: fetches the Flux SSH deploy key from 1Password via `op read` and creates the `flux-system` Kubernetes secret
- Added `bootstrap:flux-secret` task to `.taskfiles/bootstrap/Taskfile.yaml`
- Discussed 1Password CLI authentication options for a WSL2 devcontainer: Windows named pipe (not mountable in Docker), service account token via `OP_SERVICE_ACCOUNT_TOKEN`, and manual `op account add`
- Recommended service account token via `${localEnv:OP_SERVICE_ACCOUNT_TOKEN}` in `devcontainer.json` (stateless, survives rebuilds, no socket plumbing)

### Files created / modified
| File | Change |
|------|--------|
| `scripts/flux-secret.sh` | Created — `setup` / `verify` subcommands; fetches key from 1Password, generates `known_hosts` via `ssh-keyscan`, creates secret idempotently |
| `.taskfiles/bootstrap/Taskfile.yaml` | Added `flux-secret` task (`bootstrap:flux-secret`) |

### Decisions made
- `setup` checks secret existence *before* creating temp files or fetching from 1Password — avoids wasted network calls on a no-op skip, and avoids `unbound variable` crash at script exit when `trap cleanup EXIT` fires after `local` variables go out of scope
- `known_hosts` is generated at runtime via `ssh-keyscan -H github.com` (not read from disk) — `-H` hashes the hostname, matching Flux's expected format; avoids relying on a stale committed file
- Default vault `homelab`, default item `flux-deploy-key`; overridable via `--vault`/`--item` flags (direct) or `OP_VAULT`/`OP_ITEM` env vars (required path when using `task`)
- `--force` replaces an existing secret via delete + recreate (not patch) — a brief window exists where the secret is absent; acceptable on a home lab with a 5-minute Flux poll interval

### Learned / noted
- `trap` in bash is global to the shell process, not scoped to the function that sets it — a trap set inside a function fires at *script* exit, by which point `local` variables from that function are gone; with `set -u`, referencing them is fatal
- `\n` inside a double-quoted string is two literal characters when passed to `printf "%s"` — use `$'\n'` (ANSI-C quoting) to embed a real newline, or `printf "%b"` to interpret escape sequences
- The Windows 1Password app uses a named pipe (not a Unix socket) for CLI integration — named pipes cannot be bind-mounted into Docker containers; the Unix socket path documented for macOS does not apply on Windows
- Service account token (`OP_SERVICE_ACCOUNT_TOKEN`) is the practical choice for devcontainer authentication: stateless, no signin required, vault-scoped access

---

## 2026-05-06 — `mcp-server-rbac-scripts`

### What we did
- Read the `kubernetes-mcp-server` getting-started docs (Kubernetes setup + Claude Code integration)
- Created the `mcp` namespace and `mcp-viewer` ServiceAccount imperatively (one-time cluster state)
- Created `ClusterRoleBinding mcp-viewer-crb` binding the built-in `view` ClusterRole cluster-wide
- Minted a service account token and built `~/.kube/mcp-viewer.kubeconfig`
- Created `scripts/mcp.sh` — a single script with three subcommands (`setup`, `cleanup`, `renew-token`) that codifies all of the above so the operations are repeatable
- Connected the `kubernetes-mcp-server` MCP tool to Claude Code via `claude mcp add-json` using the dedicated kubeconfig
- Verified the MCP connection by listing cluster namespaces through the tool

### Files created / modified
| File | Change |
|------|--------|
| `scripts/mcp.sh` | Created — `setup` / `cleanup` / `renew-token` subcommands for MCP ServiceAccount lifecycle |

### Decisions made
- Single script with subcommands (mirrors `bootstrap.sh` pattern) rather than three separate files
- Default token duration is **8h** (practical for a work day; overridable per-invocation, e.g. `./scripts/mcp.sh renew-token 24h`)
- `setup` is fully idempotent — re-running on an existing cluster skips already-present resources and issues a fresh token
- RBAC uses the built-in `view` ClusterRole cluster-wide (Option A from the docs) — appropriate for a read-only observability tool; no custom ClusterRole needed
- Kubeconfig is written to `~/.kube/mcp-viewer.kubeconfig` (separate from the admin kubeconfig, scoped credentials)

### Learned / noted
- `kubectl create token` duration format (`8h`) uses Go's `time.Duration` syntax — GNU `date -d` requires `8 hours`; a `sed` transform bridges the two in the expiry display
- The `mcp` namespace, ServiceAccount, and ClusterRoleBinding were created imperatively and are **not** currently managed by Flux; `scripts/mcp.sh setup` serves as the source of truth for reproducing them

---

## 2026-05-06 — `flux-ssh-secret-setup`

### What we did
- Diagnosed and resolved Flux failing to reconcile the private GitHub repo
- Fixed three incorrect values in `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml`:
  - URL: HTTPS → SSH (`ssh://git@github.com/qnimbus/home-lab`)
  - Secret reference: `secretRef.name` → `pullSecret` (correct FluxInstance CRD field name)
  - Ref: `main` → `refs/heads/main` (FluxInstance `ref` must be a full Git ref path, not a branch shortname)
  - Added missing `path: ./kubernetes/flux/cluster` and `interval: 5m0s`
- Created the `flux-system` SSH deploy key secret imperatively in the cluster (`identity`, `identity.pub`, `known_hosts`)
- Patched the live `FluxInstance` directly to propagate `pullSecret` and correct ref without waiting for a Helmfile re-run
- Confirmed Flux is fully operational: `GitRepository READY`, `cluster-meta` and `cluster-apps` kustomizations applying

### Files created / modified
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` | Fixed URL, ref, path, interval; replaced `secretRef` with `pullSecret` |

### Decisions made
- SSH deploy key (`flux-deploy-key`) created with `ssh-keygen -t ed25519`; public key added as read-only GitHub deploy key; private key stored in `flux-system` Kubernetes secret and backed up to 1Password alongside `age.key`
- The `flux-system` SSH secret must be created imperatively during bootstrap — this is the one permanent exception to GitOps; all other cluster state goes through Git
- Bootstrap step 13a added to workflow: create `flux-system` SSH secret immediately after `helmfile sync`, before `git push`
- `helmfile sync` is the correct mechanism to update bootstrap-layer components (not `kubectl apply`)

### Learned / noted
- The `flux-instance` Helm chart (v0.23.0) does **not** expose all `FluxInstance` CRD fields as Helm values — `secretRef` is silently dropped; the correct values key is `pullSecret` (a plain string, not an object with a `name` key)
- The `FluxInstance` CRD `spec.sync.ref` expects a full Git ref (`refs/heads/main`), not a branch shortname; shortname produces `unable to resolve ref 'main' to a specific commit`
- `KUBECONFIG=$(pwd)/kubeconfig` must be exported in every new shell session; add to devcontainer env to avoid repeated manual export

---

## 2026-05-06 — `add-sops-plaintext-hook`

### What we did
- Added a Claude Code `PreToolUse` hook that blocks any `git add` or `git commit` command if a `*.sops.yaml` file involved is not SOPS-encrypted
- Created `.claude/hooks/check-sops.sh` — collects at-risk sops files, checks each for the `^sops:` root-level YAML key (canonical SOPS encryption marker), and emits `{"continue":false}` to block the command if plaintext is found
- Created `.claude/settings.json` — wires the script as a `PreToolUse` / `Bash` hook with a `"Checking SOPS encryption..."` status message

### Files created / modified
| File | Change |
|------|--------|
| `.claude/hooks/check-sops.sh` | Created — SOPS plaintext guard script |
| `.claude/settings.json` | Created — project-level Claude Code hook config |

### Decisions made
- Hook lives in `.claude/settings.json` (project-level) rather than `~/.claude/settings.json` (user-level) so it is scoped to this repo
- Detection uses `grep -q '^sops:'` — checks for the root-level `sops:` metadata block SOPS injects into every encrypted file, regardless of backend (age, KMS, PGP) or mode (`mac_only_encrypted`)
- Hook handles three `git add` patterns: explicit file args, broad adds (`git add .` / `git add -A`) via `git diff --name-only` + `git ls-files --others`, and `git commit` via `git diff --cached --name-only`

### Learned / noted
- `.claude/` is currently in `.gitignore` — the hook and settings exist only in the devcontainer and are not shared via Git. To make the guard apply for all contributors, remove `.claude/` from `.gitignore` (keeping `settings.local.json` gitignored separately)
- A new Claude Code session must open `/hooks` or restart to pick up a newly created `settings.json`

---

## 2026-05-06 — `setup-sops-age-key-devcontainer`

### What we did
- Analysed the full project structure, including current `talos/`, `scripts/`, `.devcontainer/`, and the archived cluster in `.archive/`
- Created `CLAUDE.md` as the project's primary self-documentation and Claude Code guidance file

### Files created / modified
| File | Change |
|------|--------|
| `CLAUDE.md` | Created — repo layout, toolchain, hardware, secrets strategy, bootstrap workflow, GitOps conventions, status table, working rules |
| `.devcontainer/devcontainer.json` | Added `remoteEnv` block setting `SOPS_AGE_KEY_FILE=${containerWorkspaceFolder}/age.key` |

### Decisions made
- `SOPS_AGE_KEY_FILE` is set via `devcontainer.json` `remoteEnv` (not `postCreateCommand.sh` or `.mise.toml`) so it is available to every terminal and VS Code process from container startup, before any shell profile or mise activation runs
- Two-tier secrets strategy documented: SOPS+age for Talos secrets, ESO+1Password Connect for application secrets

### Learned / noted
- The VS Code SOPS extension already receives the key path via `"sops.defaults.ageKeyFile": "age.key"` in devcontainer settings; `remoteEnv` completes coverage for CLI tooling
- `${containerWorkspaceFolder}` is a devcontainer built-in variable that resolves to the workspace root — prefer it over hardcoded paths in `devcontainer.json`
