---
name: project-20260819-e1000e-crc-link-flap
description: CephNodeNetworkPacketErrors sustained firing on cp-03/worker-02 eno1 after cold-start — traced to a simultaneous link flap, cp-03 stuck at 10Mbit, fixed via reboot; worker-02 CRC source still open
metadata:
  type: project
---

During the 2026-08-19 full-cluster cold-start recovery, `CephNodeNetworkPacketErrors` fired
sustained (30+ min, not a single Prometheus tick) on `talos-cp-03` and `talos-worker-02`, both on
`eno1` (Intel I219-LM, e1000e driver — the management NIC).

**Root cause chain (confirmed via `talosctl dmesg` + `/sys/class/net/eno1/statistics/*`):**

1. Both nodes' `eno1` link dropped and came back up within the *same second* of each other —
   cp-03: down 10:36:03Z / up 10:37:17Z; worker-02: down 10:36:04Z / up 10:37:18Z — despite the
   two nodes having very different boot times (cp-03 booted 10:16:50Z that morning, worker-02
   booted 09:09:13Z). Simultaneity across two unrelated chassis strongly implicates a common
   upstream cause (switch port reset/reload/STP event), not independent per-node NIC faults. No
   `e1000e` reset/hang/watchdog messages in dmesg around the event — it was a clean link
   down/up, not a driver crash.
2. On relink, **cp-03 renegotiated at only 10 Mbps Full Duplex** (down from its normal 1000 Mbps)
   and was *still* stuck there 45+ minutes later when checked live — did not self-heal. This is
   the actual smoking gun for cp-03's errors, not a transient settling issue.
3. **worker-02 renegotiated correctly back to 1000 Mbps Full Duplex**, but continued accumulating
   `rx_crc_errors` at a steady, non-decaying rate (~1/s, confirmed via two live samples 100s
   apart) — 100% of `rx_errors` on both nodes is `rx_crc_errors` (rx_frame/length/missed/fifo/over
   all zero, tx side clean, no collisions) — i.e. a pure physical-layer signal-integrity signature
   (cable/connector/port), not a host-side buffering/backlog problem.
4. `rx_dropped` was flat across both live samples on both nodes (not climbing) — consistent with
   the drops being a one-time event at the link-flap moment, distinct from the ongoing CRC errors.
   Do not conflate with the separately-diagnosed `CephNodeNetworkPacketDrops` single-tick
   `netif_rx` backlog root cause (see docs/QA.md) — that mechanism does not explain a 45+ minute
   sustained CRC error rate.

**Assessment given:** not transient/self-healing. cp-03 needs a forced relink (reboot or cable
reseat — Talos has no `ethtool -s`/imperative link-renegotiate command, only a full interface
bounce via node reboot can force PHY renegotiation) since a control-plane node parked at 10 Mbit on
its management NIC (etcd/kube-api traffic) is a bigger operational risk than the Ceph alert itself.
worker-02's steady CRC rate at correct gigabit speed points to a physical cable/connector/port
issue worth inspecting at the next physical maintenance window, not an immediate reboot.

**Why:** Live-diagnosed via talosctl during a CephNodeNetworkPacketErrors escalation, distinguishing
it from the previously-diagnosed PacketDrops single-tick noise pattern.
**How to apply:** If `CephNodeNetworkPacketErrors` or similar recurs on e1000e nodes after a
reboot/cold-start, always check `talosctl get linkstatus eno1 -o yaml` for `speedMbit` — a stuck
low-speed negotiation is a distinct, more urgent failure mode from generic CRC noise, and won't be
fixed by a `for:` debounce. Cross-check `talosctl dmesg` timestamps across *all* affected nodes for
simultaneity — same-second flaps across unrelated chassis point at the switch, not the NIC.
See also [[project_cluster_versions]] for node baseline context.

**Resolution (same day, ~11:26Z):** User authorized `talosctl reboot --nodes 10.60.0.203` (graceful,
not `reset`) to force PHY renegotiation. Confirmed effective: pre-reboot `speedMbit: 10`, post-reboot
`speedMbit: 1000` on `eno1`, `linkState: true`, `duplex: Full`. Reboot sequence was clean (graceful
kexec path, all services incl. etcd/kubelet/trustd came back healthy, no diagnostics). Post-reboot
`talosctl etcd members -n 10.60.0.203` showed all 3 CP nodes as voters (no learners) — quorum never
at risk (single node down out of 3). `talosctl health` (needs explicit `-e <ip> -n <ip>` plus
`--control-plane-nodes`/`--worker-nodes` flags — the multi-node default context in this repo's
talosconfig otherwise trips "command health is not supported with multiple nodes") passed clean
end-to-end afterward. `rx_crc_errors`/`rx_errors` on `eno1` read 0 immediately post-reboot (counter
reset on driver reinit, not proof the physical-layer issue is gone — recheck after the node has
accumulated traffic time to see if the steady CRC climb resumes). worker-02's separate CRC-at-correct-
speed issue was explicitly left untouched per instructions — still needs physical
cable/connector/switch-port inspection out of band.
