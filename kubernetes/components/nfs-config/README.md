# nfs-config

A Kustomize component that gives an app a dedicated `/config` PVC on the NAS through the `nfs` StorageClass (csi-driver-nfs), not on Ceph.

## Use case

Use it for an app's own **`/config` directory** when that data is:

- **small**, a few GiB at most;
- **read-mostly**: settings, a small SQLite database and state that changes now and then, not constantly;
- **rebuildable**: losing it means reconfiguring the app, not losing data you can't get back.

For data like this, Ceph's replication, snapshots and backups cost more than they're worth. Each `ceph-block` volume also adds Ceph client traffic on the nodes. Moving this kind of `/config` onto the NAS removed a confirmed trigger for `CephNodeNetworkPacketDrops` on the nodes with `e1000e` NICs.

This PVC holds only the app's own state. Large shared data, such as a media library or download staging area, belongs on a raw `type: nfs` mount in the HelmRelease.

Any app whose `/config` fits this profile can use the component. The current consumers are the `downloads` apps `prowlarr`, `radarr`, `sabnzbd` and `sonarr`. They're a typical fit: a handful of settings and a small SQLite database, all of it rebuildable.

### Not a good fit

- **Write-heavy workloads**: databases with steady write traffic (use CNPG via `components/postgres`), caches and queues (use `components/dragonfly`), and apps that constantly append to logs or rewrite files. Every write is a network round trip to the NAS. SQLite locking over NFS is fragile and slow under load, and the latency surfaces as probe timeouts and restarts.
- **Data you can't lose**: this volume has no backups, and deleting the PVC deletes its data (see [Caveats](#caveats)).
- **Performance-sensitive storage**: use `ceph-block`.

## What it creates

| Resource                | Name                | Details                                                                 |
| ----------------------- | ------------------- | ----------------------------------------------------------------------- |
| `PersistentVolumeClaim` | `${APP}-nfs-config` | `ReadWriteOnce`, `storageClassName: nfs`, size `${NFS_CONFIG_CAPACITY}` |

## Usage

In the app's `ks.yaml`:

```yaml
spec:
  components:
    - ../../../../components/nfs-config
  postBuild:
    substitute:
      APP: *app
      NFS_CONFIG_CAPACITY: 5Gi # optional, defaults to 5Gi
  dependsOn:
    - name: csi-driver-nfs # provides the nfs StorageClass
      namespace: system
```

In the app's `helmrelease.yaml` (app-template):

```yaml
defaultPodOptions:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
controllers:
  <app>:
    strategy: Recreate # the PVC is RWO
persistence:
  config:
    existingClaim: "${APP}-nfs-config"
    globalMounts:
      - path: /config
```

| Variable              | Required | Default | Purpose                                 |
| --------------------- | -------- | ------- | --------------------------------------- |
| `APP`                 | yes      | —       | PVC name prefix (`${APP}-nfs-config`)   |
| `NFS_CONFIG_CAPACITY` | no       | `5Gi`   | Requested size (NFS doesn't enforce it) |

All current consumers run as `1000:1000`, including Prowlarr, which has no media mount. That way every `/config` directory on the NAS has the same owner.

## Caveats

- **No backups.** Nothing snapshots or backs up these PVCs. Only use this component for data you can rebuild.
- **Deleting the PVC deletes the data.** The `nfs` StorageClass uses `reclaimPolicy: Delete`, so removing the PVC (for example by dropping the component or pruning the app) also deletes its subdirectory under `/mnt/tank/Cluster/k8s-nfs-csi` on the NAS.
- **Keep the write-heavy parts off the PVC.** Even in an app that fits, move frequently written paths onto node-local storage. For example, Prowlarr, Radarr and Sonarr mount `/config/logs` as an `emptyDir` so their constant log appends never reach NFS. If an app's main working set is write-heavy, don't use this component.
