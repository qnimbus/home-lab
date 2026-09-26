# postgres

CloudNative-PG backed PostgreSQL component, adapted from
[bykaj/home-ops](https://github.com/bykaj/home-ops)'s `components/postgres`:
a dedicated CNPG `Cluster` per consuming app, backed up to S3. Every app
database in this cluster comes from this component. List the current
consumers with:

```sh
grep -rl components/postgres kubernetes/apps --include=ks.yaml
```

## What it creates

| Resource          | Name                     | Purpose                                                                      |
| ----------------- | ------------------------ | ---------------------------------------------------------------------------- |
| `Cluster`         | `${APP}-postgres`        | The database itself, on node-local `openebs-hostpath` storage                |
| `ObjectStore`     | `${APP}-postgres-backup` | Barman Cloud S3 target for base backups and WAL archiving                    |
| `ScheduledBackup` | `${APP}-daily`           | Daily base backup                                                            |
| `ExternalSecret`  | `${APP}-postgres`        | S3 credentials from 1Password                                                |
| _(patch)_         | every `HelmRelease`      | Adds `dependsOn: database/cloudnative-pg`, so the app waits for the operator |

## Substitution variables

| Variable                   | Default        | Notes                                                                                                                                        |
| -------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP`                      | _(required)_   | Name of the consuming app — used for cluster, secret, and backup paths.                                                                      |
| `POSTGRES_USERNAME`        | `${APP}`       | Username created on initial bootstrap.                                                                                                       |
| `POSTGRES_DATABASE`        | `${APP}`       | Database name created on initial bootstrap.                                                                                                  |
| `POSTGRES_INSTANCES`       | `1`            | No replicas by default. Bump to 3 for automatic failover once an app needs it — CNPG scales live, no rebuild required.                       |
| `POSTGRES_SYNC_REPLICAS`   | `0`            | Set to `1` when `POSTGRES_INSTANCES` is `2` or greater to enable synchronous replication.                                                    |
| `POSTGRES_STORAGE`         | `5Gi`          | Per-instance PVC size.                                                                                                                       |
| `POSTGRES_ENABLE_PDB`      | `false`        | CNPG PodDisruptionBudgets. **Must stay `false` while `POSTGRES_INSTANCES` is `1`**; `"true"` only with ≥ 2. See [Node drains](#node-drains). |
| `POSTGRES_BACKUP_SCHEDULE` | `0 40 4 * * *` | Cron schedule for the S3 `ScheduledBackup`.                                                                                                  |

`POSTGRES_INSTANCES`, `POSTGRES_SYNC_REPLICAS`, and
`POSTGRES_STORAGE` don't exist in bykaj's original (he hardcodes
`instances: 3` plus `minSyncReplicas`/`maxSyncReplicas: 1` and a fixed
image/size for every consumer, uniformly, with no per-app override anywhere
in his repo — verified across all six of his apps that use the component).
Home-lab defaults to `instances: 1` with sync replication disabled
(`POSTGRES_SYNC_REPLICAS: 0`) instead, to avoid paying the 3x pod/storage
cost per app by default on a homelab-sized cluster. **`minSyncReplicas: 1`
with zero replicas blocks every write indefinitely** — there's no replica
to ever satisfy the requirement — so bump `POSTGRES_INSTANCES` and
`POSTGRES_SYNC_REPLICAS` together, never one without the other.

## Node drains

CNPG creates a `${APP}-postgres-primary` PodDisruptionBudget with
`minAvailable: 1` by default. With a single instance that allows **zero**
disruptions: the pod can never be evicted, so every node drain that reaches it
fails. That includes tuppr's Talos upgrades (see
`kubernetes/apps/system-upgrade/README.md`), which retry the drain in a loop and
bounce other pods on the node, Ceph OSDs included, on every attempt. The
component therefore sets `enablePDB: false` by default, as CNPG recommends for
single-instance clusters.

What a drain does instead: the pod is evicted and CNPG recreates it against
the same PVC. Storage is `openebs-hostpath`, which is **node-local**, so the new
pod stays `Pending` until that node is back, and the database is down for the
node's whole maintenance window (roughly 10-20 minutes for a Talos upgrade).
With one instance, that's unavoidable.

**Never set `POSTGRES_ENABLE_PDB: "true"` with `POSTGRES_INSTANCES: 1`.** It
brings back the undrainable node. The 2026-09-25 Talos v1.14.1 run looped on
talos-cp-01 for exactly this reason until the default was flipped. Treat the
two as a pair, like `POSTGRES_INSTANCES`/`POSTGRES_SYNC_REPLICAS`:

| `POSTGRES_INSTANCES` | `POSTGRES_ENABLE_PDB` | During a node drain                                            |
| -------------------- | --------------------- | -------------------------------------------------------------- |
| `1` (default)        | `false` (default)     | Database down until its node is back                           |
| `1`                  | `"true"`              | **Drain blocked forever**                                      |
| ≥ 2                  | `"true"`              | CNPG switches over to a replica; database stays up             |
| ≥ 2                  | `false`               | Primary evicted without a switchover; brief unplanned failover |

To keep a database up through drains, run replicas and enable the PDB
together.

The PostgreSQL image is fixed for every consumer (no `POSTGRES_IMAGE`
override, like bykaj's component) and written as a plain `repo:tag@digest`,
so Renovate's `cnpg` preset tracks `imageName` natively, digest included.
`.renovaterc.json5` keeps it on PostgreSQL 18.x. A Flux
`${VAR:=default}` wrapper around the value would break that: the preset
would read the `${VAR:=` prefix as part of the image name.

## Bootstrap behavior

The component's `Cluster` CR defaults to `bootstrap.recovery` from Barman at
`s3://vwn-io-cluster-cnpg/dedicated/${APP}/${POSTGRES_DATABASE}/`. A
torn-down cluster (delete the `Cluster` CR + PVCs) rebuilds itself from the
latest base backup + replays WAL. Same-path same-`serverName` rebuilds work
because of the `cnpg.io/skipEmptyWalArchiveCheck: enabled` annotation — the
recovered cluster inherits the source's `system_identifier` and writes new
WAL on a new timeline (no name collisions).

That default works for any app that already has a Barman base backup at the
destination. For a brand-new app with **no** prior backup, use the init flow
instead.

### Adding a net-new DB (no prior backup)

For a brand-new app — i.e. nothing exists at
`s3://vwn-io-cluster-cnpg/dedicated/${APP}/` yet — `bootstrap.recovery` would
fail with "no target backup found." Use the `components.postgres/cnpg=init`
label on the consuming Flux Kustomization to switch to plain `initdb`.

Concretely, an app's Flux Kustomization looks like:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app myapp
  labels:
    components.postgres/cnpg: init # <-- add this for initialization only
spec:
  components:
    - ../../../../components/postgres
  # healthCheckExprs are only ever evaluated when `wait: true` or `healthChecks`
  # is also set (see the CRD's own doc string on spec.wait) — without one of
  # these, the Cluster check below is silently never run. `wait: true` would
  # also ignore `healthChecks` and gate on every resource generically, so pair
  # it with an explicit healthChecks entry for the app's own HelmRelease
  # instead, not wait: true.
  healthChecks:
    - apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      name: *app
      namespace: myapp-namespace
  healthCheckExprs:
    - apiVersion: postgresql.cnpg.io/v1
      kind: Cluster
      failed: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'False')
      current: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'True')
  interval: 1h
  path: ./kubernetes/apps/.../myapp
  postBuild:
    substitute:
      APP: *app
      # Optional overrides; all default to ${APP} or the table above.
      # POSTGRES_DATABASE: myapp-db
      # POSTGRES_USERNAME: myapp-user
      # POSTGRES_INSTANCES: "3"
      # POSTGRES_SYNC_REPLICAS: "1"
      # POSTGRES_ENABLE_PDB: "true" # only with POSTGRES_INSTANCES >= 2
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

