---
name: e1000e-ring-buffer-drops-not-softirq
description: CephNodeNetworkPacketDrops on cp-03/worker-02's e1000e NIC is RX-ring exhaustion, not NAPI/softirq budget exhaustion — netdev_budget can't fix it
metadata:
  type: reference
---

Confirmed live with Prometheus data (2026-09-01, burst window 10:10-10:17 UTC, sabnzbd RBD
write burst — see `docs/QA.md`'s `CephNodeNetworkPacketDrops` entry, 2026-09-01 follow-up) that
the packet drops on `cp-03`/`worker-02`'s `eno1` (Intel I219-LM, `e1000e`) during Ceph client I/O
bursts are **NOT** a NAPI/softirq CPU-scheduling bottleneck, despite `net.core.netdev_budget`/
`netdev_budget_usecs` being the fix that worked on `cp-02`/`worker-01` for what looked like the
same symptom.

**Evidence, all queried directly from `kube-prometheus-stack-prometheus` (observability ns) for
the exact burst window:**
- `node_softnet_times_squeezed_total` — **flat zero**, all CPUs, both nodes, entire window. This
  is the direct signature of NAPI budget exhaustion (a scheduled device not fully drained before
  the softirq yields) and it never fired once. Rules out budget exhaustion definitively.
- `node_softnet_dropped_total` — also flat zero throughout. Rules out `netif_rx`/backlog
  overflow (the mechanism `netdev_max_backlog` guards, already ruled out in the existing
  `machine-sysctl-netdev-budget.yaml` patch comment since e1000e's NAPI driver drains its own
  ring directly and mostly bypasses that backlog anyway).
- `node_network_receive_fifo_total` — flat zero. Rules out hardware ring/FIFO overrun errors.
- `node_network_receive_drop_total` on `eno1` — **this is the metric that actually spikes**:
  0 → 600-1600 drops/sec exactly in the 10:13:30-10:17:00 window, matching the alert's fire
  window precisely. This counter reflects the driver's own `rx_dropped` stat (RX descriptor ring
  exhaustion / `skb` allocation failure at the driver level) — a layer *below* both the softnet
  backlog and the NAPI budget loop. `netdev_budget` cannot fix this: it governs how much softirq
  *time* a CPU spends draining already-queued NAPI work, not how many descriptors the ring itself
  can hold before a burst outruns it.
- CPU: even the single busiest core (`worker-02` cpu4, `cp-03` cpu6 — see NIC queue note below)
  only reached ~8-12% softirq utilization with idle staying >78% throughout. Not remotely CPU-
  saturated.
- Rook-Ceph OSD pod CPU (`rook-ceph-osd-{2,4}` on cp-03, `{6,9}` on worker-02) stayed flat at
  0.04-0.2 cores throughout — no evidence of the OSD daemon and the NIC's softirq competing for
  the same core.
- RX packet rate peaked at ~2-5k pps on a 1GbE link — roughly two orders of magnitude below
  wire-rate saturation for normal-sized frames. Confirms this was never a bandwidth/pps problem.

**NIC queue topology:** Intel I219-LM (`e1000e` driver family) is hardware single-queue — no RSS,
no multi-queue support in the chip or driver, unlike `ixgbe`/`i40e`/`igc`. All RX softirq
processing for `eno1` is pinned to whichever single CPU core owns that device's one interrupt
vector; this is consistent with the observed softirq elevation landing almost entirely on one
core per node (`worker-02` cpu4, `cp-03` cpu6) rather than spreading. Could not verify
`ethtool -l`/queue count directly — node-exporter's image is distroless (no shell/`ls` in
`$PATH`), and Talos has no SSH; would need a privileged debug pod or `talosctl` support bundle to
confirm interactively, but the well-known e1000e/I219 hardware limitation plus this asymmetric
softirq pattern is strong indirect confirmation.

**Why the fix worked on cp-02/worker-01 but not cp-03/worker-02:** likely coincidence of which
nodes' NAPI+softirq path happened to be marginal vs. which nodes' RX ring happened to be
marginal for a given burst profile — two different bottlenecks that can each show up as "the same
alert" on nominally identical hardware/driver, depending on burst shape and which OSDs currently
hold the hot PGs (see the OSD PG placement point in the QA.md entry).

**Remaining tuning levers, ranked by what's actually indicated:**
1. **RX ring buffer size** (`ethtool -G eno1 rx <N>`) — the directly indicated fix now that ring
   exhaustion is confirmed as the actual drop mechanism. e1000e's default ring is small (often
   256 descriptors) relative to modern NICs. **Talos has no declarative machine-config field for
   ethtool ring sizing** — this is not a `sysctl` and not covered by Talos's network config schema
   (interfaces/routes/bonds/VLANs only). Applying it would require an unsupported workaround: a
   privileged DaemonSet/initContainer running `nsenter --net=/proc/1/ns/net -- ethtool -G ...` at
   boot on affected nodes, since there's no persistent way to run this through `talosctl` alone
   (it doesn't survive reboot without something re-applying it).
2. **RPS** (`/sys/class/net/eno1/queues/rx-0/rps_cpus`) — would let *software* IP-processing after
   the ring get redistributed across cores, but does nothing for ring-level drops that happen
   before a packet is even pulled off the ring. Lower priority than #1 given the confirmed
   mechanism. Also not declarative in Talos — same unsupported-workaround caveat as ring sizing.
3. **IRQ affinity** — moot for a genuinely single-queue device; there's only one RX interrupt
   vector to place, so this lever doesn't apply here the way it would on a multi-queue NIC.
4. `netdev_budget`/`netdev_budget_usecs` (already applied fleet-wide via
   `talos/patches/node/machine-sysctl-netdev-budget.yaml`, IS declarative via Talos
   `machine.sysctls`) — correctly targets softirq scheduling contention, which is why it helped
   wherever *that* was the bottleneck (cp-02/worker-01) and why it did nothing here (ring
   exhaustion is a different layer entirely).

See [[reference_amt_phy_reset_blocked]] for the unrelated but similarly-shaped "looks like a Ceph
network problem, is actually a NIC-layer issue on one specific node" pattern (PHY speed lock
rather than ring exhaustion).
