# default

Personal apps with no better home: finance, documents, git, the dashboard and the guest-WiFi voucher portal. They share nothing beyond the namespace. Each stateful app gets its own CNPG cluster from [`components/postgres`](../../components/postgres/README.md), and every route is on `envoy-internal` except whoami's.

## Apps

| App                  | What it does                                   | Notes                                                                                                      |
| -------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| firefly-iii          | Personal finance manager                       | `firefly.${DOMAIN_CLUSTER}`; Postgres, kopiur-backed upload PVC; hourly cron CronJob                       |
| firefly-iii-importer | Bank CSV/API import for Firefly III            | `firefly-importer.${DOMAIN_CLUSTER}`; scales to zero (KEDA HTTP)                                           |
| forgejo              | Git hosting (upstream chart, not app-template) | `forgejo.${DOMAIN_CLUSTER}`; SSH through the `ssh` listener on `envoy-internal` (TCPRoute); Postgres       |
| homepage             | Dashboard                                      | `homepage.${DOMAIN_CLUSTER}`; config in [app/config](./homepage/app/config/)                               |
| paperless-ngx        | Document archive with OCR                      | `paperless.${DOMAIN_CLUSTER}`; Postgres, Dragonfly, NAS SMB shares; scales to zero when the NAS is down    |
| unifi-voucher-site   | Guest-WiFi voucher portal                      | `voucher.${DOMAIN_CLUSTER}`; scales to zero (KEDA HTTP); no login                                          |
| whoami               | Request-echo test app, **not deployed**        | Add `./whoami/ks.yaml` to [kustomization.yaml](./kustomization.yaml) to enable; public on `envoy-external` |

## How it fits together

**Scale to zero over HTTP.** firefly-iii-importer and unifi-voucher-site use [`components/keda/http-scaler`](../../components/keda/http-scaler/). Their HTTPRoute points at `keda-add-ons-http-interceptor-proxy` in `system`, not at the app's Service, so the interceptor can hold the first request while the pod starts. Meanwhile the `InterceptorRoute` serves a self-refreshing 503 page. It scales on `requestRate`, not concurrency: the placeholder answers in microseconds, so a concurrency gauge is back at 0 before the scaler polls, and scale-up never fires. Their `ks.yaml` depends on `keda-add-ons-http`, because bootstrap doesn't pre-install the `InterceptorRoute` CRD.

**paperless-ngx follows the NAS.** Its own [scaledobject.yaml](./paperless-ngx/app/scaledobject.yaml) scales it to zero while blackbox-exporter's `${NAS_HOST}:445` probe fails. It has no `keda/postgres-scaler` component because KEDA allows one ScaledObject per workload. `cooldownPeriod: 30` gives one extra window past the probe's 30s scrape interval, so a single failed scrape doesn't cold-restart the app. Every KEDA-scaled HelmRelease here ignores `/spec/replicas` in drift detection; without that, Flux would put the replicas back within the hour.

**paperless-ngx storage.** The archive (`consume`, `export`, `media`) and backups live on the NAS `Archive` and `Backup` SMB shares, as static PVs in [pv.yaml](./paperless-ngx/app/pv.yaml):

- They use `Retain`, so deleting the PVC or the app never touches the documents.
- `storageClassName: smb` is only a matching label, since csi-driver-smb is driver-only and no `smb` StorageClass exists. The PVC must still repeat it: it's compared even when `volumeName` is set.
- Each `volumeHandle` must be unique cluster-wide.
- The mount credentials are `system/smb-credentials`. The `csi-driver-smb` Kustomization that creates them has `wait: true`, which is what the `dependsOn` here relies on.

Gotenberg and Tika run as sidecars in the same pod and are reached over `localhost`.

**Firefly III.** The importer calls Firefly through its in-cluster Service. `VANITY_URL` is the browser-facing URL for anything sent to the user, like the OAuth redirect. The `firefly-iii-cron` CronJob calls `/api/v1/cron/<STATIC_CRON_TOKEN>` hourly. Firefly needs this at least daily for recurring transactions, bills and auto-budgets. Both apps read the 1Password `firefly-III` item.

**homepage** discovers services from the `gethomepage.dev/*` annotations on HTTPRoutes across the cluster, so a new app shows up by annotating its route. For that it needs a read-only ClusterRole and `automountServiceAccountToken: true`, which chart v5 defaults to false. Its MCP endpoint is on, authenticated by `HOMEPAGE_MCP_TOKEN` because there's no session auth. It's read-only because `/app/config` is a ConfigMap mount.

## Operating

```bash
just k8s db-backup default <app>                    # manual CNPG backup
just k8s database dump default <app> "" <db>        # "" = default file under ~/cnpg-backups
just k8s database restore default <app> <file> <db>
just k8s browse-pvc default <claim>
```

The database names differ from the app names for firefly-iii (`firefly`) and paperless-ngx (`paperless`), and `dump`/`restore` default `db` to the app name. `just` arguments are positional only: `db=firefly` would be taken as the file name.

## Gotchas

- **paperless-ngx `PAPERLESS_FILENAME_FORMAT`**: app-template runs env values through Helm's `tpl`, so Jinja's `{{ }}` must be written `{{"{{"}} … {{"}}"}}`. Unescaped, the HelmRelease fails to render and the old pod silently keeps running. `{% %}` needs no escaping.
- **paperless-ngx starts as root** (container `securityContext`). The s6-overlay init installs `tesseract-ocr-nld` for `PAPERLESS_OCR_LANGUAGES` and chowns the volumes; both fail as non-root. `USERMAP_UID`/`USERMAP_GID` then drop the app processes to 1000.
- **paperless-ngx v3** needs `PAPERLESS_DBENGINE` set explicitly (it was inferred from `DBHOST` before).
- **paperless-ngx's Dragonfly has no auth.** The operator's NetworkPolicy admits `6379` from any pod in `default`, so anything in this namespace can reach it.
- **Long startup probes** (`failureThreshold: 60`) on firefly-iii and paperless-ngx cover first-boot migrations and search-index builds.
- **firefly-iii's upload PVC** was created by an older chart version and carries `helm.sh/resource-policy: keep`. Helm left it in place, and kopiur's backup component now references it.
- **forgejo** leaves `image.tag` unset so it follows the pinned chart's `appVersion`. `cache`/`queue`/`session` are unset too, so the chart falls back to in-memory, which is fine for one replica.
- **unifi-voucher-site** has `AUTH_DISABLE: "true"`. That's only acceptable while it's internal-only; revisit it if the route is ever widened. Its secret reshapes the shared 1Password `unifi` item (full-URL `UNIFI_HOST` to bare `UNIFI_IP`/`UNIFI_PORT`, `API_KEY` to `UNIFI_TOKEN`). All other settings are listed in the [upstream README](https://github.com/glenndehaan/unifi-voucher-site).
- **whoami** listens on 8080 so it can run as non-root; its Service keeps port 80.
