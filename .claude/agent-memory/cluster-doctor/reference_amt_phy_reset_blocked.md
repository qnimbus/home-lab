---
name: amt-phy-reset-blocked-10mbps
description: Intel AMT ME can pin a node's management NIC at 10 Mbps after IDE-r/SOL KVM use, masquerading as a Ceph/network incident
metadata:
  type: reference
---

## Symptom

`eno1` (Intel I219-LM, e1000e) on an AMT-equipped node comes up at **10 Mbps** instead of
1000 Mbps on boot, persists for the entire uptime (not a transient flap), and is invisible to
`ceph health detail` / Talos `get links` operational-state fields (link reports `up`,
`LOWER_UP: true` — only `speedMbit` reveals the problem).

Downstream effects, all on the management network (`10.60.0.0/24`) carried by that NIC:
- Ceph `OSD_SLOW_PING_TIME_FRONT` (`CephOSDTimeoutsPublicNetwork` alert) — heartbeat pings
  to/from OSDs on the affected host take >1000ms instead of <1ms (public network only;
  storage/cluster_network on the separate SFP+ bond is unaffected).
- Talos `cluster.DiscoveryServiceController`: `keepalive ping failed to receive ACK within
  timeout`, `hello failed ... DeadlineExceeded`.
- `dns-resolve-cache: read udp ...->10.60.0.1:53: i/o timeout`.

## Root cause

```
e1000e 0000:00:1f.6 0000:00:1f.6 (uninitialized): Reset blocked by ME
e1000e 0000:00:1f.6: PHY reset is blocked due to SOL/IDER session.
e1000e 0000:00:1f.6 eno1: NIC Link is Up 10 Mbps Full Duplex, Flow Control: None
```

On AMT-equipped nodes (`worker-01`, `worker-02`, `cp-02` per CLAUDE.md), Talos management traffic
and Intel AMT (SOL/IDE-r) share the same physical NIC (AMT rides untagged VLAN 100, Talos rides
tagged VLAN 60). If the AMT Management Engine has an active or recently-active SOL (Serial-Over-LAN)
or IDE-r (ISO redirect/KVM) session — e.g. from using MeshCommander to boot a diagnostic ISO like
MemTest86 — the ME can hold the PHY in a locked state across the next boot, preventing a full
gigabit renegotiation. The NIC still links up (so it looks "fine" at a glance) but stays at the
ME's stale 10 Mbps.

Confirmed 2026-06-23: this happened on talos-worker-02 the boot cycle immediately following the
[[worker02-power-brick-rootcause]]-era MemTest86 IDE-r diagnostic session. Node booted
2026-06-22T20:25Z at 10 Mbps; `CephOSDTimeoutsPublicNetwork` started firing 2026-06-23T07:35Z
(once steady cluster traffic — etcd, kubelet heartbeats, Ceph OSD pings — saturated the throttled
link). All other nodes' `eno1`/management NICs report `speedMbit: 1000` for comparison.

## Diagnostic check

```bash
talosctl --nodes <ip> --endpoints <ip> get links -o yaml | grep -A3 'id: eno1' # check speedMbit
talosctl --nodes <ip> --endpoints <ip> dmesg | grep -iE "NIC Link is Up|Reset blocked by ME|SOL/IDER"
```

A node stuck at `speedMbit: 10` (or 100) when its peers show 1000 is the tell. Cross-reference
boot timestamp in dmesg against any recent MeshCommander KVM/IDE-r session on that node.

## Fix

A `talosctl reboot` (full power cycle, not just a soft reboot if the ME session persists) of the
affected node typically clears the stuck PHY state, since the ME's SOL/IDER session is generally
released after a clean AMT power-cycle. Confirm by re-checking `speedMbit` after the node rejoins.
If it recurs, avoid leaving an IDE-r/KVM session attached in MeshCommander after diagnostic work —
explicitly disconnect/release the session before the node's next boot.
