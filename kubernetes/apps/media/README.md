# media

Plex, with hardware transcoding on the nodes' Intel GPUs, its library on the NAS and its own state on Ceph. The namespace carries the `resource.kubernetes.io/admin-access` label, which the GPU claim's `adminAccess: true` needs to be admitted.

## Apps

| Kustomization | What it does                                              | Notes                                                                                    |
| ------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| plex          | Plex Media Server                                         | GPU via [components/gpu](../../components/gpu/), `/config` backed up by kopiur           |
| plex-tools    | `plex-image-cleanup`, a CronJob that prunes unused images | Runs in `MODE: remove` on Plex's config volume, so it is pinned to the node Plex runs on |

## How it fits together

**Six ways in.** Plex advertises all of them (`PLEX_ADVERTISE_URL`) and clients pick one they can reach:

| Path                           | For             | Notes                                                                          |
| ------------------------------ | --------------- | ------------------------------------------------------------------------------ |
| `plex.${DOMAIN_APP}`           | WAN             | Cloudflare Tunnel → `envoy-external`. Always needs a Plex token (see Gotchas)  |
| `plex.${DOMAIN_CLUSTER}`       | LAN browsers    | `envoy-internal`                                                               |
| `${LB_IP_PLEX}:32400`          | LAN clients     | LoadBalancer on VLAN 60, plain HTTP                                            |
| `${LB_IP_PLEX_IOT}:32400`      | IOT clients     | A second address on the IOT VLAN: the gateway blocks IOT from reaching VLAN 60 |
| `plex.${DOMAIN_TAILSCALE}`     | Tailnet devices | Tailscale Ingress, its own device tagged `tag:plex`, certificate by Tailscale  |
| `plex.media.svc.cluster.local` | Other pods      | Plain HTTP, bypasses Envoy                                                     |

The LoadBalancer addresses have no DNS name: clients learn them from plex.tv. Plex serves HTTP and HTTPS on the same port, but its certificate only covers `*.<hash>.plex.direct`, so the bare IPs are advertised over plain HTTP.

**Storage.**

| Mount          | Where                                         | Why there                                                                             |
| -------------- | --------------------------------------------- | ------------------------------------------------------------------------------------- |
| `/config`      | `ceph-block` claim from kopiur                | Backed up hourly. `strategy: Recreate` because the claim is `ReadWriteOnce`           |
| `/mnt/media`   | NFS, `/mnt/tank/Media`                        | A raw mount: the `nfs` StorageClass makes and deletes a folder per claim              |
| `/mnt/backups` | NFS, `/mnt/tank/Cluster/backup` → `apps/plex` | Plex's own database backups (`ButlerDatabaseBackupPath`), outside the cluster         |
| `scratch`      | 20Gi `emptyDir`                               | Transcodes, logs and `/tmp`. On disk, not in memory: the small nodes have 32GB of RAM |

Both NFS exports squash every client to a NAS user, so Plex's UID 1000 doesn't have to exist there.

**NAS down, Plex off.** A KEDA [ScaledObject](./plex/app/scaledobject.yaml) scales Plex to zero while the blackbox `nas-nfs` probe fails, and back when it recovers. The 30s cooldown is one probe interval, so a single failed scrape doesn't stop Plex. The HelmRelease ignores drift on `/spec/replicas`, otherwise Flux would scale it back up within the hour.

## Operating

```sh
just k8s sync-hr media plex              # re-run the Helm release
just k8s browse-pvc media plex           # look inside /config
just k8s kopiur snapshots media          # the config volume's backups
```

After changing a route, check that the public one still refuses a spoofed LAN address. It must print `401`:

```sh
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-For: 10.10.0.50' \
  https://plex.vwn.app/library/sections
```

**Rebuilding without a restored `/config`.** Plex then has no server token and needs claiming again. Get a token at <https://plex.tv/claim>, put it in the `CLAIM_TOKEN` field of the `plex` 1Password item, and start Plex within four minutes, which is how long a claim token lasts. With a restored volume the field is never read.

## Gotchas

- **The public route pins `X-Forwarded-For`.** Plex skips authentication for `PLEX_NO_AUTH_NETWORKS` and matches that list against the _first_ `X-Forwarded-For` entry, which a WAN client writes itself (Cloudflare appends to it). [httproute.yaml](./plex/app/httproute.yaml) overwrites the header with a TEST-NET address on `plex-public`, so nothing on that route gets in without a token. Removing the header instead would be worse: Plex would see Envoy's pod IP, which is on the list. The cost: Plex treats everyone on that route as remote, including you at home.
- **Both routes set `X-Plex-Http-Pipeline: infinite`**, or Plex closes idle keep-alive connections after 20 seconds, and strip `Range` on `/library/streams`, or [external subtitles fail behind a proxy](https://forums.plex.tv/t/external-srt-subtitles-are-not-working-w-reverse-proxy/886540).
- **`secureConnections=1` is load-bearing.** The values are `0` Required, `1` Preferred, `2` Disabled. Preferred accepts both; with Required, the probes, the plain-HTTP advertise URLs and the cleanup job's `PLEX_URL` would all be rejected.
- **Preferences in Git are written on every start**, but removing one from Git doesn't unset it: the value stays in `Preferences.xml` on the config volume.
- **Not `externalTrafficPolicy: Local`.** Both LoadBalancer addresses are announced over L2, not BGP, and Cilium picks the announcing node without regard to where the pod runs ([cilium#27800](https://github.com/cilium/cilium/issues/27800)). With `Local`, a node without the Plex pod refuses the connection. `Cluster` costs the real client IP on that path.
- **The Tailscale Ingress needs "HTTPS Certificates" enabled** for the tailnet in the Tailscale admin console; check there if it never gets an address. Changing `tailscale.com/tags` doesn't retag a live proxy: delete its StatefulSet so the operator recreates it.
- **Cloudflare's terms restrict video over its CDN** outside its paid video products. The public route streams through the proxied tunnel anyway.
