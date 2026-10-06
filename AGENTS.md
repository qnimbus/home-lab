@.agents/instructions/sorting.instructions.md
@.agents/instructions/flux-kustomization.instructions.md
@.agents/instructions/helm-sources.instructions.md
@.agents/instructions/helm-crds.instructions.md
@.agents/instructions/helm-values.instructions.md
@.agents/instructions/external-secrets.instructions.md
@.agents/instructions/renovate.instructions.md
@.agents/instructions/yaml-schemas.instructions.md
@.agents/instructions/dns-naming.instructions.md
@.agents/instructions/timezones.instructions.md

Reusable task skills (add-app, add-docker-app, ...) live in `.agents/skills/`; Claude Code discovers them through the `.claude/skills` symlink.

When a recurring pattern, inconsistency, or divergence from a reference repo (e.g. bykaj/home-ops) comes up during work, flag it and propose whether it should be captured as a documented convention (or explicitly rejected) rather than left implicit.

## Git workflow

- **Start every new task in a new Claude Code worktree** (`.claude/worktrees/<name>`, on its own branch: the `EnterWorktree` tool, or `claude --worktree <name>`). This goes for any task that changes files. Don't work in the main checkout, and don't reuse a worktree from an earlier task.
- **Rebase the worktree's branch on `main` whenever required:** when `main` has moved since the branch was created, before handing the work over, and before anything is merged. Rebase, don't merge `main` into the branch.
- **Committing in that worktree never needs consent.** Commit as the work progresses. Anywhere else (the main checkout, a worktree you didn't create for the task), ask first.
- **Never push to `main` without explicit consent.** Pushing to `main` is the deploy: Flux and doco-cd act on it. That covers every way of getting commits onto the remote `main`, merging a PR included. Never run `git push` autonomously: stop after committing and let the user push themselves, or explicitly ask and wait for a yes.
