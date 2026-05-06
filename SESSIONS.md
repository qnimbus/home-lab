# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

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
