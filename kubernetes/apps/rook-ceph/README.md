# rook-ceph

The cluster's replicated block storage: a Rook-managed Ceph cluster on one dedicated NVMe in each node (the nodes have other NVMe disks, which Ceph never touches), serving the default StorageClass `ceph-block` and the `ceph-block-snapshot` VolumeSnapshotClass that kopiur backups use. Everything lives in one app folder, [rook-ceph](./rook-ceph), as three Flux Kustomizations in one [ks.yaml](./rook-ceph/ks.yaml).

## Apps

| Kustomization           | What it does                                                                                 | Notes                                                                                                           |
| ----------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `rook-ceph-operator`    | Rook operator, the `ceph.rook.io` CRDs, and the ceph-csi-operator subchart with its own CRDs | Also holds the dashboard password ExternalSecret, so the Secret exists before the `CephCluster` reads it        |
| `rook-ceph-csi-drivers` | The RBD `Driver` and `OperatorConfig`, CSI ServiceAccounts and RBAC                          | Chart from ceph-csi-operator, not Rook. Depends on the operator                                                 |
| `rook-ceph-cluster`     | `CephCluster`, the `ceph-blockpool` pool, StorageClass, snapshot class, toolbox, dashboard   | Route `ceph.${DOMAIN_CLUSTER}`, three Grafana dashboards. Other apps `dependsOn` this one for `ceph-block` PVCs |

## How it fits together

**Order.** Upstream requires `rook-ceph` → `ceph-csi-drivers` → `rook-ceph-cluster` on every upgrade. Each chart's `OCIRepository` sits in its own Kustomization path, so a Renovate bump changes only that Kustomization, and its `wait: true` holds until the HelmRelease is Ready again. The cluster Kustomization depends on the operator but deliberately **not** on the drivers: that would hold back the cluster HelmRelease's own spec (its `dependsOn`, the Ceph image pin) exactly when a bump needs it applied. The HelmRelease-level `dependsOn: ceph-csi-drivers` orders those two instead.

**Three version lines**, each moved on its own:

| What                     | Pinned in                                                                               | Rule                                                                                                                                                                                                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rook (operator, cluster) | both `ocirepository.yaml` files                                                         | One Renovate group, always bumped together                                                                                                                                                                                                                                               |
| ceph-csi-drivers         | [csi-drivers/app/ocirepository.yaml](./rook-ceph/csi-drivers/app/ocirepository.yaml)    | At or below the `ceph-csi-operator` subchart in the rook-ceph chart (`dependencies` in its `Chart.yaml`), because the operator owns the CRDs. Renovate is capped (`allowedVersions` in `.renovaterc.json5`): raise the cap and the tag by hand after a Rook bump that moves the subchart |
| Ceph                     | `cephImage` in [cluster/app/helmrelease.yaml](./rook-ceph/cluster/app/helmrelease.yaml) | Pinned, because the chart's default follows the Rook release line and would turn a chart bump into an unreviewed Ceph major upgrade. Renovate is held to the stable line the pinned Rook supports. Before a major: Rook's ceph-upgrade guide and the Ceph release notes                  |

**Network.** Ceph is host-networked, and both its public and cluster network are the storage bond (`10.200.0.0/24`), keeping all Ceph traffic off the management NICs. The CSI node plugin is host-networked too (not configurable); the controller plugin stays on the pod network and reaches the mons through Cilium, which is why `bond-storage` is one of Cilium's `devices` (see [kube-system](../kube-system/README.md)). Changing `network` only reaches a daemon at its next restart: mons have to be failed over one at a time and OSD pods restarted per node, by hand.

**CSI settings live in two places.** The operator chart only carries the ceph-csi-operator and the image set (`rook-csi-operator-image-set-configmap`, which keeps sidecar images at the versions Rook tested). Which drivers run, and how, is the drivers release. The old `csi.*` switches in the operator chart are gone and silently ignored.

## Operating

```bash
just k8s toolbox                      # shell in rook-ceph-tools: ceph status, ceph osd tree, ceph df
kubectl -n rook-ceph get cephcluster  # health as Flux and tuppr see it
```

The dashboard is at `ceph.${DOMAIN_CLUSTER}`; its password comes from the 1Password item `rook-ceph`, as the Secret `rook-ceph-dashboard-password` (the name Rook expects). tuppr gates every node reboot on `HEALTH_OK`, so a lingering warning blocks Talos upgrades (see [system-upgrade](../system-upgrade/README.md)).

## Gotchas

### Don't change

