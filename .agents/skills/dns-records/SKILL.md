---
name: dns-records
description: Use when adding, renaming or removing a hostname or DNS record — naming a device or one of its interfaces, a LoadBalancer address, a DNSEndpoint, a new LAN zone, or moving a name onto the naming scheme ("give the printer a name", "add a DNS record for X", "what should this host be called", "rename nas")
---

# DNS records: zones and how to declare them

Which zone a name goes under, and the rules a name must follow, are in `.agents/instructions/dns-naming.instructions.md`. This skill holds the network zones, how each kind of record is declared, and the names that predate the scheme.

## Networks

| Network (VLAN)   | Subnet         | Zone                       |
| ---------------- | -------------- | -------------------------- |
| SkyNet (10)      | 10.10.0.0/24   | `lan.home.vwn.io`          |
| Guest (20)       | 10.20.0.0/24   | `guest.home.vwn.io`        |
| IOT (30)         | 10.30.0.0/24   | `iot.home.vwn.io`          |
| IOT Offline (40) | 10.40.0.0/24   | `iot-offline.home.vwn.io`  |
| Protect (50)     | 10.50.0.0/24   | `protect.home.vwn.io`      |
| Kubernetes (60)  | 10.60.0.0/24   | `k8s.home.vwn.io`          |
| DMZ (70)         | 10.70.0.0/24   | `dmz.home.vwn.io`          |
| Kids (90)        | 10.90.0.0/24   | `kids.home.vwn.io`         |
| Management (100) | 10.100.0.0/24  | `mgmt.home.vwn.io`         |
| Storage (200)    | 10.200.0.0/24  | `storage.home.vwn.io`      |
| WAN 2 uplink     | 192.168.8.0/24 | `wan-failover.home.vwn.io` |

Each zone is that UniFi network's DNS domain, so DHCP clients land in it too. The setting lives on the gateway, not in Git; this table is the record of what it should be.

`wan-failover` is the exception: the mobile router's own subnet, where the gateway is a DHCP client on its second WAN port. It is not a UniFi network and must not become one (the subnet would then sit on two interfaces). It holds one name, `router.wan-failover.home.vwn.io`.

## Declaring a record

- **A route, or a LoadBalancer address on VLAN 60:** the HTTPRoute's hostname, or `external-dns.kubernetes.io/hostname` on the Service.
- **A device:** a `DNSEndpoint` in `kubernetes/apps/network/external-services/<host>/`, one object for all of the host's interfaces (see `nas`).
- **A Service's address on another network:** a `DNSEndpoint` next to the app, in its namespace (see `mail/smtp-relay`). The annotation can't do it: every hostname on a Service is published against every one of its addresses, and `target` pins them all to one.
- **An app behind Traefik on the NAS:** no `DNSEndpoint`. `dexd.enabled: "true"` on the container makes dexd (`docker/nas/01-dexd`) read the Traefik router's `Host()` rule and write `<app>.${DOMAIN_APP}` to the gateway as a CNAME to `docker.${DOMAIN_APP}`. The record goes straight to the gateway, not through external-dns, and is removed when the container is. See the `add-docker-app` skill.
- **A Kustomization holding such a `DNSEndpoint`** `dependsOn` `external-dns-unifi` and `external-dns-cloudflare` (in `network`); see `flux-kustomization`.
- **A new LAN-only zone** goes on external-dns-cloudflare's `excludeDomains` before anything is named under it. Both instances read every `DNSEndpoint`; the exclusion is all that keeps a private address out of public DNS.
- **A `DNSEndpoint` meant for Cloudflare only** carries `external-dns.home.arpa/public-only: "true"`, which external-dns-unifi filters out (see the tunnel alias in `network/cloudflare-tunnel`).
- **Renaming:** add the new name and keep the old one as a second record in the same `DNSEndpoint` until nothing uses it.
- **On the gateway only:** the network domains above, and the nodes' names (the "local DNS record" on each node's UniFi client entry). Any other record there that neither external-dns nor dexd owns is stale. Each marks its records with a TXT record: external-dns under the `k8s.` prefix, dexd under `dkr.`. A single-label name can't go through external-dns at all: its ownership record (`k8s.cname-<name>`) falls outside every domain filter.
- **One source per name.** The gateway refuses a record whose name a client entry's local DNS record already holds (`Overlaps with Device Local DNS`), and that one failure stops every other change external-dns-unifi has queued, each cycle, until it is fixed. Before declaring a device, ask the user to clear any local DNS record of that name on its UniFi client entry (it isn't visible from Git or the cluster).

## Not yet on the scheme

Don't copy these. When a task touches one of these apps, propose the move to the user; don't make it unasked, since most need a change outside Git.

- `portal.guest.home.vwn.io` points at 192.168.1.1, the gateway's address on the Default network, not on the guest network its zone names.
- `printer` (as `canon`) and `smtp-relay` still answer on their old `iot.${DOMAIN_IO}` names as a second record. For `smtp-relay`, drop it once the printer is reconfigured.
- `kube-vip.home.arpa` in `kubernetes/talos/cluster.yaml.j2`.
- `external` and `internal.${DOMAIN_PROXII}`, the gateways' own names, and `${DOMAIN_CASA}` and `${DOMAIN_APPS}`, which are wired (certificate, tunnel, DNS filters) and unused: no rule covers these domains, so put no new name under them.
