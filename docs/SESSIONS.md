# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

---

## 2026-05-13 — `longhorn-1.11.2-upgrade`

### Goal
Execute the Longhorn 1.9.0 → 1.11.2 upgrade: fix two blocking defects in the helmrelease (missing `crds: CreateReplace`, tight instance-manager memory limit), verify CRD storedVersions on the live cluster, push fixes to the PR #19 branch, merge, and reconcile.

---

## 2026-05-13 — `pr-19-review`

### Goal
Review PR #19 (Longhorn 1.9.0 → 1.11.2) via the pr-upgrade-reviewer agent to assess upgrade risk before merging.

### What we did
- Fetched PR #19 (Renovate-generated, Longhorn 1.9.0 → 1.11.2, two minor version steps)
- Retrieved release notes across the full version chain (1.9.x → 1.10.x → 1.11.x)
- Identified two blocking issues:
  1. Missing `crds: CreateReplace` in both `install` and `upgrade` blocks of the HelmRelease (project convention violation and functional defect — CRD schemas have been frozen since first install)
  2. v1.10.0 permanently removed `v1beta1` API; storedVersions in etcd must be verified/migrated before the upgrade hook will allow proceeding, even when jumping directly to 1.11.2
- Identified medium risks: tight instance-manager memory limits (`64Mi`) may OOMKill under 1.11.x disk-health monitoring; stale values.yaml settings key (`orphanAutoDeletion`)
- Confirmed v1.11.2 images are published; K8s v1.36.x compatibility clear; rollback is complex but not a one-way migration

### Files changed
| File | Change |
|------|--------|
| `docs/SESSIONS.md` | Added this session entry |
| `CLAUDE.md` | Added session row to log table |

### Key decisions
- Verdict: do not merge PR #19 until `crds: CreateReplace` is added to the HelmRelease and the v1beta1 storedVersions check passes on the live cluster

---

## 2026-05-13 — `openebs-4.4.0-upgrade`

