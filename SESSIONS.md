# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

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
