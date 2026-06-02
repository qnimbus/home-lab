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

## Community Research & Validation (2026-06-02)

### What Longhorn's own test suite uses

The Longhorn project's storage-network test suite uses exactly one NAD pattern:
**flannel as the outer plugin with ipvlan L3 as a delegate**. Flannel reads a per-node
subnet file and programs host-namespace routes on each node — effectively adding
`<node-subnet>/N dev <storage-NIC>` in the host kernel. With that route present, the ipvlan
L3 driver delivers same-host packets entirely within the kernel. No switch involved, no ARP.

Flannel cannot be used on a Talos+Cilium cluster (Cilium is the primary CNI). We replicate
what flannel automates:

| Flannel does | Our equivalent |
|---|---|
| Per-node subnet file (e.g. `192.168.1.0/24` for node 1) | `whereabouts` `node_slice_size: "/28"` → one /28 per node |
| Programs `<subnet> dev <storage-NIC>` on each host | Existing `/24` connected route on `bond-storage` covers same-host |
| Programs cross-node routes to other nodes' subnets | Talos static routes per node in `talconfig.yaml` |

### What the official docs say

Longhorn's storageNetwork docs are completely silent on the same-host iSCSI problem and CNI
type guidance. They only require "the NAD must be reachable across nodes." The same-host
failure is an underdocumented architectural constraint.

### What the homelab community does

Most operators who attempted storageNetwork on Cilium-based clusters gave up or fell back to
`CiliumNetworkPolicy` for workload isolation only. No public working example of ipvlan L3 +
Talos + Cilium exists — we are in novel territory, but the theory is sound and matches
Longhorn's own test approach.

### Ceph considered and deferred

Rook-Ceph was evaluated as an alternative. Ceph has native dual-network support: OSD pods
run with `hostNetwork: true`; setting `cluster_network: 10.200.0.0/24` in the `CephCluster`
CR directs OSD↔OSD replication onto the storage VLAN automatically — no Multus, no CNI
complexity. This definitively solves the storage-VLAN routing problem.

**Decision: proceed with Longhorn ipvlan L3 first.** Ceph migration cost (new cluster
deployment, full PVC data migration from all Longhorn volumes, ongoing Ceph operational
overhead) is not justified until ipvlan L3 has been given a proper attempt. Revisit Ceph if
Attempt 3 fails.

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

