# DNS naming

Which zone a new hostname goes under: decided by what answers at the
address, and which network that address is on.

| The name points at                                 | Zone                    | Example                      |
| -------------------------------------------------- | ----------------------- | ---------------------------- |
| A device, or one of its interfaces                 | `<network>.home.vwn.io` | `nas.storage.home.vwn.io`    |
| An HTTPRoute on `envoy-internal`                   | `${DOMAIN_CLUSTER}`     | `grafana.cluster.vwn.io`     |
| A LoadBalancer address on VLAN 60                  | `${DOMAIN_CLUSTER}`     | `smtp-relay.cluster.vwn.io`  |
| A LoadBalancer address on any other network        | `<network>.home.vwn.io` | `smtp-relay.iot.home.vwn.io` |
| An HTTPRoute on `envoy-external` (WAN-reachable)   | `${DOMAIN_APP}`         | `konflate.vwn.app`           |
| The same, for a public view of the cluster itself  | `${DOMAIN_DEV}`         | `stats.clustrs.dev`          |
| Traefik on the NAS, or an app behind it (LAN-only) | `${DOMAIN_APP}`         | `docker.vwn.app`             |

In manifests, `home.vwn.io` is written `home.${DOMAIN_IO}`. `<network>` is
one of `lan`, `guest`, `iot`, `iot-offline`, `protect`, `k8s`, `dmz`,
`kids`, `mgmt`, `storage`.

**Before adding, renaming or removing a record, use the `dns-records`
skill.** It has each network's subnet, how each kind of record is declared,
and the existing names that predate this scheme. Some names in the repo
break the rules below; don't copy one without checking it against them.

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
- **Only `${DOMAIN_APP}` and `${DOMAIN_DEV}` are for WAN-reachable names.**
  `${DOMAIN_DEV}` is for what the cluster publishes about itself, readable
  by anyone: `stats.clustrs.dev` (kromgo's badges), next to
  `schemas.clustrs.dev`, which is a Cloudflare Pages project and not a
  route. Every other public app goes under `${DOMAIN_APP}`.
  external-dns-cloudflare
  excludes the LAN-only zones (`excludeDomains`: `${DOMAIN_CLUSTER}`,
  `${DOMAIN_APPS}`, `home.${DOMAIN_IO}`, `internal.${DOMAIN_PROXII}`,
  `docker.${DOMAIN_APP}`), so a route under one gets no public record.
- **`${DOMAIN_APP}` also holds the names Traefik serves on the NAS, and those
  are LAN-only.** They are there because Traefik's wildcard certificate is
  `*.vwn.app`. `docker.${DOMAIN_APP}` is Traefik's own address: a
  `DNSEndpoint`, kept out of public DNS by the exclusion above. An app
  behind it is `<app>.${DOMAIN_APP}`, one label deep; dexd writes that record
  to the gateway from the container's labels, so it never passes through
  external-dns and needs no exclusion (see the `add-docker-app` skill). A
  name belongs to an HTTPRoute or to a NAS app, never both.
- **A new LAN-only zone goes on that `excludeDomains` list before anything
  is named under it.** Both external-dns instances read every
  `DNSEndpoint`; the exclusion is all that keeps a private address out of
  public DNS.
- **No wildcard certificate covers a device name.** A device UI that needs
  TLS goes behind the gateway as an app, under `${DOMAIN_CLUSTER}`. The UDM
  is the exception: `gateway.lan.home.vwn.io` and `portal.guest.home.vwn.io`
  carry certificates the UDM issues itself (see
  `kubernetes/apps/network/README.md`), because its UI has to work when the
  cluster is down.
- **Mounts, scrape targets and probes stay on IPs** (`${NAS_HOST}`,
  `${NAS_LAN_HOST}`). A mount by name makes storage depend on the gateway's
  DNS. Names are for people and for tooling outside the cluster.
