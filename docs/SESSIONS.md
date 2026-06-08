# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

---

## 2026-06-08 — `docs-consolidation`

### Goal
Audit and consolidate the project documentation — fix stale facts, separate agent-facing from human-facing docs, de-duplicate repeated facts, archive the abandoned Longhorn storage-VLAN doc, and cap the ever-growing SESSIONS.md by splitting off an archive.

### What we did
- **Audited the full doc surface** (12 tracked docs + the `.claude/` agent corpus). Confirmed `tmp/`, `.agents/`, and `.claude/skills/` are all gitignored/vendored and out of scope. Classified every doc by primary audience (🤖 agent / 👤 human / 🗄️ history) and found the root problem: the same facts (hardware, "what's deployed", versions) live in 3–4 docs and drift independently with no designated source of truth.
- **Fixed 4 high-severity staleness items.** CLAUDE.md: jumbo-frames `TODO` → "live on all 3 nodes"; cp-03 RAM `92GB` → `96GB ECC`; Longhorn `2-replica interim` → `3-replica` + a new **Rook-Ceph (storage pivot)** row. ROADMAP.md: collapsed the 199-line abandoned *Longhorn Storage Network (Multus + Storage VLAN)* section into a ~30-line **ABANDONED** stub + a new first-class **Rook-Ceph Migration** item — lifting out the still-valid `replicaReplenishmentWaitInterval` tuning and leaving the untouched *cp-02 Thermal Stability* section intact. Reconciled the *Future Storage Options* framing (Rook/Ceph no longer "optional Stage 3").
- **De-duplicated facts.** Made CLUSTER.md the declared source of truth for current-state hardware/networks (CLAUDE.md now links out); reframed POTENTIAL-DEPLOYMENTS.md as an explicitly-secondary *candidate backlog* and fixed its broken `../tmp/home-ops-bykaj` reference → canonical `github.com/bykaj/home-ops`.
- **Created `docs/README.md`** — an audience-labelled index with statuses and a **source-of-truth map** assigning ownership of each shared fact. Fleshed out the root `README.md` stub with a real overview + documentation map (kept the accurate Getting Started section).
- **Archived `docs/longhorn-storage-network.md` → `docs/history/`** (plain `mv`, not `git mv`, to stay unstaged) and distilled its same-host-iSCSI + whereabouts PR #703 root cause into a new QA.md entry, whose heading is anchored to the links placed in CLAUDE.md/ROADMAP. Repointed the inbound links in HARDWARE-ARCHITECTURE.md and REPO-AUDIT.md; left SESSIONS.md's historical path-mentions untouched.
- **Split SESSIONS.md (2871 → 1026 lines, −64%)** at the 2026-05-22 bootstrap/day-2 boundary: the 51 older bootstrap-era sessions (2026-05-06 → 05-21) moved to a new `docs/SESSIONS-ARCHIVE.md` via a lossless character-index cut (32 + 51 = all 83 sessions preserved). Wired cross-pointers in both files, `docs/README.md`, and CLAUDE.md (new sessions always append to the active file; roll the oldest off when it grows again).

