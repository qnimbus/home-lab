# mail

Outbound mail for devices and apps that can't talk to the mail provider themselves. One relay accepts mail without credentials and forwards it through an authenticated upstream.

## Apps

| App                          | What it does                                                   | Notes                                                                                                |
| ---------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| [`smtp-relay`](./smtp-relay) | [maddy](https://maddy.email) as a send-only relay on port `25` | LoadBalancer with an address on VLAN 60 and one on the IoT VLAN; upstream credentials from 1Password |

## How it fits together

```text
printer (IoT VLAN) ──► 10.30.0.240:25 ─┐                     ┌─ @notifications.vanwetten.id ─► queue ─► Resend (its key)
LAN clients ─────────► 10.60.0.240:25 ─┼─► maddy :2525 ──────┼─ @scan.vwn.casa ──────────────► queue ─► Resend (its key)
in-cluster apps ─────► ClusterIP:25 ───┘   (envelope sender) └─ any other domain ──────────► 550, rejected
```

- **Two LoadBalancer addresses on one Service.** `lbipam.cilium.io/ips` pins both: one from the default pool, one from `pool-iot-smtp-relay`, a single-address pool that selects only this Service ([pool.yaml](../kube-system/cilium/config/pool.yaml)).
- **Two DNS names, declared in two places.** `smtp-relay.${DOMAIN_CLUSTER}` comes from the Service's `external-dns.kubernetes.io/hostname` annotation. The IoT name comes from [dnsendpoint.yaml](./smtp-relay/app/dnsendpoint.yaml), because external-dns publishes every hostname on a Service against every one of its addresses. `external-dns.kubernetes.io/target` pins the annotated name to the VLAN 60 address, and it would pin a second annotated name to that same address.
- **The upstream is Resend, one API key per sender domain.** [maddy.conf](./smtp-relay/app/resources/maddy.conf) matches the envelope sender's domain exactly (subdomains don't match) and gives each domain its own queue and `smtp.resend.com:587` target, authenticating as `resend` with that domain's key. Each key is restricted in Resend to its own domain, so a leaked key can't send as the other. The keys come from one 1Password item per domain, each with an `API_KEY` field:

  | Sender domain                | 1Password item         | Variable                       |
  | ---------------------------- | ---------------------- | ------------------------------ |
  | `notifications.vanwetten.id` | `resend-notifications` | `RESEND_NOTIFICATIONS_API_KEY` |
  | `scan.vwn.casa`              | `resend-scan`          | `RESEND_SCAN_API_KEY`          |

  Adding a domain takes a `source` block, a queue and target pair in `maddy.conf`, and another `dataFrom` entry in [externalsecret.yaml](./smtp-relay/app/externalsecret.yaml).

## Operating

```bash
kubectl -n mail logs deploy/smtp-relay -f                 # accepted mail and the upstream's answers
grep -rln "smtp-relay" kubernetes --include=*.yaml        # who sends through it, and who probes it
```

## Gotchas

- **The relay accepts mail from anyone who can reach it.** There is no authentication and no TLS on the listener. `loadBalancerSourceRanges` is the only guard, and it only covers the two LoadBalancer addresses: Cilium doesn't apply it to the ClusterIP, so every pod in the cluster can send. Widen the list when another device needs the relay; don't treat it as protection against in-cluster senders.
- **`externalTrafficPolicy` must not be `Local`.** The Service leaves it at the default, `Cluster`. Cilium's L2 announcement picks the announcing node without looking at where the pod runs. With `Local`, a leader on a node without the pod drops every connection until the lease moves. The source ranges are checked against the real client address either way.
- **maddy listens on `2525`, the Service maps `25` onto it.** The container runs as non-root with all capabilities dropped, so it never has to bind a privileged port.
- **The queue is on an `emptyDir`.** `state_dir` is `/cache/state`, so mail that is accepted but not yet delivered upstream is lost when the pod is replaced.
- **A sender outside the configured domains gets a `550` at `RCPT TO`.** In-cluster apps send as `MAIL_FROM_ADDRESS` (see the [`cluster-settings` README](../../components/cluster-settings/README.md)). A device sets its own sender: the printer's scan-to-mail has to use an address under `scan.vwn.casa`.
- **Routing reads the envelope sender, Resend checks the `From:` header.** A client whose two senders are in different domains passes the relay and is then rejected by Resend. The rejection shows up in the relay's logs, not on the client.
- **`dependsOn` both external-dns instances** is deliberate: `external-dns-cloudflare`'s exclusion list is what keeps the IoT record out of public DNS (see [flux-kustomization.instructions.md](../../../.agents/instructions/flux-kustomization.instructions.md)).
- **The blackbox probe goes through the in-cluster Service** and sends a `QUIT`: maddy logs an error for every connection dropped without one.
