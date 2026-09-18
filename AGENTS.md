@.agents/instructions/sorting.instructions.md
@.agents/instructions/flux-kustomization.instructions.md
@.agents/instructions/helm-sources.instructions.md
@.agents/instructions/external-secrets.instructions.md
@.agents/instructions/renovate.instructions.md

Reusable task skills (add-app, add-docker-app, ...) live in `.agents/skills/`; Claude Code discovers them through the `.claude/skills` symlink.

When a recurring pattern, inconsistency, or divergence from a reference repo (e.g. bykaj/home-ops) comes up during work, flag it and propose whether it should be captured as a documented convention (or explicitly rejected) rather than left implicit.

Never run `git push` autonomously in this repo. Always stop after committing (or after preparing changes to commit) and let the user push themselves, or explicitly ask and wait for a yes before pushing.
