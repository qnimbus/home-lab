# mail

Outbound mail for devices and apps that can't talk to the mail provider themselves. One relay accepts mail without credentials and forwards it through an authenticated upstream.

## Apps

| App                          | What it does                                                   | Notes                                                                                                |
| ---------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| [`smtp-relay`](./smtp-relay) | [maddy](https://maddy.email) as a send-only relay on port `25` | LoadBalancer with an address on VLAN 60 and one on the IoT VLAN; upstream credentials from 1Password |

## How it fits together

```text
printer (IoT VLAN) ──► 10.30.0.240:25 ─┐
LAN clients ─────────► 10.60.0.240:25 ─┼─► maddy :2525 ──► queue ──► upstream (STARTTLS + auth)
in-cluster apps ─────► ClusterIP:25 ───┘
```

- **Two LoadBalancer addresses on one Service.** `lbipam.cilium.io/ips` pins both: one from the default pool, one from `pool-iot-smtp-relay`, a single-address pool that selects only this Service ([pool.yaml](../kube-system/cilium/config/pool.yaml)).
- **Two DNS names, declared in two places.** `smtp-relay.${DOMAIN_CLUSTER}` comes from the Service's `external-dns.kubernetes.io/hostname` annotation. The IoT name comes from [dnsendpoint.yaml](./smtp-relay/app/dnsendpoint.yaml), because external-dns publishes every hostname on a Service against every one of its addresses. `external-dns.kubernetes.io/target` pins the annotated name to the VLAN 60 address, and it would pin a second annotated name to that same address.
- **The upstream** is whatever the `smtp-relay` item in 1Password points at. [externalsecret.yaml](./smtp-relay/app/externalsecret.yaml) maps its fields onto the `SMTP_RELAY_*` variables that `maddy.conf` reads with `{env:…}`. The config itself is inline in [helmrelease.yaml](./smtp-relay/app/helmrelease.yaml).

## Operating

```bash
kubectl -n mail logs deploy/smtp-relay -f                 # accepted mail and the upstream's answers
grep -rln "smtp-relay" kubernetes --include=*.yaml        # who sends through it, and who probes it
```

## Gotchas

- **The relay accepts mail from anyone who can reach it.** There is no authentication and no TLS on the listener. `loadBalancerSourceRanges` is the only guard, and it only covers the two LoadBalancer addresses: Cilium doesn't apply it to the ClusterIP, so every pod in the cluster can send. Widen the list when another device needs the relay; don't treat it as protection against in-cluster senders.
- **`externalTrafficPolicy` must not be `Local`.** Cilium's L2 announcement picks the announcing node without looking at where the pod runs. With `Local`, a leader on a node without the pod drops every connection until the lease moves. The source ranges are checked against the real client address either way.
- **maddy listens on `2525`, the Service maps `25` onto it.** The container runs as non-root with all capabilities dropped, so it never has to bind a privileged port.
- **The queue is on an `emptyDir`.** `state_dir` is `/cache/state`, so mail that is accepted but not yet delivered upstream is lost when the pod is replaced.
- **The sender address has to be one the upstream accepts.** See `MAIL_FROM_ADDRESS` in the [`cluster-settings` README](../../components/cluster-settings/README.md).
- **`smtp-relay.iot.${DOMAIN_IO}` is the name the printer is configured with.** It is a second record in the DNSEndpoint, outside the naming scheme. Remove it once the printer uses `smtp-relay.iot.home.${DOMAIN_IO}`.
- **`dependsOn` both external-dns instances** is deliberate: `external-dns-cloudflare`'s exclusion list is what keeps the IoT record out of public DNS (see [flux-kustomization.instructions.md](../../../.agents/instructions/flux-kustomization.instructions.md)).
- **The blackbox probe goes through the in-cluster Service** and sends a `QUIT`: maddy logs an error for every connection dropped without one.
