# kube-system

The cluster's own plumbing: the CNI, cluster DNS, the image mirror and the metrics API. Talos ships none of these (no CNI, no kube-proxy, no CoreDNS), so nothing else starts until Cilium and CoreDNS do.

## Apps

| App            | What it does                                                           | Notes                                                                                         |
| -------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| cilium         | CNI, kube-proxy replacement, LoadBalancer addresses (LB-IPAM, BGP, L2) | Two Kustomizations: `cilium` (chart) → `cilium-config` (the CRs in [config](./cilium/config)) |
| coredns        | Cluster DNS on `10.43.0.10`                                            | One replica per control-plane node                                                            |
| spegel         | Peer-to-peer registry mirror: nodes pull images from each other        | Writes its mirror config where Talos's containerd reads it                                    |
| metrics-server | Resource metrics API (`kubectl top`, HPA)                              | The only app here that bootstrap doesn't install                                              |

## How it fits together

**Bootstrap installs these before Flux exists.** The helmfile in [bootstrap/kubernetes](../../../bootstrap/kubernetes/README.md) installs cilium, coredns and spegel straight from their `app/` folders, and applies `cilium/config` with `kubectl apply -k`. Nothing substitutes `${VAR}` on that path, so these Kustomizations carry `substitution.flux.home.arpa/disabled` and their files hold literal values, such as the hostname in [service.yaml](./cilium/config/service.yaml).

**Cilium reaches the API through KubePrism** (`127.0.0.1:7445`), Talos's per-node proxy, not through the VIP. `socketLB.hostNamespaceOnly` keeps socket load-balancing out of the pods' path to it, and only takes effect with `socketLB.enabled: true`.

**LoadBalancer addresses are announced two ways, split by namespace:**

| Address              | Service           | Announced by                                  |
| -------------------- | ----------------- | --------------------------------------------- |
| `10.60.0.2`          | `kube-api`        | Talos's Layer-2 VIP (ARP), and BGP            |
| `10.60.0.230`–`.249` | everything else   | BGP                                           |
| `10.30.0.240`        | `mail/smtp-relay` | L2 (ARP) on the nodes' VLAN 30 sub-interfaces |
| `10.30.0.234`        | `media/plex`      | L2 (ARP) on the nodes' VLAN 30 sub-interfaces |

The L2 policy in [networks.yaml](./cilium/config/networks.yaml) selects the `mail` and `media` namespaces; the BGP advertisement in [l3.yaml](./cilium/config/l3.yaml) selects every namespace but those two. A new LoadBalancer Service anywhere else gets BGP with nothing to update.

**BGP** peers every node (AS 64514) with the gateway (AS 64513, `10.60.0.1`). The gateway side is [bgp.conf](./cilium/config/bgp.conf), pasted into the UniFi UI by hand; nothing applies it. It accepts only `10.60.0.2` and the general pool.

## Operating

```bash
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg bgp peers
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg bgp routes advertised ipv4 unicast
```

`status` should show `Host: BPF` routing. Each node should have one `established` session and advertise one `/32` per BGP-announced Service.

## Gotchas

- **The IoT addresses must stay on L2.** A device on VLAN 30 (the printer, a TV streamer) can't route to `10.60.0.0/24`: the gateway blocks IoT-initiated traffic to other VLANs. It needs an address in its own segment, which BGP can't give. A LoadBalancer Service added to `mail` or `media` gets L2 only, never BGP.
- **`devices: eno1+ enp4s0+ bond-storage` is exact on purpose.** Cilium announces L2 addresses only on listed devices. The trailing `+` matches the management NIC and its `.30` VLAN sub-interface (defined per node in [talos/nodes](../../talos/nodes)); plain names dropped the sub-interfaces and broke both IoT addresses on 2026-09-03. A bare `eno+`/`enp+` would also match the storage bond's member NICs, which must not be attached directly. `bond-storage` is listed so pods have a route to Ceph's public network (`10.200.0.0/24`).
- **`kube-api` shares `10.60.0.2` with Talos's `Layer2VIPConfig`.** Talos answers ARP for it from boot, without Cilium. The Service exists so external-dns can publish a name and so BGP can spread routed clients over the nodes. It is kept out of L2 announcement (it lives in `kube-system`), or the address would have two ARP owners.
- **`externalTrafficPolicy: Cluster` on `kube-api`.** Cilium's L2 leader election ignores where the endpoints are, so `Local` can black-hole an address on a node without an API server. The address is on BGP now; `Cluster` stays so a move back to L2 can't bite. DSR (`loadBalancer.mode`) keeps the client IP either way.
- **MTU stays 1500**, although the storage bond carries 9000. Cilium has one MTU for the whole cluster. At 9000, pods sent jumbo frames down the 1500 management path and anything relying on path-MTU discovery stalled (CNPG replication handshakes hung for minutes) while small packets worked. `pmtuDiscovery` complements the pin, it doesn't replace it. Host-networked Ceph daemons are unaffected; pod traffic to `10.200.0.0/24` is capped at 1500.
- **The L2 policy names no interfaces**, so it announces on every device. That is harmless on `bond-storage`: its subnet has no gateway.
- **BPF host routing depends on Talos.** With `bpf.masquerade`, it breaks DNS that Talos forwards to the host resolver ([cilium#36761](https://github.com/cilium/cilium/issues/36761)). `forwardKubeDNSToHost: false` in [cluster.yaml.j2](../../talos/cluster.yaml.j2) avoids that. If it is ever turned on, set `bpf.hostLegacyRouting: true` here.
- **Bandwidth manager with BBR is off.** It needs BPF host routing and crash-looped the agent on 2026-09-13, when the cluster still ran legacy host routing. Untested since.
- **BGP timers are short** (9s hold, 3s keepalive) for fast failover; the gateway accepts what the peer offers. `maximum-paths 5` in `bgp.conf` matches the node count: a sixth node's routes would be accepted and never installed. Per-connection ECMP hashing needs `net.ipv4.fib_multipath_hash_policy=1` on the gateway, which is set there, not in Git.
- **BGP sessions are unauthenticated**: peers are trusted by source address and AS number. Hardening means a `password` on the gateway and a matching `authSecretRef` on the `CiliumBGPPeerConfig`, with the Secret in `kube-system`.
- **Hubble runs with Relay only.** No UI and no metrics, so `hubble.metrics.dashboards` stays off too.
- **The Grafana dashboards come from the chart** (`dashboards.enabled`, `operator.dashboards.enabled`) as ConfigMaps, which [grafanadashboard.yaml](./cilium/app/grafanadashboard.yaml) loads. The `GrafanaDashboard` CRD is installed by bootstrap, so `cilium` needs no `dependsOn` for it.
