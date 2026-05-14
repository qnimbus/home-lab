Close the current session: complete the open stub in `docs/SESSIONS.md`, update the CLAUDE.md session log table with a real summary, and trim the table to the 8 most recent entries.

## Workflow

### Step 1 — Locate the open stub

Read the first 30 lines of `docs/SESSIONS.md`. Find the most recent session entry (immediately after the first `---`) that has `### Goal` but **no** `### What we did`. Extract the slug and date from the `## YYYY-MM-DD — \`slug\`` heading.

If no open stub exists, report that and stop.

### Step 2 — Synthesise session content

Using your knowledge of this conversation, draft three sections:

**What we did** — a bullet list of actual work done. Be concrete: tools used, what was discovered, what was fixed or built. Match the density and style of existing entries in `docs/SESSIONS.md`.

**Files changed** — a two-column markdown table (`File | Change`) listing every file that was edited, created, or deleted during the session. Paths in backticks. Changes as brief past-tense phrases.

**Key decisions** — bullet list of non-obvious choices and their rationale. Omit this section entirely if every decision was routine (no surprising constraints, workarounds, or tradeoffs).

To supplement memory, run `git log --oneline -10` to see commits made during the session.

### Step 3 — Complete the stub in `docs/SESSIONS.md`

Replace the open stub with the completed record. The stub runs from the `## YYYY-MM-DD` heading through (and including) the next `---` separator. Use the Edit tool with the entire stub block as `old_string`.

The completed block must follow this structure exactly:

```markdown
## YYYY-MM-DD — `slug`

### Goal
<original goal text — keep verbatim>

### What we did
- <bullet>

### Files changed
| File | Change |
|------|--------|
| `path` | description |

### Key decisions
- <bullet>

---
```

Omit `### Key decisions` entirely if there are none.

### Step 4 — Update the CLAUDE.md session log table

Find the row for this session in CLAUDE.md (match on the slug). Replace its summary column with a real one-liner:
- ≤120 characters
- Past tense, dense, no trailing period
- Same style as existing rows (look at the surrounding entries for tone)

The placeholder may be `_in progress_` (if opened via `/session-open`) or an earlier placeholder — update either way.

### Step 5 — Trim the table to 8 entries

Count all data rows in the CLAUDE.md session table — rows that begin with `> |` but are **not** the header row (`> | Date |...`) or the separator row (`> |---`). If the count exceeds 8, remove all rows beyond position 8 (oldest rows, at the bottom of the table). The full history is preserved in `docs/SESSIONS.md`.

Use the Edit tool to remove the excess rows in a single operation — construct `old_string` from the 9th data row through the last data row.

### Step 6 — Report

Output a two-line summary:
- `Session \`slug\` closed.`
- `Summary: <the one-liner used>`
- `Table: N entries remaining.`