#### 1. NAD (`nad/storage-nad.yaml`) — change mode to `l3`, switch to per-node IPAM

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
    "range": "10.200.0.64/26",
    "node_slice_size": "/28"
  }
}
```

`node_slice_size: "/28"` allocates one /28 per node from the `/26` parent pool. With nodes
named `talos-cp-01`, `talos-cp-02`, `talos-cp-03` (alphabetical allocation order), expected:

| Node        | Allocated /28     | Usable IPs       |
|-------------|-------------------|------------------|
| talos-cp-01 | `10.200.0.64/28`  | `.65` – `.78`    |
| talos-cp-02 | `10.200.0.80/28`  | `.81` – `.94`    |
| talos-cp-03 | `10.200.0.96/28`  | `.97` – `.110`   |

**Prerequisite**: `node_slice_size` requires the whereabouts **node-slice controller** — a
separate Deployment in the whereabouts chart. Already running as
`whereabouts-whereabouts-chart-controller` in `kube-system`.

**NAD must be in `kube-system`**: the node-slice controller creates NodeSlicePools in
`kube-system` with an owner reference pointing to the NAD. If the NAD is in a different
namespace (e.g. `longhorn-system`), Kubernetes GC immediately deletes the NodeSlicePool
with `OwnerRefInvalidNamespace`. The `longhorn-nad` Kustomization must use
`targetNamespace: kube-system`. The Longhorn storageNetwork setting becomes
`kube-system/longhorn-storage`.

**Verify allocation after NAD is applied to kube-system**:
```bash
kubectl get nodeslicepool -n kube-system -o yaml
```

**Same-host routing** (no explicit routes needed): the host already has a `/24` connected
route for `10.200.0.0/24` via `bond-storage`. In L3 mode, when the host sends a packet to a
pod IP in that subnet, it exits to `bond-storage` and the ipvlan L3 driver delivers it
internally — no Ethernet frame ever hits the physical switch.

**Cross-node routing** (explicit routes required): L3 mode suppresses ARP across nodes. The
host on cp-01 has no way to discover that `10.200.0.85` lives on cp-02 without a static
route. Per-node `/28` allocation gives stable, predictable ranges that can be expressed as
static routes in `talconfig.yaml`.

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

## Implementation Plan: Attempt 3 (ipvlan L3)

### Files to change

| File | Change |
|---|---|
| `kubernetes/apps/storage/longhorn/nad/storage-nad.yaml` | `l2` → `l3`; add `node_slice_size: "/28"` |
| `talos/talconfig.yaml` | Per-node static routes for cross-node /28s |
| `kubernetes/apps/storage/longhorn/app/helmrelease.yaml` | Re-enable `storageNetwork` |

### Rollout order

`storageNetwork` must remain `""` throughout steps 1–6. Do not re-enable it until static
routes are live and validated on all three nodes.

1. Verify whereabouts node-slice controller is deployed (`kubectl get deploy -n kube-system`)
2. **Update NAD** — commit, push; Flux applies. No volume impact (storageNetwork still `""`)
3. **Check `NodeSlicePool`** — confirm /28 allocation matches the expected node→range table
4. **Update `talconfig.yaml`** — add cross-node routes; run `task talos:genconfig`
5. **Apply Talos configs one node at a time** (staggered to protect etcd quorum):
   cp-01 → wait `Ready` → cp-02 → wait `Ready` → cp-03
6. **Run all pre-flight checks** (see Pre-Flight Checklist above, especially step 6)
7. **Re-enable `storageNetwork: "kube-system/longhorn-storage"`** in Longhorn HelmRelease — commit, push; Flux applies
8. Watch instance-manager pods restart; confirm `lhnet1` IPs land in expected /28 ranges
9. Monitor volumes — all should reach `attached/healthy` within a few minutes

### Cross-node static routes (`talconfig.yaml`)

Each node needs routes only to the **other two** nodes' /28 ranges. Do NOT add a route for
the node's own /28 — the /24 connected route already covers it.

```yaml
# talos-cp-01: routes to cp-02 and cp-03 pod ranges
routes:
  - network: 10.200.0.80/28
    gateway: 10.200.0.202    # cp-02 bond-storage IP
  - network: 10.200.0.96/28
    gateway: 10.200.0.203    # cp-03 bond-storage IP

# talos-cp-02: routes to cp-01 and cp-03
routes:
  - network: 10.200.0.64/28
    gateway: 10.200.0.201    # cp-01 bond-storage IP
  - network: 10.200.0.96/28
    gateway: 10.200.0.203    # cp-03 bond-storage IP

# talos-cp-03: routes to cp-01 and cp-02
routes:
  - network: 10.200.0.64/28
    gateway: 10.200.0.201    # cp-01 bond-storage IP
  - network: 10.200.0.80/28
    gateway: 10.200.0.202    # cp-02 bond-storage IP
