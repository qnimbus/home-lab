# Longhorn Storage Network Isolation — Tracking Document

## Goal

Move Longhorn engine↔replica traffic from the Cilium pod network (`10.42.x.x`) onto the
dedicated storage VLAN (`10.200.0.0/24`) via Multus CNI. Benefits:

- Eliminates a class of false replica faults caused by Cilium eBPF convergence (~10 min
  when a node goes down), which can trigger scheduling deadlocks on Longhorn volumes.
- Moves all replica I/O from the 1 GbE management NIC to the 2×10 GbE SFP+ LACP bonds.

---

## What Has Been Implemented (Already in Git)

| Component | Status | Commit |
|-----------|--------|--------|
| Storage bonds renamed to `bond-storage` on all 3 nodes (talconfig.yaml) | ✅ Done | — |
| Multus CNI DaemonSet deployed in `kube-system` | ✅ Done | — |
| whereabouts IPAM deployed in `kube-system` | ✅ Done | — |
| `cni.exclusive: false` in Cilium values | ✅ Done | c4d405c |
| `NetworkAttachmentDefinition` `longhorn-storage` in `longhorn-system` | ✅ Done | af71355 |
| NAD type changed to `ipvlan l2` (was `macvlan bridge`) | ✅ Done | 872efe6 |
| `storageNetwork` disabled (reverted twice after same-host failures) | ✅ Done | 84bd3f1 |

Current cluster state: `storageNetwork: ""` — Longhorn uses the default Cilium pod
network. All instance-manager pods are running without Multus annotations and all
volumes are healthy.

---

## Root Cause: Same-Host iSCSI Connectivity

### How Longhorn storageNetwork works

1. Longhorn annotates each `instance-manager` pod with the Multus NAD name.
2. Multus attaches a secondary interface (`lhnet1`) to the pod with an IP from the
   storage VLAN IPAM range.
3. The Longhorn engine creates an iSCSI TGT that **binds to the `lhnet1` IP** (storageIP).
4. The host's `iscsiadm` (run via `nsenter` in the host network namespace) issues:
   ```
   iscsiadm -m discovery -t sendtargets -p <storageIP>
   ```
   to discover and connect to the TGT, creating `/dev/longhorn/<volume>`.

### The invariant that makes this hard

Step 4 always runs in the **host's network namespace** — it uses `nsenter` into
`/host/proc/<pid>/ns/net`. That means the HOST kernel must be able to reach the
engine's `lhnet1` IP. When the engine and the `iscsiadm` call are on the **same node**,
the packet must travel from the host's physical interface to a virtual interface on the
same kernel — without ever leaving the machine.

This same-host path is what both attempted CNI types fail to provide.

---

## Attempt 1: macvlan bridge — FAILED

macvlan creates a virtual NIC that is a child of the host's physical NIC (`bond-storage`).
In **bridge** mode the kernel bridge explicitly isolates the parent from its children at L2:
packets sent from `bond-storage` (host) destined for a macvlan child IP are **dropped by
the bridge**. No route, no ARP override, can fix this — it is enforced in the kernel bridge
code path.

**Observed**: all 5 volumes stuck in `Attaching`; `iscsiadm` never reached the TGT.

Cross-node traffic works fine (pod A → switch → pod B on a different node).

---

## Attempt 2: ipvlan l2 — FAILED

ipvlan L2 slaves share the parent's MAC address. There is no kernel bridge isolation.
However, the same-host path still fails for a different reason:

1. Host at `10.200.0.203` ARPs for the pod at `10.200.0.65` on `bond-storage`.
2. The ipvlan slave responds: "I am `10.200.0.65`, MAC is `<bond-storage MAC>`."
3. The host sends an Ethernet frame: src=`bond-storage MAC`, dst=`bond-storage MAC`,
   IP dst=`10.200.0.65` — **destined for its own MAC**.
4. The frame goes out on the physical bond. The switch receives it on cp-03's port.
5. The switch must deliver a frame whose destination MAC belongs to cp-03's port **back
   to that same port** (hairpin / reflective relay). Most switches do **not** do this by
   default.
6. The frame is dropped. `iscsiadm` reports "Host is unreachable".

**Observed** (from Multus logs): `lhnet1` attached successfully with IP `10.200.0.66`;
cross-node replica connections from `10.200.0.65 → 10.200.0.66` worked over the storage
VLAN. Same-host `iscsiadm` discovery failed:
```
iscsiadm: cannot make connection to 10.200.0.65: Host is unreachable
```

---

## Correct Solution: ipvlan L3 + per-node /28 ranges + static host routes

In **ipvlan L3** mode:
- The kernel creates a virtual interface that routes at L3 — no ARP, no Ethernet framing.
- Packets from the host to a local L3 slave are handled entirely within the kernel routing
  table. **No packet ever goes to the physical switch for same-host traffic.**
- The host-side route for the slave IP is added automatically by the kernel when the ipvlan
  slave is created: `10.200.0.65/32 dev bond-storage` in the host netns.

