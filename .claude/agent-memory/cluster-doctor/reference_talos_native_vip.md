---
name: reference_talos_native_vip
description: This cluster's VIP is Talos's native built-in VIP feature, not a kube-vip Kubernetes pod/DaemonSet — do not search kube-system for kube-vip pods
metadata:
  type: reference
---

The cluster-doctor agent description (and the older 3-CP-node frontmatter) describes kube-vip as
running "as static pods" in ARP mode, implying it would show up via `kubectl -n kube-system get
pods -l app.kubernetes.io/name=kube-vip` or as a containerd container in the `kube-system`
namespace per node.

That is wrong for this cluster's actual implementation. The VIP is configured directly in
`talos/talconfig.yaml` per control-plane node, under the management `networkInterfaces` entry:

```yaml
networkInterfaces:
  - deviceSelector: {...}
    addresses: ["10.60.0.20X/24"]
    vip:
      ip: "${clusterEndpoint}"
```

This is Talos's own native VIP networking controller — handled entirely inside the Talos OS
networking stack, not a Kubernetes workload at all. There is no `kube-vip` pod, no DaemonSet, no
containerd container named anything like "vip" on any node. Searching for one and finding nothing
is expected and is NOT evidence of an outage or misconfiguration.

To check VIP/failover health on this cluster, use:
- `talosctl get addresses` per node — shows which node currently has the VIP bound
- Talos kernel/controller-runtime logs (`talosctl dmesg`, `talosctl logs controller-runtime` if
  needed) for VIP-related network controller messages
- Direct TCP/TLS probe to the VIP (`curl -k https://10.60.0.2:6443/healthz`)

Also relevant: KubePrism (`machine.features.kubePrism`, port 7445) is enabled cluster-wide and is
the actual mechanism for in-cluster API resilience — internal workloads (Flux, cert-manager, ESO)
talk to `127.0.0.1:7445`, not the VIP. The VIP is only on the path for *external* clients
(kubectl/flux from the devcontainer, talosctl). This means a VIP failover event has a much smaller
blast radius on this cluster than the generic kube-vip documentation implies — in-cluster
controllers do not stall waiting for ARP convergence.

See also [[reference_apiserver_etcd_loopback_noise]] for a related false-lead encountered in the
same investigation (2026-06-18).
