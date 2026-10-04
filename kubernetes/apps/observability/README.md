# observability

Metrics, alerting, dashboards and logs for the cluster and the NAS. kube-prometheus-stack is the core: it installs the monitoring CRDs and runs Prometheus and Alertmanager. Everything else here feeds it, reads from it, or ships logs to VictoriaLogs.

## Apps

| App                                                                   | What it does                                                                                 | Notes                                                                                                    |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| [kube-prometheus-stack](./kube-prometheus-stack/app/helm/values.yaml) | Prometheus, Alertmanager (3 replicas), node-exporter, kube-state-metrics                     | `prometheus.` / `alertmanager.${DOMAIN_CLUSTER}`; volumes on `ceph-block`                                |
| grafana-operator                                                      | The operator (`grafana-operator`) and the Grafana it runs (`grafana-operator-instance`)      | `grafana.${DOMAIN_CLUSTER}`, anonymous read-only; admin password from the 1Password `grafana` item       |
| victoria-logs                                                         | Single-node log store                                                                        | `victorialogs.${DOMAIN_CLUSTER}`; also takes syslog from the NAS                                         |
| fluent-bit                                                            | DaemonSet shipping container logs to VictoriaLogs                                            |                                                                                                          |
| blackbox-exporter                                                     | TCP probes, defined as `Probe` objects in [probes.yaml](./blackbox-exporter/app/probes.yaml) | Its NAS probes drive KEDA scalers elsewhere (see Gotchas)                                                |
| smartctl-exporter                                                     | SMART metrics from every node's disks                                                        | Privileged DaemonSet                                                                                     |
| unpoller                                                              | UniFi controller metrics and dashboards                                                      | API key from the 1Password `unifi` item                                                                  |
| silence-operator                                                      | Alertmanager silences kept in Git (`silence-operator-silences`)                              | Only files listed in [silences/kustomization.yaml](./silence-operator/silences/kustomization.yaml) apply |

## How it fits together

**Metrics.** Prometheus picks up every `ServiceMonitor`, `PodMonitor`, `Probe`, `PrometheusRule` and `ScrapeConfig` in the cluster (the `*SelectorNilUsesHelmValues: false` settings), so an app only ships the object, with no selector labels. The NAS is scraped through [scrapeconfig-truenas.yaml](./kube-prometheus-stack/app/scrapeconfig-truenas.yaml) on `${NAS_LAN_HOST}`: node-exporter `:9100`, smartctl-exporter `:9633` and doco-cd `:9120`, all published by the `docker/nas` stacks. Their `job` names are distinct from the in-cluster DaemonSets'.

- **etcd** serves plain-HTTP metrics on `:2381` (Talos `listen-metrics-urls`), and the chart finds the control-plane nodes through the `kube-apiserver` static pods. The Talos firewall rule `etcd-metrics-ingress` in `kubernetes/talos/controlplane.yaml.j2` must admit the pod CIDR: Prometheus reaching etcd on its own node arrives from its pod IP, and without that rule the target times out.
- **Flux objects** are exported as `gotk_resource_info` by kube-state-metrics, configured in [flux-metrics.yaml](./kube-prometheus-stack/app/resources/flux-metrics.yaml). The Flux dashboards in `flux-system/flux-instance` read it.

**Alerting.** Alertmanager's root config _is_ [alertmanagerconfig.yaml](./kube-prometheus-stack/app/alertmanagerconfig.yaml) (`alertmanagerConfiguration`), not a discovered sub-route. A discovered one would get the `OnNamespace` matcher, which only routes alerts whose `namespace` label is `observability`.

| Severity           | Receiver            | Behaviour                                                                                             |
| ------------------ | ------------------- | ----------------------------------------------------------------------------------------------------- |
| `critical`         | `pushover-critical` | Emergency priority: Pushover repeats every 60s until acknowledged, for up to 1h. Resolves are silent. |
| `warning`, `error` | `pushover`          | Normal push. `error` is the severity Flux's notification-controller uses (`components/alerts`).       |
| anything else      | `null`              | `info`, `Watchdog`, `InfoInhibitor`                                                                   |

A firing `critical` alert mutes the `warning` alert with the same `alertname` in the same namespace. Reserve `critical` for things worth being woken for; that's why `OomKilled` is a `warning`. The Pushover credentials come from the 1Password `alertmanager` item, which `system-upgrade/tuppr` also reuses.

**Dashboards.** grafana-operator owns Grafana: its Deployment, PVC and route come from [grafana.yaml](./grafana-operator/instance/grafana.yaml). Every `GrafanaDashboard` and `GrafanaDatasource` selects that Grafana by `dashboards: grafana`, the label charts' grafana-operator integrations use by default. kube-prometheus-stack renders its bundled dashboards as `GrafanaDashboard` objects (`grafana.operator` in its values). Apps in other namespaces ship their own, with `allowCrossNamespaceImport: true`. List them with `kubectl get grafanadashboards -A`.

**Logs.** fluent-bit tails `/var/log/containers` and sends JSON lines to `victoria-logs-server:9428`, tagged `log_source=kubernetes`. Talos runs containerd only, so the default `docker`/`cri` parser doesn't match; the `containerd` regex parser in its values does. The pod's app label becomes `app_name`, the same field syslog records use. Syslog from the NAS arrives through [syslog-service.yaml](./victoria-logs/app/syslog-service.yaml):

