# kopiur

`backup` gives an app a persistent volume that is backed up hourly to the NAS with [kopiur](../../apps/system/kopiur/) and refilled from the latest backup when it is created. Every backed-up app volume in the cluster comes from this component:

```sh
grep -rl components/kopiur/backup kubernetes/apps --include=ks.yaml
```

## What it creates

| Resource                | Name                   | Purpose                                                                          |
| ----------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| `PersistentVolumeClaim` | `${KOPIUR_CLAIM}`      | The app's volume. Create-once, populated by the `Restore`                        |
| `Restore`               | `${KOPIUR_CLAIM}`      | Volume populator: fills a new claim from the latest snapshot, or leaves it empty |
| `SnapshotPolicy`        | `${KOPIUR_CLAIM}`      | What to back up, to the `nas` ClusterRepository, and how long to keep it         |
| `SnapshotSchedule`      | `${KOPIUR_CLAIM}`      | When: hourly by default                                                          |
| _(by the operator)_     | `kopiur-cache-<claim>` | The mover's kopia cache, a claim the operator creates from the policy            |

Retention is 24 hourly, 7 daily, 4 weekly, and always the latest 3.

## Usage

In the app's `ks.yaml`:

```yaml
spec:
  components:
    - ../../../../components/kopiur/backup
  postBuild:
    substitute:
      APP: *app
```

and in its HelmRelease:

```yaml
persistence:
  data:
    existingClaim: "${KOPIUR_CLAIM:=${APP}}"
```

No `dependsOn` on kopiur: see the `add-app` skill.

## Variables

| Variable                    | Default               | Purpose                                                                                  |
| --------------------------- | --------------------- | ---------------------------------------------------------------------------------------- |
| `APP`                       | —                     | Required. Names everything unless `KOPIUR_CLAIM` is set                                  |
| `KOPIUR_CLAIM`              | `${APP}`              | Claim name. Snapshots are keyed on it, so a new name restores an empty volume            |
| `KOPIUR_CAPACITY`           | `5Gi`                 | Size of the app's volume                                                                 |
| `KOPIUR_ACCESSMODES`        | `ReadWriteOnce`       | Access mode of the app's volume                                                          |
| `KOPIUR_STORAGECLASS`       | `ceph-block`          | Storage class of the app's volume                                                        |
| `KOPIUR_COPYMETHOD`         | `Snapshot`            | `Direct` for storage without CSI snapshots (`openebs-hostpath`, `nfs`, static PVs)       |
| `KOPIUR_SNAPSHOTCLASS`      | `ceph-block-snapshot` | VolumeSnapshotClass used by `Snapshot`                                                   |
| `KOPIUR_SCHEDULE`           | `H * * * *`           | Cron. `H` hashes the schedule's identity into a stable minute                            |
| `KOPIUR_MOVER_UID` / `_GID` | `1000`                | Must match the pod's `runAsUser`/`runAsGroup`, so files are read and restored as the app |
| `KOPIUR_CACHE_CAPACITY`     | `5Gi`                 | Size of the mover's cache claim. See below                                               |
| `KOPIUR_CACHE_STORAGECLASS` | `openebs-hostpath`    | Storage class of the cache claim: node-local, kept off replicated storage                |

## Sizing

**The cache does not follow the volume.** `KOPIUR_CACHE_CAPACITY` is `5Gi` whatever `KOPIUR_CAPACITY` is. The cache holds what kopia has fetched from the repository (indexes and metadata on a backup, content blocks on a restore), not a copy of the volume, and `openebs-hostpath` doesn't enforce the size as a quota anyway. kopiur's docs give no sizing rule beyond "large repositories"; what bounds kopia's use is `contentCacheSizeMb`/`metadataCacheSizeMb`, which this component leaves at kopia's defaults. Raise the capacity only for a mover that actually runs out.

It used to default to `KOPIUR_CAPACITY`, which tied a volume that can grow (`ceph-block`) to one that can't (`openebs-hostpath` refuses expansion).

**Changing `KOPIUR_CACHE_CAPACITY` does not touch an existing cache claim.** The operator only creates the claim when it is missing and never re-applies over it, so the new size takes effect the next time the claim is created. To apply it now, delete `kopiur-cache-<claim>` between runs: it is only a cache, and the next mover gets a fresh one.

**Raising `KOPIUR_CAPACITY` does not resize a live volume.** The claim is labelled `kustomize.toolkit.fluxcd.io/ssa: IfNotPresent` (its `dataSourceRef` is immutable), so Flux never re-applies it. The new number only takes effect when the claim is next created. To grow the live one as well:

```sh
kubectl patch pvc <claim> -n <namespace> --type merge \
  -p '{"spec":{"resources":{"requests":{"storage":"<size>"}}}}'
```

Keep the claim declared: dropping the component from a Kustomization lets Flux prune the volume.
