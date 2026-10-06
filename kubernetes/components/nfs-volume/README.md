# nfs-volume

A Kustomize component that gives an app a dedicated volume on the NAS through the `nfs` StorageClass (csi-driver-nfs), not on Ceph.

## Use case

Use it for an app's own data when that data is:

- **small**, a few GiB at most;
- **read-mostly**: settings and state that change now and then, not constantly, and no SQLite database the app keeps open (see [Not a good fit](#not-a-good-fit));
- **rebuildable**: losing it means reconfiguring the app, not losing data you can't get back.

For data like this, Ceph's replication, snapshots and backups cost more than they're worth. Each `ceph-block` volume also adds Ceph client traffic on the nodes, which is a trigger for `CephNodeNetworkPacketDrops` on the nodes with `e1000e` NICs.

This volume holds only the app's own state. Large shared data, such as a media library or download staging area, belongs on a raw `type: nfs` mount in the HelmRelease.

Find what uses it with `grep -rl components/nfs-volume kubernetes/apps --include=ks.yaml`.

### Not a good fit

- **Write-heavy workloads**: databases with steady write traffic (use CNPG via `components/postgres`), caches and queues (use `components/dragonfly`), and apps that constantly append to logs or rewrite files. Every write is a network round trip to the NAS.
- **An app with a live SQLite database, however small.** SQLite locks and unlocks its files on every transaction, and on NFS an unlock can block in the kernel (`nfs_iocounter_wait`) for 30 seconds or more while the mount itself answers in milliseconds, with no NFS timeouts and an idle NAS. The app hangs with it, which surfaces as probe timeouts and restarts. The size of the database and its write volume make no difference.
- **Data you can't lose**: this volume has no backups, and deleting the PVC deletes its data (see [Caveats](#caveats)).
- **Performance-sensitive storage**: use `ceph-block`.

## What it creates

| Resource                | Name         | Details                                                                 |
| ----------------------- | ------------ | ----------------------------------------------------------------------- |
| `PersistentVolumeClaim` | `${APP}-nfs` | `ReadWriteOnce`, `storageClassName: nfs`, size `${NFS_VOLUME_CAPACITY}` |

## Usage

In the app's `ks.yaml`:

```yaml
spec:
  components:
    - ../../../../components/nfs-volume
  dependsOn:
    - name: csi-driver-nfs # provides the nfs StorageClass
      namespace: system
  postBuild:
    substitute:
      APP: *app
```

In the app's `helmrelease.yaml` (app-template):

```yaml
defaultPodOptions:
  securityContext:
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
    runAsGroup: 1000
    runAsUser: 1000
persistence:
  config:
    existingClaim: "${APP}-nfs"
    globalMounts:
      - path: /config
```

The claim is `ReadWriteOnce`, which app-template's default `Recreate` strategy fits: don't switch the controller to `RollingUpdate`.

| Variable              | Required | Default | Purpose                                 |
| --------------------- | -------- | ------- | --------------------------------------- |
| `APP`                 | yes      | —       | PVC name prefix (`${APP}-nfs`)          |
| `NFS_VOLUME_CAPACITY` | no       | `5Gi`   | Requested size (NFS doesn't enforce it) |

Run every consumer as `1000:1000`, so every directory on the NAS has the same owner.

## Caveats

- **No backups.** Nothing snapshots or backs up these PVCs. Only use this component for data you can rebuild.
- **Deleting the PVC deletes the data.** The `nfs` StorageClass uses `reclaimPolicy: Delete`, so removing the PVC (for example by dropping the component or pruning the app) also deletes its subdirectory under `/mnt/tank/Cluster/k8s-nfs-csi` on the NAS.
- **Keep the write-heavy parts off the PVC.** Even in an app that fits, move frequently written paths onto node-local storage. For example, mount a log directory as an `emptyDir` so constant log appends never reach NFS. If an app's main working set is write-heavy, don't use this component.
