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
| Storage bonds renamed to `bond-storage` on all 3 nodes | ✅ Done | talconfig.yaml |
| Multus CNI DaemonSet deployed in `kube-system` | ✅ Done | — |
| whereabouts IPAM deployed in `kube-system` | ✅ Done | — |
| `cni.exclusive: false` in Cilium values | ✅ Done | c4d405c |
| `NetworkAttachmentDefinition` `longhorn-storage` in `longhorn-system` | ✅ Done | af71355 |
| NAD IPAM routes patched (`"dst": "10.200.0.0/24"`) | ✅ Done | af71355 |
| NAD updated to `ipvlan l2` mode (was `macvlan bridge`) | 🔄 Pending push | — |
| `storageNetwork: "longhorn-system/longhorn-storage"` re-enabled | 🔄 Pending push | — |

The infrastructure is in place. The `storageNetwork` setting is currently empty — Longhorn
uses the default Cilium pod network. Instance-manager pods do **not** have macvlan
annotations and all volumes are healthy.

---

## The Blocker: macvlan Bridge Mode Cannot Route Host→Pod (Same Node)

### What happens when `storageNetwork` is set

1. Longhorn annotates each `instance-manager` pod with the Multus NAD.
2. Multus attaches a `lhnet1` secondary interface in the `10.200.0.64/26` range
   (macvlan child of `bond-storage`).
3. The Longhorn engine creates an iSCSI TGT that **binds to the macvlan IP** (storageIP).
4. The host's `iscsiadm` (run via `nsenter` in the host network namespace) attempts
   to discover the TGT at that storageIP.

### Why it fails for volumes whose engine lands on the same node as the TGT

macvlan creates a virtual NIC that is a **child of the host's physical NIC**. Bridge mode
specifically isolates the child from its parent at L2: packets sent from `bond-storage`
(host) destined for a macvlan child IP are **dropped by the kernel bridge** — the host
cannot reach its own macvlan children.

This is a fundamental kernel behaviour, not a misconfiguration. All 5 volumes stuck in
`Attaching` because every engine's TGT was unreachable from the local host's nsenter call.

### Cross-node path works fine

Packets from `bond-storage` on node A to a macvlan IP on node B travel over the physical
switch and arrive at node B's NIC as normal L2 frames — no macvlan isolation involved.
The `"routes": [{"dst": "10.200.0.0/24"}]` patch already in the NAD ensures the reply
path is symmetric.

---

## Solution: ipvlan L2 Mode

**ipvlan L2** is the correct mode for this use case:

- All interfaces (master `bond-storage` + every slave) share the same MAC address.
- **No bridge isolation**: the kernel can route from the host directly to its own ipvlan children.
- Cross-node: ARP works normally over the physical 10GbE switch (slaves respond to ARP with the
  shared bond-storage MAC; the switch delivers the packet to the correct node's port).
- **No static host routes needed**: each node already has a `/24` connected route via `bond-storage`,
  which covers the entire `10.200.0.64/26` IPAM pool.
- `ipvlan` binary is present at `/opt/cni/bin/ipvlan` on all nodes (deployed by Multus init container).

### Required changes

#### 1. Update the NAD (`nad/storage-nad.yaml`)

Change `type` and `mode` only — IPAM, routes, and MTU remain the same:

```json
{
  "cniVersion": "0.3.1",
  "name": "longhorn-storage",
  "type": "ipvlan",
  "master": "bond-storage",
  "mode": "l2",
  "mtu": 9000,
  "ipam": {
    "type": "whereabouts",
    "range": "10.200.0.64/26",
    "routes": [
      {"dst": "10.200.0.0/24"}
    ]
  }
}
```

#### 2. Re-enable `storageNetwork` in Longhorn values

```yaml
defaultSettings:
  storageNetwork: "longhorn-system/longhorn-storage"
```

No `talconfig.yaml` changes required — no node reboots needed.

### Why L2 over L3

ipvlan L3 suppresses ARP entirely. Cross-node routing would require static /32 host routes for
every pod IP (unknowable ahead of time) or per-node IPAM ranges with static /28 routes in
`talconfig.yaml` — implying Talos node reboots and complex config. L2 avoids all of this at
negligible cost (ARP for ~6 pod IPs cluster-wide).

---

## Pre-Flight Verification (Before Enabling `storageNetwork`)

```bash
# 1. Confirm ipvlan binary is available on all nodes
talosctl --nodes 10.60.0.201,10.60.0.202,10.60.0.203 read /opt/cni/bin/ipvlan

# 2. Verify no volumes are degraded/rebuilding before flip
kubectl -n longhorn-system get volumes

# 3. After enabling storageNetwork, watch instance-managers restart
kubectl -n longhorn-system get pods -l longhorn.io/component=instance-manager -w

# 4. Confirm storageIPs are in the 10.200.0.64/26 range
kubectl -n longhorn-system get replicas \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.storageIP}{"\n"}{end}'

# 5. Confirm host can reach an instance-manager's ipvlan IP
# (run from node, replace IP with actual storageIP)
talosctl --nodes 10.60.0.201 -- ping 10.200.0.65
```

---

## Current State

- **storageNetwork**: `"longhorn-system/longhorn-storage"` (enabled in values.yaml, pending Flux push).
- **NAD**: updated to `ipvlan l2` mode (pending Flux push).
- **Next action**: Push changes; monitor instance-manager rolling restart and verify storageIPs
  land in `10.200.0.64/26`.

---

## References

- [Longhorn storageNetwork docs](https://longhorn.io/docs/latest/advanced-resources/deploy/storage-network/)
- [ipvlan kernel docs](https://www.kernel.org/doc/html/latest/networking/ipvlan.html)
- Session log: `multus-nad-talos-setup` in `docs/SESSIONS.md`
