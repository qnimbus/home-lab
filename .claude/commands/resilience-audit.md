Audit a cluster component's failure modes using a standard FMEA schema — for each plausible way it can fail, record blast radius, detection, existing mitigation, recovery procedure, and whether that recovery has actually been tested. Regenerates/updates `docs/RESILIENCE-AUDIT.md`. Use when asked to assess the impact of a component going down, catalog failure modes, evaluate disaster-recovery readiness, or answer "what happens if X fails".

## Input

Optional argument: a component or domain name (e.g. `rook-ceph`, `flux`, `cloudnative-pg`, `network`).
- Named component: audit only that component, adding/refreshing its section in `docs/RESILIENCE-AUDIT.md`.
- `full`: audit every component listed in the Backlog section, one at a time.
- Nothing provided: read the Backlog section of `docs/RESILIENCE-AUDIT.md` and ask the user which component to start with — don't guess at cluster-wide scope.

## FMEA Schema

Every failure mode gets one row in a per-component table with these columns:

| Column | What goes here |
|---|---|
| Failure Mode | The specific way this fails — not a category. "Two OSDs down simultaneously, exceeding min_size" not "storage failure". |
| Blast Radius | What actually breaks, and — just as important — what *keeps working*. Name the specific apps/PVCs/consumers affected, not "the cluster". |
| Detection | How this would actually be noticed today: named alert rule, dashboard, or "nothing — silent until X". |
| Existing Mitigation | What's already in place that reduces likelihood or impact (replication factor, PDBs, redundant replicas, quorum size). "None" is a valid, important answer. |
| Recovery Procedure | The actual steps, or a link to where they live (`CLUSTER.md#anchor`, `QA.md#anchor`, `just <module> <recipe>`). Never re-type a procedure that's already documented elsewhere — link it. If no procedure exists, say so explicitly — don't invent one to fill the cell. |
| Tested | One of: **Drilled** (executed for real — cite the date/incident/session), **Partial** (the general mechanism is exercised but not this specific scenario), **Untested** (theoretical only). Be honest — an untested "should work" is the whole point of this audit. |
| Severity | See heuristic below. |

### Severity heuristic

- **Critical** — broad/cluster-wide blast radius AND (no mitigation OR recovery is untested/undocumented). These are the findings that matter.
- **Warning** — mitigated (redundancy/automation exists) but recovery is untested, partially documented, or detection is weak.
- **Info** — mitigated, detected, and recovery is Drilled. Include these too — they're evidence the system works, not just a list of what's broken.

## Workflow

### Step 1 — Scope

Confirm which component this pass covers. Check `docs/RESILIENCE-AUDIT.md` for an existing section on it — if present, this is a refresh (Step 5 updates in place); if absent, this is a first pass (Step 5 appends a new section and removes it from the Backlog list).

### Step 2 — Discovery

Gather what actually exists for this component before inventing failure modes:
- Find its manifests under `kubernetes/apps/` — replica counts, `dependsOn`, StorageClass usage, PDBs, topology-spread/HA annotations.
- Grep `docs/CLUSTER.md`, `docs/ROADMAP.md`, and `docs/QA.md` for the component name — pull existing runbooks, drill records, and known incidents rather than re-deriving them.
- Check `ops/*/mod.just` for existing operational recipes (status checks, recovery commands).
- Grep `docs/SESSIONS.md` / `docs/SESSIONS-ARCHIVE.md` for past incidents involving this component (per CLAUDE.md: grep narrow, never read in full).

### Step 3 — Enumerate failure modes

Work through the categories below; not all apply to every component — use judgment:
- Loss of a single replica/instance/node hosting this component
- Simultaneous loss of multiple replicas (exceeding the component's redundancy factor)
- Network partition between this component's peers, or between it and its consumers
- Total/quorum loss (etcd, mon, leader-election — whichever applies)
- Bad upgrade / bad config change (Helm release failure, CRD mismatch)
- Capacity exhaustion (disk, memory, connection limits)
- Ungraceful power loss vs. the component's documented graceful-shutdown path (if one exists, note whether an *unplanned* equivalent is also covered)
- Upstream/external dependency outage (DNS, 1Password Connect, WAN, NTP)
- Silent data corruption or drift (not a crash — wrong state that isn't caught)

### Step 4 — Fill the table

One row per plausible failure mode found in Step 3. Cross-reference Step 2's findings — cite real alert names, real `just` recipes, real session slugs. Do not fabricate a recovery procedure that doesn't exist; an empty/gap cell is a valid and useful finding, not something to paper over.

### Step 5 — Write `docs/RESILIENCE-AUDIT.md`

- First-ever run: create the file using the structure in Step 6.
- New component: append a new `## <Component>` section before the Backlog section, remove it from the Backlog list.
- Refresh of an existing component: replace that section's table in place; update its "Last audited" line.
- Always update the top-level summary table (one row per audited component: component, worst severity found, tested status, open gap count).

### Step 6 — Document structure

```markdown
# Cluster Resilience Audit (FMEA) <!-- omit from toc -->

> **Living document, audit-generated** — regenerated per-component by the `resilience-audit` skill, not hand-maintained. Re-run a component's section after significant architecture changes to it.
> Last audited: **YYYY-MM-DD** · Components covered: N

## Contents <!-- omit from toc -->
...

## Summary

| Component | Worst Severity | Tested | Open Gaps |
|---|---|---|---|

## <Component Name>

_Last audited: YYYY-MM-DD_

<one-paragraph description of what it is and why it matters — don't repeat CLUSTER.md, link it>

| Failure Mode | Blast Radius | Detection | Existing Mitigation | Recovery Procedure | Tested | Severity |
|---|---|---|---|---|---|---|
...

## Backlog (not yet audited)

- component-name — one-line reason it matters / why it should be next
```

### Step 7 — Report

Output a short summary: which component(s) were audited, the count of Critical/Warning/Info findings, and the single most important gap found (if any Critical exists). Don't restate the full table — the user can read the file.

## Edge Cases

- **No existing runbook for a plausible failure mode**: this is the audit doing its job — record it as a Critical/Warning gap with "Recovery Procedure: none documented" rather than skipping the row.
- **Component has no redundancy by design** (e.g. a single-replica operator): don't flag single-instance loss as a gap if a restart/reschedule is sufficient recovery — only flag it if data loss or extended outage results.
- **Overlapping components** (e.g. a network failure affects both Ceph and etcd): document it once under the component most directly responsible, cross-link from the other's row rather than duplicating the analysis.
- **Don't duplicate CLUSTER.md/QA.md/ROADMAP.md** — this document's job is the *catalog and severity assessment*, not a second copy of runbooks that already exist. Link, don't paste.
