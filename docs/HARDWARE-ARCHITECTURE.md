# Proposed Hardware Architecture — 5-Node Expansion

> **Status:** PROPOSED (2026-06-06). Not yet implemented. This document captures the target
> hardware distribution, node-role assignment, and Rook-Ceph topology for the planned expansion
> from the current 3-node cluster to **5 nodes**. It supersedes the abandoned Longhorn storage-VLAN
> effort (see [history/longhorn-storage-network.md](history/longhorn-storage-network.md)) — the storage tier is
> **Rook-Ceph** on the existing `10.200.0.0/24` bond fabric.
>
> Two physical items must be **verified on real hardware** before this is committed (flagged inline
> as ⚠️ **VERIFY**): MS-A2 slot count, and whether the Lenovo "WLAN" M.2 slots carry PCIe (NVMe-capable).

---

## Goal

A resilient Talos Linux + FluxCD + Rook-Ceph cluster with good storage performance, **sane failure
domains**, and efficient workload placement. The driving design priority chosen for this build is
**capacity-first Ceph** (maximise usable storage) while still retaining single-host self-heal.

---

## Nodes & Tiers

Five bare-metal nodes across three capability tiers. Strength order: **MS-A2 ≫ M90q (×2) > M920q (×2)**.

| Node | Tier | CPU | RAM | 10 GbE | Tier rationale |
|------|------|-----|-----|--------|----------------|
| **MS-A2** (Minisforum) | Premium | Ryzen 9 9955HX, 16C/32T | 96 GB **ECC** DDR5 (fixed) |  X710 dual SFP+ | Fastest CPU, ECC, most M.2 slots → control plane anchor + premium workloads + OSD |
| **M90q #1** (Lenovo) | Workhorse | i5-10500T, 6C/12T | 64 GB | X520 dual SFP+ | HT + 2 fast M.2 slots → storage + general compute |
| **M90q #2** (Lenovo) | Workhorse | i5-10500T, 6C/12T | 64 GB | X520 dual SFP+ | As above |
| **M920q #1** (Lenovo) | Light | i5-8500T, 6C/6T | 64 GB | X520 dual SFP+ | Oldest, no HT, single fast slot → OSD host (no etcd) |
| **M920q #2** (Lenovo) | Light | i5-8500T, 6C/6T | stock (16–32 GB) | X520 dual SFP+ | As above → control plane + light worker |

**RAM distribution:** the interchangeable pool is **6× 32 GB Kingston Fury Impact DDR4-3200**
SO-DIMMs. These populate **M90q #1, M90q #2, and M920q #1 at 64 GB** (2×32 each = all 6 modules).
**M920q #2** runs whatever stock RAM arrives (16–32 GB) — adequate for a light control-plane node
(etcd + apiserver want ~2–4 GB). MS-A2's 96 GB ECC is fixed and never reassigned.

> This allocation **de-risks the unknown M90q stock RAM**: the Fury modules are placed deterministically
> on the nodes that need the headroom, so the build does not depend on what the M90q ship with.

---

## M.2 Slot Budget (the binding constraint)

This architecture is shaped less by CPU/RAM than by **how many full-speed NVMe slots each chassis
exposes**. The slot inventory:

| Node | Full-speed slots (2280, x4) | Boot-only slot | OSD-grade homes |
|------|------------------------------|----------------|-----------------|
| **MS-A2** | **3×** 2280 PCIe **4.0** x4 (slots 2/3 also take **22110** PLP) | — | 3 |
| **M90q #1 / #2** | **2×** 2280 PCIe **3.0** x4 | 2230 WLAN slot (PCIe x1, see note) | 2 each |
| **M920q #1 / #2** | **1×** 2280 PCIe x4 | 1× slow 2230/short (boot-class) | 1 each |

Design rules derived from the slot budget:

1. **An OSD and a low-latency etcd disk both want a full-speed 2280.** A node with only one such slot
   (M920q) can host **either** an OSD **or** etcd — not both. Therefore **an OSD-hosting M920q must not
   run etcd** (its only fast slot is consumed; etcd would fall onto the slow boot slot — the fsync trap
   we avoid).
2. **MS-A2's three slots dissolve the OSD-vs-local-scratch trade-off** — it runs boot+etcd, an OSD,
   **and** a local NVMe scratch on three separate devices.
3. **A Talos boot disk does not need bandwidth** (read-mostly at startup, never on the etcd/Ceph hot
   path), so it is the right tenant for any slow/short slot. The M920q's second slot already runs a
   2280 at reduced lanes on the live cluster (cp-01/cp-02 each show two `nvmeXn1`), which is exactly
   how boot is parked there.

> ⚠️ **VERIFY — MS-A2 slot count:** assumed 3× M.2. Confirm on the physical unit.
>
> ⚠️ **VERIFY — Lenovo WLAN/2230 slots are PCIe (Key-M), not Key-E/CNVio:** many Tiny WLAN slots carry
> only Wi-Fi/BT signalling and **will not enumerate an NVMe SSD**. The analogous M920q slot works on
> the live cluster, so the M90q slot probably carries PCIe too — but confirm it appears as `nvmeXn1`
> before relying on it. Repurposing it also disables onboard Wi-Fi/BT (irrelevant for wired nodes).

