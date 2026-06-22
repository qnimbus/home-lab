---
name: project-worker02-harddown-20260621
description: Fifth hard-down on talos-worker-02 (ex-cp-02), 2026-06-21, 4 days after heatsink repaste fix — inconclusive, AMT log unreachable from this shell
metadata:
  type: project
---

## Incident summary

talos-worker-02 (10.60.0.205, Lenovo M920Q, formerly cp-02) rebooted unexpectedly on 2026-06-21.
Confirmed kernel ring-buffer start (= boot time) at **2026-06-21T18:24:45.63Z**, boot sequence
complete and kubelet healthy by **18:24:58Z** — matches the `lastTransitionTime` the user found on
the node conditions exactly. This is the 5th hard-down on this physical unit and the FIRST since
the 2026-06-17 heatsink-reseat + repaste fix that had resolved both known fault patterns (thermal
VRM trip from 2026-06-01, and 4x silent kernel-wedge hard-downs 2026-06-02→06-10). Happened during
a CNPG cluster rebuild / B2 backup-restore-drill in the `database` namespace.

## What was checked (2026-06-22 investigation)

- `talosctl -n 10.60.0.205 dmesg`: ring buffer starts cold at 18:24:45.63Z (first line is the
  `Linux version` banner) — **no pre-crash log survived**, consistent with every prior occurrence.
  No panic/oops/MCE lines anywhere in the post-boot buffer either.
- `/sys/fs/pstore` via `talosctl -n 10.60.0.205 list`: **empty** (only `.` entry) — pstore capture
  was never armed/available on this hardware, same as all prior incidents. Confirmed again, not
  assumed.
- `talosctl -n 10.60.0.205 health` / `etcd members`: both return
  `Unimplemented ... only available on control plane nodes` — worker-02 is a worker in the current
  5-node topology, these checks don't apply. Used `talosctl service` + `kubectl get node` instead;
  all services (apid, kubelet, containerd, cri, etc.) healthy, node `Ready`, uptime ~13h45m at
  check time, no anomalies post-recovery.
- kube-apiserver Events for the node and the `database` namespace: **already rotated out** (default
  ~1h TTL) — no corroborating K8s-side event trail survived to investigate the crash window.
- AMT event log via MeshCommander: **could not retrieve.** The `meshcommander` sidecar is reachable
  by container DNS name (`http://meshcommander:3000`, HTTP 302 → `/default.htm`) from this agent's
  shell, but it is a stateful JS web UI that negotiates WSMAN/SOAP sessions against the node's AMT
  ME interface with its own auth — not a scriptable REST endpoint a `curl` can pull structured event
  data from. No `docker` CLI is available in this shell either. This check requires a human (or a
  browser-driving agent) at `http://localhost:3000` in the devcontainer. **Not yet documented
  anywhere as a repeatable procedure** — grepped `docs/incidents/`, `docs/QA.md`,
  `docs/HARDWARE-ARCHITECTURE.md`: AMT is only used there for KVM/IDE-r/disk enumeration, never for
  event-log forensics. If this becomes a recurring ask, worth asking the user how they actually
  read the AMT log by hand (likely the MeshCommander UI's event-log panel) so the procedure can be
  written down.

## Assessment

Inconclusive — same as every prior occurrence. Boot-time evidence pins the down to shortly before
18:24:45Z on 2026-06-21 but provides no causal signal (thermal vs. wedge vs. new I/O-load variable
from the B2 restore drill). See [[feedback_pstore_never_armed]] if created — pstore capture gap is
now confirmed 2x; worth raising whether it's enable-able on this hardware/Talos version at all.
