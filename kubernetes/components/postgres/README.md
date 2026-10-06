# postgres

A dedicated CloudNative-PG `Cluster` per consuming app, backed up to S3 and dumped nightly to the NAS. Every app database in the cluster comes from this component:

```sh
grep -rl components/postgres kubernetes/apps --include=ks.yaml
```

## What it creates

| Resource          | Name                           | Purpose                                                                           |
| ----------------- | ------------------------------ | --------------------------------------------------------------------------------- |
| `Cluster`         | `${APP}-postgres`              | The database, on node-local `openebs-hostpath` storage                            |
| `ObjectStore`     | `${APP}-postgres-backup`       | Barman Cloud S3 target for base backups and WAL archiving                         |
| `ScheduledBackup` | `${APP}-daily`                 | Base backup on `POSTGRES_BACKUP_SCHEDULE`                                         |
| `ExternalSecret`  | `${APP}-postgres`              | S3 credentials from the `cloudnative-pg` 1Password item                           |
| `HelmRelease`     | `${APP}-postgres-backup-local` | CronJob that `pg_dump`s the database to the NAS ([backup-local](./backup-local/)) |
| `PrometheusRule`  | `${APP}-postgres-backup-local` | `PostgresDumpMissed`: no successful dump in 25 hours                              |
| _(patch)_         | every `HelmRelease`            | Appends `dependsOn: database/cloudnative-pg`, so the app waits for the operator   |

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
| `POSTGRES_DUMP_SCHEDULE`   | no       | `0 2 * * *`    | NAS dump cron: a normal five-field Kubernetes CronJob, in UTC                  |

The default is one instance rather than a fixed three instances with one sync replica for every app: that would give HA everywhere, but triple the pods and storage per app. The replica settings come in pairs:

- **`POSTGRES_SYNC_REPLICAS: 1` with a single instance blocks every write forever**: no replica can ever confirm. Raise `POSTGRES_INSTANCES` first.
- **`POSTGRES_ENABLE_PDB: "true"` with a single instance makes the node undrainable.** CNPG's primary PDB (`minAvailable: 1`) then allows zero evictions, and tuppr's Talos upgrades retry the drain in a loop, bouncing everything else on the node.

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

A **brand-new database** has nothing to recover from, and `recovery` fails with "no target backup found". Label the app's Flux Kustomization `components.postgres/cnpg: init`. A patch in [`clusters/main/apps.yaml`](../../clusters/main/apps.yaml) then swaps `bootstrap` for a plain `initdb` of `POSTGRES_DATABASE` owned by `POSTGRES_USERNAME`.

**Remove the label once the first backup exists.** It's harmless day to day (bootstrap only runs when the cluster is created), but left in place it turns a future rebuild into an empty `initdb` instead of a restore. To get a backup right away, run `just k8s db-backup <namespace> <app>`.

## Renaming an app

Every name, including the S3 path, derives from `${APP}`, so a rename creates a new, empty cluster and the data moves by dump and restore:

1. Dump the old database: `just k8s database dump <ns> <old> "" <db>`.
2. In the new `ks.yaml`, add the `init` label. If the app uses kopiur, pin `KOPIUR_CLAIM` to the old claim name: its snapshots are keyed on it, and a new name restores an empty volume.
3. **Right before pushing**, `kubectl -n <ns> patch ks <old> --type merge -p '{"spec":{"deletionPolicy":"Orphan"}}'`. Otherwise pruning the old Kustomization deletes the old cluster and PVCs. Push nothing else first: a `cluster-apps` reconcile resets it.
4. Once the rename is applied, delete the old HelmRelease **and its HTTPRoute/InterceptorRoute**. The older route wins a hostname conflict and sends traffic to the deleted Service. Delete the old ExternalSecret too if the new one targets the same Secret name: ESO won't take over a Secret another ExternalSecret owns.
5. `just k8s database restore <ns> <new> <file> <db>` (its prompt needs a real terminal), restart the app, take a backup, then drop the label.
6. Delete the orphans by hand, the old `Cluster` last. Keep anything named after a pinned `KOPIUR_CLAIM`. Everything the old Kustomization applied, the components' objects included, still carries its label, so this lists them all:

   ```bash
   kubectl get "$(kubectl api-resources --verbs=list --namespaced -o name | grep -v '^events' | paste -sd, -)" \
     -n <ns> -l kustomize.toolkit.fluxcd.io/name=<old> -o name
   ```

   A hand-written list of kinds misses whatever a component adds, such as `components/dragonfly`'s PodMonitor. Objects an operator created carry no Flux label and go with their owner.

