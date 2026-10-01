# DNS naming

Which domain a new hostname goes under. Three patterns, by what the name
points at:

| Points at                          | Pattern                        | Example                   |
| ---------------------------------- | ------------------------------ | ------------------------- |
| A device, or one of its interfaces | `<host>.<network>.home.vwn.io` | `nas.storage.home.vwn.io` |
| A cluster app or service, LAN-only | `<app>.${DOMAIN_CLUSTER}`      | `grafana.cluster.vwn.io`  |
| A cluster app, reachable from WAN  | `<app>.${DOMAIN_APP}`          | `konflate.vwn.app`        |

## Devices: `<host>.<network>.home.vwn.io`

The zone says which network the address is on. `<network>` is the UniFi
network's own DNS domain, so DHCP clients land in the same zone as the
static records:

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

- A host on several networks gets one name per interface, same `<host>`:
  `nas.lan.home.vwn.io`, `nas.iot.home.vwn.io`, `nas.storage.home.vwn.io`.
- `<host>` is the role, not the product: `nas`, not `truenas`. The device's
  own hostname may differ; the role name is what manifests and docs use.
- These names exist only on the UniFi gateway. `home.vwn.io` has no public
  records, and nothing under it may get one: external-dns-cloudflare
  excludes it (`excludeDomains`), along with the other LAN-only zones. A new
  LAN-only zone is added to that list.
- No other private namespace: not `.internal`, not `home.arpa`, not a bare
  single-label name.
- The wildcard certificates stop one level down (`*.vwn.io`,
  `*.cluster.vwn.io`), so none covers a device name. A device UI that needs
  TLS goes behind the gateway as an app (`external-services`), under the app
  pattern.

Cluster nodes are devices: `talos-cp-01.k8s.home.vwn.io`. `cluster.vwn.io`
is for what the cluster serves, not for the machines on VLAN 60, so a host
registering a name there can't shadow an app.

### Where a device record lives

- **In Git**, as a `DNSEndpoint` under
  `kubernetes/apps/network/external-services/` (see `nas`), published by
  external-dns-unifi. This is the default for a device with a fixed address.
  One object holds all of a host's interfaces. A record on the gateway that
  external-dns doesn't own is then stale by definition.
- Its Flux Kustomization `dependsOn` `external-dns-unifi`, whose chart
  installs the `DNSEndpoint` CRD, and `external-dns-cloudflare`, whose
  exclusion has to be running first (see `flux-kustomization`).
- **On the gateway**, for what external-dns can't express: each network's
  DNS domain (the table above is the record of what they should be), and
  the nodes' names, which are the "local DNS record" on each node's UniFi
  client entry. A network's domain only names DHCP clients; it doesn't
  rename a client that has its own record.

## Apps and services: `${DOMAIN_CLUSTER}` and `${DOMAIN_APP}`

- LAN-only HTTPRoutes and LoadBalancer Services go under
  `${DOMAIN_CLUSTER}`.
- Anything reachable from the WAN goes under `${DOMAIN_APP}`. Not
  `${DOMAIN_CLUSTER}`: it sits two levels under `vwn.io` and Cloudflare's
  Universal SSL covers one (see `kubernetes/apps/network/README.md`).
- A Service with an address on a device network (the IOT-side
  `smtp-relay` VIP) is named for that network, as a device would be.

## Mounts and probes stay on IPs

`${NAS_HOST}` and `${NAS_LAN_HOST}` are addresses, and stay that way in NFS
and SMB mounts, scrape targets and probes. A mount by name makes storage
depend on the gateway's DNS being up. The names are for people and for
tooling that runs outside the cluster (`ansible/inventory.yaml`, ssh).

## Not yet on the scheme

Existing names that predate it. Don't copy them; move them when the app is
touched anyway.

- `smtp-relay.iot.${DOMAIN_IO}` rather than `iot.home.vwn.io`
  (`kubernetes/apps/mail/smtp-relay`). IoT devices are configured with that
  name by hand, so moving it means reconfiguring them.
- `canon`, `gw-adam` and `gw-anna` are on the scheme, and still answer on
  their old `iot.${DOMAIN_IO}` names as a second record in the same
  `DNSEndpoint`. Drop the old record once nothing uses it.
- `plex.${DOMAIN_APPS}`: a LAN-only Service outside `${DOMAIN_CLUSTER}`,
  and the only name `${DOMAIN_APPS}` carries.
- `flux-webhook` and `konflate-webhook` under `${DOMAIN_IO}`: WAN-facing,
  so they belong under `${DOMAIN_APP}`. Moving them means updating the
  webhook URL on the GitHub side too.
- `udm.${DOMAIN_APP}`, `guest.unifi.${DOMAIN_APP}`: devices under the public
  app domain.
- `wan-failover.${DOMAIN_CLUSTER}` and `mobilerouter.lan.home.vwn.io`: both
  192.168.8.1, on neither network.
- `kube-vip.home.arpa` in `kubernetes/talos/cluster.yaml.j2`.
- `${DOMAIN_CASA}` and `${DOMAIN_PROXII}` have no pattern. `${DOMAIN_PROXII}`
  carries the two gateway targets only; `${DOMAIN_CASA}` is wired
  (certificate, tunnel, DNS filters) and unused.
