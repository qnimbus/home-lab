# system-upgrade

Automated, GitOps-driven Talos and Kubernetes upgrades, run by [tuppr](https://tuppr.home-operations.com). A version bump merged to `main` is all it takes: Flux applies the new target, and tuppr rolls it out node by node with health checks, alert silences and progress notifications.

## Layout

| Path                                   | What it is                                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `tuppr/ks.yaml`                        | Two Flux Kustomizations: `tuppr` (operator) → `tuppr-upgrade` (upgrade resources)                    |
| `tuppr/app/helm/values.yaml`           | Chart values: notifications, Alertmanager silences, monitoring, Reloader                             |
| `tuppr/app/externalsecret.yaml`        | `tuppr-notification-secret`: the Pushover URL for progress notifications                             |
| `tuppr/app/prometheusrule.yaml`        | `TalosUpgradePending` / `KubernetesUpgradePending`, which fill a gap in the chart's rules            |
| `tuppr/upgrade/talosupgrade.yaml`      | `TalosUpgrade/cluster`: target Talos version, rollout policy, health gate (backups + Ceph), silences |
| `tuppr/upgrade/kubernetesupgrade.yaml` | `KubernetesUpgrade/kubernetes`: target Kubernetes version and backup checks                          |

## How an upgrade happens

1. **Renovate opens a PR** that bumps each version in two places, which must stay equal:

   | Version    | Node config (`kubernetes/talos/version.yaml`) | tuppr target                                       | Renovate dependency                         |
   | ---------- | --------------------------------------------- | -------------------------------------------------- | ------------------------------------------- |
   | Talos      | `talos_version`                               | `talosupgrade.yaml` `spec.talos.version`           | `custom.talos-factory` / `siderolabs/talos` |
   | Kubernetes | `k8s_version`                                 | `kubernetesupgrade.yaml` `spec.kubernetes.version` | `docker` / `ghcr.io/siderolabs/kubelet`     |

   Both files carry the same `# renovate:` annotation, so Renovate sees each pair as one dependency and bumps both in a single PR. `version.yaml` feeds `just talos render-config`/`apply-node`, and the tuppr files drive the actual upgrade. Merging a PR that changes only one side leaves the rendered node config and the running cluster disagreeing. If you bump by hand, bump both.

2. **Merge to `main`.** Flux reconciles `tuppr-upgrade` and applies the new spec, which starts a new run.
3. **tuppr runs the upgrade** (see below), sending a Pushover message as each node starts and finishes.
4. **Verify** with `just talos nodes`, which lists each node's Talos and kubelet versions.

Talos and Kubernetes upgrades never run concurrently: whichever starts first runs to completion, and the other waits in `Pending` and starts on its own afterwards. Merging both PRs in one sitting is safe, just slow (a 5-node Talos run takes 1–3h).

## What a Talos run does

`TalosUpgrade/cluster` targets every node, **one at a time** (`parallelism: 1`). Two control-plane nodes down together would break etcd quorum on this 3 CP + 2 worker cluster.

Per run:

1. **Pre-pull** (on by default): the installer image is pulled onto every node before anything is cordoned. A bad tag or schematic parks the run in `Pending` before any disruption. Spegel serves the image peer-to-peer, so this normally clears in under two minutes.
2. **Health gate**, re-checked every 10s before each node; the node waits until every check passes:
   - **Backups:** no kopiur `Snapshot` may be `Running` (a just-created one without a status also blocks) and no `Restore` may be `Resolving`/`Restoring`. Timeout 30m, which leaves room for a large first backup.
   - **Ceph:** the `CephCluster` must report `HEALTH_OK`. Because this runs before _every_ node, each reboot waits until Ceph has fully recovered from the previous one, instead of stacking a second outage on a degraded cluster. It sets no `timeout`, so tuppr's 10m default applies.

   The flip side: any _lingering_ `HEALTH_WARN` blocks the whole run, not just a recovering one. The usual suspect after reboots is `RECENT_CRASH`, which stays for about two weeks unless archived (`ceph crash archive-all` from `just k8s toolbox`). Muted warnings (e.g. the insecure-key-type auth warnings) leave the cluster at `HEALTH_OK` and don't block.

3. **Per node**: drain, wait for CSI volumes to detach, upgrade, reboot, and wait for the node to come back `Ready` on the new version.

Policy choices that differ from upstream defaults:

| Setting                      | Value        | Why                                                                                                                                                                                                                  |
| ---------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `policy.waitForVolumeDetach` | `true`       | `ceph-block` is the default StorageClass, so most pods hold RWO RBD volumes. Without it, a fast reboot orphans the mount and the pod hits `Multi-Attach` on its next node.                                           |
| `policy.placement`           | `hard`       | The upgrade Job must never land on the node it's rebooting. Pinned explicitly: this object was created when the default was `soft`, and later default changes never touch a field that already exists.               |
| `policy.rebootMode`          | `powercycle` | A full power cycle instead of Talos's default (kexec) reboot, which upstream recommends for nodes that don't reboot cleanly. Matches `just talos upgrade-node` and `reboot-node`, which already use `-m powercycle`. |
| `policy.debug`               | (default)    | Left on. The webhook warns about it on every apply, but a verbose Job log is worth more on a rare, hard-to-rerun upgrade. Don't "fix" the warning.                                                                   |

Things to know about timing:

- `policy.timeout` (30m) bounds each node's `talosctl` command, **not** the drain. The drain has its own hard-coded 10m timeout, and the volume-detach wait is a best-effort 2m.
- Rook's OSD/mon/mgr PDBs block eviction while Ceph recovers from the previous node, so a full run is serialised on Ceph recovery and can take hours. The Ceph health gate adds the full wait for `HEALTH_OK` on top of that.
- If a drain fails, tuppr rolls the batch back and uncordons every node, including the failing one, then retries after 1m. Nodes are not left cordoned.

### How the upgrade image is chosen

tuppr doesn't read `schematic.yaml.j2`. It takes each node's **current** install image and swaps in the new version, so a node stays on whatever factory schematic it was installed with. If the node's running extensions don't match the schematic in its install image, tuppr refuses to upgrade that node (the run sits in `Pending`, which is what `TalosUpgradePending` catches).

**Changing a schematic is therefore an out-of-band job**: `just talos apply-node <node>` to push the new install image into the machine config, then `just talos upgrade-node <node>`. That's also how most of the nodes reached their current schematic.

## What a Kubernetes run does

`KubernetesUpgrade/kubernetes` upgrades the control plane and kubelets cluster-wide, with no node reboots. It uses the same backup checks as Talos, but no Ceph check: nothing reboots, so Ceph isn't disturbed. tuppr's webhook allows **only one** `KubernetesUpgrade` per cluster: edit its version, never add a second resource.

## Alerting and notifications

| Channel                                            | Tells you                                         | Source                                                               |
| -------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------- |
| Pushover progress messages                         | "node 3 of 5 started / finished"                  | tuppr itself (`notification.*` in values)                            |
| Chart `PrometheusRule`                             | Run `Failed`, `Stuck`, `Blocked`; operator absent | `monitoring.prometheusRule.enabled`                                  |
| `TalosUpgradePending` / `KubernetesUpgradePending` | A run stuck in `Pending` for 15m                  | `app/prometheusrule.yaml`                                            |
| Grafana dashboard, ServiceMonitor                  | Phase and duration metrics                        | `monitoring.*` (picked up by kube-prometheus-stack's `{}` selectors) |

**Why the Pending alerts exist:** the chart's rules don't cover `Pending`, and progress notifications only fire once a run starts. On 2026-09-09 the v1.13.10 run sat in `Pending` for ~19 minutes (a schematic mismatch on talos-cp-01) and nothing fired on either channel. The rules key on `tuppr_*_upgrade_phase{phase="Pending"}`, not on `tuppr_upgrade_progressing` (which also reads 0 after a clean finish). They exclude tuppr's own Talos/Kubernetes coordination wait, which is healthy. `for: 15m` outlasts a normal pre-pull and still beats the 19 minutes that went unnoticed.

**Notification credentials:** the ExternalSecret reuses the 1Password `alertmanager` item (`pover://<user key>@<token>`), so tuppr notifies wherever Alertmanager does, and rotating those credentials re-renders this Secret too. Split it into its own item if that coupling ever gets in the way. The chart injects the URL as an env var, so the Deployment carries `reloader.stakater.com/auto` to restart on rotation. Without it, notifications would silently go nowhere after a rotation.

### Silences during a run

tuppr holds Alertmanager silences only while a run is active. The silence is a short lease it keeps extending, capped per node at `maxDuration: 4h`, then released. It reaches Alertmanager directly at `kube-prometheus-stack-alertmanager.observability.svc:9093` (no auth, since the v2 API is unauthenticated in-cluster).

The rule is: **silence the expected effects of a planned drain and reboot, never the alerts that would show the upgrade itself going wrong.**

| Silenced                      | Alerts                                                                                                                                                                                   |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Node leaving and rejoining    | `KubeNodeNotReady`, `KubeNodeUnreachable`, `KubeNodeReadinessFlapping`, `KubeNodeEviction`, `KubeletDown`                                                                                |
| Workload churn from the drain | `KubeDeploymentReplicasMismatch`, `KubeDaemonSetNotScheduled`, `KubeDaemonSetRolloutStuck`, `KubeContainerWaiting`, `KubePodNotReady`, `KubePdbNotEnoughHealthyPods`                     |
| Ceph losing one host          | `CephOSDDown`, `CephOSDHostDown`, `CephMonDown`, `CephHealthWarning`, `CephOSDFlapping`, `CephDaemonSlowOps`, `CephNodeNetworkPacketDrops`, `CephMonDownQuorumAtRisk`, `CephOSDDownHigh` |
| tuppr false positive          | `UpgradeJobRunningTooLong`: a hard-coded 1h on a cluster-wide gauge that a healthy 5-node run can exceed. It still fires outside a run.                                                  |

Deliberately **still paging**: `CephHealthError`, `CephPGsInactive`, `CephPGUnavailableBlockingIO`, `CephFilesystem*`, `KubeAPIDown`, tuppr's `TalosUpgradeFailed` / `TalosUpgradeNodeFailed` / `TalosUpgradeStuck`, and the two `*Pending` rules. These key on data actually being unavailable rather than redundancy being reduced.

`CephMonDownQuorumAtRisk` and `CephOSDDownHigh` started out unsilenced, but at this cluster's size any one host being down trips both (10 OSDs at 2 per host, so one host is 20%; 3 mons, so one down is at the quorum floor), and neither has a topology-aware threshold. Every alert name in the list was checked against the live rule set, because a typo would silently match nothing.

## Operating

```bash
kubectl get talosupgrade,kubernetesupgrade -n system-upgrade -w      # watch
kubectl describe talosupgrade cluster -n system-upgrade              # status + events
kubectl get talosupgrade cluster -n system-upgrade -o jsonpath='{.status.message}'
kubectl logs -f deploy/tuppr -n system-upgrade                       # controller
just talos nodes                                                      # versions per node
```

| Task                       | How                                                                                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pause / resume a run       | `kubectl annotate talosupgrade cluster -n system-upgrade tuppr.home-operations.com/suspend="true"` (remove with `suspend-`). This also expires its silences. |
| Retry a `Failed` run       | `kubectl annotate talosupgrade cluster -n system-upgrade tuppr.home-operations.com/reset="$(date)"`. `Failed` is terminal until you act.                     |
| Upgrade a node by hand     | `just talos upgrade-node <node>` (suspend tuppr first so it doesn't interfere)                                                                               |
| Upgrade Kubernetes by hand | `just talos upgrade-k8s <version>`                                                                                                                           |
| Debug the controller       | Set `controller.logLevel: debug` in `values.yaml` temporarily                                                                                                |
| Emergency stop             | `kubectl scale deploy/tuppr -n system-upgrade --replicas=0`                                                                                                  |

## Flux wiring and its trade-off

`tuppr-upgrade` depends on `tuppr` because the `TalosUpgrade`/`KubernetesUpgrade` CRDs only exist once the chart is installed. That's the usual operator → CR split.

`tuppr` in turn depends on **kube-prometheus-stack**, because the chart renders a ServiceMonitor and PrometheusRule and `app/prometheusrule.yaml` needs the CRD for Flux's dry-run. Without it, a fresh bootstrap races, the Helm install fails, and remediation uninstalls the release, taking `tuppr-upgrade` down with it. Other apps (blackbox-exporter, flux-instance, cloudnative-pg) ship PrometheusRules without this dependency and just tolerate the transient failure. tuppr doesn't, because a failed install here is uninstalled rather than retried.

The cost: a break anywhere up the chain (kube-prometheus-stack → rook-ceph-cluster) freezes delivery of `TalosUpgrade` changes, including a rollback. In practice the window is narrow. rook-ceph-cluster only reports failed on `HEALTH_ERR`, and the whole 2026-09-09 run sat in `HEALTH_WARN` with the chain intact. If it ever does freeze, `tuppr-upgrade` shows `DependencyNotReady` and stays on its last revision. Don't fight Flux: recover the node with `just talos upgrade-node` instead.
