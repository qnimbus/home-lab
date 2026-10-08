# database

The database operators. Nothing here is a database: each app gets its own instance, in its own namespace, by pulling in a component. [postgres](../../components/postgres/README.md) creates a CloudNative-PG `Cluster` with its backups, [dragonfly](../../components/dragonfly/README.md) a Redis-compatible `Dragonfly`. Those READMEs cover the instances; this one covers the operators behind them.

## Apps

| App                       | What it does                                                      | Notes                                                                  |
| ------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `cloudnative-pg-operator` | The CloudNative-PG operator, its dashboard and alert rules        | The HelmRelease is `cloudnative-pg`                                    |
| `plugin-barman-cloud`     | CNPG plugin that ships base backups and WAL to S3 (`ObjectStore`) | Needs cert-manager; `dependsOn` the operator                           |
| `dragonfly-operator`      | The Dragonfly operator and its dashboard                          | Lives in [dragonfly/](./dragonfly/); the HelmRelease has the same name |

The first two share [cloudnative-pg/ks.yaml](./cloudnative-pg/ks.yaml).

## How it fits together

- **Apps wait for an operator through their HelmRelease, not their Kustomization.** Each component patches `dependsOn` onto the app's HelmRelease: `cloudnative-pg` or `dragonfly-operator`, in `database`. Renaming one of these HelmReleases therefore breaks every consumer; find them with `grep -rl "components/postgres\|components/dragonfly" kubernetes/apps --include=ks.yaml`.
- **`plugin-barman-cloud` talks to the operator over mutual TLS.** Its chart creates a self-signed `Issuer` and two `Certificate`s, which is why its Kustomization depends on `cert-manager` (for the CRDs, not for a `ClusterIssuer`).
- **Dashboards reach Grafana two ways.** The CNPG chart only renders a ConfigMap (`monitoring.grafanaDashboard.create`), so [grafanadashboard.yaml](./cloudnative-pg/operator/app/grafanadashboard.yaml) wraps it in a `GrafanaDashboard`. The Dragonfly chart renders its own `GrafanaDashboard` (`grafanaDashboard.grafanaOperator`). See [observability](../observability/README.md) for how Grafana selects them.
- **The alert rules cover every `Cluster` in the cluster**, whichever namespace it is in: [prometheusrule.yaml](./cloudnative-pg/operator/app/prometheusrule.yaml) reads the `cnpg_*` metrics the instances export. Backup alerting is the component's business, see its README.

## Operating

```bash
kubectl get clusters.postgresql.cnpg.io,dragonflies -A        # every instance and its state
kubectl get backups.postgresql.cnpg.io -A                     # base backups and their phase
just k8s db-backup <namespace> <app>                          # base backup to S3, now
just k8s database dump <namespace> <app> [file] [db]          # pg_dump to a local file
just k8s database restore <namespace> <app> <file> [db]       # DESTRUCTIVE, asks first
```

`dump` and `restore` ([mod.just](./mod.just)) work on the `<app>-postgres` cluster's primary. `restore` drops and recreates the objects in the target database and disconnects its clients first; it needs a real terminal for the confirmation. A relative file path is resolved against the directory `just` was called from.

## Gotchas

- **Uninstalling an operator must never take its CRDs along.** Deleting a CRD deletes every `Cluster` or `Dragonfly` in the cluster, and with it the data. All three charts template their CRDs with `helm.sh/resource-policy: keep` (for Dragonfly through its default `crds.keep: true`; don't switch that off). Before moving or renaming a release here, read [helm-crds](../../../.agents/instructions/helm-crds.instructions.md).
- **The operators are not in bootstrap's CRD phase.** On a fresh cluster an app with a `Cluster` or `Dragonfly` fails its dry-run until the operator has installed its CRDs, and Flux retries it.
- **An operator upgrade can restart every database.** A new CNPG operator version rolls out its instance manager to all `Cluster` pods; with one instance per app (the component's default) each database is briefly down.
- **The Barman plugin runs as a sidecar in every `Cluster` pod**, injected by the operator. Its image version follows the plugin's chart, so an upgrade here also changes the database pods.
