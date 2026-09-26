# postgres

A dedicated CloudNative-PG `Cluster` per consuming app, backed up to S3, adapted from [bykaj/home-ops](https://github.com/bykaj/home-ops)'s `components/postgres`. Every app database in the cluster comes from this component:

```sh
grep -rl components/postgres kubernetes/apps --include=ks.yaml
```

## What it creates

| Resource          | Name                     | Purpose                                                                         |
| ----------------- | ------------------------ | ------------------------------------------------------------------------------- |
| `Cluster`         | `${APP}-postgres`        | The database, on node-local `openebs-hostpath` storage                          |
| `ObjectStore`     | `${APP}-postgres-backup` | Barman Cloud S3 target for base backups and WAL archiving                       |
| `ScheduledBackup` | `${APP}-daily`           | Base backup on `POSTGRES_BACKUP_SCHEDULE`                                       |
| `ExternalSecret`  | `${APP}-postgres`        | S3 credentials from the `cloudnative-pg` 1Password item                         |
| _(patch)_         | every `HelmRelease`      | Appends `dependsOn: database/cloudnative-pg`, so the app waits for the operator |

## Usage

In the app's `ks.yaml`:

```yaml
metadata:
  name: &app myapp
  labels:
    components.postgres/cnpg: init # only for a brand-new database, see below
spec:
  components:
    - ../../../../components/postgres
  healthCheckExprs:
    - apiVersion: postgresql.cnpg.io/v1
      kind: Cluster
      current: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'True')
      failed: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'False')
  healthChecks:
    - apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      name: *app
      namespace: <namespace>
  postBuild:
    substitute:
      APP: *app
```

- **The HelmRelease must already have `spec.dependsOn`**, even if empty (`dependsOn: []`). The component's patch appends to that list and fails if it's missing.
- `healthCheckExprs` does nothing on its own: Flux only evaluates it when the Kustomization also has `healthChecks` (or `wait: true`, which would ignore `healthChecks`). Without the HelmRelease check, the Cluster check is silently skipped.

The app reads its connection from the CNPG-generated `${APP}-postgres-app` Secret (keys `host`, `port`, `dbname`, `username`, `password`, `uri`, `jdbc-uri`, `pgpass`) and connects to `${APP}-postgres-rw`. Prefer the individual keys; most charts don't take `uri`. Worked examples: `forgejo/app/helmrelease.yaml` (`additionalConfigFromEnvs`) and `n8n/app/helmrelease.yaml` (`env`). There's no `Pooler`/PgBouncer; add one per cluster if transaction pooling is ever needed.

## Variables

| Variable                   | Required | Default        | Purpose                                                                        |
| -------------------------- | -------- | -------------- | ------------------------------------------------------------------------------ |
| `APP`                      | yes      | —              | Prefix for every resource name and the S3 backup path                          |
| `POSTGRES_DATABASE`        | no       | `${APP}`       | Database created on bootstrap                                                  |
| `POSTGRES_USERNAME`        | no       | `${APP}`       | Owner role created on bootstrap                                                |
| `POSTGRES_INSTANCES`       | no       | `1`            | Pod count; CNPG scales live, no rebuild                                        |
| `POSTGRES_SYNC_REPLICAS`   | no       | `0`            | `min`/`maxSyncReplicas`; `1` only with `POSTGRES_INSTANCES` ≥ 2                |
| `POSTGRES_ENABLE_PDB`      | no       | `false`        | CNPG PodDisruptionBudgets; `"true"` only with `POSTGRES_INSTANCES` ≥ 2         |
| `POSTGRES_STORAGE`         | no       | `5Gi`          | Per-instance PVC size                                                          |
| `POSTGRES_BACKUP_SCHEDULE` | no       | `0 40 4 * * *` | Base-backup cron. **Six fields, seconds first**: `0 40 4 * * *` is 04:40 daily |

bykaj hardcodes three instances with one sync replica for every app. Here the default is one instance, to avoid tripling pods and storage per app. The replica settings come in pairs:

- **`POSTGRES_SYNC_REPLICAS: 1` with a single instance blocks every write forever**: no replica can ever confirm. Raise `POSTGRES_INSTANCES` first.
- **`POSTGRES_ENABLE_PDB: "true"` with a single instance makes the node undrainable.** CNPG's primary PDB (`minAvailable: 1`) then allows zero evictions, and tuppr's Talos upgrades retry the drain in a loop, bouncing everything else on the node. The 2026-09-25 v1.14.1 run looped on talos-cp-01 until the default became `false`.

| `POSTGRES_INSTANCES` | `POSTGRES_ENABLE_PDB` | During a node drain                                            |
| -------------------- | --------------------- | -------------------------------------------------------------- |
| `1` (default)        | `false` (default)     | Database down until its node is back (~10–20 min for Talos)    |
| `1`                  | `"true"`              | **Drain blocked forever**                                      |
| ≥ 2                  | `"true"`              | CNPG switches over to a replica; database stays up             |
| ≥ 2                  | `false`               | Primary evicted without a switchover; brief unplanned failover |

A single instance can't survive a drain either way: `openebs-hostpath` is node-local, so the recreated pod waits for its node to return.

The PostgreSQL image is the same for every consumer and written as a plain `repo:tag@digest`, so Renovate's `cnpg` preset tracks it natively. Don't wrap it in `${VAR:=…}`: the preset would read that prefix as part of the image name.

## Bootstrap

By default the `Cluster` bootstraps with `recovery` from `s3://vwn-io-cluster-cnpg/dedicated/${APP}/` (Barman server name `${APP}`). Deleting the `Cluster` and its PVCs therefore rebuilds the database from the latest base backup plus WAL. The `cnpg.io/skipEmptyWalArchiveCheck` annotation lets the rebuilt cluster archive to the same path, on a new timeline.

A **brand-new database** has nothing to recover from, and `recovery` fails with "no target backup found". Label the app's Flux Kustomization `components.postgres/cnpg: init`. A patch in [`flux/cluster/ks.yaml`](../../flux/cluster/ks.yaml) then swaps `bootstrap` for a plain `initdb` of `POSTGRES_DATABASE` owned by `POSTGRES_USERNAME`.

**Remove the label once the first backup exists.** It's harmless day to day (bootstrap only runs when the cluster is created), but left in place it turns a future rebuild into an empty `initdb` instead of a restore. To get a backup right away, run `just k8s db-backup <namespace> <app>`.

## Backups

Base backups on the schedule above, plus continuous WAL archiving, go to one shared Backblaze B2 bucket (`vwn-io-cluster-cnpg`), each app under its own `dedicated/${APP}/` prefix. They're bzip2-compressed, AES256-encrypted and kept for 14 days. S3 is the only copy: unlike bykaj, there's no local NFS backup sidecar.

- **Keep the `AWS_*_CHECKSUM_*: when_required` env on the `ObjectStore` sidecar.** Newer botocore sends chunked-trailer checksums without `Content-Length`, which B2 rejects with `MissingContentLength`.
- The superuser needs no 1Password wiring: `enableSuperuserAccess` without a `superuserSecret` makes CNPG generate one per cluster.

## Caveats

- **No backup-failure alerting.** A rule has to watch the Barman plugin's `barman_cloud_cloudnative_pg_io_last_{available,failed}_backup_timestamp`. `cnpg_collector_last_available_backup_timestamp` and the `Cluster.status` backup fields stay at zero for plugin-based backups ([plugin-barman-cloud#380](https://github.com/cloudnative-pg/plugin-barman-cloud/issues/380)). A `PrometheusRule` in this component, keyed on `${APP}-postgres`, would cover every consumer.
