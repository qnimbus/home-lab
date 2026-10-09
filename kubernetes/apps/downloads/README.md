# downloads

The Usenet pipeline that fills the media library: Prowlarr finds releases, Sonarr and Radarr decide what to grab, Sabnzbd downloads it, and Configarr keeps the quality profiles in line with the TRaSH guides. Seerr is the front door: people ask for a film or series there and it hands the request to Radarr or Sonarr. Plex, which serves the result, lives in [media](../media/).

## Apps

| Kustomization | What it does                                         | Notes                                                                        |
| ------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| prowlarr      | Indexer proxy for Sonarr and Radarr                  | No media mount: it only talks to indexers and to the other apps' APIs        |
| sonarr        | TV series automation                                 | Mounts the media share                                                       |
| radarr        | Movie automation                                     | Mounts the media share                                                       |
| sabnzbd       | Usenet downloader                                    | Mounts the media share; the high memory limit is deliberate (see Gotchas)    |
| seerr         | Request portal for films and series                  | No media mount: it only talks to Plex's, Sonarr's and Radarr's APIs          |
| configarr     | CronJob that syncs TRaSH profiles and custom formats | No route and no storage; reads Sonarr's and Radarr's API keys from 1Password |

The five web apps are LAN-only on `envoy-internal` (`<app>.${DOMAIN_CLUSTER}`) and appear on Homepage through their route annotations.

## How it fits together

**One filesystem for downloads and library.** Sonarr, Radarr and Sabnzbd all mount the NAS export `/mnt/tank/Media` at `/mnt/media`. Sabnzbd downloads into it, and Sonarr and Radarr import by hardlinking the finished file into the library. A hardlink only works within one filesystem, so the download area and the library must stay on this single mount: splitting them over two mounts turns every import into a copy. It is a raw `type: nfs` mount, not a claim on the `nfs` StorageClass, for the reason [media](../media/README.md) gives.

**Config on Ceph, backed up.** Each web app's `/config` is a `ceph-block` claim from [components/kopiur/backup](../../components/kopiur/README.md), snapshotted hourly to the NAS and refilled from the latest snapshot when the claim is created. It must not go back on NFS: see Gotchas.

**The apps' own backups go to the NAS.** `/mnt/backups` is `apps/<app>` under the NAS export `/mnt/tank/Cluster/backup`, the same export Plex uses. The mount does nothing by itself: set Settings → General → Backups → Folder to `/mnt/backups` in Sonarr, Radarr and Prowlarr, and the backup folder under Folders in Sabnzbd. The setting lives in each app's database, so it comes back with a restored `/config`.

**API keys come from Git, not from first boot.** Each app's ExternalSecret sets its API key from 1Password (`<APP>__AUTH__APIKEY`, `SABNZBD__API_KEY`), so the keys are known before the apps exist. Configarr depends on that: its [ExternalSecret](./configarr/app/externalsecret.yaml) reads the `sonarr` and `radarr` items directly and has no 1Password item of its own. Its template maps them to the names [config.yml](./configarr/app/resources/config.yml) looks up with `!env`.

**Not in Git.** Everything the apps keep in their own databases is set in their UIs: Sabnzbd's news servers and folders, Sonarr's and Radarr's root folders and download clients, Prowlarr's indexers and its links to Sonarr and Radarr, Seerr's links to Plex, Sonarr and Radarr and its users. It is only as safe as the `/config` backups. Quality profiles and custom formats are the exception: Configarr rewrites them on every run and deletes ones it doesn't manage, so change those in `config.yml`, not in the UI.

## Operating

```sh
just k8s sync-hr downloads sonarr                  # re-run a Helm release
just k8s browse-pvc downloads sonarr               # look inside /config
just k8s kopiur snapshots downloads                # the config volumes' backups
just k8s sync-es downloads configarr               # after rotating an API key in 1Password
kubectl -n downloads create job --from=cronjob/configarr configarr-manual   # sync profiles now
```

## Gotchas

- **The apps listen on their upstream default ports**, not on 80: Prowlarr 9696, Radarr 7878, Sonarr 8989, Sabnzbd 8080. Probes, Services, routes and Configarr's `base_url` all have to agree; a probe on the wrong port is a `CrashLoopBackOff`.
- **Prowlarr, Radarr and Sonarr have no login of their own** (`<APP>__AUTH__METHOD: External`): anyone who can reach `envoy-internal` is in. "Disabled for Local Addresses" is no alternative: every request arrives from Envoy's pod address, so it lets everyone in as well, and with an empty Allowed Hosts field the apps reject every save of Settings → General. Put real authentication in front before exposing one of them beyond the LAN.
- **Seerr does have a login**: Plex accounts, set up in its first-run wizard. Until that wizard is finished, whoever opens the route first becomes the admin.
- **Sabnzbd rejects a `Host` header it doesn't know** with "Hostname verification failed". `SABNZBD__HOST_WHITELIST_ENTRIES` must list both the route's hostname (browsers) and the in-cluster Service name (the download-client calls from Sonarr and Radarr). The image's entrypoint writes it into `sabnzbd.ini` on every start, so editing the whitelist in the UI doesn't last.
- **Sabnzbd's 6Gi memory limit is sized for unpacking**, not for downloading. Unpacking one large UHD remux needs more than 2Gi, even with Direct Unpack off.
- **No SQLite database on NFS.** With `/config` on the `nfs` StorageClass, Prowlarr, Radarr and Sonarr freeze for 30 seconds or more at a time: `/ping` needs the database, and a thread releasing a SQLite file lock blocks in the NFS client (`nfs_iocounter_wait`) while the mount itself answers in milliseconds. The size of the database and its write volume make no difference.
- **Liveness and readiness are one tight probe: a 1s timeout, three failures.** Restarts with `/ping` timeouts in the events mean the app is freezing; look at the storage before loosening the probe. The startup probe allows five minutes, so a database migration after an app upgrade isn't killed mid-way.
- **Seerr's probes differ**: they call `/api/v1/status` with a 5s timeout, and its state is under `/app/config`, not `/config`. Its `/app/config/logs` is an `emptyDir` too, and so is `/app/.next/cache`, which Next.js writes to under the read-only root filesystem.
- **`/config/logs` is an `emptyDir` on Prowlarr, Radarr and Sonarr**, and their log database is off (`<APP>__LOG__DBENABLED`), so logging never touches the backed-up volume. The text logs don't survive a pod being recreated, and the Logs page in each UI is empty; console output still reaches `kubectl logs`.
- **Configarr's root filesystem is read-only.** That works because its clone of the TRaSH guides lands on the `repos` `emptyDir`. Something new that writes elsewhere needs its own mount.
- **TRaSH IDs in `config.yml` get replaced upstream** when a guide is restructured. Check an ID against [TRaSH-Guides/Guides](https://github.com/TRaSH-Guides/Guides) before copying it from another repo.