---

## Final Node Roles & Disk Placement

| Node | K8s roles | etcd | Slot 1 (OSD/data) | Slot 2 | Slot 3 |
|------|-----------|:----:|-------------------|--------|--------|
| **MS-A2** | CP + OSD + **premium worker** | ✅ | **Crucial T500 2 TB** — OSD | **Goodram P44N 1 TB** — boot + etcd | **1 TB NVMe** — local scratch (AI / build / Plex) |
| **M90q #1** | CP + OSD + worker | ✅ | **Crucial T500 2 TB** — OSD | **Kingston NV3 1 TB** — boot + etcd | *(boot → 2230 if trick applied; see Growth Path)* |
| **M90q #2** | OSD + worker | — | **Crucial T500 2 TB** — OSD | NV3 / Phison — boot | *(reserved OSD bay if trick applied)* |
| **M920q #1** | OSD + light worker | — | **Crucial P310 2 TB** — OSD #4 *(its one fast slot)* | 1 TB 2280 — boot *(slow slot)* | — |
| **M920q #2** | CP + light worker | ✅ | **1 TB NVMe** — boot + etcd *(its one fast slot)* | slow slot — spare/scratch | — |

**Control plane / etcd: MS-A2 + M90q #1 + M920q #2** (3 members — kept at 3, not 5, for etcd write
latency). Placement rationale:

- **One member per tier / hardware generation** — a thermal, PSU, or firmware fault affecting one
  chassis type cannot take quorum.
- **ECC-anchored on MS-A2** — an unprotected memory bit-flip in the etcd datastore is catastrophic
  corruption; the ECC node anchors quorum.
- **Never on M920q #1** — its single fast slot is the 4th OSD, so etcd has no fast home there.
- Colocation with OSDs/workloads on MS-A2 / M90q #1 is safe: Talos runs etcd as a **guaranteed-QoS
  static pod**, and every etcd member sits on a full-speed 2280 **separate** from any OSD device.

> etcd peer traffic stays on the management subnet (`advertisedSubnets: ["10.60.0.0/24"]`) — it never
> crosses the storage VLAN, consistent with current cluster policy.

---

## Rook-Ceph Topology

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| OSD hosts | **4** — MS-A2, M90q #1, M90q #2, M920q #1 | ≥4 hosts is the threshold for single-host **self-heal** under `size=3` |
| OSD devices | 3× **Crucial T500 2 TB** (DRAM, TLC) + 1× **Crucial P310 2 TB** (DRAM-less) | T500s are the only DRAM-cached drives → the performance backbone |
| Replication | `size=3`, `min_size=2` | Standard safe replicated config; avoid `size=2/min_size=1` (single-failure data loss) |
| Failure domain | `host` | One OSD per host → clean host-level domain |
| Raw / usable | 8 TB raw → **~2.67 TB usable** (~2.2 TB at 85 % nearfull) | 8 TB ÷ 3 replicas |
| Device classing | P310 2 TB stays in the main pool, with **`ceph osd primary-affinity <p310-osd> 0`** | Keeps the one DRAM-less OSD holding replicas (for the 4th failure domain) but off the read hot path |

### Why these specific drives

- **The 3× T500 are the only primary-grade OSDs** — they have DRAM cache + real TLC, giving
  predictable fsync latency and endurance under Ceph's write-heavy BlueStore. The pool is kept
  T500-homogeneous except for the deliberate 4th OSD.
- **DRAM-less drives are otherwise kept out of Ceph.** NV3 / P310 / Goodram are fine for boot, etcd
  (tiny WAL writes), and local PVs, but as primary OSDs they show poor sustained random-write latency
  and faster wear. The **one** exception is the P310 2 TB as the 4th OSD — accepted purely to buy the
  4th failure domain, and neutralised on reads via `primary-affinity 0`.

### Self-heal behaviour & residual risk

With `size=3` over **4** hosts, losing one host leaves a legal home for the orphaned third replica on
the surviving 4th host → Ceph **self-heals back to full redundancy** while the failed host is still
down. (A 3-host `size=3` cluster cannot do this — it sits degraded until the host returns, and a disk
failure in that window means data loss. The 4th host is what removes that risk.)

**Residual risk:** the normal homelab one — do not run **two** hosts down simultaneously, and watch for
`HEALTH_WARN`. Capacity is gated by the smallest host and CRUSH weighting; keep pool utilisation
conservative.

---

## Growth Path (M90q 2230-slot trick)

The M90q WLAN/2230 slot can be repurposed as a **PCIe x1 boot SSD** (as already done on the M920q),
exiling boot off the fast 2280 slots. This **does not change the recommended 4-host topology** — the
M90q were never slot-starved, and a second OSD crammed into an M90q shares that host's failure domain
(adds raw TB, **zero** added fault tolerance).