- **The drivers release must be named `ceph-csi-drivers`.** Rook stamps the `Driver` and `OperatorConfig` it created with that release name so exactly this release can adopt them. Another name fails Helm's ownership check.
- **The RBD driver name `rook-ceph.rbd.csi.ceph.com`** is the provisioner in the StorageClass, the snapshot class and every existing PV. Renaming it orphans them all.
- **Everything the drivers chart renders is marked `keep`.** The cluster-wide install remediation answers a failed install with `helm uninstall`, which would delete the adopted `Driver` (tearing down the RBD node DaemonSet and provisioner) or the CSI RBAC. The operator release marks its CRDs `keep` for the same reason: the subchart's `csi.ceph.io` CRDs aren't kept by the chart, and losing them deletes the `Driver`.
- **CSI keys stay `keyType: aes`.** AES256K keys need a 7.0 kernel on the nodes, and a key rotation that picked AES256K would break every PVC mount. It equals the chart default and is stated on purpose.
- **No size=1 pool.** `ceph-block-single` was retired on 2026-06-24: single-copy PGs make `ceph osd ok-to-stop` false for every OSD, which jams Rook's rolling OSD updates and every Ceph upgrade. Throwaway data goes on `openebs-hostpath`.
- **No `compression_*` keys in the StorageClass `parameters`.** Compression is a pool property (`parameters` on the pool's `spec`), and StorageClass parameters are immutable, so adding one fails every Helm upgrade.
- **Devices are pinned by `/dev/disk/by-id`**, with `useAllNodes` and `useAllDevices` off. NVMe enumeration differs per node (the OSD disk is `nvme0n1` on the workers and another name on each control-plane node), so a kernel-name selector could wipe a system disk.
- **Driver settings go under `drivers.rbd`, not `driverSpecDefaults`.** The chart always renders `snapshotPolicy`, `grpcTimeout`, `log` and the controller plugin fields on the `Driver`, and the operator lets those win.

### Why it is set this way

- **`snapshotPolicy: volumeSnapshot`**: the chart default drops the snapshotter sidecar that `ceph-block-snapshot` needs. **`grpcTimeout: 150`**: Rook's long-standing value; the chart's 30s gives spurious provisioning failures on a busy cluster. **Log rotation off**: it would move CSI logs from stdout to a hostPath, out of VictoriaLogs.
- **CSI resources and priority classes** are Rook's old defaults. The chart ships none, which would make the node plugin BestEffort.
- **`osdsPerDevice: 2`** gives independent TCP flows between node pairs, so the LACP bond spreads replication over both links.
- **mgr modules:** `rook` is off because on Ceph 20.2.3 and 20.2.4 the prometheus module calls an orchestrator method it doesn't implement, logging a module crash every 15 seconds (rook/rook#18124). It only feeds dashboard pages nobody uses. `restful` is off because Tentacle removed it.
- **Muted health warnings.** The four `AUTH_INSECURE_*` warnings stay for as long as any CephX key is AES, which the CSI keys are. The mute lives in Ceph and is sticky: removing an entry does not unmute it. Flip it to `policy: unmute` once the CSI keys can move. The two `HEALTH_ERR` codes of that family are deliberately not muted.
- **Tolerations for `tuppr.home-operations.com/outdated`** keep mons and the mgr running through a Talos upgrade. OSDs are pinned to their node anyway.
- **Log noise:** `mon_cluster_log_to_stderr` off (each mon otherwise repeats every other mon's cluster log; `ceph log last` still has it), pg_autoscaler at `error`, and RocksDB stats dumps off. The last one goes through `bluestore_rocksdb_options_annex`: `rocksdb_stats_dump_period_sec` is not a Ceph key, and setting it put the operator in a failed-reconcile loop.
- **Alert overrides:** the stock `CephNodeDiskspaceWarning` and `CephNodeNetworkPacketDrops` rules have no `for:`, so one noisy evaluation fired them. The first also skips a node's first 30 minutes after boot, when too little history skews its two-day prediction.
- **Dashboard:** `ssl: false` because the gateway terminates TLS. `prometheusEndpoint` feeds its embedded graphs, which are blank without it.
- **`wipeDevicesFromOtherClusters`** only matters when the `CephCluster` is torn down: it lets a rebuilt cluster reuse a disk with a stale bluestore signature.
- **The CSI ServiceMonitor can't work.** It selects Services the ceph-csi-operator never labels, so leave it off.
- **The namespace enforces PodSecurity `privileged`**, so Ceph's privileged, host-networked pods keep being admitted if the cluster default is ever tightened.
- **The Grafana dashboards set `allowCrossNamespaceImport`**, since Grafana runs in `observability`.

### Rotating CephX keys

Bump `security.cephx.daemon.keyGeneration` and leave the policy; don't set `daemon.keyType` (Rook picks the cipher). When Rook's guide pairs a rotation with a Ceph bump, land both in one change. Expect about ten minutes of `HEALTH_ERR` while Rook rolls every daemon and then rotates the keys, restarting each daemon set a second time. During that window Flux and `CephHealthError` both alert, and the operator logs an error on purpose to restart the mons. It clears once every `status.cephx.*.keyGeneration` matches. Don't roll back for it.
