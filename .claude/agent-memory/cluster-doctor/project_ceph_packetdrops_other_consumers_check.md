---
name: ceph-packetdrops-other-consumers-check
description: 2026-09-01 audit of whether ceph-block consumers besides sabnzbd can trigger CephNodeNetworkPacketDrops — live episode caught mid-investigation, ruled out Prometheus/victoria-logs/volsync/sabnzbd, root cause of that specific episode still unidentified
metadata:
  type: project
---

**Context:** after confirming sabnzbd's `/config` PVC as one root cause of
`CephNodeNetworkPacketDrops` on `cp-03`/`worker-02` (see [[reference_e1000e_ring_buffer_drops_not_softirq]]
and `docs/QA.md`'s 2026-09-01 entries), and migrating the entire `downloads` namespace
(sabnzbd/sonarr/radarr/prowlarr — all four, not just sabnzbd, per commits `bea944e`/`605ae2e`) off
`ceph-block` onto NFS, checked whether other `ceph-block` consumers could reproduce the same
failure mode.

**VolSync hourly-backup synchronization: confirmed real and unmitigated.** All 8 apps sharing
`kubernetes/components/volsync` (paperless-ngx, plex, open-webui, n8n, pgadmin, waha, firefly-iii,
forgejo) — grepped every `ks.yaml`, zero override the component's default `VOLSYNC_SCHEDULE:=0 * * * *`.
Confirmed live via `ReplicationSource.status.lastSyncTime`: all 8 completed their hourly sync
within the same ~30s window (13:00:31-13:00:59 UTC, 2026-09-01). This is a real synchronized-burst
risk worth fixing (stagger via per-app `VOLSYNC_SCHEDULE` in each `ks.yaml`), independent of
whether it's caused a page yet.

**Live episode caught mid-investigation (2026-09-01, 13:51:46-13:53:01 UTC, cp-03+worker-02
simultaneously) — the most direct data point available, and it does NOT match the volsync theory:**
last volsync sync had completed 50+ minutes earlier (13:00:59), no mover pods/jobs were running,
next scheduled sync was 14:00. `node_network_receive_drop_total{device="eno1"}` spiked
simultaneously on both nodes at 13:51:15 (244/s cp-03, 231/s worker-02) — confirms the cross-node
simultaneous-burst mechanism, but the trigger for *this specific* episode was not identified:
- Prometheus's own pod network TX: flat throughout (~10-13KB/s) — directly rules out Prometheus's
  own TSDB/WAL writes as the cause of this episode.
- victoria-logs-server TX: flat (~1.8-2.1KB/s) — ruled out.
- sabnzbd: 14MB/s incoming download traffic at the time, but running on `cp-01` (unaffected `igc`
  node) with its PVC already on NFS — ruled out.
- plex (on cp-03, affected node) / n8n (cp-03) / open-webui (worker-02): all flat TX/RX, no burst
  coincident with the episode — ruled out for this specific occurrence.
- `ceph -s` showed 36 MiB/s read / 84 op/s read client I/O ~3min after the episode (still
  `HEALTH_OK`, no recovery/backfill) that didn't match any topk'd pod's container-level receive
  rate — likely Ceph-internal (scrub) since OSDs are host-networked and invisible to per-pod
  cAdvisor metrics, or a client outside the checked set. **Not conclusively identified** —
  `rbd perf image iostat` (would show per-image I/O) is an interactive TUI that doesn't work over
  a single `kubectl exec`; would need a live session or `dmesg`-adjacent capture at the next
  occurrence to pin down further.

**Historical 14-day Prometheus retention (2026-08-19 → 2026-09-01) — updates the node list:**
Only `cp-03` (10.60.0.203) and `worker-02` (10.60.0.205) show ANY `CephNodeNetworkPacketDrops`
activity (pending or firing) in the full retention window — `cp-02`/`worker-01` show zero, despite
older `docs/QA.md` entries describing all four `e1000e` nodes as affected historically. Either
`cp-02`/`worker-01` genuinely haven't had a bad-enough burst land on their OSDs in the last 14
days, or whatever made them affected earlier has changed — worth re-checking if this pattern holds.
16 distinct firing episodes in the window; minute-of-hour clustering near top-of-hour was
weak-to-moderate (~44-63% of episodes within ±5-10min of :00 vs ~18-35% expected by chance at
n=16) — suggestive but not strong, and the one live episode actually caught was NOT near the top
of the hour (13:51-13:53), which argues against volsync-hourly-sync being the dominant driver even
though the synchronization itself is real.

**Net verdict for `docs/ROADMAP.md`'s "Ceph public_network: Move to Storage VLAN" item:** the
*arr-stack migration did not fully solve the underlying problem — a fresh episode fired 3+ hours
after that migration completed, with no identifiable single-app trigger among the apps checked.
This is evidence the ring-exhaustion mechanism is closer to intrinsic-to-sharing-public_network-on-
e1000e-NICs than a purely per-app problem that migrations will eventually whack-a-mole away. Also:
the ROADMAP's existing "pre-work" suggestion to check CNPG Postgres is stale — CNPG's actual DB
storage is `openebs-hostpath`, not `ceph-block` at all (confirmed by reading the manifests
directly) — the pre-work note should point at Plex's `/config` PVC (20Gi ceph-block, same
SQLite-config pattern as sabnzbd's confirmed trigger, currently on `cp-03`) and
Prometheus/victoria-logs instead.

See [[reference_e1000e_ring_buffer_drops_not_softirq]] for the underlying NIC-layer mechanism this
builds on.
