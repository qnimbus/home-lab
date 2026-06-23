# talos-worker-02 Hardware Faults (the M920Q formerly known as cp-02) — RESOLVED

> ## ✅ RESOLVED (2026-06-22) — failing power brick, replaced and confirmed stable
>
> This physical unit — a Lenovo M920Q (i5-8500T, `nct6683` board sensor, X520 storage bond) —
> suffered two distinct fault patterns between 2026-06-01 and 2026-06-21:
>
> 1. **Board/VRM thermal shutdown** (one incident, 2026-06-01) — fixed by a heatsink clean +
>    thermal paste reapply on 2026-06-17.
> 2. **Recurring silent hard-downs** (at least 8 occurrences, 2026-02 → 06-21) — root-caused on
>    2026-06-22 to a **failing external power brick** that cannot sustain peak simultaneous
>    current draw. Confirmed via MemTest86 hardware isolation (the failure followed the brick,
>    not the board/RAM/cooling). The brick has since been **replaced and confirmed stable**.
>
> **Naming note:** this unit was control-plane `cp-02` (`10.60.0.205`) in the original 3-node
> topology. During the 5-node expansion it was demoted to `talos-worker-02` (same IP) — a
> Minisforum MS-A2 became the new `cp-01` and a Lenovo M90q became the new `cp-02`. All
> `cp-02`/`cp-01` references below are **as they were at the time of the incidents** (pre-expansion
> naming); they do not refer to the current `cp-01`/`cp-02` hardware.
>
> Live monitoring (`NodeVRMTemperatureHigh`/`Critical`, `NodeCpuTemperatureWarning`/`Critical`) added
> during this investigation remains in production at
> `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml` —
> generically useful, not diagnostic-only, so it was kept rather than archived with this document.

## Timeline

