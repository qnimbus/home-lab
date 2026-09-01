---
name: ceph-packetdrops-eee-and-roles-ruled-out
description: 2026-09-01 — neither Ceph mon/mgr/OSD role placement nor Energy Efficient Ethernet (EEE/802.3az) differentiates cp-03/worker-02 (affected by CephNodeNetworkPacketDrops) from cp-02/worker-01 (unaffected)
metadata:
  type: project
---

**Context:** continuing the `e1000e` RX-ring-exhaustion investigation
([[reference_e1000e_ring_buffer_drops_not_softirq]], [[project_ceph_packetdrops_other_consumers_check]]).
Checked two new candidate differentiators between the affected nodes (`cp-03`, `worker-02`) and
the unaffected ones (`cp-02`, `worker-01`) — both came back negative (no differentiation found).

**1. Ceph role placement (live-verified 2026-09-01, `ceph osd tree`/`ceph mon dump`/`kubectl -n
rook-ceph get pods -o wide`):**

| Node | OSDs | mon | mgr |
|---|---|---|---|
| cp-01 (igc, unaffected — different NIC family entirely) | osd.0, osd.3 | mon.a | mgr-b (**active**) |
| cp-02 (e1000e, unaffected) | osd.1, osd.5 | — | mgr-a (standby) |
| cp-03 (e1000e, **affected**) | osd.2, osd.4 | — | — |
| worker-01 (e1000e, unaffected) | osd.7, osd.8 | mon.e | — |
| worker-02 (e1000e, **affected**) | osd.6, osd.9 | mon.d | — |

All 4 e1000e nodes host exactly 2 OSDs each — no count differentiator. Mon presence doesn't
track affected-ness either: worker-01 (unaffected) and worker-02 (affected) both host a mon;
cp-02 (unaffected) and cp-03 (affected) both have no mon. Mgr presence is the same story (cp-02
has a standby mgr, is unaffected; cp-03 has neither mon nor mgr, is affected). **No Ceph role
combination explains the affected/unaffected split** — ruled out as a lead. `ceph -s` was
`HEALTH_OK`, 33 pgs active+clean, 10/10 OSDs up at check time.

**2. EEE (Energy Efficient Ethernet / IEEE 802.3az) on `eno1` — checked via `kubectl debug
node/<node> --image=nicolaka/netshoot -- sleep 3600` (this sets `hostNetwork: true`
automatically, so `ethtool` inside the debug pod sees the real physical `eno1` directly — no
`nsenter`/chroot needed; the earlier assumption in
[[reference_e1000e_ring_buffer_drops_not_softirq]] that this required more machinery was overly
cautious, `kubectl debug node/` alone is sufficient). Checked all 4 e1000e nodes:**

All 4 (`cp-02`, `cp-03`, `worker-01`, `worker-02`) report **byte-for-byte identical**
`ethtool --show-eee eno1` output:
```
EEE status: enabled - inactive
Tx LPI: 17 (us)
Supported EEE link modes:  100baseT/Full, 1000baseT/Full
Advertised EEE link modes:  100baseT/Full, 1000baseT/Full
Link partner advertised EEE link modes:  Not reported
```
All 4 also show identical link state: `Speed: 1000Mb/s`, `Duplex: Full`, `Link detected: yes`.

`enabled - inactive` means the driver has EEE turned on and is advertising it, but it is **not
currently active** (not in an LPI low-power cycle) — consistent with `Link partner advertised EEE
link modes: Not reported`, i.e. the upstream switch port either doesn't support/advertise EEE or
the driver can't read its advertisement, so LPI is never actually negotiated active. Since this
state is identical across all 4 nodes regardless of affected status, **EEE is ruled out as the
differentiator** between cp-03/worker-02 and cp-02/worker-01. It remains theoretically possible
that EEE contributes to the drop mechanism *uniformly* across all 4 (i.e., a necessary-but-not-
sufficient factor), but it cannot explain why only 2 of the 4 nodes actually alert — that split
must come from something else (burst timing/PG placement/hot-object locality per
[[project_ceph_packetdrops_other_consumers_check]], not a static NIC config difference).

Given "enabled - inactive" (LPI never actually negotiates), disabling EEE defensively
(`ethtool -s eno1 eee off` — not persistent across reboot without a Talos-unsupported
workaround, same caveat as ring sizing) is low-value: there's no evidence LPI is ever entered in
practice on this link, so there's nothing for a wake-latency fix to remove.

**Net effect on the investigation:** neither of these two new hypotheses differentiates the
affected pair from the unaffected pair. The ring-exhaustion mechanism itself
([[reference_e1000e_ring_buffer_drops_not_softirq]]) remains confirmed and unchallenged; what
still differentiates *which* nodes alert on a given burst remains unidentified — most likely
burst-timing/hot-PG-locality (which OSDs happen to receive the bursty client I/O) rather than a
static per-node hardware/config difference, per the existing note in
[[project_ceph_packetdrops_other_consumers_check]].
