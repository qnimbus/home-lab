Analyse unstaged changes and selectively stage files based on session context and safety rules. Intended for use before /git-commit when nothing is staged yet.

## Workflow

### Step 1 — Survey the working tree

Run in parallel:
- `git status --short` — full list of modified, untracked, and deleted files
- `git diff` — full diff of every unstaged change in tracked files

If the staging area is already non-empty, report that and stop — this command is for the case where nothing is staged yet. Tell the user to run /git-commit instead, or ask whether they want to stage additional files on top of what is already staged.

### Step 2 — Cross-reference with session context

Review what was worked on during this conversation: which files were read, edited, or created. Use that knowledge to classify every changed file into one of three buckets:

- **Stage** — the file was intentionally modified as part of this session's work
- **Skip** — the file changed but appears unrelated to the current session (e.g. an editor artefact, a file the session only read but did not edit)
- **Warn** — the file requires explicit user decision before staging (see safety rules below)

When in doubt, put the file in **Warn** rather than silently staging it.

### Step 3 — Apply safety rules (mandatory — never bypass)

Immediately place any file matching these criteria into **Warn** regardless of session context:

- `*.sops.yaml` — encrypted secrets; only stage if the session explicitly encrypted and verified the file
- `talos/clusterconfig/*` — generated files; must never be staged directly (edit `talconfig.yaml` and re-run `genconfig` instead)
- Any file containing plaintext that looks like a token, password, private key, or API secret
- `.env`, `*.key`, `*.pem`, `age.key` — credential files that must never be committed
- Files the session did not touch at all

For partial changes: if a file has both session-related and unrelated hunks, flag it in **Warn** and tell the user to stage it with `git add -p <file>` so they can select individual hunks interactively.

### Step 4 — Stage and report

For every **Stage** file, run `git add <file>` by explicit filename — never use `git add .` or `git add -A`.

After staging, report a clear three-section summary:

```
Staged:
  <list of files staged and why>

Skipped (not session-related):
  <list of files left unstaged and why>

Needs your decision:
  <list of files in Warn bucket with a one-line reason each>
```

Do **not** commit — staging is this command's only responsibility. Tell the user to run /git-commit when ready.