What the label does (via the patch in
[`flux/cluster/ks.yaml`](../../flux/cluster/ks.yaml), search
`components.postgres/cnpg=init`): strips `spec.bootstrap.recovery` and
`spec.externalClusters`, replacing `bootstrap` with a plain `initdb` that
creates a database + owner role named `${POSTGRES_USERNAME:=${APP}}`. CNPG
generates the role's password into the app Secret as usual.

**After the first scheduled backup lands** (daily at 04:40, or after
manually creating a one-shot `Backup`), **remove the `cnpg: init` label**.
Future cluster rebuilds will then follow the default `recovery` path.
Keeping the label after a backup exists is harmless during normal operation
(bootstrap is only consulted at cluster creation), but it would prevent a
rebuild from ever restoring data if the cluster is ever destroyed and
recreated.

To force an immediate backup so you can drop the label sooner:

```sh
just k8s db-backup <namespace> <app>
```

(equivalent to `kubectl apply`-ing a one-shot `postgresql.cnpg.io/v1 Backup`
against `<app>-postgres` — see `db-backup` in `kubernetes/mod.just`, already
written for this `${APP}-postgres` naming convention.)

## Backups

Daily full backups via the `ScheduledBackup` resource (see
[`scheduledbackup.yaml`](./scheduledbackup.yaml)), with continuous WAL
archiving to the same `s3://vwn-io-cluster-cnpg/dedicated/${APP}/` prefix.
`retentionPolicy: 14d`.

