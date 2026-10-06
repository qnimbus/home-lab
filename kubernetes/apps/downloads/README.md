# downloads

The Usenet pipeline that fills the media library: Prowlarr finds releases, Sonarr and Radarr decide what to grab, Sabnzbd downloads it, and Configarr keeps the quality profiles in line with the TRaSH guides. Plex, which serves the result, lives in [media](../media/).

## Apps

| Kustomization | What it does                                         | Notes                                                                        |
| ------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| prowlarr      | Indexer proxy for Sonarr and Radarr                  | No media mount: it only talks to indexers and to the other apps' APIs        |
| sonarr        | TV series automation                                 | Mounts the media share                                                       |
| radarr        | Movie automation                                     | Mounts the media share                                                       |
| sabnzbd       | Usenet downloader                                    | Mounts the media share; the high memory limit is deliberate (see Gotchas)    |
| configarr     | CronJob that syncs TRaSH profiles and custom formats | No route and no storage; reads Sonarr's and Radarr's API keys from 1Password |

The four web apps are LAN-only on `envoy-internal` (`<app>.${DOMAIN_CLUSTER}`) and appear on Homepage through their route annotations.

## How it fits together

**One filesystem for downloads and library.** Sonarr, Radarr and Sabnzbd all mount the NAS export `/mnt/tank/Media` at `/mnt/media`. Sabnzbd downloads into it, and Sonarr and Radarr import by hardlinking the finished file into the library. A hardlink only works within one filesystem, so the download area and the library must stay on this single mount: splitting them over two mounts turns every import into a copy. It is a raw `type: nfs` mount, not a claim on the `nfs` StorageClass, for the reason [media](../media/README.md) gives.

**Config on the NAS too.** Each web app's `/config` is a claim from [components/nfs-config](../../components/nfs-config/README.md), which is why their Kustomizations depend on `csi-driver-nfs`. That README has the trade-offs: no backups, and deleting the claim deletes the data. All four run as `1000:1000` so every `/config` directory has the same owner.

**API keys come from Git, not from first boot.** Each app's ExternalSecret sets its API key from 1Password (`<APP>__AUTH__APIKEY`, `SABNZBD__API_KEY`), so the keys are known before the apps exist. Configarr depends on that: its [ExternalSecret](./configarr/app/externalsecret.yaml) reads the `sonarr` and `radarr` items directly and has no 1Password item of its own. Its template maps them to the names [config.yml](./configarr/app/resources/config.yml) looks up with `!env`.

**Not in Git.** Everything the apps keep in their own databases is set in their UIs: Sabnzbd's news servers and folders, Sonarr's and Radarr's root folders and download clients, Prowlarr's indexers and its links to Sonarr and Radarr. Losing a `/config` claim means redoing that by hand. Quality profiles and custom formats are the exception: Configarr rewrites them on every run and deletes ones it doesn't manage, so change those in `config.yml`, not in the UI.

## Operating

```sh
just k8s sync-hr downloads sonarr                  # re-run a Helm release
just k8s browse-pvc downloads sonarr-nfs-config    # look inside /config
just k8s sync-es downloads configarr               # after rotating an API key in 1Password
kubectl -n downloads create job --from=cronjob/configarr configarr-manual   # sync profiles now
```

## Gotchas

- **The apps listen on their upstream default ports**, not on 80: Prowlarr 9696, Radarr 7878, Sonarr 8989, Sabnzbd 8080. Probes, Services, routes and Configarr's `base_url` all have to agree; a probe on the wrong port is a `CrashLoopBackOff`.
- **Sabnzbd rejects a `Host` header it doesn't know** with "Hostname verification failed". `SABNZBD__HOST_WHITELIST_ENTRIES` must list both the route's hostname (browsers) and the in-cluster Service name (the download-client calls from Sonarr and Radarr). The image's entrypoint writes it into `sabnzbd.ini` on every start, so editing the whitelist in the UI doesn't last.
- **Sabnzbd's 6Gi memory limit is sized for unpacking**, not for downloading. 2Gi was OOM-killed on 2026-08-24 by one large UHD remux, with Direct Unpack already off.
- **The split startup/liveness/readiness probes on Prowlarr, Radarr and Sonarr widen tolerance; they don't fix anything.** With one shared probe and a 1s timeout, the kubelet kept restarting these pods after `/ping` timeouts (2026-09-20). Why `/ping` stalls is not known. Now startup allows five minutes, liveness needs a minute of consecutive timeouts before a restart, and readiness takes the pod out of the Service without restarting it. Sabnzbd still has the single 1s probe and wasn't affected.
- **`/config/logs` is an `emptyDir` on those three apps**, to keep constant log appends off NFS. It was a trial for the same restarts, not a proven cause: the SQLite databases, `logs.db` included, are still on NFS. The text logs don't survive a pod being recreated; console output still reaches `kubectl logs`.
- **Configarr's root filesystem is read-only.** That works because its clone of the TRaSH guides lands on the `repos` `emptyDir`. Something new that writes elsewhere needs its own mount.
- **TRaSH IDs in `config.yml` get replaced upstream** when a guide is restructured. Check an ID against [TRaSH-Guides/Guides](https://github.com/TRaSH-Guides/Guides) before copying it from another repo.
