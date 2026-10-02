# DNS naming

Which zone a new hostname goes under: decided by what answers at the
address, and which network that address is on.

| The name points at                               | Zone                    | Example                      |
| ------------------------------------------------ | ----------------------- | ---------------------------- |
| A device, or one of its interfaces               | `<network>.home.vwn.io` | `nas.storage.home.vwn.io`    |
| An HTTPRoute on `envoy-internal`                 | `${DOMAIN_CLUSTER}`     | `grafana.cluster.vwn.io`     |
| A LoadBalancer address on VLAN 60                | `${DOMAIN_CLUSTER}`     | `smtp-relay.cluster.vwn.io`  |
| A LoadBalancer address on any other network      | `<network>.home.vwn.io` | `smtp-relay.iot.home.vwn.io` |
| An HTTPRoute on `envoy-external` (WAN-reachable) | `${DOMAIN_APP}`         | `konflate.vwn.app`           |

In manifests, `home.vwn.io` is written `home.${DOMAIN_IO}`.

## Networks

| Network (VLAN)   | Subnet        | Zone                      |
| ---------------- | ------------- | ------------------------- |
| SkyNet (10)      | 10.10.0.0/24  | `lan.home.vwn.io`         |
| Guest (20)       | 10.20.0.0/24  | `guest.home.vwn.io`       |
| IOT (30)         | 10.30.0.0/24  | `iot.home.vwn.io`         |
| IOT Offline (40) | 10.40.0.0/24  | `iot-offline.home.vwn.io` |
| Protect (50)     | 10.50.0.0/24  | `protect.home.vwn.io`     |
| Kubernetes (60)  | 10.60.0.0/24  | `k8s.home.vwn.io`         |
| DMZ (70)         | 10.70.0.0/24  | `dmz.home.vwn.io`         |
| Kids (90)        | 10.90.0.0/24  | `kids.home.vwn.io`        |
| Management (100) | 10.100.0.0/24 | `mgmt.home.vwn.io`        |
| Storage (200)    | 10.200.0.0/24 | `storage.home.vwn.io`     |

Each zone is that UniFi network's DNS domain, so DHCP clients land in it
too. The setting lives on the gateway, not in Git; this table is the record
of what it should be.

## Rules

- **VLAN 60 has two zones, split by what answers.** A machine on it is a
  device: `talos-cp-01.k8s.home.vwn.io`. An address the cluster hands out
  from it (a gateway, a LoadBalancer Service) is a service:
  `${DOMAIN_CLUSTER}`. `10.60.0.240` is `smtp-relay.cluster.vwn.io`, never
  `smtp-relay.k8s.home.vwn.io`.
- **One name per address, same `<host>`.** A host or Service on several
  networks gets a name in each network's zone: `nas.lan`, `nas.iot` and
  `nas.storage` under `home.vwn.io`.
- **`<host>` is the role, not the product:** `nas`, not `truenas`.
- **No other private namespace:** not `.internal`, not `home.arpa`, not a
  bare single-label name.
- **Only `${DOMAIN_APP}` is for WAN-reachable names.** external-dns-cloudflare
  excludes the LAN-only zones (`excludeDomains`: `${DOMAIN_CLUSTER}`,
  `${DOMAIN_APPS}`, `home.${DOMAIN_IO}`, `iot.${DOMAIN_IO}`,
  `internal.${DOMAIN_PROXII}`), so a route under one gets no public record.
- **No wildcard certificate covers a device name.** A device UI that needs
  TLS goes behind the gateway as an app, under `${DOMAIN_CLUSTER}`.
- **Mounts, scrape targets and probes stay on IPs** (`${NAS_HOST}`,
  `${NAS_LAN_HOST}`). A mount by name makes storage depend on the gateway's
  DNS. Names are for people and for tooling outside the cluster.

## Declaring a record

- **A route, or a LoadBalancer address on VLAN 60:** the HTTPRoute's
  hostname, or `external-dns.kubernetes.io/hostname` on the Service.
- **A device:** a `DNSEndpoint` in
  `kubernetes/apps/network/external-services/<host>/`, one object for all of
  the host's interfaces (see `nas`).
- **A Service's address on another network:** a `DNSEndpoint` next to the
  app, in its namespace (see `mail/smtp-relay`). The annotation can't do it:
  every hostname on a Service is published against every one of its
  addresses, and `target` pins them all to one.
- **A Kustomization holding such a `DNSEndpoint`** `dependsOn`
  `external-dns-unifi` and `external-dns-cloudflare` (in `network`); see
  `flux-kustomization`.
- **A new LAN-only zone** goes on external-dns-cloudflare's `excludeDomains`
  before anything is named under it. Both instances read every
  `DNSEndpoint`; the exclusion is all that keeps a private address out of
  public DNS.
- **A `DNSEndpoint` meant for Cloudflare only** carries
  `external-dns.home.arpa/public-only: "true"`, which external-dns-unifi
  filters out (see the tunnel alias in `network/cloudflare-tunnel`).
- **Renaming:** add the new name and keep the old one as a second record in
  the same `DNSEndpoint` until nothing uses it.
- **On the gateway only:** the network domains above, and the nodes' names
  (the "local DNS record" on each node's UniFi client entry). Any other
  record there that external-dns doesn't own is stale.

## Not yet on the scheme

Don't copy these; move them when the app is touched anyway.

- `canon`, `gw-adam`, `gw-anna` and `smtp-relay` still answer on their old
  `iot.${DOMAIN_IO}` names as a second record. For `smtp-relay`, drop it
  once the printer is reconfigured.
- `canon` is a product name; the role is `printer`.
- `plex.${DOMAIN_APPS}`: a VLAN 60 LoadBalancer outside `${DOMAIN_CLUSTER}`,
  and the only name `${DOMAIN_APPS}` carries.
- `flux-webhook` and `konflate-webhook` under `${DOMAIN_IO}`: WAN-reachable,
  so they belong under `${DOMAIN_APP}`. Moving them means updating the
  webhook URL on the GitHub side.
- `udm.${DOMAIN_APP}` (homepage links to it): a device under the public app
  domain.
- `wan-failover.${DOMAIN_CLUSTER}`: 192.168.8.1 is neither a cluster address
  nor on a network above.
- `kube-vip.home.arpa` in `kubernetes/talos/cluster.yaml.j2`, and the unused
  `home.arpa` in external-dns-unifi's `domainFilters`.
- `external` and `internal.${DOMAIN_PROXII}`, the gateways' own names, and
  `${DOMAIN_CASA}`, which is wired (certificate, tunnel, DNS filters) and
  unused: neither domain has a pattern.
