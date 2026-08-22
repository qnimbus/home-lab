Stage and commit changes following this repository's git conventions — analyses unstaged changes, decides what belongs in the commit, stages it, then commits. Merges the former `/git-stage` and `/git-commit` into a single command.

## Step 0 — Authorization gate (mandatory — never bypass)

Before doing anything else, determine why this command is running:

- **User-invoked** — the user's message this turn typed `/git-commit`, or otherwise explicitly asked to stage/commit right now. Skip to Step 1.
- **Claude-invoked** — Claude is running this command on its own initiative, without an explicit ask this turn (e.g. tidying up before a task or session ends). This is only permitted when **all three** of the following hold:
  1. The working directory is a git worktree Claude itself entered — its path contains `.claude/worktrees/` — not the primary repo checkout.
  2. `git branch --show-current` is that worktree's own feature branch, never `main` (or the repo's default branch).
  3. **The worktree/branch was actually created for the current task** — not a pre-existing worktree the session merely happened to be launched into (a background job's working directory can be pinned at launch to a worktree left over from earlier, unrelated work). Check this explicitly: does the branch name, and the topic of `git log --oneline -5` (already pulled in Step 1), match what this conversation has actually been doing? A worktree named after — and with a commit history about — a different feature/task fails this condition even though 1 and 2 hold.

  Check all three explicitly (`pwd` / `git rev-parse --show-toplevel`, `git branch --show-current`, and the branch-name/log-topic comparison) before proceeding. If any check fails — primary checkout, currently on `main`, or a topically mismatched worktree — **stop and ask the user** whether to commit here anyway or set up a fresh worktree/branch for this task first. Do not rationalize around this ("the change is small", "the task is done", "it's already isolated in *a* worktree" are never sufficient on their own).

## Step 1 — Survey the working tree

Run in parallel:
- `git status --short` — full list of staged, modified, and untracked files
- `git diff` — unstaged changes in tracked files
- `git diff --cached` — anything already staged
- `git log --oneline -5` — recent commit messages, to match the style in use

## Step 2 — Cross-reference with session context

Review what was worked on during this conversation: which files were read, edited, or created. Classify every changed file (staged or not) into one of three buckets:

- **Stage** — the file was intentionally modified as part of this session's work
- **Skip** — the file changed but appears unrelated to the current session (e.g. an editor artefact, a file the session only read but did not edit)
- **Warn** — the file requires explicit user decision before staging (see Step 3)

When in doubt, put the file in **Warn** rather than silently staging it.

## Step 3 — Apply safety rules (mandatory — never bypass)

Immediately place any file matching these criteria into **Warn** regardless of session context:

- `*.sops.yaml` — encrypted secrets; only stage if the session explicitly encrypted and verified the file
- `talos/clusterconfig/*` — generated files; must never be staged directly (edit `talconfig.yaml` and re-run `genconfig` instead)
- Any file containing plaintext that looks like a token, password, private key, or API secret
- `.env`, `*.key`, `*.pem`, `age.key` — credential files that must never be committed
- Files the session did not touch at all

For partial changes: if a file has both session-related and unrelated hunks, flag it in **Warn** and tell the user to stage it with `git add -p <file>` so they can select individual hunks interactively.

## Step 4 — Stage and confirm scope

For every **Stage** file, run `git add <file>` by explicit filename — never use `git add .` or `git add -A`.

Report the staging outcome:

```
Staged:
  <files staged this run and why>

Already staged (from before this run):
  <files, if any>

Skipped (not session-related):
  <files left unstaged and why>

Needs your decision:
  <Warn-bucket files with a one-line reason each>
```

If nothing ends up staged (nothing new this run and nothing pre-existing), report that and stop — do not commit an empty changeset. If the **Needs your decision** list is non-empty, surface it clearly even though staging otherwise succeeded — those files still need the user's call.

## Step 5 — Check upstream drift

Run `git fetch --dry-run`. If remote changes exist, report them and ask the user whether to pull before proceeding.

## Step 6 — Commit

Draft a commit message:
- Follow the Conventional Commits specification: `<type>(<optional-scope>): <subject>`
- Common types: `feat`, `fix`, `chore`, `docs`, `refactor`, `ci`
- Subject line: imperative mood, ≤72 chars, lowercase after the colon
- Match the tone and granularity of recent commits from Step 1
- Body: include only if the diff contains a non-obvious decision or constraint that the subject line cannot capture — omit otherwise

Commit constraints (mandatory — never deviate):
- Do **not** add a `Co-Authored-By:` trailer
- Do **not** use `--no-verify` or any flag that bypasses hooks
- Pass the commit message via a heredoc to preserve formatting:
  ```
  git commit -m "$(cat <<'EOF'
  <message>
  EOF
  )"
  ```

## Step 7 — Report

- Run `git status` to confirm success
- Report the short commit hash and subject line
- Do **not** push — pushing always requires explicit user confirmation, with no exception, even for a Claude-invoked run authorized under Step 0.