- It's a separate LoadBalancer that exposes only syslog, so the unauthenticated HTTP API on `:9428` stays cluster-internal. Only `${NAS_LAN_HOST}` may connect, and external-dns publishes `victorialogs-syslog.${DOMAIN_CLUSTER}` for the NAS to point at.
- It maps `514` to `:1514`, because VictoriaLogs runs as uid 1000 and can't bind a privileged port.
- Records carry the sender IP (`useRemoteIP`) because syslog hostnames aren't trustworthy. `proc_id` isn't a stream field because PIDs change on every restart and would start a new stream each time.

## Operating

| Task                                                                   | How                                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grow the Prometheus volume                                             | Raise `storageSpec` in the values **and** edit the live PVC (`kubectl -n observability edit pvc prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0`). The template alone never resizes an existing PVC. Volumes only grow.                |
| Silence an alert permanently                                           | Add a `Silence` to `silence-operator/silences/` and list it in that folder's `kustomization.yaml`                                                                                                                                                                                   |
| Check dashboards synced                                                | `kubectl get grafanadashboards,grafanadatasources -A`; `NoMatchingInstance` means a wrong selector                                                                                                                                                                                  |
| Unwedge doco-cd (`DocoCdPollFailing`, `ref file is empty` in its logs) | A crash mid-fetch leaves a zero-length git ref in its cached clone, and it never self-heals. On the NAS: stop doco-cd, delete the clone under `/data` in the `doco-cd_data` volume (not the whole volume), start it again. The next poll re-clones and redeploys any drifted stack. |
| Grafana admin password                                                 | `just k8s view-secret observability grafana-secret`                                                                                                                                                                                                                                 |

## Gotchas

- **The namespace is PSA `privileged`** (the patch in [kustomization.yaml](./kustomization.yaml)): node-exporter needs hostNetwork, hostPID, host paths and hostPort `9100`, and smartctl-exporter runs privileged.
- **`instanceSelector` is immutable.** To change a dashboard's or datasource's selector, delete the object and let Flux recreate it; for chart-rendered ones, delete them, then `flux reconcile hr <name> --force`.
- **Keep the datasource names and uids** (`Prometheus`/`prometheus`, `Alertmanager`/`alertmanager`, `VictoriaLogs`/`victoria-logs`). Dashboards map their inputs by name, and some hard-code the uid.
- **The VictoriaLogs Grafana plugin is bumped by hand** in [grafanadatasource.yaml](./victoria-logs/app/grafanadatasource.yaml). Its releases are `v`-prefixed but the field must not be, so Renovate can't track it.
- **The Pushover message templates are whitespace-sensitive.** The lines that print text sit at the block's base column on purpose: YAML indentation there becomes literal text in every alert after the first. Pushover also caps a message at 1024 runes, so a message lists only each alert's description, summary or message, for at most 5 alerts.
- **Prometheus sizing:** `retentionSize` stays below the PVC size so Prometheus drops old blocks before the disk fills. Retention is 30 days so multi-week investigations keep their baseline. There's no CPU limit, to avoid throttling during scrape bursts.
- **`crds.upgradeJob`** server-side-applies the CRDs before the operator rolls out, which multi-minor chart jumps need.
- **node-exporter's `chip` label comes from the hwmon device path, not the kernel name**, so check `node_hwmon_sensor_label` before writing a temperature alert. [hardware-temps.yaml](./kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml) keys on `platform_coretemp_0` (Intel) and `pci0000:00_0000:00:18_3` (AMD). smartctl-exporter's own temperature rule is off in favour of these.
- **`NodeHwmonTextfileStale`** watches the NAS's `sensors-textfile` sidecar. If it stops writing, node-exporter keeps serving the last values and every NAS temperature alert goes blind. 90s is six of its 15s scan intervals.
- **The doco-cd rules watch its poll counters, not its health endpoint.** `/v1/health` reports process liveness, and it stayed green while a corrupted clone stopped every reconcile on 2026-09-02. `DocoCdNotReconciling` deliberately isn't `absent()`: a fully down target is `TargetDown`'s job. `DocoCdRestartLoop` exists because short crash loops never last long enough for `TargetDown`.
- **The NAS probes are `tcp_connect`, not `icmp`**, because a host can answer ping while `nfsd` or Samba is wedged. Their `probe_success` series drive KEDA: `:445` scales the apps using `components/keda/smb-scaler`, and `:2049` scales Plex. A failing probe scales those apps to zero.
- **smtp-relay is probed through its in-cluster Service**, because its LoadBalancer only admits the printer's IP. Its module is `smtp_banner` (read the greeting, send `QUIT`, read the reply), not `tcp_connect`: maddy logs an error for every connection dropped without a `QUIT`. The Probes reach the exporter at `blackbox-exporter:9115`, a name that relies on its `fullnameOverride`. VictoriaLogs' `fullnameOverride` likewise keeps `victoria-logs-server`, which fluent-bit, the route and the datasource reference.
- **The `/etc/nfsmount.conf` silence:** Talos writes that file through `machine.files`, and node-exporter reports it as a mountpoint, duplicating `CephNodeDiskspaceWarning`. The other three files in `silences/` are the inactive X520-fallback silences, deliberately left out of the kustomization. Re-add them if the VLAN-200 storage fallback ever returns.
- **fluent-bit doesn't depend on victoria-logs**: its HTTP output retries until the server is up.
- **The Prometheus, Alertmanager and VictoriaLogs routes carry a homepage `pod-selector`** because the charts' pod labels don't match the route names.
- **The Grafana image is rewritten to `mirror.gcr.io`** by [mutatingadmissionpolicy.yaml](./grafana-operator/instance/mutatingadmissionpolicy.yaml), to stay clear of Docker Hub rate limits.
- **unpoller** scrapes every 2m because it only polls the controller that often. Two of its dashboards also declare a stray `DS_UNIFI_POLLER` input, mapped to Prometheus like the rest.
