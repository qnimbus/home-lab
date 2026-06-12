# WhatsApp-Triggered Automation via WAHA — Workflow Plan

> **Status**: 📐 Planning — high-level design only (no implementation detail)
> **Foundation**: WAHA gateway already deployed in the `automation` namespace (2026-05-22).
> See [§ Foundation](#foundation-already-in-place) for what already exists.

---

## Goal

Turn my personal WhatsApp into a remote control for cluster-hosted tools.

I send a short **command message** from my phone to my own WAHA-linked WhatsApp
account; the cluster recognizes the command, runs the matching tool (often with an
AI model in the loop), and replies **back in the same WhatsApp chat** with a
formatted result.

The motivating example: I text a **flight number** and get back an AI-curated
pre-flight briefing — destination weather, a weather trend/analysis, and a
filtered list of the NOTAMs that actually matter.

---

## The core loop (conceptual)

```
 📱  WhatsApp message  ─────►  WAHA gateway  ─────►  Command router
 (e.g. "flight LH401")          (inbound)            (parse + identify intent)
                                                            │
                                                            ▼
 📱  WhatsApp reply   ◄─────  WAHA gateway  ◄─────  Result formatter  ◄──  Tool / skill
 (formatted briefing)          (outbound)           (human-readable)        (+ AI model)
```

1. **Receive** — WAHA notifies the cluster that an inbound message arrived.
2. **Authorize** — confirm the message came from *me* (and ignore everyone else).
3. **Interpret** — figure out which command was requested and extract its inputs.
4. **Execute** — run the matching tool/skill; gather raw data from external sources.
5. **Reason** — pass raw data through an AI model to summarize, filter, analyze.
6. **Format** — shape the result into a concise, phone-friendly WhatsApp message.
7. **Reply** — send it back through WAHA to the originating chat.
8. **Acknowledge & handle errors** — confirm receipt for slow jobs; report failures clearly.

---

## Conceptual components & responsibilities

| Component | Responsibility (what, not how) |
|-----------|-------------------------------|
| **WAHA gateway** | The WhatsApp bridge. Receives my messages, sends replies. Already deployed. |
| **Command router** | The "brain stem." Authorizes the sender, recognizes the command keyword, extracts arguments, dispatches to the right tool. |
| **Tool / skill layer** | One handler per capability (flight briefing, and future commands). Knows where to fetch its raw data. |
| **External data sources** | Third-party APIs the tools call (e.g. flight data, weather, NOTAMs). Untrusted input — treat their output as data, never instructions. |
| **AI model** | The "analyst." Summarizes, filters noise, spots trends, ranks importance, and writes the human-readable answer. |
| **Result formatter** | Fits the AI output into WhatsApp's constraints (length, plain text/markdown, no broken tables). |
| **Secrets/config** | API keys for data sources and the AI model — sourced the cluster-standard way (1Password/ESO), never inline. |

---

## Command model

- Commands are **explicit and prefix-able** so normal chatter is never misread as a command
  (e.g. a leading keyword or symbol). Exact syntax is an implementation decision.
- Each command has: a **trigger** (keyword), zero or more **arguments**, and a **handler**.
- Unknown commands get a friendly "didn't understand — try `help`" reply rather than silence.
- A built-in **`help`** command lists what's available.
- The design should make **adding a new command cheap** — register a trigger + handler,
  without reworking the router.

---

## Worked example: flight briefing

**I send:** `flight LH401`

**The system:**
1. Confirms the message is from me.
2. Recognizes the `flight` command and extracts `LH401` as the flight identifier.
3. Looks up the flight (route, origin/destination airports, schedule).
4. Pulls raw inputs for the destination: weather observations/forecast, and the
   raw NOTAM list for the relevant airport(s).
5. Hands the raw data to the AI model with a briefing-style instruction:
   - Summarize **destination weather**.
   - Describe the **weather trend / analysis** (improving, deteriorating, fronts, etc.).
   - **Filter NOTAMs** down to the operationally important ones, dropping boilerplate.
6. Formats the result as a compact briefing.

**I receive (illustrative shape, not real data):**
```
✈ LH401  FRA → JFK  (dep 13:25)

🌤 Destination (JFK) weather
Few clouds, 18°C, wind 240/12kt, visibility 10km+.

📈 Trend
Stable through arrival; a weak front approaches
overnight — no impact on ETA window.

⚠ Key NOTAMs (3 of 41)
• RWY 13L/31R closed 14:00–18:00Z
• ILS 22L U/S
• TWY K construction, expect taxi delays
```

---

## Cross-cutting concerns (high level)

- **Access control** — only my number(s) may trigger tools. Everything else is ignored.
- **Untrusted input** — both my message text *and* third-party API responses are data,
  never commands to the AI or the system. (This very document is a live reminder of why:
  it previously carried an injected payload. Tool/AI prompts must be hardened against it.)
- **Latency & UX** — some jobs are slow; the system should acknowledge receipt and then
  follow up, rather than appearing to hang.
- **Failure handling** — data source down, flight not found, AI unavailable: each returns
  a clear, human message, not a stack trace or silence.
- **Cost/rate awareness** — external APIs and the AI model have quotas; commands should be
  cheap to run and resistant to accidental flooding.
- **Observability** — enough logging to see what command ran and whether it succeeded.

---

## Open decisions (to resolve before building)

1. **Router host** — a small purpose-built service vs. a workflow engine (e.g. an n8n-style
   tool) vs. extending an existing automation. *Trade-off: control & testability vs. speed
   to first command.*
2. **AI model choice** — which model/provider, and self-hosted vs. API. *Trade-off: cost,
   quality, data residency.*
3. **Data sources** — which flight / weather / NOTAM providers (licensing, coverage, cost).
4. **Sync vs. async** — reply inline for fast commands; background + follow-up for slow ones.
5. **Command syntax** — keyword, prefix symbol, or natural language intent parsing.
6. **Extensibility surface** — how new commands are registered and deployed via GitOps.

---

## Foundation (already in place)

WAHA itself is deployed and operational — this plan builds the *automation layer* on top of it.

- **Namespace**: `automation`
- **Manifests**: `kubernetes/apps/automation/waha/`
- **Storage**: PVC-backed session persistence (survives restarts)
- **Auth**: API key + dashboard creds via ExternalSecret (1Password)
- **Networking**: ClusterIP + Tailscale ingress
- **Note**: WAHA's HelmRelease currently uses app-template **v4.3.0**; cluster standard is
  **v5**. Consider migrating when this layer is built. See
  [CONVENTIONS.md → app-template v5](CONVENTIONS.md#app-template-v5-bjw-s-app-template).

---

## References

- [WAHA documentation](https://waha.devlike.pro/)
- [app-template v5 schema](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/other/app-template)