### Goal
Verify the OpenEBS 4.3.2 → 4.4.0 minor upgrade (PR #18) reconciled cleanly after merge.

### What we did
- Reviewed PR #18 via `pr-upgrade-reviewer` agent — assessed as low-risk (LocalPV Hostpath only; all other engines disabled)
- Merged PR #18; confirmed Flux had not yet picked up the new tag (OCIRepository still at 4.3.2 on 1h interval)
- Force-reconciled the chain: `flux reconcile source git flux-system` → `flux reconcile ks cluster-meta --with-source`
- OCIRepository updated to `4.4.0`, cosign signature verified
- HelmRelease upgraded to `openebs/openebs.v2` with chart `openebs@4.4.0` (`UpgradeSucceeded`)
- `openebs-localpv-provisioner` pod recycled cleanly (0 restarts, label `chart=localpv-provisioner-4.4.0`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/openebs.yaml` | OCI tag bumped `4.3.2` → `4.4.0` (via PR #18) |

### Key decisions
- No pre-merge steps were needed; `crds: CreateReplace` already in place from the previous session meant CRD schema updates were handled automatically

---

## 2026-05-13 — `openebs-oci-source-fix`

### Goal
Diagnose and fix the broken `OCIRepository/openebs` source in `flux-system` so Flux can reconcile OpenEBS again (currently stuck with "does not have an artifact").

### What we did
- Inspected live cluster state: `OCIRepository/openebs` was actually Ready (artifact stored, cosign verified); the problem was in the `HelmRelease`
- Root cause: timing race — HelmRelease reconcile checked the OCIRepository at `12:45:08Z`, 30 seconds before the OCI artifact was stored at `12:45:38Z`; HelmRelease got stuck in `SourceNotReady` until its next 1h cycle
- Forced an immediate reconcile with `flux reconcile helmrelease openebs -n openebs` — resolved successfully (`applied revision 4.3.2`)
- Added missing `crds: CreateReplace` to both `install` and `upgrade` blocks in `helmrelease.yaml` (required by CLAUDE.md convention for operator charts that ship CRDs)
- Removed completed roadmap item; added entry to Completed table

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/openebs/openebs/app/helmrelease.yaml` | Added `crds: CreateReplace` to `install` and `upgrade` blocks |
| `docs/ROADMAP.md` | Removed OpenEBS OCIRepository fix item from In Progress; added to Completed |

### Key decisions
- The OCIRepository timing race is inherent to async Flux controllers with matching 1h intervals; no structural fix is needed — `flux reconcile` is the correct operational response
- `crds: CreateReplace` is a correctness fix, not cosmetic — Helm silently leaves old CRD schemas in place on upgrade without it

---

## 2026-05-13 — `claude-md-session-lifecycle`

### What we did
- Added a mandatory `## Session Lifecycle` section to `CLAUDE.md` defining the open/close protocol
- Defined the stub format (slug, `### Goal`, separator) that must be prepended to `docs/SESSIONS.md` at session start
- Defined the close steps: replace Goal with `### What we did` + `### Files changed` + optional `### Key decisions`; update the CLAUDE.md session log table summary
- Added a note for interrupted sessions (stub is still useful — complete it next session under the same slug)
- Opened and closed this session as a live demonstration of the new workflow

### Files changed
| File | Change |
|------|--------|
| `CLAUDE.md` | Added `## Session Lifecycle` section; added `claude-md-session-lifecycle` row to session log table |
| `docs/SESSIONS.md` | Prepended this session stub; completed on close |

### Key decisions
- Placed Session Lifecycle as its own `##` section (not bullets inside "Working in This Repo") to make it prominent and easy to find via heading navigation
- Kept the stub format minimal — just a slug, date, and `### Goal` — so opening a session has near-zero friction

---

## 2026-05-13 — `kubernetes-upgrade-v1.35-v1.36`

### What we did
- Executed the v1.35.4 upgrade using the manual staggered approach (Phase 2: `talosctl patch mc`
  per node, 2-minute stable-PID verification; Phase 3: `upgrade-k8s` for remaining components)
- Fixed a pre-existing `KubernetesUpgrade` CRD stuck in `Upgrading` phase targeting v1.33.11
  (result of a prior revert commit that Flux reconciled before the re-upgrade commit was pushed;
  the CRD's admission webhook blocked Flux from updating the spec while Upgrading was in progress)
- Executed the v1.36.0 upgrade using the tuppr-native path (merged Renovate PR #13; tuppr ran
  `upgrade-k8s` automatically via a job pod; no manual steps required; validated as safe)
- Documented two operational patterns in QA.md: the `KubernetesUpgrade` mismatch/cleanup pattern
  (manual upgrade-ahead-of-Git) and the v1.34.7 crash loop root cause (gRPC etcd connection flood)
- Added Kubernetes upgrade operational rules to CLAUDE.md (preferred tuppr-native path, manual
  fallback procedure, KubernetesUpgrade cleanup command)
- Removed `TROUBLESHOOTING.md` (session-scoped runbook); all durable knowledge migrated to
  `QA.md` and `CLAUDE.md`
- Updated `scripts/mcp.sh` for reliable MCP token management

### Files changed
| File | Change |
|------|--------|
| `talos/talenv.yaml` | `kubernetesVersion`: v1.34.7 → v1.35.4 → v1.36.0 |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/kubernetesupgrade.yaml` | `spec.kubernetes.version`: v1.34.7 → v1.35.4 → v1.36.0 |
| `QA.md` | Added: tuppr downgrade-job mismatch pattern; v1.34.7 crash loop root cause |
| `CLAUDE.md` | Expanded upgrade-path bullet with operational rules; added session log entries |
| `TROUBLESHOOTING.md` | Removed (content migrated to QA.md and CLAUDE.md) |
| `scripts/mcp.sh` | Updated by user for reliable MCP token management |

### Key decisions
- **tuppr-native path is preferred** for all future Kubernetes minor upgrades: merge the Renovate
  PR and let tuppr handle it. Manual `patch mc` only needed if a crash loop is observed on the
  first node patched.
- **KubernetesUpgrade mismatch cleanup**: if you ever run `upgrade-k8s` manually ahead of Git,
  delete the `KubernetesUpgrade` resource before Flux reconcile to avoid the downgrade-job loop.

---

## 2026-05-13 — `kubernetes-upgrade-v1.34-crash-recovery`

### What we did
- Diagnosed cluster fully down: all 3 apiservers still on v1.34.7 and crash-looping (not reverted
  as expected from the prior session's runbook); VIP (10.60.0.2) down; etcd healthy throughout
- Root cause: `kube-apiserver v1.34.7` opens ~100 gRPC channels to etcd simultaneously at startup,
  overwhelming TLS handshake queue → `rbac/bootstrap-roles` PostStartHook fatal timeout; three
  nodes upgraded simultaneously caused synchronised backoff waves preventing recovery
- Reverted all 3 apiservers to v1.33.11 via staggered `talosctl patch mc` (one node at a time,
  strategic merge form); removed removed feature gates (`MutatingAdmissionPolicy`, `v1alpha1`
  runtime-config) from `talos/patches/controller/cluster.yaml`
- Re-upgraded to v1.34.7 using same staggered approach with 2-minute stable-PID verification
  per node; cluster recovered successfully
- Wrote `TROUBLESHOOTING.md` as the v1.35.4 forward-looking upgrade runbook (later removed this
  session and migrated content to QA.md)

### Files changed
| File | Change |
|------|--------|
| `talos/patches/controller/cluster.yaml` | Removed `MutatingAdmissionPolicy=true` and `admissionregistration.k8s.io/v1alpha1` feature gates |
| `talos/talenv.yaml` | v1.34.7 → v1.33.11 (revert) → v1.34.7 (re-upgrade) |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/kubernetesupgrade.yaml` | same version churn |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/talosupgrade.yaml` | corrected stale v1.10.6 → v1.13.0 |

---

## 2026-05-13 — `longhorn-psa-fix`

### What we did
- Diagnosed Longhorn as completely non-functional as a CSI provider due to missing PodSecurity
  Admission (PSA) namespace label on `longhorn-system`
- Kubernetes PSA was enforcing the `baseline` policy on unlabelled namespaces; Longhorn requires
  `privileged` because its core components use `securityContext.privileged=true`, `SYS_ADMIN`
  capability, and `hostPath` volumes (required for CSI mount operations)
- Root cause: the `longhorn-system` namespace manifest in Git lacked
  `pod-security.kubernetes.io/enforce: privileged`; the label is not set automatically by the
  Longhorn Helm chart — it must be declared on the namespace resource in Git
- Diagnosis performed by cluster-doctor agent (read-only); agent identified PSA as the
  single root error via pod events (`FailedCreate` on `longhorn-csi-plugin` DaemonSet), confirmed
  by the cascade: no CSI socket → all CSI sidecars (attacher, provisioner, resizer, snapshotter)
  in CrashLoopBackOff; only cp-02 instance-manager survived (predated enforcement trigger)
- **No PVCs existed** — no data was at risk
- Fixed by adding `pod-security.kubernetes.io/enforce/warn/audit: privileged` to `namespace.yaml`;
  setting all three levels ensures audit/warn visibility as well as enforcement parity
- Fix survives Flux reconciliation because the label is declared in the namespace manifest in Git
  (Flux drift detection would overwrite any imperatively-added label)

### Probable trigger
The Kubernetes version revert (`e49c556`, `v1.34.7 → v1.33.11`) likely left a stricter cluster-level
PSA default than was previously active. The namespace label was never in Git — the Helm chart
doesn't set it — and the deployment appeared to work before because PSA was not previously
enforcing `baseline` as the cluster default.

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/longhorn-system/longhorn/app/namespace.yaml` | Add PSA `enforce/warn/audit: privileged` labels |

---

## 2026-05-12 — `talos-upgrade-v1.10-to-v1.13`

### What we did
- Analysed Renovate PR for `ghcr.io/siderolabs/installer` (`v1.10.6 → v1.13.1`); determined safe
  incremental path: `v1.10.6 → v1.11.6 → v1.12.7 → v1.13.0`
  - `v1.13.1` was a git tag but not a published GitHub release or Docker image — Renovate tracked
    the tag; closed/ignored in favour of targeting `v1.13.0` (latest actual release)
- **Fixed Taskfile bug** in `talos:upgrade-node`: `--image` was passed twice — once by
  `talhelper gencommand upgrade` (correct, with `:v<version>` tag) and once via `--extra-flags`
  (versionless, would override via cobra last-wins). Removed the redundant `--extra-flags` image
  arg and the now-unused `TALOS_IMAGE` var
- **Fixed `admission-controller-patch.yaml`**: was a JSON RFC 6902 `op: remove` patch; Talos v1.12
  introduced multi-document machine configs and talhelper now rejects JSON 6902 patches for them.
  Converted to strategic merge patch (`admissionControl: []`)
- Upgraded all 3 nodes through each hop one at a time (preserving etcd quorum); used
  `mise exec talosctl@<current-server-version>` for each hop; confirmed ±1 minor version skew
  is fine (ENHANCE_YOUR_CALM only occurs beyond ±1 minor)
- Cluster now fully on Talos `v1.13.0`, kernel `6.18.24-talos`, containerd `2.2.3`

### Files changed
| File | Change |
|------|--------|
| `talos/talenv.yaml` | `talosVersion`: `v1.10.6` → `v1.13.0` |
| `.taskfiles/talos/Taskfile.yaml` | `upgrade-node`: remove redundant `--image` extra-flag and `TALOS_IMAGE` var |
| `talos/patches/controller/admission-controller-patch.yaml` | Convert JSON 6902 `op: remove` to strategic merge `admissionControl: []` |

---

## 2026-05-12 — `purge-failed-pods-script`

### What we did
- Created `scripts/purge-failed-pods.sh` — walks the ownership chain (Pod → ReplicaSet →
  Deployment/DaemonSet/StatefulSet), verifies controller health before deleting, and defaults to
  dry-run mode; pass `--delete` to apply
- Added `task purge-failed-pods` to root `Taskfile.yaml` with `DELETE=true` var mirroring the
  script flag; follows the same `VAR=value` convention as `INSECURE=true` in `talos:apply`
- Updated `QA.md` — extended the Cluster Recovery / Unclean Shutdown fix section with a reference
  to the script, the task invocation, and the health criteria used per controller kind

### Files changed
| File | Change |
|------|--------|
| `scripts/purge-failed-pods.sh` | NEW — dry-run/live pod cleanup script |
| `Taskfile.yaml` | Add `purge-failed-pods` task |
| `QA.md` | Extend unclean-shutdown fix section with script/task reference |

---

## 2026-05-12 — `tuppr-upgrade-controller-deployment`

### What we did
- Researched automated Talos + Kubernetes upgrade tooling; selected **tuppr** (home-operations/tuppr
  v0.1.26) as the community-standard GitOps-native successor to the archived `jfroy/tnu`
- Deployed tuppr: OCIRepository source, Flux Kustomization pair, HelmRelease with `crds:
  CreateReplace`, `TalosUpgrade` + `KubernetesUpgrade` CRD instances pinned to current running
  versions (v1.10.6 / v1.33.4) — upgrades are idle until Renovate bumps them
- Updated Renovate config: removed `installer` + `kubelet` from `ignoreDeps`; replaced single
  grouped rule with two separate `separateMinorPatch: true` rules to prevent dangerous minor-skip PRs
- **Fixed two rollout errors discovered during live reconciliation:**
  1. **cosign verification failure** — copied `verify: provider: cosign` from openebs OCIRepository
     without checking; `charts/` (first-party) is unsigned, only `charts-mirror/` is cosign-signed;
     required patching the live OCIRepository resource directly to break cluster-meta's frozen
     health-check before flux reconcile could proceed
  2. **CRD chicken-and-egg dry-run failure** — `TalosUpgrade`/`KubernetesUpgrade` instances were
     in the same Kustomization as the HelmRelease; Flux dry-runs all resources before applying any,
     so the CRD types didn't exist yet; fixed by splitting into two Kustomizations with `dependsOn`
- Researched `.archive` for CRD ordering patterns; confirmed split-Kustomization + `dependsOn` is
  the canonical approach; refactored to archive convention of multi-document `ks.yaml`
- Added five Q&A entries to `QA.md`: CRD chicken-and-egg, `crds: CreateReplace`, cosign registry
  split, `valuesFrom` + configMapGenerator + kustomizeconfig.yaml, Renovate minor vs patch PRs
- Added ToC to `QA.md`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/tuppr.yaml` | NEW — OCIRepository for tuppr chart (no cosign) |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Add tuppr.yaml |
| `kubernetes/apps/system-upgrade/kustomization.yaml` | NEW — namespace-level entry-point |
| `kubernetes/apps/kustomization.yaml` | Add system-upgrade |
| `kubernetes/apps/system-upgrade/tuppr/ks.yaml` | NEW — multi-doc: tuppr + tuppr-upgrade Kustomizations |
| `kubernetes/apps/system-upgrade/tuppr/app/kustomization.yaml` | NEW — configMapGenerator + helmrelease |
| `kubernetes/apps/system-upgrade/tuppr/app/namespace.yaml` | NEW |
| `kubernetes/apps/system-upgrade/tuppr/app/helmrelease.yaml` | NEW — `crds: CreateReplace` |
| `kubernetes/apps/system-upgrade/tuppr/app/helm/values.yaml` | NEW |
| `kubernetes/apps/system-upgrade/tuppr/app/helm/kustomizeconfig.yaml` | NEW — valuesFrom name rewrite |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/kustomization.yaml` | NEW |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/talosupgrade.yaml` | NEW — v1.10.6, parallelism: 1 |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/kubernetesupgrade.yaml` | NEW — v1.33.4 |
| `renovate.json5` | Remove installer+kubelet from ignoreDeps; add per-package separateMinorPatch rules |
| `talos/patches/controller/machine-features.yaml` | Comment: system-upgrade-controller → tuppr |
| `QA.md` | Add ToC; add 5 new entries covering rollout lessons |

### Notes
- Cluster bootstraps cleanly from current repo state: `dependsOn` ordering guarantees CRDs are
  registered before instances are applied on a fresh install
- Next Renovate PRs for Talos/k8s will target `talosupgrade.yaml` and `kubernetesupgrade.yaml`;
  merge one minor at a time (Talos and Kubernetes both require sequential minor upgrades)

---

## 2026-05-12 — `qa-log-and-eth0-rename`

### What we did
- Explained the `eth0: renamed from tmp<random>` kernel messages visible in the Talos console on
  cp-03 — confirmed normal CNI behaviour (Cilium veth pair creation for pod networking), not errors
- Created `QA.md` — a persistent log of operational Q&A capturing cluster-specific behaviours
  that look alarming but aren't, plus actionable signals for when they would indicate a real problem
- Added a reference to `QA.md` in `CLAUDE.md` alongside the existing CLUSTER.md and SESSIONS.md pointers

### Files changed
| File | Change |
|------|--------|
| `QA.md` | NEW — operational Q&A log; first entry: eth0 rename messages |
| `CLAUDE.md` | Add `QA.md` reference in the intro doc-pointer block |

---

## 2026-05-12 — `storage-storageclasses-and-conventions`

### What we did
- Added `longhorn-retain` StorageClass — identical parameters to the default `longhorn` class but
  with `reclaimPolicy: Retain`; for stateful workloads where accidental PVC deletion must not
  silently destroy data (databases, media libraries)
- Added `longhorn-single` StorageClass — single replica, `reclaimPolicy: Retain`; for workloads
  that manage their own application-level replication (CloudNativePG streaming replication, Redis
  Sentinel) to avoid double replication overhead
- Added doc-comment convention to CLAUDE.md: all cluster YAML should carry comments explaining
  the *why* of non-obvious values, provisional settings, and operational implications
- Discussed and clarified: `Recreate` vs `RollingUpdate` for RWO PVCs; `longhorn` vs
  `longhorn-static` StorageClass differences; reclaim policy scoping (StorageClass vs PV);
  double replication trade-off with CNPG; `staleReplicaTimeout` behaviour

### Final StorageClass inventory
| StorageClass | Reclaim | Replicas | Use case |
|---|---|---|---|
| `longhorn` *(default)* | Delete | 2 | Ephemeral/replaceable volumes |
| `longhorn-retain` | Retain | 2 | Stateful workloads, irreplaceable data |
| `longhorn-single` | Retain | 1 | App-managed replication (CNPG, Redis Sentinel) |
| `longhorn-static` | Delete | — | Manual static binding / disaster recovery |
| `openebs-hostpath` | Delete | — | Node-local scratch volumes |

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/longhorn-system/longhorn/app/storageclass-retain.yaml` | NEW |
| `kubernetes/apps/longhorn-system/longhorn/app/storageclass-single.yaml` | NEW |
| `kubernetes/apps/longhorn-system/longhorn/app/kustomization.yaml` | Add both new StorageClasses |
| `CLAUDE.md` | Add doc-comment convention under GitOps Conventions |

### Notes
- `numberOfReplicas: "2"` in both new StorageClasses must be bumped to `"3"` when cp-02 drive
  arrives (same trigger as the Longhorn HelmRelease values)
- `staleReplicaTimeout: 30` means replicas offline >30 min are rebuilt from scratch rather than
  incrementally re-synced; fine for home lab, raise to 120 for longer maintenance windows

---

## 2026-05-12 — `persistent-storage-deploy-and-fix`

### What we did
- Committed all prior session changes (3 commits: Talos prereqs, K8s app layer, docs) and pushed to origin
- Ran `task reconcile` — Flux pulled the new manifests and attempted to deploy both apps
- Diagnosed two errors:
  - **openebs**: `namespaces "openebs" not found` — `install.createNamespace: true` is a Helm directive and runs too late; Flux needs the namespace to already exist when it applies the HelmRelease CR
  - **longhorn**: `ConfigMap/longhorn-values namespace not specified` — configMapGenerator entry lacked an explicit `namespace: longhorn-system`
- Fixed both by adding explicit `Namespace` resources to each app's `app/` directory and wiring them into `kustomization.yaml`; also added `namespace: longhorn-system` to the configMapGenerator
- Pushed fix commit, reconciled — both HelmReleases installed successfully within ~30 seconds

### Result
- **OpenEBS**: `openebs-hostpath` StorageClass live (non-default, WaitForFirstConsumer)
- **Longhorn**: `longhorn` StorageClass live (default, WaitForFirstConsumer), 2-replica mode; full pod stack running on all 3 nodes
- **StorageClasses**: `longhorn` (default), `longhorn-static`, `openebs-hostpath`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/openebs/openebs/app/namespace.yaml` | NEW — explicit Namespace for openebs |
| `kubernetes/apps/openebs/openebs/app/kustomization.yaml` | Add `./namespace.yaml` to resources |
| `kubernetes/apps/longhorn-system/longhorn/app/namespace.yaml` | NEW — explicit Namespace for longhorn-system |
| `kubernetes/apps/longhorn-system/longhorn/app/kustomization.yaml` | Add `./namespace.yaml`; add `namespace: longhorn-system` to configMapGenerator |

### Remaining step (cp-02 drive)
When the Crucial P310 1TB 2230 arrives:
1. `talosctl get disks --nodes 10.60.0.202` → grab serial
2. Add inline `machine.disks` patch for cp-02 in `talos/talconfig.yaml` (matching cp-01/cp-03 by-id pattern)
3. `task talos:apply IP=10.60.0.202`
4. Set `allowScheduling: true` in `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-02.yaml`
5. Bump `defaultClassReplicaCount` and `defaultReplicaCount` from `2` → `3` in `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml`

---

## 2026-05-07 — `persistent-storage-k8s-app-layer`

### What we did
- Created the full Flux GitOps app layer for **OpenEBS LocalPV** and **Longhorn** — both are now
  committed and ready to reconcile once pushed to the repo
- Added two new Flux sources to `kubernetes/flux/meta/repos/`:
  - `oci/openebs.yaml` — OCIRepository pointing to `ghcr.io/home-operations/charts-mirror/openebs`
    tag `4.3.2`, cosign-verified
  - `helm/longhorn.yaml` — HelmRepository pointing to `https://charts.longhorn.io`
- Created `kubernetes/apps/openebs/` — full Flux Kustomization + HelmRelease for OpenEBS LocalPV:
  - `openebs-hostpath` StorageClass, non-default, base path `/var/mnt/openebs/local` (EPHEMERAL)
  - All engines except `localpv-provisioner` disabled; no snapshot-controller dependency
- Created `kubernetes/apps/longhorn-system/` — full Flux Kustomization + HelmRelease + node-configs:
  - Chart pinned at `1.9.0` from the longhorn HelmRepository
  - `defaultClassReplicaCount: 2` and `defaultReplicaCount: 2` (provisional — cp-02 has no drive
    yet; bump both to 3 when Crucial P310 arrives)
  - talos-cp-01 and talos-cp-03 node-configs: `allowScheduling: true` (drives mounted)
  - talos-cp-02 node-config: `allowScheduling: false` (drive pending; won't attempt replica placement)
  - Values passed via configMapGenerator + `kustomizeconfig.yaml` nameReference pattern
  - `csi.kubeletRootDir: /var/lib/kubelet` (Talos requirement)
  - Control-plane tolerations on longhornManager, longhornDriver, longhornInstanceManager
- Wired up `kubernetes/apps/kustomization.yaml` — added `./openebs` and `./longhorn-system`
- Both Flux Kustomization CRs placed in `flux-system` namespace (not app namespaces) to avoid
  bootstrap chicken-and-egg: a CR in e.g. `openebs` namespace can't be stored before that
  namespace exists; `flux-system` always exists and HelmRelease uses `createNamespace: true`
- Both ks.yaml files carry `substitution.flux.home.arpa/disabled: "true"` to opt out of the
  cluster-apps postBuild substitution patch (cluster-settings/cluster-secrets don't exist yet)

### Files created / modified
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/openebs.yaml` | NEW — OCIRepository for openebs chart |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added openebs |
| `kubernetes/flux/meta/repos/helm/longhorn.yaml` | NEW — HelmRepository for longhorn chart |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Added longhorn |
| `kubernetes/apps/kustomization.yaml` | Added `./openebs` and `./longhorn-system` |
| `kubernetes/apps/openebs/kustomization.yaml` | NEW — namespace-level kustomization |
| `kubernetes/apps/openebs/openebs/ks.yaml` | NEW — Flux Kustomization CR |
| `kubernetes/apps/openebs/openebs/app/kustomization.yaml` | NEW |
| `kubernetes/apps/openebs/openebs/app/helmrelease.yaml` | NEW — HelmRelease |
| `kubernetes/apps/longhorn-system/kustomization.yaml` | NEW — namespace-level kustomization |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | NEW — Flux Kustomization CR |
| `kubernetes/apps/longhorn-system/longhorn/app/kustomization.yaml` | NEW — configMapGenerator |
| `kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml` | NEW — HelmRelease |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | NEW — Longhorn values |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/kustomizeconfig.yaml` | NEW — nameReference |
| `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-01.yaml` | NEW |
| `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-02.yaml` | NEW — `allowScheduling: false` |
| `kubernetes/apps/longhorn-system/longhorn/app/node-configs/talos-cp-03.yaml` | NEW |

### Decisions made

**Flux Kustomization CRs in `flux-system`, not app namespaces**
On a fresh cluster, placing a Flux Kustomization CR in e.g. `longhorn-system` fails because
that namespace doesn't exist yet — the CR cannot be stored. Keeping all CRs in `flux-system`
(which always exists) and relying on `HelmRelease.install.createNamespace: true` eliminates
the bootstrapping deadlock entirely.

**No `spec.targetNamespace` on Longhorn Kustomization**
Longhorn's node-config files contain `kind: Node` objects, which are cluster-scoped (no
namespace). Setting `targetNamespace` would cause Kustomize to inject a namespace onto them,
which the Kubernetes API server rejects. Each resource declares its own namespace explicitly.

**`defaultClassReplicaCount: 2` until cp-02 hardware arrives**
With only 2 nodes having storage disks, a 3-replica PVC cannot be scheduled. Setting to 2
means Longhorn can provision volumes immediately on cp-01/cp-03. When cp-02's Crucial P310
1TB 2230 is installed, update both `defaultClassReplicaCount` and `defaultReplicaCount` to 3
and flip `allowScheduling: true` in `node-configs/talos-cp-02.yaml`.

### Next steps when resuming
1. `git push` → Flux will reconcile and deploy OpenEBS and Longhorn
2. Verify: `kubectl get helmrelease -A` and `kubectl get storageclass`
3. Test with a PVC against `openebs-hostpath` and `longhorn` storage classes
4. When cp-02's Crucial P310 arrives:
   - `talosctl get disks --nodes 10.60.0.202` → grab serial
   - Add inline `machine.disks` patch for cp-02 in `talos/talconfig.yaml`
   - `task talos:apply IP=10.60.0.202`
   - Set `allowScheduling: true` in `node-configs/talos-cp-02.yaml`
   - Bump `defaultClassReplicaCount` and `defaultReplicaCount` to `3` in `helm/values.yaml`

---

## 2026-05-07 — `persistent-storage-talos-prereqs`

### What we did
- Decided on dual storage tier: **OpenEBS LocalPV** (node-local, no replication) + **Longhorn** (3-replica HA) — complementary, not redundant
- Added `siderolabs/iscsi-tools` and `siderolabs/util-linux-tools` to `talos/schematic.yaml`
- Added per-node inline `machine.disks` patches to `talconfig.yaml` for cp-01 and cp-03 using
  `/dev/disk/by-id/` serial-based paths (more robust than device-path selectors)
- Diagnosed cp-02's missing storage disk — confirmed physically not installed (Crucial P310 1TB
  2230 + M.2 A/E adapter ordered; not a hardware fault, just not yet installed)
- Re-registered schematic at factory.talos.dev → new ID:
  `1aaf751348ca0f837eca199fa21933d3375641d972f9fb0d816e7bf87c81f1fc`
- Rolling apply + upgrade across all three nodes (one at a time to preserve etcd quorum):
  - cp-01: config applied with reboot (disk patch diff); then OS upgraded; `ext-iscsid` confirmed started; `/var/mnt/longhorn-storage` mounted XFS on `/dev/nvme1n1p1`
  - cp-02: config applied without reboot (no disk patch); OS upgraded; `ext-iscsid` confirmed started
  - cp-03: config applied with reboot (disk patch diff); then OS upgraded; disk enumeration swapped
    (nvme0n1 ↔ nvme1n1) but by-id path targeted the correct Crucial drive — `/var/mnt/longhorn-storage`
    mounted XFS on `/dev/nvme0n1p1` (2 TB Crucial, now enumerated as nvme0n1)
- Fixed bug in `bootstrap:cluster`: shell `task talos:genconfig` calls replaced with `task:` map
  references; `dir:` removed from the task; all paths made absolute — prevents spurious `talos/talos/`
  directory creation caused by CWD ambiguity when subtasks were called as shell subprocesses
- Removed stale `talos/talos/clusterconfig/` artifact (empty talosconfig left by the bug above)
- Updated `CLUSTER.md` disk inventory with correct drive models, by-id paths, and cp-02 status
- Used `talosctl@1.10.6` (via `mise exec`) for upgrade commands — required due to client (1.13.0) /
  server (1.10.6) version mismatch causing `ENHANCE_YOUR_CALM` gRPC errors with the default client

### Files created / modified
| File | Change |
|------|--------|
| `talos/schematic.yaml` | Enabled `iscsi-tools` and `util-linux-tools` extensions |
| `talos/talconfig.yaml` | Per-node inline `machine.disks` patches for cp-01 (IRP-SSDPR serial `G4E004578`) and cp-03 (CT2000P310SSD8 serial `252450B1A33B`) |
| `talos/talenv.yaml` | Auto-updated by `task talos:iso` with new schematic `talosImageURL` |
| `CLUSTER.md` | Corrected disk inventory: GoodRam IRDM PRO NANO on cp-01 (via M.2 A/E adapter), Crucial P310 on order for cp-02, Crucial CT2000P310SSD8 on cp-03; by-id paths documented |
| `ROADMAP.md` | Updated hardware snapshot; moved Persistent Storage to In Progress |
| `.taskfiles/bootstrap/Taskfile.yaml` | Fixed `bootstrap:cluster`: shell `task` calls → `task:` references; `dir:` removed; gensecret command uses absolute `{{.TALOS_DIR}}` paths throughout |

### Decisions made

**Per-node by-id serial paths over global `/dev/nvme1n1`**
A global patch using the device path would have partitioned the wrong disk on cp-03 when its
NVMe enumeration order swapped after the upgrade (AirDisk and Crucial switched positions). Serial-
based `/dev/disk/by-id/nvme-<MODEL>_<SERIAL>` paths are stable across enumeration changes and are
the correct approach for bare-metal NVMe on any multi-drive node.

**cp-02 Longhorn deployment gated on drive arrival**
cp-02 has no storage disk installed. Longhorn 3-replica requires a disk on all three nodes to
place replicas. cp-02 will be configured when the Crucial P310 1TB 2230 arrives: run
`talosctl get disks --nodes 10.60.0.202`, grab the serial, add an inline patch matching cp-01/cp-03
pattern, then `task talos:apply IP=10.60.0.202` (no upgrade needed — already on the new schematic).

**OpenEBS can deploy immediately; Longhorn waits for cp-02**
OpenEBS LocalPV needs no dedicated disk — it uses EPHEMERAL hostpath. It can be deployed now
to unblock node-local workloads. Longhorn HelmRelease can be committed to Git now; it will just
sit unscheduled on cp-02 until the disk lands.

### Lessons learned

**go-task: always use `task:` map syntax for subtask invocations, never shell `task` commands**
When a task has `dir:` set and calls subtasks as shell commands (`- task foo`), the `task` binary
is spawned as a subprocess inheriting the modified CWD. Depending on go-task version and how
ROOT_DIR is resolved from that CWD, relative path variables can double up (e.g., `talos/talos/`).
Using `- task: foo` (map key syntax) invokes the subtask directly within go-task's own process —
no subprocess, no CWD ambiguity, variables always resolved from the root Taskfile.

**NVMe enumeration can change across reboots even without hardware changes**
cp-03's nvme0n1 (AirDisk) and nvme1n1 (Crucial) swapped after the upgrade reboot. Device paths
are not stable on bare-metal NVMe. `installDiskSelector: model:` and `machine.disks: device: /dev/disk/by-id/`
are the two stable mechanisms in Talos — use them everywhere, never raw `/dev/nvme*` paths.

**`talosctl disks` deprecated in newer clients; use `talosctl get disks`**
The `talosctl disks` subcommand is deprecated in Talos 1.10+ clients and exits with code 1.
Use `talosctl get disks` (or `talosctl get discoveredvolumes` for partition-level detail).

---

## 2026-05-07 — `etcd-learner-recovery-and-toolchain`

### What we did
- Diagnosed why cp-03 KVM console showed `STAGE: Booting READY: False` after disk migration
- Root cause: LACP was disabled on switch ports during ISO maintenance boot so the bare NIC could
  get DHCP connectivity; cp-03 received `10.60.0.16` via DHCP and advertised it as an etcd peer
  URL alongside the correct static IP `10.60.0.203` — both URLs got permanently recorded in the
  etcd member list for the LEARNER entry
- Once LACP was restored, `10.60.0.16` no longer existed; the LEARNER could never be promoted
  because etcd couldn't reach all its own peer URLs
- Fixed in three steps:
  1. `talosctl etcd remove-member <stale-id>` — removed the corrupt LEARNER entry; cp-03 immediately
     re-added itself with only the correct `10.60.0.203` peer URL
  2. Waited for raft log sync (raft applied index matched across all three nodes within seconds)
  3. Manually promoted via `etcdctl member promote <member-id-hex>` — Talos does not auto-promote
     LEARNER members and has no `talosctl etcd promote` subcommand
- Added `etcd = "3.5.21"` to `.mise.toml` (version must track Talos-bundled etcd — check with
  `talosctl etcd status` after any Talos upgrade)
- Added `talosctl` and `etcd` to `ignoreDeps` in `renovate.json5` — both must track the running
  cluster version, not upstream releases; auto-merge rule would otherwise silently bump them

### Files created / modified
| File | Change |
|------|--------|
| `CLUSTER.md` | New troubleshooting row: dual peer URLs / stuck LEARNER after LACP-disabled ISO boot |
| `.mise.toml` | Added `etcd = "3.5.21"` with coupling comment |
| `renovate.json5` | Added `talosctl` and `etcd` to `ignoreDeps` with explanatory comments |

### Decisions made

**Manual etcdctl promotion required**
Talos does not auto-promote etcd LEARNER members to voting members. The `talosctl etcd` subcommands
do not include `promote`. The only path is `etcdctl member promote <hex-id>` using admin TLS certs
extracted via `talosctl read /system/secrets/etcd/{ca,admin}.{crt,key}`.

**etcd pinned to cluster-bundled version, excluded from Renovate**
`etcd` in mise must match the etcd version bundled with the running Talos release. Allowing Renovate
to bump it independently would create a version mismatch with the server. Same reasoning applies to
`talosctl`, which was not yet excluded from Renovate despite already being in the toolchain.

### Lessons learned

**Disable LACP on switch AND remove the extra peer URL before leaving maintenance mode**
When doing ISO maintenance with LACP-bonded nodes, the plain NIC gets a DHCP address that etcd
records as a peer URL. Once LACP is re-enabled the DHCP IP vanishes and the LEARNER is permanently
stuck. Fix: after any such maintenance, immediately check `talosctl etcd members` for dual peer
URLs. If present: remove the stale member, let the node rejoin cleanly, then manually promote.

**etcd admin certs live at `/system/secrets/etcd/` on each Talos node**
Files: `ca.crt`, `admin.crt`, `admin.key` (and `peer.crt`/`peer.key`/`server.crt`/`server.key`).
Extract with `talosctl read /system/secrets/etcd/<file> --nodes <node>`. Use `admin.crt` + `admin.key`
as the etcdctl client identity — `server.crt` is for the etcd server TLS, not client auth.

---

## 2026-05-07 — `cp03-nvme-swap-and-disk-migration`

### What we did
- Powered down talos-cp-03 (`talosctl shutdown`) to install a spare 128 GB NVMe (AirDisk)
- Verified live disk layout with `talosctl get discoveredvolumes`: new drive landed as `nvme1n1`
  (128 GB, prior Linux install — EFI + swap + ext4); 2 TB Crucial remained `nvme0n1`
- Refactored `talos:apply` task: merged maintenance-mode and running-node apply into one task
  with `INSECURE=true` flag; default is authenticated (running node); updated Day-2 runbook
- Switched all three nodes from `installDisk` (device path) to `installDiskSelector` (model name)
  after discovering NVMe device names are not stable when drives are added/removed
- Attempted to migrate Talos to the 128 GB drive via `talosctl upgrade` — failed (see below)
- Successfully migrated Talos to the 128 GB AirDisk via ISO boot + maintenance mode apply
- cp-03 now runs Talos from nvme0n1 (128 GB AirDisk); nvme1n1 (2 TB Crucial) is blank and free
- Updated ROADMAP.md, CLUSTER.md disk inventory; all three nodes now have free dedicated OSD drives

### Files created / modified
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | All nodes: `installDisk` → `installDiskSelector` by model name; cp-03 system disk changed to AirDisk 128 GB |
| `.taskfiles/talos/Taskfile.yaml` | `apply` task: `INSECURE=true` flag for maintenance mode; default authenticated |
| `CLUSTER.md` | Disk inventory updated (cp-03 AirDisk as system, 2 TB free); Day-2 runbook updated; troubleshooting entries added |
| `CLAUDE.md` | Session log updated; bootstrap workflow note updated |
| `ROADMAP.md` | Hardware snapshot updated; Stages 2–3 revised (hardware gap now closed) |

### Decisions made

**`installDiskSelector` by model name over `installDisk` by path**
NVMe device names (`nvme0n1`/`nvme1n1`) are assigned by the kernel at boot based on PCIe
enumeration order, which changes when drives are added or removed. During this session, adding
the 128 GB drive caused the 2 TB to shift from `nvme0n1` to `nvme1n1` across reboots. Model-
based selectors (`model: "KINGSTON SNV3S1000G"`, `model: "AirDisk 128GB SSD"`) are stable
regardless of enumeration order. All three nodes were switched.

**Single `apply` task with `INSECURE` flag**
Merged maintenance-mode and running-node apply variants into one task. `INSECURE=true` is the
explicit exceptional case (bootstrap/maintenance); default is the safe authenticated day-2 path.

**ISO boot for disk migration, not `talosctl upgrade`**
`talosctl upgrade` always reinstalls to the currently-running system disk — it does not respect
`installDisk`/`installDiskSelector` to pick a new target disk. ISO boot gives a clean installer
that reads `diskSelector` from the applied config with no "current system disk" bias.

### Lessons learned / failures

**`talosctl upgrade` does NOT change the system disk**
Three upgrade attempts all reinstalled Talos to the 2 TB (current system disk), ignoring
`installDiskSelector: model: "AirDisk 128GB SSD"` in the config. This is by design — upgrade
is an in-place operation. To migrate to a different physical disk, boot from ISO instead.

**Device names swap on reboot after adding an NVMe drive**
After physically installing the 128 GB drive, the 2 TB (previously `nvme0n1`) became `nvme1n1`
and vice versa. Any config using device paths would target the wrong disk. Use model selectors.

**`wipe: true` is required to install to a disk with existing non-Talos partitions**
With `wipe: false` (default), the Talos installer refuses to touch disks that have non-Talos
partition tables (e.g. the Linux EFI+swap+ext4 on the AirDisk). Adding `wipe: true` as a
temporary node-level patch forced the installer to wipe and repartition the target disk.
Remove the patch after the migration — it's not needed for future upgrades.

**talosctl 1.13.0 client cannot run `upgrade` against Talos 1.10.6 server**
The newer client sends more aggressive gRPC keepalive pings, triggering `ENHANCE_YOUR_CALM /
too_many_pings` GOAWAY from the older server. Fix: `mise exec talosctl@1.10.6 -- talosctl ...`
to use a version-matched client. Install with `mise install talosctl@1.10.6`.

**`talosctl reset --system-labels-to-wipe STATE EPHEMERAL` puts node in maintenance mode**
but the node may boot back to normal Talos if the EFI entry for the existing install is intact
and the installer doesn't run (no config applied in time). ISO boot is more reliable for
guaranteed maintenance mode entry.

**Disk migration procedure (validated)**
1. Cordon + drain the node
2. Boot from Talos ISO (virtual media or physical)
3. `task talos:apply IP=<node> INSECURE=true` — installer installs to `diskSelector` target
4. `kubectl wait --for=condition=Ready node/<node> --timeout=300s`
5. `kubectl uncordon <node>`
6. Remove any temporary `wipe: true` patch; `task talos:genconfig && task talos:apply IP=<node>`

---

## 2026-05-07 — `persistent-storage-roadmap`

### What we did
- Added a comprehensive **Persistent Storage** entry to `ROADMAP.md` covering: hardware snapshot,
  Talos system-disk partitioning research, storage option comparison, and a 4-stage rollout plan
- Ran `talosctl get discoveredvolumes` against all three nodes to get ground-truth disk inventory
- Discovered **cp-01 also has a free nvme1n1 (1 TB, no partition table)** — not previously documented;
  only cp-03 still lacks a secondary drive
- Corrected `CLUSTER.md` disk inventory and updated the storage row in `CLAUDE.md`'s status table

### Files created / modified
| File | Change |
|------|--------|
| `ROADMAP.md` | New "Persistent Storage" section added before External Secrets; covers hardware, Talos partitioning verdict, option table, and 4-stage rollout |
| `CLUSTER.md` | Disk inventory table updated — cp-01 nvme1n1 added; closing note corrected |
| `CLAUDE.md` | Storage row in "What is Complete vs. Planned" updated; session log row added |

### Decisions made / researched

**Talos system-disk partitioning — not viable**
The `EPHEMERAL` partition grows to fill 100% of remaining disk space at install time (confirmed
live: cp-01 nvme0n1p4 = 999 GB, cp-03 nvme0n1p4 = 2.0 TB). `machine.disks` only targets
non-system disks; the `UserVolume` API (Talos 1.9+) does not carve space from `EPHEMERAL` either.
Hostpath-inside-EPHEMERAL is possible but shares IOPS/capacity with the OS — avoid for stateful data.

**Recommended storage path (staged)**
1. **OpenEBS LocalPV** — deploy now, no hardware needed, hostpath storage class for cache/CI
2. **Longhorn on cp-01 + cp-02** — use both free nvme1n1 drives; 2-replica HA immediately
3. **One NVMe for cp-03** — completes 3-node set; promote to 3 replicas or evaluate Rook/Ceph
4. **NFS/SMB CSI** — if/when a NAS is added; ReadWriteMany workloads, wired via ExternalSecret

**Longhorn handles asymmetric disk sizes fine**
Longhorn is replica-based (not pool-based), so a 2 TB OSD on cp-03 vs 1 TB on the others is a
non-issue. Each volume replica is sized to the volume, not the disk. The larger disk simply
absorbs more replicas/volumes and has more scheduling headroom.

### Learned / noted
- `talosctl disks` is deprecated in Talos 1.10+; use `talosctl get discoveredvolumes` instead
- The live node inventory contradicted the documented disk inventory — worth verifying hardware
  state with `talosctl` rather than relying solely on documentation from prior sessions

---

## 2026-05-07 — `bootstrap-task-params-and-age-key`

### What we did
- Added optional `VAULT` and `ITEM` parameters to `bootstrap:flux-secret` — previously the task silently accepted `OP_VAULT`/`OP_ITEM` env vars (known only to the script), now they are first-class Taskfile parameters with defaults shown in the task description
- Created `scripts/age-key.sh` — fetches the SOPS age private key from 1Password and writes it to `age.key`; mirrors the structure of `flux-secret.sh` exactly (same colour helpers, `op whoami` check, `--force` guard, `trap cleanup EXIT`, validation before write)
- Added `bootstrap:age-key` task wiring `VAULT`, `ITEM`, `FIELD` as optional task parameters

### Files created / modified
| File | Change |
|------|--------|
| `.taskfiles/bootstrap/Taskfile.yaml` | `flux-secret`: added `vars:` + `env:` for `VAULT`/`ITEM`; updated `desc` to advertise params. Added new `age-key` task with `VAULT`/`ITEM`/`FIELD` params |
| `scripts/age-key.sh` | Created — `fetch` / `verify` subcommands; fetches age key from 1Password, validates `AGE-SECRET-KEY-1` prefix, writes to `$SOPS_AGE_KEY_FILE`, `chmod 600` |

### Decisions made
- **`vars:` + `env:` two-step** — Taskfile `vars:` resolves the `| default` template; `env:` then sets the shell environment variable the script reads. This is the only way to apply Taskfile template functions and still have the result visible to a subprocess
- **Param names `VAULT`/`ITEM`/`FIELD`** (not `OP_VAULT` etc.) — task parameters follow the project convention of short uppercase names (cf. `IP=required` in talos tasks); the `OP_` prefix is the script's internal convention
- **Validate before write** — script checks the retrieved value starts with `AGE-SECRET-KEY-1` before moving the temp file to `age.key`; a wrong field name (e.g. pointing at the public key comment) would otherwise silently corrupt the key file
- **Defaults `ITEM="SOPS age key"`, `FIELD="text"`** — updated to match the actual 1Password item structure; overridable at call site for portability

### Learned / noted
- `trap cleanup EXIT` fires at *script* exit, not at function return — any variable the `cleanup` function references must be in scope at process exit. A `local` variable inside the function that sets the trap is out of scope by that point; with `set -u` this kills the script with `unbound variable`. Fix: omit `local` for temp-file vars that the trap handler touches (same pattern already used in `flux-secret.sh`)
- `task bootstrap:age-key -- verify` does not forward the subcommand to the script; extra args after `--` in go-task CLI syntax are passed as `CLI_ARGS`, not appended to `cmds`. Call the script directly for subcommands that are not wired as separate tasks

---

## 2026-05-06 — `renovate-setup`

### What we did
- Added `renovate.json5` at the repo root to configure the Mend Renovate GitHub App
- Installed the Mend Renovate GitHub App on `qnimbus/home-lab` (browser step, user-performed)
- Fixed a lookup failure for the `1password` mise tool — added to `ignoreDeps` because the CLI is distributed via AgileBits' own servers, not GitHub; Renovate defaults to `github-tags` for unknown mise tools and finds nothing
- Disabled Talos + Kubernetes version tracking in Renovate at user request — those versions will be managed via a separate upgrade mechanism; added both `ghcr.io/siderolabs/installer` and `ghcr.io/siderolabs/kubelet` to `ignoreDeps`

### Files created / modified
| File | Change |
|------|--------|
| `renovate.json5` | Created — full Renovate config (see decisions below) |

### Decisions made
- **`ignoreDeps` over `packageRules[enabled:false]`** for manually-managed packages: `ignoreDeps` is an early filter evaluated before any manager or `packageRule`, making the intent ("don't touch these") explicit and up-front rather than buried in a rule
- **`docker:enableMajor` preset included** — without it Renovate silently skips major Docker image bumps; Talos and Kubernetes use `datasource=docker`, so this would suppress major version notifications for those packages (and any future ones tracked the same way)
- **`schedule: ["every weekend"]`** — avoids weekday PR noise on a home lab; can be changed to `"at any time"` for continuous scanning
- **`automergeType: "branch"` for mise and GitHub Actions** — Renovate merges directly to the branch when clean, no PR required; `ignoreTests: true` needed because this repo has no CI
- **`minimumReleaseAge: "3 days"` on GitHub Actions auto-merge** — gives the community a soak window to catch regressions before an update lands automatically
- **Grouped `Talos + Kubernetes`, `Flux`, `cert-manager`, `CoreDNS`, `Spegel`** — components that always ship together or should be reviewed together produce a single PR rather than one each
- **Custom regex manager** uses `datasource=` annotation format (e.g. in `talenv.yaml`); the native helmfile manager uses the `registryUrl=` annotation format — they look similar but feed different Renovate subsystems
- **`ignorePaths: ["**/*.sops.*"]`** — prevents Renovate from treating encrypted ciphertext as version strings

### Learned / noted
- Two annotation styles coexist in the repo: `# renovate: registryUrl=... chart=...` (read by the native `helmfile` manager from `helmfile.yaml`) and `# renovate: datasource=... depName=...` (read by the custom regex manager from `talenv.yaml`). They are not interchangeable
- Renovate's `mise` manager reads `.mise.toml` natively but falls back to `github-tags` for any tool it doesn't recognise. The `1password` tool resolves via `aqua:1password/cli` in the mise registry (an AgileBits download, not GitHub), so the `github-tags` lookup returns no results
- The `$schema` URL in `renovate.json5` triggers a VS Code JSON language-server warning in the devcontainer ("location untrusted") because the container cannot reach `docs.renovatebot.com` at schema-load time — the config is valid and Renovate itself reads the schema correctly when running remotely; the warning is a false positive

---

## 2026-05-06 — `node-hw-correction-and-runbook-updates`

### What we did
- Corrected a node hardware mix-up in `talconfig.yaml` and `CLAUDE.md`: `talos-cp-01` had been configured with MS-A2 NIC drivers (RTL8125 / i40e) and a two-NIC LACP bond on management, but is actually a Lenovo M920Q with a single e1000e management NIC and ixgbe storage bond; `talos-cp-03` is the Minisforum MS-A2
- Updated network interface config for `talos-cp-01` to use `deviceSelector: driver: e1000e` (single NIC, no bond on management) and `bond0` with `driver: ixgbe` (storage, X520-DA2)
- Fixed the node order in the CLAUDE.md hardware table to match physical assignments (cp-01 = M920Q #1, cp-02 = M920Q #2, cp-03 = MS-A2)
- Added `talos:wait-bootstrap` task — polls `kubectl get nodes` until all nodes (count derived from `talconfig.yaml`) show `Ready`, then prints `kubectl get nodes -o wide` and exits
- Added a **Day-2 Config Changes** section to the Bootstrap Runbook in `CLUSTER.md` documenting the standalone `genconfig` → `apply-all` / `apply IP=` pattern for post-bootstrap config edits
- Updated Phase 1 of the Bootstrap Runbook to use `task talos:wait-bootstrap` instead of a bare `kubectl get nodes -o wide`

### Files created / modified
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Corrected `talos-cp-01` hardware: e1000e mgmt NIC (no bond), ixgbe storage bond (X520-DA2); fixed node hostname comments |
| `CLAUDE.md` | Fixed hardware table: cp-01/cp-02 = M920Q, cp-03 = MS-A2 |
| `.taskfiles/talos/Taskfile.yaml` | Added `talos:wait-bootstrap` task |
| `CLUSTER.md` | Added Day-2 Config Changes section; Phase 1 verification now uses `task talos:wait-bootstrap` |

### Decisions made
- `wait-bootstrap` derives expected node count from `yq '.nodes | length' talconfig.yaml` rather than hardcoding 3 — stays correct if nodes are added
- `awk '$2 == "Ready"'` used for node status check (exact column match) rather than `grep Ready`, which would also match "NotReady"
- Day-2 config change section placed immediately before Troubleshooting in the runbook — it answers a "what do I run after editing talconfig?" question which naturally precedes debugging

### Learned / noted
- `bootstrap:cluster` embeds `talos:genconfig` as step 2 — it is not visible as a top-level runbook step, which makes it easy to miss when doing day-2 config edits outside of a full re-bootstrap
- Node hardware assignments were transposed from a previous session: the MS-A2 (cp-03) config had been applied to cp-01's stanza, causing it to reference i40e and RTL8125 drivers that don't exist on the M920Q hardware

---

## 2026-05-06 — `cp02-disk-cleanup`

### What we did
- Identified and wiped a legacy Proxmox LVM installation from `nvme1n1` on `talos-cp-02` (10.60.0.202)
- Discovered the disk inventory across all three nodes via `talosctl get disks` and `talosctl get discoveredvolumes`
- Documented disk inventory in `CLUSTER.md`

### Problem and resolution
The Proxmox install had left an LVM2 Physical Volume on `nvme1n1p3`, with the volume group activating 8 `dm-*` logical volumes at every boot. The kernel's device mapper stack (`dm-0` through `dm-7`) blocked all `talosctl wipe` attempts with `FailedPrecondition: blockdevice in use`. Wiping the LV content (`dm-*` devices) did not release the mappings because LVM re-activates based on PV metadata, not LV content. The fix was `talosctl reset --graceful=false --reboot --wipe-mode=user-disks --user-disks-to-wipe=/dev/nvme1n1`, which wiped `nvme1n1` during Talos's own shutdown path before LVM re-activated.

### Files created / modified
| File | Change |
|------|--------|
| `CLUSTER.md` | Added Node Disk Inventory section |

### Decisions made
- `--wipe-mode=user-disks` was the correct flag — it wipes only the specified user disk and preserves the system disk (`nvme0n1`), so the node retained its Talos machine config and rejoined the cluster immediately after reboot without requiring `apply-config`

### Learned / noted
- `talosctl disks` is deprecated; use `talosctl get disks`, `talosctl get systemdisk`, `talosctl get discoveredvolumes` instead
- `talosctl wipe disk` takes a bare device ID (e.g. `nvme1n1`), **not** a `/dev/` path — but `talosctl reset --user-disks-to-wipe` takes the full `/dev/nvme1n1` path on Talos 1.10.6
- `talosctl get discoveredvolumes` shows filesystem/volume-manager signatures per partition (e.g. `lvm2-pv`, `ext4`, `swap`) — the most useful command for identifying foreign disk layouts
- LVM PV header lives on the partition (`nvme1n1p3`), not the LV content; wiping `dm-*` devices zeroes LV data but leaves the PV metadata intact — LVM will re-activate the VG on every reboot until the PV header itself is destroyed
- `talosctl reset` wipes disks during its own shutdown sequence, bypassing the userspace "in use" guard that blocks live wipe commands

---

## 2026-05-06 — `cluster-bootstrap-runbook`

### What we did
- Performed a full end-to-end cluster bootstrap from reset through Flux operational: `talos:reset` → `talos:wait-maintenance` → `bootstrap:cluster` → `bootstrap:apps` → `bootstrap:flux-secret` → verified `flux get all -A` shows all resources `Ready`
- Added `talos:wait-maintenance` task — polls TCP port 50000 per node (sequential, prints dots) and exits once all nodes accept connections
- Added a comprehensive **Bootstrap Runbook** to `CLUSTER.md` covering all four phases with tables, timing estimates, and a troubleshooting section
- Fixed `scripts/flux-secret.sh` — removed `local` from temp file variable declarations so the `trap cleanup EXIT` handler can reference them at script exit
- Updated `bootstrap:flux-secret` task to chain `flux reconcile source git flux-system` immediately after secret creation, eliminating the manual reconcile step that was otherwise needed

### Files created / modified
| File | Change |
|------|--------|
| `CLUSTER.md` | Added Bootstrap Runbook section (Phases 0–4, troubleshooting table) |
| `.taskfiles/talos/Taskfile.yaml` | Added `talos:wait-maintenance` task |
| `.taskfiles/bootstrap/Taskfile.yaml` | `flux-secret` task: `cmd` → `cmds` + `flux reconcile`; added `flux` precondition |
| `scripts/flux-secret.sh` | Removed `local` from `tmp_identity`, `tmp_pub`, `tmp_known_hosts` declarations |
| `ROADMAP.md` | Created — pending work items in priority/dependency order |

### Decisions made
- `nc -z -w 3 <ip> 50000` over `talosctl version --insecure` for maintenance mode detection — `talosctl version` returns a gRPC "not implemented" error in maintenance mode (non-zero exit), making it useless as a readiness signal; port 50000 being open is the correct proxy for "node will accept `apply-config --insecure`"
- `silent: true` on `wait-maintenance` suppresses go-task's command echo; `>/dev/null 2>&1` on the `nc` call suppresses its per-connection success message — both needed for clean output
- Flux reconcile belongs in the Taskfile (not in `flux-secret.sh`) — the script owns secret lifecycle, the task owns workflow orchestration; adding `flux` as a dependency to the script would be a layering violation

### Learned / noted
- Flux's source-controller caches a "secret not found" state from before the secret was created; it does not immediately re-check on secret creation — `flux reconcile source git` forces an instant retry rather than waiting up to 5 minutes for the next poll
- `trap cleanup EXIT` fires at *script* exit, not *function* return — `local` variables declared inside the function are out of scope by that point; with `set -u` active, referencing them is fatal (`unbound variable`). Fix: drop `local` for any variable the `trap` handler references
- `talosctl bootstrap` reliably returns `grpc: the client connection is closing` on the first attempt because the node restarts after receiving its machine config; the `until … do sleep 10; done` wrapper in the task handles this correctly — it is not an error

---

## 2026-05-06 — `devcontainer-secret-management`

### What we did
- Created `scripts/flux-secret.sh` — automates step 12a of the bootstrap workflow: fetches the Flux SSH deploy key from 1Password via `op read` and creates the `flux-system` Kubernetes secret
- Added `bootstrap:flux-secret` task to `.taskfiles/bootstrap/Taskfile.yaml`
- Discussed 1Password CLI authentication options for a WSL2 devcontainer: Windows named pipe (not mountable in Docker), service account token via `OP_SERVICE_ACCOUNT_TOKEN`, and manual `op account add`
- Recommended service account token via `${localEnv:OP_SERVICE_ACCOUNT_TOKEN}` in `devcontainer.json` (stateless, survives rebuilds, no socket plumbing)

### Files created / modified
| File | Change |
|------|--------|
| `scripts/flux-secret.sh` | Created — `setup` / `verify` subcommands; fetches key from 1Password, generates `known_hosts` via `ssh-keyscan`, creates secret idempotently |
| `.taskfiles/bootstrap/Taskfile.yaml` | Added `flux-secret` task (`bootstrap:flux-secret`) |

### Decisions made
- `setup` checks secret existence *before* creating temp files or fetching from 1Password — avoids wasted network calls on a no-op skip, and avoids `unbound variable` crash at script exit when `trap cleanup EXIT` fires after `local` variables go out of scope
- `known_hosts` is generated at runtime via `ssh-keyscan -H github.com` (not read from disk) — `-H` hashes the hostname, matching Flux's expected format; avoids relying on a stale committed file
- Default vault `homelab`, default item `flux-deploy-key`; overridable via `--vault`/`--item` flags (direct) or `OP_VAULT`/`OP_ITEM` env vars (required path when using `task`)
- `--force` replaces an existing secret via delete + recreate (not patch) — a brief window exists where the secret is absent; acceptable on a home lab with a 5-minute Flux poll interval

### Learned / noted
- `trap` in bash is global to the shell process, not scoped to the function that sets it — a trap set inside a function fires at *script* exit, by which point `local` variables from that function are gone; with `set -u`, referencing them is fatal
- `\n` inside a double-quoted string is two literal characters when passed to `printf "%s"` — use `$'\n'` (ANSI-C quoting) to embed a real newline, or `printf "%b"` to interpret escape sequences
- The Windows 1Password app uses a named pipe (not a Unix socket) for CLI integration — named pipes cannot be bind-mounted into Docker containers; the Unix socket path documented for macOS does not apply on Windows
- Service account token (`OP_SERVICE_ACCOUNT_TOKEN`) is the practical choice for devcontainer authentication: stateless, no signin required, vault-scoped access

---

## 2026-05-06 — `mcp-server-rbac-scripts`

### What we did
- Read the `kubernetes-mcp-server` getting-started docs (Kubernetes setup + Claude Code integration)
- Created the `mcp` namespace and `mcp-viewer` ServiceAccount imperatively (one-time cluster state)
- Created `ClusterRoleBinding mcp-viewer-crb` binding the built-in `view` ClusterRole cluster-wide
- Minted a service account token and built `~/.kube/mcp-viewer.kubeconfig`
- Created `scripts/mcp.sh` — a single script with three subcommands (`setup`, `cleanup`, `renew-token`) that codifies all of the above so the operations are repeatable
- Connected the `kubernetes-mcp-server` MCP tool to Claude Code via `claude mcp add-json` using the dedicated kubeconfig
- Verified the MCP connection by listing cluster namespaces through the tool

### Files created / modified
| File | Change |
|------|--------|
| `scripts/mcp.sh` | Created — `setup` / `cleanup` / `renew-token` subcommands for MCP ServiceAccount lifecycle |

### Decisions made
- Single script with subcommands (mirrors `bootstrap.sh` pattern) rather than three separate files
- Default token duration is **8h** (practical for a work day; overridable per-invocation, e.g. `./scripts/mcp.sh renew-token 24h`)
- `setup` is fully idempotent — re-running on an existing cluster skips already-present resources and issues a fresh token
- RBAC uses the built-in `view` ClusterRole cluster-wide (Option A from the docs) — appropriate for a read-only observability tool; no custom ClusterRole needed
- Kubeconfig is written to `~/.kube/mcp-viewer.kubeconfig` (separate from the admin kubeconfig, scoped credentials)

### Learned / noted
- `kubectl create token` duration format (`8h`) uses Go's `time.Duration` syntax — GNU `date -d` requires `8 hours`; a `sed` transform bridges the two in the expiry display
- The `mcp` namespace, ServiceAccount, and ClusterRoleBinding were created imperatively and are **not** currently managed by Flux; `scripts/mcp.sh setup` serves as the source of truth for reproducing them

---

## 2026-05-06 — `flux-ssh-secret-setup`

### What we did
- Diagnosed and resolved Flux failing to reconcile the private GitHub repo
- Fixed three incorrect values in `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml`:
  - URL: HTTPS → SSH (`ssh://git@github.com/qnimbus/home-lab`)
  - Secret reference: `secretRef.name` → `pullSecret` (correct FluxInstance CRD field name)
  - Ref: `main` → `refs/heads/main` (FluxInstance `ref` must be a full Git ref path, not a branch shortname)
  - Added missing `path: ./kubernetes/flux/cluster` and `interval: 5m0s`
- Created the `flux-system` SSH deploy key secret imperatively in the cluster (`identity`, `identity.pub`, `known_hosts`)
- Patched the live `FluxInstance` directly to propagate `pullSecret` and correct ref without waiting for a Helmfile re-run
- Confirmed Flux is fully operational: `GitRepository READY`, `cluster-meta` and `cluster-apps` kustomizations applying

### Files created / modified
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` | Fixed URL, ref, path, interval; replaced `secretRef` with `pullSecret` |

### Decisions made
- SSH deploy key (`flux-deploy-key`) created with `ssh-keygen -t ed25519`; public key added as read-only GitHub deploy key; private key stored in `flux-system` Kubernetes secret and backed up to 1Password alongside `age.key`
- The `flux-system` SSH secret must be created imperatively during bootstrap — this is the one permanent exception to GitOps; all other cluster state goes through Git
- Bootstrap step 13a added to workflow: create `flux-system` SSH secret immediately after `helmfile sync`, before `git push`
- `helmfile sync` is the correct mechanism to update bootstrap-layer components (not `kubectl apply`)

### Learned / noted
- The `flux-instance` Helm chart (v0.23.0) does **not** expose all `FluxInstance` CRD fields as Helm values — `secretRef` is silently dropped; the correct values key is `pullSecret` (a plain string, not an object with a `name` key)
- The `FluxInstance` CRD `spec.sync.ref` expects a full Git ref (`refs/heads/main`), not a branch shortname; shortname produces `unable to resolve ref 'main' to a specific commit`
- `KUBECONFIG=$(pwd)/kubeconfig` must be exported in every new shell session; add to devcontainer env to avoid repeated manual export

---

## 2026-05-06 — `add-sops-plaintext-hook`

### What we did
- Added a Claude Code `PreToolUse` hook that blocks any `git add` or `git commit` command if a `*.sops.yaml` file involved is not SOPS-encrypted
- Created `.claude/hooks/check-sops.sh` — collects at-risk sops files, checks each for the `^sops:` root-level YAML key (canonical SOPS encryption marker), and emits `{"continue":false}` to block the command if plaintext is found
- Created `.claude/settings.json` — wires the script as a `PreToolUse` / `Bash` hook with a `"Checking SOPS encryption..."` status message

### Files created / modified
| File | Change |
|------|--------|
| `.claude/hooks/check-sops.sh` | Created — SOPS plaintext guard script |
| `.claude/settings.json` | Created — project-level Claude Code hook config |

### Decisions made
- Hook lives in `.claude/settings.json` (project-level) rather than `~/.claude/settings.json` (user-level) so it is scoped to this repo
- Detection uses `grep -q '^sops:'` — checks for the root-level `sops:` metadata block SOPS injects into every encrypted file, regardless of backend (age, KMS, PGP) or mode (`mac_only_encrypted`)
- Hook handles three `git add` patterns: explicit file args, broad adds (`git add .` / `git add -A`) via `git diff --name-only` + `git ls-files --others`, and `git commit` via `git diff --cached --name-only`

### Learned / noted
- `.claude/` is currently in `.gitignore` — the hook and settings exist only in the devcontainer and are not shared via Git. To make the guard apply for all contributors, remove `.claude/` from `.gitignore` (keeping `settings.local.json` gitignored separately)
- A new Claude Code session must open `/hooks` or restart to pick up a newly created `settings.json`

---

## 2026-05-06 — `setup-sops-age-key-devcontainer`

### What we did
- Analysed the full project structure, including current `talos/`, `scripts/`, `.devcontainer/`, and the archived cluster in `.archive/`
- Created `CLAUDE.md` as the project's primary self-documentation and Claude Code guidance file

### Files created / modified
| File | Change |
|------|--------|
| `CLAUDE.md` | Created — repo layout, toolchain, hardware, secrets strategy, bootstrap workflow, GitOps conventions, status table, working rules |
| `.devcontainer/devcontainer.json` | Added `remoteEnv` block setting `SOPS_AGE_KEY_FILE=${containerWorkspaceFolder}/age.key` |

### Decisions made
- `SOPS_AGE_KEY_FILE` is set via `devcontainer.json` `remoteEnv` (not `postCreateCommand.sh` or `.mise.toml`) so it is available to every terminal and VS Code process from container startup, before any shell profile or mise activation runs
- Two-tier secrets strategy documented: SOPS+age for Talos secrets, ESO+1Password Connect for application secrets

### Learned / noted
- The VS Code SOPS extension already receives the key path via `"sops.defaults.ageKeyFile": "age.key"` in devcontainer settings; `remoteEnv` completes coverage for CLI tooling
- `${containerWorkspaceFolder}` is a devcontainer built-in variable that resolves to the workspace root — prefer it over hardcoded paths in `devcontainer.json`
