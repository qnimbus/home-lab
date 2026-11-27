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

**The cache claim's size doesn't follow the app's volume.** `KOPIUR_CACHE_CAPACITY` is `5Gi` for every app, whatever its `KOPIUR_CAPACITY` is:

- **What the cache holds.** Pieces of the repository on the NAS that kopia fetched during a run: mostly indexes and metadata on a backup, data blocks on a restore. It is not a copy of the app's volume, so a large volume doesn't need a large cache.
- **The claim's size is not a limit.** `openebs-hostpath` is a plain directory on the node, so nothing stops kopia writing more than the claim's `5Gi`.
- **The cache budgets are the limit.** kopia prunes its cache to a content budget and a metadata budget. This component sets neither (`contentCacheSize`/`metadataCacheSize`, or the older `contentCacheSizeMb`/`metadataCacheSizeMb`). With no budget set, kopiur derives both from the cache claim's capacity: 60% for content and 15% for metadata, about 3 GiB and 768 MiB of a `5Gi` claim.
- **When to raise `KOPIUR_CACHE_CAPACITY`.** Only for an app whose backups or restores fail for lack of cache space. A larger claim gives kopia larger budgets.
- **Why it doesn't default to `KOPIUR_CAPACITY`.** The app's volume (`ceph-block`) can be expanded later, and the cache claim (`openebs-hostpath`) can't. Tying the two together would leave the cache behind whenever the volume grows.

**Raising `KOPIUR_CACHE_CAPACITY` doesn't grow an existing cache claim.** kopiur grows a cache claim whose StorageClass allows expansion and never shrinks one. `openebs-hostpath` doesn't allow it, so a raise only gets a `CachePvcExpansionNotAllowed` Warning event on the `SnapshotPolicy`, and a lower value a `CachePvcShrinkRefused` one. The budgets are sized to the smaller of the spec and the claim, so neither breaks a backup. To apply the new size, delete `kopiur-cache-<claim>` between runs: it is only a cache, and the next mover gets a fresh one.

**Raising `KOPIUR_CAPACITY` does not resize a live volume.** The claim is labelled `kustomize.toolkit.fluxcd.io/ssa: IfNotPresent` (its `dataSourceRef` is immutable), so Flux never re-applies it. The new number only takes effect when the claim is next created. To grow the live one as well:

```sh
kubectl patch pvc <claim> -n <namespace> --type merge \
  -p '{"spec":{"resources":{"requests":{"storage":"<size>"}}}}'
```

Keep the claim declared: dropping the component from a Kustomization lets Flux prune the volume.

## Files rewritten in place

kopia skips reading a file whose size and modification time match the previous snapshot, and reuses the old content. A program that overwrites a file in place without moving its mtime is therefore backed up stale, and the backup still reports success. A CSI snapshot (`copyMethod: Snapshot`) doesn't help: the comparison is against the previous kopia snapshot. kopiur confirmed this for MariaDB/InnoDB, whose redo log and Aria logs are rewritten in place while their mtime stays old.

No app on this component needs a fix. Their databases are SQLite, which writes through `write()` and so updates the mtime. The apps with a real database server (`n8n`, `firefly`, `paperless`) use `components/postgres`, which CNPG backs up with Barman, not kopia.

An app that keeps such files on its volume (MariaDB/MySQL, or anything that preallocates a file and writes to it through `mmap`) needs `SnapshotPolicy.spec.upload.forceHashPercent: 100`. kopia then re-reads and re-hashes every file on every run. Lower values pick files at random and only bound how long one can stay stale. The cost is a full read of the volume per backup; unchanged data is still not uploaded again. Set it in that app's `ks.yaml`, not for every app:

```yaml
spec:
  patches:
    - patch: |
        - op: add
          path: /spec/upload/forceHashPercent
          value: 100
      target:
        kind: SnapshotPolicy
```

`--force-hash` can't go in `kopiaArgs`: kopiur's webhook refuses any flag it already sets from a field.
