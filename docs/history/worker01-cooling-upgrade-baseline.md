# talos-worker-01 — Cooling Upgrade Thermal Baseline

**Node:** talos-worker-01 (Lenovo M920Q #1, Intel i5-8500T, 6C/6T, 64 GB) — mgmt `10.60.0.204`
**Purpose:** Record CPU thermals on the **stock 35 W cooler** before swapping to a **65 W copper-heatsink + new-fan** solution, so the upgrade's effect can be measured.
**Status:** ✅ Complete. Stock baseline + 65 W copper post-upgrade both captured on worker-01 (same chip, matched ambient). See [Post-upgrade results](#post-upgrade-results--worker-01).

> Context: the same 65 W kit was already fitted to the identical **M920Q #2 (talos-worker-02, i5-8600T)** during the June 2026 power-down investigation — but no pre-upgrade baseline was ever taken on that unit, so worker-01 is the only node where a true before/after is possible. Related hardware history: [`cp02-worker02-hardware-faults.md`](cp02-worker02-hardware-faults.md). Reusable side-by-side comparison tool: [`cp-thermal-compare.sh`](cp-thermal-compare.sh) (its `CP01`/`CP02` IPs are these two M920Q nodes).

---

## Baseline run — 2026-07-02

- **Cooler under test:** stock Lenovo 35 W heatsink + fan
- **Ambient:** ≈ 28 °C (acpitz `thermal_zone0`)
- **Load tool:** `stress-ng --cpu 6 --cpu-method matrixprod`, 300 s, all 6 cores
- **Measurement source:** Prometheus node-exporter on the node (`hostNetwork`), no install on Talos required

### Results summary

| Metric | Idle | Full load (6c, 5 min) | Δ |
|---|---|---|---|
| CPU package temp | 47–52 °C | **76–78 °C** (plateau) | +~28 °C |
| Hottest core | ~52 °C | ~78 °C | — |
| **Rise over ambient** | ~22 °C | **~50 °C** | — |
| CPU fan (fan2) | ~1300 RPM | **~3600–4137 RPM** | +~2800 |
| All-core frequency | ~near-idle | **~3.0 GHz sustained** (base 2.1) | — |
| Headroom to throttle (TCC 94 °C) | — | **~16 °C** | — |
| Headroom to Tjmax (crit 100 °C) | — | ~22 °C | — |

- **`stress-ng` verification:** 2,131,513 bogo-ops over 300 s; user-time 1754.6 s ÷ 300 s ≈ **5.85 cores busy** (near-total saturation); `passed: 6/6`, `failed: 0`.
- **Cluster impact:** worker-01 hosts a Ceph OSD; Ceph stayed **`HEALTH_OK`** for the whole run (pool `size=3`/`min_size=2` absorbs one slow OSD).
- **Cooldown:** back to high-50s °C within ~30–60 s of load ending; fan spun down to ~1300 RPM.

### Idle sample (30 s, before load)

```
sample 1:  pkg=52°C  hottest_core=52°C  fan=1298 rpm  load1=0.57
sample 2:  pkg=52°C  hottest_core=52°C  fan=1297 rpm  load1=0.53
sample 3:  pkg=51°C  hottest_core=50°C  fan=1324 rpm  load1=0.48
sample 4:  pkg=48°C  hottest_core=51°C  fan=1323 rpm  load1=0.44
sample 5:  pkg=50°C  hottest_core=50°C  fan=1323 rpm  load1=0.41
sample 6:  pkg=47°C  hottest_core=47°C  fan=1298 rpm  load1=0.38
```

### Under-load sample (10 s interval; stress ended ≈ t=265 s)

```
t(s)   pkg°C   hot°C   allcore            fan_rpm  GHz(avg)  load1
1      77      77      74/74/75/75/76/77  3797     3.20      5.60
12     78      78      76/76/77/78/78/78  3870     3.20      6.55
23     76      76      73/73/74/75/75/76  4067     3.00      7.34
36     76      76      73/73/74/74/76/76  3625     3.00      7.76
46     76      76      73/74/74/75/75/76  3703     2.92      8.67
58     76      76      73/74/75/75/76/76  3692     2.93      8.56
70     76      76      74/75/75/75/76/76  3703     3.00      8.66
82     77      77      75/75/75/75/76/77  3625     3.00      8.48
93     77      77      74/75/76/76/76/77  3636     3.00      8.18
105    77      77      75/75/76/76/76/77  3703     2.98      7.85
116    77      77      74/74/76/76/76/77  3625     2.92      7.78
129    78      77      75/76/76/77/77/77  3625     3.00      7.81
141    77      77      76/76/76/76/77/77  3797     2.98      8.44
153    78      77      75/76/76/77/77/77  3883     3.00      9.10
165    78      78      75/76/76/77/77/78  3797     3.00      8.64
177    78      78      75/76/76/78/78/78  3797     2.94      8.89
188    78      78      76/76/76/77/77/78  3870     2.98      8.89
202    78      78      76/77/77/77/78/78  3797     3.00      8.53
213    78      78      76/77/77/77/78/78  3870     2.97      8.30
224    77      78      76/76/77/77/77/78  3797     2.90      8.16
236    78      78      76/77/77/77/78/78  3883     2.93      8.63
248    78      78      75/76/76/77/77/78  4137     3.00      8.46
260    78      78      76/76/76/77/77/78  4137     3.00      8.28
--- stress ended ~here; cooldown below ---
271    64      68      62/63/63/63/64/68  3738     1.91      7.52
282    63      63      57/58/58/58/58/63  1664     3.20      6.45
292    57      60      56/56/57/57/58/60  1507     1.25      5.54
303    59      58      54/54/55/55/56/58  1477     2.54      4.68
314    62      62      54/54/54/54/60/62  1477     3.24      3.65
324    56      55      53/54/54/54/54/55  1507     2.25      3.23
335    60      60      52/53/53/53/54/60  1317     3.36      2.81
346    57      56      52/52/52/53/55/56  1293     3.30      2.62
```

---

## Commentary

**No thermal throttling occurred.** Under sustained all-core load the package peaked at 78 °C — a full **16 °C below the 94 °C TCC/throttle target** — while the all-core clock held ~3.0 GHz (base is 2.1 GHz) for the entire run. This is the signature of a CPU that is **power-limited (PL1 ≈ 35 W), not thermally limited**, on the stock cooler.

**Implication for the upgrade.** Because the stock cooler already keeps this "T" part off its thermal ceiling, the 65 W copper-heatsink swap is **unlikely to raise sustained clocks** — those are capped by the 35 W power budget, not by heat. The gains to expect instead:

1. **Lower plateau temperature at the same load** — plausibly landing in the low-60s °C.
2. **Lower fan RPM / less noise** to hold that temperature.

**How to compare fairly.** Room temperature will differ between test sessions, so compare the **rise over ambient** (~50 °C under load here), not absolute °C. Reuse the *exact* same load (`stress-ng --cpu 6 --cpu-method matrixprod`, 5 min) and note ambient each time.

**Sensor notes.**
- Real CPU sensor is `platform_coretemp_0`: `temp1` = Package, `temp2`–`temp7` = Core 0–5.
- Fan `fan2` on `platform_nct6683` (Super-I/O) is the CPU blower.
- Ignore `platform_nct6683` `temp5 = 127.5 °C` — an unconnected sensor pinned to max, not a real reading.
- `thermal_zone0` (acpitz) ≈ ambient/chipset; the two `nvme_*` chips ≈ 42 °C are the SSDs, not the CPU.

### Caveat: CPU frequency numbers are a noisy proxy

The `GHz(avg)` column in the sample logs comes from `node_cpu_scaling_frequency_hertz` (kernel `scaling_cur_freq`) — an **instantaneous per-core snapshot**, not delivered/effective frequency. Under HWP with all cores loaded, individual snapshots frequently read the 0.80 GHz floor (a core caught mid-context-switch or servicing the scrape), so both the *variance* and the *absolute level* are unreliable.

Verified 2026-07-02 with a 60 s, 1 Hz sampling run on each node under identical load:

| Statistic (under load) | worker-01 (8500T, stock) | worker-02 (8600T, copper) |
|---|---|---|
| 6-core-avg mean | 2.61 GHz | 2.56 GHz |
| 6-core-avg std ("bounce") | 0.806 GHz | 0.860 GHz |
| Single-core snapshot range | 0.80–3.40 GHz | 0.80–3.60 GHz |

**Both nodes are statistically identical** — same mean, same std. The apparent "worker-02 clock varies more" in the 10 s cross-unit log was cadence luck, not a real difference (and not a BIOS profile difference — `scaling_min`/`scaling_max` policy is identical: 0.80 GHz floor, turbo ceiling = each chip's spec, 3.5 GHz / 3.7 GHz). The trustworthy "ran flat-out?" signal is **`stress-ng` bogo-ops** (2.13M vs 1.96M, steady), which indicates a steady *effective* clock on both. Gold-standard effective frequency would need APERF/MPERF (`turbostat`, privileged MSR read) — not needed here.

---

## Reproduce (apples-to-apples)

Talos has no shell, so both steps go through the cluster. **Read-only temp probe** (node-exporter binds host network, no install):

```sh
curl -s http://10.60.0.204:9100/metrics | grep -E 'node_hwmon_temp_celsius|node_hwmon_fan_rpm'
# coretemp temp1=Package, temp2-7=Core0-5; fan2=CPU fan
```

**Load** via a transient `kubectl` Job (diagnostic only — created then deleted, not committed to Git/Flux). Must run non-root with a writable `/tmp`, or `stress-ng` aborts with `temp-path '.' must be readable and writeable`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: thermal-stress-worker01
  namespace: default
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 420
  ttlSecondsAfterFinished: 120
  template:
    spec:
      restartPolicy: Never
      nodeName: talos-worker-01          # target node under test (change per node)
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        seccompProfile: { type: RuntimeDefault }
      containers:
        - name: stress-ng
          image: colinianking/stress-ng:latest
          workingDir: /tmp
          command: ["stress-ng"]
          args: ["--cpu","6","--cpu-method","matrixprod","--temp-path","/tmp","--timeout","300s","--metrics-brief"]
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: { drop: ["ALL"] }
          resources:
            requests: { cpu: "500m", memory: "128Mi" }
            limits:   { cpu: "6",    memory: "512Mi" }
          volumeMounts: [{ name: tmp, mountPath: /tmp }]
      volumes: [{ name: tmp, emptyDir: {} }]
```

```sh
export KUBECONFIG=$(pwd)/kubeconfig
kubectl apply -f stress-worker01.yaml
# sample temps every 10s while it runs, then:
kubectl logs -n default -l app.kubernetes.io/name=thermal-stress   # stress-ng bogo-ops summary
kubectl delete job thermal-stress-worker01 -n default              # clean up
```

---

## Cross-unit comparison — worker-02 (65 W copper), 2026-07-02

worker-02 (M920Q #2, **i5-8600T**) already has the 65 W copper-heatsink + new-fan kit but no pre-upgrade baseline of its own. Running the **identical load** on both nodes gives an early read on what the kit buys. Same tool, same day, near-identical ambient (27.8 °C vs ~28 °C).

| Metric | **worker-01** — stock 35 W (i5-8500T) | **worker-02** — 65 W copper (i5-8600T) |
|---|---|---|
| Idle package | 47–52 °C | 46–47 °C |
| Idle fan | ~1300 RPM | ~1580 RPM |
| **Full-load package** | **76–78 °C** (steady) | **~68–74 °C** (~72 °C typical, variable) |
| **Load rise over ambient** | **~50 °C** | **~44 °C** |
| **Full-load fan** | **~3600–4137 RPM** | **~2600–3287 RPM** |
| All-core sustained clock | ~3.0 GHz | ~2.7–3.1 GHz (bouncier) |
| Ambient at test | ~28 °C | 27.8 °C |
| `stress-ng` bogo-ops | 2,131,513 | 1,961,596 |
| Peak headroom to throttle (94 °C) | 16 °C | ~20 °C |

**Findings:**
- The copper cooler wins on **both axes at once**: ~5–6 °C cooler at load (44 °C rise vs 50 °C) **while spinning ~900–1000 RPM slower**. Normally temp trades against noise; here you get cooler *and* quieter.
- Since both CPUs are 35 W power-limited (comparable heat output, confirmed by similar bogo-ops), the lower rise at less airflow is attributable to the heatsink, not the silicon.
- **No performance gain** — worker-02 held ~3 GHz all-core and actually logged slightly fewer bogo-ops (1.96M vs 2.13M). Reconfirms these T-parts are power-bound, not heat-bound: the upgrade buys thermal/acoustic headroom, not clocks.

**Caveats:** (1) Different silicon (8600T vs 8500T), but the shared 35 W cap keeps heat output the controlled variable. (2) worker-02's load temps were noticeably **more variable** (64–74 °C swing vs worker-01's tight 76–78 °C) and its fan idles higher (~1580 RPM) — points to a more *reactive* fan curve on the new fan. (3) worker-02 carried slightly higher background pod load (load1 peaked ~9.8 vs ~8.5), explaining the small bogo-ops deficit.

**Predicted worker-01 post-upgrade:** load plateau dropping from ~78 °C to the low-70s (~44 °C over ambient) and full-load fan down by ~1000 RPM — cooler and quieter, no performance change.

### worker-02 under-load sample (10 s interval; stress ended ≈ t=285 s)

```
t(s)   pkg°C   hot°C   allcore            fan_rpm  GHz(avg)  load1
3      69      67      63/63/65/67/67/67  2784     3.19      2.20
15     65      65      61/62/62/64/65/65  3269     1.72      4.43
26     67      64      61/62/63/63/64/64  3225     1.71      5.07
38     68      70      68/68/69/70/70/70  2948     2.91      5.70
52     66      68      61/63/66/66/67/68  2739     2.90      6.12
65     71      71      63/67/68/68/68/71  2948     1.92      6.58
76     73      73      63/63/70/70/71/73  2608     3.42      6.81
87     73      73      71/72/72/72/72/73  3166     1.68      7.85
101    69      72      67/69/70/71/71/72  2941     2.98      8.30
115    68      67      61/62/65/67/67/67  3287     2.42      8.29
126    71      72      67/68/69/69/70/72  2941     2.92      8.50
140    69      69      67/67/68/68/68/69  2948     2.70      8.37
153    72      71      68/69/69/69/70/71  2803     3.13      8.67
167    73      73      67/67/68/69/73/73  2948     3.12      9.43
179    65      72      64/68/70/71/71/72  3076     2.02      9.03
192    64      73      62/63/68/68/70/73  2803     3.13      9.45
205    73      72      68/69/70/70/71/72  2803     1.54      9.49
216    70      72      68/69/70/71/71/72  2992     2.64      9.43
227    69      72      62/67/67/69/72/72  2955     1.30      9.79
243    74      74      71/71/71/71/72/74  2955     3.05      9.36
255    65      72      63/64/65/65/67/72  2649     2.20      9.56
270    72      72      70/70/71/72/72/72  2970     3.02      9.38
282    68      68      67/68/68/68/68/68  2970     2.85      9.38
--- stress ended ~here; cooldown below ---
292    63      63      54/54/54/55/56/63  1610     3.15      8.06
303    55      55      52/52/53/53/53/55  1610     3.02      6.82
314    53      53      51/52/53/53/53/53  1617     2.25      5.77
324    64      64      52/52/54/54/60/64  1395     3.50      4.88
335    52      52      50/51/51/51/52/52  1393     1.18      4.13
345    55      55      49/51/51/51/52/55  1400     3.36      3.49
356    56      56      49/49/50/51/52/56  1400     2.87      3.11
367    54      54      49/49/51/51/51/54  1392     2.70      2.56
```

`stress-ng` verification: 1,961,596 bogo-ops / 300 s, `passed: 6/6`, `failed: 0`. Ceph stayed `HEALTH_OK`.

---

## Post-upgrade results — worker-01

Upgrade performed 2026-07-02 (drain → 65 W copper-heatsink + new-fan swap → reboot; Ceph `noout` auto-managed by Rook disruption management, recovered to `HEALTH_OK` on return). Identical load, **same chip (i5-8500T)**, matched ambient 27.8 °C — the cleanest before/after.

| Metric | Stock 35 W (before) | 65 W copper (after) | Improvement |
|---|---|---|---|
| Idle package | 47–52 °C | **37–42 °C** | ~10 °C raw, but **~4–6 °C cooler-attributable** † |
| Idle rise over ambient | ~22 °C | **~12 °C** | inflated by post-drain under-load † |
| Idle fan | ~1300 RPM | ~1185 RPM | ~115 RPM quieter |

† Post-upgrade idle was measured while worker-01 was under-loaded post-drain (fewer pods). Part of the idle drop is reduced workload, not cooling — see findings and the workload-artifact section below. The **full-load rows are the reliable, matched-condition comparison.**
| Full-load package plateau | 76–78 °C | **73–74 °C** | ~4 °C cooler |
| Full-load rise over ambient | ~50 °C | **~46 °C** | ~4 °C |
| Fan RPM at full load | 3600–4137 | **2650–3000** | ~1000–1100 RPM quieter |
| All-core sustained clock | ~3.0 GHz | ~3.0 GHz | unchanged |
| `stress-ng` bogo-ops | 2,131,513 | 2,178,562 | +2 % (noise) |
| Ambient at test | ~28 °C | 27.8 °C | matched |

**Findings:**
- **Idle: the raw ~10 °C drop is partly a measurement artifact — the cooler-attributable share is ~4–6 °C.** The post-upgrade idle (37–42 °C) was captured minutes after the drain+reboot, while worker-01 was *under-loaded* (11 pods vs its normal complement — Kubernetes doesn't auto-rebalance after a drain). Part of the drop is fewer resident pods, not better cooling. The honest cooler-only idle gain, read from the matched-load cross-unit comparison (copper worker-02 ~46 °C vs stock worker-01 ~50 °C at comparable pod load), is closer to **~4–6 °C**. Expect worker-01's idle to drift up toward the mid-40s °C as pods redistribute. See [Why worker-01 appeared to idle cooler than worker-02](#why-worker-01-appeared-to-idle-cooler-than-worker-02-workload-artifact-not-the-heatsink).
- **Load is the trustworthy comparison (matched conditions): ~4 °C cooler *and* ~1000 RPM quieter simultaneously.** The absolute temp drop understates the gain — fan speed is temperature-driven, so the cooler keeps the die cool enough that the fan never ramps to the stock ~4000 RPM. At equal airflow the temp gap would be far wider. Honest summary: *same work, cooler, quieter.*
- **No performance change** — bogo-ops +2 % (noise), clock steady ~3 GHz. Confirms the 35 W power cap, not cooling, sets sustained speed. The upgrade buys thermal/acoustic margin, not throughput.
- **Matched the prediction** from the worker-02 cross-unit read (forecast: low-70s, ~44 °C rise, ~1000 RPM less → actual: 73–74 °C, ~46 °C rise, ~1000 RPM less).
- **Cross-check vs worker-02** (8600T, same kit): under *matched* full load the two coolers are **equivalent** (~72–74 °C, ~2600–3000 RPM) — worker-02 a hair cooler, consistent with its marginally higher-binned silicon. The apparent "worker-01 idles cooler" difference is **not a cooling difference** — see below.

### Why worker-01 appeared to idle cooler than worker-02 (workload artifact, not the heatsink)

An initial reading showed worker-01 idling ~10 °C cooler than worker-02 (37–42 °C vs 46–47 °C), which looked odd given worker-02 is the higher-binned 8600T on the same cooler. Investigated 2026-07-02 — it is a **background-workload artifact, not a hardware/cooling difference**:

| | worker-01 | worker-02 |
|---|---|---|
| Running pods | **11** | **18** |
| Extra resident services | — | Ceph **mon-g** (~28m), **postgres-v17** replica (~10m), envoy-external (~6m) |
| Live idle package (measured together) | 44 °C | 46 °C |
| Live idle fan | ~1280 RPM | ~1550 RPM |

- **worker-02 simply does more idle work** — it hosts a Ceph mon and a postgres replica that worker-01 doesn't (18 pods vs 11). More resident services → higher idle power → higher idle temp and a higher fan floor.
- **Measured at the same moment the gap is only ~2 °C**, not ~10 °C. The larger initial gap was a timing artifact: worker-01 was sampled minutes after its drain+reboot while unusually empty.
- **Kubernetes does not auto-rebalance pods back after a drain.** Workloads that migrated off worker-01 during the swap stay put until something reschedules them, so worker-01 is currently *under-loaded as a lingering consequence of the drain*. Expect its idle temp to drift up toward worker-02's as pods redistribute.
- **Conclusion:** the coolers perform equivalently. Comparisons must be done at **matched load** (the stress test already provides this) — idle temps are dominated by pod placement, not the heatsink. Do **not** drain a node just to re-measure thermals: draining evicts its workload, which *manufactures* a fake idle improvement and needlessly degrades Ceph.

### Post-upgrade idle sample (30 s)

```
sample 1:  pkg=42°C  hottest_core=42°C  fan=1185 rpm  ambient=27.8°C  load1=0.33
sample 2:  pkg=42°C  hottest_core=42°C  fan=1182 rpm  ambient=27.8°C  load1=0.31
sample 3:  pkg=37°C  hottest_core=37°C  fan=1182 rpm  ambient=27.8°C  load1=0.36
sample 4:  pkg=40°C  hottest_core=40°C  fan=1191 rpm  ambient=27.8°C  load1=0.38
sample 5:  pkg=37°C  hottest_core=37°C  fan=1195 rpm  ambient=27.8°C  load1=0.43
sample 6:  pkg=40°C  hottest_core=40°C  fan=1192 rpm  ambient=27.8°C  load1=0.40
```

### Post-upgrade under-load sample (10 s interval; stress ended ≈ t=295 s)

```
t(s)   pkg°C   hot°C   allcore            fan_rpm  GHz(avg)  load1
2      48      49      47/47/49/49/49/49  1202     3.20      0.69
12     61      60      58/58/58/59/60/60  1200     3.20      1.51
25     65      66      63/63/64/64/65/66  1403     3.20      2.20
36     70      69      66/66/67/67/69/69  1910     3.20      2.79
47     71      71      68/69/70/70/71/71  2226     3.20      3.84
61     68      68      65/66/66/67/68/68  1948     3.00      4.25
72     69      69      67/67/67/68/69/69  2090     2.93      4.91
84     70      70      68/68/68/68/70/70  2120     2.98      5.08
95     70      71      69/69/69/69/70/71  2277     2.93      5.22
107    71      71      69/69/70/70/71/71  2453     2.92      5.60
120    72      72      69/69/70/70/71/72  2631     3.00      5.74
131    72      72      69/70/70/70/72/72  2649     3.00      6.11
142    72      72      70/70/71/71/72/72  2649     2.98      6.17
154    72      72      70/70/71/71/71/72  2660     3.00      6.14
166    72      73      70/71/71/72/72/73  2660     3.00      6.12
177    73      73      71/71/71/71/72/73  2672     2.98      6.31
189    73      73      71/71/72/72/72/73  2678     3.00      6.34
200    74      73      71/71/72/72/73/73  2684     2.95      6.37
211    74      74      71/71/72/72/72/74  2977     3.00      6.56
224    74      74      71/71/72/72/73/74  2970     2.93      6.47
235    74      74      71/71/71/72/73/74  2992     3.00      6.40
246    73      74      71/72/72/72/73/74  2985     2.97      6.38
258    73      73      71/72/72/72/73/73  3000     3.00      6.64
270    74      73      72/72/72/73/73/73  2992     3.00      6.61
281    74      74      72/72/72/72/74/74  2992     3.00      6.68
294    74      74      71/72/72/73/74/74  3000     3.00      6.58
--- stress ended ~here; cooldown below ---
304    66      66      57/58/58/58/59/66  2515     2.92      6.49
315    58      58      53/54/54/54/54/58  1517     1.30      5.49
326    53      53      52/52/53/53/53/53  1300     3.10      4.35
336    59      59      51/51/52/52/52/59  1307     3.33      3.75
347    54      54      49/51/51/51/51/54  1298     2.84      3.32
```

`stress-ng` verification: 2,178,562 bogo-ops / 300 s, `passed: 6/6`, `failed: 0`. Ceph stayed `HEALTH_OK`.
