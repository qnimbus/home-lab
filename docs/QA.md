# Cluster Q&A — Operational Knowledge Log

Concise answers to questions that came up during cluster operation. Each entry captures the *why* so it's useful months later.

---

## Table of Contents

**Storage**
- [Longhorn CSI components are in CrashLoopBackOff / no pods created for `longhorn-csi-plugin`](#longhorn-csi-components-are-in-crashloopbackoff--longhorn-csi-plugin-daemonset-has-0-pods)
- [Why was routing Longhorn replica traffic onto the storage VLAN abandoned?](#why-was-routing-longhorn-replica-traffic-onto-the-storage-vlan-abandoned)

**Networking**
- [Why does cp-03 show many `eth0: renamed from tmp<random>` messages?](#why-does-the-talos-console-for-cp-03-show-many-eth0-renamed-from-tmprandom-kernel-messages)
- [Why can't I reach the cluster nodes (both VLANs) while the internet works fine?](#why-cant-i-reach-the-cluster-nodes-both-vlans-while-the-internet-works-fine)
- [A single iperf3 stream over the storage bond tops out at ~9.7 Gbit/s — is the LACP bond broken? (+ how to benchmark the storage fabric)](#a-single-iperf3-stream-over-the-storage-bond-tops-out-at-97-gbits--is-the-lacp-bond-broken)
- [Why does an externally-exposed app get `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` even though its Envoy certificate looks correct?](#why-does-an-externally-exposed-app-get-err_ssl_version_or_cipher_mismatch-even-though-its-envoy-certificate-looks-correct)

**Cluster Recovery / Unclean Shutdown**
- [After a simultaneous power-off, the dashboard shows ~90 failed pods — but the cluster looks healthy. What happened?](#after-a-simultaneous-power-off-of-all-nodes-the-dashboard-shows-90-failed-pods-and-a-failed-deployment--but-the-cluster-looks-healthy-what-happened)
- [How do I recover when Cilium and CoreDNS are both gone simultaneously?](#how-do-i-recover-when-cilium-and-coredns-are-both-gone-simultaneously)
- [A HelmRelease is Stalled with `MissingRollbackTarget` — how do I recover?](#a-helmrelease-is-stalled-with-missingrollbacktarget--how-do-i-recover)
- [Longhorn finalizer patches fail with "failed calling webhook" — why?](#longhorn-finalizer-patches-fail-with-failed-calling-webhook--why)
- [flux-instance is stuck uninstalling and Flux CRDs have disappeared — how do I recover?](#flux-instance-is-stuck-uninstalling-and-flux-crds-have-disappeared--how-do-i-recover)

**GitOps / Flux**
- [How does the full Flux GitOps workflow fit together — what are the moving parts and how do they relate?](#how-does-the-full-flux-gitops-workflow-fit-together--what-are-the-moving-parts-and-how-do-they-relate)
- [When deploying a chart that installs CRDs, why must the CRD instances live in a separate Kustomization?](#when-deploying-a-chart-that-installs-crds-why-must-the-crd-instances-live-in-a-separate-kustomization)
- [Why add `crds: CreateReplace` to operator HelmReleases?](#why-add-crds-createreplace-to-operator-helmreleases)
- [Why does `charts/tuppr` not support cosign, when `charts-mirror/openebs` does?](#why-does-ghcriohome-operationschartstuppr-not-support-cosign-verification-when-ghcriohome-operationscharts-mirroropenebs-does)
- [Why does `valuesFrom` require both a `configMapGenerator` and a `kustomizeconfig.yaml`?](#why-does-every-app-that-uses-valuesfrom-need-both-a-configmapgenerator-and-a-kustomizeconfigyaml)
- [Can a HelmRelease override `timeout` (or other fields set by the global `cluster-apps` patch)?](#can-a-helmrelease-override-timeout-or-other-fields-set-by-the-global-cluster-apps-patch)
- [A resource using `${VARIABLE}` syntax is not being substituted — what's happening?](#a-resource-using-variable-syntax-is-not-being-substituted--whats-happening)
- [What are the risks of bypassing a Kustomization finalizer, and how should I delete a Flux resource safely?](#what-are-the-risks-of-bypassing-a-kustomization-finalizer-and-how-should-i-delete-a-flux-resource-safely)
- [How do I choose between HelmRepository and OCIRepository — and what happens if I use the wrong one?](#how-do-i-choose-between-helmrepository-and-ocirepository--and-what-happens-if-i-use-the-wrong-one)
- [I changed `helm/values.yaml`, pushed, and the Kustomization reconciled — but the HelmRelease never upgraded. Why?](#i-changed-helmvaluesyaml-pushed-and-the-kustomization-reconciled--but-the-helmrelease-never-upgraded-why)

**Kubernetes Workloads**
- [A healthy Deployment shows both `Available` and `Progressing` — is something wrong?](#a-healthy-deployment-shows-both-available-and-progressing--is-something-wrong)

**Upgrades (tuppr + Renovate)**
- [Does Renovate create incremental PRs per minor version, or one PR to the latest?](#does-renovate-create-incremental-prs-for-each-talosk8s-minor-version-or-one-pr-jumping-to-the-latest)
- [Why does tuppr start failing "downgrade" jobs after a manual upgrade?](#why-does-tuppr-start-spawning-failing-downgrade-jobs-after-a-manual-kubernetes-upgrade)
- [What caused the kube-apiserver v1.34.7 crash loop?](#what-caused-the-kube-apiserver-v1347-crash-loop-and-will-it-happen-again)
- [Why does `task talos:wipe-ceph-osds-live` fail after a cluster reset?](#why-does-task-taloswipe-ceph-osds-live-fail-after-a-cluster-reset)

**Observability / Alerting**
- [Why did a "Ceph" alert fire for packet drops on a management NIC, when Ceph traffic runs on the storage VLAN?](#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan)

**Database / Backups**
- [Why did Backblaze B2 WAL archiving fail with `IncompleteBody: The request body was too small` after migrating off Storj?](#why-did-backblaze-b2-wal-archiving-fail-with-incompletebody-the-request-body-was-too-small-after-migrating-off-storj)

---

## Storage

### Longhorn CSI components are in CrashLoopBackOff / `longhorn-csi-plugin` DaemonSet has 0 pods

**Short answer:** The `longhorn-system` namespace is missing `pod-security.kubernetes.io/enforce: privileged`. Kubernetes PSA is blocking Longhorn's privileged containers before they start.

**Detail:** Longhorn's storage engine requires capabilities that the Kubernetes `baseline` PSA policy forbids:
- `securityContext.privileged: true` — instance-manager and longhorn-csi-plugin
- `SYS_ADMIN` capability — longhorn-csi-plugin (required for bind-mount operations)
- Multiple `hostPath` volumes — unix domain sockets, engine binaries, kubelet directories

Without the namespace label, unlabelled namespaces inherit the cluster-level PSA default. If that default is `baseline` (or `restricted`), pod creation for `longhorn-csi-plugin` fails with:

```
pods "longhorn-csi-plugin-xxxxx" is forbidden: violates PodSecurity "baseline:latest":
  non-default capabilities (container "longhorn-csi-plugin" must not include "SYS_ADMIN" ...),
  hostPath volumes (...), privileged (... must not set securityContext.privileged=true)
```

This triggers a cascade: no `longhorn-csi-plugin` pod → no `/csi/csi.sock` socket → every CSI sidecar (attacher, provisioner, resizer, snapshotter) crashes trying to connect to that socket → Longhorn cannot provision or attach any volumes.

Note: `longhorn-manager` and `engine-image` may still run (they have lighter security requirements), making Longhorn *appear* partially healthy. The HelmRelease will also show `Ready: True` in Flux — Flux deployed the chart successfully; the PSA enforcement happens at pod-creation time, after Helm.

**Confirm it is a PSA issue:**

```bash
# Look for FailedCreate events on the csi-plugin DaemonSet
kubectl get events -n longhorn-system --field-selector=reason=FailedCreate

# Check what PSA labels the namespace has (or lacks)
kubectl get ns longhorn-system -o jsonpath='{.metadata.labels}' | jq
```

**Fix:** The `pod-security.kubernetes.io/enforce: privileged` label must be in the namespace manifest in Git — not applied imperatively — because Flux drift detection will overwrite any label that is not declared in source. The Longhorn Helm chart does **not** set this label automatically.

```yaml
# kubernetes/apps/longhorn-system/longhorn/app/namespace.yaml
metadata:
  name: longhorn-system
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/warn: privileged
    pod-security.kubernetes.io/audit: privileged
```

Set all three levels (`enforce`, `warn`, `audit`) so that admission warnings and audit log entries are also emitted at the same level — this surfaces any future PSA violation before it becomes a hard failure.

**This pattern applies to any privileged system workload** — Rook/Ceph OSDs, GPU driver DaemonSets, node-level agents, or any other chart that needs `privileged: true` or `SYS_ADMIN`. Always check whether the namespace has the PSA label when these components fail to start with no obvious error in their own logs.

**Trigger in this cluster (2026-05-13):** The Kubernetes version revert from v1.34.7 → v1.33.11 (`e49c556`) appears to have left a stricter cluster-level PSA default active. The namespace label was never in Git (the Longhorn chart doesn't set it), and the deployment had worked previously — indicating PSA enforcement tightened during the v1.34 upgrade attempt.

---

### Why was routing Longhorn replica traffic onto the storage VLAN abandoned?

**Short answer:** After 5 attempts, driving Longhorn engine↔replica traffic onto the `10.200.0.0/24`
storage VLAN via Multus + whereabouts hit an **unsolvable same-host iSCSI** problem. The cluster pivoted
to **Rook-Ceph** instead. Full attempt log preserved in
[history/longhorn-storage-network.md](history/longhorn-storage-network.md).

**The root cause (the part worth remembering):** Longhorn presents each volume to the consuming node via
**iSCSI to a pod-local IP**. When the engine pod and the consuming node's `iscsiadm` are **co-located on
the same host**, the host kernel needs a route to the pod's `lhnet1` (storage-VLAN) IP. With **ipvlan-L3**:

- the ipvlan slave lives in the *pod* netns, so the host has **no `/32` route** back to that pod IP, and
- ipvlan-L3 **suppresses ARP**, so the host can't resolve it on the L2 segment either.

The per-node `/28` + static-route scheme only fixes **cross-node** traffic; it does nothing for the
same-host path. `macvlan` and `ipvlan l2` were also tried and failed for related L2/host-isolation reasons.

**Why Rook-Ceph sidesteps it:** Ceph OSDs run with `hostNetwork: true` and a native `cluster_network`,
so replication rides the storage VLAN **directly from host network namespaces** — no CNI, no pod-IP
routing, no same-host problem. See [HARDWARE-ARCHITECTURE.md](HARDWARE-ARCHITECTURE.md).

**Bonus finding (whereabouts on Talos):** whereabouts crashes on Talos because the chroot has no
`/etc/hostname`. The fix (backport of upstream [PR #703](https://github.com/k8snetworkplumbingwg/whereabouts/pull/703))
is to write a `nodename` file + `configuration_path` into the on-host flatfile `whereabouts.conf` — the
value must live in the **flatfile, not the NAD**, because `getNodeName` treats a NAD value as a directory
while `GetFlatIPAM` treats it as a file. (Solved, but moot now that the whole approach is dropped.)

---

## Networking

### Why does the Talos console for cp-03 show many `eth0: renamed from tmp<random>` kernel messages?

**Short answer:** Normal CNI activity — not errors.

**Detail:** Each message represents Cilium creating a veth pair for a newly scheduled pod. The kernel assigns a temporary name (`tmp<hex>`) to the host-side interface; the CNI then renames the pod-side end to `eth0` inside the pod's network namespace. The kernel logs that rename at the host level, which is why it surfaces in the Talos console.

Bursts of these messages (e.g. many within a second) indicate pods being created or rescheduled in rapid succession — common after a DaemonSet rollout, Longhorn stabilising after initial deployment, or a deployment restart. cp-03 (32c, 92 GB) attracts the most pods due to scheduler resource-fit, so it generates these more frequently than the M920Q nodes.

**Actionable only if:** the same burst pattern repeats continuously over minutes, which would suggest a pod CrashLoopBackOff cycling through restarts. In that case, check `kubectl get pods -A | grep -v Running`.

---

### Why can't I reach the cluster nodes (both VLANs) while the internet works fine?

**Short answer:** A client running **Tailscale with `--accept-routes`** is preferring the cluster's tailscale-operator **subnet routes** for `10.60.0.0/24` and `10.200.0.0/24` over the direct LAN. When the cluster (or the subnet-router pod) is down, those advertised routes **blackhole** — so everything to the lab subnets is shovelled into Tailscale and dropped, even though the nodes are perfectly reachable on the local LAN. Internet is unaffected. Fix: stop Tailscale (or `--accept-routes=false`) on the client; on WSL2 also `wsl --shutdown` to flush the cached route.

**The diagnostic signature:** *both* lab subnets unreachable *simultaneously* (every node + the API VIP, all ports) while the internet is fine. Three independent machines don't lose two NICs each at once — a whole-subnet loss across two VLANs points at a single upstream route/tunnel, not the cluster. This is the trap: every symptom (kubectl timeout, talosctl timeout, can't ping nodes, can't reach NFS) *looks* like a dead cluster, but the cluster is healthy — it's a client-side routing artifact.

**The smoking gun — MTU 1280:**
```bash
ip route get 10.60.0.201
# 10.60.0.201 via 172.17.0.1 dev eth0 ... mtu 1280   ← 1280 is Tailscale's MTU
```
A direct LAN route is **MTU 1500**. Seeing **1280** on a route to the lab means the path is going through Tailscale, not the local network. (Internet still works because its route is separate and 1500.)

**Why it bites WSL2 / the devcontainer too:** the devcontainer has no Tailscale itself — it routes everything via the WSL2 host (`172.17.0.1`), which inherits Windows' routing. If Tailscale on **Windows** captured the lab subnets, the container sees it as the dead 1280 route. Closing Tailscale on Windows is not enough on its own: WSL2 **caches** the route, so you must `wsl --shutdown` (from Windows) and reopen, or wait for the cache to expire (~10 min).

**Confirm:**
```bash
curl -m5 -o /dev/null -w '%{http_code}\n' https://github.com   # 200 → internet fine
curl -m5 -k https://10.60.0.2:6443/healthz                     # timeout → lab unreachable
ip route get 10.60.0.2                                         # mtu 1280 → Tailscale is the cause
```

**Fix:**
1. On the client running Tailscale: `tailscale set --accept-routes=false` (or `tailscale down`, or quit the app).
2. On WSL2/devcontainer: `wsl --shutdown` from a Windows terminal, then reopen the devcontainer.
3. Verify: `ip route get 10.60.0.2` now shows **mtu 1500** via the LAN gateway, and `kubectl get nodes` responds.

**Prevention:** don't run `--accept-routes` on a client that is *also* on the lab LAN — it has a direct path and doesn't need the Tailscale subnet route. If a client must accept routes, scope what tailscale-operator advertises so the lab subnets a LAN-local machine already reaches aren't pulled into the tunnel.

**Encountered 2026-06-09** during the Rook-Ceph migration: the cluster briefly went down, its subnet-router pod with it, and both the devcontainer and the Windows host lost the lab subnets for ~12h — chased as a "cluster outage" until the MTU-1280 route gave it away. (The nodes also needed reboots that day for an unrelated `READY: False` state, which muddied the diagnosis — but the *reachability* loss was purely this Tailscale route hijack.)

---

### Why does the cluster have a tagged VLAN 30 sub-interface on every node's mgmt NIC and a `pool-iot` Cilium pool — isn't 10.30.0.0/24 supposed to be IOT-only?

**Short answer:** to let a Canon printer on the IOT VLAN reach `smtp-relay` without crossing the UniFi
inter-VLAN firewall — which only permits IOT→mgmt *return* traffic, not IOT-*initiated* connections. Giving
every node a direct L2 presence on 10.30.0.0/24 means the printer's connection to `smtp-relay`'s IOT-side
LB IP (`10.30.0.240`, `pool-iot`) never has to cross that fence at all — it's answered by ARP and delivered
directly on the same L2 segment. `smtp-relay` pins two LB IPs (`10.60.0.240` from `pool`, `10.30.0.240` from
`pool-iot`), each published under its own hostname (`smtp-relay.cluster.vwn.io` / `smtp-relay.iot.vwn.io`)
via an `external-dns` `target` override + a separate `ExternalName` Service, so neither hostname publishes
both addresses.

IPv6 is disabled on the VLAN 30 sub-interfaces (`net.ipv6.conf.<iface>/30.disable_ipv6: "1"` in
`talos/talconfig.yaml`) — the IOT gateway's RA/SLAAC was assigning a routable ULA the interface has no use
for. Gotcha: the sysctl **key** must escape the interface name's embedded dot as `/` (the `/proc` **path**
still uses the literal dotted name, `/proc/sys/net/ipv6/conf/eno1.30/disable_ipv6`) — get this backwards and
Talos silently ignores the sysctl.

**The side effect this created — and why it's *not* fully closed yet:** every 0.0.0.0-bound host service
(kube-apiserver `:6443`, kubelet `:10250`, etcd metrics, Talos `apid`/`trustd`) is now *also* reachable from
any IOT device, because the node's VLAN 30 address makes that traffic **L2-local** — it never touches the
UniFi gateway, so no gateway/router firewall rule can see or filter it. Confirmed directly: browsing to
`https://10.30.0.20x:6443/` from an IOT-connected laptop returns a normal `401 Unauthorized` from
kube-apiserver, not a connection failure.

A first fix attempt used a `CiliumClusterwideNetworkPolicy` host-firewall (`nodeSelector` targeting the
`reserved:host` identity, "allow all except 10.30.0.0/24") plus widening Cilium's `devices:` Helm value to
attach both the physical NIC and its `.30` VLAN child. **Reverted** — it didn't work (`cilium-dbg policy get`
resolved the rule correctly with `DefaultDeny: true`, but the host endpoint's `policy-enabled` stayed
`"none"`, matching a known class of silent Cilium host-identity/label-matching failures — e.g. upstream
issue #24415 — though not confirmed as the exact same bug), and it broke something else (widening `devices:`
to two interfaces per node made masquerade/egress-device selection ambiguous, breaking pod egress to the
storage VLAN — NAS SMB started timing out, which KEDA misread as an outage and scaled `paperless-ngx` to
zero). Cilium issues #19497, #36803, and #40521 confirm `devices:` conflating "BPF attach interfaces" with
"masquerade interface" is a real, still-open upstream gap, not a one-off misconfiguration — don't retry
widening `devices:` as part of any future fix here.

**Layer 1 mitigation (2026-08-20):** a UniFi Traffic Rule blocks the IOT network from initiating *routed*
connections to every other internal network (mgmt `10.60.0.0/24`, storage `10.200.0.0/24`, home LAN
`10.10.0.0/24`) — stateful, so it only blocks new IOT→elsewhere connections, not replies to LAN-initiated
sessions (casting, printing, Sonos control keep working). UniFi's Multicast DNS (mDNS reflector) stays
enabled between IOT and the home LAN so Chromecast/Sonos/printer discovery keeps working across the VLAN
boundary despite the block. This closes lateral movement to other VLANs, but on its own does **not** close
the kube-apiserver/kubelet exposure — that traffic is L2-local within VLAN 30 itself and a gateway rule
simply never sees it (see Layer 2 below for what actually closes that). UniFi Client Isolation was
considered and rejected as a substitute: it's all-or-nothing at L2 within a VLAN, so enabling it would also
block the printer's `smtp-relay` path (same L2-local mechanism). A MAC-based isolation allowlist, if the
controller supports it, could narrow the exposed population from "any IOT device" to "just the printer" —
but still exposes every port on the node to that one device, not just `smtp-relay`'s port, so it's a partial
layer at best.

**Layer 2 — the actual fix (implemented and verified 2026-08-20):** Talos's native declarative ingress
firewall (`NetworkDefaultActionConfig` / `NetworkRuleConfig`, nftables-based) closes the L2-local exposure
directly at the node, without touching Cilium's `devices:`/masquerade path at all — avoiding the confirmed
root cause of the earlier regression. `talos/patches/global/network-firewall.yaml` and
`talos/patches/controller/network-firewall.yaml` add `NetworkRuleConfig` allow rules for kubelet (`10250`),
`apid` (`50000`), `trustd` (`50001`) on every node, plus kube-apiserver (`6443`), etcd client/peer
(`2379-2380`), etcd metrics (`2381`), controller-manager (`10257`), and scheduler (`10259`) on control-plane
nodes — each scoped to `10.60.0.0/24` (and `10.10.0.0/24` where a workstation legitimately needs direct
access), never `10.30.0.0/24`.

The open question from the original research — whether a per-port `NetworkRuleConfig` restricts only that
port while leaving every other port untouched, or whether it only takes effect once the *global* default is
flipped to `block` — is resolved: **a `NetworkRuleConfig` is a self-contained allowlist for the port it
names, regardless of the global default action.** Confirmed two ways: (1) inspecting the live
`talosctl get nftableschain -o yaml` output directly showed `policy: accept` at the chain level with
explicit per-port `DROP` rules matching an inverted source-subnet set — exactly this mechanism, not
inferred; (2) a closed Talos GitHub issue (siderolabs/talos#12955) showing a port-scoped rule correctly
restricting that port under a global `accept` default. This means the global default was deliberately left
at `accept` — no need to enumerate Ceph/Spegel/node-exporter/app-LoadBalancer ports, and no risk to future
services on any port without its own rule. The historical Talos NodePort/hostPort firewall-bypass concern
(discussion #10347) doesn't apply here either — that bug was fixed in Talos v1.9.4 (this cluster runs
v1.13.2), and separately this cluster has no NodePort usage at all (Cilium fully replaces kube-proxy).

Rolled out node-by-node (workers first, then control-plane nodes one at a time) via
`talosctl apply-config --mode=try` (auto-reverts if a node becomes unreachable) before persisting, with an
etcd-quorum health check between every step. **Verified end-to-end from an actual IOT-connected device**:
`10.30.0.202:6443` is now unreachable (previously returned a `401`), while `10.10.0.0/24` (home LAN) can
still reach it — exactly the intended split.

**Gotcha found ~20 minutes after rollout: Prometheus scrapes host ports directly by node IP, sourced from
its own pod IP — not a host IP.** `kube-prometheus-stack`'s `kubelet`, `kube-controller-manager`,
`kube-scheduler`, and `apiserver` jobs all connect straight to `<node-ip>:<port>` (e.g. `10.60.0.201:10250`)
from the Prometheus pod's own address (`10.42.0.0/16`), not through any Service/ClusterIP indirection. Since
`10.42.0.0/16` wasn't in any of those four rules' `ingress` list, the firewall silently blocked Prometheus's
own scrapes the moment it went live — firing `KubeletInstanceUnreachable`, `KubeControllerManagerInstanceUnreachable`,
`KubeSchedulerInstanceUnreachable`, and `KubeAPIInstanceUnreachable` within ~15 minutes (the alerts' `for:`
duration). Fixed by adding `10.42.0.0/16` (the pod CIDR) as an allowed source subnet on all four rules —
strictly additive, so no re-verification of the IOT-block itself was needed. **If a future
`NetworkRuleConfig` is added for any other port that kube-prometheus-stack scrapes directly by node IP
(check `kubectl get servicemonitors -n observability -o yaml` for `job` labels using node/host addressing
rather than a Service), add `10.42.0.0/16` to it up front** — this class of breakage is easy to reproduce
and easy to miss until the alert fires. `etcd` metrics (`2381`) escaped this only because
`kubeEtcd.enabled: false` in this cluster's values — nothing scrapes that port at all.

---

### A single iperf3 stream over the storage bond tops out at ~9.7 Gbit/s — is the LACP bond broken?

**Short answer:** No. LACP (802.3ad) never splits a single TCP flow across both member links — it hashes
each flow to *one* link for the life of that flow. ~9.7 Gbit/s is line-rate for one 10G member. To see
the aggregate you must run **many parallel flows** so the hash spreads them across both links. Benchmarked
2026-06-10, the `10.200.0.0/24` storage fabric reaches **~19.3 Gbit/s aggregate (~96% of 20G)** — both
links saturate cleanly under load.

**Why one stream can't go faster:** With `xmitHashPolicy: layer3+4` the bond hashes on
`{src-IP, dst-IP, src-port, dst-port}`. Between a fixed host pair the two IPs are constant, so only the L4
ports vary the hash — a single connection has one fixed tuple → one link → ~10G ceiling (jumbo frames get a
single flow *close* to the 9.4–9.8 range; 1500-byte frames leave more on the table to per-packet overhead).
Both directions hash independently (each host's bond governs its own TX), and the **switch re-hashes** when
forwarding into the destination LAG — so a true 20G result requires the host hash *and* the switch hash to
both spread.

**Why an 8-stream run can still read low (the trap):** Source ports are *ephemeral* — the kernel picks fresh
ones per connection, so the hash distribution is a **new random draw every run**. Collisions are not the issue
(8 flows over 2 links *must* collide — pigeonhole); what varies is how *evenly* the flows split. The count of
flows on a given link follows `Binomial(8, 0.5)`, and with only 8 flows the variance is high: a perfect 4/4
split has only ~27% probability, while a **5/3-or-worse split occurs ~73% of the time**. When one member is
oversubscribed its flows congest (heavy retransmits) and the under-loaded member lacks enough flows to ramp to
10G in the test window — so the aggregate drops, e.g. 15.5 Gbit/s on one run and 19.x on the next with no
config change. **Never trust a single multi-stream run.** The honest number is the *best of several* (shows the
ceiling when the split is even) or a **16+ stream** run, where `Binomial(16, 0.5)` (mean 8, σ=2) clamps tightly
around an even split. Re-running the same 8-stream test 3× confirmed this: 15.5 → then 19.2 / 19.6 / 19.6.

**How Ceph actually uses the bond (researched against Squid 19.2.3):** Counter-intuitively, Ceph does **not**
light up both links for traffic between a single node pair. Its messenger multiplexes all
replication/recovery between two OSD daemons onto **one cluster-network TCP connection** (the other ~2–3
connections per OSD-pair are tiny heartbeats), and there is **no Ceph option to open more** —
`ms_async_op_threads` is a worker *thread pool* (CPU parallelism), not a per-peer connection count; the
official Network Configuration Reference exposes no inter-OSD connection multiplier. So with **1 OSD per
node** (our topology), heavy replication between two nodes is a single flow pinned to one link (~9.75 Gbit/s)
— *worse* than this 16-stream benchmark, which was a best case for LACP spread. The only lever for more
streams between two hosts is **more OSD daemons**: N OSDs/node → up to N² distinct OSD-pair connections, each
hashable to either link (Rook `storage.config.osdsPerDevice`, or more physical drives/nodes). This is **moot
for us** — 9.75 Gbit/s on a single link is still ~4× the ~2.5 Gbit/s drive ceiling, so Ceph stays disk-bound
regardless of how the flows hash. (Aggregate *cluster* throughput across all node pairs does scale with OSD
count; the single-pair limit is what one host-to-host transfer sees.)

#### Benchmark method (reusable runbook)

Talos is immutable and minimal — there is **no `iperf3` on the host** and no SSH. The storage bond is a
*host* interface (not on the pod network), so push traffic over it from `hostNetwork: true` pods pinned to
specific nodes. Run them in a **`privileged`-PSA namespace** (e.g. `rook-ceph`); `baseline`/`restricted`
namespaces reject `hostNetwork`. Use an image with both `ping` and `iperf3` (`nicolaka/netshoot`).

**1 — Verify the bond is actually a 2-link LAG (config-as-running, not just config-as-written):**
```bash
export TALOSCONFIG=$(pwd)/talos/clusterconfig/talosconfig
talosctl -n 10.60.0.201 read /proc/net/bonding/bond-storage
# Want: Transmit Hash Policy: layer3+4 | both slaves "MII Status: up" at 10000 Mbps
#       Active Aggregator "Number of ports: 2" + a Partner Key (proves the SWITCH aggregated both)
```
A common silent failure is the switch *not* aggregating — you stay at 10G with both NICs "up". The
`Number of ports: 2` + non-zero `Partner Key` is the proof the switch put both links in one LAG.

**2 — Verify jumbo frames end-to-end before throughput** (a broken path-MTU silently fragments and tanks
throughput). Run from inside a host-net pod over the *storage* IPs:
```bash
# 8972 payload + 28 ICMP/IP headers = 9000 on the wire; DF set → must not fragment
kubectl -n rook-ceph exec iperf-client -- ping -c 3 -M do -s 8972 -I 10.200.0.201 10.200.0.202
# success with 0% loss = full 9000 MTU clean, switch included
```

**3 — Throughput** (bind source to the storage IP so traffic can't leak onto the mgmt bond):
```bash
# single stream = per-link ceiling
kubectl -n rook-ceph exec iperf-client -- iperf3 -c 10.200.0.202 -B 10.200.0.201 -t 15 -O 3
# 16 streams = forces an even hash split → aggregate (run a few times; take the best)
kubectl -n rook-ceph exec iperf-client -- iperf3 -c 10.200.0.202 -B 10.200.0.201 -P 16 -t 20 -O 3
kubectl -n rook-ceph exec iperf-client -- iperf3 -c 10.200.0.202 -B 10.200.0.201 -P 16 -t 20 -O 3 -R  # reverse
```
`-O 3` omits TCP slow-start from the average. Reading: aggregate climbing past the single-link ceiling =
both links carrying traffic; stuck at ~9.7 no matter how many streams = hash not spreading (host or switch).

**4 — Real Ceph throughput (no new pods, uses the toolbox):**
```bash
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rados bench -p ceph-blockpool 30 write --no-cleanup -t 16
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rados bench -p ceph-blockpool 15 seq -t 16
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rados -p ceph-blockpool cleanup   # tidy up the objects
```
The host-net iperf pods are transient verification scaffolding — `kubectl delete pod iperf-server iperf-client`
when done. They are **not** Flux-managed (this is the same throwaway pattern used for the CSI smoke-test PVC).

#### Results (2026-06-10, cp-01 ↔ cp-02)

| Test | Result | Reading |
|------|--------|---------|
| Jumbo ping (9000B, DF) | 0% loss, ~0.3 ms | Full 9000 MTU clean incl. switch |
| iperf3 single stream | **9.75 Gbit/s** | One flow = one link, at line rate |
| iperf3 8 streams (1st run) | 15.5 Gbit/s | Unlucky hash draw — *not* a fault |
| iperf3 8 streams (re-runs) | 19.2 / 19.6 / 19.6 | Same test, balanced draws |
| iperf3 16 streams | **19.2–19.3 Gbit/s** | ~96% of 20G — both links saturated |
| rados bench write (3×repl) | 314 MB/s (~2.5 Gbit/s) | **Drive-bound**, not network-bound |
| rados bench seq read | 314 MB/s (~2.5 Gbit/s) | Drive-bound |

**The takeaway is the ratio:** real Ceph throughput (~2.5 Gbit/s, gated by consumer-NVMe write speed under
3× sync-write replication) is ~1/8th of the network ceiling. The fabric has **~7–8× headroom** over what the
disks can deliver — even a worst-case full-OSD rebuild won't bottleneck on the network; the NVMe will. If
storage throughput ever needs to grow, the lever is disks (faster/enterprise NVMe, more OSDs per node), not
the bond.

---

### Why does an externally-exposed app get `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` even though its Envoy certificate looks correct?

**Short answer:** Cloudflare's free Universal SSL only issues an edge certificate covering the zone root plus *one* level of wildcard (`example.com` + `*.example.com`). A hostname two levels deep — like `whoami.apps.vwn.io` (`whoami` under `apps.vwn.io`, itself under `vwn.io`) — isn't covered by `*.vwn.io`, so Cloudflare's edge rejects the TLS handshake outright. This happens *before* the request ever reaches the tunnel, `cloudflared`, or anything in this repo — the origin-side `Certificate`/`Secret` on the Gateway is completely irrelevant to this failure.

**The trap:** Gateway API's `ResolvedRefs` status only checks that the referenced `Secret` exists — it doesn't validate SAN coverage — and the origin cert genuinely *is* correct (`apps-vwn-io-tls` does cover `*.apps.vwn.io`). Everything in-cluster looks healthy: `HTTPRoute` Accepted, `Certificate` Ready, `Gateway` Programmed. The failure is invisible to `kubectl` entirely; it only shows up as a generic client-side TLS error when actually browsing the hostname from outside the LAN. Worse, testing from the LAN itself can give a false negative: if local DNS (e.g. a UniFi `service`-source record) resolves the hostname straight to the Gateway's private LB IP, that test never touches Cloudflare's edge at all and "succeeds" while the public path is still broken.

**Confirm:** compare a one-level vs. two-level hostname against Cloudflare's real edge IP directly, bypassing local DNS:
```bash
dig @1.1.1.1 <hostname> +short                                          # get a real Cloudflare anycast IP
curl -v --resolve <hostname>:443:<that-ip> https://<hostname> 2>&1 | grep -E "subjectAltName|TLS alert|handshake failure"
```
One level deep (`flux-webhook.vwn.io`, `apps.vwn.io`) → handshake succeeds, SAN matched via `*.vwn.io`. Two levels deep (`whoami.apps.vwn.io`) → `TLS alert, handshake failure`, no HTTP response at all.

**Fix — pick one:**
1. Use a hostname that only nests one level under a zone you already control (e.g. `whoami.vwn.app` instead of `whoami.apps.vwn.io`) — works immediately with zero Cloudflare changes, as long as the origin `Certificate`, `cloudflared` ingress rule, and both `external-dns` `domainFilters` already cover that zone (they did here, since `vwn.app` was already in use elsewhere).
2. Enable Cloudflare **Total TLS** for the zone (auto-issues certs for every subdomain level).
3. Order a Cloudflare **Advanced Certificate** explicitly listing the second-level wildcard (e.g. `*.apps.vwn.io`).

**Prevention:** `envoy-external`'s `certificateRefs` (`kubernetes/apps/network/envoy-gateway/config/gateway.yaml`) has an inline comment marking which certs are WAN-safe for new routes. Only `vwn-app-tls`/`vwn-casa-tls` (one level under their own zone roots) are safe without one of the fixes above; `cluster-vwn-io-tls`/`apps-vwn-io-tls` are origin-only until Cloudflare's edge coverage is extended.

**Encountered 2026-06-19** while validating external connectivity with a `whoami` smoke-test app, after first fixing an unrelated, genuinely-real `cloudflared` SNI bug that looked like it would explain the same symptom but didn't.

---

## Cluster Recovery / Unclean Shutdown

### After a simultaneous power-off of all nodes, the dashboard shows ~90 failed pods and a failed Deployment — but the cluster looks healthy. What happened?

**Short answer:** Ghost pods from an unclean shutdown. The cluster is fine; the pod objects need manual deletion.

**Detail:** When all nodes lose power simultaneously, kubelets never get a chance to write terminal status for their running containers. On restart, the kubelet can no longer find those containers and reports their status as `ContainerStatusUnknown`, which transitions the pod to `Failed` phase. Kubernetes does **not** automatically garbage-collect `Failed` pods (only `Succeeded` ones are eligible for GC by default).

Meanwhile the Deployment controller sees the failed pods and creates replacements — potentially dozens of times before one stabilises. The result is a large number of stale `Failed` pod objects in etcd that have no containers behind them, but are never cleaned up automatically.

In this cluster the pattern after a full 3-node shutdown was:
- ~91 `cilium-operator` pods in `kube-system`, all `ContainerStatusUnknown`, all on `talos-cp-03`
- `cilium-operator` Deployment showing `1/1` (healthy) despite the pod count
- Dashboard reporting "Failed: 1" for Deployment and ReplicaSet — it counts pod failures, not desired/ready state
- `openebs` Flux Kustomization throwing transient health-check timeouts during boot sequencing (self-resolved)

**How to confirm this is the issue (not a real failure):**

```bash
# Are all failed pods for the same workload and ContainerStatusUnknown?
kubectl get pods -A --field-selector=status.phase=Failed

# Is the Deployment itself healthy?
kubectl get deployment -n kube-system cilium-operator
# Expect: READY 1/1

# Are there NodeShutdown events matching the outage timestamp?
kubectl get events -n kube-system --field-selector=reason=NodeShutdown
```

**Fix — delete the stale pods (safe, no config change needed):**

```bash
# Generalised: delete all Failed pods in a namespace for a specific workload
kubectl delete pods -n kube-system \
  -l app.kubernetes.io/name=cilium-operator \
  --field-selector=status.phase=Failed
```

If the outage affected multiple workloads across namespaces, run a broader sweep:

```bash
kubectl delete pods -A --field-selector=status.phase=Failed
```

This is safe as long as the owning Deployments/DaemonSets show healthy desired/ready counts beforehand. The controllers will not create new replacements because they already have the desired number of running pods.

**Safer alternative — script that verifies owner health first:**

`scripts/purge-failed-pods.sh` (also exposed as `task purge-failed-pods`) walks the full ownership chain (Pod → ReplicaSet → Deployment) and checks controller health before deleting anything. It skips pods whose owner is not confirmed healthy, and skips unrecognised owner kinds (e.g. Jobs) entirely.

```bash
task purge-failed-pods              # dry-run: prints what would be deleted, no changes made
task purge-failed-pods DELETE=true  # live: deletes only pods with a confirmed-healthy owner
```

Health criteria used by the script:
- **Deployment** — `Available` condition is `True`
- **DaemonSet** — `numberReady == desiredNumberScheduled`
- **StatefulSet** — `readyReplicas == replicas`

Use this instead of the broad `kubectl delete pods -A` sweep when you want an automated check rather than a manual pre-flight.

**Why cp-03 accumulates more than the other nodes:** The scheduler preferentially places workloads on cp-03 (AMD, 32c, 92 GB) due to resource fit. More pods means more `ContainerStatusUnknown` events after a crash.

---

### How do I recover when Cilium and CoreDNS are both gone simultaneously?

**Short answer:** Manual `helm install` in this exact order — Cilium first (uses `hostNetwork:true`, needs no CNI), CoreDNS second (needs Cilium), flux-instance third (needs DNS). Flux controllers cannot self-heal because they are regular pods that require a working CNI and DNS.

**Why this can happen:** Bypassing a Kustomization finalizer (patching `finalizers: null`) skips the prune cycle. The Kustomization is immediately deleted from etcd but all managed resources remain as orphans. When Flux later reconciles a fresh Kustomization over the same path it may prune those orphans — including Cilium and CoreDNS — before they can be re-created.

**Recovery sequence:**

**Step 1 — Reinstall Cilium:**
```bash
helm install cilium cilium/cilium --version <version> \
  --namespace kube-system \
  -f kubernetes/apps/kube-system/cilium/app/helm/values.yaml
```
Wait until all Cilium agent pods are `Running` before proceeding — pending pods cannot get network sandboxes until CNI is up.

**Step 2 — Reinstall CoreDNS:**
```bash
# CoreDNS is OCI-distributed in this cluster
helm upgrade --install coredns oci://ghcr.io/coredns/charts/coredns \
  --version <version> --namespace kube-system \
  -f kubernetes/apps/kube-system/coredns/app/helm/values.yaml
```
Do not use `--wait` here — CoreDNS pods may stay `ContainerCreating` during the Cilium startup window. Verify manually with `kubectl get pods -n kube-system -l app.kubernetes.io/name=coredns`.

**Step 3 — Reinstall flux-instance (if Flux controllers are gone):**

First, clear any stale Helm release secrets holding the release in `uninstalling` state:
```bash
kubectl get secrets -n flux-system | grep sh.helm.release.v1.flux-instance
kubectl delete secret -n flux-system <each-stale-secret>
```
Then reinstall:
```bash
helm install flux-instance oci://ghcr.io/controlplaneio-fluxcd/charts/flux-instance \
  --version <version> --namespace flux-system \
  -f kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml
```
flux-operator picks up the fresh Helm release and deploys all four Flux controllers.

**Step 4 — Recreate the onepassword-connect bootstrap secret (if ESO is failing):**
```bash
task bootstrap:onepassword-connect-secret
```
`onepassword-connect-secrets` in the `external-secrets` namespace is an **imperatively-created bootstrap credential** — it is NOT managed by ExternalSecrets (it is the credential for the secret manager itself). It gets orphaned and deleted during cascade failures and must be recreated manually. Without it, all ExternalSecrets downstream of the `onepassword` ClusterSecretStore fail.

**Step 5 — Let Flux reconcile:**
```bash
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
```

**Key constraints:**
- If `helm install` fails with "cannot reuse a name that is still in use", the release is stuck in a failed or `uninstalling` state — use `helm upgrade --install` or delete the stale Helm release secrets first
- Current chart versions are pinned in each `app/helmrelease.yaml` file — use the exact same versions to avoid surprise upgrade mechanics
- Cilium must be running before CoreDNS; CoreDNS must be running before source-controller can clone from GitHub

---

### A HelmRelease is Stalled with `MissingRollbackTarget` — how do I recover?

**Short answer:** `MissingRollbackTarget` means helm-controller wants to roll back but there is no prior Helm revision to roll back to — typically because `cleanupOnFail: true` removed resources from a failed first install. Seed revision 1 via direct `helm install --no-hooks`, then force Flux to adopt it.

**Why it happens:** The global `cluster-apps` HelmRelease defaults include `upgrade.remediation.strategy: rollback` and `cleanupOnFail: true`. When a chart's very first install fails, `cleanupOnFail: true` deletes the resources created during the attempt. helm-controller then tries to remediate via rollback — but there is no prior revision. It sets `Stalled: MissingRollbackTarget` and stops retrying entirely. Unlike the `Failed` condition, `Stalled` does NOT enter the normal retry loop.

**Recovery:**
```bash
# 1. Get chart details from the HelmRelease
kubectl get helmrelease <name> -n <namespace> -o yaml | grep -A8 chart

# 2. For HelmRepository-backed charts: add the repo
helm repo add <repo-name> <repo-url>
helm repo update

# 3. Seed revision 1 (--no-hooks avoids admission webhook failures during recovery)
helm install <release-name> <chart-ref> \
  --version <version> \
  --namespace <namespace> \
  --no-hooks \
  -f kubernetes/apps/<path>/app/helm/values.yaml

# 4. Force Flux to adopt the existing release
flux reconcile helmrelease <name> -n <namespace>
```

After step 4, helm-controller performs an `upgrade` (not install) against revision 1. If the upgrade succeeds, `Stalled` clears and normal reconciliation resumes.

**Note:** `--no-hooks` is safe for recovery when the deployment does not require pre-install hooks. For charts that depend on webhooks from other Helm charts (e.g. cert-manager), omit it and be prepared to resolve webhook errors first.

---

### Longhorn finalizer patches fail with `"Internal error: failed calling webhook"` — why?

**Short answer:** `ValidatingWebhookConfiguration/longhorn-webhook-validator` and `MutatingWebhookConfiguration/longhorn-webhook-mutator` are **cluster-scoped** resources — they survive namespace deletion. They intercept all mutations to Longhorn CRD objects and route them to the Longhorn webhook service, which is gone. Delete both webhook configurations before patching finalizers.

**Why cluster-scoped webhook configs survive:** When Kubernetes terminates a namespace it deletes namespace-scoped resources (pods, services, deployments). Cluster-scoped resources like `ValidatingWebhookConfiguration` and `MutatingWebhookConfiguration` are not owned by any namespace — they remain intact. The Longhorn Helm uninstall may not delete them either if the release was incomplete. With `failurePolicy: Fail`, every CRD mutation triggers a call to the dead service and fails immediately.

**Full cleanup procedure:**
```bash
# Step 1: Remove the cluster-scoped webhook interceptors
kubectl delete validatingwebhookconfiguration longhorn-webhook-validator
kubectl delete mutatingwebhookconfiguration longhorn-webhook-mutator

# Step 2: Clear finalizers on all Longhorn CRD object types (9 types)
for res in volumes engines replicas instancemanagers backuptargets engineimages nodes volumeattachments; do
  kubectl get ${res}.longhorn.io -n longhorn-system -o name 2>/dev/null | \
    xargs -r -I{} kubectl patch {} -n longhorn-system \
    -p '{"metadata":{"finalizers":[]}}' --type=merge
done

# Step 3: Clear finalizers on PVCs in any namespace that had Longhorn volumes
for pvc in $(kubectl get pvc -n <namespace> -o name); do
  kubectl patch $pvc -n <namespace> -p '{"metadata":{"finalizers":[]}}' --type=merge
done
```

To discover all Longhorn CRD types before starting:
```bash
kubectl api-resources --verbs=list --namespaced -o name | grep longhorn
```

After the webhooks are removed and finalizers are cleared, the `longhorn-system` namespace terminates within a few minutes.

---

### flux-instance is stuck in `uninstalling` state and Flux CRDs have disappeared — how do I recover?

**Short answer:** The `FluxInstance` CR is itself a Flux CRD — when flux-instance uninstalls itself, the CRD disappears, taking the FluxInstance object with it and stopping all controllers. Delete the stale Helm release secrets that are holding the release in `uninstalling` state, then reinstall via `helm install`.

**Why Helm secrets block recovery:** When a Helm uninstall is interrupted mid-way, Helm writes a release secret with `status: uninstalling`. Any subsequent `helm install <same-name>` fails with "cannot reuse a name that is still in use" because Helm sees the stale secret. The old FluxInstance CR is gone (CRD was deleted), and there is no controller left to finish the uninstall and clean up the secret.

**Recovery:**
```bash
# 1. List stale Helm release secrets
kubectl get secrets -n flux-system | grep sh.helm.release.v1.flux-instance

# 2. Delete each one
kubectl delete secret -n flux-system \
  sh.helm.release.v1.flux-instance.v1 \
  sh.helm.release.v1.flux-instance.v2   # repeat for any additional versions

# 3. Reinstall
helm install flux-instance oci://ghcr.io/controlplaneio-fluxcd/charts/flux-instance \
  --version <version> --namespace flux-system \
  -f kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml
```

flux-operator detects the fresh Helm release, verifies its FluxInstance CR, and deploys all four Flux controllers. Once source-controller is running it can clone the repo and the reconcile tree resumes.

---

## GitOps / Flux

### How does the full Flux GitOps workflow fit together — what are the moving parts and how do they relate?

**Short answer:** Five object types across four controllers form a pipeline: `GitRepository` feeds `Kustomization`, which creates `HelmRepository`/`OCIRepository` sources and more `Kustomization` children, which create `HelmRelease` objects, which helm-controller turns into running Helm releases.

**The four controllers and what each owns:**

| Controller | Watches | Does |
|---|---|---|
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository`, `HelmChart` | Clones repos, fetches chart indexes/OCI manifests, stores versioned artifacts locally |
| `kustomize-controller` | `Kustomization` | Renders Kustomize overlays against a source artifact and applies/prunes resources |
| `helm-controller` | `HelmRelease` | Runs `helm install`/`upgrade`/`rollback` using a `HelmChart` artifact |
| `notification-controller` | `Alert`, `Receiver` | Dispatches events to external systems (Slack, GitHub webhooks) |

**The object graph — root to leaf:**

```
GitRepository/flux-system  (ssh://github.com/qnimbus/home-lab)
│
└── Kustomization/flux-system  (path: ./kubernetes/flux/cluster/)
    │   [managed by flux-operator; applies every commit]
    │
    ├── Kustomization/cluster-meta  (path: ./kubernetes/flux/meta/)
    │       Creates: HelmRepository objects (cilium, longhorn, …)
    │                OCIRepository objects (coredns, cert-manager, …)
    │       source-controller fetches each index/manifest → artifact
    │
    ├── Kustomization/cluster-vars  (path: ./kubernetes/flux/vars/)
    │       Creates: ConfigMaps/Secrets with cluster-wide substitution vars
    │       (cluster name, domain, node IPs, etc.)
    │
    └── Kustomization/cluster-apps  (path: ./kubernetes/apps/, dependsOn: cluster-meta)
            Injects global HelmRelease defaults via spec.patches (timeout, crds, retries)
            │
            ├── Kustomization/cilium → Kustomization/cilium-config
            ├── Kustomization/coredns
            ├── Kustomization/external-secrets → onepassword-connect → onepassword-store
            ├── Kustomization/cert-manager → cluster-issuers
            ├── Kustomization/envoy-gateway → envoy-gateway-config
            ├── Kustomization/longhorn → kube-prometheus-stack
            ├── Kustomization/metrics-server
            ├── Kustomization/flux-operator → flux-instance, flux-receiver
            ├── Kustomization/tuppr → tuppr-upgrade
            └── … (one per app)
                    Each creates:
                      - HelmRelease (the chart deployment spec)
                      - ConfigMap (generated from helm/values.yaml via configMapGenerator)
                      - Namespace, RBAC, ExternalSecret, etc. as needed
```

**What source-controller does behind the scenes:**

When helm-controller sees a `HelmRelease` referencing a `HelmRepository`, source-controller silently creates a `HelmChart` object (not visible in the normal `kubectl get` flow). `HelmChart` causes source-controller to download the actual `.tgz` chart tarball from the repo index and store a versioned artifact. helm-controller then reads that artifact to run its Helm operations. `OCIRepository`-backed HelmReleases use `chartRef:` instead of `chart.spec.sourceRef:`, which skips the intermediate `HelmChart` step — source-controller pulls the OCI layer directly.

**The reconciliation loop (one full cycle):**

```
1. You push a commit to GitHub
2. source-controller polls GitRepository at its interval (default: 1h; webhook: seconds)
   → detects new SHA → clones → stores artifact tagged with SHA
3. kustomize-controller sees GitRepository artifact updated
   → re-renders ./kubernetes/flux/cluster/
   → applies cluster-meta, cluster-apps, cluster-vars (creates/patches/prunes)
4. cluster-meta reconciles → HelmRepository/OCIRepository objects exist
   → source-controller fetches updated chart indexes and OCI manifests
5. cluster-apps reconciles → all per-app Kustomizations exist with dependsOn ordering
6. Each per-app Kustomization reconciles (in dependency order):
   → applies HelmRelease + ConfigMap + supporting resources
7. helm-controller sees HelmRelease created/changed
   → source-controller has already fetched the chart (HelmChart artifact ready)
   → runs helm upgrade (or install if first time)
   → updates HelmRelease .status.conditions with result
8. Kustomization health checks poll the HelmRelease ready condition
   → once True, Kustomization becomes True
   → unblocks any dependsOn children
```

**The `valuesFrom` / `configMapGenerator` pattern:**

Each app's values live in `app/helm/values.yaml`. Rather than inline them into the HelmRelease, kustomize-controller generates a ConfigMap from that file using `configMapGenerator`. The ConfigMap name gets a content-hash suffix (e.g. `cilium-values-6bk9f2t`), which changes whenever `values.yaml` changes — causing Flux to automatically trigger a Helm upgrade on the next reconcile. The `helm/kustomizeconfig.yaml` file tells Kustomize to rewrite the HelmRelease's `spec.valuesFrom[].name` to match the hashed name, so helm-controller finds the right ConfigMap.

**The global HelmRelease defaults patch:**

`cluster-apps` injects a `spec.patches` block into every child Kustomization. This patch targets all `HelmRelease` objects and sets `timeout`, `crds: CreateReplace`, and remediation retries cluster-wide. Because this patch is appended last in the rendering chain, it always wins over any `timeout:` set directly in an individual HelmRelease.

**Gotcha — two separate `spec.patches` injections cancel each other out:**

If two separate outer patches in `cluster-apps` both inject a `spec.patches` list into Kustomizations (e.g. one for HelmRelease defaults, one for drift detection), Kustomize treats `spec.patches` as an unkeyed list and uses **replace** semantics. The second entry overwrites the first — the Kustomizations end up with only the last patch's list. The fix is to merge both inner patch items into a **single** outer patch entry so the full list is set atomically. See `kubernetes/flux/cluster/ks.yaml` — both HelmRelease defaults and drift detection share one outer block.

**Key invariants to remember:**

- `source-controller` must have a ready artifact before anything downstream can proceed. DNS failure → no artifact → everything blocks.
- Cilium (the CNI) and CoreDNS are bootstrapped before Flux takes over, because Flux's own controllers are regular pods that need a working network. If both are lost simultaneously, Flux cannot self-heal without a manual reinstall of those two charts.
- Deleting a Kustomization with `prune: true` (or bypassing its finalizer) triggers cascading deletion of everything it manages. The safe deletion path always goes through Git — remove the resource from the path and let Flux reconcile it away cleanly.
- `dependsOn` only gates the *start* of reconciliation — it does not prevent a child from being deleted if the parent is deleted first.

---

### When deploying a chart that installs CRDs, why must the CRD instances live in a separate Kustomization?

**Short answer:** Flux dry-runs every resource in a Kustomization before applying any of them. If the Kustomization contains both the HelmRelease (which installs the CRDs) and instances of those CRDs, the dry-run fails — the API types don't exist yet at validation time.

**Detail:** Before applying a Kustomization, the Flux kustomize-controller performs a server-side dry-run of every resource it is about to create or update. This validates that the API server knows about the resource types. When a HelmRelease and its CRD instances are in the same Kustomization, the dry-run order is non-deterministic — the HelmRelease itself is just a CR telling the helm-controller to do work later; it does not install the CRDs synchronously during the dry-run. So Flux tries to validate `TalosUpgrade` against the API, gets `no matches for kind "TalosUpgrade"`, and the whole Kustomization fails before anything is applied.

**The fix — split into two Kustomizations (both in one multi-document `ks.yaml`):**

```yaml
# Document 1 — operator
kind: Kustomization
metadata:
  name: my-operator
spec:
  path: ./app          # contains HelmRelease only
  healthChecks:
    - kind: HelmRelease
      name: my-operator
      namespace: my-ns

# Document 2 — CRD instances
kind: Kustomization
metadata:
  name: my-operator-config
spec:
  path: ./config       # contains CRD instances
  dependsOn:
    - name: my-operator
```

`dependsOn` tells Flux not to attempt the second Kustomization until the first is Ready. `ks.yaml` is only marked Ready once its `healthChecks` (the HelmRelease) pass — meaning the chart is fully installed and the CRDs exist in the API. By the time `ks-upgrade.yaml` runs its dry-run, the types are registered.

**Important subtlety — `wait: false` vs `healthChecks`:** Setting `wait: false` on a Kustomization skips waiting for resources that have no explicit health check. But if you define `healthChecks` explicitly, Flux always evaluates those regardless of `wait`. So `ks.yaml` with `wait: false` + a HelmRelease `healthCheck` still correctly gates `ks-upgrade.yaml`.

**This pattern applies to any chart that installs CRDs you want to use in Git** — cert-manager (Certificate, ClusterIssuer), external-secrets (ExternalSecret, SecretStore), Longhorn (custom node configs), etc. The pattern is: operator Kustomization → `dependsOn` → CRD-instance Kustomization.

---

### Why add `crds: CreateReplace` to operator HelmReleases?

**Short answer:** By default, Helm never updates CRDs on `helm upgrade` — only on `helm install`. Without `CreateReplace`, a chart upgrade that ships a new CRD schema silently leaves the old schema in the cluster.

**Detail:** Helm's conservative default exists because CRD schema changes can be destructive — a `replace` deletes and recreates the CRD object, which briefly interrupts controllers watching that resource. Rather than risk accidental breakage, Helm chose to do nothing on upgrade. The consequence is that if an operator chart ships a new field in a CRD (e.g. a new `spec.policy.rebootMode` on `TalosUpgrade`), upgrading the HelmRelease installs the new controller binary but leaves the old CRD schema in place. Resources using the new field are silently ignored or rejected.

`CreateReplace` opts in to CRD updates on both install and upgrade:

```yaml
install:
  crds: CreateReplace
upgrade:
  crds: CreateReplace
```

This should be set on any HelmRelease for a chart that owns CRDs — operators, admission controllers, storage drivers, etc. It is safe for home-lab use where the tradeoff (brief CRD replacement vs. stale schema) clearly favours keeping schemas current.

**Note:** `CreateReplace` is a Flux helm-controller option, not a native Helm flag. The equivalent in raw Helm is `--skip-crds=false` combined with manual CRD management, which is why the Flux field exists as a convenience.

---

### Why does `ghcr.io/home-operations/charts/tuppr` not support cosign verification, when `ghcr.io/home-operations/charts-mirror/openebs` does?

**Short answer:** They are two different registry paths with different release pipelines. `charts-mirror` is a community-signed mirror of third-party charts; `charts` is the home-operations org's own first-party charts and does not go through the same signing pipeline.

**Detail:** The home-operations community maintains two distinct OCI chart registries under `ghcr.io/home-operations/`:

- **`charts-mirror/`** — mirrors of popular third-party charts (openebs, etc.) that the community re-signs with cosign keyless signing as part of their automated mirror pipeline. These can use `verify: provider: cosign`.

- **`charts/`** — first-party charts for community-authored tools (tuppr, etc.). As of May 2026, these are pushed without cosign signatures, so `verify: provider: cosign` causes an immediate `VerificationError`.

Using `verify: cosign` on an unsigned chart produces a failure that is *not retried until the next interval* (1h by default). Because the OCIRepository is a health-checked dependency of `cluster-meta`, this failure cascades: `cluster-meta` gets stuck running health checks for the bad revision, and `cluster-apps` (which `dependsOn: cluster-meta`) never unblocks. Removing the bad resource spec mid-health-check requires patching the live resource directly and force-reconciling the source — a Flux reconcile alone is not enough because the kustomization is frozen mid-health-check.

**Rule of thumb:** only add `verify: provider: cosign` when you have confirmed the upstream registry signs its releases. For home-operations charts, check the release workflow in the source repo, or look for `*.sig` artifacts alongside the chart tag in GHCR.

---

### Why does every app that uses `valuesFrom` need both a `configMapGenerator` and a `kustomizeconfig.yaml`?

**Short answer:** Kustomize mangles ConfigMap names by appending a content hash. The `kustomizeconfig.yaml` tells it to apply the same rename to the HelmRelease's `valuesFrom` reference — otherwise Flux tries to mount a ConfigMap that doesn't exist.

**Detail:** When Kustomize sees a `configMapGenerator` block, it creates the ConfigMap but renames it from (e.g.) `tuppr-values` to `tuppr-values-6bk9f2t`. The hash is derived from the file contents, so it changes whenever `helm/values.yaml` changes — giving Flux a reliable trigger to re-apply the HelmRelease with the new values.

The problem is that the HelmRelease manifest has a static reference:

```yaml
valuesFrom:
  - kind: ConfigMap
    name: tuppr-values        # ← Kustomize doesn't know to rewrite this by default
```

Without `kustomizeconfig.yaml`, Kustomize rewrites the ConfigMap's own name but leaves the HelmRelease reference pointing at the old bare name. Flux then tries to load `tuppr-values` (no hash), finds nothing, and the HelmRelease fails.

The `kustomizeconfig.yaml` in `app/helm/` registers an additional field spec that tells Kustomize: "also rewrite `spec/valuesFrom/name` inside any `HelmRelease` resource when it matches a generated ConfigMap name." After that, both the ConfigMap and the reference in the HelmRelease carry the same hash, and Flux resolves them correctly.

```yaml
# helm/kustomizeconfig.yaml
nameReference:
  - kind: ConfigMap
    version: v1
    fieldSpecs:
      - path: spec/valuesFrom/name
        kind: HelmRelease
```

**Why bother with the hash at all?** It makes values changes self-propagating in GitOps — Kustomize produces a new ConfigMap name, Flux detects the HelmRelease spec changed, and triggers a Helm upgrade automatically. Without the hash, editing `values.yaml` and pushing would *not* trigger a reconcile because the HelmRelease manifest itself wouldn't change.

---

### Can a HelmRelease override `timeout` (or other fields set by the global `cluster-apps` patch)?

**Short answer:** No — not from within the HelmRelease itself. The global patch always wins because it is injected as the last patch in the rendering chain. To change the timeout for all charts, edit `kubernetes/flux/cluster/ks.yaml`. For a single chart, see the options below.

**Why the HelmRelease's own `timeout:` loses:**

The `cluster-apps` Kustomization injects a nested `spec.patches` entry into every child Kustomization:

```
cluster-apps patches: →  child Kustomization spec.patches: [
                              <any patches from ks.yaml>,   ← applied first
                              <global HelmRelease patch>     ← appended last, always wins
                          ]
```

Kustomize strategic merge patches replace scalar fields, so the last entry to touch `timeout` wins. The global patch is always last. Setting `timeout: 15m` in `helmrelease.yaml` or in `app/kustomization.yaml` is silently overwritten.

**Options for a per-chart timeout:**

**Option A — Change the global default** (`kubernetes/flux/cluster/ks.yaml`)
Simplest. Touch one file. Appropriate when the existing global value is too conservative for a specific workload and raising it is safe for all charts (e.g., bumping `10m → 15m` to accommodate kube-prometheus-stack's CRD + PVC provisioning time).

**Option B — Add a per-Kustomization override in `cluster-apps/ks.yaml`**
Add a second `patches:` block that targets only the specific Kustomization and injects its own HelmRelease patch *after* the global one:

```yaml
# kubernetes/flux/cluster/ks.yaml — appended after the global HelmRelease defaults patch
- patch: |-
    apiVersion: kustomize.toolkit.fluxcd.io/v1
    kind: Kustomization
    metadata:
      name: kube-prometheus-stack
    spec:
      patches:
        - patch: |-
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: kube-prometheus-stack
            spec:
              timeout: 20m
          target:
            kind: HelmRelease
            name: kube-prometheus-stack
  target:
    kind: Kustomization
    name: kube-prometheus-stack
```

Because this entry appears after the global one in `cluster-apps`' `patches:` list, it is appended after in the child's effective patch list and runs last — so `20m` wins. Works correctly, but centralises per-chart knowledge in the cluster-level file.

**Option C — Restructure the global patch to use substitution variables** *(recommended for future refactor)*
Change the global patch to use a Flux postBuild variable with a default:

```yaml
# In the global HelmRelease patch (kubernetes/flux/cluster/ks.yaml):
timeout: "${HELM_TIMEOUT:-15m}"
```

Then any child Kustomization that needs a different value sets it via its `postBuild.substituteFrom` source (the `cluster-secrets` Secret or a per-app ConfigMap):

```yaml
# kubernetes/flux/vars/cluster-settings.yaml (or a per-app override)
data:
  HELM_TIMEOUT: "20m"
```

This keeps per-chart overrides local to the chart's own directory and avoids touching the cluster-level file. It requires: (1) changing the global patch to use the substitution syntax, and (2) each chart that needs a non-default value adding `HELM_TIMEOUT` to its substitution source. The global `cluster-apps` variable substitution patch already runs before the HelmRelease defaults patch, so the variable is resolved correctly.

---

### A resource using `${VARIABLE}` syntax is not being substituted — what's happening?

**Short answer:** The Flux Kustomization that manages the resource has `substitution.flux.home.arpa/disabled: "true"` in its labels. This opts it out of the `cluster-apps` global patch that injects `postBuild.substituteFrom`, so variables are never resolved. The literal `${VARIABLE}` string reaches the API server — either silently wrong or rejected outright by validation.

**How the substitution pipeline works:**

The `cluster-apps` Kustomization (`kubernetes/flux/cluster/ks.yaml`) has a `patches:` block that targets child Kustomizations **without** the `substitution.flux.home.arpa/disabled: "true"` label. Matching Kustomizations receive an injected `postBuild.substituteFrom` pointing at `cluster-settings` ConfigMap and `cluster-secrets` Secret. Kustomizations with the disabled label are excluded entirely — no substitution source is wired up.

**Symptom:**

Adding a resource with `${DOMAIN_CLUSTER}` (or any cluster variable) to a disabled Kustomization causes Flux to apply the literal string. For strictly-validated resource types like `HTTPRoute` (which enforces a DNS hostname regex), the dry-run fails and blocks the entire Kustomization:

```
HTTPRoute.gateway.networking.k8s.io "longhorn" is invalid:
spec.hostnames[0]: Invalid value: "longhorn.${DOMAIN_CLUSTER}":
spec.hostnames[0] in body should match '^(\*\.)?[a-z0-9]...'
```

No resources from that path are applied until the error is resolved.

**Find which Kustomizations have substitution disabled:**

```sh
kubectl get kustomization -n flux-system -o json \
  | jq -r '.items[] | select(.metadata.labels["substitution.flux.home.arpa/disabled"] == "true") | .metadata.name'
```

**Fix:**

Remove the `substitution.flux.home.arpa/disabled: "true"` label from the Kustomization's `ks.yaml`. Existing resources in that path that don't use `${...}` syntax are completely unaffected — substitution is a no-op for them.

---

### What are the risks of bypassing a Kustomization finalizer, and how should I delete a Flux resource safely?

**Short answer:** Bypassing a Kustomization finalizer skips the prune cycle — all managed resources (HelmReleases, namespaces, Deployments) are orphaned in the cluster rather than cleaned up. If orphaned resources include Cilium or CoreDNS, the cluster can lose its network substrate before Flux can react. Always delete Flux resources through Git, not by patching finalizers.

**What the finalizer does:** When a Kustomization with `prune: true` is deleted, kustomize-controller runs a cleanup pass removing every resource the Kustomization applied that no longer appears in the rendered manifests. Only after this pruning cycle completes does the controller clear the finalizer and let Kubernetes finish the deletion. This guarantees nothing is left behind.

**What bypassing does:**
```bash
# This bypasses the prune cycle entirely:
kubectl patch kustomization <name> -n flux-system \
  -p '{"metadata":{"finalizers":[]}}' --type=merge
```
Kubernetes immediately considers the Kustomization deleted. kustomize-controller never runs pruning. All previously-managed resources remain as orphans with no Flux tracking.

**Why this escalates:** If `cluster-apps` (or another Kustomization with `prune: true`) later reconciles and detects that the orphaned resources are no longer declared in the Git path, it prunes them — potentially deleting Cilium, CoreDNS, or other critical infrastructure.

**The 2026-05-15 outage root cause chain:**
```
OCIRepository DENIED (metrics-server, bad URL)
  → cluster-meta health check stuck
    → cluster-apps blocked (dependsOn: cluster-meta)
      → Kustomization finalizer bypassed to try to unblock
        → all cluster-apps children orphaned
          → cluster-apps re-reconciled → prune cycle ran
            → Cilium DaemonSet deleted → CNI gone
              → CoreDNS Deployment deleted → DNS gone
                → Flux controllers stuck ContainerCreating
                  → cluster unable to self-heal
```
Full recovery required manual `helm install` of Cilium, CoreDNS, and flux-instance in sequence, plus recreating the onepassword-connect bootstrap secret.

**The safe deletion path — always through Git:**
1. Remove the resource's entry from the Git path (delete the directory, or remove it from the parent `kustomization.yaml`)
2. Push the change
3. Flux reconciles and prunes cleanly

**Legitimate use of finalizer bypass:** When the Kustomization itself is stuck (e.g. a health check that will never pass) and you need to unblock it. Only safe when the managed resources have already been deleted separately, or you are intentionally abandoning them and will clean up manually. After bypassing, always verify no critical workloads were orphaned.

**The correct unblocking approach for a stuck source:** Instead of bypassing the Kustomization finalizer, fix the source error. A `DENIED` from a registry is not a cluster health issue — it is a misconfigured `OCIRepository` or `HelmRepository`. Delete and recreate the source resource with the correct URL/type. The Kustomization health check will pass once the source resolves.

---

### How do I choose between HelmRepository and OCIRepository — and what happens if I use the wrong one?

**Short answer:** Use `HelmRepository` for charts distributed via a Helm index (`https://` URL, `helm repo add` pattern). Use `OCIRepository` for charts distributed as OCI artifacts (`oci://` URL). Using the wrong type produces `DENIED: requested access to the resource is denied` — the registry path does not exist, and the registry treats that as an access denial.

**How to tell which type a chart uses:**

| Signal | Source type |
|--------|-------------|
| Official docs say `helm repo add <name> https://...` | `HelmRepository` |
| Official docs say `helm install ... oci://ghcr.io/...` | `OCIRepository` |
| [kubesearch.dev](https://kubesearch.dev) shows an `https://` URL | `HelmRepository` |
| [kubesearch.dev](https://kubesearch.dev) shows an `oci://` URL | `OCIRepository` |

**Verify before writing YAML:**
```bash
# HelmRepository — confirm the index file exists:
curl -s https://<repo-url>/index.yaml | head -5

# OCIRepository — confirm the OCI path is reachable:
helm show chart oci://<registry>/<path>:<version>
```

**The metrics-server incident (2026-05-15):** metrics-server publishes a traditional Helm index only — there are no OCI artifacts at `ghcr.io/kubernetes-sigs/charts/metrics-server`. An `OCIRepository` pointing at that path returned `DENIED`. source-controller could not fetch the artifact, which blocked `cluster-meta`'s health check, which blocked `cluster-apps` via `dependsOn`, freezing the entire reconcile tree.

**Correct `HelmRepository` definition for metrics-server:**
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: metrics-server
  namespace: flux-system
spec:
  interval: 1h
  url: https://kubernetes-sigs.github.io/metrics-server
```

**Correct HelmRelease reference** — `chart.spec.sourceRef` for `HelmRepository`; `chartRef` for `OCIRepository`. These are not interchangeable:
```yaml
# HelmRepository-backed (chart.spec.sourceRef):
spec:
  chart:
    spec:
      chart: metrics-server
      # renovate: registryUrl=https://kubernetes-sigs.github.io/metrics-server
      version: 3.13.0
      sourceRef:
        kind: HelmRepository
        name: metrics-server
        namespace: flux-system

# OCIRepository-backed (chartRef):
spec:
  chartRef:
    kind: OCIRepository
    name: <oci-repo-name>
    namespace: flux-system
```

**Prevention rule:** Before writing any new Helm source, run the verification command above and check [kubesearch.dev](https://kubesearch.dev) to confirm the chart is actually published at that URL.

---

### I changed `helm/values.yaml`, pushed, and the Kustomization reconciled — but the HelmRelease never upgraded. Why?

**Short answer:** `driftDetection: mode: enabled` (injected cluster-wide by the `cluster-apps` patch) changes the helm-controller's reconciliation code path. With drift detection enabled, the controller does not immediately re-render values from `valuesFrom` when a referenced ConfigMap changes. The upgrade sits in a queue but won't fire until either the 1h interval elapses or you trigger it manually.

**Detail:** The normal helm-controller flow watches ConfigMaps referenced in `valuesFrom` — when the ConfigMap changes, it queues the HelmRelease for an immediate reconcile. With `driftDetection: mode: enabled`, the controller instead uses a drift-check loop that compares deployed resources against chart manifests. The `valuesFrom` hash change is detected but processed behind the drift cycle rather than immediately, so the upgrade is effectively delayed by up to the full `interval` (1h in this cluster).

Concretely: the Kustomization applies the updated ConfigMap and reports `Ready` (in under a second, because `wait: false`) while the HelmRelease still shows the old `configDigest` in its status. The HelmRelease is not failing — it just hasn't run yet.

**Fix — force the upgrade immediately:**

```bash
KUBECONFIG=/workspaces/home-lab/kubeconfig \
  flux reconcile helmrelease <name> -n <namespace> --with-source
```

`--with-source` re-fetches the OCIRepository artifact first; omit it if only values changed (not the chart version), since the source is already current.

**How to confirm the upgrade happened:** the HelmRelease `status.history[0].configDigest` will change to a new hash, and `status.conditions[0].message` will read `Helm upgrade succeeded`.

**Affected releases:** every HelmRelease in this cluster, because `cluster-apps` injects `driftDetection: mode: enabled` via a nested patch on all child Kustomizations.

---

## Kubernetes Workloads

### A healthy Deployment shows both `Available` and `Progressing` — is something wrong?

**Short answer:** No. `Progressing=True` is the permanent **success** state after a rollout completes. It does not mean the rollout is still running.

**Detail:** Kubernetes Deployments carry three conditions:

| Condition | Meaning |
|-----------|---------|
| `Available` | The deployment has at least the desired number of ready pods right now |
| `Progressing` | The last rollout completed successfully (`NewReplicaSetAvailable`) — or is actively rolling out |
| `ReplicaFailure` | Pods could not be created (e.g. image pull error, resource quota) |

The counter-intuitive part: Kubernetes sets `Progressing=True` when a rollout completes and **never clears it**. A fully healthy, idle deployment that rolled out days ago will still show `Progressing=True`. UIs (Lens, k9s) often render this condition alongside `Available`, making it look alarming.

**The only bad `Progressing` state** is `Progressing=False` with reason `ProgressDeadlineExceeded` — meaning a rollout *started* but stalled before completing within `spec.progressDeadlineSeconds` (default 600 s). That is the signal to investigate.

**How to check from the CLI:**

```bash
# Quick sanity check — look for Progressing=False or ReplicaFailure=True
kubectl describe deployment <name> -n <ns> | grep -A3 "Conditions:"

# All conditions at once
kubectl get deployment <name> -n <ns> -o jsonpath='{.status.conditions[*]}'
```

**Common trigger in this cluster:** Running `task reconcile` or pushing a commit causes Flux to reconcile and possibly issue a Helm upgrade. This creates a new ReplicaSet (visible in the Deployment's "Deploy Revisions" in Lens), the old one scales to 0, and `Progressing` reflects the completed rollout. The old ReplicaSet lingers at 0 replicas (Kubernetes keeps a history for rollback); that is also normal.

---

## Upgrades (tuppr + Renovate)

### Does Renovate create incremental PRs for each Talos/K8s minor version, or one PR jumping to the latest?

**Short answer:** One PR to the latest — `separateMinorPatch: true` separates minor PRs from patch PRs, but within the minor category it still jumps to the newest available version.

**Detail:** With the current config, if the cluster is on `v1.10.6` and both `v1.11.x` and `v1.12.x` are released, Renovate opens a single minor PR targeting `v1.12.x` — not two separate PRs stepping through `v1.11` first. Both Talos and Kubernetes require sequential minor upgrades (you cannot skip `v1.11` entirely), so merging such a PR and letting tuppr act on it would fail.

**Is this a real risk?** For a weekly Renovate schedule and a cluster that is kept reasonably current, in practice no. Talos releases minor versions roughly every 2–3 months; running weekly means you are almost never more than one minor behind when Renovate opens the PR.

**What to do when a minor-bump PR arrives:**
1. Open the PR and check the version jump in `talosupgrade.yaml` (and `talenv.yaml`).
2. If it skips a minor (e.g. `v1.10.x → v1.12.y`), edit the PR to target only the next minor (`v1.11.latest`) and merge that first.
3. After tuppr finishes the rolling upgrade, Renovate will re-open with the next step.

Patch PRs (e.g. `v1.10.6 → v1.10.9`) are always safe to merge directly — Talos supports arbitrary patch skips within a minor.

---

### Why does tuppr start spawning failing "downgrade" jobs after a manual Kubernetes upgrade?

**Short answer:** When you run `talosctl upgrade-k8s` manually, the cluster advances to the new version *before* Git is updated. tuppr sees `CURRENT > TARGET` and tries to reconcile backward. `talosctl` refuses downgrade paths (e.g. 1.35→1.34), so the jobs fail safely — but they loop indefinitely until the CRD is cleaned up.

**Detail:** tuppr reconciles by comparing the running kubelet version against `spec.kubernetes.version` in the `KubernetesUpgrade` resource. If you run `upgrade-k8s --to v1.35.4` manually before updating `kubernetesupgrade.yaml` in Git, the CRD still declares `v1.34.7`. tuppr spawns jobs targeting `v1.34.7`, each job calls `upgrade-k8s` internally and immediately fails with "unsupported upgrade path 1.35→1.34". The admission webhook then blocks Flux from updating the spec while the phase is `Upgrading`.

**Fix:**
```bash
kubectl delete kubernetesupgrade kubernetes -n system-upgrade
kubectl delete jobs -n system-upgrade --all   # owned jobs cascade on CRD delete; belt-and-suspenders
flux reconcile source git flux-system && flux reconcile kustomization tuppr-upgrade
```
Flux recreates the resource from the current Git state (which should already have the new version), tuppr sees `CURRENT == TARGET`, and marks it `Completed` immediately.

**How to avoid it:** Use the tuppr-native path — merge the Renovate PR and let tuppr drive the upgrade. The cluster and Git advance together; no mismatch.

---

### What caused the kube-apiserver v1.34.7 crash loop, and will it happen again?

**Short answer:** `kube-apiserver v1.34.7` opens ~100 gRPC channels to etcd *simultaneously* at startup, overwhelming etcd's TLS handshake queue. The `rbac/bootstrap-roles` PostStartHook times out fatally. On 3 nodes upgraded in rapid succession, backoff timers re-synchronise into waves that prevent recovery indefinitely.

**Detail:** The crash sequence is:
1. `kube-apiserver` starts → opens ~100 gRPC channels to etcd within 100 ms
2. etcd's TLS handshake queue saturates → internal etcd client delays
3. Informer cache sync delays → `rbac/bootstrap-roles` PostStartHook times out (`F0512 hooks.go:204 PostStartHook "rbac/bootstrap-roles" failed`)
4. `F` = Fatal → kubelet restarts with exponential backoff
5. Three nodes upgraded simultaneously → backoff waves synchronise → permanent thundering-herd

**What was NOT the cause:** Talos version (stable throughout); etcd corruption (3-member quorum maintained); feature gate flags (admission controllers loaded successfully every startup — red herring).

**Fix applied:** Remove feature gates (`MutatingAdmissionPolicy`, `v1alpha1` runtime-config) that would have caused unrelated errors; upgrade apiservers *one node at a time* using `talosctl patch mc` with a strategic merge patch, waiting for a 2-minute stable PID before touching the next node.

**Will it recur?** v1.35.4 and v1.36.0 upgrades completed without incident using `talosctl upgrade-k8s` (sequential, not simultaneous). The thundering-herd appears to have been specific to v1.34's gRPC connection pool behaviour, or the single-node-at-a-time sequencing in `upgrade-k8s` provides sufficient spacing. Continue using tuppr's automatic path; fall back to manual `patch mc` with 2-minute windows only if a crash loop is observed.

---

### Why does `task talos:wipe-ceph-osds-live` fail after a cluster reset?

**Short answer:** Talos's `block.LVMActivationController` locks the entire LVM VG (physical disk + all logical volumes) as a unit. Neither `dmsetup remove --force` inside a privileged pod nor `talosctl wipe disk` can break that lock while the controller holds it. The fix is a two-step process: destroy the LVM PV header on the raw disk with `dd`, then reboot the node.

> **This is now automated.** `task talos:wipe-ceph-osds-live` (the `live-osd-cleanup` bootstrap stage) detects when a node still holds active `ceph-*` dm devices — the wipe pod emits a `REBOOT_REQUIRED=1` sentinel — and reboots those nodes itself, **staggered one at a time and gated on each control-plane node's etcd rejoining before the next**, so quorum is preserved. Because this stage runs *before* Cilium/CoreDNS/workloads are installed, the reboot happens while there are no PVCs to multi-attach and no Ceph to degrade — the safe window. The manual sequence below is only a fallback for a running cluster (e.g. a single replacement disk day-2).

**Detail:** When Talos boots with a disk that has Ceph LVM metadata (left over from a previous cluster), the `LVMActivationController` activates the Ceph VG and creates `dm-0`/`dm-1` device-mapper entries. It then holds these as a locked group in its internal state. This causes two failure modes:

1. **`dmsetup remove --force` hangs** — the controller continuously tries to re-activate the VG while the pod is trying to remove the DM device. `--force` bypasses some checks but does not interrupt a held lock; the `find -exec dmsetup remove` call never returns.
2. **`talosctl wipe disk nvme0n1` fails** with `FailedPrecondition: blockdevice "nvme0n1" is in use by disk "dm-0"` — Talos's wipe API enforces the same group lock.

**Why `dd` breaks the cycle:** `dd if=/dev/zero of=/dev/nvme0n1 bs=1M count=16 oflag=direct` writes directly to the raw block device, bypassing the DM layer entirely. Linux allows raw writes to a device even when DM devices are mapped on top of it — the DM layer is a logical overlay, not an exclusive lock at the kernel block level. Once the LVM PV header (at the start of the disk) is zeroed, Talos's controller rescans on its next pass and finds no LVM signature. Its `discoveredvolumes` status for `nvme0n1` transitions from `lvm2-pv` to blank.

**Why a reboot is still required:** Zeroing the PV header tells the controller there is no VG to activate, but the DM devices (`dm-0`, `dm-1`) that were created at boot are already in the kernel DM table and are not removed automatically — Talos's wipe API zeroed their content but did not issue `dmsetup remove`. A node reboot clears all kernel DM state; because the PV metadata is gone, the controller finds nothing to activate on the next boot and the disk comes up clean.

**Full recovery sequence (v1.13.x):**

```bash
# 1. Zero the LVM PV header — destroys the signature the controller reads
talosctl -n <NODE_IP> wipe disk dm-0 dm-1      # zeros DM content (optional belt-and-suspenders)
# OR from inside the wipe-osd-lvm.sh privileged pod:
# dd if=/dev/zero of=/dev/nvme0n1 bs=1M count=16 oflag=direct conv=notrunc

# 2. Verify Talos no longer sees an LVM PV on the disk
talosctl -n <NODE_IP> get discoveredvolumes | grep nvme0n1
# Should show: disk  2.0 TB  (no "lvm2-pv" type)

# 3. Reboot the node to flush kernel DM state
talosctl -n <NODE_IP> reboot
# Wait for node to rejoin (check: kubectl get nodes)

# 4. Confirm the disk is clean
talosctl -n <NODE_IP> ls /dev/disk/by-id | grep ceph    # should be empty
talosctl -n <NODE_IP> get discoveredvolumes | grep nvme0n1  # still blank
```

**Reboot safety:** OSD nodes can be rebooted one at a time without risk, which is exactly what the automated stage does. Rebooting any single control-plane node (cp-01/02/03) leaves 2/3 etcd members active (sufficient quorum); the workers (worker-01/02) are not etcd members. The automated path additionally waits for the rebooted CP node's etcd to answer the member-list RPC again before moving to the next node, so quorum is never at risk even across multiple CP reboots in one pass.

**v1.14 will fix this natively:** Talos v1.14 (in alpha as of 2026-06) adds `talosctl wipe lv <name>`, `talosctl wipe vg <name>`, and `talosctl wipe pv <name>` commands that go through the controller's own deactivation path instead of fighting it. Once v1.14 is stable, the `live-osd-cleanup` bootstrap step can be simplified to call these commands directly instead of deploying privileged pods. See [ROADMAP.md → Talos Config Audit](ROADMAP.md#talos-config-image-extensions--patch-audit) for the upgrade note.

---

## Observability / Alerting

### Why did a "Ceph" alert (`CephNodeNetworkPacketDrops`) fire for packet drops on a management NIC, when Ceph traffic runs on the storage VLAN?

**Short answer:** the alert name is misleading. Rook's bundled `CephNodeNetworkPacketDrops` rule (from the upstream ceph-mixin) has no network-scoping in its PromQL — it checks `device!="lo"` and nothing else, meaning it fires on *any* interface on *any* node node-exporter runs on, not specifically Ceph's `cluster_network`/`public_network` interfaces. It only carries the "Ceph" name because the upstream mixin assumes Ceph owns dedicated hardware (every NIC on a Ceph node *is* "a Ceph NIC" in that world) — not true here, where Ceph's **replication** traffic cleanly rides the `10.200.0.0/24` storage bond and is unaffected by management-NIC drops.

> **Correction (2026-08-19):** the line above previously said "the management NIC is functionally unrelated to [Ceph]" — that's not accurate. Live config confirmed via `ceph config get mon public_network`/`cluster_network` during a Full-Cluster Cold Start: `cluster_network = 10.200.0.0/24` (storage bond, replication + heartbeat-back only) but **`public_network = 10.60.0.0/24`** (management) — so OSD client I/O and heartbeat-front traffic genuinely does ride the management NIC by design. The original point about the alert's PromQL not being network-scoped still stands; it just doesn't follow that management-NIC drops are irrelevant to Ceph — a sustained drop there could plausibly affect client I/O or heartbeat-front, just not replication/backfill.

**What actually happened (2026-06-20):** a genuine, brief traffic burst on `eno1` (the management NIC) on `talos-worker-02` — packet rate jumped from a ~200/s baseline to ~2000/s for about 60–90 seconds (09:00:30–09:01:00 UTC), tripping the rule's `≥10 drops/sec` threshold. Checked for a cause via Prometheus: CPU was flat (no starvation-driven ring-buffer overflow), no pod restarts occurred cluster-wide in that window, and Spegel (the most likely "bursty host traffic" source) doesn't use `hostNetwork` so it can't directly explain a host-interface spike. Root cause of the burst itself was not identified — pinning it down would need kernel `dmesg` or a live packet capture from the moment it happened, which isn't retroactively recoverable from Prometheus metrics alone.

**When to dig further:** treat a single occurrence as noise — it self-resolved within a minute and hasn't recurred. If it starts recurring, capture `talosctl dmesg` and interface stats live (via the `talos-node-manager` agent) at the moment it fires; that's the only way to actually catch the responsible traffic.

**Encountered 2026-06-20** while verifying the newly-wired Alertmanager → Pushover pipeline (see [ROADMAP.md → Alertmanager Receiver](ROADMAP.md#alertmanager-receiver)).

**2026-07-18 follow-up — debounced, not eliminated:** the burst turned out to be recurring (5 episodes over 2026-07-11 → 07-18), always lasting a single 30s rule-evaluation tick. Added `CephNodeNetworkPacketDrops: { for: 1m }` to `prometheusRuleOverrides` in `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml` — requires 2 consecutive bad evaluations (60s) before firing, which filters the single-tick blips while still catching a genuinely sustained drop (e.g. a failing NIC) within a minute. See `docs/SESSIONS.md` → `diagnose-alerts-command-and-ceph-packetdrops-tuning`.

**2026-08-05 follow-up — isolated the affected hardware, still no root cause for the burst itself:** the periodic burst (roughly every 3 minutes) hits the management NIC on **all of** `talos-cp-02`, `talos-cp-03`, `talos-worker-01`, and `talos-worker-02` at essentially the same time, but **never** `talos-cp-01`. Cross-referencing `talos/talconfig.yaml`, the difference is the management NIC chipset, not node role (VIP-eligible control planes and non-eligible workers are both on the affected list): the four affected nodes all use an **Intel I219-LM** (`e1000e` driver); `cp-01` alone uses a newer **Intel I225/I226** (`igc` driver). Confirmed via `rate(node_network_receive_fifo_total[1m])` that the drops are receive-only with **zero FIFO/hardware ring-buffer errors** — meaning this isn't link saturation or a bad cable, it's the kernel's software RX path (`netif_rx` backlog) briefly falling behind a short burst, something a lot more likely on an older single-queue `e1000e` chip than a newer `igc` one. Of the four affected nodes, only `talos-cp-02` has actually crossed the `for: 1m` threshold and paged (3-9 times/day); the other three self-resolve as `pending` within the debounce window. The burst's *source* is still unidentified — same limitation as 2026-06-20, this needs a live packet capture or `dmesg` at the exact moment, not retroactive Prometheus queries.

---

## Database / Backups

### Why did Backblaze B2 WAL archiving fail with `IncompleteBody: The request body was too small` after migrating off Storj?

**Short answer:** the bucket name contained a literal dot (`vwn.io-cluster-cnpg`). AWS's own S3 docs warn against periods in bucket names specifically because of HTTPS/virtual-hosted-style hostname-matching issues, and Backblaze's S3-compatible API broke the same way. Renaming to a dot-free bucket fixed it immediately — none of the other things tried (chart version, `maxParallel`, trailing slash, region) were the actual cause.

**The trap:** `exit status 4` from `barman-cloud-wal-archive` is a generic wrapper error code — the real message is one level down, in `barman-cloud-wal-archive`'s own stderr. Multiple *different*, real GitHub issues (`cloudnative-pg/cloudnative-pg#7105`, `#9724`) document *different* root causes that all surface as the same generic `exit status 4` against B2/MinIO/IBM S3/Hetzner — a `maxParallel`/trailing-slash workaround for one user, a region-signing bug for another. None of those fixes were wrong in general, they just weren't *this* cluster's problem — each was tried and empirically disproven against the live cluster before moving to the next theory.

**What actually settled it:** comparing against a known-working reference (`bykaj/home-ops`, running barman-cloud against B2 in the same region, `us-west-001`) showed a far simpler config than what had been built up — no `maxParallel` override, no region setting, no trailing slash. The only remaining real difference was the bucket name itself.

**Detail — why a dot in a bucket name breaks HTTPS:** S3-style virtual-hosted addressing puts the bucket name in the hostname (`bucket.s3.region.example.com`). A wildcard TLS certificate (`*.s3.region.example.com`) only matches one DNS label — a bucket name containing a dot turns part of the bucket name into what looks like an extra hostname label, breaking certificate/hostname validation for any code path that constructs (even transiently) a virtual-hosted-style request, even when the configured `endpointURL` is otherwise path-style.

**Encountered 2026-06-21** during the Storj → Backblaze B2 backup migration (see [ROADMAP.md → CloudNativePG: Backup, PITR, and Per-App Provisioning](ROADMAP.md#cloudnative-pg-backup-pitr-and-per-app-provisioning)).

---

## Autoscaling (KEDA)

### pgadmin's homepage tile shows "Not Found" when it's scaled to zero — is the KEDA HTTP Add-on broken?

**Short answer:** No. That's homepage's Kubernetes-mode pod-status widget correctly reporting "no pod exists right now" — a cosmetic side effect of scale-to-zero, not an HTTP-level failure anywhere in the request path.

**Detail:** homepage discovers pgadmin via `gethomepage.dev/*` annotations on its `HTTPRoute` (`mode: cluster`, `gateway: true` in `kubernetes.yaml`) and shows pod/container status by querying the Kubernetes API directly for pods matching pgadmin's label selector — it does not make an HTTP request through the Gateway for this widget. When the `ScaledObject` has scaled pgadmin to 0 replicas, there is no pod to find, so the tile shows "Not Found." This is unrelated to whether the actual request path (Envoy Gateway → `HTTPRoute` → KEDA HTTP Add-on interceptor → pgadmin) is working.

**Verified working, twice, from inside the cluster (2026-07-10)** while pgadmin was at 0 replicas:
- Direct to the interceptor Service (`keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local:8080`) with the correct `Host` header — `302 Found` (pgadmin's normal redirect to `/login`) plus an `X-Keda-Http-Cold-Start: true` response header, and the pod scaled 0→1.
- Through the full external path (HTTPS + SNI straight at the `envoy-internal` Gateway Service, exactly what a browser hits) — same result.

Both confirm the interceptor → KEDA → scale-up chain works end-to-end. The homepage tile's "Not Found" only reflects the pod-count check, not a routing bug — clicking the tile's actual link still works correctly.

**Cold-start feedback:** by default the interceptor silently holds the first request open until pgadmin's pod becomes ready, which can look like a hung page with no explanation if the cold start takes more than a couple of seconds. `kubernetes/apps/database/pgadmin/app/interceptorroute.yaml` addresses this with `coldStart.placeholder` — an immediate "Starting pgAdmin…" page, auto-refreshing until pgadmin is ready. See the next entry for a real gotcha this combination hits with the wrong `scalingMetric`.

---

### Why did the KEDA HTTP Add-on stop scaling pgadmin back up after adding a `coldStart.placeholder`?

**Short answer:** with `scalingMetric.concurrency` (the initial config), yes — `coldStart.placeholder` serves its static response *before* the request registers as demand long enough for KEDA to notice, so pgadmin never scales back up and the placeholder shows forever. Switching to `scalingMetric.requestRate` fixes it completely, with no other changes — confirmed by reading the interceptor's actual source (not guessed) and verified live.

**Detail — why `concurrency` breaks:** the interceptor's request pipeline (`interceptor/proxy.go` in `kedacore/http-add-on`, chart v0.15.0) wraps handlers outermost-first as `Routing → Counting → Placeholder → (proxy to backend)`. `Counting` (`pkg/queue/queue.go`, `Memory.Increase`/`Decrease`) tracks **two independent counters per host**: an in-flight `concurrency` gauge and a separate monotonic `requestCount` that only ever goes up. `Placeholder` sits inside `Counting`: with no ready endpoint, it writes its response and returns in microseconds, so `concurrency` is back to 0 before the scaler's external component ever samples it — that component *polls* each interceptor's queue counts on a fixed ticker (`KEDA_HTTP_SCALER_STREAM_INTERVAL_MS`, chart default **200ms**; see `scaler/queue_pinger.go`), and a microsecond-wide gauge blip essentially never lands inside a 200ms window. `ScaledObject.status.conditions[Active]` never flips `True`, and pgadmin stays at 0 replicas indefinitely.

**Why `requestRate` doesn't have this problem:** the scaler computes `RequestRate` as a delta of the *monotonic* `requestCount` between two polls (`scaler/queue_pinger.go`'s `aggregatedCount`/`prevPodCounts`). `Counting` increments `requestCount` on every request — including placeholder-served ones, since `Counting` runs *before* `Placeholder` short-circuits — and nothing ever decrements it. A request that comes and goes in microseconds still shows up as `+1` at the very next poll, regardless of how briefly it was "in flight." Switching `kubernetes/apps/database/pgadmin/app/interceptorroute.yaml`'s `scalingMetric` from `concurrency` to `requestRate` (identical `coldStart.placeholder`, no other changes) fixed it.

**Verified live (2026-07-10), from a genuinely cold, idle state** (75s wait to flush the `requestRate` window of prior test traffic, confirmed `ScaledObject.status.conditions[Active] == False` and 0 pods first): a single request got the placeholder (`HTTP 503` in ~5ms — proving it wasn't held), and `Active` flipped `True` within seconds, with a `Ready` pod at ~35s.

**A heavier alternative was tried first and abandoned:** `coldStart.fallback` (route to a separate, always-on Service after `timeouts.readiness` elapses) also works, since a fallback-bound request is genuinely held — and counted — until the timeout, unlike a placeholder. It was dropped once `requestRate` proved sufficient, since a fallback requires deploying and permanently running a second workload (e.g. a small nginx pod) just to serve a static page — the `requestRate` fix needs zero extra infrastructure. `fallback` is still the right tool if a route genuinely can't tolerate the placeholder's "instant response with no proxying" semantics (e.g. it needs to preserve method/body for the eventual retry), or if `concurrency` scaling is required for a workload that doesn't have `requestRate` as a genuine option — see the CRD's `scalingMetric` docs, both may be set simultaneously and KEDA scales on whichever demands more replicas.

**Encountered 2026-07-10**, same session as the `pgadmin` scale-to-zero deployment (see `docs/dra-gpu-migration-plan.md`'s sibling doc `docs/keda-nfs-scaler-plan.md` for the broader KEDA context).

**Related:** [CONVENTIONS.md → Drift Detection → Ignore rules](CONVENTIONS.md#ignore-rules-preferred-over-full-opt-out) (KEDA `ScaledObject`s need a `driftDetection.ignore` override or Flux reverts the scale-to-zero); `docs/keda-nfs-scaler-plan.md` for the (currently unrelated, NFS-specific) KEDA scaling pattern this cluster may adopt later.