| Date (2026) | Event |
|---|---|
| 06-01 | Board/VRM thermal shutdown — two outages, 124 min total (09:29–11:33 UTC) |
| 06-02 | Silent hard-down #1, during Longhorn storageNetwork migration |
| 06-05 | Silent hard-down #2, during the storageNetwork rollback |
| 06-10 | Silent hard-down #3 (during Rook-Ceph Phase 5); thermal path confirmed cp-02-specific via cp-01 comparison; silent hard-down #4 — first forensically-captured occurrence (off-node vitals armed just in time) |
| 06-11 | AMT/ME out-of-band management discovered (corrects earlier "no BMC/IPMI" assumption); cp-01 also shows memory-corruption signature during a cluster re-IP (separate, coincidental issue) |
| 06-12, 06-13, 06-16 | Three previously-uncatalogued reboot clusters found later (06-22) via AMT event log pull — raises the true occurrence count to 8 |
| 06-17 | Heatsink clean + thermal paste reapply — both fault patterns stop recurring for 4 days |
| 06-17 | Worker-02 onboarded to Rook-Ceph as `osd.8` — separate issue, see [Related](#related-worker-02-ceph-osd-gap-separate-issue-resolved-2026-06-18) below |
| 06-21 | Silent hard-down #5 — repaste fix did not hold; reopens the investigation |
| 06-22 | AMT event log pulled (169 events) — confirms a +2h clock offset, finds the 3 uncatalogued 06-12/13/16 clusters, and shows this hardware's AMT sensor coverage has **no thermal/power/MCE channel at all** (dead end) |
| 06-22 | **Root cause found**: MemTest86 hardware-isolation matrix (below) identifies the external power brick. Brick replaced; node confirmed stable. |

## Fault 1: Board/VRM thermal shutdown (2026-06-01)

Captured at 30s resolution from `node_hwmon_temp_celsius`:

```
09:26:55  CPU cores: 47–48°C   nct6683/temp2 (VRM/board): 53°C  — normal
09:27:25  CPU cores: 64–66°C   nct6683/temp2: 64°C               — all 6 cores +15–18°C in one scrape
09:27:55  CPU cores: 48–53°C   nct6683/temp2: 68°C               — cores recover via TCC throttle
09:28:25  CPU cores: 48–52°C   nct6683/temp2: 71°C               — board keeps heating
09:29:25  CPU cores: 47–52°C   nct6683/temp2: 72°C               — last reading; BIOS cuts power
```

CPU cores recovered (throttling kicked in) but the `nct6683`/`temp2` board/VRM channel kept
rising even after load dropped — the BIOS thermal protection tripped on **board temperature**,
not the CPU die. ACPI trip points: fan activates at 50°C, active trip 71°C, critical 119°C — but
the BIOS has an unlisted hardware VRM threshold around 72–75°C.

The pattern (all cores spike simultaneously + board keeps heating after core recovery) pointed to
a degraded thermal path: dried thermal paste and/or a dust-clogged fan reducing airflow over the
CPU heatsink and the board/VRM area behind it. Blocked the Cilium `cni.exclusive=false` HelmRelease
upgrade (DaemonSet health check failed on the stuck pod) and delayed the Longhorn storage-network
rollout.

### Confirmation via cp-01 comparison (2026-06-10)

cp-01 was identical hardware (M920Q, i5-8500T, `nct6683`, X520) on identical config, used as a
"what good looks like" reference. Under a Ceph benchmark at standard cooling:

| Metric | cp-01 | cp-02 | Δ (cp-02 − cp-01) |
|---|---|---|---|
| Board avg/max | 49 / 62°C | 55 / 70°C | **+5.5 / +8.0** |
| CPU-busy | ~25% | ~22% | cp-02 doing *less* work |

Hotter board + cooler/lighter CPU = degraded *dissipation* (restricted VRM airflow), not extra
heat generation — confirming a cp-02-unit-specific physical fault, and that the gap widens under
load. This is a genuinely separate fault from the silent hard-downs below (those hit at ~28°C
idle, no thermal correlation at all).

### Fix

- Opened the M920Q, blew out the fan/heatsink assembly with compressed air (2026-06-17)
- Reapplied thermal paste (2026-06-17)
- Verified the fan spins up under load — stable post-repaste, no recurrence since

## Fault 2: Recurring silent hard-downs (2026-06-02 → 2026-06-21)

Distinct signature from the thermal trip: **no thermal precursor**, 100% packet loss on **both**
NICs simultaneously (mgmt e1000e + storage X520), `apid` unreachable, nothing in `dmesg`, idle
temps normal (~28°C). Recovery required a physical power-cycle every time (no BMC/IPMI was known
at first — AMT was discovered later, see below).

### Occurrences

- **06-02** (1st): during the Longhorn storageNetwork migration (commit `0edb316`). Kubelet
  heartbeat stopped 15:32:45. `dmesg` after recovery showed only the post-reboot ring buffer —
  pre-crash logs unrecoverable (Talos does not persist kernel logs across boots).
- **06-05** (2nd): during the storageNetwork *rollback* (commit `299904e`). Kubelet stopped
  10:02:03. Same signature. At this point looked 2-for-2 correlated with Cilium/Multus reconciles
  — but only a userspace agent-pod restart, no reboot/NIC reconfig, which shouldn't kill both NICs.
- **06-10** (3rd): during Rook-Ceph Phase 5 (pgadmin → ceph-block), light load, **no Cilium/Multus
  reconcile at all** (already fully removed weeks earlier) — broke the "Cilium reconcile"
  correlation, refocused suspicion on a unit-specific hardware fault and/or X520/storage-load
  stress.
- **06-10** (4th, **first forensically captured**): off-node vitals (node-exporter tightened to
  10s scrape, on durable `ceph-block` Prometheus, armed earlier that day) caught a dense
  pre-crash record for the first time. Full report: see [Appendix A](#appendix-a-forensically-captured-hard-down-4-2026-06-10) below.
- **06-12, 06-13, 06-16**: three reboot clusters found later via the AMT event log pull (06-22) —
  never logged in any session at the time. The 06-12 cluster uniquely showed two "Embedded
  controller/management controller initialization" events (Intel ME re-init), which only happens
  on a genuine AC power loss — a more severe signature than the others, possibly a distinct event
  layered on the same underlying fault.
- **06-21** (5th): during a CNPG B2-restore-drill, 14:17:30Z → 14:39:45Z (~22 min, one failed
  restart attempt then a successful one). Pre-crash thermal data flat and normal throughout — the
  exact "healthy → instant silence, zero ramp" fingerprint from the 4th occurrence. (A second,
  unrelated 90s blip the same day at 18:23:45Z was a deliberate BIOS-entry reboot to revert a
  manually-set 100% fan speed — not a fault.)

### Theories ruled out

- **Cilium/Multus reconcile correlation** — broken by the 06-10 occurrence (no reconcile in
  flight at all).
- **Thermal** — board sensor flat 51–54°C during the 4th occurrence (20°C below the 72°C BIOS
  trip); confirmed unrelated to Fault 1.
- **OOM / memory leak** — `MemAvailable` rock-steady (~62GB) through every capture.
- **NIC/link degradation** — zero errors/drops on every interface right up to the freeze; NICs
  went healthy → dark in one instant, not via a ramp.
- **Non-ECC RAM bit-flip** (the leading theory for most of the investigation) — fit the "silent,
  no logs, both NICs gone" signature, and was *corroborated* by a `kube-state-metrics`
  `exec format error` crash-loop that only occurred while scheduled on cp-02 (mangled ELF bytes —
  consistent with a containerd content-store bit-flip). **Disproven 2026-06-22**: MemTest86 ran
  zero errors across 4 full attempts into Test 3 before the machine lost power outright — not a
  freeze, an actual power loss, and RAM integrity was never the issue.
- **netconsole over the mgmt NIC** — investigated as a capture mechanism, found not viable:
  cp-02 boots systemd-boot + UKI, and Talos ignores `machine.install.extraKernelArgs` under UKI
  (breaking change since v1.10, siderolabs/talos#11145). Would have required a cp-02-specific UKI
  rebuild via Image Factory for low yield against a hang that's too wedged to emit over UDP anyway.
- **AMT/ME out-of-band event log** — discovered 2026-06-11 as a *better* capture path than
  netconsole (Serial-over-LAN, KVM, boot redirection, survives NIC/OS failure). Pulled in full on
  2026-06-22 (169 events, 06-12→06-22): confirmed a **+2h clock offset** versus real UTC, and
  found the 3 uncatalogued reboot clusters above — but also proved this hardware's AMT event log
  has **no sensor wired in for thermal/power/MCE at all**: across all 169 events the only
  `EventSensorType` value present is `15` (boot/restart). Not "checked, found nothing" — this
  channel structurally cannot show that class of event on this hardware.

### Root cause: MemTest86 hardware isolation (2026-06-22)

With the AMT event log a confirmed dead end, MemTest86 V11.7 (PassMark) was run via JetKVM. **4/4
runs powered the machine off completely** (not a freeze) at a tight, reproducible point: Test 3
(Moving inversions, ones & zeroes), Pass 25%, ~40–42s elapsed every time, zero MemTest-reported
errors. CPU package temp stayed comfortable (54–59°C); a fan-at-100% run dropped CPU temp 5°C but
did not move the failure point at all, ruling out CPU-die heat as the trigger.

Clean isolation matrix (worker-02 has its own JetKVM + DC-passthrough rig, same as worker-01):

| Power brick | JetKVM DC passthrough in circuit | Result |
|---|---|---|
| worker-02's own | present | FAIL ×4 (~40s, Test 3, Pass 25%) |
| worker-02's own | removed | FAIL (same point, immediately) |
| worker-01's (swapped in) | removed | PASS — ran 28+ min clean, Pass 58%, Test 7, zero errors |

The failure followed the **brick**, independent of the passthrough adapter. talos-worker-02's
external power adapter could not sustain MemTest86's peak simultaneous current draw (6 cores +
both memory channels saturated at once), and the whole machine lost power as a result — not a
kernel wedge, not a RAM defect, not a board/VRM thermal trip. This retroactively explains every
prior occurrence cleanly: zero thermal precursor every time, complete insensitivity to cooling,
genuine power-off rather than a hang, and why bit-for-bit identical worker-01 never once faulted.
It also explains the sporadic (not constant) production cadence — real workloads rarely peg all 6
cores *and* saturate both memory channels simultaneously for 40+ seconds the way MemTest86
deliberately does; it took unusually heavy coincident load (Ceph rebalances, CNPG restore drills,
Cilium agent churn) to occasionally trip the same marginal threshold.

One imperfect fit, noted honestly: the 06-10 4th occurrence froze under trivial load (load1
0.2–0.57) — not a contradiction, since a genuinely degrading adapter (aging capacitor, marginal
internal joint) can also drop out on its own schedule, with higher odds under load but not
exclusively triggered by it.

**This means the 2026-06-17 heatsink+repaste was never the fix for this fault** — it likely
helped the *separate*, already-confirmed-distinct board/VRM thermal pattern (Fault 1), but had
nothing to do with the adapter-driven power loss, which is why it recurred on 06-21 after 4 clean
days.

### Remedy

Replaced talos-worker-02's external power adapter. Confirmed stable since.

## Appendix A: Forensically-captured hard-down #4 (2026-06-10)

The off-node vitals capture (armed earlier that day, commit `bca4cee`: node-exporter scrape
tightened to 10s on durable `ceph-block` Prometheus) plus the live `scripts/cp02-watch.sh`
alerter (now archived alongside this document — see [Diagnostic tooling](#diagnostic-tooling))
caught this occurrence with a dense pre-crash record — the first time a cp-02 hard-down was not
a post-reboot blind spot.

### Signature

cp-02 went hard-down at ~19:41:01 UTC: node `NotReady`, kubelet/apid unreachable. Both network
paths confirmed dead from two independent vantage points — mgmt side: Prometheus `up=0`
(`10.60.0.202:9100`) + 100% mgmt ping loss; storage side: Ceph marked osd.3+osd.4 `down` and
mon-c out of quorum (these live on cp-02's `10.200.0.0/24` X520 bond). Whole-machine freeze ⇒
every NIC dark at once. Identical to the 06-02 ×2 and 06-10 (3rd) silent downs; distinct from the
06-01 thermal trip (this one happened cold, board 52°C).

> **Evidence caveat preserved from the original report:** do not cite a devcontainer ping to
> `10.200.0.202` as proof the storage NIC died — the devcontainer has **no route to the
> `10.200.0.0/24` storage VLAN** (cp-01, cp-03, and TrueNAS storage IPs are all unreachable from
> it; only a Docker-bridge default route exists). Storage-side liveness must come from Ceph or
> the nodes themselves, never a local ping.

### Pre-crash telemetry (last successful scrapes, 19:38:00 → 19:39:50 UTC)

| Metric | Behaviour up to the freeze | Reading |
|---|---|---|
| Board/VRM (`nct6683` temp2) | flat | 51–54°C |
| CPU package (`coretemp`) | flat, idle | 47–50°C |
| `MemAvailable` | rock-steady, even rising | ~62.2–62.4 GB |
| `load1` | trivial, mild uptick | 0.20 → 0.57 |
| Per-NIC errs/drops (all devices) | all zero | 0 |

Then: instantaneous 100% dark on both NICs, no intervening degradation on any series — exactly
the fingerprint that later (2026-06-22) turned out to mean a power-supply dropout, not a kernel
wedge.

### Cluster blast-radius (all expected, data safe)

- Ceph `HEALTH_WARN` (not `ERR`): osd.3+osd.4 down, mon-c out. Mon quorum held 2/3 (a,b); mgr `a`
  active. 33 PGs `active+undersized+degraded` — still serving at 2 replicas (`min_size=2`
  satisfied). Stayed undersized (failure domain `zone`, no 4th zone to rebuild into) until cp-02
  returned.
- etcd: 2/3 quorum (apiserver responsive ⇒ quorum intact).
- Workloads: zero stuck pods cluster-wide. RWO-pinned volumes resumed on cp-02's return.

Recovery required a physical power-cycle (M920Q has no BMC/IPMI known at the time — AMT was
discovered the next day, 2026-06-11). Kernel ring buffer wipes on reboot and netconsole was
unviable under UKI, so nothing further could be captured from the dead node.

## Appendix B: Thermal measurement log (cp-01 vs cp-02)

Tracking log for the board/VRM sensor (`node_hwmon_temp_celsius{chip="platform_nct6683_2592",
sensor="temp2"}`) comparing cp-02 against its identical twin cp-01, taken with
`docs/history/cp-thermal-compare.sh` (see [Diagnostic tooling](#diagnostic-tooling)).

| Date (UTC) | Label | board avg/max (cp01 → cp02) | Δ avg / Δ max | Load | Notes |
|---|---|---|---|---|---|
| 2026-06-10 14:12 | standard-cooling post-benchmark | cp01 49/62, cp02 55/70 | **+5.5 / +8.0** | cpu-busy max ~22% | cp-02 peaked 70°C (2°C from the 06-01 trip) under a Ceph benchmark at standard cooling; cp-01 identical load peaked 62°C. No crash. Gap widens with load (+5 idle → +8 peak). |

No further fans-100/post-repaste rows were ever recorded — the 06-17 repaste resolved Fault 1
before a follow-up measurement pass was needed, and the investigation's focus shifted entirely to
Fault 2 (the power brick) after the 06-21 recurrence.

## Diagnostic tooling

Two purpose-built scripts were written for this investigation, hardcoding the pre-5-node-expansion
`cp-01`/`cp-02` IPs (`.204`/`.205`). They are archived here rather than left in `scripts/` since
they were single-purpose diagnostic tools for a now-closed investigation, not general cluster
tooling — kept for reference/template value if a similar hardware investigation is needed again:

- [`cp02-watch.sh`](cp02-watch.sh) — live Prometheus-polling alerter for board/CPU temperature and
  NIC error bursts, with a "possible hard-down" alert on consecutive missed scrapes. Designed to
  run via the `Monitor` tool with `persistent: true` so each emitted line streams into a Claude
  Code session as an event.
- [`cp-thermal-compare.sh`](cp-thermal-compare.sh) — side-by-side board/CPU/load comparison
  between two nodes over a trailing window, with a ready-to-paste markdown row for the measurement
  log above.

## Related: worker-02 Ceph OSD gap (separate issue, resolved 2026-06-18)

A distinct, unrelated issue on the same physical node (by then renamed `talos-worker-02`):
commit `36f6c77` (the "five-node-bootstrap-completion" session) excluded worker-02 from
`cephClusterSpec.storage.nodes` in the Rook-Ceph HelmRelease, reasoning that its Kingston
`nvme0n1` was the boot disk. That reasoning was factually wrong — `talosctl get systemdisk`
confirmed the actual boot disk is `nvme1n1` (Crucial CT1000P310SSD2); `docs/CLUSTER.md`'s disk
inventory had the mapping right all along. `nvme0n1` sat idle, carrying a leftover `lvm2-pv`
signature from a prior provisioning attempt.

**Fixed 2026-06-18**: wiped the stale `lvm2-pv` signature (`vgchange -an` + `wipefs -a`, no
reboot needed, node stayed live throughout) and added `talos-worker-02` to `storage.nodes`.
`osd.8` joined cleanly; cluster reached `HEALTH_OK` with all 33 PGs `active+clean` within under a
minute. See `docs/CLUSTER.md`'s Rook-Ceph section for the current OSD layout.

## References

- Session logs: `worker02-power-brick-rootcause`, `cnpg-storj-to-b2-migration`,
  `rook-ceph-grafana-dashboards` in `docs/SESSIONS.md`; `five-node-bootstrap-completion` in
  `docs/SESSIONS-ARCHIVE.md`.
- Live monitoring (kept, not archived):
  `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml`.