Unlike bykaj's original, there is **no** local NFS backup sidecar
(`postgres-backup-local`-style). S3 is the only backup copy. Add one if a
database ever needs the extra redundancy.

## S3 backend

Every consumer shares one Backblaze B2 bucket (`vwn-io-cluster-cnpg`), each under
its own `dedicated/${APP}/` prefix. The S3 credentials come from the
`cloudnative-pg` 1Password item; only its S3 fields are used. Backups and WAL
are bzip2-compressed and AES256-encrypted, and kept for 14 days.

The `ObjectStore` sets `AWS_REQUEST_CHECKSUM_CALCULATION` and
`AWS_RESPONSE_CHECKSUM_VALIDATION` to `when_required` on the Barman sidecar.
Newer botocore sends chunked-trailer checksums without a `Content-Length`
header, and B2 (like several other non-AWS S3 providers) rejects those uploads
with `MissingContentLength`. These variables restore the older header-based
behaviour. Don't remove them.

`enableSuperuserAccess: true` with no explicit `superuserSecret` means CNPG
generates its own per-cluster superuser credentials, so that part needs no
1Password wiring.

## Connecting from an app

CNPG generates a `${APP}-postgres-app` Secret (CNPG's default naming:
`<cluster name>-app`) with these keys: `uri`, `jdbc-uri`, `username`,
`password`, `host`, `port`, `dbname`, `pgpass`. Confirm the exact name once
deployed — `kubectl get secrets -n <namespace> | grep postgres`.

Default to reading the individual keys rather than `uri`, which most charts
don't accept as a single connection string:

```yaml
DB_HOST: "${APP}-postgres-rw" # or hardcode e.g. "myapp-postgres-rw" if easier to read
DB_USER:
  valueFrom:
    secretKeyRef:
      name: myapp-postgres-app
      key: username
DB_PASSWORD:
  valueFrom:
    secretKeyRef:
      name: myapp-postgres-app
      key: password
DB_NAME:
  valueFrom:
    secretKeyRef:
      name: myapp-postgres-app
      key: dbname
```

(For worked examples, see `forgejo/app/helmrelease.yaml`'s
`additionalConfigFromEnvs` or `n8n/app/helmrelease.yaml`'s `env`.) For a chart
that does accept one connection string:

```yaml
DATABASE_URL:
  valueFrom:
    secretKeyRef:
      name: "{{ .Release.Name }}-postgres-app"
      key: uri
```

Either way, the value points at the cluster's read-write primary service
`${APP}-postgres-rw`. There is no `Pooler` / PgBouncer in this component —
apps connect directly. Add a `Pooler` CRD per cluster as a follow-up if
transaction-mode pooling is ever needed.

## Health check expression

```yaml
healthCheckExprs:
  - apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    failed: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'False')
    current: status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'True')
```

This alone does nothing. Flux only evaluates `healthCheckExprs` when the
Kustomization also has `wait: true` or `healthChecks`, so pair it with a
`healthChecks` entry for the app's HelmRelease, as in the "Adding a net-new
DB" example above. Without one, the Cluster check is silently skipped.

## Known gaps versus bykaj's original

- No local NFS backup sidecar (see [Backups](#backups)).
- **No backup-failure alerting.** If a cluster's backups silently stopped,
  nothing would surface it. A rule for this has to watch the Barman plugin's
  own metric, `barman_cloud_cloudnative_pg_io_last_{available,failed}_backup_timestamp`.
  The legacy `cnpg_collector_last_available_backup_timestamp` metric and the
  `Cluster.status` backup fields stay at zero for plugin-based backups (see
  [cloudnative-pg/plugin-barman-cloud#380](https://github.com/cloudnative-pg/plugin-barman-cloud/issues/380)).
  The natural fix is a `PrometheusRule` in this component, parameterized on
  `${APP}-postgres`, so every consumer gets the alert automatically.
