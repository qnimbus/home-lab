Open a new session: prepend a stub to `docs/SESSIONS.md` and add a placeholder row to the CLAUDE.md session log table.

## Input

Optional argument: a session slug or a short description of planned work.
- Slug (no spaces, kebab-case): use as-is.
- Description (contains spaces): derive a kebab-case slug from it.
- Nothing provided: infer the slug from the current conversation context.

## Workflow

### Step 1 — Determine date and slug

Run `date +%Y-%m-%d` to get today's date.
Determine the slug from the argument or conversation context.
Draft a one-sentence goal from the argument or context.

### Step 2 — Guard: check for an already-open stub

Read the first 25 lines of `docs/SESSIONS.md`. If the first session entry (immediately after the opening `---`) contains `### Goal` but **not** `### What we did`, an unclosed stub already exists. Report the slug of the open stub and stop — do not nest stubs.

### Step 3 — Insert stub into `docs/SESSIONS.md`

Insert the following block between the opening `---` separator (line 5) and the first existing session entry. Use the Edit tool with the exact `---\n\n## ` boundary as `old_string` to anchor the insertion:

```
---

## YYYY-MM-DD — `slug`

### Goal
<one-sentence goal>

---

## 
```

→ replaced with the new stub prepended before the existing `## `.

### Step 4 — Prepend row to the CLAUDE.md session log table

Find the separator line `> |------|---------|---------|` in CLAUDE.md. Using the Edit tool, replace the separator + first existing data row with the separator + new row + first existing data row:

```
> | YYYY-MM-DD | `slug` | _in progress_ |
```

The new row must use the `> ` blockquote prefix. Insert it immediately after the separator, before the existing first data row.

### Step 5 — Report

Output exactly three lines:
```
Session `slug` opened (YYYY-MM-DD).
Run: /rename slug
Then run /session-close when done.
```
