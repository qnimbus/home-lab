# system

Cluster-wide plumbing that apps rely on but don't talk to directly: storage drivers, snapshot support, event-driven autoscaling, backups, config reloads, GPU access and the schema site.

## Apps

| App                           | What it does                                                                                   | Notes                                                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `crd-schema-publisher`        | Publishes JSON schemas for every installed CRD and the built-ins to `schemas.clustrs.dev`      | Cloudflare Pages project `schemas`; see [yaml-schemas](../../../.agents/instructions/yaml-schemas.instructions.md) |
| `csi-driver-nfs`              | `nfs` StorageClass: one NAS subdirectory per PVC under `/mnt/tank/Cluster/k8s-nfs-csi`         | Used by [`components/nfs-config`](../../components/nfs-config/README.md)                                           |
| `csi-driver-smb`              | SMB CSI driver only, plus the `smb-credentials` Secret                                         | No StorageClass; consumers hand-write static PVs                                                                   |
| `intel-gpu-resource-driver`   | DRA driver exposing the nodes' Intel iGPUs for transcoding                                     | Installed without NFD                                                                                              |
| `keda`, `keda-add-ons-http`   | Event-driven and HTTP scale-to-zero autoscaling                                                | Consumed via `components/keda/*`; CRDs kept on uninstall                                                           |
| `kopiur`, `kopiur-repository` | Kopia backup operator and the `nas` ClusterRepository on the NAS                               | Consumed via `components/kopiur/backup`; read-only UI at `kopia.${DOMAIN_CLUSTER}`                                 |
| `openebs`                     | `openebs-hostpath` local-PV StorageClass under `/var/mnt/openebs/local`                        | Everything but the local hostpath engine is switched off                                                           |
| `reloader`                    | Restarts workloads annotated `reloader.stakater.com/auto` when their Secrets/ConfigMaps change | Watches every namespace                                                                                            |
| `snapshot-controller`         | CSI VolumeSnapshot controller                                                                  | CRDs come from bootstrap, so nothing needs to `dependsOn` it; CRDs kept on uninstall                               |

Everything deploys into `system`. The operators that template their CRDs mark them `helm.sh/resource-policy: keep`, so uninstalling a release (a deleted, renamed or moved HelmRelease) leaves the CRDs and every object of those kinds in place: `keda` through `crds.additionalAnnotations`, `keda-add-ons-http` and `snapshot-controller` through a post-renderer, since their charts have no value for it. Keep that protection; the cost is only that a real removal needs `kubectl delete crd`. Helm reads the policy from the stored release manifest, so it only protects a release once an upgrade has applied it.

## Storage choices

- **`nfs` is scratch space.** `reclaimPolicy: Delete` removes the PVC's NAS subdirectory with it, so nothing precious goes there. Data you can't lose gets a hand-written static PV with `Retain` (see `default/paperless-ngx/app/pv.yaml`). Its export is dedicated rather than shared with the hand-managed `/mnt/tank/Cluster` exports, because the provisioner deletes directories it thinks it owns. Mount options mirror `/etc/nfsmount.conf` in [cluster.yaml.j2](../../talos/cluster.yaml.j2), so CSI mounts behave like the direct NFS mounts. `volumeBindingMode: Immediate`, since NFS has no topology to wait for.
- **SMB has no StorageClass** because every share needs its own source path and credentials. A consumer writes a static PV with `driver: smb.csi.k8s.io`, `storageClassName: smb` on both PV and PVC (no such StorageClass exists; the matching name only pairs them for static binding), and `nodeStageSecretRef: system/smb-credentials`.
- **Kopiur** mounts the repository in the controller too (`/repository`, same path as the ClusterRepository), because it runs catalog scans and maintenance in-process. The NAS share is Mapall to the TrueNAS `kubernetes` user (3001), so neither the controller's UID nor each mover's UID reaches the NAS: movers run as the app's own UID (`KOPIUR_MOVER_UID/GID`) to read and restore its files with the right owner, and kopia's `0600` repository files stay readable across them. Movers have memory requests but no limit, since memory scales with app data and a limit would kill large backups mid-run.

## Operating

```bash
just k8s kopiur snapshots <ns>                         # kopiur snapshots in a namespace, oldest first
kubectl -n system get secret nas-kopia-ui-auth -o yaml # Kopia UI login (user `kopia`), generated by kopiur
```

## Gotchas

- **Every namespace with an HTTPRoute pointing at `keda-add-ons-http-interceptor-proxy` must be listed in [referencegrant.yaml](./keda/app-http-add-on/referencegrant.yaml).** A missing one is silent at apply time: the route is Accepted, `ResolvedRefs` goes False with `RefNotPermitted`, the browser gets a plain 500 and KEDA never scales up. List the consumers with `grep -rl components/keda/http-scaler kubernetes --include=ks.yaml`.
- [`components/keda/http-scaler`](../../components/keda/http-scaler/scaledobject.yaml) hardcodes the add-on's namespace in `scalerAddress` (`keda-add-ons-http-external-scaler.system:9090`), and consumers' HTTPRoutes name it in their `backendRefs`. Moving the add-on means updating both.
- `keda-add-ons-http` must reconcile before any app with an `InterceptorRoute`, since that CRD comes from its chart. Consumers `dependsOn` it.
- The KEDA `GrafanaDashboard` sets `allowCrossNamespaceImport: true`. Grafana lives in `observability`, and without the flag the dashboard is skipped silently.
- `smb-credentials` is created asynchronously by External Secrets. `csi-driver-smb` runs with `wait: true` so a consumer that `dependsOn` it only mounts once the Secret exists.
- `intel-gpu-resource-driver` overrides the chart's CDI paths to `/var/cdi/{static,dynamic}`: `/etc` is read-only on Talos, and the chart defaults crash-looped the driver on every node. The paths must match `cdi_spec_dirs` in [cluster.yaml.j2](../../talos/cluster.yaml.j2). `manageBinding` is off because the iGPU is only used for transcoding, not VFIO passthrough. xpumd stays at its chart default (off), so `healthMonitoring`, which needs it, is disabled and the plugin runs `privileged` to read GPU details from the device itself.
- The `nas` ClusterRepository pins `identityDefaults` to kopiur's own defaults (`policyName@namespace`). Changing them once snapshots exist forks the backup history.
- The Kopia UI (`spec.server`) is read-only: it can browse and restore files but not delete or change backups.