7. To drop the `KOPIUR_CLAIM` pin later, first check what the claim holds. An empty claim, or one with only derived data, can switch straight away, because the new claim starts empty. Real data has to be copied across first. The old claim isn't pruned (it's create-once), so delete it by hand. Its kopia snapshots and policies stay in the repository, because deleting a schedule defaults to `onScheduleDelete: Retain`. Delete them in the Kopia UI (`kopia.${DOMAIN_CLUSTER}`, see [system](../../apps/system/README.md)), or with the CLI from `nas-kopia-ui`'s pod:

   ```bash
   kubectl -n system exec deploy/nas-kopia-ui -- kopia snapshot delete --all-snapshots-for-source <claim>@<ns>:/pvc/<claim> --delete
   kubectl -n system exec deploy/nas-kopia-ui -- kopia policy delete <claim>@<ns>:/pvc/<claim> <claim>@<ns>
   ```

   `<claim>` is the old pinned claim name, which is also the policy name kopia files it under: `<old>-config`, not `<old>`, if that was the claim's name. The space comes back after the next full maintenance run and kopia's safety delay.

## Backups

Base backups on the schedule above, plus continuous WAL archiving, go to one shared Backblaze B2 bucket (`vwn-io-cluster-cnpg`), each app under its own `dedicated/${APP}/` prefix. They're bzip2-compressed, AES256-encrypted and kept for 14 days.

- **Keep the `AWS_*_CHECKSUM_*: when_required` env on the `ObjectStore` sidecar.** Newer botocore sends chunked-trailer checksums without `Content-Length`, which B2 rejects with `MissingContentLength`.
- The superuser needs no 1Password wiring: `enableSuperuserAccess` without a `superuserSecret` makes CNPG generate one per cluster, and the NAS dump logs in with it.

### NAS dumps

A second, independent copy: the `${APP}-postgres-backup-local` CronJob ([postgres-backup-local](https://github.com/prodrigestivill/docker-postgres-backup-local), retention in [its HelmRelease](./backup-local/helmrelease.yaml)) writes a `pg_dump` custom-format file to `/mnt/tank/Cluster/backup/apps/postgres-local/${APP}/` on the NAS, as `kubernetes` 3001:3001. Unlike the Barman backups, a dump survives losing the B2 bucket or its credentials, and restores into a newer PostgreSQL major. `just k8s database restore <namespace> <app> <file>` takes it directly; `kubectl create job -n <namespace> --from=cronjob/<app>-postgres-backup-local <app>-dump-test` runs one by hand.

**Keep the dump image's major tag equal to the `cnpg` image's PostgreSQL major.** `pg_dump` can't dump a newer server. The job creates `/backups/${APP}` itself before calling `/backup.sh`, because the image checks that `BACKUP_DIR` exists before its own `mkdir` runs, so a first run would otherwise always fail. The same wrapper sets `umask 0027`, the only place to control modes (the image has no setting): folders are 0750, dumps 0640.

## Caveats

- **No alerting on the S3 backups.** The NAS dumps are covered: `PostgresDumpMissed` fires after 25 hours without a success, and a failed run trips the stock `KubeJobFailed`. For S3, a rule has to watch the Barman plugin's `barman_cloud_cloudnative_pg_io_last_{available,failed}_backup_timestamp`. `cnpg_collector_last_available_backup_timestamp` and the `Cluster.status` backup fields stay at zero for plugin-based backups ([plugin-barman-cloud#380](https://github.com/cloudnative-pg/plugin-barman-cloud/issues/380)). A `PrometheusRule` in this component, keyed on `${APP}-postgres`, would cover every consumer.
