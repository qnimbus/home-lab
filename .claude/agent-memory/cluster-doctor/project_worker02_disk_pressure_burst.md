---
name: worker02-disk-pressure-burst-2026-06-23
description: CephNodeDiskspaceWarning on worker-02 2026-06-23 traced to a containerd image-pull burst the prior evening, not a structural capacity problem
metadata:
  type: project
---

2026-06-23: `CephNodeDiskspaceWarning` fired twice (duplicate mountpoint pair, see
[[reference_node_exporter_duplicate_mountpoint_alerts]]) on talos-worker-02 `/dev/nvme1n1p4`
(EPHEMERAL/`/var`). Root cause: a bursty containerd image-pull/layer-extraction event between
**2026-06-22 17:21-21:46 UTC** (~8 GiB consumed in under 5 hours — `node_filesystem_free_bytes`
dropped 102.9 GiB -> 94.3 GiB in discrete steps), most likely the VolSync operator deploy plus
waha's `existingClaim` retrofit landing on this node around that window (see SESSIONS.md
`volsync-deploy-pvc-incident`, commit history `a0f3c6d`/`8900961`). `predict_linear(...,2d)` caught
the steep portion of that burst right as it ended, projecting forward as if the rate were
sustained — it wasn't; usage flattened immediately after (94-96 GiB free, noisy ±1.5 GiB,
including a partial GC recovery at 07:41 UTC the next morning).

A same-day Talos reboot (`talosctl reboot -n 10.60.0.205`, IPMI poweroff logged at
`2026-06-23T08:39:27Z`, unrelated AMT/NIC-speed fix) was **ruled out** as the cause — postdates the
fill burst by ~11 hours and pod ages post-reboot don't correlate with the drop window.

Breakdown at alert time (kubelet `/stats/summary`): 128.78 GB capacity, 99.8 GB available, 28.96 GB
used, of which **19.09 GB is containerd imagefs** (~66% of used space) — not logs, not a runaway
pod (`ephemeral-storage` per-pod usage on worker-02 was <1 MiB for every pod, including waha).

All 5 nodes have an **identical** 119.9 GiB EPHEMERAL partition (uniform `installDiskSelector`
across the fleet); worker-02's 22.5% used sat mid-pack (range 11.6%-27.9% across nodes at the
time). Not a structurally undersized node — a fill-rate artifact hitting a `predict_linear`
alert's narrow 2-day lookback window.

**How to apply:** if this alert recurs on any node shortly after a Flux deploy/image-heavy
reconcile, check `node_filesystem_free_bytes` step-changes over the preceding 6-12h before
assuming sustained capacity exhaustion — `predict_linear` over a short window is sensitive to
single bursts. Cross-check kubelet `stats/summary` `runtime.imageFs.usedBytes` vs per-pod
`ephemeral-storage.usedBytes` to distinguish "image cache grew" from "a pod is leaking disk."