Its real value is a **friction-free capacity-first growth path**:

- **Apply the trick, move M90q boot to the 2230 slot, and bank the freed 2280 slots as empty OSD bays.**
  When a 4th/5th T500 is purchased, it drops straight into a full-speed bay — no chassis teardown, no
  boot-disk juggling, no etcd migration. This is how this cluster scales storage: **bigger/more OSDs
  into existing fast bays**, not more chassis.
- **Optional 5-OSD-host variant (extra failure domain now):** relocate etcd off M920q #2 onto M90q #2
  (which gains a spare 2280 via the trick, boot on its 2230), then promote **M920q #2 to a 5th OSD
  host** with a 1 TB drive → 5 failure domains, more rebalance headroom on a host loss, ~3 TB usable.
  Deferred unless the extra domain is wanted immediately.

---

## Kubernetes Scheduling

| Mechanism | Plan |
|-----------|------|
| Labels | `node-role.kubernetes.io/control-plane` (auto); `storage=true` on OSD hosts (Rook `nodeAffinity` target); tier labels `node.homelab/tier=premium\|workhorse\|light` |
| Taints | **Do not blanket-taint the control plane** — MS-A2 is both CP and the premium worker. Optionally taint **only M920q #2** (`control-plane:NoSchedule`, tolerated by system/light add-ons) to keep it lean. **Do not taint OSD nodes** — they are the main workers. |
| Failure domain | Pod anti-affinity across `kubernetes.io/hostname` for HA app replicas |

**Workload placement:**

- **MS-A2 (premium):** RAM-hungry / AI-inference / database / build workloads, plus anything benefiting
  from the **local NVMe scratch** (slot 3) — AI model weights, build cache, Plex transcode. *Note:* the
  9955HX iGPU (Radeon 610M) is weak for hardware transcode — plan on CPU transcode (16C handles several
  streams) or a dedicated GPU for many HW-encoded streams.
- **M90q (workhorse):** general stateful/stateless apps on Ceph-RBD storage.
- **M920q (light):** control plane, monitoring agents, light add-ons — keep heavy workloads off.

---

## 10 GbE Network Design

Reuses the existing `10.200.0.0/24` storage fabric and policy (see [CLUSTER.md](CLUSTER.md)).

- **LACP bond (802.3ad)** across both X520 ports (MS-A2 on its SFP+), **MTU 9000 (jumbo)**, with mgmt
  (`10.60`) and storage (`10.200`) carried as VLANs over the bond. LACP gives 2×10 G aggregate plus
  port-level resilience; per-flow stays capped at 10 G.
- **Converged Ceph public + cluster network** on the storage VLAN. Do **not** physically split into a
  separate Ceph cluster network yet — with 4 NVMe OSDs the bottleneck is the 10 G link itself, and
  splitting prematurely just halves client bandwidth. Revisit only if monitoring shows replication
  saturating the link.
- **All OSD nodes on 10 GbE** (all five have it; OSD hosts mandatory, light CP nodes benefit as
  clients).

---

## Open Decisions / Action Items

1. ⚠️ **VERIFY** MS-A2 slot count (assumed 3×) and the Lenovo 2230 slots' PCIe/NVMe capability.
2. Confirm the cheap boot drives' form factor against the target slots (2280 at reduced lanes is fine).
3. **Future capacity:** a small **22110 PLP** SSD in an MS-A2 slot 2/3 would be an ideal upgraded etcd
   home (safe, low-latency fsync) and/or Ceph `block.db`/WAL device — earmark as the one high-value
   purchase.
4. **Future capacity-first scaling:** buy a 4th/5th T500 2 TB and drop into the banked M90q OSD bays
   (raises usable capacity without adding chassis).
5. Next step when approved: generate the GitOps artifacts — Rook `CephCluster` (4 OSD hosts,
   `size=3/min_size=2`, host domain, P310 `primary-affinity 0`, `storage` `nodeAffinity`) + Talos
   `talconfig` `installDiskSelector` and node-label/role patches.

---

## Drive Inventory Reference

| Drive | Class | Role in this design |
|-------|-------|---------------------|
| 3× Crucial T500 2 TB (DRAM, TLC) | Primary OSD | Ceph OSDs (MS-A2, M90q #1, M90q #2) |
| Crucial P310 2 TB (DRAM-less) | Secondary OSD | Ceph OSD #4 (M920q #1), `primary-affinity 0` |
| Goodram IRDM Pro P44N 1 TB (DRAM-less, Gen4) | Boot/etcd | MS-A2 boot + etcd |
| 2–3× Kingston NV3 1 TB (DRAM-less/HMB) | Boot/etcd/scratch | M90q boot+etcd, M920q #2 boot+etcd, MS-A2 local scratch |
| Crucial P310 1 TB (DRAM-less) | Boot/etcd | spare boot/etcd |
| Phison E15T 256 GB (OEM, boot-class) | Boot | non-etcd boot (M90q #2) |
| AirDisk 128 GB (budget boot-class) | Boot | non-etcd boot / 2230 trick |