For **cross-node** traffic in L3 mode, ARP is suppressed — the host needs static routes
to reach remote nodes' pod IPs. Since pod IPs are dynamically allocated by whereabouts,
we must use **per-node IP ranges** that can be statically routed:

| Node     | whereabouts range | bond-storage IP |
|----------|-------------------|-----------------|
| cp-01    | `10.200.0.64/28`  | `10.200.0.201`  |
| cp-02    | `10.200.0.80/28`  | `10.200.0.202`  |
| cp-03    | `10.200.0.96/28`  | `10.200.0.203`  |

Each node then adds static routes to the other two nodes' /28 ranges via their bond-storage
IP. Example for cp-01:
```yaml
routes:
  - network: 10.200.0.80/28
    gateway: 10.200.0.202
  - network: 10.200.0.96/28
    gateway: 10.200.0.203
```

### Required changes

#### 1. NAD (`nad/storage-nad.yaml`) — change type and range

```json
{
  "cniVersion": "0.3.1",
  "name": "longhorn-storage",
  "type": "ipvlan",
  "master": "bond-storage",
  "mode": "l3",
  "mtu": 9000,
  "ipam": {
    "type": "whereabouts",
    "range": "10.200.0.64/28",
    "routes": [
      {"dst": "10.200.0.0/24"}
    ]
  }
}
```

> **Note**: A single shared `/28` range is NOT enough for L3 — each node must use its
> own range. whereabouts does not support per-node pools natively in a single NAD.
> Options:
> - Three separate NADs (`longhorn-storage-cp01`, etc.) with a custom annotation per node.
>   Complex; Longhorn storageNetwork only references one NAD name.
> - Use whereabouts `node_slice_size` annotation (if supported in the deployed version).
> - Accept a single `/26` pool and use ipvlan L3 with a **loopback trick** (see below).

#### Loopback trick alternative (avoids per-node NADs)

Because ipvlan L3 allows the host to reach same-node pod IPs via kernel routing, a single
`/26` pool still works for same-host — the kernel adds a `/32` host route automatically.
The remaining problem is cross-node: without static routes the host can't ARP for remote
pod IPs.

**Workaround**: add a static route on each node for the **entire pod /26** via its own
bond-storage IP (self-route), which forces the kernel to do L3 lookups for all /26
addresses. Then also add a route for each remote node's expected /26 (same /26 — this
doesn't help distinguish nodes). This doesn't fully solve cross-node without per-node
ranges.

**Bottom line**: per-node /28 ranges + static routes in talconfig.yaml is the correct
approach. It requires Talos node reboots (one at a time, staggered).

#### 2. talconfig.yaml — add static routes per node

Under each node's `bond-storage` interface configuration, add `routes:` pointing to the
other two nodes' /28 ranges via their `bond-storage` IP. Must be added to each of the 3
nodes, then `task talos:genconfig` re-run and applied one node at a time.

#### 3. Re-enable `storageNetwork` in Longhorn values

```yaml
defaultSettings:
  storageNetwork: "longhorn-system/longhorn-storage"
```

---

## Pre-Flight Checklist (Before Next Attempt)

```bash
# 1. Confirm ipvlan binary on all nodes (already present)
talosctl --nodes 10.60.0.201,10.60.0.202,10.60.0.203 ls /opt/cni/bin/ | grep ipvlan

# 2. Verify static routes reach cross-node /28 ranges after talconfig apply
talosctl --nodes 10.60.0.201 get routes | grep '10\.200\.0\.'

# 3. Verify no volumes degraded/rebuilding before enabling
kubectl -n longhorn-system get volumes

# 4. After enabling storageNetwork, watch instance-manager restart
kubectl -n longhorn-system get pods -l longhorn.io/component=instance-manager -w

# 5. Confirm storageIPs are in expected /28 range per node
kubectl -n longhorn-system get replicas \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.storageIP}{"\n"}{end}'

# 6. Confirm same-host iscsiadm can reach pod IP (run on cp-03, use actual assigned IP)
talosctl --nodes 10.60.0.203 -- nsenter --net=/proc/1/ns/net -- \
  iscsiadm -m discovery -t sendtargets -p 10.200.0.97
```

---

## Current State

- **storageNetwork**: `""` — disabled. All volumes healthy on Cilium network.
- **NAD**: `ipvlan l2` mode (872efe6) — in Git but storageNetwork disabled so not in use.
  Update NAD to `ipvlan l3` before next attempt.
- **talconfig.yaml**: no static routes yet — required before next attempt.
- **whereabouts range**: currently `/26` shared pool — must change to per-node `/28`.
- **Next session**: plan and apply ipvlan L3 + per-node /28 + talconfig static routes.

---

## References

- [Longhorn storageNetwork docs](https://longhorn.io/docs/latest/advanced-resources/deploy/storage-network/)
- [ipvlan kernel docs](https://www.kernel.org/doc/html/latest/networking/ipvlan.html)
- Session log: `multus-nad-talos-setup` in `docs/SESSIONS.md`
