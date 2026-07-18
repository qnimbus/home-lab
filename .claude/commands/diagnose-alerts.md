Diagnose alerts that are currently firing, pending, or recently fired — cross-reference live Alertmanager/Prometheus state against this repo's PrometheusRules, silence-operator Silences, and past session history to determine what's real, what's already known, and what needs action.

## Input

Optional argument: an alertname (e.g. `CephNodeDiskspaceWarning`) or a rough keyword (e.g. `ceph`, `thermal`).
- Named alert: diagnose only that alert.
- Nothing provided: survey everything currently firing or pending, then also check for alerts that fired and resolved within the last 24h (see Step 2b) so short-lived flaps aren't missed just because Alertmanager's live view is now clean.

## Endpoints

Both hostnames are internal (`envoy-internal`) and directly reachable via `curl -sk` from this devcontainer — no port-forward needed. Don't hardcode the domain; read it live so this survives a `DOMAIN_CLUSTER` change:

```sh
PROM=https://$(KUBECONFIG=$(pwd)/kubeconfig kubectl get httproute kube-prometheus-stack-prometheus -n observability -o jsonpath='{.spec.hostnames[0]}')
AM=https://$(KUBECONFIG=$(pwd)/kubeconfig kubectl get httproute kube-prometheus-stack-alertmanager -n observability -o jsonpath='{.spec.hostnames[0]}')
```

Use `curl -sk` (self-signed/internal cert — `-k` is expected here, not a shortcut to excuse elsewhere).

## Workflow

### Step 1 — Confirm scope

If an alertname/keyword was given, scope everything below to matches on `labels.alertname` (exact or substring). Otherwise scope is "all non-Watchdog alerts" — `Watchdog` is the intentional always-firing dead-man's-switch rule (`vector(1)`, severity `none`); mention it only if it is *not* firing, since that itself means the alerting pipeline is broken.

### Step 2 — Pull live state

Run in parallel:

**2a. Current Alertmanager state** — firing/suppressed/inhibited, as Alertmanager sees it right now:
```sh
curl -sk "$AM/api/v2/alerts?active=true&silenced=true&inhibited=true"
```
Each entry has `status.state` (`active`/`suppressed`), `status.silencedBy`/`inhibitedBy` (fingerprints), `labels`, `annotations`, `startsAt`, `generatorURL`.

**2b. Recently-fired-but-now-resolved** — Alertmanager itself keeps no history beyond current state, so a flap that resolved 10 minutes ago won't show in 2a. Query Prometheus's `ALERTS` timeseries over a lookback window instead:
```sh
curl -sk "$PROM/api/v1/query_range?query=ALERTS%7Balertstate%3D%22firing%22%7D&start=$(date -d '24 hours ago' +%s)&end=$(date +%s)&step=60s"
```
Any alertname appearing here but absent from 2a fired and resolved within the window — worth reporting even though it's not currently active.

**2c. Rule state** — pending alerts still inside their `for:` window (not yet visible to Alertmanager at all), plus evaluation health:
```sh
curl -sk "$PROM/api/v1/rules"
```
Filter for `state: "pending"` or `state: "firing"`, and separately flag any rule group with a non-empty `lastError` — a broken `expr` is itself a silent alerting gap.

**2d. Active silences** (only if 2a shows anything `suppressed`):
```sh
curl -sk "$AM/api/v2/silences"
```
Match `status.silencedBy` fingerprints from 2a against this list to get the human `matchers` and `comment` for why it's suppressed.

### Step 3 — Cross-reference against the repo

For each distinct alertname surfaced in Step 2, gather repo context in parallel:

- **Rule definition**: `grep -rn "alert: <name>" kubernetes/apps/` — most custom rules live in
  `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/`, but Ceph and other
  operators ship their own bundled `PrometheusRule` objects too (search all of `kubernetes/apps/`,
  not just observability). If found, read the full rule block **including surrounding comments** —
  this repo deliberately keeps root-cause history and threshold rationale as inline YAML comments
  (see `hardware-temps.yaml`'s hwmon-staleness rule for the pattern), so the comment often already
  answers "why does this alert exist and what does firing actually mean." If not found in-repo,
  it's a default rule bundled by the `kube-prometheus-stack` chart itself (or a Rook/CNPG chart) —
  note that and rely on the live `annotations` from Step 2 instead.

- **Known-silence check**: `grep -rln "<name>" kubernetes/apps/observability/silence-operator/silences/`
  — even if the alert isn't currently silenced (e.g. it's a new label combination the existing
  `Silence` matcher doesn't cover), an existing `Silence` file for the same alertname is strong
  evidence this is a known, already-triaged condition. Read the file's comment block for the
  accepted root cause.

- **Past incidents**: grep (never read in full — see CLAUDE.md) `docs/QA.md`,
  `docs/SESSIONS.md`, and `docs/SESSIONS-ARCHIVE.md` for the alertname. Prior sessions frequently
  root-caused exactly this alert (e.g. `NodeHwmonTextfileStale`, the X520-fallback packet-drop
  alerts) — don't re-diagnose from scratch if it's already been solved once.

- **Notification routing**: check `kubernetes/apps/observability/kube-prometheus-stack/app/alertmanagerconfig.yaml`'s
  `route.routes` — `severity: critical` → `pushover-critical` (emergency priority, repeats every
  60s for up to 1h until acknowledged); `severity: warning|error` → `pushover` (normal priority,
  once). State plainly whether this alert would have paged the user and at what urgency, since
  `severity` in the rule's `labels` is what decides that, not the alert's apparent real-world
  importance.

### Step 4 — Characterize firing alerts (skip for fully-silenced/known-benign ones)

For alerts that are actively firing/pending and not already covered by an existing accepted
`Silence`, query the rule's own `expr` via `query_range` (window: `for:` duration × 4, or 1h if
unknown) to see the actual trend — climbing, flat, or already reverting. This distinguishes "brief
threshold graze, self-resolving" from "actively getting worse." Report the current value against
the threshold in the rule, not just "firing: yes/no."

If the alert points at something needing live pod/node investigation (crash loops, resource
exhaustion, network drops, node-layer symptoms) rather than a metrics/threshold question, say so
explicitly and suggest handing off to the `cluster-doctor` agent (or `talos-node-manager` for
Talos/OS-layer symptoms) — this command's job is triage (is it real, is it known, what's the
trend), not full incident response.

### Step 5 — Report

One block per distinct alert, ordered firing-and-unknown first, then firing-and-known, then
silenced/suppressed, then resolved-within-window (2b only):

```
### <AlertName>  [firing|pending|suppressed|resolved ~<when>]

**Severity:** critical|warning|... → pages via <receiver> at <priority>
**Source:** <repo file:line> | default rule (<chart>)
**Current state:** <value> vs threshold <expr summary>, trend <climbing/flat/reverting> over <window>
**Known?** <Silence file / QA.md line / session slug — or "no, new">
**Assessment:** <one or two sentences — what's actually happening>
**Recommendation:** <fix root cause / add a Silence following <example file>'s pattern / hand off to cluster-doctor / no action, working as intended>
```

Close with a one-line overall summary: how many alerts are genuinely new/unaddressed vs already
triaged/silenced/known-benign.

**Do not** create, edit, or apply any `Silence`, `PrometheusRule`, or other cluster resource as
part of this command — it diagnoses and recommends only. If the user wants a new `Silence` added,
that's a follow-up edit through the normal GitOps flow (edit the file, `/git-stage`, `/git-commit`
when explicitly asked).
