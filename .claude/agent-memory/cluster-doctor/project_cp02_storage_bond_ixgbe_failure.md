---
name: cp02-storage-bond-ixgbe-failure
description: RESOLVED 2026-07-07 — cp-02's X520 (ixgbe) HW init failure (2026-06-25) triggered a fleet-wide VLAN-200 storage fallback; replacement X520 installed in cp-03 and bond-storage restored on all 5 nodes. Kept for historical incident detail and the watch-item on cp-03's enp2s0f0.
metadata:
  type: project
---

On 2026-06-25, investigated "3 pending deployments" report. Found 6 pods stuck
(`automation/waha`, `database/pgadmin`, `observability/{alertmanager,grafana,prometheus,
victoria-logs-server}`), all `FailedMount`/`FailedAttachVolume`/`Multi-Attach` on Rook-Ceph RBD
PVCs. Root cause chain:

1. `talos-cp-02` rebooted at 2026-06-24T18:21Z (uptime ~12h at investigation time).
2. On boot, dmesg showed: `ixgbe 0000:02:00.0: HW Init failed: -114` and same for `0000:02:00.1`
   — **both ports of cp-02's dual-port Intel X520 (ixgbe) NIC failed PCI/firmware probe**. The
   kernel never created slave interfaces for them.
3. This left `bond-storage` (802.3ad LACP bond carrying `10.200.0.202/24`, MTU 9000, the Ceph
   `cluster_network`/storage path) mastered but slave-less: `operationalState: down`,
   `linkState: false` in `talosctl get links bond-storage`. Confirmed via
   `talosctl get links -o yaml` parsed for `name/linkState/speedMbit/driver` — the default table
   view hides this, must check the full link object.
4. cp-02's own OSDs (osd.1, osd.4) and other cluster OSDs were observed by cp-02's kernel rbd
   client (`libceph` in dmesg) flapping down/up every 3-5 min — heartbeat timeouts caused by the
   storage network being unreachable from cp-02, not actual OSD crashes (mon side showed them
   stable `up` except osd.1/osd.4 which mon eventually marked `down` after missed heartbeats).
   Ceph health: `HEALTH_WARN`, 19 pgs stuck peering, 14 pgs active+undersized+degraded,
   14.5% objects degraded.