### Files changed
| File | Change |
|------|--------|
| `CLAUDE.md` | Hardware SoT pointer + jumbo/RAM fixes; Longhorn 3-replica + Rook-Ceph rows; SESSIONS-archive note |
| `README.md` | Replaced stub banner with project overview + documentation map |
| `docs/README.md` | **New** — audience-labelled doc index + source-of-truth map |
| `docs/ROADMAP.md` | Collapsed abandoned Longhorn-VLAN section → stub; added Rook-Ceph Migration item; reconciled Future Storage Options + TOC |
| `docs/POTENTIAL-DEPLOYMENTS.md` | Reframed as candidate backlog; fixed broken `tmp/` ref → `github.com/bykaj/home-ops` |
| `docs/QA.md` | Added distilled "why storage-VLAN was abandoned" root-cause entry (same-host iSCSI, whereabouts PR #703) + TOC row |
| `docs/REPO-AUDIT.md` | Repointed longhorn-doc path mention to `docs/history/` |
| `docs/HARDWARE-ARCHITECTURE.md` | Repointed broken longhorn-doc link to `history/` |
| `docs/longhorn-storage-network.md` → `docs/history/` | Moved (abandoned topic; full post-mortem preserved) |
| `docs/SESSIONS.md` | Split: kept 2026-05-22→06-05 (32 sessions); archive footer pointer |
| `docs/SESSIONS-ARCHIVE.md` | **New** — bootstrap-era sessions 2026-05-06 → 05-21 (51 sessions) |

### Key decisions
- **Adapted the "2 months" archive heuristic to a 2026-05-22 bootstrap/day-2 boundary** — the whole log spans only ~1 month, so a literal 2-month cutoff would archive nothing. The chosen line is semantically meaningful (setup era vs operations) and yields a clean ~35/65 split.
- **Used Python splices (not the Edit tool) for the 199-line ROADMAP collapse and the SESSIONS split** — exact multi-hundred-line matches are error-prone; anchoring on unique header strings is robust and guarantees the lossless partition.
- **Presented the audit and asked the user to set execution scope before editing** — doc consolidation spans many files and some moves are hard to reverse; the repo's strict no-autonomous-change culture warranted a green light first.
- **Left nothing staged or committed** — per repo rules; the longhorn-doc move surfaces as delete + untracked `history/` until `/git-stage` detects it as a rename.

---

## 2026-06-05 — `longhorn-storagevlan-rollback`

### Goal
Abandon the Longhorn-on-storage-VLAN effort after 5 failed attempts and cleanly remove all of its scaffolding (Multus/whereabouts/NAD/Cilium override + the dead Talos `/28` routes), pivoting storage-VLAN replication to a future Rook-Ceph deployment.

### What we did
- **Mapped the full storage-VLAN footprint** and split it along a GitOps-vs-machine-config seam: everything under `kubernetes/` is self-pruning (delete file → Flux GCs the live object), while the `talconfig.yaml` routes are baked into each node's machine config and only leave via `genconfig` + apply.
- **Part A — GitOps teardown (commit `299904e`).** Deleted the entire `kube-system/multus/` stack (incl. the `448ed24` PR #703 whereabouts backport), the whereabouts OCIRepository source, the `longhorn-storage` NAD + its `longhorn-nad` Kustomization document, and reverted Cilium `cni.exclusive: false`. Refreshed the now-permanent `storageNetwork: ""` comment to point at the Ceph decision. Validated all touched kustomizations with `kubectl kustomize` before committing (+40/−504, overwhelmingly removal).
- **Part B — Talos route removal.** Stripped the cross-node `/28` static routes from all three `bond-storage` blocks in `talconfig.yaml` (kept the bond, `/24` addresses, jumbo MTU — Ceph reuses them). `genconfig` regenerated clean configs; a `--dry-run` apply proved each change is **"Applied configuration without a reboot"** — a live route withdrawal, overturning the doc's inherited assumption that route changes need reboots. Applied cp-01 → cp-03 → cp-02, each verified reboot-free with only the `/24` route remaining.
- **Monitored the reconcile.** Flux picked up `299904e`: multus DaemonSets gone, whereabouts HelmRelease Helm-uninstalled, NodeSlicePool GC'd (the `net-attach-def` CRD itself removed). Cilium Helm upgrade succeeded and rolled its agents to reclaim CNI exclusivity.
- **cp-02 hard-down (2nd occurrence) during the Cilium agent rollout.** cp-02 went `NotReady` — kubelet heartbeat stopped, 100% mgmt-network packet loss, Talos `apid` unreachable; same signature as 2026-06-02. cp-01/cp-03 took the identical Cilium restart cleanly. Confirmed etcd quorum held (2/3), recovered via user power-cycle, then watched all 5 Longhorn volumes rebuild cp-02 replicas back to `healthy` 3/3. Notably, the later reboot-free route apply did **not** trigger another down — narrowing the suspect to agent-restart/eBPF-reload stress.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/**` (9 files) | Deleted the entire Multus + whereabouts stack (incl. PR #703 backport) |
| `kubernetes/apps/kube-system/kustomization.yaml` | Dropped `./multus/ks.yaml` resource |
| `kubernetes/flux/meta/repos/oci/whereabouts-chart.yaml` | Deleted the whereabouts OCIRepository source |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Dropped `./whereabouts-chart.yaml` resource |
| `kubernetes/apps/longhorn-system/longhorn/nad/**` (2 files) | Deleted the `longhorn-storage` NAD |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | Removed the `longhorn-nad` Kustomization document |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Reverted `cni.exclusive: false` → exclusive default |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Refreshed `storageNetwork: ""` comment (abandoned → Ceph) |
| `talos/talconfig.yaml` | Removed cross-node `/28` routes; kept bond/addrs/MTU; updated comments |
| `docs/longhorn-storage-network.md` | Added "⛔ ABANDONED → Rook-Ceph" banner (history preserved) |

### Key decisions
- **Abandoned Longhorn-on-storage-VLAN rather than pursue Attempt 6.** The whereabouts chroot blocker was solved, but same-host iSCSI over ipvlan-L3 is structurally unsolvable here; Rook-Ceph's native `cluster_network` on `hostNetwork` OSDs sidesteps it entirely with no CNI.
- **Kept the `bond-storage` fabric (interface, `/24` addresses, jumbo MTU).** Removing only the ipvlan-L3-specific `/28` routes leaves the storage VLAN clean and Ceph-ready.
- **Dry-ran the Talos apply before committing to it.** Confirming the route removal was reboot-free eliminated the staggered-reboot ceremony and, crucially, the exposure to cp-02's reboot fragility.
- **Recorded the cp-02 recurrence as a real data point** (now 2-for-2 with network-stack reconciles, both during agent churn, never during a live config edit) in the open `cp02-outage-investigation`.

---

## 2026-06-02 — `longhorn-storagenetwork-attempt5`

### Goal
Backport the unreleased upstream whereabouts fix to break the multus-chroot node-name blocker, validate per-node `node_slice_size` IPAM in isolation, then attempt the Longhorn `storageNetwork` flip — which failed on the same-host iSCSI path and was rolled back, restoring service.

### What we did
- **Pinned the Attempt-4 blocker to upstream.** Read the v0.9.3 whereabouts source: `getNodeName` resolves node identity as `$NODENAME` env → `<configuration_path>/nodename` file → `/etc/hostname`. The CNI plugin runs in the multus `chroot:/hostroot`, so it never inherits the daemon's `NODENAME` env and Talos has no `/etc/hostname` → nil-pointer panic. Exact match for open upstream issue **#518**; the fix is PR **#703**, which **merged to `master` on 2026-06-02 but is unreleased** (latest release v0.9.3 predates it) — so no chart bump was available.
- **Backported PR #703 (`448ed24`, KEPT).** Replaced the insufficient `/etc/hostname` emptyDir postRenderer with a DaemonSet `args` override that, after `install-cni.sh`, injects `"configuration_path": "/etc/cni/net.d/whereabouts.d"` into the flatfile `whereabouts.conf` and writes `$NODENAME` to `/host/etc/cni/net.d/whereabouts.d/nodename`. Both land in the host CNI dir (writable on Talos, unlike `/etc/hostname`). Sharp edge confirmed from source: `configuration_path` must live in the flatfile, **not** the NAD — `GetFlatIPAM` treats a NAD value as a *file* and `io.ReadAll`s a directory.
- **Validated in isolation (gate passed).** All 3 whereabouts pods rolled clean (no panic); verified the on-host `nodename` + `configuration_path` files via `talosctl read`; throwaway probe pods pinned per node each pulled their `/28` slice's first IP through the chroot — cp-01 `10.200.0.65`, cp-02 `.81`, cp-03 `.97` — the exact path that panicked in Attempts 3–4.
- **Quiesced + flipped (`d6be5da`).** Suspended HelmReleases `pgadmin`/`waha`/`kube-prometheus-stack`, scaled Deployments to 0, patched Prometheus/Alertmanager **CR** replicas to 0; all 5 volumes detached. Set `storageNetwork: "kube-system/longhorn-storage"`. Flux reconciled; instance-managers recreated with `lhnet1` attached at the correct per-node `/28` IPs (`.65`/`.81`/`.97`).
- **FAILED on same-host iSCSI.** All 5 engines co-located on cp-03 stuck `starting`; volumes cycled `attaching ↔ detaching`. Host routing showed the plan's load-bearing assumption was wrong: the kernel does **not** add a `/32` route to a local pod's ipvlan IP (the slave lives in the pod netns), and ipvlan L3 suppresses ARP — so a node cannot reach a pod's storage IP on its **own** host. Cross-node `/28` routes worked; same-host is structurally broken in this design (same wall as Attempts 1–2).
- **Rolled back (`f719cef`) and recovered service.** `git revert d6be5da` + push set `storageNetwork: ""`. Longhorn cleared the setting (`value=""`, `applied=false`) but deadlocked — the old IMs kept `lhnet1` and volumes never cleanly detached. Broke the deadlock by deleting the instance-manager pods (user-run; the classifier blocked agent attempts at the live setting patch / HR suspend / IM deletion as out-of-band infra changes). Recreated IMs came up clean; all 5 volumes re-attached on the pod network (2 `healthy`, 3 `degraded` rebuilding at session end); consumers recovered.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | Replaced `/etc/hostname` emptyDir postRenderer with PR #703 backport — `configuration_path` in flatfile + `nodename` file via DaemonSet `args` override — `448ed24` (**kept**) |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Enabled then reverted `storageNetwork` — `d6be5da`, `f719cef` (net unchanged) |
| `docs/longhorn-storage-network.md` | Added Attempt 5 section then reverted with the flip — `d6be5da`, `f719cef` (net unchanged; **re-add pending**) |

### Key decisions
- **Backported the unreleased PR #703** (~5 lines via postRenderer) rather than wait for a whereabouts release or jump to Ceph — it was the sole blocker. Tracked to remove when a release > 0.9.3 ships it.
- **Two-phase gated rollout** — validating IPAM in isolation before the disruptive flip is exactly why the flip's failure was unambiguously attributable to same-host routing, not the CNI fix.
- **Rolled back via Git, not a live patch** — the classifier (correctly) blocked out-of-band mutation of shared Longhorn infra; the user ran the IM-pod deletion to break Longhorn's detach deadlock.
- **same-host iSCSI over ipvlan L3 remains unsolved** — the `/28`+static-routes scheme only fixes cross-node. Next options: host-side ipvlan shim (route to local pod IPs), ipvlan L3S, or Rook-Ceph (native dual-network). The Attempt-5 writeup must be re-added to `docs/longhorn-storage-network.md` (lost in the revert).

---

## 2026-06-02 — `longhorn-storagenetwork-attempt4`

### Goal
Re-enable Longhorn `storageNetwork` over the ipvlan-L3 storage VLAN (attempt 4) by fixing the whereabouts `/etc/hostname` panic and the multus OOM crash-loop — ultimately blocked by a multus-chroot root cause and reverted, with recovery from a mid-migration cp-02 hard-down.

### What we did
- **whereabouts `/etc/hostname` fix (`3c624a8`)**: the chart has no `initContainers` hook, so injected one via a Flux **`postRenderers`** Kustomize patch on the HelmRelease. First cut wrote to a hostPath host `/etc` and failed (`Read-only file system`); reworked to an `emptyDir` + `subPath` populating the daemon pod's own `/etc/hostname`. Verified all 3 whereabouts pods healthy with correct per-node hostname (v3 deployed).
- Unstuck a Flux/Helm deadlock: the first render wedged the release in `pending-upgrade` (helm `--wait` on a crash-looping pod); restarting the helm-controller pod cleared the stale operation and applied the corrected render.
- **multus OOM fix (`49ea52c`)**: discovered `kube-multus-ds` on cp-02 in `CrashLoopBackOff` (22 restarts, `OOMKilled` exit 137) — the 50Mi limit couldn't service the burst of queued CNI ADD requests, blocking ALL pod sandbox creation on the node and degrading every Longhorn volume. Raised limit to 256Mi, dropped the CPU limit. cp-02 recovered, instance-manager started, all 5 volumes rebuilt to `healthy` 3/3.
- **storageNetwork re-enable (`0edb316`) + quiesce**: suspended the consuming workloads' HelmReleases and scaled consumers to 0 (patched Prometheus/Alertmanager **CR** `replicas`, not the operator-managed StatefulSets); volumes detached cleanly.
- **Definitive blocker found**: re-enabling made instance-managers request `lhnet1` and IP allocation **still panicked** on `/etc/hostname`. Root cause: the whereabouts **CNI plugin** (not the daemon pod) runs inside the multus thick-daemon's **`chroot:/hostroot`**, so it reads the **host's** `/etc/hostname` — absent on Talos, read-only `/etc`. The daemon-pod fix never reaches that context.
- **Reverted (`ad1666a`)** to restore service. Cleared the setting, deleted wedged instance-manager pods carrying the stale `lhnet1` annotation, resumed HelmReleases.
- **cp-02 hard-down incident**: during the migration thrash cp-02 went unreachable on BOTH NICs (talosctl `no route to host`, kubelet heartbeat stopped 15:32:45). User power-cycled; cp-02 rejoined cleanly and volumes rebuilt to `healthy` 3/3. Post-reboot `dmesg` held only the current boot — pre-crash logs lost (ring buffer reset). Root cause deferred to a tracked follow-up; multus held at 256Mi through the reboot with only 1 restart.
- Updated `docs/longhorn-storage-network.md` with the Attempt 4 outcome, chroot root cause, recovery procedure, and Attempt 5 research direction; saved an open cp-02-outage investigation note to persistent memory.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | Added `postRenderers` patch injecting `/etc/hostname` initContainer (emptyDir + subPath) — `3c624a8` |
| `kubernetes/apps/kube-system/multus/app/multus-daemonset.yaml` | Raised daemon memory limit 50Mi→256Mi, dropped CPU limit — `49ea52c` |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Re-enabled then reverted `storageNetwork`; comment documents the multus-chroot blocker — `0edb316`, `ad1666a` |
| `docs/longhorn-storage-network.md` | Documented Attempt 4 outcome, chroot root cause, cp-02 incident, recovery procedure, Attempt 5 direction (uncommitted) |

### Key decisions
- Used Flux `postRenderers` rather than chart values — the whereabouts chart exposes no `initContainers`/`extraVolumes` hooks.
- Targeted the daemon pod's own `/etc/hostname` (emptyDir+subPath) because the host `/etc` is read-only on Talos and `hostNetwork` shares only the net namespace — though this later proved insufficient for the CNI-plugin allocation path.
- Sequenced as separate pushes (multus OOM fix validated to full health *before* the storageNetwork re-enable) so a risky change wasn't coupled to a still-recovering node.
- Reverted rather than pushing forward: the chroot blocker is design-level (needs Option B node-identity-without-host-hostname or Option C per-node IPPools), not a live-cluster guess — restore service first.
- cp-02 root cause deliberately deferred: pre-crash kernel logs were unrecoverable post-reboot, so investigation is tracked separately rather than blocking recovery.

---

## 2026-06-02 — `postgres-backup-monitoring`

### Goal
Add a liveness probe and Prometheus alerting rules to the postgres-backup-local CronJob for container-level health enforcement and cluster-level failure detection.

### What we did
- Added `HEALTHCHECK_PORT: "8080"` env var to the backup container so it exposes an HTTP health endpoint on port 8080
- Wired a custom liveness probe (`httpGet /` on port 8080) with `initialDelaySeconds: 7200` (2h) to match the backup window, `failureThreshold: 1`, `periodSeconds: 60` — tight dead-man's switch at the container layer
- Created `prometheusrule.yaml` with two alerts:
  - `PostgresBackupMissed` — dead-man's switch using `kube_cronjob_status_last_successful_time`; fires (critical) if no successful backup in 25h or the CronJob disappears entirely
  - `PostgresBackupJobFailed` — fires (warning) when any `postgres-backup-local-*` Job records a failure; auto-resolves when the failed Job is GC'd
- Registered the new PrometheusRule in `kustomization.yaml`
- Committed as `8d12e96`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/helmrelease.yaml` | Added `HEALTHCHECK_PORT: "8080"` env var and custom liveness probe |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/kustomization.yaml` | Added `prometheusrule.yaml` as a resource |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/prometheusrule.yaml` | New file — PrometheusRule with `PostgresBackupMissed` and `PostgresBackupJobFailed` alerts |

### Key decisions
- `initialDelaySeconds: 7200` matches the backup duration window; setting it shorter would kill the pod mid-backup
- Alert threshold is 90000s (25h not 24h) to absorb slight CronJob scheduling drift without false positives
- Used `kube_cronjob_status_last_successful_time` from kube-state-metrics (already present) rather than adding custom metrics to the backup container — zero instrumentation overhead

---

## 2026-05-31 — `multus-nad-talos-setup`

### Goal
Deploy Multus CNI + whereabouts IPAM, create a macvlan NAD on the storage VLAN, rename storage bonds to `bond-storage` across all 3 Talos nodes, and enable Longhorn's `storageNetwork` setting to move engine↔replica traffic off the Cilium pod network.

### What we did
- Continued from compacted context (previous session hit context limit mid-implementation); completed all Phase 2 manifests — vendored Multus thick DaemonSet v4.2.4 split into 4 files (CRD, RBAC, ConfigMap, DaemonSet), whereabouts HelmRelease with `chartRef` → new `whereabouts-chart` OCIRepository (tag `0.9.3`), configMapGenerator + kustomizeconfig for values
- Extended `longhorn/ks.yaml` to multi-doc: added `longhorn-nad` Kustomization with `dependsOn: [multus, longhorn]`; added `nad/storage-nad.yaml` macvlan NAD on master `bond-storage`, whereabouts range `10.200.0.64/26`, MTU 9000
- Committed and pushed `82bc07a` (feat(longhorn): deploy Multus CNI and storage VLAN network isolation); monitored Flux reconciliation live via MCP tools
- **Three consecutive image fixes** during live reconciliation monitoring:
  - `docker.io/containernetworking/plugins:v1.9.1` — tag does not exist; `containernetworking/plugins` never publishes to Docker Hub
  - `ghcr.io/k8snetworkplumbingwg/plugins:v1.6.2` — pulled successfully but image only contains k8snetworkplumbingwg extra plugins (no macvlan/ipvlan)
  - `ghcr.io/siderolabs/cni:v1.13.0` directly — correct binaries confirmed via `crane export`; image is distroless (no shell), `sh -c "cp ..."` fails with `exec: "sh": not found`
  - **Final fix** (`8301702`): used K8s `imageVolume` (beta in 1.36, confirmed available via dry-run) to mount `siderolabs/cni:v1.13.0` as read-only volume + `busybox` init container to copy macvlan/ipvlan; binary paths `/opt/cni/bin/macvlan` and `ipvlan` confirmed via `crane export`
- Monitored full reconciliation to green: whereabouts 3/3, Multus DaemonSet 3/3 Running, NAD `longhorn-storage` created in `longhorn-system`, Kustomizations `multus` and `longhorn-nad` both `Applied revision: 8301702`
- Verified macvlan + ipvlan + multus-shim binaries present in `/opt/cni/bin/` on all nodes via `talosctl ls`
- Applied Talos machine configs to all 3 nodes (`task talos:apply IP=10.60.0.20X`) — all applied live without reboot; `bond-storage` with `10.200.0.201/202/203` confirmed live on all nodes via `talosctl get addresses`
- Phase 4: added `storageNetwork: "longhorn-system/longhorn-storage"` to Longhorn values; verified all 8 PVCs are RWO (no RWX detach constraint); ready to commit/push

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Renamed storage bonds: bond0→bond-storage (cp-01, cp-02), bond1→bond-storage (cp-03) |
| `kubernetes/flux/meta/repos/oci/whereabouts-chart.yaml` | New OCIRepository for `ghcr.io/k8snetworkplumbingwg/whereabouts-chart:0.9.3` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added whereabouts-chart entry |
| `kubernetes/apps/kube-system/kustomization.yaml` | Added `./multus/ks.yaml` |
| `kubernetes/apps/kube-system/multus/ks.yaml` | New Kustomization; dependsOn cilium; healthChecks DaemonSet + whereabouts HelmRelease |
| `kubernetes/apps/kube-system/multus/app/kustomization.yaml` | New; configMapGenerator for whereabouts values |
| `kubernetes/apps/kube-system/multus/app/multus-crd.yaml` | New; vendored NetworkAttachmentDefinition CRD from Multus v4.2.4 |
| `kubernetes/apps/kube-system/multus/app/multus-rbac.yaml` | New; vendored ClusterRole/ClusterRoleBinding/ServiceAccount |
| `kubernetes/apps/kube-system/multus/app/multus-configmap.yaml` | New; vendored multus-daemon-config ConfigMap |
| `kubernetes/apps/kube-system/multus/app/multus-daemonset.yaml` | New; vendored DaemonSet v4.2.4-thick; imageVolume pattern for CNI plugin install |
| `kubernetes/apps/kube-system/multus/app/whereabouts-helmrelease.yaml` | New; HelmRelease using chartRef OCIRepository |
| `kubernetes/apps/kube-system/multus/app/helm/whereabouts-values.yaml` | New; NoExecute toleration + resource limits |
| `kubernetes/apps/kube-system/multus/app/helm/kustomizeconfig.yaml` | New; nameReference for ConfigMap hash propagation |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | Extended to multi-doc; added longhorn-nad Kustomization |
| `kubernetes/apps/longhorn-system/longhorn/nad/kustomization.yaml` | New |
| `kubernetes/apps/longhorn-system/longhorn/nad/storage-nad.yaml` | New macvlan NAD; master bond-storage; whereabouts 10.200.0.64/26 |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Added replicaReplenishmentWaitInterval 900s (committed); storageNetwork setting (pending commit) |

### Key decisions
- **imageVolume pattern for distroless source**: K8s 1.36 `imageVolume` (beta) mounts a container image filesystem as read-only; lets `busybox` copy specific binaries from `siderolabs/cni` without needing a shell in the source image — cleaner than runtime GitHub downloads
- **siderolabs/cni as CNI plugin source**: Talos's own CNI bundle matches running Talos version; `crane export` confirmed macvlan+ipvlan at `/opt/cni/bin/`; `containernetworking/plugins` never publishes images; `k8snetworkplumbingwg/plugins` is extra plugins only
- **macvlan over ipvlan**: Both work on bare metal; macvlan is the Longhorn-documented default; ipvlan is preferred for cloud/hypervisor environments with MAC spoofing enforcement (not applicable here)
- **`storageNetwork` affects more than RWX**: Longhorn chart comment says "mounting RWX volumes" but the setting also attaches secondary interfaces to instance-manager pods (all volume I/O); all cluster PVCs are RWO so no RWX detach constraint applies
- **No reboot required for bond rename**: Talos applies network interface name changes live via its network controller; all 3 nodes accepted the bond-storage rename without rebooting

---

## 2026-05-30 — `hardware-monitoring`

### Goal
Audit hardware sensor coverage, then deploy Grafana (with pre-built dashboards), a privileged `smartctl-exporter` DaemonSet for SMART disk health, and PrometheusRules for hardware temperature alerting.

### What we did
- Audited hardware monitoring coverage: confirmed `prometheus-node-exporter` DaemonSet already collects CPU/mem/disk/network; queried `talosctl ls /sys/class/hwmon` across all 3 nodes — all key temperature drivers already auto-loaded (`coretemp` on cp-01/cp-02, `k10temp` on cp-03 MS-A2, `nvme` × 2 per node, `nct6686` super-I/O on M920Q, `ixgbe` NIC on cp-02)
- Sampled live sensor readings: cp-01 CPU 49°C, cp-02 CPU 38°C, cp-03 AMD Tctl 69°C (elevated — mini-PC chassis), NVMe composite 44–53°C; identified `nct6686` Thermistor 7 at 127°C as a phantom (unconnected thermistor input, not a real alert)
- Researched bykaj reference: their `smartctl-exporter` ScrapeConfig points to `${NAS_HOST}:9633` — not a K8s DaemonSet; bykaj runs Talos VMs on Proxmox so the hypervisor layer covers disk health; bare-metal deployment requires an in-cluster DaemonSet instead
- Enabled Grafana in kube-prometheus-stack: 5 Gi Longhorn PVC, `Recreate` strategy, admin password via ExternalSecret from 1Password `grafana` item, `forceDeployDashboards: true`, sidecar searching all namespaces, `root_url` set for proper redirect handling
- Added `grafana.${DOMAIN_CLUSTER}` HTTPRoute on `envoy-internal` pointing at `kube-prometheus-stack-grafana:80`
- Deployed `prometheus-smartctl-exporter` as a privileged DaemonSet (chart `0.16.1`, app `v0.14.0`): chart hardcodes `privileged: true` + `/dev` hostPath mount, auto-scans NVMe devices, `observability` namespace already has `pod-security.kubernetes.io/enforce: privileged`; built-in SMART health PrometheusRules enabled (media errors, critical warning, spare threshold, device status), SMART temperature rule disabled in favour of hwmon
- Created `hardware-temps` PrometheusRule: CPU warning >80°C / critical >90°C scoped to `coretemp.*|k10temp.*` (naturally excludes nct6686 phantom); NVMe warning >65°C / critical >75°C via `nvme.*` hwmon chip

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/smartctl-exporter.yaml` | New OCIRepository for `prometheus-community/charts/prometheus-smartctl-exporter:0.16.1` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `smartctl-exporter.yaml` resource |
| `kubernetes/apps/observability/smartctl-exporter/ks.yaml` | New Kustomization; `dependsOn: kube-prometheus-stack` |
| `kubernetes/apps/observability/smartctl-exporter/app/kustomization.yaml` | New; ConfigMapGenerator for values |
| `kubernetes/apps/observability/smartctl-exporter/app/helmrelease.yaml` | New HelmRelease using smartctl-exporter OCIRepository |
| `kubernetes/apps/observability/smartctl-exporter/app/helm/values.yaml` | New; ServiceMonitor + SMART health rules enabled, temperature rule disabled |
| `kubernetes/apps/observability/kustomization.yaml` | Added `smartctl-exporter/ks.yaml` resource |
| `kubernetes/apps/observability/kube-prometheus-stack/app/externalsecret.yaml` | New; pulls `ADMIN_PASSWORD` from 1Password `grafana` → `grafana-admin-secret` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Grafana enabled; persistence, admin secret, dashboard sidecar, tolerations, `root_url` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml` | Added `grafana.${DOMAIN_CLUSTER}` HTTPRoute |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Added `externalsecret.yaml` and `prometheusrules` directory |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml` | New PrometheusRule: CPU + NVMe temperature alerts |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/kustomization.yaml` | New; resources the hardware-temps rule |

### Key decisions
- **Chip-scoped temperature alerts (`coretemp.*|k10temp.*`)** rather than a broad `node_hwmon_temp_celsius > N` — avoids nct6686 Thermistor 7 phantom reading (127°C) triggering false critical alerts on M920Q nodes without needing an explicit exclusion filter
- **SMART temperature rule disabled** in smartctl-exporter PrometheusRules — NVMe SMART temperatures are sampled by the drive firmware and less precise than kernel hwmon; hwmon composite temp (`nvme.*`) is more representative for alerting
- **`Recreate` deployment strategy for Grafana** — Longhorn PVC is `ReadWriteOnce`; a rolling update would try to attach the volume to two pods simultaneously and stall

---

## 2026-05-30 — `jumbo-frames-storage-vlan`

### Goal
Benchmark storage VLAN throughput between Talos nodes and TrueNAS, then implement MTU 9000 jumbo frames across all storage bonds and Cilium to reduce switch incast retransmits.

### What we did
- Ran iperf3 benchmarks from Kubernetes pods (pod-network and host-network) against TrueNAS (10.200.0.41); demonstrated LACP layer3+4 hashing behaviour and why all 4 `-P 4` streams hash-collided onto one bond member (port numbers differing only in low 6 bits, discarded by `>> 6` shift)
- Established that host-network pods bound to the storage VLAN IP (`-B 10.200.0.201`) bypass Cilium overlay and measure the raw bond path: single stream 9.42 Gbps vs 5.49 Gbps through Cilium (40% overhead from encapsulation suppressing CUBIC cwnd growth)
- Showed 16-stream test at MTU 1500 yielded 13.4 Gbps with 181,203 retransmits — identified switch incast (too many packets per second overflowing port buffers) as the binding constraint, not LACP distribution
- Implemented MTU 9000: updated `talconfig.yaml` storage bonds (cp-01 `bond0`, cp-02 `bond0`, cp-03 `bond1`) from `mtu: 1500` to `mtu: 9000`, removed TODO comments; added `MTU: 9000` to Cilium values and corrected wrong interface-name comment (had cp-01/cp-03 layout swapped); ran `talhelper genconfig`
- Applied configs node-by-node with MTU and Ready verification between each; cp-01 live with no reboot; cp-02 rebooted unexpectedly (M920Q thermal protection, BIOS hard power-cut leaving no dmesg trace — unrelated to config change), recovered and MTU confirmed; cp-03 applied without reboot
- Held cp-03 apply while cp-02 was offline to preserve 2/3 etcd quorum; diagnosed link-selector warnings as cosmetic (LACP bond MAC propagates to both slaves, alias controller skips — bond operational)
- Post-MTU 16-stream test: 14.2 Gbps, 40,086 retransmits (−78%); single stream 9.90 Gbps; identified BBR congestion control as next step to reduce remaining CUBIC incast backoff

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Changed storage bond mtu 1500→9000 on cp-01 (bond0), cp-02 (bond0), cp-03 (bond1); removed TODO comments |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | Added `MTU: 9000`; corrected interface layout comment (had cp-01 and cp-03 swapped) |

### Key decisions
- **Host-network pods with `-B <storage-IP>`** for raw bond measurements — pod-network path through Cilium suppresses CUBIC cwnd growth and is not representative of NFS storage performance
- **Explicit `MTU: 9000` in Cilium values** — Cilium native-routing mode auto-detects MTU from the default-route interface (management NIC, 1500 MTU), so pod veth interfaces would remain at 1500 even after bond change without an explicit override
- **Node-by-node apply with etcd quorum guard** — never applied cp-03 while cp-02 was down; a second simultaneous failure would have dropped etcd to 1/3 and made the cluster API read-only

---

## 2026-05-29 — `postgres-nfs-backup`

### Goal
Deploy and verify a daily `pg_dumpall`-based NFS backup CronJob for the `postgres-v17` cluster, writing to TrueNAS over the storage VLAN.

### What we did
- Confirmed ExternalSecret `dataFrom+rewrite` migration was fully complete: verified all 12 cluster ExternalSecrets `SecretSynced: True` via `kubectl get externalsecrets -A`; updated ROADMAP.md to move the item to Completed
- Designed TrueNAS NFS configuration: dedicated dataset `/mnt/tank/Cluster/cloudnative-pg` on `tank` pool; NFS share on storage VLAN via `bond1` (10.200.0.41/24); dataset `chown 4000:4000` for non-root container; `maproot: root` not needed since UID 4000 passes through numerically without a named user
- Built `postgres-backup-local` app-template v5 CronJob: `POSTGRES_CLUSTER: "TRUE"` for `pg_dumpall`, `POSTGRES_DB: postgres` to satisfy image validation, `POSTGRES_EXTRA_OPTS: "-c"` only (pg_dumpall doesn't accept `-Z` or `-C`); daily schedule with 7d/4w/6m retention; runs as UID 4000 (`runAsNonRoot: true`); `enableServiceLinks: false`; `ttlSecondsAfterFinished: 43200`
- Added Flux Kustomization to `cloudnative-pg/ks.yaml` as third doc with `dependsOn: cloudnative-pg-cluster`; reuses existing `cloudnative-pg-secret` rather than a new ExternalSecret
- Debugged three live failures: (1) `SYN_SENT` — TrueNAS NFS not bound to bond1 interface; (2) `database "backups" does not exist` — `POSTGRES_DB: "*"` glob-expands to `/backups` mount dir in script working dir; (3) `invalid option -- 'Z'` — pg_dumpall doesn't accept `-Z6`
- Fixed all three issues iteratively via live `kubectl patch cronjob` + manual job triggers; verified `Completed` pod with correct symlinks (`daily/`, `weekly/`, `monthly/`, `last/`) on TrueNAS
- Added restore drill roadmap entry with step-by-step `pg_dumpall` restore procedure and drill checklist

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Added `postgres-backup-local` Kustomization as third doc |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/helmrelease.yaml` | Created: app-template v5 CronJob with NFS persistence, UID 4000, pg_dumpall config |
| `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/kustomization.yaml` | Created: Kustomize entry-point |
| `docs/ROADMAP.md` | Marked ExternalSecret migration complete; marked NFS backup item ✅ with gotchas; added restore drill entry |

### Key decisions
- **Storage VLAN (10.200.0.41) over management VLAN** — TrueNAS has bond1 on the same storage fabric as the node storage bonds; isolates backup traffic from kube-apiserver/etcd on the management NIC
- **UID 4000 (non-root) over root** — matches both reference implementations; requires one `chown 4000:4000` on TrueNAS but eliminates rootless-root in the database namespace; numeric UID works without a named user on TrueNAS
- **`POSTGRES_CLUSTER: "TRUE"` over `POSTGRES_DB: "*"`** — `*` glob-expands to the NFS mount directory name in the script's working directory; `pg_dumpall` is also future-proof for new databases added to the shared cluster
- **Reuse `cloudnative-pg-secret`** over a new ExternalSecret — credentials already present in the `database` namespace; avoided duplicating the same 1Password fields

---

## 2026-05-29 — `pgadmin-deploy`

### Goal
Deploy pgAdmin as a web-based admin UI for the shared `postgres-v17` CNPG cluster, living in the `database` namespace alongside the cluster it manages.

### What we did
- Discussed CNPG pod distribution: established that `podAntiAffinityType: required` prevents initial co-location but does not change node-failure recovery behaviour because `openebs-hostpath` PVCs are node-local regardless; the PVC's own node-affinity is the binding scheduling constraint on failure
- Discussed CNPG automatic failover: confirmed the operator promotes the most up-to-date standby (synchronous standby preferred), re-targets the `postgres-v17-rw` Service, and rejoins the old primary as standby via `pg_rewind` once its node recovers — no manual intervention
- Researched pgAdmin patterns on kubesearch.dev and studied both `tmp/home-ops-bykaj` and `tmp/home-ops.old` reference implementations; chose the `dpage/pgadmin4` image with `ghcr.io/home-operations/k8s-sidecar` initContainer pattern
- Created pgAdmin Kustomization with `dependsOn: cloudnative-pg-cluster + onepassword-store`; kept in `database` namespace alongside CNPG (single namespace simpler for future NetworkPolicy rules)
- HelmRelease (app-template v5): initContainer creates per-user storage folder and seeds `.pgpass` with correct permissions (chmod 600); Longhorn 2Gi PVC for config data so pod can reschedule across nodes after failure; startup + liveness/readiness probes on `/misc/ping`; `PGADMIN_REPLACE_SERVERS_ON_STARTUP: "True"` makes server config declarative
- ExternalSecret pulls from two 1Password items: `pgadmin` (→ `PA_` prefix, email + password) and `cloudnative-pg` (→ `DB_` prefix, reusing existing superuser fields); template produces `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`, `pgpass`, and `servers.json` keys in a single Secret
- `servers.json` hardcodes `postgres-v17-rw.database.svc.cluster.local` as the connection target with `sslmode: prefer` and `passfile: /.pgpass`; no Flux substitution variables needed
- Compared old reference initContainer (function-based, multi-user, backup symlink, `/tmp/secrets/pgpass`) vs current implementation (inline, single-user, `/tmp/secrets/.pgpass` via subPath); all differences are intentional simplifications for single-admin home lab without backup volumes
- HTTPRoute on `envoy-internal` → `pgadmin.${DOMAIN_CLUSTER}` (LAN-only); standalone `httproute.yaml` following cluster convention

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/database/pgadmin/ks.yaml` | Created: Flux Kustomization; dependsOn cloudnative-pg-cluster + onepassword-store |
| `kubernetes/apps/database/pgadmin/app/kustomization.yaml` | Created: Kustomize entry-point |
| `kubernetes/apps/database/pgadmin/app/helmrelease.yaml` | Created: app-template v5 with initContainer, Longhorn PVC, probes, envFrom |
| `kubernetes/apps/database/pgadmin/app/externalsecret.yaml` | Created: pulls pgadmin + cloudnative-pg items; produces pgpass + servers.json |
| `kubernetes/apps/database/pgadmin/app/httproute.yaml` | Created: HTTPRoute on envoy-internal for pgadmin.${DOMAIN_CLUSTER} |
| `kubernetes/apps/database/kustomization.yaml` | Added `./pgadmin` resource |

### Key decisions
- **`database` namespace over `tools`**: co-location simplifies future NetworkPolicy allow-rules (pgAdmin is inside the namespace it talks to); easy to move later if a general `tools` namespace emerges
- **Longhorn PVC (not openebs-hostpath)**: pgAdmin is a single-pod stateless-ish app — Longhorn allows pod to reschedule to any node after a node failure, unlike openebs-hostpath which is node-local
- **No OIDC/OAuth2**: dropped from references (requires Authentik, not deployed); `internal` auth only; can be layered on later
- **Hardcoded DB hostname in ExternalSecret template**: avoids Flux substitution variables in the ESO template layer; `postgres-v17-rw.database.svc.cluster.local` is stable and doesn't need to be parameterised
- **`podAntiAffinityType: required` on CNPG cluster** (committed in previous session): hard placement guarantee at initial scheduling; no effect on recovery since openebs-hostpath PVC node-affinity is the real binding constraint

---

## 2026-05-29 — `cloudnative-pg-deploy`

### Goal
Deploy CloudNativePG operator and a shared 3-instance PostgreSQL 17 cluster as new database infrastructure for the home-lab cluster.

### What we did
- Researched CNPG community patterns on kubesearch.dev and studied the `tmp/home-ops-bykaj` reference (operator/cluster/barman-cloud/postgres-backup-local structure, ObjectStore CR, ExternalSecret pattern, PrometheusRules, variable-substituted cluster naming for major-version upgrades)
- Decided on a single shared `postgres-v17` cluster (not per-app) and deferred S3/barman-cloud backup to a future session; cluster has HA via 3-replica streaming replication with no PITR until backup is wired in
- Verified current chart version `0.28.2` via `gh api` GHCR query; added OCIRepository to `flux/meta/repos/oci/`
- Created `database` namespace and top-level kustomization; wired into `kubernetes/apps/kustomization.yaml`
- Created multi-doc `ks.yaml` following CLAUDE.md operator+CRD pattern: `cloudnative-pg-operator` (wait+healthChecks, dependsOn cert-manager) and `cloudnative-pg-cluster` (dependsOn operator + onepassword-store)
- CNPG operator HelmRelease: `crds.create: true`, `monitoring.podMonitorEnabled: true`, Grafana dashboard enabled; PrometheusRule with 7 alert rules (replication lag, XID age, WAL archiver failure, deadlocks, backend waits, long transactions, replica WAL receiver down)
- `postgres-v17` Cluster CR: 3 instances, `openebs-hostpath` 20Gi, `initdb` bootstrap (fresh cluster), `enablePodMonitor: true`, synchronous replication (any 1 standby), `enablePDB: false` (CNPG issue #2570)
- ExternalSecrets updated to CONVENTIONS.md pattern: `dataFrom.extract` + `rewrite: CNPG_$1` + `template` mapping to CNPG's expected `username`/`password` keys; 1Password fields prefix-free (`SUPER_USER`, `SUPER_PASS`, `BOOTSTRAP_USER`, `BOOTSTRAP_PASS`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/cloudnative-pg.yaml` | Created: OCIRepository for CNPG chart, tag 0.28.2, Renovate-tracked |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added cloudnative-pg.yaml resource |
| `kubernetes/apps/kustomization.yaml` | Added `./database` resource |
| `kubernetes/apps/database/namespace.yaml` | Created: Namespace database |
| `kubernetes/apps/database/kustomization.yaml` | Created: aggregates namespace.yaml + cloudnative-pg |
| `kubernetes/apps/database/cloudnative-pg/ks.yaml` | Created: multi-doc Kustomizations (operator + cluster) |
| `kubernetes/apps/database/cloudnative-pg/kustomization.yaml` | Created: includes ks.yaml |
| `kubernetes/apps/database/cloudnative-pg/operator/app/helmrelease.yaml` | Created: CNPG operator HelmRelease with monitoring |
| `kubernetes/apps/database/cloudnative-pg/operator/app/prometheusrule.yaml` | Created: 7 PrometheusRule alert rules |
| `kubernetes/apps/database/cloudnative-pg/operator/app/kustomization.yaml` | Created |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml` | Created: postgres-v17 Cluster CR, 3 instances, openebs-hostpath |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/externalsecret.yaml` | Created: superuser + bootstrap ExternalSecrets, rewrite+template pattern |
| `kubernetes/apps/database/cloudnative-pg/cluster/app/kustomization.yaml` | Created |

### Key decisions
- `openebs-hostpath` over Longhorn for PostgreSQL storage: CNPG replicates data across 3 pods itself; Longhorn would add double-replication with I/O amplification and no reliability benefit
- S3 backup (barman-cloud plugin) deferred: user chose HA-only for initial deployment; PITR can be layered on without recreating the cluster
- `enablePDB: false` following bykaj reference (CNPG issue #2570): default PDB can block Talos node drain during upgrades on a 3-control-plane-only cluster
- Chart pinned at `0.28.2` (verified via `gh api` GHCR query) rather than guessing a version; Renovate tracks future releases via `datasource=docker` comment

---

## 2026-05-29 — `external-services-truenas`

### Goal
Audit bykaj's external-services pattern, evaluate envoy-internal reuse vs a dedicated envoy-services gateway, document the decision, and implement the pattern for TrueNAS as the first LAN resource proxy.

### What we did
- Audited `bykaj/home-ops` external-services: identified three routing variants (plain HTTP via `HTTPRoute`, TLS passthrough via `TLSRoute`, FQDN-based via Envoy `Backend` CRD with ConsistentHash LB for Proxmox session affinity); noted EndpointSlice label requirements (`kubernetes.io/service-name`, `endpointslice.kubernetes.io/managed-by`) and a port mismatch in `proxmox-backup-server`
- Evaluated dedicated `envoy-services` gateway vs reusing `envoy-internal`; decided on reuse — no TLS passthrough or IP-level ACL requirements at this stage, and adding a `TLS: Passthrough` listener to `envoy-internal` would widen its surface area unnecessarily
- Added Scenario 4 (LAN resource proxy) to `docs/CLUSTER.md` with a complete 3-file YAML example and `external-services/` directory convention; added forward reference to ROADMAP.md for TLS passthrough path
- Added "Dedicated `envoy-services` Gateway (Future)" to `docs/ROADMAP.md` under Researched Patterns with three concrete migration triggers (IP-level ACLs, TLS passthrough, scale) and cost estimate (+3 Envoy pod replicas, +1 CiliumLB IP)
- Created `kubernetes/apps/network/external-services/truenas/`: `EndpointSlice` → `10.10.0.41:8080`, headless `Service` (no selector), `HTTPRoute` on `envoy-internal` → `truenas.${DOMAIN_CLUSTER}`; top-level `ks.yaml` with `targetNamespace: network` and `dependsOn: envoy-gateway-config`
- Wired `./external-services/ks.yaml` into `kubernetes/apps/network/kustomization.yaml`

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | Added Scenario 4: LAN resource proxy with 3-file YAML example and envoy-services cross-reference |
| `docs/ROADMAP.md` | Added Dedicated envoy-services Gateway (Future) under Researched Patterns |
| `kubernetes/apps/network/kustomization.yaml` | Added `./external-services/ks.yaml` resource |
| `kubernetes/apps/network/external-services/ks.yaml` | Created: Flux Kustomization, `targetNamespace: network`, `dependsOn: envoy-gateway-config` |
| `kubernetes/apps/network/external-services/truenas/endpoint.yaml` | Created: EndpointSlice pointing to 10.10.0.41:8080 |
| `kubernetes/apps/network/external-services/truenas/service.yaml` | Created: headless Service (no selector), port 8080 |
| `kubernetes/apps/network/external-services/truenas/httproute.yaml` | Created: HTTPRoute `truenas.${DOMAIN_CLUSTER}` → envoy-internal |
| `kubernetes/apps/network/external-services/truenas/kustomization.yaml` | Created: Kustomize entry-point listing 3 resources |

### Key decisions
- Reuse `envoy-internal` over a dedicated `envoy-services` gateway — avoids extra Envoy pod fleet and CiliumLB IP; migration triggers and cost documented in ROADMAP.md for when IP-level ACLs or TLS passthrough are needed
- Use `${DOMAIN_CLUSTER}` (internal-only, absent from cloudflared config) for all LAN resource hostnames; TLS terminates at `envoy-internal` with the pre-loaded wildcard — no per-service cert needed
- `ks.yaml` declares `targetNamespace: network` explicitly rather than relying on namespace fields in manifests, keeping the individual resource YAMLs namespace-agnostic

---

## 2026-05-29 — `waha-hook-auth-fix`

### Goal
Debug and fix persistent 401s from the WAHA postStart hook — traced through WAHA bcrypt-verify mode, Flux PostBuild variable substitution silently emptying `${VAR}` patterns, and hardened by moving the plain API key to a file mount to keep it out of the process environment.

### What we did
- Observed consistent 401s from the postStart hook across multiple pod restarts despite the manual `curl` from inside the pod returning 422 (authenticated); confirmed `WAHA_API_KEY_PLAIN` was set and non-empty in the running pod
- Diagnosed root cause 1: `WAHA_API_KEY` is a bcrypt hash; WAHA auto-detects this and switches to bcrypt-verify mode — the hook was sending the hash, not the plain key; switched hook to `$WAHA_API_KEY_PLAIN`
- Diagnosed root cause 2: Flux PostBuild substitution (active on the `waha` Kustomization) matched `${WAHA_API_KEY_PLAIN}` and silently replaced it with an empty string (undefined cluster variable); confirmed by inspecting the rendered HelmRelease in-cluster — `"X-Api-Key: "` in the applied spec; fixed by switching to bare `$WAHA_API_KEY_PLAIN` (no braces), which Flux's `${VAR}` pattern does not match
- Hook succeeded after fix: `POST /api/sessions` → 422 (session exists, authenticated) → fallback `POST /api/sessions/default/start` → 201; `[Client] Successfully authenticated` in logs
- Implemented file-mount approach to keep plain key out of process environment: replaced `envFrom: secretRef: waha-secret` with explicit `env` entries per key (excluding `WAHA_API_KEY_PLAIN`); added `waha-secret` volume mount at `/run/secrets/waha`; hook reads key via `$(cat /run/secrets/waha/WAHA_API_KEY_PLAIN)` (shell command substitution — immune to Flux `${VAR}` substitution)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Three iterations: switched to `WAHA_API_KEY_PLAIN`, fixed Flux substitution with bare `$VAR`, switched to file-mount auth with explicit env entries |

### Key decisions
- Used bare `$VAR` not `${VAR}` to defeat Flux PostBuild substitution — Flux only matches the braced form; bare `$VAR` is left untouched and the shell expands it at runtime. This is a reusable pattern for any hook script referencing values that are not cluster-level substitution variables
- Used `$(cat /run/secrets/waha/WAHA_API_KEY_PLAIN)` (shell command substitution) rather than a bare env var — this is also immune to Flux `${VAR}` substitution since it's not that syntactic pattern
- Chose explicit `env` entries over `envFrom` to selectively exclude `WAHA_API_KEY_PLAIN` from the environment; `envFrom` maps all secret keys to env vars with no exclusion mechanism

---

## 2026-05-29 — `waha-session-autostart`

### Goal
Add a `postStart` lifecycle hook to the WAHA HelmRelease to auto-start the default WhatsApp session via the REST API on pod start, replacing non-functional PLUS-only env vars.

### What we did
- Diagnosed that `WHATSAPP_START_SESSION`, `WHATSAPP_RESTART_ALL_SESSIONS`, and `WAHA_WORKER_RESTART_SESSIONS` are PLUS-only and are no-ops in the CORE image currently deployed
- Evaluated Kubernetes options for post-start API calls: `postStart` lifecycle hook vs sidecar container; chose `postStart` as the cleaner pattern (no idle container, well-defined timing before readiness probes fire)
- Confirmed `curl` availability in the WAHA container by exec-ing into the running pod (`waha-5f59684d8b-lgf64`): Debian 12 Bookworm base with `curl 7.88.1` at `/usr/bin/curl`
- Added `postStart` hook to the `app` container: polls `/ping` until the app responds, then calls `POST /api/sessions` with `{"name":"default","start":true}`; falls back to `POST /api/sessions/default/start` for the case where the session already exists on the PVC (409 conflict on create)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/automation/waha/app/helmrelease.yaml` | Added `lifecycle.postStart` hook (15 lines) to auto-start the default WhatsApp session via REST API |

### Key decisions
- Chose `postStart` over a sidecar: `curl` confirmed present in the Debian 12 base image, so no external image needed; sidecar would require `sleep infinity` to keep the pod alive, consuming resources permanently
- Two-step fallback (`POST /api/sessions` → `POST /api/sessions/default/start`): handles both fresh PVC (session must be created) and restart with existing session data (create returns 409, start-only call succeeds)
- `|| true` at the end prevents a non-zero hook exit (e.g. session already started) from triggering a container restart loop

---

## 2026-05-29 — `externalsecret-migration`

### Goal
Audit and migrate all ExternalSecrets to the `dataFrom.extract` + `rewrite.regexp` + `template` pattern per CONVENTIONS.md, and fix a pre-existing `flux-receiver` breakage caused by stale 1Password Connect cache.

### What we did
- Audited all 10 ExternalSecrets: identified 6 needing migration, confirmed 2 already compliant (`tailscale-operator`, `waha`), found `flux-receiver` partially migrated with a wrong template output key (`FLUX_GITHUB_WEBHOOK_TOKEN` vs the required `token`)
- Inspected all 5 relevant 1Password items (`cloudflared`, `unifi`, `flux`, `actions-runner`, `anthropic`) for field names, types, and shape — confirmed `cloudflared` item is shared by 3 ExternalSecrets, requiring `template` scoping on all three to prevent field leakage
- Diagnosed `flux-receiver` `Ready: False`: root cause was 1Password Connect cache staleness, not a missing item — `flux` item existed with both field names but Connect hadn't synced it; item has been accessible in the vault since ~2026-05-15
- Restarted 1Password Connect (`kubectl rollout restart deployment/onepassword-connect -n external-secrets`) → all 10 ExternalSecrets returned to `SecretSynced: True`
- Fixed `flux-receiver` ExternalSecret template key: `FLUX_GITHUB_WEBHOOK_TOKEN` → `token`; annotated Receiver to force reconcile → `Ready: True`, webhook URL restored
- Migrated `cert-manager/cluster-issuers`: added `rewrite: CF_$1` + scoping template exposing exactly `API_TOKEN` key (cert-manager `apiTokenSecretRef` requirement)
- Migrated `network/external-dns/cloudflare`: switched from `data[]` to `dataFrom.extract` + `rewrite: CF_$1` + template
- Migrated `network/cloudflared`: switched to `dataFrom.extract` + `rewrite: CF_$1` + template (`TUNNEL_TOKEN: "{{ .CF_TUNNEL_TOKEN }}"`) — staged, requires `TUNNEL_TOKEN` → `TOKEN` 1P rename before commit
- Migrated `network/external-dns/unifi`: `dataFrom.extract` + `rewrite: UNIFI_$1` + template — staged, requires `UNIFI_HOST` → `HOST` and `UNIFI_API_KEY` → `API_KEY` renames
- Migrated both `actions-runner-system` ExternalSecrets: `dataFrom.extract` + rewrite + template — staged, requires `ACTIONS_RUNNER_*` → short names and `ANTHROPIC_API_KEY` → `API_KEY` renames
- Provided `op item edit --template` commands for user to run for all four 1P items; auto-mode classifier correctly blocked write operations as production-secrets mutations

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-receiver/app/externalsecret.yaml` | Fixed template output key to `token` (Flux Receiver CRD requirement) |
| `kubernetes/apps/cert-manager/cluster-issuers/app/externalsecret.yaml` | Added `rewrite: CF_$1` + scoping template; was partially migrated (no rewrite) |
| `kubernetes/apps/network/external-dns/cloudflare/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: CF_$1` + template |
| `kubernetes/apps/network/cloudflared/app/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: CF_$1` + template (staged; needs 1P rename) |
| `kubernetes/apps/network/external-dns/unifi/externalsecret.yaml` | Migrated `data[]` → `dataFrom.extract` + `rewrite: UNIFI_$1` + template (staged; needs 1P rename) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/externalsecret.yaml` | Both ExternalSecrets migrated to `dataFrom.extract` + rewrite + template (staged; needs 1P renames) |

### Key decisions
- Added `template` scoping to ALL migrations regardless of roadmap's "no template needed" notes — the shared `cloudflared` item has 3 fields; without scoping, all three app secrets would receive unrelated keys (e.g. tunnel `cert-manager-secret` would also contain `CF_TUNNEL_TOKEN`)
- Used `CF_$1` rewrite for `cloudflared` tunnel (roadmap proposed `TUNNEL_$1`) — keeps all three cloudflared-derived ExternalSecrets on a consistent `CF_` prefix, matching `external-dns-cloudflare` and `cert-manager` which were already established; the template then maps `CF_TUNNEL_TOKEN` → `TUNNEL_TOKEN` for the consumer
- The staged cloudflared/unifi/actions-runner manifests reference post-rename field names; they **must not be committed before the 1P renames complete** or all three ExternalSecrets will immediately enter `SecretSyncError`

---

## 2026-05-25 — `flux-alertmanager-notifications`

### Goal
Implement Flux alerting by wiring notification-controller to Alertmanager for event-driven resource failure alerts, and adding a Prometheus PodMonitor and PrometheusRules for controller-level health monitoring.

### What we did
- Reviewed `docs/REPO-AUDIT.md` W1 (no Flux Alert/Provider configured); used `gitops-knowledge` skill to enumerate all supported Flux Provider types
- Decided on `alertmanager` Provider: in-cluster, integrates with existing kube-prometheus-stack, no extra infrastructure
- Cross-referenced with bykaj's home-ops repo: they use PrometheusRules + PodMonitor (metric-based) rather than Flux Alert/Provider; identified that their approach misses individual HelmRelease/Kustomization failure alerting — the two approaches are complementary
- Created `flux-alerts` app with Flux `Provider` (type: `alertmanager`, in-cluster Service URL) and `Alert` (`eventSeverity: error`, watches all `Kustomization` + `HelmRelease` resources, three noise-exclusion patterns)
- Added `PodMonitor` (scrapes all 4 Flux controllers via `http-prom`) and `PrometheusRule` (`FluxInstanceAbsent` + `FluxInstanceNotReady`, 5m threshold) to the `flux-instance` app
- Confirmed `flux-system` is correct for all resources: `kube-prometheus-stack` has `*SelectorNilUsesHelmValues: false`, enabling cluster-wide PodMonitor/PrometheusRule discovery from any namespace

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-alerts/ks.yaml` | Created — Flux Kustomization, dependsOn kube-prometheus-stack |
| `kubernetes/apps/flux-system/flux-alerts/app/kustomization.yaml` | Created |
| `kubernetes/apps/flux-system/flux-alerts/app/notifications.yaml` | Created — Provider (alertmanager) + Alert (flux-errors, error severity) |
| `kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml` | Created — scrapes helm/source/kustomize/notification controllers |
| `kubernetes/apps/flux-system/flux-instance/app/prometheusrule.yaml` | Created — FluxInstanceAbsent + FluxInstanceNotReady rules |
| `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml` | Updated — added podmonitor and prometheusrule resources |
| `kubernetes/apps/flux-system/kustomization.yaml` | Updated — added flux-alerts entry |

### Key decisions
- Used in-cluster Service URL (`svc.cluster.local:9093`) for the alertmanager Provider address — avoids a gateway hop and keeps alerting functional even when external ingress is down
- Co-located PodMonitor + PrometheusRule in `flux-instance` app (not `observability`) — "app owns its observability" pattern; `*SelectorNilUsesHelmValues: false` enables Prometheus to discover them from any namespace
- Implemented both Flux Alert/Provider AND PrometheusRules as complementary layers: event-driven covers individual resource failures; metric-based covers controller-level health and absence detection

---

## 2026-05-25 — `drift-detection-global-default`

### Goal
Enable `driftDetection: enabled` as a cluster-wide default for all HelmReleases via the `cluster-apps` global patch, with a label-based opt-out mechanism and full documentation.

### What we did
- Reviewed `docs/REPO-AUDIT.md`; identified W2 (drift detection on only 5/20 HelmReleases) as the primary work item
- Explained drift detection: Flux detects and reverts out-of-band mutations to Helm-owned resources (via server-side apply field ownership) on every reconciliation interval; `mode: warn` detects without reverting, `mode: enabled` detects and corrects
- Audited all 15 HelmReleases missing drift detection (`grep -rL driftDetection`); confirmed none have HPA, VPA, or other controllers that write back to `.spec` fields — all are safe to enable
- Identified non-HPA risk cases: VPA (resources.requests), Service `nodePort` auto-assignment, mutating admission webhooks adding annotations to Helm-managed resources, operators that write to CRD `.spec` (not just `.status`)
- Confirmed `spec.driftDetection.ignore` rules survive the global patch (strategic merge on object sub-fields; global patch only writes `mode`), but `mode: disabled` does not survive (global patch is last writer on scalar fields)
- Added a **separate** drift detection patch block to `kubernetes/flux/cluster/ks.yaml` (kept separate from install/upgrade defaults so the label selector doesn't accidentally exclude other defaults)
- Implemented opt-out label selector `driftDetection.flux.home.arpa/disabled notin (true)` on the inner HelmRelease target — same pattern as `substitution.flux.home.arpa/disabled`
- Updated `CLAUDE.md` HelmRelease defaults section: added `driftDetection: enabled` to the defaults YAML, added note that `ignore` rules survive the global patch (the exception to "last writer wins")
- Added "Drift Detection" section to `docs/CONVENTIONS.md`: opt-out label, `ignore` rules pattern, table of common ignore scenarios (HPA, VPA, nodePort, mutating webhooks), note on what drift detection doesn't watch
- Marked W2 resolved in `docs/REPO-AUDIT.md`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/cluster/ks.yaml` | Added drift detection patch block with `driftDetection.flux.home.arpa/disabled` opt-out label selector |
| `CLAUDE.md` | Updated HelmRelease defaults section with drift detection default and ignore-rules survival note |
| `docs/CONVENTIONS.md` | Added Drift Detection section: opt-out label, ignore rules, risk table, ownership scope |
| `docs/REPO-AUDIT.md` | Marked W2 resolved; updated audit note |

### Key decisions
- **Separate patch block** rather than folding `driftDetection` into the existing install/upgrade defaults patch — the existing patch has no label selector and applies universally; mixing them would mean the opt-out label accidentally excludes install/upgrade defaults too
- **`ignore` rules in HelmRelease YAML survive the global patch** because `driftDetection` is an object field and strategic merge only writes `mode`; this allows per-release path exclusions without needing a local Kustomize patch
- **Full opt-out requires the label on the HelmRelease** (not the Kustomization) because the inner patch target operates at the HelmRelease level

---

## 2026-05-24 — `gitops-repo-audit`

### Goal
Perform a full GitOps best-practices and security audit of the cluster repository, then implement Cosign supply-chain verification for all OCIRepositories where publishers confirmed signed artifacts.

### What we did
- Invoked the `/gitops-repo-audit` skill; ran discovery script revealing 14 OCIRepositories, 20 HelmReleases, 30 Kustomizations across 14 app namespaces; classified repo as single-cluster GitOps monorepo (Flux Operator pattern)
- Added `kustomize` and `kubeconform` to `.mise.toml` (missing tools); ran manifest validation — no Flux/Kubernetes manifest errors; non-Flux files (Talos patches, Taskfile) produced expected schema-skip results
- Checked for deprecated Flux APIs — none found
- Assessed best practices: dependency chains sound, SOPS encryption in place, global HelmRelease patch covers crds/remediation; identified gaps: no `driftDetection`, no `reconcile.fluxcd.io/watch` labels on cluster-vars ConfigMaps, no Flux Alert/Provider notification resources
- Performed security review: OCIRepositories missing Cosign verification was the highest-priority finding
- Investigated each OCI publisher for signature presence using registry API curl calls (`/v2/<repo>/manifests/sha256-<digest>.sig`) — confirmed 7 of 14 OCIRepositories are signed; 7 (tuppr, kube-prometheus-stack, coredns, spegel, gha-runner-scale-set*, envoy-gateway) are unsigned
- Confirmed signing method per publisher: cert-manager uses key-based RSA (published PEM); flux-operator, flux-instance, external-dns, openebs, app-template, tailscale-operator all use keyless OIDC via GitHub Actions (`cosign sign --yes`)
- Confirmed OIDC identities by reading each publisher's GitHub Actions workflows; used org-level subject regexp (`^https://github.com/<org>/`)
- Added `verify:` blocks to 6 OCIRepositories (keyless OIDC); created `cert-manager-cosign-key.yaml` Secret with RSA public key for key-based verification; upgraded `openebs.yaml` from bare `provider: cosign` to include `matchOIDCIdentity`
- Validated all changes with `kustomize build kubernetes/flux/meta/repos/oci/` — 15 resources output (14 OCIRepositories + 1 Secret), no errors

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/app-template.yaml` | Added keyless cosign verify (bjw-s-labs org) |
| `kubernetes/flux/meta/repos/oci/cert-manager-cosign-key.yaml` | New: Secret with cert-manager RSA public key |
| `kubernetes/flux/meta/repos/oci/cert-manager.yaml` | Added key-based cosign verify referencing cert-manager-cosign-key |
| `kubernetes/flux/meta/repos/oci/external-dns.yaml` | Added keyless cosign verify (home-operations org) |
| `kubernetes/flux/meta/repos/oci/flux-instance.yaml` | Added keyless cosign verify (controlplaneio-fluxcd org) |
| `kubernetes/flux/meta/repos/oci/flux-operator.yaml` | Added keyless cosign verify (controlplaneio-fluxcd org) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added cert-manager-cosign-key.yaml to resources list |
| `kubernetes/flux/meta/repos/oci/openebs.yaml` | Upgraded bare `provider: cosign` to include `matchOIDCIdentity` (home-operations org) |
| `kubernetes/flux/meta/repos/oci/tailscale-operator.yaml` | Added keyless cosign verify (home-operations org) |

### Key decisions
- Detected signatures without `cosign` CLI by querying the registry API for `.sig` manifest tags; initial `curl -sv` mixed stderr/stdout causing false 404s — switched to `curl -s -D - -o /dev/null` to properly separate headers from body
- Stored cert-manager public key in a plain (non-SOPS) Secret — it is a published RSA public key, not a private credential, so encryption adds no security benefit
- Used org-level regexp for `subject` (`^https://github.com/<org>/`) rather than pinning to a specific repo or branch — tolerates future repo reorganisation within the trusted org while keeping trust tightly scoped

---

## 2026-05-24 — `tailscale-connector-crd-fix`

### Goal
Debug and fix the failing `tailscale-configs` Kustomization by tracing the missing `connectors.tailscale.com` CRD to a Helm chart values flag (`installCRDs: true`) and hardening the dependency ordering.

### What we did
- Used `/gitops-cluster-debug` skill (Workflow 3) to diagnose the failing `tailscale-configs` Kustomization; called `get_flux_instance` to confirm all 4 Flux controllers healthy with exactly 1 failing Kustomization
- Fetched `tailscale-configs` Kustomization via MCP — error: `the server could not find the requested resource (patch connectors.tailscale.com subnet-router)`; confirmed `tailscale-operator` Kustomization was `Ready` and HelmRelease (v1.96.5) had installed successfully
- Verified `connectors.tailscale.com` CRD absent via `kubectl get crd`; installed Tailscale CRDs were `dnsconfigs`, `proxyclasses`, `proxygrouppolicies`, `proxygroups`, `recorders`, `tailnets`
- Checked `ProxyGroup` CRD schema — types: `egress`, `ingress`, `kube-apiserver`; no `subnet-router` type, ruling out a 1:1 swap
- Queried Tailscale docs via context7 — confirmed `Connector` with `subnetRouter.advertiseRoutes` is still the official API for subnet routing in v1.96.x
- Pulled Helm chart `tailscale-operator@1.96.5` tarball and read `templates/connector.yaml` — entire CRD gated behind `{{ if .Values.installCRDs }}`; root cause: `installCRDs` not set in HelmRelease values, silently skipping the CRD
- Added `installCRDs: true` to HelmRelease values; changed `wait: false` → `wait: true` on the `tailscale-operator` Kustomization to eliminate the CRD registration race condition

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/tailscale/tailscale-operator/app/helmrelease.yaml` | Added `installCRDs: true` to values — enables `connectors.tailscale.com` CRD |
| `kubernetes/apps/tailscale/tailscale-operator/ks.yaml` | `wait: false` → `wait: true` on `tailscale-operator` Kustomization |

### Key decisions
- Root-caused by pulling and inspecting the chart tarball directly — `connector.yaml` is a regular Helm template (not in `crds/`), making it opt-in and silently skippable; the ProxyGroup schema check and context7 lookup confirmed `Connector` is not deprecated, just opt-in
- `wait: true` applied to `tailscale-operator` (not `tailscale-configs`) because the race is in the operator's CRD registration step, not in configs deployment

---

## 2026-05-24 — `setup-flux-mcp-server`

### Goal
Install fluxcd/agent-skills (gitops-knowledge, gitops-cluster-debug, gitops-repo-audit) and wire up flux-operator-mcp as a new MCP server so the gitops-cluster-debug skill has live cluster access.

### What we did
- Installed 3 Flux skills from OCI image `ghcr.io/fluxcd/agent-skills` via `flux-operator skills install --agent claude-code`: `gitops-knowledge`, `gitops-cluster-debug`, `gitops-repo-audit`; artifact signature verified by cosign
- Explored the `.claude/skills/` vs `.claude/commands/` distinction: installed OCI packages land in `skills/` (directory with `SKILL.md`, `assets/`, `evals/`, `references/`); hand-authored slash commands stay as flat `.md` files in `commands/`
- Explored `.agents/skills/` structure: agent-agnostic registry with `catalog.yaml` (OCI source + cosign OIDC policy + target agents) and `catalog-lock.yaml` (pinned digest); `flux-operator skills install` projects skill content into `.claude/skills/` for Claude Code
- Compared `cluster-doctor.md` against `gitops-cluster-debug`: confirmed not redundant — cluster-doctor covers full-stack Talos+K8s+CNI+storage diagnosis with live topology context; gitops-cluster-debug is Flux-only and requires `flux-operator-mcp` (not previously configured)
- Added `flux-operator-mcp = "0.50.0"` to `.mise.toml` with Renovate datasource comment; added `flux-operator-mcp` server entry to `.mcp.json` (gitignored) with `--read-only` and pointing at existing `mcp-viewer.kubeconfig`
- Ran `mise install flux-operator-mcp`; verified binary via `mise exec -- flux-operator-mcp --version`
- Confirmed MCP connection after shell refresh: `get_flux_instance` returned full FluxInstance + FluxReport; all 4 controllers healthy; identified 1 failing Kustomization (32 total) and Flux v2.6.4 outdated notice (latest v2.8.8)

### Files changed
| File | Change |
|------|--------|
| `.mise.toml` | Added `flux-operator-mcp = "0.50.0"` with renovate comment |
| `.mcp.json` | Added `flux-operator-mcp` server entry (gitignored — not tracked) |

### Key decisions
- Used `--read-only` for flux-operator-mcp to preserve GitOps discipline (no imperative cluster changes via AI tools)
- Pinned flux-operator-mcp at `0.50.0` to match `flux-operator` already in `.mise.toml`; shared Renovate datasource comment keeps both in sync

---

## 2026-05-23 — `arc-runner-deploy`

### Goal
Deploy GitHub Actions Runner Controller (ARC) with a self-hosted runner scale set and wire up claude-code-action to automatically review Renovate PRs using the pr-upgrade-reviewer agent.

### What we did
- Prioritised ARC + Claude PR review above other roadmap items; user created GitHub App and added credentials to 1Password
- Created two OCIRepository sources for `gha-runner-scale-set-controller` and `gha-runner-scale-set` ARC charts under `flux/meta/repos/oci/`
- Built multi-document `ks.yaml` (controller Kustomization → `dependsOn` → scale-set Kustomization) with `substitution.flux.home.arpa/disabled: "true"` on both to prevent cluster-apps postBuild expanding GitHub URLs as Flux variables
- Created controller HelmRelease with explicit `serviceAccount.name: actions-runner-controller`; runner HelmRelease with kubernetes containerMode; ExternalSecrets for GitHub App creds (`home-lab-runner-secret`) and Anthropic API key (`anthropic-secret`)
- Created RBAC: Kubernetes SA `actions-runner` + `cluster-admin` ClusterRoleBinding (intentional — runner workflows need full kubectl/flux access)
- Created `.github/workflows/renovate-pr-review.yml` using `anthropic-ai/claude-code-action@v1` with `ANTHROPIC_API_KEY` injected via runner environment (ExternalSecret → pod env)
- Fixed typo `anthropics/` → `anthropic-ai/` in action reference; fixed ExternalSecret `key:` for anthropic-secret (user corrected to `key: anthropic`)
- Diagnosed Talos SA `ErrNamespaceNotAllowed`: `actions-runner-system` blocked by Talos SA namespace allowlist; removed Talos SA and its volume mounts — commit `fb3767e`
- Observed two Renovate PRs (#39 actions/checkout, #40 kube-prometheus-stack) triggering simultaneously; runners created but cycling every ~5 minutes — initially misdiagnosed as openebs-hostpath node-locality PVC issue; applied Longhorn fix (`d2b5cb0`) — later found incorrect
- Resumed next day: renewed MCP token; re-triggered run `26332793877` to test Longhorn fix; observed new failure mode: rapid create/destroy cycle at ~15 s intervals
- Analysed ARC controller logs: `"exitCode": 0` at the exact same millisecond as `"ready": true` — runner binary not executing at all; no hook pods created
- Consulted reference implementation `bykaj/home-ops`; identified missing `command: [/home/runner/run.sh]` — the `home-operations/actions-runner` image does not wire `run.sh` as Docker CMD, causing the container to exit immediately (exit 0) and producing the create/destroy loop
- Added `command: [/home/runner/run.sh]` to runner container spec
- User challenged Longhorn choice: confirmed `openebs-hostpath` uses `WaitForFirstConsumer` which records node affinity on the PV, automatically constraining ARC hook pods to the same node as the runner — Longhorn was unnecessary; reverted to `openebs-hostpath` with 10 Gi work volume
- Hardened workflow: added `timeout-minutes: 15` (job) + per-step timeouts, `concurrency` group with `cancel-in-progress: true`, `synchronize` event type, explicit `github_token`
- Reviewed `pr-upgrade-reviewer` agent: user added unattended operation constraints, PR number intake from CLI arg / `PR_NUMBER` env, Step 6 (mandatory PR comment posting with idempotent HTML-marker-based update-or-create logic)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/gha-runner-scale-set-controller.yaml` | Created OCIRepository source |
| `kubernetes/flux/meta/repos/oci/gha-runner-scale-set.yaml` | Created OCIRepository source |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added two new OCI repo entries |
| `kubernetes/apps/kustomization.yaml` | Added `actions-runner-system` resource |
| `kubernetes/apps/actions-runner-system/kustomization.yaml` | Created namespace kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/ks.yaml` | Created two-doc Kustomization (controller + scale set) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/app/helmrelease.yaml` | Created controller HelmRelease |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/app/kustomization.yaml` | Created app kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/kustomization.yaml` | Created runners kustomization |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/helmrelease.yaml` | Created; fixed with `command: run.sh`, reverted to openebs-hostpath 10 Gi |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/externalsecret.yaml` | Created two ExternalSecrets (runner creds + anthropic key) |
| `kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-lab/rbac.yaml` | Created SA + cluster-admin CRB (Talos SA added then removed) |
| `.github/workflows/renovate-pr-review.yml` | Created; improved with timeout, concurrency, synchronize event, github_token |
| `.claude/agents/pr-upgrade-reviewer.md` | Enhanced: unattended mode, PR number intake, Step 6 mandatory comment posting |

### Key decisions
- `substitution.flux.home.arpa/disabled: "true"` on both ARC Kustomizations — GitHub URLs and secret names contain `${...}` patterns that cluster-apps postBuild would expand as Flux variables
- Multi-doc `ks.yaml` required — runner scale set CRDs must exist before instances; `dependsOn` + separate Kustomization prevents Flux dry-run failure at deploy time
- Talos SA removed entirely — `actions-runner-system` is not in the Talos SA namespace allowlist; accessing Talos API from CI requires a different approach not yet implemented
- `cluster-admin` intentionally granted — runner workflows need full cluster write access; homelab risk is accepted and documented in a `rbac.yaml` comment
- `command: [/home/runner/run.sh]` required — `home-operations/actions-runner` does not use `run.sh` as Docker CMD; without it the container exits immediately (exit 0), creating an infinite rapid create/destroy loop indistinguishable from a passing run
- openebs-hostpath with `WaitForFirstConsumer` over Longhorn — `WaitForFirstConsumer` records node affinity on the PV, constraining hook pods to the same node as the runner; Longhorn adds unnecessary network overhead; the earlier Longhorn switch was based on a misdiagnosis of the 5-minute timeout cycle

---

## 2026-05-23 — `cloudflare-ssl-webhook-fix`

### Goal
Fix the broken GitHub Flux webhook by diagnosing and resolving Cloudflare Universal SSL's one-level wildcard limitation, an external-dns zone-filter misconfiguration, and a stale cloudflared in-process config.

### What we did
- Continued from `debug-flux-dns-tunnel` — the big multi-domain commit was applied but external-dns-cloudflare logged only 4 lines and never synced
- Diagnosed the silence using a debug pod (`--once --dry-run --log-level=debug`): Cloudflare external-dns v0.21.0 requires the exact Cloudflare zone name in `domainFilters`; `cluster.vwn.io` doesn't match the `vwn.io` zone — it was silently skipping all desired records
- User added `DOMAIN_IO: vwn.io` to `cluster-secrets.sops.yaml`; amended `64844f0` to add `${DOMAIN_IO}` to external-dns-cloudflare `domainFilters` (preserving original commit subject)
- External-dns created `external.cluster.vwn.io` and `flux-webhook.cluster.vwn.io` Cloudflare CNAME records
- GitHub webhook delivery failed with `tls: handshake failure` — root cause: cloudflared pods were 17-20h old and still running config with `originServerName: gateway.vwn.io` (the old CLUSTER_DOMAIN); restarted cloudflared
- Second failure: Cloudflare Universal SSL covers `vwn.io` + `*.vwn.io` only (one wildcard level); `flux-webhook.cluster.vwn.io` is two levels deep — not covered by any cert at Cloudflare's edge
- Investigated Option A (NS delegation for `cluster.vwn.io` sub-zone) — Cloudflare rejected it: "should not delegate subdomain to the same nameserver as current zone"
- Chose Option C: move all public-facing endpoints to first-level `vwn.io` subdomains (covered by Universal SSL, no cost/complexity)
- Changed `flux-webhook.${DOMAIN_CLUSTER}` → `flux-webhook.${DOMAIN_IO}`, `external.${DOMAIN_CLUSTER}` → `external.${DOMAIN_IO}` across httproute, dnsendpoint, gateway annotations, and cloudflared ingress; committed as `c98664c`
- Waited for external-dns `policy: sync` to delete the old `cluster.vwn.io` CNAME + TXT records before removing the zone from `domainFilters` — removing early would have orphaned the ownership records
- Confirmed cleanup in external-dns logs; removed `${DOMAIN_CLUSTER}` from cloudflare domainFilters and updated `originServerName` to `gateway.${DOMAIN_IO}`; committed as `67275b9`
- cloudflared pods hadn't restarted after the ConfigMap update (process reads config only at startup); rolled deployment; webhook redeliver returned 200 OK
- Deleted orphaned `wildcard-production-tls` Secret from `network` namespace (cert had been removed in Phase B but Secret persisted)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `DOMAIN_IO: vwn.io` (amended into `64844f0`) |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Added `${DOMAIN_IO}` to domainFilters; later removed `${DOMAIN_CLUSTER}` |
| `kubernetes/apps/flux-system/flux-receiver/app/httproute.yaml` | Hostname `DOMAIN_CLUSTER` → `DOMAIN_IO` |
| `kubernetes/apps/network/cloudflared/app/dnsendpoint.yaml` | `external.DOMAIN_CLUSTER` → `external.DOMAIN_IO` |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | Removed `*.DOMAIN_CLUSTER` ingress; added `*.DOMAIN_IO`; updated `originServerName` |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Both `external-dns` annotations → `external.DOMAIN_IO` |

### Key decisions
- Option C (first-level `vwn.io` subdomains) chosen over NS delegation (rejected by Cloudflare) and Advanced Certificate Manager (paid) — Universal SSL already covers `*.vwn.io` without additional setup
- `${DOMAIN_CLUSTER}` kept in external-dns-cloudflare `domainFilters` until `policy: sync` cleaned up owned records; removing it earlier would have left orphan CNAME + TXT records in Cloudflare with no owner to clean them up
- cloudflared `originServerName` uses `gateway.${DOMAIN_IO}` as TLS SNI for the tunnel → Envoy backend connection; Envoy routes using the HTTP Host header, not SNI — the mismatch is intentional and harmless with `noTLSVerify: true`

---

## 2026-05-23 — `debug-flux-dns-tunnel`

### Goal
Add multi-domain TLS support, remove legacy `CLUSTER_DOMAIN`, harden Envoy Gateway, and fix a Cloudflare tunnel routing bug where `external.proxii.nl` (private DNS) was used as the external-dns target instead of the cloudflared tunnel endpoint.

### What we did
- Compared envoy-gateway deployment against bykaj reference repo; identified gaps: no BackendTrafficPolicy (compression/retry), no observability, no memory limits, no drainTimeout
- Added `BackendTrafficPolicy` (zstd/brotli/gzip compression, retry on TCP reset, tcpKeepalive, `requestTimeout: 0s`), `ClientTrafficPolicy` (http3, tcpKeepalive), `drainTimeout: 180s`, memory 256Mi request / 1Gi limit (Burstable QoS)
- Added `PodMonitor` + `ServiceMonitor` for Envoy proxy pods and control-plane metrics
- Added four domain variables (`DOMAIN_APP`, `DOMAIN_CASA`, `DOMAIN_CLUSTER`, `DOMAIN_APPS`) to `cluster-secrets.sops.yaml`; removed legacy `CLUSTER_DOMAIN` (`vwn.io`) entirely
- Created four per-domain wildcard Certificate CRs (`vwn.app`, `vwn.casa`, `cluster.vwn.io`, `apps.vwn.io`); removed `wildcard-production` Certificate; updated both gateway `certificateRefs`; removed `hostname:` restriction from HTTPS listeners (SNI-based cert selection)
- Migrated `prometheus`, `alertmanager` HTTPRoutes to `DOMAIN_CLUSTER` / `envoy-internal`; migrated `flux-webhook` to `DOMAIN_CLUSTER` / `envoy-external`
- Removed `CLUSTER_DOMAIN` from cert-manager ClusterIssuers, cloudflared ingress rules, and external-dns domainFilters
- Added static `DNSEndpoint` for `kube-vip.cluster.vwn.io → 10.60.0.2` and `external-dns-endpoints` Kustomization (later replaced)
- **Diagnosed tunnel routing bug:** `flux-webhook.cluster.vwn.io` resolved to `external.proxii.nl → 10.60.0.230` (private IP); Cloudflare's edge can't reach private IPs, so tunnel was never engaged. Root cause: `external.proxii.nl` is in private UniFi DNS, not a Cloudflare-managed zone
- **Fixed:** Added `DNSEndpoint` CR in cloudflared app creating `external.cluster.vwn.io CNAME <tunnel-id>.cfargotunnel.com`; changed gateway target annotation from `external.${DOMAIN_PROXII}` → `external.${DOMAIN_CLUSTER}`; added `CLOUDFLARE_TUNNEL_ID` to cluster-secrets
- Removed `crd` from `external-dns-unifi` sources to prevent CNAME/A conflict (both instances would have created conflicting record types for the same intermediate hostname)
- Replaced `kube-vip` `DNSEndpoint` CR with a real `kube-api` `LoadBalancer` Service in `cilium/config/`; Cilium LB IPAM pins it to `10.60.0.2`; `external-dns-unifi` `service` source creates `kube-vip.cluster.vwn.io A 10.60.0.2` without needing the `crd` source
- Removed `external-dns-endpoints` Kustomization and `endpoints/` directory
- Installed `dnsutils` in devcontainer (added to `postCreateCommand.sh`); added prominent no-commit directive to `CLAUDE.md`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Added `DOMAIN_APP/CASA/CLUSTER/APPS/PROXII`, `CLOUDFLARE_TUNNEL_ID`; removed `CLUSTER_DOMAIN` |
| `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` | BackendTrafficPolicy, ClientTrafficPolicy, memory limits, drainTimeout 180s |
| `kubernetes/apps/network/envoy-gateway/config/certificate.yaml` | Replaced `wildcard-production` with 4 per-domain wildcard Certificates |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Removed hostname restriction; multi-cert refs; tunnel target fixed |
| `kubernetes/apps/network/envoy-gateway/app/observability.yaml` | New — PodMonitor + ServiceMonitor |
| `kubernetes/apps/network/envoy-gateway/app/kustomization.yaml` | Added `observability.yaml` |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | Removed `CLUSTER_DOMAIN` ingress entries; added all 4 new domains; fixed `originServerName` |
| `kubernetes/apps/network/cloudflared/app/dnsendpoint.yaml` | New — `external.cluster.vwn.io CNAME <tunnel-id>.cfargotunnel.com` |
| `kubernetes/apps/network/cloudflared/app/kustomization.yaml` | Added `dnsendpoint.yaml` |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Updated `domainFilters` |
| `kubernetes/apps/network/external-dns/unifi/helmrelease.yaml` | Updated `domainFilters`; removed `crd` source |
| `kubernetes/apps/network/external-dns/ks.yaml` | Removed `external-dns-endpoints` Kustomization |
| `kubernetes/apps/network/external-dns/endpoints/` | Deleted — replaced by `kube-api` Service |
| `kubernetes/apps/kube-system/cilium/config/service.yaml` | New — `kube-api` LoadBalancer Service for `kube-vip.cluster.vwn.io` |
| `kubernetes/apps/kube-system/cilium/config/kustomization.yaml` | Added `service.yaml` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-production.yaml` | Removed `CLUSTER_DOMAIN` from `dnsZones` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-staging.yaml` | Removed `CLUSTER_DOMAIN` from `dnsZones` |
| `kubernetes/apps/flux-system/flux-receiver/app/httproute.yaml` | Hostname → `flux-webhook.${DOMAIN_CLUSTER}` |
| `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml` | Hostnames → `${DOMAIN_CLUSTER}` |
| `docs/ROADMAP.md` | Added multi-domain cert pipeline pattern (deferred) |
| `CLAUDE.md` | Prominent no-commit directive blockquote |
| `.devcontainer/postCreateCommand.sh` | Added `dnsutils` |

### Key decisions
- Domain vars go in encrypted `cluster-secrets.sops.yaml`, not plaintext `cluster-settings.yaml` — these values are considered infrastructure secrets
- `hostname:` restriction removed from gateway HTTPS listeners — SNI-based cert selection handles routing; HTTP virtual hosting is still controlled by HTTPRoute `hostnames:` field
- `external.cluster.vwn.io` chosen as the cloudflared tunnel intermediary hostname (not `external.proxii.nl`) because it lives in a Cloudflare-managed zone; both external-dns instances resolve it differently via split DNS (Cloudflare: CNAME → tunnel; UniFi: A → 10.60.0.230)
- `crd` source removed from UniFi external-dns (mirrors bykaj pattern); static LAN records handled via `service` source instead, avoiding CNAME/A conflicts
- `kube-vip.cluster.vwn.io` hardcoded in `service.yaml` (not a variable) because `cilium-config` Kustomization has substitution disabled (`substitution.flux.home.arpa/disabled: "true"`) — changing this would be a broader risk than hardcoding a stable infrastructure hostname

---

## 2026-05-23 — `uncordon-cp-02-node`

### Goal
Diagnose and fix the cp-02 persistent boot loop (JetKVM EFI boot entry root cause), then repair Longhorn's stale disk UUID record to bring cp-02's storage disk fully online.

### What we did
- Continued from `nvme-disk-config-talos` — cp-02 was configured but kept booting to ISO/maintenance mode instead of Talos after every power cycle
- Diagnosed masking issue: `talosctl reboot` uses Linux kexec by default (bypasses BIOS entirely), so the boot failure was invisible until `--mode powercycle` was used
- Booted Alpine Linux via JetKVM virtual media to inspect UEFI state; `apk add efibootmgr` was unavailable (no network), BusyBox `strings -e l` unsupported; decoded UTF-16LE boot entry labels using `tr -d '\000' < /sys/firmware/efi/efivars/Boot####-<GUID>`
- Identified root cause: **JetKVM Virtual Media (Boot0016)** had higher UEFI priority than Talos Linux (Boot0000); with Alpine ISO mounted in JetKVM, every boot went to maintenance mode
- Deleted all UEFI boot entries except Boot0000 via direct efivars manipulation (`chattr -i` + `rm`); ejected Alpine ISO from JetKVM virtual media; power-cycled
- cp-02 booted Crucial P310 successfully (Lenovo logo visible via JetKVM); all 3 nodes Ready (Talos v1.13.2, K8s v1.36.1); mounts confirmed: `nvme1n1=EPHEMERAL/system`, `nvme0n1p1=/var/mnt/longhorn-storage`
- Ran cluster-doctor diagnostic: cp-02 already uncordoned; Longhorn disk `default-disk-1030500000000` had `DiskFilesystemChanged` UUID mismatch, `allowScheduling: false`
- Fixed stale `node.longhorn.io/default-disks-config` annotation on Node object (`allowScheduling: false → true`, aligning with Git manifest)
- Removed stale Longhorn disk entry via `kubectl patch`; controller re-discovered disk with fresh UUID `3becac06-4aac-499c-a8de-a49badaefaaa`; disk now `Ready: True, Schedulable: True`, ~913 GiB available
- Confirmed existing volumes remain at 2 replicas (pre-cp-02); new volumes will use 3-replica default; manual UI bump or `Replicas Auto Balance` setting needed to expand existing volumes
- Created `docs/BOOT-ISSUE-TROUBLESHOOTING.md` documenting M920Q A/E slot boot behavior, EFI entry manipulation workaround, and required BIOS settings

### Files changed
| File | Change |
|------|--------|
| `docs/BOOT-ISSUE-TROUBLESHOOTING.md` | New — M920Q A/E slot UEFI boot troubleshooting guide (efivars manipulation, JetKVM gotcha, BIOS settings) |

### Key decisions
- Direct efivars `chattr -i` + `rm` used instead of `efibootmgr` — Alpine on JetKVM had no network; efivars manipulation is equivalent from any Linux live environment
- Deleted all non-Talos UEFI entries (including JetKVM virtual media entry) rather than reordering — prevents any external boot source overriding Talos on future power cycles
- Longhorn disk UUID reset via imperative `kubectl patch` (not GitOps) — stale UUID is a live controller-state problem, not representable in Git; Longhorn re-adds disk with correct UUID within seconds

---

## 2026-05-22 — `nvme-disk-config-talos`

### Goal
Install the Crucial P310 1TB NVMe drive in cp-02, reconfigure Talos to boot from it and use the Kingston as Longhorn storage, and promote Longhorn to 3-replica mode.

### What we did
- Shut down cp-02 with `talosctl shutdown` (note: `halt` command removed in Talos 1.9+; `shutdown` is the equivalent)
- User installed Crucial P310 1TB 2230 NVMe in cp-02 and booted into Talos maintenance mode
- Ran `talosctl get disks --insecure` to identify both drives: Crucial (`nvme1n1`, model `CT1000P310SSD2`, serial `25174FD70E4D`) as new drive; Kingston (`nvme0n1`, model `KINGSTON SNV3S1000G`, serial `50026B7383B9D0CC`) as former system disk
- Updated `talos/talconfig.yaml`: changed `installDiskSelector.model` from `KINGSTON SNV3S1000G` → `CT1000P310SSD2`; added `machine.disks` patch mounting Kingston (`/dev/disk/by-id/nvme-KINGSTON_SNV3S1000G_50026B7383B9D0CC`) at `/var/mnt/longhorn-storage`; removed all cp-02 TODO comments
- Ran `task talos:genconfig` to regenerate all three node configs from updated talconfig
- Applied config in maintenance mode: `task talos:apply IP=10.60.0.202 INSECURE=true`; Talos installed to Crucial and rebooted cleanly
- Verified mount layout post-reboot: `nvme1n1p4 → /var` (Crucial = system disk), `nvme0n1p1 → /var/mnt/longhorn-storage` (Kingston = Longhorn storage, XFS auto-formatted)
- Waited for cp-02 to rejoin Kubernetes cluster as Ready control-plane node (all 3 nodes Ready, v1.36.1)
- Updated `node-configs/talos-cp-02.yaml`: `allowScheduling: false → true`
- Updated `helm/values.yaml`: `defaultClassReplicaCount` and `defaultReplicaCount` 2 → 3 (pending Flux reconciliation)

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | cp-02 `installDiskSelector` → Crucial P310; `machine.disks` patch added for Kingston; TODO comments removed |
| `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-02.yaml` | `allowScheduling: false → true`; holding comment removed |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | `defaultClassReplicaCount` and `defaultReplicaCount` 2 → 3; TODO comments removed |

### Key decisions
- `installDiskSelector.model: "CT1000P310SSD2"` used for Crucial — matches exact model string from `talosctl get disks`, consistent with cp-03's AirDisk selector pattern
- Kingston device path uses `nvme-KINGSTON_SNV3S1000G_<serial>` form (not EUI WWID) — matches cp-01's existing Kingston disk patch for readability and consistency
- Longhorn replica bump left as uncommitted GitOps change — takes effect via Flux reconciliation after push; no in-cluster emergency

---

## 2026-05-22 — `cluster-doc-sync`

### Goal
Run a cluster-doctor health diagnostic and sync CLUSTER.md component versions and ROADMAP.md completion status against live cluster state.

### What we did
- Spawned cluster-doctor agent for a full health audit; cluster all-green: 3 nodes Ready (Talos v1.13.2, K8s v1.36.1), all 27 Kustomizations and 17 HelmReleases Ready, all PVCs Bound, wildcard cert valid
- Agent identified 8 component versions in CLUSTER.md drifted ahead of documentation via Renovate auto-merges since last doc sync
- Updated CLUSTER.md section headings: Cilium (v1.17.6 → v1.19.4), CoreDNS (v1.43.0 → v1.45.2), Spegel (v0.4.0 → v0.7.1), cert-manager (v1.17.2 → v1.20.2), ESO (v0.18.2 → v2.5.0), FluxCD operator (v0.23.0 → v0.50.0), kube-prometheus-stack (v75.10.0 → v85.2.1), tuppr (v0.1.28 → v0.1.35)
- Agent confirmed metrics-server is fully deployed (HelmRelease v3.13.0, pod 1/1 Running 29h); removed from ROADMAP "In Progress" and added to Completed table
- Answered cert-manager-startupapicheck: Completed Job (7d old, no running pods); auto-cleaned on next cert-manager Helm upgrade via hook cleanup; no manual action needed; v1.17.2-labelled Job from initial install coexists with live v1.20.2 chart harmlessly

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | 8 component version headings bumped to match live cluster |
| `docs/ROADMAP.md` | metrics-server section removed from In Progress; row added to Completed table |

---

## 2026-05-22 — `renovate-oci-tag-fix`

### Goal
Review PRs #32 and #38 (cloudflared and Envoy Gateway upgrades); identify and fix Renovate OCI tag series drift in envoy-gateway and cert-manager annotations.

### What we did
- Reviewed PR #32 (cloudflared 2025.9.0 → 2026.5.0) via `pr-upgrade-reviewer` agent; confirmed two v2026.x breaking changes (proxy-dns removal in v2026.2.0, edge-ip-version default changed to "auto" in v2026.4.0) do not apply to this cluster's config (tunnel run only, no proxy-dns, no IP version pinning); verdict: safe to merge
- Reviewed PR #38 (Envoy Gateway v1.7.3 → 1.8.0) via `pr-upgrade-reviewer` agent; six v1.8.0 breaking changes documented (CRD sub-chart split, Gateway API v1.5.1, DirectResponse interpolation, SecurityPolicy timeout semantics, samplingFraction scale, OIDC filter restructure), none intersecting with this cluster's config
- Spotted that Renovate proposed tag `1.8.0` (no `v` prefix) despite current OCIRepository tag being `v1.7.3` — verified via Docker Hub API that both `v1.8.0` and `1.8.0` exist as separate OCI artifacts with different digests; unprefixed tag is the wrong upgrade path
- Added `extractVersion=^v(?<version>.*)$` to Renovate annotation in `oci/envoy-gateway.yaml` to lock Renovate to the `v`-prefixed tag series going forward
- Audited all 11 OCI repository annotation files; found `oci/cert-manager.yaml` also tracks a `v`-prefixed tag (`v1.20.2`) with the same dual-tag pattern on quay.io; applied the same `extractVersion` fix
- Recommended closing PR #38 and letting Renovate re-open with the corrected `v1.8.0` tag (or manually patching the tag in the PR before merging)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/envoy-gateway.yaml` | Added `extractVersion=^v(?<version>.*)$` to Renovate annotation |
| `kubernetes/flux/meta/repos/oci/cert-manager.yaml` | Added `extractVersion=^v(?<version>.*)$` to Renovate annotation |

### Key decisions
- `extractVersion=^v(?<version>.*)$` chosen as the fix — it filters Renovate's tag candidates to only `v`-prefixed ones so non-prefixed tags are invisible, rather than just relying on the current tag's format to guide updates
- Audit extended proactively to all OCI repo annotation files (not just envoy-gateway) to prevent the same tag-series drift from affecting cert-manager on its next Renovate PR

---

## 2026-05-22 — `app-template-v5-review`

### Goal
Review and merge PR #33 (app-template 4.6.2 → 5.0.1 major bump) and document the v5 breaking-change schema rules across the cluster documentation.

### What we did
- Used `pr-upgrade-reviewer` agent to assess PR #33 (Renovate-generated, app-template 4.6.2 → 5.0.1)
- Agent identified 5 breaking changes in v5.0.0: `rawResources` must wrap manifests under `manifest:` key; default ServiceAccount auto-created per controller; `automountServiceAccountToken` defaults to `false`; `NetworkPolicy` `controller`/`podSelector` are mutually exclusive; `ServiceMonitor`/`PodMonitor` `jobLabel` default changed to `app.kubernetes.io/name`
- Confirmed cloudflared (the only current app-template consumer) uses none of the affected features — no values changes required pre-merge; verdict: safe to merge
- Documented v5 schema rules: full authoring reference added to `docs/CONVENTIONS.md`; brief pointer added under GitOps Conventions in `CLAUDE.md`; version inventory entry added to `docs/CLUSTER.md`
- Decided CONVENTIONS.md was the correct home for detailed schema rules, consistent with the existing pattern where CLAUDE.md holds summary pointers and CONVENTIONS.md holds detailed authoring reference material

### Files changed
| File | Change |
|------|--------|
| `docs/CONVENTIONS.md` | Added app-template v5 section with 5 breaking rules, code examples, and upstream docs link |
| `CLAUDE.md` | Added brief app-template v5 pointer under GitOps Conventions |
| `docs/CLUSTER.md` | Added app-template shared chart library inventory entry under Running Components |

### Key decisions
- Schema details placed in `CONVENTIONS.md` rather than `CLAUDE.md` — CONVENTIONS.md is explicitly the "Extended Reference" supplement; keeping CLAUDE.md as a pointer index avoids bloating it with per-chart schema reference material

---

## 2026-05-22 — `connect-upgrade-fix`

### Goal
Review PRs #29 and #30, fix a pre-existing double-encoding bug in the 1Password Connect credentials secret, merge the Connect upgrade, and recover from a post-merge ClusterSecretStore outage.

### What we did
- Reviewed PR #29 (cert-manager v1.17.2→v1.20.2) and PR #30 (1Password Connect 2.0.1→2.4.1) using parallel `pr-upgrade-reviewer` agents
- PR #29 flagged CAUTION: `RotationPolicy` default flipped `Never→Always` in v1.18, and `issuerRef` API defaults re-introduced in v1.20 — provided two `kubectl` audit commands to run before merging
- PR #30 flagged CAUTION: chart v2.3.0 removed the double-base64 workaround for the credentials file — verified secret encoding to confirm impact
- Confirmed the live `onepassword-connect-secrets` secret was double-encoded (`base64(base64(json))`) — the bootstrap task explicitly piped `| base64 -w 0`, then Kubernetes added a second layer; old chart stripped one layer internally
- Explained the issue in depth: old chart read credentials via env var (expected base64 string, decoded it); new chart mounts as a plain file (no decode — single encoding required)
- Fixed the secret before merging: extracted inner JSON via double-decode, deleted and re-created the secret with single encoding, restarted Connect, confirmed `ClusterSecretStore` was `Ready=True` on chart v2.0.1
- Merged PR #30; Helm upgrade to connect@2.4.1 succeeded cleanly (`v3` release)
- Post-merge: `ClusterSecretStore` went `NotReady` with `cannot find secret data for key: "token"` — the Connect API token used by ESO had been dropped when the secret was re-created
- Diagnosed: original secret held two keys (`1password-credentials.json` + `token`); re-creation only restored the credentials file
- Recovery: read token from `op://homelab/HomeLab Access Token/credential`, patched the live secret, force-annotated `ClusterSecretStore` to trigger immediate ESO reconciliation — `Ready=True` within 10 seconds
- Updated the bootstrap task to remove `| base64 -w 0` so future re-bootstrap creates a correctly single-encoded secret

### Files changed
| File | Change |
|------|--------|
| `.taskfiles/bootstrap/Taskfile.yaml` | Removed `\| base64 -w 0` from credentials read in `onepassword-connect-secret` task |

### Key decisions
- Fixed and validated the secret encoding on the *old* chart first, before merging — proved Connect still worked with single-encoding under v2.0.1, reducing risk of a combined encoding + upgrade failure
- After the missing `token` was found post-upgrade, patched the existing secret rather than deleting-and-recreating to avoid dropping the credentials file a second time
- Used a `force-sync` annotation on the `ClusterSecretStore` to trigger immediate ESO reconciliation rather than waiting up to the natural polling interval

---

## 2026-05-22 — `renovate-pr-triage`

### Goal
Triage all open Renovate minor/patch PRs using parallel pr-upgrade-reviewer agents and harden the Renovate soak policy to close a gap where container image minors had no minimumReleaseAge.

### What we did
- Queried GitHub for all open Renovate PRs labelled `type/minor` or `type/patch` — found 9 PRs (#21, #22, #23, #24, #25, #26, #28, #29, #30)
- Launched 9 `pr-upgrade-reviewer` agents in parallel, one per PR, to assess upgrade risk
- Consolidated results: **4 SAFE** (#21 flux, #25 app-template, #26 coredns, #28 spegel), **3 CAUTION** (#22 cilium, #29 cert-manager, #30 1Password Connect), **2 HOLD** (#23 cloudflared, #24 envoy gateway)
- HOLD details: #23 stale — target `2025.11.1` is 6 months old, latest is `2026.5.0`; #24 — no release notes published, tag format anomaly (`1.8.0` vs `v1.7.3`), CRD sub-chart split, K8s v1.36 outside documented support matrix
- CAUTION details: #22 cilium requires 3 pre-merge kubectl checks (BGPv1 removal, v2alpha1 apiVersion, `FromRequires`/`ToRequires` CNP fields); #29 cert-manager `rotationPolicy` default flipped `Never→Always` in v1.18; #30 1Password Connect v2.3.0 fixed double-base64 encoding — verify secret was single-encoded
- Identified gap: container image minor/patch updates (non-Talos/K8s) had no `minimumReleaseAge` — only protected by the weekly schedule (0–7 day window), allowing PRs to open against incompletely-published releases
- Added a 3-day soak gate to `renovate.json5` for all container minor/patch updates excluding `siderolabs/installer` and `siderolabs/kubelet`; committed `4df7f84`

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Added `minimumReleaseAge: "3 days"` gate rule for container image minor/patch updates |

### Key decisions
- Used 9 parallel `pr-upgrade-reviewer` agents rather than a `/loop` — more efficient for a fixed known list; `/loop` is designed for time-based recurrence, not list iteration
- New soak rule uses `matchPackageNames` negation exclusions to avoid interfering with the existing 5-day soak rules for Talos/K8s, which are higher-priority and more restrictive

---

## 2026-05-22 — `kps-upgrade-85`

### Goal
Review, plan, and execute the kube-prometheus-stack upgrade from 75.10.0 to 85.2.1 (Renovate PR #34), safely sequencing CRD updates across 6 prometheus-operator minor bumps.

### What we did
- Ran `pr-upgrade-reviewer` agent on PR #34; identified 10 chart-major / 6 prometheus-operator-minor jump (v0.84.1 → v0.90.1) requires chart-native `crds.upgradeJob` pre-upgrade hook rather than relying solely on the global `crds: CreateReplace` Flux patch
- Verified `allowSchedulingOnControlPlanes: true` (in `talos/patches/controller/cluster.yaml`) removes the control-plane taint entirely — nodes have no taints; initial plan's `tolerations` block for `upgradeJob` was dropped
- Added `crds.enabled: true` + `crds.upgradeJob.enabled: true` to `values.yaml`; committed `7136a02` and pushed to main ahead of the PR merge
- Confirmed Flux reconciled the values change at 75.10.0 (HelmRelease advanced to release v2, "Helm upgrade succeeded"); ConfigMap verified to contain new `crds:` block
- Merged PR #34; upgrade completed to 85.2.1 — all 7 pods healthy, Prometheus CR `Reconciled: True` (distroless `v3.11.3`), Alertmanager CR `Reconciled: True` (`v0.32.1`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Added `crds.upgradeJob.enabled: true` block at top of file |

### Key decisions
- Dropped `crds.upgradeJob.tolerations` from the plan after live verification: `allowSchedulingOnControlPlanes: true` removes the taint outright; existing tolerations throughout `values.yaml` are redundant artefacts from chart defaults
- Committed values change to main before merging the OCIRepository tag PR so Flux could verify the Job wiring at the current version before the 10-version jump landed; treats the upgrade as forward-only (CRD downgrade not feasible after)

---

## 2026-05-22 — `renovate-improvements`

### Goal
Review the Renovate configuration and implement five targeted improvements: auto-merge rules for Helm patches and image digests, a kustomize manager regex fix, package grouping for major stacks, and release soak periods for Talos and Kubernetes.

### What we did
- Reviewed `renovate.json5` against `docs/ROADMAP.md` to identify 6 improvement opportunities
- Fixed a silent bug in the kustomize manager: regex `^kustomization` only matched the root-level file; changed to `(^|/)kustomization` so all `kustomization.yaml` files under `kubernetes/apps/` are now scanned by Renovate
- Added auto-merge for Helm chart patch updates after a 3-day community soak — eliminates the majority of patch PRs silently via `automergeType: "branch"`
- Added auto-merge for container image digest updates after a 1-day soak (digest = same tag, new SHA; no version change); excluded `siderolabs/installer` and `siderolabs/kubelet` which go through tuppr
- Added `minimumReleaseAge: "5 days"` to Talos and Kubernetes rules so PRs don't open until the community has had time to surface regressions in OS/runtime releases
- Added grouping rules for 5 previously ungrouped stacks: Longhorn, kube-prometheus-stack, Envoy Gateway, ExternalDNS, External Secrets
- Evaluated `.renovate/` config split (improvement 6) — determined it requires proper Renovate local preset format (not a raw file drop), adds real complexity at the current file size (~282 lines); deferred with a threshold of ~400 lines
- Expanded the existing ROADMAP stub for the Renovate config split with correct preset mechanics, exact `extends` syntax, concrete per-file split plan, and trigger threshold

### Files changed
| File | Change |
|------|--------|
| `renovate.json5` | Auto-merge rules (Helm patch + digest), kustomize regex fix, 5 new group rules, 5-day soak on Talos/K8s |
| `docs/ROADMAP.md` | Expanded Renovate config split entry with local preset mechanics and step-by-step implementation guide |

### Key decisions
- Excluded `siderolabs/installer` and `siderolabs/kubelet` from digest auto-merge — even a same-SHA digest refresh on those images warrants awareness given they go through tuppr's upgrade machinery
- Chose 5-day soak for Talos/K8s (vs 3-day for charts) — OS and runtime regressions are harder to recover from and community reports tend to appear later than chart issues
- Deferred `.renovate/` split: the key non-obvious blocker is that split files must be valid Renovate presets referenced via `extends`, not raw fragments auto-scanned from the directory — the refactor has real cost and the file is still manageable

---

## 2026-05-22 — `talos-audit-ntp`

### Goal
Cluster health check and Talos config/schematic audit via cluster-doctor; implement the NTP server expansion (Finding 2.6) with 4 EU/NL-prioritised sources applied live across all nodes.

### What we did
- Reviewed cluster status and roadmap after a 2-day gap; confirmed Green health and identified Talos config/schematic audit as the top priority before proceeding with new deployments
- Ran cluster-doctor agent for combined live cluster health audit + full Talos config/schematic review:
  - All 3 nodes Ready (Talos v1.13.2, K8s v1.36.1); all 26 Kustomizations + 17 HelmReleases True; both Longhorn volumes Healthy on cp-01 + cp-03
  - Elevated restart counts on several pods identified as historical artefacts from the 2026-05-15 recovery incident, not ongoing instability
  - Schematic verified clean: `iscsi-tools`, `util-linux-tools`, `intel-ucode`, `amd-ucode` all present; no missing extensions for the hardware profile
  - Sysctls (10 GbE socket buffers), NFS defaults, etcd subnet restrictions, cluster.yaml, machine-features all verified correct
  - 6 findings produced: 2.1 (bond driver-glob selectors on cp-01/cp-02), 2.6 (only 2 NTP sources), 2.3/2.5 deferred, 3.x acceptable-as-is
- Planned and implemented Finding 2.6 — expanded NTP from 2 to 4 sources with EU/NL preference:
  - Added `ntp.time.nl` (SIDN/NLNOG Dutch stratum 1) and `nl.pool.ntp.org` (NL zone pool) to replace generic `pool.ntp.org`; kept `time.cloudflare.com`; added `time.google.com` for AS diversity
  - Applied staggered (cp-01 → cp-02 → cp-03); all nodes applied without reboot and stayed Ready throughout
  - Verified: `TimeServerStatus` shows all 4 servers on all 3 nodes; `TimeStatus SYNCED: true` on all nodes

### Files changed
| File | Change |
|------|--------|
| `talos/patches/global/machine-time.yaml` | Expanded NTP servers from 2 to 4 (EU/NL preference) |

### Key decisions
- Chose `ntp.time.nl` (operated by SIDN + NLNOG) as the primary NL-specific source — the most authoritative Dutch stratum-1 server available publicly, not a generic pool alias
- Replaced `pool.ntp.org` with `nl.pool.ntp.org` for geographic locality; kept `time.cloudflare.com` (AS13335) and added `time.google.com` (AS15169) so the two anycast sources come from independent autonomous systems
- 4 distinct sources unlocks chrony's Marzullo algorithm for falseticker detection; with only 2 sources chrony can detect disagreement but cannot identify which server is wrong

---

## Archived sessions

Sessions older than **2026-05-22** (the bootstrap/setup era, **2026-05-06 → 2026-05-21**) have been moved to [SESSIONS-ARCHIVE.md](SESSIONS-ARCHIVE.md) to keep this active log lean. Grep the archive the same way you grep this file.
