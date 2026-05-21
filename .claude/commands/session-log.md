Retroactively create and close a complete session record for work already done — use when you forgot to run `/session-open` before starting work.

## Input

Optional argument: a session slug or a short description of the work done.
- Slug (no spaces, kebab-case): use as-is.
- Description (contains spaces): derive a kebab-case slug from it.
- Nothing provided: infer the slug from git log and conversation context.

## Workflow

### Step 1 — Guard: check for an already-open stub

Read the first 30 lines of `docs/SESSIONS.md`. If the first session entry (immediately after the opening `---`) contains `### Goal` but **not** `### What we did`, an unclosed stub already exists. Report the slug of the open stub and stop — run `/session-close` to close it first.

### Step 2 — Determine date, slug, and goal

Run the following commands in parallel to build a full picture of the session's changes:

```sh
date +%Y-%m-%d
git status --short
git diff --stat HEAD          # unstaged + staged vs last commit
git diff --cached --stat      # staged only (subset of above, for clarity)
git log --oneline -15         # recent commits — may include pre-session work
```

**Important**: `git log` may contain commits from a previous session or unrelated work. Use the **conversation context** as the authoritative filter — only attribute commits and changes to this session if they were discussed or produced in this conversation.

Determine the slug from the argument, or infer it from the conversation context and the changes identified above.
Draft a one-sentence goal that captures what was accomplished.

### Step 3 — Synthesise session content

The **conversation context is the primary source of truth**. Git output supplements it — use `git status`, `git diff --name-only HEAD`, and `git log` to enumerate files and commits, but always cross-reference against the conversation to exclude unrelated changes.

For uncommitted work, run:
```sh
git diff --name-only HEAD       # all modified files not yet committed
git diff --cached --name-only   # staged-only files
```

Draft three sections:

**What we did** — a bullet list of actual work done. Be concrete: tools used, what was discovered, what was fixed or built. Match the density and style of existing entries in `docs/SESSIONS.md`.

**Files changed** — a two-column markdown table (`File | Change`) listing every file that was edited, created, or deleted **as part of this session** (committed, staged, or unstaged). Paths in backticks. Changes as brief past-tense phrases. Exclude files modified in unrelated prior commits.

**Key decisions** — bullet list of non-obvious choices and their rationale. Omit this section entirely if every decision was routine (no surprising constraints, workarounds, or tradeoffs).

### Step 4 — Insert complete record into `docs/SESSIONS.md`

Insert a complete (not stub) block between the opening `---` separator (line 5) and the first existing session entry. Use the Edit tool with the exact `---\n\n## ` boundary as `old_string` to anchor the insertion:

```
---

## YYYY-MM-DD — `slug`

### Goal
<one-sentence goal>

### What we did
- <bullet>

### Files changed
| File | Change |
|------|--------|
| `path` | description |

### Key decisions
- <bullet>

---

## 
```

→ replaced with the new complete record prepended before the existing `## `.

Omit `### Key decisions` entirely if there are none.

### Step 5 — Prepend row to the CLAUDE.md session log table

Find the separator line `> |------|---------|---------|` in CLAUDE.md. Using the Edit tool, replace the separator + first existing data row with the separator + new row + first existing data row:

```
> | YYYY-MM-DD | `slug` | <one-liner summary> |
```

The new row must use the `> ` blockquote prefix. The summary must be:
- ≤120 characters
- Past tense, dense, no trailing period
- Same style as existing rows (look at the surrounding entries for tone)

### Step 6 — Trim the table to 8 entries

Count all data rows in the CLAUDE.md session table — rows that begin with `> |` but are **not** the header row (`> | Date |...`) or the separator row (`> |---`). If the count exceeds 8, remove all rows beyond position 8 (oldest rows, at the bottom of the table). The full history is preserved in `docs/SESSIONS.md`.

Use the Edit tool to remove the excess rows in a single operation — construct `old_string` from the 9th data row through the last data row.

### Step 7 — Report

Output exactly three lines:
```
Session `slug` recorded (YYYY-MM-DD).
Summary: <the one-liner used>
Table: N entries remaining.
```