5. The RBD CSI **nodeplugin pod on cp-02** (`rook-ceph.rbd.csi.ceph.com-nodeplugin-*`) has stuck
   in-memory operation locks for several Volume IDs — every NodeStage/NodeUnstage retry from
   kubelet gets rejected with `rpc error: code = Aborted desc = an operation with the given
   Volume ID ... already exists`. This is because the original stage/unstage call hung
   (can't reach the RBD image over a dead storage network) and never released its lock.
6. Net effect: duplicate `VolumeAttachment` objects exist for the same PV pointing at two
   different nodes simultaneously (e.g. both `talos-cp-01` and `talos-cp-02` attached to the
   same `pvc-65fb312a-...`), causing `Multi-Attach error` for any pod the scheduler places on
   the "wrong" node, and `FailedMount` (Aborted/already exists) for pods scheduled where Rook
   expects them. Pods had been retrying for **361 failed mount attempts over 12h** — this has
   been silently broken since the reboot, not a fresh problem.

**Why this wasn't found via `ceph health` alone**: `ceph health detail` correctly named cp-02 and
osd.1/osd.4, but the actual blast radius (6 unrelated app pods cluster-wide via CSI lock
contention) is not visible from Ceph's perspective — needed `kubectl get volumeattachments` +
per-PV cross-reference + rbdplugin nodeplugin pod logs to see the stuck-lock mechanism.

**Hardware drift note**: CLAUDE.md's hardware table lists cp-02 (Lenovo M90q) as having only
`eno1` 1GbE management — no ixgbe/X520 card documented for cp-02. Live `talosctl get links`
clearly shows ixgbe driver present and PCI-enumerated (`0000:02:00.0`/`.1`) on cp-02, and
`bond-storage` (802.3ad, MTU 9000) is configured against it. CLAUDE.md needs a hardware-table
update — cp-02 evidently does have a 2-port X520 add-in card for the storage bond, like
worker-01/worker-02. Flag this to the user; do not silently edit CLAUDE.md from this agent's
memory.

**Fix is node-layer, not Kubernetes-layer**: a Talos `reboot` of cp-02 (or physically
reseating/power-cycling the NIC card if reboot doesn't clear the ixgbe probe failure) is the
correct remediation — this is a [[reference_amt_phy_reset_blocked]]-adjacent pattern (PCIe/NIC
init failures after a reboot) but the symptom (-114 probe failure) and fix differ: that memory is
about AMT pinning copper PHY speed after SOL/IDE-r; this is ixgbe HW init failing outright,
unrelated to AMT (cp-02 is AMT-equipped but this NIC is the X520, not the AMT-managed port).
After the bond recovers, the stuck CSI operation locks and duplicate VolumeAttachments should
self-clear once kubelet's mount retries succeed; if they don't clear within a few minutes of the
bond coming back up, the rbdplugin nodeplugin pod on cp-02 needs a restart to drop its stale
in-memory locks (Disruptive — drops in-flight mount/unmount ops cluster image-wide briefly, but
scoped to one node's CSI plugin daemonset pod).

**Follow-up verification (same 2026-06-25 incident, ~1h later) — is this card-specific to cp-02,
or could cp-03 (identical M90q + X520-DA2 hardware) share the fault?**

- Confirmed node identity: `10.60.0.202` genuinely is `talos-cp-02` (`talosctl get member` +
  `talosctl get hostname` both via direct endpoint and cross-checked) — the failure was not
  misattributed to the wrong node.
- Confirmed cp-02's actual hardware against `talos/talconfig.yaml` (not CLAUDE.md's stale table):
  the per-node comment explicitly reads `# Lenovo M90q #1 (i5-10500T, 6C/12T, 64GB, +X520-DA2
  SFP+ 10GbE) — permanent CP`. **CLAUDE.md's hardware table is wrong/stale** — it lists cp-02
  with only `mgmt: eno1 1GbE (VLAN 60+200 on single port)` and no X520/bond mention at all, and
  doesn't list cp-03 as its own row (collapsed into a 4-row 3-CP-era table). Both cp-02 and
  cp-03 are M90q #1/#2, each with an added X520-DA2 dual-SFP+ card feeding `bond-storage`,
  identical to worker-01/worker-02's X520-DA2 cards. CLAUDE.md needs a hardware-table refresh to
  add cp-03 as its own row and correct cp-02's NIC list — flagged to user, not edited by this
  agent (out of scope for a live-incident diagnosis).
- Checked cp-03 (`10.60.0.203`) for the same fault during a fresh reboot of cp-03 (user-initiated,
  unrelated to the cp-02 incident). On this fresh boot, **both ixgbe ports probed cleanly**:
  `ixgbe 0000:02:00.0`/`.1` both reported `NIC Link is Up 10 Gbps, Flow Control: RX/TX`, no
  `-114`/HW Init failure anywhere in the boot's dmesg, and `bond-storage` came up fully:
  `operationalState: up`, `linkState: true`, `speedMbit: 20000` (full 2x10G LACP aggregate).
  **cp-03 does not share cp-02's fault** — same hardware model (M90q + X520-DA2), same
  kernel/driver version, clean probe. This points at a cp-02-specific defect (that specific card,
  its specific PCIe slot/riser, or a firmware/power quirk unique to that unit) rather than a
  systemic ixgbe/driver/Talos-version issue that would be expected to also hit cp-03 or the
  worker nodes' X520s.
- Operational note: talosctl calls against a node within ~20s of its own reboot can return
  `connection refused` on port 50000 (apid not up yet) — this is expected and self-resolves;
  retry rather than concluding node failure from a single refused connection right after a known
  reboot event.

**Remediation attempts tried (same 2026-06-25 incident, escalating) — none cleared the fault:**

1. Warm reboot (talosctl-equivalent) — `-114` reproduced on both ports, `bond-storage` stayed down.
2. Full cold power-cycle (physical power off 20-30s, capacitors discharged, then powered back on)
   — `-114` reproduced identically a 3rd time. This is strong evidence against a "stuck firmware
   semaphore that a power cycle clears" theory; the NIC's wedged state apparently survives even a
   complete de-power, which usually means either genuine silicon/component failure on the card,
   or NVM/EEPROM corruption that a power cycle cannot reset (EEPROM content persists across power
   loss by design).
3. Physical reseat of the X520-DA2 card (removed and reinserted in the same slot) — `-114`
   reproduced identically a 4th time (confirmed live via direct talosctl to cp-02, boot timestamp
   `2026-06-25T09:09:30Z`). This rules out a loose-seating/connector-contact theory — reseating in
   the same slot did not help, which is consistent with the clean PCI enumeration evidence
   (vendor/device ID correct, x8 link width achieved, no AER errors) pointing at the failure being
   *inside* the controller/NVM rather than at the PCIe electrical/mechanical connection.

Four consecutive identical failures across reboot, cold power-cycle, and reseat — same `-114` on
both ports every time — point toward either a genuinely failed 82599 controller die, or corrupted
NVM/EEPROM on this specific card that no power-state or seating change can clear. Remaining
untried options: try a different PCIe slot on cp-02's board (if available) to fully rule out a
slot/riser-specific fault despite clean bus enumeration; attempt NVM/firmware reflash via Intel
tooling if available; or treat as hardware failure and pursue card replacement/RMA.

**Talos reset is not a viable fix for this class of fault** — `talosctl reset` only wipes/reinstalls
the node's `STATE`/`EPHEMERAL` partitions and reinstalls the Talos OS image; it has no path to
touch a NIC card's onboard firmware/NVM, which is what's implicated here. All 5 nodes run the
identical Talos image version (confirmed via `kubectl get nodes -o wide` showing uniform
`v1.13.2`/`6.18.29-talos` before this incident), built from one shared `talenv.yaml` — there is no
per-node image/driver-version divergence for a reset to correct, and cp-03 (same hardware family,
same image) already proved the stock `ixgbe` driver works fine on identical hardware. A reset
would just reinstall the same already-tested-and-failing combination.

## Escalation: fleet-wide bond-storage decommission (2026-07-01/07-02)

The card-level fault above eventually escalated to a full hardware replacement: cp-03's physical
node was replaced 2026-07-01 (talconfig.yaml comment: "Lenovo M90q #3 ... replaced 2026-07-01
after hardware failure") and the **replacement unit has no X520 card installed at all yet**. As
part of this, the user applied (live, via talosctl — not yet git-committed as of 2026-07-02) an
inline patch on **all 5 nodes** that:
- Adds a tagged VLAN 200 sub-interface on each node's onboard 1GbE management NIC
  (`enp4s0.200` on cp-01, `eno1.200` on cp-02/cp-03/worker-01/worker-02), carrying the *same*
  `10.200.0.20{1..5}/24` storage IP the bond used to carry, MTU 1500.
- Comments out the `addresses:` block under each node's `bond-storage` interface config, so the
  bond interface still exists (per config) but is unaddressed and carries no traffic.

Live-cluster confirmation (2026-07-02): `talosctl get links` shows `bond-storage`
`operationalState: down`, `linkState: false`, `speedMbit: 4294967295` (unset sentinel) on **every**
node, including cp-01/worker-01/worker-02 which have healthy, previously-working X520 hardware —
this is expected and intentional, not a new fault. `talosctl get addresses` confirms all 5 nodes'
storage IP now rides the `.200` VLAN interface instead. `ceph -s` is `HEALTH_OK`, all 10 OSDs
up/in, 3 mons in quorum, 33 active+clean pgs — the cluster is fully healthy on the 1GbE fallback
path (same subnet, so Ceph's public/cluster_network config needed no changes).

**Effect on monitoring**: this fleet-wide bond-storage decommission makes both `NodeBondingDegraded`
and `CephNodeNetworkBondDegraded` fire on **every** node simultaneously (`master="bond-storage"`,
`node_bonding_slaves=2, node_bonding_active=0` on the 4 nodes that still have X520 cards physically
present; `node_bonding_slaves=0` on cp-03 which has no card at all — alert rule is
`(node_bonding_slaves - node_bonding_active) != 0`, so cp-03 doesn't fire since 0-0=0). This is
**expected noise for the duration of the fallback**, not a new incident — do not chase it as a
hardware problem without first re-reading this entry and checking `git diff talos/talconfig.yaml`
for an uncommitted bond-storage-disable patch matching the live `down` state.

As of 2026-07-02 there is no `Silence` CR (silence-operator, see the nfsmount.conf precedent in
[[reference_node_exporter_duplicate_mountpoint_alerts]]) covering these two alerts, and the
talconfig.yaml change is uncommitted — both are gaps worth flagging to the user, not something
this agent should fix unilaterally (Silence creation and git commits are user-gated actions).
Revert path once replacement X520 cards are installed: remove the inline VLAN-200 patches,
uncomment the `bond-storage` `addresses:` blocks, and update cp-03's `bond-storage` deviceSelector
MACs (currently placeholder `xx:xx:xx:xx:xx:xx`, no card installed).

## Resolution (2026-07-07)

A replacement X520-DA2 was physically installed in cp-03. Verified via `talosctl dmesg`/`get links`
before migrating: both ports (`enp2s0f0`/`enp2s0f1`, MACs `90:e2:ba:e8:ea:00`/`:01`) probed cleanly
— no `-114`/HW Init failure anywhere in the boot buffer, unlike the original faulty card. One
non-blocking anomaly: `enp2s0f0` showed more boot-time SFP+ link flap cycles (8x) than its sibling
`enp2s0f1` (2x) before both settled to a stable `Up 10Gbps` — held stable for 2h17m+ before the
LACP migration, so treated as normal DAC/cold-insertion autoneg settling rather than a fault. Worth
rechecking first if `CephNodeNetworkBondDegraded` ever reappears specifically on cp-03.

`talos/talconfig.yaml` was reverted fleet-wide: VLAN-200 patches commented out (not deleted — kept
for easy fallback per user request) on all 5 nodes, `bond-storage` `addresses:` restored, cp-03's
placeholder deviceSelector MACs replaced with the real ones above. Applied live via
`task talos:apply` per node (cp-03 first, verified bond formed + `ceph -s` stayed healthy, then the
remaining 4). No reboots required for any node. Ceph briefly repeated the same
`OSD_SLOW_PING_TIME_BACK`/`_FRONT`-style slow-heartbeat `HEALTH_WARN` seen during the original
2026-06-18 cutover (MAC-table/ARP relearning after the interface change) — self-cleared to
`HEALTH_OK` within ~30s, no PG degradation.

The 3 fallback `silence-operator` Silences (`bond-storage-degraded-x520-fallback-ceph`,
`-node-exporter`, `ceph-node-network-packet-drops-x520-fallback`) were deactivated, since their
documented revert conditions were all met: dropped from `kustomization.yaml`'s resources list (so
they no longer apply) but kept on disk, relabeled `INACTIVE`, in case the same VLAN-200 fallback is
ever needed again. If `CephNodeNetworkBondDegraded`/`NodeBondingDegraded`/`CephNodeNetworkPacketDrops`
fire again on any node going forward, treat it as a **real** condition, not fallback noise — these
Silences are no longer wired into the Kustomization and won't suppress anything.