```

Route changes require a node reboot — apply one node at a time (step 5 above).

### Fallback options if Attempt 3 fails

| Option | Change | Risk |
|---|---|---|
| ipvlan L3S | `"mode": "l3s"` in NAD | L3S passes traffic through host netfilter; unknown interaction with Cilium eBPF |
| Ceph/Rook migration | Replace Longhorn entirely | High migration cost; definitively solves the problem |

---

## Incident: All volumes stuck in `attaching` (2026-06-02)

### Symptoms

All 5 Longhorn volumes (`pgadmin`, `waha`, `grafana`, `alertmanager`, `prometheus`) were in
`attaching` state with `unknown` robustness. Consumer pods were stuck in `Init:0/1` or
`Init:0/2`. All engines were `stopped`; the engine for `pvc-74f992be` (pgadmin) had no node
assigned at all.

### Root cause

The `longhorn-manager` pod on `talos-cp-02` had accumulated **31 restarts**. Each restart cycled
the cp-02 `instance-manager` pod, leaving replica objects with a blank `.spec.instanceManager`
reference (`instancemanager.longhorn.io "" not found` in manager logs). When the instance manager
came back, Longhorn couldn't reconcile those replicas until the reference was re-populated.

The cp-03 instance manager also restarted (49 min before detection), causing the cp-03 replicas
to enter `stopped` state. The cascade left every engine with no running replicas to connect to,
so all engines stayed `stopped` and volumes stayed in `attaching`.

### How it self-healed (no manual action required)

Longhorn's reconciler recovered automatically once all three instance managers were running:

1. The cp-02 instance manager came up clean. Within seconds, Longhorn started the stopped
   replicas (observed in manager log: `state updated from stopped to running`).
2. Engines started on cp-03 (the node the consumer pods targeted), reached quorum with the
   running cp-01 replicas, and transitioned volumes to `attached`.
3. Longhorn created new cp-02 replicas for volumes that had lost their cp-02 copy, scheduling
   background rebuilds from the healthy cp-01 replicas.
4. Consumer pods progressed through init containers and reached `Running` within ~2 minutes of
   the last instance manager restart.

### Diagnosis steps taken

```bash
# 1. Renew expired MCP token
bash scripts/mcp.sh renew-token 8h

# 2. Check volume state (all showed attaching/unknown)
kubectl -n longhorn-system get volumes.longhorn.io

# 3. Check instance managers (noted cp-02 IM was 34s old — just restarted)
kubectl -n longhorn-system get pods -l longhorn.io/component=instance-manager

# 4. Check engine state (all stopped; pgadmin engine had no node)
kubectl -n longhorn-system get engines.longhorn.io

# 5. Check replica state (cp-01 replicas running; cp-02/cp-03 stopped, no IM ref)
kubectl -n longhorn-system get replicas.longhorn.io

# 6. Check longhorn-manager pod restarts (cp-02 had 31 restarts)
kubectl -n longhorn-system get pods -l app=longhorn-manager

# 7. Tail cp-02 manager log — found "" not found errors, then saw replica start
kubectl -n longhorn-system logs longhorn-manager-dgz5v -c longhorn-manager --tail=100
```

### Outcome

All volumes `attached/healthy` within ~3 minutes. No data loss. WAHA recovered first; Grafana,
Alertmanager, and Prometheus had short-lived `degraded` status while new cp-02 replicas rebuilt.

### Follow-up

The repeated cp-02 `longhorn-manager` crashes are unrelated to the storageNetwork work but
warrant investigation. Consider checking the cp-02 manager's OOMKill history and node pressure.

---

## Current State

- **storageNetwork**: `kube-system/longhorn-storage` — enabled (Attempt 3).
- **NAD**: `ipvlan l3` + `node_slice_size: "/28"` in `kube-system`.
- **NodeSlicePool**: live in `kube-system`; cp-01→.64/28, cp-02→.80/28, cp-03→.96/28.
- **talconfig.yaml**: cross-node /28 routes applied to all nodes (no reboot required).
- **Pending validation**: confirm `lhnet1` IPs land in correct /28 ranges; confirm same-host
  iSCSI attach succeeds. See Pre-Flight Checklist step 4–6.

---

## References

- [Longhorn storageNetwork docs](https://longhorn.io/docs/latest/advanced-resources/deploy/storage-network/)
- [ipvlan kernel docs](https://www.kernel.org/doc/html/latest/networking/ipvlan.html)
- Session log: `multus-nad-talos-setup` in `docs/SESSIONS.md`
