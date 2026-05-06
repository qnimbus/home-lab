# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

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
