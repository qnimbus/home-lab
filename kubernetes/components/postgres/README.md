# postgres

CloudNative-PG backed PostgreSQL component, adapted from
[bykaj/home-ops](https://github.com/bykaj/home-ops)'s `components/postgres`:
a dedicated `Cluster` per consuming app. Use for a new app that needs its
own isolated database — **not** a drop-in replacement for the existing
shared `postgres-v17` cluster in `kubernetes/apps/database/cloudnative-pg/`,
which several apps (paperless, open-webui, n8n, firefly) still use and this
component does not touch.

## Substitution variables

| Variable                   | Default                          | Notes                                                                                                                  |
| -------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `APP`                      | _(required)_                     | Name of the consuming app — used for cluster, secret, and backup paths.                                                |
| `POSTGRES_USERNAME`        | `${APP}`                         | Username created on initial bootstrap.                                                                                 |
| `POSTGRES_DATABASE`        | `${APP}`                         | Database name created on initial bootstrap.                                                                            |
| `POSTGRES_IMAGE`           | `cloudnative-pg/postgresql:17.6` | Matches the shared cluster's pinned version, for consistency.                                                          |
| `POSTGRES_INSTANCES`       | `1`                              | No replicas by default. Bump to 3 for automatic failover once an app needs it — CNPG scales live, no rebuild required. |
| `POSTGRES_SYNC_REPLICAS`   | `0`                              | Set to `1` when `POSTGRES_INSTANCES` is `2` or greater to enable synchronous replication.                              |
| `POSTGRES_STORAGE`         | `5Gi`                            | Per-instance PVC size.                                                                                                 |
| `POSTGRES_BACKUP_SCHEDULE` | `0 40 4 * * *`                   | Cron schedule for the S3 `ScheduledBackup`.                                                                            |

`POSTGRES_INSTANCES`, `POSTGRES_IMAGE`, and `POSTGRES_STORAGE` don't exist in
bykaj's original (he hardcodes `instances: 3` and a fixed image/size for
every consumer, uniformly, with no per-app override anywhere in his repo —
verified across all six of his apps that use the component). Home-lab
defaults to `instances: 1` instead, to avoid paying the 3x pod/storage cost
per app by default on a homelab-sized cluster; apps that want HA opt in
explicitly.

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
      # POSTGRES_IMAGE: ghcr.io/cloudnative-pg/postgresql:18.6
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
(`postgres-backup-local`-style) in this component yet — the shared cluster
has one, this doesn't. Add one later if a dedicated cluster needs the extra
redundancy.

## S3 backend

Reuses the same Backblaze B2 bucket and the same `cloudnative-pg` 1Password
item (S3 credentials fields only — not the superuser fields) as the shared
cluster in `kubernetes/apps/database/cloudnative-pg/`, just under a
`dedicated/${APP}/` prefix instead of a separate bucket or a new 1Password
item. `enableSuperuserAccess: true` with no explicit `superuserSecret` means
CNPG auto-generates its own per-cluster superuser credentials — no 1Password
wiring needed for that part at all.

## Connecting from an app

CNPG generates a `${APP}-postgres-app` Secret (CNPG's default naming:
`<cluster name>-app`) with these keys: `uri`, `jdbc-uri`, `username`,
`password`, `host`, `port`, `dbname`, `pgpass`. Confirm the exact name once
deployed — `kubectl get secrets -n <namespace> | grep postgres`.

Standard app-template pattern:

```yaml
DATABASE_URL:
  valueFrom:
    secretKeyRef:
      name: "{{ .Release.Name }}-postgres-app"
      key: uri
```

The `uri` points at the cluster's read-write primary service
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

## Known gaps versus bykaj's original

- No local NFS backup sidecar (see Backups above).
- `components/keda/postgres-scaler` (scale-to-zero) is not wired up for any
  app using this component yet — its `ScaledObject` gates on the _shared_
  cluster's `${PG_HOST}` blackbox probe, which has nothing to do with a
  dedicated cluster's own health. An app switching to a dedicated cluster
  needs its own `Probe` against `${APP}-postgres-rw` before that scaler
  would be meaningful again.
