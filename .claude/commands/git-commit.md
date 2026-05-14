Stage and commit changes following this repository's git conventions.

## Workflow

Run the following in parallel:
- `git status` — identify staged and unstaged files
- `git diff --cached` — inspect every staged change
- `git log --oneline -5` — read recent commit messages to match the style in use

If nothing is staged, report that and stop — do not commit an empty changeset.

Check for upstream drift before committing:
- Run `git fetch --dry-run` to detect remote changes
- If remote changes exist, report them and ask the user whether to pull before proceeding

Draft a commit message:
- Follow the Conventional Commits specification: `<type>(<optional-scope>): <subject>`
- Common types: `feat`, `fix`, `chore`, `docs`, `refactor`, `ci`
- Subject line: imperative mood, ≤72 chars, lowercase after the colon
- Match the tone and granularity of recent commits in `git log`
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

After committing:
- Run `git status` to confirm success
- Report the short commit hash and subject line
- Do **not** push — pushing requires explicit user confirmation every time, and must never be done automatically
