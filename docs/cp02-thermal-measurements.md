# cp-02 Thermal Measurements — cp-01 vs cp-02 board/VRM delta

Tracking log for the **degraded thermal path on cp-02** (Lenovo M920Q). cp-01 is an *identical*
node (i5-8500T, nct6683 super-I/O, X520) and serves as the "what good looks like" reference. The
key metric is the **board/VRM sensor** (`node_hwmon_temp_celsius{chip="platform_nct6683_2592",
sensor="temp2"}`) — the channel that ran away to 72°C before the 2026-06-01 BIOS thermal shutdown.

> This is the **thermal** fault (dust/dried paste → poor VRM airflow), which is **distinct** from
> the *silent* hard-downs that strike at ~28°C idle (the non-ECC RAM-bitflip suspect — see
> [ROADMAP → cp-02 Thermal Stability](ROADMAP.md) and memory `project-cp02-outage-investigation`).

## How to take a measurement

```bash
KUBECONFIG=$(pwd)/kubeconfig bash scripts/cp-thermal-compare.sh "<label>"
# e.g. "standard idle", "fans-100 idle", "fans-100 benchmark", "post-repaste benchmark"
# Env: WINDOW=30m (trailing window the min/avg/max are computed over)
```

Run a matched pair of conditions to make the delta meaningful:
- **Same cooling, same load** on both nodes (the script reports `CPU-busy` so you can confirm
  comparable utilisation — a board delta only means something at similar load).
- Take **standard-cooling** and **fans-100%** runs to quantify how much headroom the fan buys.
- Re-measure **after a heatsink clean + thermal-paste reapply** — success = cp-02 within ~1–2°C of cp-01.

Append the script's generated `log row` to the table below.

## Interpreting the delta

cp-02's board running **hotter than cp-01 while its CPU is equal-or-cooler and doing equal-or-less
work** is the signature of degraded *dissipation* (not extra heat generation): restricted airflow
over the board/VRM. The gap **widening under load** (small at idle, large at peak) confirms it.

## Measurements

| Date (UTC) | Label | board avg/max (cp01 → cp02) | **Δ avg / Δ max** | Load | Notes |
|------------|-------|-----------------------------|-------------------|------|-------|
| 2026-06-10 14:12 | standard-cooling post-benchmark | cp01 49/62, cp02 55/70 | **+5.5 / +8.0** | cpu-busy max ~22% | Baseline. cp-02 peaked 70°C (2°C from the 06-01 trip) under a Ceph benchmark at standard cooling; cp-01 identical load peaked 62°C. No crash. Gap widens with load (+5 idle → +8 peak). |
| | fans-100 idle | | | | _todo: re-run with cp-02 BIOS fans at 100%_ |
| | fans-100 benchmark | | | | _todo: same benchmark, fans 100% — does cp-02 stay well clear of 72?_ |
| | post-repaste | | | | _todo: after heatsink clean + paste reapply — target: Δ within ~1–2°C_ |

## Related

- Live alerter: `scripts/cp02-watch.sh` (board/CPU/up watch; run via Monitor in a session).
- Comparison tool: `scripts/cp-thermal-compare.sh`.
- [ROADMAP → cp-02 Thermal Stability](ROADMAP.md), memory `project-cp02-outage-investigation`.
