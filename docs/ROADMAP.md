# Home Lab — Cluster Roadmap <!-- omit from toc -->

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

## Contents  <!-- omit from toc -->

- [In Progress](#in-progress)
  - [Rook v1.19 → v1.20 Upgrade (ceph-csi-drivers migration, PRs #96/#97)](#rook-v119--v120-upgrade-ceph-csi-drivers-migration-prs-9697)
  - [Forgejo: Deferred Follow-ups (Actions Runner, WAN Exposure)](#forgejo-deferred-follow-ups-actions-runner-wan-exposure)
  - [WAN Failover Router: Host Header Rewrite](#wan-failover-router-host-header-rewrite)
  - [Renovate PR-Review Workflow: Cost/Bug Investigation, Re-enable](#renovate-pr-review-workflow-costbug-investigation-re-enable)
  - [Flux Render CI: Migrate flux-local → flate](#flux-render-ci-migrate-flux-local--flate)
  - [Renovate on an In-Cluster Runner](#renovate-on-an-in-cluster-runner)
  - [CloudNativePG: Backup, PITR, and Per-App Provisioning](#cloudnativepg-backup-pitr-and-per-app-provisioning)
  - [Postgres NFS Backup: Restore Drill](#postgres-nfs-backup-restore-drill)
  - [~~Longhorn Storage Network (Multus + Storage VLAN)~~ — ABANDONED, superseded by Rook-Ceph](#longhorn-storage-network-multus--storage-vlan--abandoned-superseded-by-rook-ceph)
  - [Rook-Ceph Migration](#rook-ceph-migration)
  - [~~cp-02 Thermal Stability (Lenovo M920Q)~~ — RESOLVED](#cp-02-thermal-stability-lenovo-m920q--resolved)
  - [Future Storage Options](#future-storage-options)
  - [Storage VLAN Performance Benchmarking](#storage-vlan-performance-benchmarking)
  - [Grafana](#grafana)
  - [Alertmanager Receiver](#alertmanager-receiver)
  - [e1000e Management-NIC Packet Drops: `netdev_budget` Experiment](#e1000e-management-nic-packet-drops-netdev_budget-experiment)
  - [Ceph `public_network`: Move to Storage VLAN](#ceph-public_network-move-to-storage-vlan)
  - [Prometheus Metric Hygiene: Drop Static and Low-Value Series](#prometheus-metric-hygiene-drop-static-and-low-value-series)
  - [Scheduling Topology: Follow-up Fixes](#scheduling-topology-follow-up-fixes)
  - [Kubernetes Descheduler](#kubernetes-descheduler)
  - [Talos Config, Image Extensions \& Patch Audit](#talos-config-image-extensions--patch-audit)
  - [Migrate Remaining HelmRepositories to `home-operations/charts-mirror`](#migrate-remaining-helmrepositories-to-home-operationscharts-mirror)
  - [Tailscale kubectl Authentication (RBAC)](#tailscale-kubectl-authentication-rbac)
  - [Cilium BGP Control Plane (replace L2 Announcement)](#cilium-bgp-control-plane-replace-l2-announcement)
  - [CSI Snapshots (external-snapshotter + Ceph VolumeSnapshotClass)](#csi-snapshots-external-snapshotter--ceph-volumesnapshotclass)
  - [VolSync (PVC Backup)](#volsync-pvc-backup)
  - [Researched Patterns (bykaj/home-ops)](#researched-patterns-bykajhome-ops)
  - [Dragonfly: Snapshot Persistence (Future)](#dragonfly-snapshot-persistence-future)
- [Completed](#completed)

---

## In Progress

### Rook v1.19 → v1.20 Upgrade (ceph-csi-drivers migration, PRs #96/#97)

**✅ COMPLETE (2026-09-04).** Step 1 landed as commit `4d1a6c5` (17:00): the operator upgrade,
`ceph-csi-drivers` install and CSI pod roll went exactly as sequenced (~6 min end to end,
provision/attach paused for ~1 min, no mount impact): all 25 Rook deployments at `v1.20.7`,
Ceph `HEALTH_OK` on `19.2.3`, Driver adopted with `keep`, cephcsi 3.17.1 on all nodes, and a
throwaway PVC + VolumeSnapshot probe passed. Renovate auto-closed #96/#97 and re-opened the
cluster-chart bump as #103 under the "Rook-Ceph chart" group; merged 19:39 — the cluster HR
upgraded to chart `v1.20.7` with no daemon restarts (only the toolbox recycled), Ceph unchanged
at `19.2.3`, `security.cephx.csi.keyType: aes` now rendered. All three HRs Ready; the lockstep
gates are in steady state (operator chart == both `rook.io/chart-version` annotations).
One artifact needed cleanup: the outgoing v1.19.6 operator created a stray CephFS `Driver` CR
when the chart upgrade stripped its ConfigMap (see [QA.md](QA.md)); delete it imperatively
(`kubectl -n rook-ceph delete driver.csi.ceph.io rook-ceph.cephfs.csi.ceph.com`) — Rook v1.20
cannot recreate it, and its 0/2 controller otherwise fires replica-mismatch alerts.

Renovate opened two independent PRs bumping
`ghcr.io/rook/rook-ceph` (#96) and `ghcr.io/rook/rook-ceph-cluster` (#97) from `v1.19.6` to
`v1.20.7`. Both are held by `renovate/stability-days` and **must not be merged as-is** — see the
[Rook v1.20 upgrade guide](https://rook.github.io/docs/rook/v1.20/Upgrade/rook-upgrade/):

- **v1.20 breaking change:** Rook no longer deploys the CSI drivers. The `rook-ceph` chart keeps only
  the `ceph-csi-operator` subchart (0.6.0 → 1.0.4) and the CSI image-set ConfigMap; the `Driver` /
  `OperatorConfig` CRs, CSI ServiceAccounts and RBAC move to a new, mandatory `ceph-csi-drivers`
  chart. Required Helm order: `rook-ceph` → `ceph-csi-drivers` → `rook-ceph-cluster`.
- **Hidden Ceph major bump:** the v1.20 cluster chart defaults `cephVersion` to Tentacle `v20.2.4`
  (v1.19: Squid `v19.2.3`); our cluster HR left it unset. Now pinned to `v19.2.3` so Ceph upgrades
  become their own Renovate PRs.
- Rook v1.19.5+ already pre-annotated the live CRs with `meta.helm.sh/release-name: ceph-csi-drivers`,
  so the new release adopts them; live CSI settings were saved per the guide's step 1 and reproduced
  in the HelmRelease values where chart defaults would otherwise change behaviour (`snapshotPolicy`
  — VolSync depends on the snapshotter sidecar; `grpcTimeout` 150 s; no log-rotation sidecar;
  Rook's resource defaults).

**Drafted (uncommitted) in this repo:** `kubernetes/flux/meta/repos/oci/ceph-csi-drivers.yaml`
(home-operations charts-mirror 1.0.4, cosign-verified), `kubernetes/apps/rook-ceph/rook-ceph/csi-drivers/app/`,
a third `rook-ceph-csi-drivers` Kustomization in `rook-ceph/ks.yaml`, the operator HR stripped of
the removed `csi.enable*` values, the cluster HR pinned to `quay.io/ceph/ceph:v19.2.3` + explicit
`security.cephx.csi.keyType: aes`, the **operator** OCI tag bumped to `v1.20.7` (= PR #96), and
Renovate rules (group the two Rook charts; dashboard approval for Ceph majors and for
`ceph-csi-drivers` bumps). The **cluster** OCI tag is deliberately left at `v1.19.6` — see the
sequence below.

**Ordering design.** A `chartRef` HelmRelease upgrades on its own the moment its OCIRepository tag
changes, so Kustomization `dependsOn` cannot sequence chart upgrades — worse, a Kustomization-level
dependency on the new csi-drivers Kustomization would hold back the cluster HR's *spec* (the Ceph
pin!) while helm-controller upgraded the live, unpinned spec to the v1.20 chart and its Tentacle
default. Ordering therefore lives in the HRs: `ceph-csi-drivers` and `rook-ceph-cluster` each carry
a `rook.io/chart-version` annotation (Renovate-tracked with the same `depName` as the operator tag,
so it moves in the same grouped PR) and a `dependsOn` `readyExpr` that waits until the operator
release's applied `chartVersion` equals that annotation (Flux's lockstep pattern; the cluster HR
also waits for `ceph-csi-drivers` Ready). This is permanent, not a migration-only gate. The drivers
HR marks everything it renders `helm.sh/resource-policy: keep` via a postRenderer, so the
cluster-wide install remediation (`helm uninstall` on failure) can never remove the live RBD driver,
its SAs or its RBAC.

**Rollout sequence:**
1. Commit + push the draft. Flux: operator upgrades to `v1.20.7` (deletes the old
   `ceph-csi-rbd-*`/`rook-csi-*` SAs + RBAC, bumps the CSI image set) → gate opens →
   `ceph-csi-drivers` installs (adopts the CRs, creates `rook-ceph-rbd-csi-ceph-com-*` SAs/RBAC,
   rolls CSI pods to cephcsi v3.17.1) → cluster HR reconciles its new spec on the unchanged
   `v1.19.6` chart (pin = chart default, no Ceph change). Expected ~1–2 min window between the first
   two steps: new PVC provision/attach pauses, and the node-plugin DaemonSet may start rolling
   against the deleted old SA on one node and stall there until the drivers chart lands — a pod
   restart needing an RBD mount on that node can fail briefly. Existing mounts are unaffected.
   Renovate closes #96 as superseded and re-opens the cluster bump under the "Rook-Ceph chart" group.
2. Verify: `kubectl -n rook-ceph get operatorconfig,driver`, all `rook-version` labels at
   `v1.20.7`, node-plugin DaemonSet 5/5 on the new SA, `ceph -s`, a throwaway PVC, a VolSync sync.
3. Merge the cluster-chart bump (regrouped #97 → #103). The cluster HR's gate is already
   satisfied, the chart upgrades with `cephImage` pinned — Ceph stays `19.2.3`. Re-verify
   `ceph -s` and the CephCluster image. *(Done 19:39, verified.)*

If the operator upgrade fails and rolls back to `v1.19.6`, the gates stay closed (annotation says
`v1.20.7`): recovery is reverting the commit (tags + annotations together), which reopens them.

**Renovate fallout (2026-09-04 evening):** within two hours of the Ceph pin landing, Renovate
opened PR #101 proposing `quay.io/ceph/ceph v19.2.3 → v21.1.0` — a two-major jump to a release
candidate (Ceph `x.1.z` = RC, `x.2.z` = stable) that Rook 1.20 does not support at all (Squid +
Tentacle only). The `dependencyDashboardApproval` rule meant to hold Ceph majors was not honoured
(no "Pending Approval" section ever appeared on the dashboard), so both Ceph rules now use hard
`allowedVersions` pins instead (`/^v19\.2\.\d+$/`; `ceph-csi-drivers <=1.0.4`) — raise them
deliberately when the corresponding upgrade is planned. #101 must not be merged; Renovate closes
it itself once the rule is on `main` (it did, within minutes). The same run opened the real
step-3 PR (#103, merged — see status above) and #102 (`quay.io/ceph/ceph v19.2.3 → v19.2.6`),
which stays parked: see the CVE follow-up below.

**Follow-ups:**
- **CVE-2025-30156 — ✅ DONE 2026-09-04 (commit `f9c47d5`, session
  `ceph-cve-2025-30156-key-rotation`):** the cluster HR carries `cephImage.tag: v19.2.6` *and* `security.cephx.daemon`
  `{keyRotationPolicy: KeyGeneration, keyGeneration: 2}` in one change, plus
  `healthCheck.muteHealthWarning` for the four residual `AUTH_INSECURE_*` warnings (CSI keys stay
  AES: Talos kernel 6.18 < 7.0). Renovate PR #102 (tag-only) becomes redundant once this lands and
  should auto-close. v19.2.6 also fixes CVE-2026-50152 (mon config-key store readable with
  `mon allow r`). **Exposure audited 2026-09-04:** `ceph config-key ls` holds 113 keys — Ceph
  config + history, device-health metrics, Rook telemetry counters, mgr module state. The only
  secrets are `mgr/dashboard/jwt_secret` (dashboard session-token signing key) and
  `mgr/dashboard/accessdb_v2` (dashboard users; passwords stored as bcrypt hashes, and the admin
  password itself is Rook-managed from the 1Password-backed `rook-ceph-dashboard-password`
  Secret). No OSD LUKS keys (OSDs unencrypted), no cephadm SSH key (not cephadm). Pre-patch, the
  only non-daemon entities with `mon allow r` were the four CSI keys, which live in Kubernetes
  Secrets in `rook-ceph` — reading them already implies namespace-level compromise. Risk: low.
  ✅ `jwt_secret` rotated 2026-09-04 23:25 UTC: `ceph config-key rm mgr/dashboard/jwt_secret &&
  ceph mgr fail`. Gotcha: `mgr fail` respawns the mgr process but the dashboard's `JwtManager`
  initialises **lazily** (on the first `gen_token`/`decode_token`), so the key only reappears on the
  first dashboard request carrying a token — any old session token triggers it and is rejected.
  The mons re-elected `a` as active, which is fine. Dashboard password left as is (bcrypt hash,
  1Password-managed); rotate it there if ever wanted. Ceph's general rotation guidance still pending.
  **Observed rollout (2026-09-04, matches Rook release-1.20 `setIsSafeToRotateCephxKeys`):**
  two passes, 12 minutes total. Pass 1 (20:25–20:29 UTC) rolled 3 mons, 2 mgrs, 10 OSDs to 19.2.6
  with rotation gated off; `HEALTH_ERR` opened at 20:26 with the first 19.2.6 mon. At 20:29:49 the
  operator reloaded its controller-manager in-process (log "restarting rook operator"; pod restart
  count stayed 0 — it is *not* a crash). Pass 2 (20:30–20:36) rotated admin (second in-process
  reload) → mon → crash/exporter → mgr → osd, restarting each daemon set again; the mon restart is
  driven by a deliberate reconcile failure ("triggering a new reconcile to restart the mon daemons")
  logged at E level. `HEALTH_OK` at 20:36:42, cluster Kustomization Ready again the same tick,
  CephCluster phase Ready at 20:37. During the 10-minute `HEALTH_ERR` window the 12 dependent
  Kustomizations held new Git changes (workloads untouched) and Flux + `CephHealthError` paged.
  End state: 16 keys `aes256k`, 5 `aes` (4 CSI + rbd-mirror-peer, by design), four warnings
  `(MUTED, STICKY)`, toolbox picked up the rotated admin key by itself (no restart needed — the
  v1.20.7 toolbox watches the mounted mon keyring). Renovate PR #102 auto-closed.
  Later: flip the mutes to `unmute` and rotate CSI keys to `aes256k` once Talos ships kernel ≥ 7.0.
- **Tentacle (v20.2.4) — ✅ DONE 2026-09-05, session `ceph-tentacle-upgrade`** (commits
  `c9d41d3` pre-step, `b0bb9b6` bump). Two commits, in order:
  1. ✅ Pre-step: `rook` and `restful` mgr modules set `enabled: false` in the cluster HR. The
     `rook` module (the `ceph orch` backend, unused here) triggers a permanent mgr-module-crash
     loop on 20.2.3/20.2.4 via the prometheus module's `node_proxy_fullreport` call
     (rook/rook#18124, tracker 79106, no Tentacle backport yet); Rook 1.20.7 force-disables it on
     20.2.2–20.2.4 but the guide says disable *before* upgrading. `restful` was Ceph's Squid-era
     default and no longer exists in Tentacle.
  2. ✅ Image bump `cephImage.tag: v19.2.6 → v20.2.4` + Renovate pin loosened to `v20.2.x` with
     x ≥ 4 (v20.2.0 data-corruption bug with `readAffinity`, which we enable; 20.2.1–20.2.3 miss
     the CVE fixes). Observed rollout 10:36–10:40 UTC, **4.5 minutes**: mons → mgrs → OSDs one
     node-pair at a time (a brief `OSD_DOWN`/`OSD_HOST_DOWN` HEALTH_WARN per pair is normal),
     then Rook set `require-osd-release tentacle` at 10:40:34 (downgrade impossible from here).
     No key rotation, no `HEALTH_ERR`, no pages. `status.cephx` unchanged at generation 2 (still
     stamped `keyCephVersion 19.2.6-0` — Rook only rewrites that on rotation). `min_mon_release
     20`, `ceph versions` = 15 × 20.2.4, dashboard + prometheus mgr endpoints up, 0 crashes.
     Side effect: the `open-webui` Kustomization failed its next reconcile on a Job
     immutable-field dry-run — unrelated to Ceph, see the next item.
- ✅ **open-webui: bootstrap Job re-apply race fixed (2026-09-05, same session).**
  `job-bootstrap-admin.yaml` had `ttlSecondsAfterFinished: 3600` against a 1h Kustomization
  interval, so Flux re-created the (idempotent) Job every hour and, when a reconcile landed inside
  the TTL deletion window — as the 10:40 UTC re-trigger from `rook-ceph-cluster` flipping Ready
  did — the server-side dry-run failed on the terminating Job's immutable pod template, a 2-minute
  blip that paged the Flux error Alert each time. Fix: dropped the TTL; the completed Job stays as
  a record and applying the unchanged manifest over it is a no-op (verified: the 10:30 reconcile
  succeeded with the completed Job present). Re-run deliberately by deleting the Job.
- ✅ `csi-metrics` ServiceMonitor dropped (2026-09-04, `csi.serviceMonitor.enabled: false`). It was
  dead by construction: the ceph-csi-drivers chart (1.0.4 and upstream main) cannot set
  `Driver.spec.liveness.metricsPort`, and ceph-csi-operator's `reconcileLivenessService` creates the
  Service with ports only — no labels, no selector — so the `app: csi-metrics` selector could never
  match. Revisit only if both upstream gaps close.

### Forgejo: Deferred Follow-ups (Actions Runner, WAN Exposure)

Forgejo (self-hosted git, `kubernetes/apps/development/forgejo/`) was deployed following the exact
`finance/firefly-iii` shape: official upstream chart, CNPG `Database` CRD against the shared
`postgres-v17` cluster, `ceph-block` persistence, one consolidated 1Password item. HTTPS + SSH are
both LAN-only (`envoy-internal`).

- **Backup for the repo-data PVC ✅** — wired up `components/volsync` (same pattern as
  Firefly/pgadmin/waha) against the chart's real PVC name (`gitea-shared-storage`, not the
  component's `${APP}` default of `forgejo` — verified live via `kubectl get pvc` before wiring,
  per the `waha` retrofit lesson already documented in `docs/CLUSTER.md`: "don't trust
  chart-templating assumptions").
- **Forgejo Actions / self-hosted runner** — would land as a sibling
  `kubernetes/apps/development/forgejo-runner/` app dir in the same `development` namespace.
- **WAN-facing exposure** (`envoy-external`) for either the web UI or git-over-SSH — currently LAN
  (Tailscale/VPN) only.
- **OIDC/SSO integration, SSH commit signing** — both supported directly by the chart, zero-risk
  to add later without restructuring.

### WAN Failover Router: Host Header Rewrite

**Status: fix committed (2026-07-08), pending live verification.** `wan-failover.${DOMAIN_CLUSTER}` proxied a physical router's web UI at a raw IP via `HTTPRoute` + a manually-managed `EndpointSlice`. The router's firmware validates the inbound `Host` header against its own IP and rejects/misbehaves on the proxied hostname.

Two Gateway-API-level fixes were tried and both failed in ways that made things worse, not just ineffective:
- `URLRewrite.hostname` rejects IP literals outright (`"cannot be an ip address"`).
- `RequestHeaderModifier` silently strips `Host` from its `set` list as a disallowed header, leaving the filter with nothing to apply.

Either failure leaves the `HTTPRoute` `Accepted: False`, which has a second-order effect: `external-dns-unifi` (`sources: [gateway-httproute, service]`, `policy: sync`) only advertises DNS records for `Accepted` routes and actively deletes them otherwise — so a rejected filter doesn't just fail to fix the Host-header problem, it also takes down DNS resolution for the hostname entirely (this happened live, twice).

**Resolved differently, at the user's direction**: bypass Envoy Gateway for this hostname entirely rather than fight its Host-rewrite restrictions. `kubernetes/apps/network/external-services/wan-failover/service.yaml` is now a single `Service` with no real endpoints, carrying `external-dns.alpha.kubernetes.io/target: 192.168.8.1` — this makes `external-dns-unifi`'s `service` source point the DNS record straight at the router's LAN IP instead of the Gateway's LB IP. The browser then connects directly to the router over plain HTTP (`http://wan-failover.${DOMAIN_CLUSTER}`, not `https://`) exactly as if it had typed `http://192.168.8.1` — no proxy, no TLS termination, no Host-header rewrite needed since there's no hop that changes it. `HTTPRoute`/`EndpointSlice` removed; the `envoy-gateway-config` `dependsOn` in `ks.yaml` removed too since this app no longer touches the Gateway at all. Considered and rejected: a small reverse-proxy sidecar (nginx/Caddy) that would do the rewrite itself — works, but judged too heavy for what this is.

### Renovate PR-Review Workflow: Cost/Bug Investigation, Re-enable

**Status: disabled (2026-07-04).** `.github/workflows/renovate-pr-review.yml` (invokes the `pr-upgrade-reviewer` agent via `claude-code-action` on Renovate PRs) was racking up unexpected Claude usage costs. Disabled with `gh workflow disable renovate-pr-review.yml -R qnimbus/home-lab` while the cause is investigated — re-enable with `gh workflow enable renovate-pr-review.yml -R qnimbus/home-lab` once resolved.

One contributing bug already found and fixed in the same session: on `workflow_dispatch` (manual) runs, the agent had no way to tell "local checkout" (the PR's own head commit) apart from live `main`, and on PR #71 falsely declared the PR "superseded" purely from local file contents already matching the PR's own change. Fixed in commit `f522e97` by grounding the agent explicitly — both the workflow's `prompt:` and the `pr-upgrade-reviewer` agent's own operational constraints now state that a local file read is never sufficient evidence about `main`'s state.

**Still to investigate before re-enabling:**
- What is actually driving the cost overrun — re-runs triggered per PR update, large `WebFetch`/`WebSearch` volume (fetching full release notes/changelogs per run), an unbounded retry loop, or something else not yet identified.
- Whether the `f522e97` grounding fix is sufficient on its own, or should be paired with tighter guardrails (e.g. narrower `--allowedTools`, capping WebFetch/WebSearch calls per run, gating manual `workflow_dispatch` runs the same way automatic runs are label-gated).

### Flux Render CI: Migrate flux-local → flate

**Status: shipped on flux-local (2026-09-05); flate blocked upstream.** `.github/workflows/flux-render.yaml` renders the whole Flux tree offline on every `kubernetes/**` PR — `flux-local test` as the merge gate, `flux-local build` → `scripts/validate-rendered.sh` (kubeconform on the *rendered* output), and a rendered-manifest diff vs `main` posted as one sticky PR comment by the bot App. Local equivalents: `task flux:test`, `task flux:validate`, `task flux:diff`; tool pinned as `pipx:flux-local` in `.mise.toml`. See [CLUSTER.md → CI checks](CLUSTER.md#ci-checks-github-actions).

flux-local 8.4.0 is sunsetted upstream (prints a deprecation notice) in favour of [`home-operations/flate`](https://github.com/home-operations/flate). flate 0.6.5 was evaluated the same day and **never completes on this tree**: every `test`/`build` run stalls ~0.4 s in at 140-150 % CPU with the DAG dispatcher spawning millions of goroutines; even the documented `--concurrency 1` workaround timed out at 15 min. Our graph is clean (92 Kustomizations, 45 `dependsOn`, 0 dangling, 0 cycles) — the cause is upstream: [flate#828](https://github.com/home-operations/flate/issues/828) (non-deterministic scheduler hang under parallel reconcile) and [flate#937](https://github.com/home-operations/flate/issues/937) (`dependsOn` resolution defects, unreliable `diff` exit codes).

**Migrate when:** `flate test all --path kubernetes/flux/cluster` completes on this tree in < 5 min locally (re-test after each flate minor; both issues closed is the signal). Then, same workflow shape:
- replace the `docker://ghcr.io/allenporter/flux-local` steps with `jdx/mise-action` (`install_args: "ubi:home-operations/flate kubeconform yq"`) and `"ubi:home-operations/flate"` in `.mise.toml` (Renovate's mise manager supports the ubi backend)
- `flate test all --path kubernetes/flux/cluster`; `flate build all … | scripts/validate-rendered.sh -` (flate wipes SOPS values to `..PLACEHOLDER_<key>..` rather than substituting — re-measure false positives before trusting the kubeconform pass)
- `flate diff all --base origin/main -o github` — single checkout plus `git fetch --depth=1 origin main`; the `--strip-attr` defaults already match the flux-local list; `-o github` emits `@@ <path> @@` hunks for a ```diff fence, so the sticky-comment step is unchanged

**Follow-ups (independent of the tool):**
- If branch protection is ever enabled (needs GitHub Pro or a public repo): replace the trigger-level `paths:` filter with a `filter` job + terminal `success` gate (bykaj `flux-local.yaml`), otherwise a required check that is skipped by the path filter blocks merges forever.

### Renovate on an In-Cluster Runner

**Status: parked (2026-09-05); RBAC blocker removed 2026-09-06, still not done.** Renovate moved
from the Mend-hosted app to `.github/workflows/renovate.yaml` (bykaj pattern:
`renovatebot/github-action` under the bot App, every 6 h + push-on-config + dispatch). It runs on
`ubuntu-latest` and costs ~2-3 billed minutes per run; an in-cluster runner would make it free and
allow an hourly cron.

Originally parked because neither scale set fit: `home-lab-readonly` (zero RBAC, where
`renovate-pr-review.yml` ran) couldn't take a `container:`/`docker://` job without ARC's kubernetes
container hook re-granting the namespaced Role the readonly split existed to remove, and `home-lab`
(cluster-admin) forbade auto-triggered workflows. **That split was consolidated back into a single
`home-lab` scale set on 2026-09-06** (see the Actions Runner Controller section in
`docs/CLUSTER.md`) specifically to match bykaj's simpler model — `home-lab` now runs both
auto-triggered workflows already, so the RBAC objection above no longer applies. What's still
unresolved, independent of RBAC: the container hook (`actions/runner-container-hooks`, k8s) creates
the job pod with only `fsGroup: 1001`; the job container runs as the image's own uid (Renovate
image: `USER 12021`), so writes to `$GITHUB_OUTPUT`/`_temp` on the 1001-owned work volume are a
known failure mode unless an `ACTIONS_RUNNER_CONTAINER_HOOK_TEMPLATE` forces `runAsUser: 1001` *and*
the image tolerates that uid. Also worth weighing before revisiting: Renovate running as a
`container:` job on `home-lab` would inherit that runner's `cluster-admin` + `os:admin` Talos
access — a materially bigger blast radius for an hourly-scheduled job than the scoped
`ubuntu-latest` runner it uses today, whether or not the container-hook issue gets fixed.

**Cheapest viable shape when revisited:** no job container at all — run directly in the `home-lab`
runner pod (`ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER=false` already), `actions/setup-node` (Renovate
44 needs `node ^24.11`) + `npx renovate@<pinned>`; the repo has no lockfiles, so Renovate needs only
`git`. This sidesteps the container-hook uid issue entirely (no job container), but still inherits
`home-lab`'s full privilege for the run — accept that trade-off explicitly before switching.
Independent of the runner: add `actions/cache` on `/tmp/renovate` (the action's default
`docker-volumes: /tmp:/tmp` exposes it) if lookups dominate run time.

### CloudNativePG: Backup, PITR, and Per-App Provisioning

The `cloudnative-pg-deploy` session deployed the CNPG operator and a shared `postgres-v17` cluster (3 instances, `openebs-hostpath`). Three follow-on items were explicitly deferred:

#### 1 — Barman-cloud plugin + S3 WAL archiving (PITR) ✅

Deployed 2026-06-18. The cluster previously had HA via streaming replication but no point-in-time
recovery; barman-cloud now provides continuous WAL archiving plus daily base backups to a Storj.io
S3-compatible bucket, closing that gap.

**What was implemented:**

1. **OCIRepository** `kubernetes/flux/meta/repos/oci/plugin-barman-cloud.yaml` — `oci://ghcr.io/cloudnative-pg/charts/plugin-barman-cloud` (cosign-verified, same publisher pipeline as the CNPG operator chart)
2. **plugin-barman-cloud Kustomization** `kubernetes/apps/database/cloudnative-pg/plugin-barman-cloud/app/` — HelmRelease only. The chart is fully self-contained (creates its own cert-manager `Issuer`/`Certificate`s and a pre-annotated `Service` for plugin discovery) — no manual TLS resources needed, simpler than originally scoped below
3. **ObjectStore CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml` — targets an existing Storj.io bucket (`https://gateway.storjshare.io`), not Cloudflare R2/Backblaze B2 as originally planned. Storj's client-side-encrypted, erasure-coded architecture (no single custodian holds a complete decryptable copy) avoids the US CLOUD Act exposure that R2/B2 share regardless of EU data-residency settings
4. **ScheduledBackup CR** `kubernetes/apps/database/cloudnative-pg/cluster/app/scheduledbackup.yaml` — daily `02:00 UTC` base backup, `method: plugin`, `backupOwnerReference: self`, `immediate: true`
5. **Cluster CR** — `plugins: [{isWALArchiver: true, name: barman-cloud.cloudnative-pg.io}]`; `serverName` parameterized via `postBuild.substitute.CNPG_V17_CURRENT_CLUSTER` in `ks.yaml`

**1Password fields added** to the existing `cloudnative-pg` item: `S3_ACCESS_KEY`, `S3_SECRET_KEY` (Storj access key ID / secret key).

**Two non-obvious bugs found during live testing** (fixed in commits `ff4c48d` / `9c883a6`):
- The existing ExternalSecret's `target.template.data` block is an explicit key allow-list — `dataFrom.extract` + `rewrite.regexp` only populates the *template's* variable namespace, it does **not** automatically add new keys to the rendered Secret. Adding the 1Password fields alone did nothing until `CNPG_S3_ACCESS_KEY`/`CNPG_S3_SECRET_KEY` were added explicitly to `template.data`.
- Storj's S3 gateway rejects `PutObject` calls using botocore's newer chunked-trailer checksum encoding (`MissingContentLength`). Fixed via `ObjectStore.spec.instanceSidecarConfiguration.env`, setting `AWS_REQUEST_CHECKSUM_CALCULATION`/`AWS_RESPONSE_CHECKSUM_VALIDATION` to `when_required` — the only override point the plugin exposes for the per-instance sidecar that runs both WAL archiving and base backups.

**Verified working:** `ContinuousArchiving` and `LastBackupSucceeded` Cluster conditions both `True`; a manual test `Backup` completed end-to-end (hot/online, ~4s) with objects confirmed landing in the Storj bucket.

**Recovery verified via live drill (2026-06-18):** a disposable `postgres-v17-restore-test` Cluster (`kubernetes/apps/database/cloudnative-pg/restore-test/`, removed again after the drill) recovered via `bootstrap.recovery.source` + `externalClusters[].plugin` pointing at the same `cloudnative-pg-backup` ObjectStore — `Cluster` object created to `Ready` in **54 seconds**, replaying ~5h24m of WAL forward from the most recent base backup. Confirmed as a genuine physical recovery (not a coincidentally-matching empty cluster) via `pg_control_system()`: identical `system_identifier` on source and recovered cluster, with the recovered cluster correctly promoted onto a new timeline (`1` → `2`). The renamed `cloudnative-pg-backup` ObjectStore (was `cloudnative-pg-storj`, made provider-agnostic since the CR name shouldn't bake in the current S3 backend) and a commented `bootstrap.recovery`/`externalClusters` template + runbook now live directly in `cluster.yaml` for the real disaster-recovery case — since CNPG only consults `spec.bootstrap` once, at `Cluster`-object creation, a full reset/rebootstrap today would otherwise silently `initdb` an empty database instead of recovering. Automated via `just cnpg restore-from-backup`/`undo-restore` (`ops/cnpg/mod.just`).

**Dependency chain:** `cloudnative-pg-operator → plugin-barman-cloud → cloudnative-pg-cluster` (`ks.yaml` `dependsOn`).

**Migrated to Backblaze B2 (2026-06-21):** Storj replaced as a temporary stopgap, not a permanent provider decision. Only `objectstore.yaml`'s `destinationPath`/`endpointURL` changed — no ExternalSecret/Cluster changes needed, since the ExternalSecret's `dataFrom.extract` + regex rewrite already exposes whatever `S3_ACCESS_KEY`/`S3_SECRET_KEY` values live in 1Password, and B2's `keyID`/`keySecret` map directly onto those AWS-style fields. Two regressions accepted knowingly: B2's region is fixed at the *account* level (not per-bucket), so EU data locality would need a separate account; and barman-cloud only supports server-side encryption (`AES256`/`aws:kms`), never client-side, so Backblaze itself can technically decrypt these backups — Storj's no-custodian-decrypt property is gone.

**The actual bug, after a lot of misdirection:** WAL archiving failed 100% of the time with `IncompleteBody: The request body was too small` against B2. Several plausible fixes were tried and individually disproven against the live cluster: `wal.maxParallel: 1` + trailing-slash `destinationPath` (from `cloudnative-pg/cloudnative-pg#7105`), `s3Credentials.region` + `AWS_DEFAULT_REGION` (`#9724` — a real bug, but for a different symptom, `SignatureDoesNotMatch` on retention-policy `ListObjectsV2`, not the WAL-archive failure), and downgrading `plugin-barman-cloud` `0.7.0` → `0.6.0` to rule out a library regression (same error reproduced on the older `barman-cloud@v0.5.0`). The actual cause: **the bucket name contained a literal dot** (`vwn.io-cluster-cnpg`) — AWS's own S3 docs warn against periods in bucket names because of HTTPS/virtual-hosted-style hostname-matching issues, and Backblaze's S3-compatible API broke the same way. Renaming to a dot-free bucket (`vwn-io-cluster-cnpg`) fixed `IncompleteBody` immediately, found by comparing against `bykaj/home-ops`'s working B2 config in the same region (`us-west-001`) with none of the speculative fixes applied.

**Re-verified live on the actual production cluster (2026-06-21):** ran the full `just cnpg restore-from-backup` → delete `Cluster` → Flux recreate → `just cnpg undo-restore` cycle for real, rather than a disposable test cluster (the database had no real data yet, so the risk was accepted). Confirmed genuine recovery via WAL timeline promotion (`1` → `2`) in `pg_control_checkpoint()`, not a coincidentally-healthy empty `initdb`.

---

#### 2 — Local NFS backup (postgres-backup-local) ✅

Deployed. `pg_dumpall` CronJob running daily at midnight (Europe/Amsterdam) writing to `10.200.0.41:/mnt/tank/Cluster/cloudnative-pg` (storage VLAN). Retention: 7 days / 4 weeks / 6 months. Runs as UID 4000 (non-root).

**Gotchas discovered during deployment:**
- TrueNAS NFS service must be explicitly bound to the storage VLAN interface (`bond1`) — it does not auto-bind to new interfaces
- `POSTGRES_DB: "*"` glob-expands to the NFS mount directory name (`backups`) in the script's working directory — use `POSTGRES_CLUSTER: "TRUE"` instead
- `pg_dumpall` does not support `-Z` (compression) or `-C` (create database) flags — use `POSTGRES_EXTRA_OPTS: "-c"` only
- TrueNAS dataset must be `chown 4000:4000` before the pod runs; numeric UID works fine without a named user on TrueNAS

**Restore workflow:** see roadmap item [Postgres NFS Backup: Restore Drill](#postgres-nfs-backup-restore-drill).

---

#### 3 — Per-app database and user provisioning

Apps that need PostgreSQL connect to the shared `postgres-v17` cluster. Two patterns exist:

**Option A — CNPG managed resources (preferred):** Use the `Database` and `Pooler` CRDs that CNPG installs. Each app gets its own `Database` CR (creates the database), a `ClusterRoleBinding` for the app's service account, and optionally a `Pooler` CR (PgBouncer sidecar for connection pooling). Credentials surface as a Secret that the app mounts.

**Option B — Manual provisioning:** `kubectl exec` into the primary pod and run `CREATE DATABASE` / `CREATE USER` / `GRANT`. Fast but not GitOps — avoids CRD complexity for one-off databases.

For the first app needing Postgres, use Option B to unblock quickly; migrate to Option A once the pattern is clear.

**Connection string format** (within cluster):
```
postgresql://<user>:<password>@postgres-v17-rw.database.svc.cluster.local:5432/<dbname>
```
The `postgres-v17-rw` Service is created automatically by CNPG and always points to the current primary.

---

#### 4 — Major version upgrade path (17 → 18)

CNPG supports in-place major version upgrades by creating a new cluster from a backup of the old one. The `postBuild.substitute` + `CNPG_V17_CURRENT_CLUSTER` / `CNPG_V17_PREVIOUS_CLUSTER` variables in `ks.yaml` (see bykaj reference `cluster/ks.yaml`) encode the active and previous cluster names so the `recovery.source` in the Cluster CR can be managed without editing YAML.

**When to implement:** barman-cloud (item 1 above) is now done, and its `bootstrap.recovery`/`externalClusters` mechanics have been proven end-to-end via a live drill — not just theoretically unblocked. Pick up when a 17 → 18 upgrade is actually needed.

---

### Postgres NFS Backup: Restore Drill

The `postgres-backup-local` CronJob writes a daily `pg_dumpall` backup to TrueNAS (`/mnt/tank/Cluster/cloudnative-pg`). A backup that has never been tested for restore is not a backup. This item tracks the restore workflow and periodic drills.

**Why not restore straight into `postgres-v17-rw`:** `postgres-backup-local` dumps with `POSTGRES_EXTRA_OPTS: "-c"` (clean), so the dump is a single linear script containing `DROP DATABASE`/`DROP ROLE`/`CREATE DATABASE` statements ahead of each database's data. There is no way to selectively replay that "into a temporary database" on the same live server — piping it into `postgres-v17-rw` as superuser would drop and recreate every database on the production cluster. The only way to honor "never touch live data" is a fully disposable scratch Postgres server that never contacts `postgres-v17-rw`, mirroring the barman-cloud restore drill ([item 1 above](#1--barman-cloud-plugin--s3-wal-archiving-pitr-)).

**Restore drill:** automated via `just cnpg nfs-restore-drill` (`ops/cnpg/mod.just`). The recipe:
1. Starts a disposable `postgres:17` pod (official image, not the `prodrigestivill/postgres-backup-local` client wrapper) with the NFS backup share mounted **read-only**
2. Discovers the latest backup filename dynamically from `/backups/last/*.sql.gz` inside that pod (never assumes a fixed filename)
3. Restores the dump into the scratch instance only, via plain `psql` (deliberately **without** `ON_ERROR_STOP`), timing the operation. A `pg_dumpall --clean` dump replayed by connecting as the very role it drops/recreates (`postgres`) always throws a handful of harmless, well-documented self-referential errors for that one role — can't drop your own current role, so the role "already exists" on the subsequent `CREATE ROLE`, so the dump's recorded `GRANTED BY postgres` can't be replayed until that role holds admin on the granted role. The recipe scans the output and fails only on errors **outside** that known/tolerated set — there is no `pg_restore_log` to check (that's `pg_restore`/custom-format terminology; this is a plain-text dump restored via `psql`)
4. Verifies by comparing database list (`pg_database`) and role list (`pg_roles`) between the scratch (restored) instance and the live `postgres-v17` primary — the live-side check is read-only, via `kubectl exec` into the existing CNPG primary pod (local trust auth as the `postgres` OS user), so the production superuser password is never extracted from `cloudnative-pg-secret`
5. Tears the scratch pod down unconditionally (`trap ... EXIT`), so a failed run never leaves an orphaned pod. Set `KEEP_SCRATCH=1` to skip auto-teardown for manual inspection (used for the canary check below)

**Bug found and fixed by the first drill run:** `postgres-backup-local`'s `POSTGRES_EXTRA_OPTS` was `"-c"` only, which makes `pg_dumpall` emit *unconditional* `DROP DATABASE`/`DROP ROLE` statements. Restoring onto a fresh/empty target (exactly the disaster-recovery scenario this backup exists for) failed immediately on the first `DROP DATABASE app` — the database that never existed there. Fixed by adding `--if-exists` (commit `18a053a`, pushed) — the standard pairing for `--clean` that makes those drops conditional.

**Restore drill checklist:**
- [x] Confirm the drill restored into the disposable scratch pod only — `postgres-v17-rw` was never contacted (structural: the recipe never references that Service)
- [x] Confirm database list and role list match between scratch and live (modulo the scratch pod's own bootstrap defaults)
- [x] Confirm no *unexpected* `ERROR`/`FATAL` lines in `psql` output (the tolerated self-referential `postgres`-role errors above are expected on every run, not a failure signal)
- [x] Document the time taken (RTO) — printed by the recipe on completion
- [x] Confirm the scratch pod was deleted (`kubectl get pod -n database` shows it gone)

**Scope note:** no per-app data exists on `postgres-v17` yet — [item 3, per-app provisioning](#3--per-app-database-and-user-provisioning), is still pending — so the first drill run seeded a throwaway canary database/table on production (then deleted it) purely to give the row-count check something real to verify. Going forward, re-run this drill after item 3 lands real app data and extend the verification step to compare row counts for the app's key tables.

**When to drill:** after first successful backup, then every 3 months or after any major Postgres version upgrade. Each run is recorded below:

| Date | Duration (RTO) | Pass/Fail | Notes | Next due |
|------|-----------------|-----------|-------|----------|
| 2026-06-18 | 4s | ✅ Pass | First run. Found+fixed a real restore-blocking bug (missing `--if-exists`, commit `18a053a`). Canary dataset (50 rows) restored intact, matching live exactly; database/role lists matched | 2026-09-18 |

**Real disaster-recovery restore (production-touching):** automated via `just cnpg nfs-restore-from-backup` (`ops/cnpg/mod.just`) — the actual incident-recovery procedure, distinct from the disposable drill above. **Only safe when `postgres-v17` has no data worth losing** (verified live by the recipe before it asks for confirmation) — it restores **directly into `postgres-v17-rw`**, dropping and recreating every database. The recipe:
1. Prints the current database list on `postgres-v17-rw` and warns explicitly before asking to proceed
2. Starts a helper pod (official `postgres:17` image, command overridden to `sleep infinity` so it never runs its own `initdb`) with the NFS share mounted read-only and `PGHOST`/`PGUSER`/`PGPASSWORD` wired from `cloudnative-pg-secret` via `secretKeyRef` — credentials never pass through a shell or this tool's context
3. Discovers the latest backup file and prints its mtime for visual confirmation, behind a second confirm gate
4. **Terminates all other active backend connections** to `postgres-v17-rw` (`pg_terminate_backend`) immediately before restoring — `DROP DATABASE` refuses to run while *any* session, even idle, is connected, and pgAdmin keeps a persistent connection open per database it has browsed
5. Restores via `gunzip | psql` (no `ON_ERROR_STOP`), timing the run, and tolerates the same self-referential role errors as the drill plus one CNPG-specific case: `streaming_replica` (CNPG's permanent replication role) can't be dropped because it permanently holds `EXECUTE` grants on file-access functions used by CNPG's instance manager — that role is reconciled by the CNPG operator independently of this dump, so leaving it untouched is correct
6. Prints the database list again and tears the helper pod down unconditionally

**First real run (2026-06-19):** validated end-to-end against live production with no per-app data at risk (`app` had zero user tables at the time). Two real, previously-undiscovered issues surfaced and were fixed before the run that finally passed cleanly:
- A `gum log` formatting bug: passing a multi-line message as several separate quoted strings (used purely for source readability) followed by a trailing `stage <value>` pair caused `gum` to mis-pair the extra strings as bogus key/value fields, garbling the rendered warning. Fixed by collapsing each multi-string message into one string — also retroactively fixed in `nfs-restore-drill`'s verify-warning and `restore-from-backup`'s existing-cluster warning, which had the same latent bug.
- `streaming_replica`'s standing function grants blocking `DROP ROLE` (see step 5) — added to the tolerated-error filter.
- pgAdmin's idle per-database connections blocking `DROP DATABASE` (see step 4) — fixed by terminating other backends immediately before the restore.

| Date | Duration (RTO) | Pass/Fail | Notes | Next due |
|------|-----------------|-----------|-------|----------|
| 2026-06-19 | 1s | ✅ Pass | First real run against `postgres-v17-rw` (no per-app data at risk). Two attempts failed and were fixed in-flight (`streaming_replica` grant-dependency tolerance, pgAdmin connection termination) before a clean pass; also fixed a latent `gum log` formatting bug found along the way | 2026-09-19 |

**Dependencies:** `postgres-backup-local` ✅ (backup running)

---

### ~~Longhorn Storage Network (Multus + Storage VLAN)~~ — ABANDONED, superseded by Rook-Ceph

> **Status: ABANDONED (2026-06-05).** After 5 attempts, routing Longhorn engine↔replica traffic onto
> the storage VLAN via Multus + whereabouts (ipvlan-L3) was abandoned on an unsolvable **same-host iSCSI**
> blocker. The full attempt log, root-cause analysis, and the whereabouts PR #703 finding are preserved in
> [history/longhorn-storage-network.md](history/longhorn-storage-network.md); the distilled root cause is in
> [QA.md](QA.md#why-was-routing-longhorn-replica-traffic-onto-the-storage-vlan-abandoned). The storage-VLAN
> isolation goal now moves to **Rook-Ceph**, whose native `cluster_network` on `hostNetwork` OSDs sidesteps
> the same-host problem — see [Rook-Ceph Migration](#rook-ceph-migration) below and
> [HARDWARE-ARCHITECTURE.md](HARDWARE-ARCHITECTURE.md).
>
> All Multus/whereabouts/NAD scaffolding + the Cilium `cni.exclusive` override + cross-node `/28` Talos
> routes were removed in the rollback (commit `299904e`). `bond-storage` + jumbo MTU are **kept** (Ceph
> reuses the fabric).

**~~Still-valid tuning lifted from the abandoned plan~~ — VOID (Longhorn removed):** the carried-over
suggestion to raise Longhorn's `replicaReplenishmentWaitInterval` (`600`→`900` s) no longer applies —
the `kubernetes/apps/longhorn-system/` tree was deleted in the Rook-Ceph migration. Ceph's analogous
behaviour (delaying recovery after a node loss so the network can converge) is governed by the OSD's
`mon_osd_down_out_interval` (default 600 s), which is already conservative; no change needed.

---

### Rook-Ceph Migration

The committed replacement for both Longhorn (interim) and the abandoned storage-VLAN isolation effort.
Target topology, drive placement, failure-domain design, and the 5-node expansion context are specified in
**[HARDWARE-ARCHITECTURE.md](HARDWARE-ARCHITECTURE.md)** (Rook-Ceph `size=3`/`min_size=2`, `host` failure
domain, OSDs on the `10.200.0.0/24` bond). Detail intentionally lives in the hardware doc — do not duplicate
it here.

**✅ COMPLETE (2026-06-10).** Rook-Ceph v1.19.6 deployed via Flux under `kubernetes/apps/rook-ceph/`
(operator + cluster split, host networking with `cluster_network` on the storage bond, OSDs pinned by
`/dev/disk/by-id`); `HEALTH_OK` with 3 host-spread OSDs. `ceph-block` is the **default StorageClass**.

- **Phase 4** — operator + cluster deployed; storage-fabric benchmarked (~19.3 Gbit/s aggregate, drive-bound).
- **Phase 5** — all consumers re-pointed from longhorn → `ceph-block`: **pgadmin** (canary, disposable),
  **waha** (WhatsApp `gows/` session restored from NFS, reconnected `WORKING` no QR re-scan), and
  **kube-prometheus-stack** (grafana `grafana.db` restored from NFS; prometheus/alertmanager fresh). The
  prometheus+alertmanager StatefulSets were deleted out-of-band first (immutable `volumeClaimTemplates`).
  Stale longhorn PVC/PV zombies (never deleted, only backed up) were force-cleared. Longhorn fully gone.

#### Toolbox deployment style (current: chart built-in)

Phase 4 enables the **chart-supplied** toolbox (`toolbox.enabled: true` in the `rook-ceph-cluster`
HelmRelease) — a single `rook/ceph` Deployment giving the `ceph` CLI in-cluster
(`kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status`). Lowest-maintenance option;
sufficient for status/debugging.

**Possible future switch — standalone `app-template` toolbox** (ByKaj pattern,
`tmp/home-ops-bykaj/.../rook-ceph-tools/`): a separate `bjw-s/app-template` HelmRelease with the chart's
built-in toolbox turned off. Worth adopting only for extras the built-in lacks — an NFS `Transfer` mount for
exporting/importing RBD images or `ceph` dumps to the NAS, explicit resource limits + Reloader annotations,
or a toolbox image pinned by digest independent of the chart. Cost: one more HelmRelease + OCIRepository to
maintain. Defer until a concrete need (e.g. offline image export) appears.

---

### ~~cp-02 Thermal Stability (Lenovo M920Q)~~ — RESOLVED

> **Status: RESOLVED.** Two distinct fault patterns on this M920Q unit (now `talos-worker-02`,
> 10.60.0.205) — a 2026-06-01 board/VRM thermal shutdown, and a series of recurring silent
> hard-downs spanning 2026-06-02 → 2026-06-21 — are both closed. The thermal fault was fixed by
> a heatsink clean + repaste (2026-06-17); the hard-downs were root-caused (2026-06-22) to a
> failing external power brick via MemTest86 hardware-isolation, which has since been replaced
> and confirmed stable. Full investigation timeline, diagnostics, and tooling:
> [history/cp02-worker02-hardware-faults.md](history/cp02-worker02-hardware-faults.md).

---

### Future Storage Options

Replicated block storage is covered by the committed [Rook-Ceph Migration](#rook-ceph-migration) (Ceph also
provides RWX block volumes and S3-compatible object storage natively). The remaining optional item:

> **Status: NFS deployed, SMB driver-only.** `csi-driver-nfs` (dynamic `nfs` StorageClass, dedicated
> TrueNAS export `/mnt/tank/Cluster/k8s-nfs-csi`, `Delete` reclaim) and `csi-driver-smb` (driver +
> `smb-credentials` ExternalSecret, no dynamic StorageClass) are both deployed in
> `kubernetes/apps/system/csi-driver-nfs/` and `kubernetes/apps/system/csi-driver-smb/`. SMB has no
> concrete consumer app yet — future SMB workloads use a hand-authored static
> PersistentVolume/PersistentVolumeClaim pair (`driver: smb.csi.k8s.io`, `nodeStageSecretRef` →
> `smb-credentials` in the `csi-driver-smb` namespace), not a dynamic StorageClass, since each SMB
> share needs its own explicit `source`/credentials. NFS: any future app can request
> `storageClassName: nfs` directly. Two manual, out-of-band prerequisites gate this working:
> the `/mnt/tank/Cluster/k8s-nfs-csi` NFS export must be created on TrueNAS (Storage VLAN,
> `10.200.0.0/24`), and a `smb-credentials` item (fields `SMB_USERNAME`/`SMB_PASSWORD`) must exist
> in the `homelab` 1Password vault. Talos's CIFS/SMB kernel client support is unconfirmed (no
> existing SMB mount in this repo to prove it) — worth validating with a real static-PV smoke test
> before treating SMB as production-ready.

- **NFS/SMB CSI**: Deploy `csi-driver-nfs` and/or `csi-driver-smb` for ReadWriteMany file workloads (photo libraries, shared media) backed by the NAS. Wire credentials via ExternalSecret from 1Password (ESO + 1Password Connect already deployed — no blocker). Optional even after Rook-Ceph, for NAS-backed RWX where Ceph capacity should be conserved.

---

### Storage VLAN Performance Benchmarking

A repeatable benchmark suite for the storage VLAN fabric. Run after any network change (MTU, bonding config, switch firmware, node add/replace) and periodically as a regression check. Methodology developed during the `jumbo-frames-storage-vlan` session.

All tests use host-network pods bound to the storage VLAN IP (`-B 10.200.x.x`) to bypass Cilium and measure the raw bond path. The iperf3 server on TrueNAS must be running (`iperf3 -s -D`; for the bond test also `iperf3 -s -p 5202 -D`).

#### Test 1 — Single-stream link health (run per node)

```bash
kubectl run iperf3-raw --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-01"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.201 -t 10
# Repeat with cp-02 (10.200.0.202) and cp-03 / -B 10.200.0.203 / bond1
```

**Pass:** ≥9.8 Gbps, ≤100 retransmits. Failure indicates link degradation, MTU mismatch, or CC misconfiguration.

#### Test 2 — MTU end-to-end verification (MSS 8960 = MTU 9000 − 40)

```bash
kubectl run iperf3-raw --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 5 -M 8960
```

**Pass:** connection succeeds, Cwnd reaches ≥2 MB. Failure means a hop is still at 1500 MTU.

#### Test 3 — Bond utilization (bidirectional simultaneous)

```bash
kubectl run iperf3-send --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 12 -P 8 -p 5201 &
kubectl run iperf3-recv --restart=Never --image=networkstatic/iperf3 \
  --overrides='{"spec":{"hostNetwork":true,"nodeSelector":{"kubernetes.io/hostname":"talos-cp-03"}}}' \
  -- -c 10.200.0.41 -B 10.200.0.203 -t 12 -P 8 -p 5202 -R &
```

**Pass:** combined send + receive ≥25 Gbps (proves both bond members active). ≤10 Gbps total means one bond member is down or the switch is distributing incorrectly.

#### Prometheus metrics to monitor

Node-exporter exposes per-interface byte counters. Wire into Grafana once deployed:

```promql
# Per-bond-member throughput on storage NICs
rate(node_network_receive_bytes_total{device=~"enp1s0f[01]|enp5s0f[01]np[01]"}[5m]) * 8
rate(node_network_transmit_bytes_total{device=~"enp1s0f[01]|enp5s0f[01]np[01]"}[5m]) * 8
# TCP retransmit rate (cluster-wide)
rate(node_netstat_Tcp_RetransSegs[5m])
```

Bond member devices: cp-01/02 bond0 → `enp1s0f0` / `enp1s0f1`; cp-03 bond1 → `enp5s0f0np0` / `enp5s0f1np1`.

#### Baselines (2026-05-30 — MTU 9000 + BBR)

| Test | Result |
|------|--------|
| Single stream cp-01 → TrueNAS | 9.90 Gbps, 0 retx |
| Single stream cp-03 → TrueNAS | 9.91 Gbps, 0 retx |
| TrueNAS → cp-03 reverse | 9.87 Gbps, 0 retx |
| MTU verify (MSS 8960) | ✅ Cwnd 2.36 MB |
| Bidirectional 8+8 streams (cp-03) | 13.1 + 13.9 = **27.0 Gbps** — both bond members confirmed |

**Dependencies:** storage VLAN jumbo frames ✅ (`jumbo-frames-storage-vlan`), BBR + fq ✅. Independent of all other roadmap items.

---

### Grafana

**✅ Done.** Deployed via kube-prometheus-stack (`grafana.enabled: true`). Persistence on a `ceph-block` PVC
(`strategy: Recreate`, RWO); `grafana.db` was restored from the NFS backup during the Phase 5 storage
migration. `sidecar.dashboards`/`sidecar.datasources` enabled (auto-discovers ConfigMaps labelled
`grafana_dashboard: "1"` cluster-wide); served at `https://grafana.${DOMAIN_CLUSTER}` via an
`envoy-internal` HTTPRoute; admin password from 1Password via ExternalSecret.

> Remaining polish (optional, not blocking): confirm `forceDeployDashboards` coverage and prune the
> bundled **Longhorn** dashboards (dead — Longhorn removed) to reduce dashboard clutter.

---

### Alertmanager Receiver

**✅ Done (2026-06-20, commits `878b7d1`, `0d51e10`).** A root `AlertmanagerConfig` (`alertmanagerSpec.alertmanagerConfiguration.name`) routes by `severity` label — `critical` → emergency-priority Pushover (retry/expire, persistent sound), `warning|error` → normal Pushover, default `null`. The `error` value also catches Flux's own `notification-controller` `Alert`/`Provider` forwarding. Credentials via a new `alertmanager` ExternalSecret from 1Password. Live-tested; a message-truncation bug (Pushover's 1024-rune cap, blown past by the per-alert label dump multiplying across grouped alerts) was found and fixed in the same pass.

> Residual, unverified: whether each "alerting rule to add at minimum" below already exists as a bundled rule (Rook-Ceph ships its own Ceph-mixin `PrometheusRule`s; kube-prometheus-stack ships default rule groups) or still needs to be authored — the routing now exists either way, but coverage hasn't been confirmed metric-by-metric.
> - `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod accumulation
> - `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
> - `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure
> - `ceph_health_status != 0` — Ceph not `HEALTH_OK` (warn on `1`/`HEALTH_WARN`, page on `2`/`HEALTH_ERR`)
> - `ceph_osd_up < ceph_osd_in` — a Ceph OSD is `in` the CRUSH map but `down` (degraded redundancy)

---

### e1000e Management-NIC Packet Drops: `netdev_budget` Experiment

**Current status (2026-09-01) — TL;DR.** The full chronological investigation is below; this is
the current-state summary for anyone (including a future session) who doesn't want to read all of
it to know where things stand.

- **Confirmed mechanism**: NIC RX-ring exhaustion on `eno1` (Intel I219-LM, `e1000e`,
  single-queue) — the driver's own `rx_dropped` counter, a layer below softirq. Not CPU/softirq
  contention, not bandwidth/pps saturation (both directly refuted with live data).
- **Fixed, shipped, verified**:
  - `sabnzbd`/`sonarr`/`radarr`/`prowlarr`'s `/config` PVCs migrated off `ceph-block` onto NFS —
    removed one confirmed Ceph-client-I/O trigger.
  - VolSync's hourly backup schedule (8 `ceph-block`-backed apps, previously all synchronized to
    the same ~30s window every hour) staggered via a new deterministic tool
    (`scripts/volsync-schedule.py`) — removed a second, independently-confirmed synchronized-burst
    risk.
- **Ruled out** as explanations for why only `cp-03`/`worker-02` alert (not `cp-02`/`worker-01`,
  same NIC/driver): Ceph role placement (no pattern), Energy Efficient Ethernet (identical,
  inactive on all 4 nodes), and the original `netdev_budget`/softirq theory (superseded by the
  ring-exhaustion finding).
- **Confirmed viable, not yet implemented**: raising the RX ring buffer (`ethtool -G eno1 rx
  <N>`) — confirmed 16x headroom (256/4096 descriptors, identical on all 4 nodes) via live
  `ethtool -g`, re-confirmed unchanged 2026-09-02. This is the most directly-indicated remaining
  fix. Needs an unsupported Talos workaround (no declarative field for ring sizing) —
  **deliberately not built yet**, pending an explicit decision to implement. A pre-fix baseline
  was captured 2026-09-01 for comparison whenever it does get applied — see the baseline table
  further down this entry.
- **Escalated overnight, cause still unresolved — and the working traffic-source theory just got
  a serious complication (2026-09-02).** `cp-03`/`worker-02` had a much rougher stretch than the
  baseline (5-6 firing clusters each between 2026-09-01 15:42 and 2026-09-02 04:55 UTC, peak
  burst magnitude 3.6-3.8x higher, roughly as many drops in ~12h as their entire prior history).
  Checked every specific-workload hypothesis (Ceph scrub, client op-rate, CNPG, Envoy, Plex,
  victoria-logs, VolSync, CronJobs) and **all came back negative** — nothing correlates. What *did*
  turn up, unexpectedly: the bursty small-packet (127-585 byte, well under MTU) traffic pattern
  also exists on `cp-01` — the node that has never once alerted — at 10-100x higher packet rate,
  continuously, even when `cp-03`/`worker-02` are quiet. `cp-01` just has a bigger NIC/ring and
  absorbs it. Which nodes see this traffic at all lines up exactly with which node currently holds
  a Cilium L2-announcement leader lease for some Service (`cp-02`/`worker-01` hold none and have
  never shown this pattern) — but the actual *application* traffic behind those leases (Envoy
  requests, syslog rows, Plex bytes) wasn't elevated during the bursts, so it isn't simply "more
  legitimate traffic." **This means the traffic causing most of these drops may not be Ceph
  client I/O at all** — the `sabnzbd` episode was confirmed as genuine Ceph RBD traffic, but this
  broader, more persistent pattern looks like Cilium/datapath-adjacent chatter instead (plausible
  guess: L2-announcement-related ARP traffic; unconfirmed). **Real implication**: if this traffic
  isn't Ceph, moving Ceph's `public_network` to the storage VLAN (item #4 below) wouldn't touch
  it — that project's rationale needs re-examining before it gets more weight as "the fix."
- **2026-09-03 — a fresh episode reconfirms genuine Ceph `public_network` traffic as (at least) a
  contributing mechanism, via a disambiguation method that's now repeatable.** A `cp-03`+`worker-02`
  episode (04:20-04:42 UTC) traced to `rook-ceph-mon-a`/`osd-0`/`osd-3` write activity on `cp-01`
  (real counters, not the gauge-`rate()` mistake caught mid-investigation), and — checked directly
  against live Cilium L2-announcement lease holders — `cp-03` held **zero** leases at the time yet
  mirrored `worker-02`'s burst shape in lockstep. That rules out L2-lease chatter as *this* episode's
  explanation (cp-03 has none to chatter about) and points back to Ceph mon-quorum/OSD
  heartbeat-front traffic between `cp-01` and its `public_network` peers on `cp-03`/`worker-02`.
  Also newly confirmed: this failure mode now has a second victim beyond the alert itself —
  Prometheus's own rule-group evaluation stalled 216s and missed 34 iterations because its
  Ceph-RBD-backed TSDB PVC contended for I/O during the same window (`PrometheusMissingRuleEvaluations`,
  previously flagged unexplained in the 2026-09-01 triage session). Full writeup:
  [QA.md](QA.md#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan).
  Doesn't overturn the 2026-09-02 Cilium/L2 finding for *other* episodes, but restores weight to
  item #4 below rather than leaving it fully discounted — and **the user has now said (2026-09-03)
  they want to actively move toward implementing it**, not just track it as a someday project. See
  the dedicated section for the status change and concrete next steps this triggers.
- **Possible troubleshooting steps from here, roughly ranked** (none implemented yet — see the
  numbered list further down for full detail on each):
  1. Build the `ethtool -G` ring-size workaround — cleared to proceed, not yet built. Still likely
     to help regardless of the traffic source, since it directly addresses the ring layer.
  2. Live packet capture on `cp-01`'s `enp4s0` (or `cilium monitor`/BPF-level metrics) during a
     future burst, to positively identify the small-packet traffic — supersedes the earlier
     `rbd perf image iostat` plan now that the leading hypothesis has shifted away from Ceph.
  3. Check Plex's `/config` PVC (same `ceph-block`/SQLite shape as the confirmed `sabnzbd`
     trigger) if it's ever implicated — still open, though now a secondary lead behind #2.
  4. [Move Ceph's `public_network` to the storage VLAN](#ceph-public_network-move-to-storage-vlan)
     — reconfirmed (2026-09-03) as addressing at least a real subset of episodes, and now the
     user's explicitly stated direction of travel; still cluster-wide blast radius and an
     unresearched live mon reconfiguration, which is exactly what the dedicated section below is
     now scoping as concrete next steps rather than open-ended caveats.
  5. Last resort: widen the alert's `for:` window (masks symptoms, doesn't fix anything).

---

**Applied live 2026-08-05 ~11:20 UTC** (via `talosctl apply-config`, no reboots needed — confirmed
via `talosctl read` on all 4 nodes; etcd quorum and Ceph `HEALTH_OK` unaffected throughout the
rollout; committed in `f4d1c8a`). `CephNodeNetworkPacketDrops` recurs on the 4 nodes with an Intel
I219-LM (`e1000e`) management NIC (`cp-02`, `cp-03`, `worker-01`, `worker-02`) but never on `cp-01`
(newer Intel I225/I226, `igc`) — full root-cause writeup in
[QA.md](QA.md#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan).
Confirmed the drops are receive-only with zero FIFO/hardware-ring errors (a software RX-path
symptom, not link saturation), and that `net.core.netdev_max_backlog` — already bumped to 300000
fleet-wide for the Ceph storage bond — has no effect on it (confirmed live via `talosctl read` on
`cp-02`, still at kernel defaults: `netdev_budget=300`, `netdev_budget_usecs=8000`, unaffected by
the backlog change).

Staged `talos/patches/node/machine-sysctl-netdev-budget.yaml` (wired onto the 4 affected nodes
only) raises `net.core.netdev_budget` to `1000` and `net.core.netdev_budget_usecs` to `16000` —
this governs how much the `NET_RX` softirq drains from *all* polled NAPI devices (every physical
NIC and every Cilium-managed pod veth) per pass, which is a more plausible bottleneck than backlog
depth for a hardware-NAPI driver like `e1000e`. **This is genuinely an experiment** — there's no
confirmed mechanism for the underlying ~3-minute periodic burst itself, so there's no guarantee
this sysctl is the right lever — live values now `netdev_budget=1000`, `netdev_budget_usecs=16000`
on all 4 nodes, verified via `talosctl read`.

#### Metrics to monitor (before/after comparison)

```promql
# Total RX-dropped packets per node per day — the cleanest, alert-independent signal
sum by (instance) (increase(node_network_receive_drop_total{device="eno1", instance=~"10.60.0.20[2-5]:9100"}[24h]))

# Peak burst magnitude per node (does the burst itself shrink, even if not eliminated?)
max_over_time((rate(node_network_receive_drop_total{device="eno1"}[1m]))[24h:15s])

# Did it actually page (crossed the `for: 1m` threshold)?
count_over_time(ALERTS{alertname="CephNodeNetworkPacketDrops", alertstate="firing"}[24h])
```

#### Baseline (2026-08-05, pre-patch)

| Node | 24h total RX drops (`eno1`) | 24h firing (paged) count |
|------|------------------------------|---------------------------|
| cp-02 (`.202`) | 736,638 | 25 |
| cp-03 (`.203`) | 748,074 | 0 |
| worker-01 (`.204`) | 755,388 | 0 |
| worker-02 (`.205`) | 744,322 | 0 |

Only `cp-02` has ever crossed the `for: 1m` debounce and actually paged; the other 3 nodes
self-resolve as `pending`. All 4 nodes drop a broadly similar *volume* of packets/day despite that
difference — `cp-02` apparently just has slightly-longer-duration bursts, not more frequent ones.

**Early read (2026-08-05, ~3h post-apply, matched 08:12-11:20 vs 11:20-14:28 windows):** all 4
nodes moved the same direction on every metric — total RX-drop volume down 13-16%, peak burst
magnitude down 15-33% (bigger effect on `cp-03`/`worker-01`/`worker-02` than `cp-02`), and `cp-02`'s
firing count went 4 → 1. Encouraging, but **not conclusive**: the two windows are adjacent
different times of day rather than the same hour on different days, so some of this could be
diurnal traffic variation rather than the patch, and 3h/4-firings is a small sample. Needs the full
1-2 week checkpoint below to separate signal from noise.

**Checkpoint (2026-09-01, ~4 weeks post-patch) — split result, not a uniform fix.** The planned
1-2 week re-check slipped; by the time it ran, Prometheus's 2-week retention (`storage.tsdb.retention.time=2w`)
plus a fleet-wide reboot of all 4 nodes on 2026-08-19 (~09:09-11:37 UTC, unrelated maintenance) had
already reset `node_network_receive_drop_total`'s counters, so a true 27-day trend isn't queryable —
the longest available continuous window is the 13 days since that reboot, which happens to double
as a clean before/after split point. Sysctls confirmed still correctly applied on all 4 nodes via
`talosctl read` (`netdev_budget=1000`, `netdev_budget_usecs=16000` everywhere) — the split below is
a real behavioral divergence, not config drift.

| Node | Baseline 24h drops (Aug 5) | Baseline firings | 13d total drops (since Aug-19 reboot) | Current 24h drops (Sep 1) | Current 24h firings |
|------|------------------------------|---------------------------|------------------------------------------|------------------------------|------------------------|
| cp-02 (`.202`) | 736,638 | 25 | **0** | 0 | 0 |
| worker-01 (`.204`) | 755,388 | 0 | **1,666** | 0 | 0 |
| cp-03 (`.203`) | 748,074 | 0 | 4,616,015 | 502,376 | 9 (~2 episodes) |
| worker-02 (`.205`) | 744,322 | 0 | 5,081,565 | 755,618 | 6 (~2 episodes) |

- **`cp-02`/`worker-01`: the patch worked** — >99.99% reduction, zero alert firings across the full
  13-day post-reboot window. Order-of-magnitude success, exactly the outcome hoped for.
- **`cp-03`/`worker-02`: the patch did not hold.** Aug 20-24 looked equally good (10K-40K
  drops/day, ~95%+ down from baseline), then a regression set in: Aug 25 jumped to 212K-227K/day,
  Aug 26-27 spiked to **1.1M-1.7M/day — worse than the pre-patch baseline** — partially recovered
  Aug 28, then climbed steadily again through Aug 31-Sep 1 (176K→253K→377K→502K/day/node),
  culminating in `cp-03`/`worker-02` paging again this morning (2026-09-01, 10:10-10:17 UTC).

**Root cause of the regression — confirmed, not speculated (2026-09-01 live investigation):** this
morning's page coincided almost exactly with a `sabnzbd` download burst (`downloads` namespace).
Timing: `sabnzbd`'s `container_network_receive_bytes_total` ramped from 1.7 MB/s at 10:10 UTC to a
84.5 MB/s peak at 10:13:30, sustained 60-75 MB/s through 10:16; `cp-03` went `pending` at 10:10:45
(45s into the ramp) and both nodes fired 10:14:45-10:17:00 — squarely inside the sustained-download
window. But `sabnzbd`/`prowlarr`/`sonarr`/`radarr` all run on **`talos-cp-01`** (the unaffected
`igc` node) — so this is *not* host-NIC contention between the *arr pods and the alert-affected
NICs. The mechanism established so far: `sabnzbd`'s `/config` PVC (5Gi, `ceph-block`, RWO) holds
its SQLite queue/history database — the only thing it has on Ceph, since (confirmed 2026-09-01 by
reading the manifests directly) the actual downloaded bytes land on a raw NFS mount, never
touching Ceph. What's still **inferred, not separately measured**: that `/config`'s DB writes
during a download are large/frequent enough on their own to produce the observed traffic — a
timing correlation plus the PVC/network mapping, not a measured RBD byte-volume for this PVC. That
gap is exactly what follow-up #2 below (map the RBD image to its PG/OSD acting set, or read
per-OSD write-bytes during a live burst) would close. And `CephCluster.spec.network.addressRanges.public`
is `10.60.0.0/24`, the **same management VLAN** `eno1`/this alert watches. `cp-03` and `worker-02`
happened to host the OSDs holding the busy PGs during this burst (`cp-03`: OSD 2/4; `worker-02`:
OSD 6/9 + mon-d) — confirmed via a genuine packet-rate surge on `eno1` itself
(`node_network_receive_packets_total`: cp-03 921→5,324 pps, worker-02 595→4,210 pps, a 5-7x jump
matching the burst window exactly, not just alert-threshold noise). Plex (also on `cp-03`) was
ruled out as the trigger — its own pod-level traffic was <900 B/s throughout. This also explains
the run's day-to-day node variance in the table above: which nodes get hit depends on which OSDs
currently hold the hot PGs, which shifts over time — not a fixed hardware weakness on `cp-03`/`worker-02`
specifically.

**Mechanism, confirmed 2026-09-01 — NIC RX-ring exhaustion, not softirq/CPU contention.** The
initial working theory (this morning's page = OSD-daemon CPU competing with `eno1`'s softirq for
the same core) was checked directly against Prometheus for the exact burst window
(`cp-03`/`worker-02`, 10:05-10:20 UTC) and **refuted**:
- `rate(node_softnet_times_squeezed_total[1m])` — the direct signal for "`NET_RX` softirq ran out
  of its `netdev_budget` before finishing"— stayed **flat zero** on every core, the whole window.
- `rate(node_softnet_dropped_total[1m])` — the `netif_rx`/backlog-overflow counter — also flat
  zero (consistent with `e1000e` being a NAPI driver that drains its own ring directly and mostly
  bypasses that backlog path anyway).
- Busiest core hit only ~8-12% softirq, idle stayed >78% throughout on both nodes. Rook-Ceph OSD
  pod CPU (`osd-2`/`osd-4` on `cp-03`, `osd-6`/`osd-9` on `worker-02`) sat flat at 0.04-0.2 cores —
  no OSD-vs-softirq contention.
- The metric that actually moved: `rate(node_network_receive_drop_total{device="eno1"}[1m])`
  itself — 0 → 600-1,600 drops/sec, exactly in 10:13:30-10:17:00 UTC. This is the NIC driver's own
  `rx_dropped` counter, a layer *below* both the softnet backlog and the NAPI budget loop: the
  RX descriptor ring filling up (or an `skb` allocation failure) before the kernel drains it.
- The Intel I219-LM (`e1000e`) is hardware **single-queue** — no RSS/multi-queue support, unlike
  the storage bond's `ixgbe`/`igc`-class NICs — so its entire RX path, ring included, pins to one
  CPU core with no way to spread load, regardless of how high `netdev_budget` is set.

**This means `netdev_budget` was tuning the wrong layer for this failure mode.** It raises how
much a CPU processes *per softirq pass* — correct if the bottleneck is backlog/budget exhaustion
(the `squeezed`/`dropped` counters), but irrelevant if packets are being dropped by the driver
before they ever reach softirq processing. `cp-02`/`worker-01` showing zero drops since Aug-19
is genuine — but on current evidence it may mean "no Ceph write burst large enough to expose the
same ring-exhaustion has landed on their OSDs yet," not "the sysctl fixed the underlying failure
mode there." All 4 nodes share the identical NIC/driver, so all 4 are presumed equally exposed to
ring exhaustion under a big enough burst; which ones actually show it depends on CRUSH/PG
placement at the time, per the mechanism above.

**Confirmed (2026-09-01) — real headroom exists, `ethtool -G` is worth pursuing.** Checked
`ethtool -g eno1` live on all 4 e1000e nodes via `kubectl debug node/... --image=nicolaka/netshoot`
(same approach as the EEE check below — `hostNetwork` automatic, no nsenter/chroot needed):
identical everywhere, RX/TX both `256` current against a `4096` pre-set hardware maximum — **16x
headroom**, never touched from the `e1000e` driver default on any node. Offload settings
(`rx-checksumming`, `generic-receive-offload`, `large-receive-offload`) also came back stock and
identical on all 4 — not a contributing factor. One caveat the check surfaced: ring size is
uniform across alerting (`cp-03`/`worker-02`) and quiet (`cp-02`/`worker-01`) nodes alike, so it
doesn't by itself explain *which* nodes hit the ceiling under a given burst — that remains
burst-timing/hot-PG locality (see "Ruled out" below), not a contradiction. Take a
`node_network_receive_drop_total` baseline per node before applying a bump, for a clean before/after.
Re-confirmed unchanged on 2026-09-02 (still `256`/`4096` on all 4 nodes, as expected — nothing
had been applied in between; a reboot alone would not change this, since ring size is a driver-init
default re-set on every boot, not persisted state a reboot could reset to something different).

**Pre-`ethtool -G` baseline, captured 2026-09-01 20:33:27–20:34:03 UTC** (ring still at
default 256/4096 — same 3 PromQL queries as the original 2026-08-05 baseline, for methodological
consistency, plus a 7d window and the raw absolute counter since episodes are sparse enough that
24h alone can be noisy):

| Node | 24h RX-drop Δ | 7d RX-drop Δ | Peak burst 24h (drops/sec) | Firing samples 24h | Firing samples 7d | Absolute counter |
|------|---------------:|---------------:|------------------------------:|----------------------:|----------------------:|--------------------:|
| cp-02 (`.202`) | 0 | 0 | 0 | 0 | 0 | 2,805 |
| cp-03 (`.203`) | 2,390,153.91 | 5,682,347.86 | 1,556.2 | 83 | 118 | 6,639,382 |
| worker-01 (`.204`) | 0 | 798.04 | 0 | 0 | 0 | 5,294 |
| worker-02 (`.205`) | 2,555,397.29 | 6,283,519.68 | 1,645.6 | 73 | 94 | 7,118,182 |

Notes: "firing samples" is `count_over_time` on 30s-scraped `ALERTS` samples (sample count while
firing, not distinct episode count — same methodology as the original baseline, so the two are
comparable). The 7d `increase()` values on `cp-03`/`worker-02` (5.68M/6.28M) come in lower than
their raw absolute counters (6.64M/7.12M), consistent with at least one node-exporter/counter
reset inside that 7-day window rather than a query artifact — the absolute counter is the more
reliable long-run reference point precisely because it isn't affected by that. `cp-02` and
`worker-01` remain essentially silent (0 in every 24h/7d window), consistent with every prior
finding this session that only `cp-03`/`worker-02` have shown any activity in the available
retention. **Whenever `ethtool -G` is actually applied, re-run these same 3+2 queries and diff
against this table** — a meaningful win looks like `cp-03`/`worker-02`'s 24h/7d deltas dropping by
an order of magnitude, similar to how the original `netdev_budget` checkpoint was judged.

**Caveat on the baseline above, discovered 2026-09-02:** the 20:33-20:34 UTC snapshot window
landed *inside* one of `cp-03`'s active firing clusters (20:07-21:08 UTC) — it's a real, honest
instant-in-time snapshot, not a query error, but it means "baseline" here is "state at that
moment," not "representative quiet-state." Sound for the delta math below; worth knowing if
eyeballing the absolute numbers alone.

**Trend check, 2026-09-02 ~08:21 UTC (~11h47m after the baseline) — still nothing applied, but
the picture has moved substantially, not stayed flat:**

| Node | Absolute counter now | Δ since 20:33 UTC baseline | Peak burst 24h now (drops/sec) | Firing samples 24h now |
|------|--------------------------:|-------------------------------:|-----------------------------------:|----------------------------:|
| cp-02 (`.202`) | 2,805 | 0 | 0 | 0 |
| cp-03 (`.203`) | 9,769,424 | **+3,130,042** | 5,904.8 (**3.8x** baseline's 1,556.2) | 158 (**~2x** baseline's 83) |
| worker-01 (`.204`) | 5,412 | +118 (noise) | 3.93 | negligible |
| worker-02 (`.205`) | 10,459,042 | **+3,340,860** | 6,257.8 (**3.6x** baseline's 1,645.6) | 152 (**~2x** baseline's 73) |

`cp-03`/`worker-02` each accumulated roughly as many drops in this ~12h window as they had in
their *entire* history up to the baseline. This wasn't one continuing episode either — clustering
the `ALERTS` series (gap >10min = new cluster) found **5 distinct firing clusters on `cp-03`** and
**6 on `worker-02`** between 15:42 and 22:54 UTC on 2026-09-01 (roughly hour-long each, with
quiet gaps between), plus a fresh one on `worker-02` at **04:54-04:55 UTC on 2026-09-02** — about
3.5h before this check. `cp-02`/`worker-01` remained essentially silent throughout, unchanged from
every prior finding. Ring buffer confirmed still untouched (256/4096) during this same window —
see the re-confirmation note above.

This is real data pointing toward *worse*, not toward "stable and waiting for a fix to be
applied" — whether that's meaningful escalation or just this failure mode's natural burstiness
showing a rough night isn't something one overnight window can settle on its own, but it's worth
weighing when deciding how urgently to move on item #1 below.

**Investigated why the overnight window was worse (2026-09-02) — inconclusive, but surfaced a
significant new lead that complicates the "it's Ceph client I/O" framing.** User asked two
things: is a switch/router issue possible, and what actually changed overnight. On the first: no
— structurally ruled out. `node_network_receive_drop_total` counts packets that *arrived* at the
NIC and got dropped by the driver; a switch/upstream drop would never reach the node at all, so
it's invisible to this specific counter by construction. Combined with the zero FIFO/hardware-ring
errors confirmed early in this investigation (rules out signal integrity/bad cable/failing port)
and stable negotiated link state (1000Mb/s full duplex, no flapping, confirmed during the EEE
check) — this is unambiguously a host-side phenomenon, not upstream network infrastructure.

On the second — checked every specific-workload hypothesis for the four overnight firing clusters
(`cp-03`: 16:09-17:05, 20:07-21:08, 21:18-21:19, 21:50-22:54 UTC 2026-09-01; `worker-02`: same
set plus a fresh 04:54-04:55 UTC 2026-09-02 episode) and **all came back negative**:
- Ceph scrub/deep-scrub: `ceph_pg_scrubbing`/`ceph_pg_deep` zero for the entire 13.5h window checked.
- Ceph client op-rate (`ceph_osd_op_r`/`_w`): flat 150-700 ops/s all night, no spike lining up.
- Per-OSD latency on osd.2/4 (`cp-03`)/osd.6/9 (`worker-02`): flat 2-8ms, comparable to unaffected OSDs.
- Bulk throughput: RX bytes/s on `eno1` never exceeded ~2MB/s even at peaks. **Average packet size
  during bursts was 127-585 bytes — well under MTU.** This is a packet-*rate* phenomenon with
  trivial payload, not a bulk transfer — a materially different shape than the confirmed `sabnzbd`
  episode.
- TCP retransmits/connection churn/kube-apiserver request rate: all flat, no storm.
- CNPG Postgres: confirmed on `openebs-hostpath`, not `ceph-block` at all — can't be a Ceph client.
- Envoy Gateway (external + internal) request rate, victoria-logs ingestion, Plex RX bytes: all
  essentially zero/flat during every burst window — no elevated application traffic.
- The 3 cluster-wide CronJobs and VolSync's per-app-staggered hourly syncs: no schedule lines up
  with all four windows (one CronJob partially overlaps only the *last* cluster).

**What turned up instead, unexpectedly:**
1. `cp-03` and `worker-02`'s drop timing tracks nearly sample-for-sample identically all night —
   a shared trigger, not two nodes independently noisy.
2. **The same bursty small-packet pattern exists on `cp-01` too** — the node that has never once
   alerted — at 10-100x higher packet rate (up to 160k pkt/s vs. ~1-7k on the affected nodes),
   continuously, including during stretches where `cp-03`/`worker-02` show nothing. `cp-01`
   absorbs it because its NIC/ring is bigger, not because it doesn't see the traffic.
3. Which nodes see this pattern *at all* lines up exactly with which node currently holds a
   Cilium L2-announcement leader lease for some Service: `cp-01` holds `kube-api`/`envoy-external`,
   `cp-03` holds `envoy-internal`/`victoria-logs-syslog`, `worker-02` holds `plex`. `cp-02` and
   `worker-01` hold **zero** leases and have never shown this pattern in the entire investigation
   — a cleaner, more concrete differentiator than the earlier "burst-timing/hot-PG locality"
   framing, though it explains node *selection*, not the traffic's origin.
4. However — the actual application traffic riding those leased Services (Envoy HTTP requests,
   syslog rows, Plex streaming bytes) was checked directly and was **not** elevated during the
   bursts. So it isn't "more legitimate service traffic through the leader" — something tied to
   holding the lease itself, separate from the service traffic behind it.

**Why this matters beyond just this one overnight window:** the working assumption through most
of this investigation has been that the traffic exhausting the ring is Ceph client I/O riding the
management VLAN (confirmed true for the `sabnzbd` episode specifically). This finding suggests
that assumption doesn't hold for most of what's actually been observed — small-packet,
low-throughput, Cilium-lease-correlated chatter looks like a materially different phenomenon,
plausibly Cilium/datapath-adjacent (a plausible but unconfirmed guess: L2-announcement-related
ARP re-defense traffic). **This is genuinely unresolved** — a strong lead, not a diagnosis. But it
directly affects how much weight the `public_network`-to-storage-VLAN project (item #4 below)
deserves as "the fix": if this traffic isn't Ceph traffic at all, moving Ceph's client I/O to a
different network doesn't touch it.

**Next diagnostic step**: a live packet capture on `cp-01`'s `enp4s0` (or `cilium monitor`/BPF-level
metrics) during a future burst — `cp-01` is the best node to capture on since it shows this
pattern continuously at high amplitude, not just during rare alerting episodes. This supersedes
the earlier `rbd perf image iostat` plan, which was built on the now-uncertain assumption that the
traffic is Ceph-related.

**Follow-up options, ranked by what the evidence now indicates:**
1. **NOT YET BUILT, cleared to proceed — raise the RX ring buffer size** (`ethtool -G eno1 rx
   <N>`) — directly indicated by the `rx_dropped` spike lining up with ring-layer symptoms, and
   confirmed 16x headroom exists (see above). **Not declarative in Talos** — machine config's
   network schema covers interfaces/routes/bonds/VLANs, not `ethtool` ring sizing — so this needs
   an unsupported workaround (a privileged DaemonSet/initContainer running `ethtool -G` at boot,
   since nothing else persists it across reboots) and is mildly disruptive (brief link reset when
   applied).
2. Map `sabnzbd`'s RBD image to its live PG/OSD acting set during a future burst (`ceph osd map
   <pool> <rbd-image>` or `rados -p <pool> osdmap`) to fully confirm the OSD-placement mechanism
   rather than inferring it from co-timed metrics.
3. **DONE (2026-09-01)** — moved `sabnzbd`/`sonarr`/`radarr`/`prowlarr`'s `/config` PVCs off
   `ceph-block` onto the cluster's `nfs` StorageClass (previously provisioned but unused). This
   was a single shared-component change, not a per-app migration: all four apps got `/config`
   from the same `kubernetes/components/volsync` Kustomize component, whose `pvc.yaml` defaulted
   `storageClassName` to `${VOLSYNC_STORAGECLASS:=ceph-block}` — none of the four `ks.yaml` files
   overrode it. `sonarr`/`radarr` also write `/config` on library-import events (which fire right
   as a download completes), so all four needed migrating, not just `sabnzbd`. Shipped as two
   phased commits: phase 1 (`3d2b905`, additive — new `nfs`-backed PVC + one-off copy Job per
   app, old PVC untouched, apps scaled to `replicas: 0` for the copy window) and phase 2
   (`bea944e`, cutover — repoints `persistence.config` at the new PVC, removes `volsync`/the old
   `ceph-block` PVC). No automated backup for this data going forward (small, recreatable state —
   queue DB, history, indexer defs) rather than retargeting VolSync at NFS, since NFS has no CSI
   snapshot support in this cluster and the data's value doesn't justify a `Direct`-copyMethod
   backup path.

   **Verification before/after cutover:** phase 1's copy Jobs all completed with matching file
   counts on all four apps; `sabnzbd` (the one with a disproportionate `du`-reported byte delta —
   1.57% on only 8 files, vs. ≤0.6% on the other three's larger trees) got a full SHA-256
   per-file diff via a throwaway read-only pod — byte-for-byte identical, confirming the `du`
   delta was cross-filesystem directory-inode accounting noise, not lost data. After phase 2,
   all four apps came back up on the new PVC with their existing config genuinely recognized
   (not a fresh-setup state) — `sabnzbd` resumed its postproc queue, `radarr` resumed RSS sync
   with prior indicator state, `prowlarr` immediately queried its actual configured indexers
   (DrunkenSlug/NZBFinder/NZBgeek), `sonarr` recognized `sonarr.db`/`logs.db` on both boot
   attempts. Old `ceph-block` PVCs and `volsync` `ReplicationSource`/`ReplicationDestination`/
   `ExternalSecret` confirmed pruned via the kustomize-controller GC log, not just absence.

   **Watch item, not yet actioned:** `sonarr` restarted once on its first post-cutover boot —
   the liveness/readiness probe (`period=10s, failureThreshold=3`) killed it ~20-30s after
   "Application started" before it finished binding, most likely NFS mount/first-access latency
   being slower than local Ceph RBD was. Both boot attempts show identical, error-free config
   recognition, so this wasn't a data problem, and it self-resolved on the second attempt.
   Deliberately left as-is rather than loosening probe timing off a single occurrence — if this
   recurs on a future restart/reschedule of `sonarr` or any of the other three, that's the signal
   to actually widen `initialDelaySeconds`/`failureThreshold` for these apps' probes.
4. **Structural alternative/complement to #3 — move Ceph's entire `public_network` onto the
   storage VLAN.** See the dedicated [Ceph `public_network`: Move to Storage
   VLAN](#ceph-public_network-move-to-storage-vlan) entry below — this is a distinct, larger
   project the user wants to pursue eventually regardless of whether #3 alone resolves the
   current alert, since it's the structurally-correct end state for the whole cluster, not just
   the `downloads` namespace.
5. Check whether other Ceph-backed PVCs with bursty write patterns show the same signature.
   **Plex's `/config` PVC (20Gi, `ceph-block`, currently on `cp-03` — an affected node) is the
   leading candidate** — same SQLite-on-Ceph shape as the confirmed `sabnzbd` trigger. Did not
   fire during the live episode captured below, but remains the closest structural analog and
   worth checking first at the next occurrence.
6. **Stagger VolSync's hourly backup schedule across its 8 `ceph-block`-backed consumers**
   (`paperless-ngx`, `plex`, `open-webui`, `n8n`, `pgadmin`, `waha`, `firefly-iii`, `forgejo`).
   Confirmed live (2026-09-01) — not just from config — that all 8 apps' `ReplicationSource`
   `lastSyncTime` lands in the same ~30-second window every hour (`13:00:31`–`13:00:59` UTC
   observed), since none of their `ks.yaml` files override the shared
   `kubernetes/components/volsync` component's `VOLSYNC_SCHEDULE:=0 * * * *` default. This is a
   real synchronized-burst risk on its own — cheap to fix (offset each app's `VOLSYNC_SCHEDULE`
   by a few minutes) — independent of whether it has caused a page yet; the live episode below
   did not coincide with a sync window, so this and that episode are two separate findings, not
   one.
7. If none of the above are pursued, revisit widening `CephNodeNetworkPacketDrops`'s `for:` window
   further or adding per-node overrides — but only as a last resort now that a real, addressable
   traffic source is identified, not as the first move.

**Do not** raise `net.core.netdev_budget`/`netdev_budget_usecs` further on `cp-03`/`worker-02` —
confirmed above to not be the constrained resource for this failure mode; more budget can't help a
ring that's already full before softirq gets to drain it.

**Ruled out (2026-09-01) — Ceph role placement and EEE, neither differentiates the affected
nodes.** Checked whether `cp-03`/`worker-02` (affected) have some static Ceph-role or NIC-power
difference from `cp-02`/`worker-01` (unaffected, same NIC/driver, zero episodes in 14 days):
- **Ceph roles**: `ceph osd tree`/`ceph mon dump` live — every e1000e node carries exactly 2 OSDs,
  no count difference. `worker-01` (unaffected) and `worker-02` (affected) both host a mon;
  `cp-02` (unaffected) and `cp-03` (affected) both host neither mon nor mgr. No pattern.
- **Energy Efficient Ethernet (802.3az)**: a plausible hypothesis — EEE's PHY low-power idle and
  LPI wake-latency on burst resumption fits the ring-exhaustion-at-burst-start failure shape, and
  the Intel I219-LM has a known history of EEE-related issues. Checked live via `ethtool
  --show-eee eno1` (through a `kubectl debug node/...` pod, `hostNetwork: true`, no
  nsenter/chroot needed) on all 4 e1000e nodes: byte-for-byte identical everywhere —
  `EEE status: enabled - inactive` (driver has it on, but it never actually negotiates active
  since the switch side doesn't advertise EEE support back, so no LPI wake-latency is actually
  occurring on any of the 4 links). Nothing to disable that would change anything.

Reinforces the standing theory rather than adding a new lever: which specific node(s) page on a
given burst comes down to burst-timing and hot-PG locality (whichever OSDs are primary for the
busy PGs at that moment), not a fixed hardware/firmware/role difference between the 4 e1000e
nodes — they are equally exposed. No BIOS-level fix is currently indicated.

**Live episode caught mid-investigation (2026-09-01, 13:51:46–13:53:01 UTC) — trigger not
identified.** While checking whether OTHER `ceph-block` consumers could reproduce the `sabnzbd`
failure mode, a real episode fired on `cp-03`+`worker-02` simultaneously — `node_network_receive_drop_total{device="eno1"}`
spiked on both nodes at `13:51:15` (244/s `cp-03`, 231/s `worker-02`), the same cross-node
simultaneous-burst signature seen before. Checked and **ruled out** as the cause: Prometheus's own
pod network TX (flat, ~10-13KB/s throughout — directly refutes "Prometheus's own TSDB writes
trigger its own alert"), `victoria-logs` (flat, ~1.8-2.1KB/s), VolSync (last sync completed 50+ min
earlier, nothing active, next not due for an hour), `sabnzbd` (14MB/s of live download traffic at
the time, but on `cp-01` — the unaffected node — and its whole namespace is already off
`ceph-block`), and `plex`/`n8n`/`open-webui` (the 3 of the 8 volsync apps currently scheduled on
the affected nodes — all flat). `ceph -s` showed 36 MiB/s read / 84 op/s at `HEALTH_OK` shortly
after — unmatched to any monitored pod's traffic, and **not conclusively attributed**: plausibly
Ceph-internal (scrub/deep-scrub — OSDs are host-networked, invisible to per-pod cAdvisor metrics)
or an unmonitored client, but unconfirmed.

**Updated historical framing:** across the full available 14-day Prometheus retention
(2026-08-19 → 2026-09-01), only `cp-03`/`worker-02` show *any* `CephNodeNetworkPacketDrops`
activity (pending or firing) — `cp-02`/`worker-01` show zero in this window. This refines, not
contradicts, the 4-week checkpoint above: it's still consistent with "no burst big enough to
expose ring exhaustion has landed on `cp-02`/`worker-01` since the Aug-19 reboot," now with 14
days of clean data behind it rather than 13.

**What this means for prioritizing the projects above:** the migration (#3, done) and VolSync
staggering (#6, not yet done) both remove real, identified traffic sources — but this live episode
fired *after* the migration completed, with no single-app cause identified among everything
checked. That argues the ring-exhaustion failure mode is closer to an intrinsic property of running
Ceph client I/O over this specific NIC/topology than something fully solvable by migrating
individual apps off `ceph-block` one at a time — each migration closes one door, but the ring stays
just as small for whatever's left. Doesn't change the recommended order (do the cheap fixes first),
but is a real data point toward eventually prioritizing item #4 ([Ceph `public_network`: Move to
Storage VLAN](#ceph-public_network-move-to-storage-vlan)) rather than treating it as indefinitely
deferrable — that's a cost/urgency call for the user to make, not one this one inconclusive episode
should force on its own.

**Next safe check, for the next live occurrence:** start `rbd perf image iostat` streaming *before*
the next episode (it's a live TUI, not capturable via one-shot `kubectl exec`) to finally attribute
the unexplained 36 MiB/s read to a specific RBD image/PVC:
```bash
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rbd perf image iostat --pool ceph-blockpool -f json
```

---

### Ceph `public_network`: Move to Storage VLAN

**Caveat added 2026-09-02 — re-examine this project's rationale before treating it as "the"
fix.** The `CephNodeNetworkPacketDrops` investigation this section's status was originally scoped
against found new evidence that most of the observed packet-drop bursts (not the originally
confirmed `sabnzbd` episode, but the broader recurring pattern) may not be Ceph client I/O at all —
small-packet, low-throughput traffic that correlates with Cilium L2-announcement leader-lease
ownership instead, present on `cp-01` too at much higher amplitude with no alert (bigger ring
absorbs it). See the e1000e packet-drops entry above ("Investigated why the overnight window was
worse") for the full finding. **If that holds up, moving Ceph's `public_network` to the storage
VLAN would not fix most of what's actually been observed**, since the traffic wouldn't be Ceph
traffic to begin with — it's still worth doing eventually for the traffic that *is* confirmed
Ceph (the `sabnzbd`-shaped kind), but the case for treating it as the comprehensive fix needs the
Cilium/datapath lead run down first, not assumed.

**Update 2026-09-03 — the caveat above still stands for the *broader* recurring pattern, but a
fresh episode reconfirms genuine Ceph traffic as a real, distinct contributing mechanism, via a
disambiguation method other episodes can now reuse.** A `cp-03`+`worker-02` episode (04:20-04:42
UTC) traced to `rook-ceph-mon-a`/`osd-0`/`osd-3` write activity on `cp-01`. Checked live against
Cilium L2-announcement lease holders: `cp-03` held **zero** leases at the time yet mirrored
`worker-02`'s burst shape in lockstep — ruling out L2-lease chatter as *this* episode's cause (there
was nothing for cp-03 to be chattering about) and pointing to Ceph mon-quorum/OSD heartbeat-front
traffic between `cp-01` and its `public_network` peers instead — a different mechanism than the
`sabnzbd` RBD-client-PVC case (confirmed 2026-09-01), not a re-run of it. Also newly observed: this
failure mode now has a second victim beyond the alert itself — Prometheus's own rule-group
evaluation stalled 216s and missed 34 scheduled iterations because its own Ceph-RBD-backed TSDB PVC
contended for I/O during the same window. Full writeup:
[QA.md](QA.md#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan).
**The user has confirmed (2026-09-03) they want to actively move toward implementing this
project now**, rather than continue treating it as an indefinitely deferrable someday-item — see
"Next steps to unblock a start," below, for what that means concretely.

**Status: executed and verified (2026-09-03, session `ceph-storage-bond-migration-plan`) —
all 5 phases complete except the optional Phase 5 hardening and the 2-week observation window
below.** This cluster deliberately split Ceph traffic across two fabrics at
greenfield (`docs/SESSIONS-ARCHIVE.md:435`): `cluster_network` (OSD↔OSD
replication/heartbeat/backfill) on the storage bond (`10.200.0.0/24`, 2x10G LACP bond, `bond-storage`
— see terminology note below), but `public_network` (client I/O — every CSI/RBD read and write, plus
mon traffic and heartbeat-front) on the **management network** (`10.60.0.0/24`) instead — the same
fabric as `etcd`/`kube-apiserver`/`kubelet`/DNS/Cilium control-plane traffic. That choice is what made
the `CephNodeNetworkPacketDrops` investigation above possible in the first place: Ceph client I/O from
`sabnzbd`'s `/config` PVC was landing on a 1GbE, single-queue, small-ring-buffer NIC shared with
cluster-critical traffic, not on the well-provisioned storage bond most people would assume "Ceph
traffic" means.

**Terminology correction (2026-09-03):** this section previously said "storage VLAN." There is no
currently-active 802.1Q VLAN carrying storage traffic — `10.200.0.0/24` is a dedicated, untagged,
physically-separate LACP 802.3ad bond (`bond-storage`) on discrete SFP+ NICs, not a tagged VLAN over
shared cabling. A tagged VLAN 200 sub-interface only ever existed as a temporary emergency fallback
(2026-06-25→07-07, X520 hardware failure) and is commented out today in `talos/talconfig.yaml`,
unrelated to this migration. Below and in future updates, this project is described as moving
`public_network` onto the storage bond / `10.200.0.0/24`, not "the storage VLAN."

The user has confirmed (2026-09-03: now as an active priority, not just an eventual one) they want
to move `public_network` onto `10.200.0.0/24` too, so **all** Ceph traffic — client and replication
alike — rides the same isolated, multi-queue, jumbo-frame
fabric. This is more than a traffic relocation: the storage bond's NICs are multi-queue with
materially larger default ring depths than the management NICs' `e1000e`/I219-LM, so this plausibly
sidesteps the ring-exhaustion failure mode structurally (for every current and future `ceph-block`
consumer cluster-wide), rather than just moving today's specific trigger off Ceph (which is what the
narrower `sabnzbd`/*arr `/config` migration above accomplishes on its own, separately and sooner).

**Why this remains a large, careful project even with the go-ahead — blast radius, not
willingness, is the constraint:**
- **Blast radius is the whole cluster, not one namespace.** `public_network` is where *every* Ceph
  client talks to mons/OSDs — CNPG Postgres, Grafana, Waha, pgAdmin, Firefly-iii, Forgejo, and
  anything else on `ceph-block` (the default StorageClass) all depend on it. A mistake here risks
  every stateful workload in the cluster, not four low-stakes SQLite DBs.
- **Requires a live mon reconfiguration.** Ceph mons bind to `public_network` addresses at startup;
  changing it on a running cluster means adding mons on the new network and retiring the old ones —
  exactly the mon-failover dance the original greenfield choice was designed to avoid entirely by
  getting the network right before the cluster ever had data.

**Both research prerequisites resolved (2026-09-03, session `ceph-storage-bond-migration-plan`):**
1. **Rook mon-network migration mechanics.** Confirmed via official Rook docs: changing
   `addressRanges.public` does **not** automatically move existing mons — "the existing mons will
   remain running with the same network settings with which they were created... you will need to
   failover the mons." No fully-documented CIDR-only-change procedure exists upstream, but the
   general Rook mon-failover mechanism is well documented: scaling a mon Deployment to 0 causes the
   operator to detect the failure, create and validate a canary mon, then promote it into quorum.
   Since `addressRanges.public` is updated before triggering failover, the replacement mon should be
   scheduled on the new network. Must be done one mon at a time to preserve 2-of-3 quorum throughout.
   OSD/MDS pods separately need a rolling restart afterward — Rook does not apply network changes to
   daemon pods until they restart.
2. **Pod-to-storage-bond reachability — the harder blocker, confirmed NOT to exist today.** Two
   independent gaps: Cilium's BPF datapath (`kubernetes/apps/kube-system/cilium/app/helm/values.yaml`)
   only attaches to the management interface (`devices:` is commented out, auto-detected via the
   default route, which `bond-storage` doesn't have); and `bond-storage` is documented in
   `kubernetes/apps/kube-system/cilium/config/networks.yaml` as an isolated L2 segment with no route
   back to the management subnet — an intentional design choice. Crucially, this is **not avoidable**:
   confirmed Rook v1.19.6 defaults `CSI_ENABLE_HOST_NETWORK` to `false` for greenfield clusters (this
   one, with no override anywhere in this repo), so the `csi-rbdplugin`/`csi-cephfsplugin` node
   plugins run on the **pod network**, not hostNetwork — every workload's RBD/CephFS mount genuinely
   talks to mons/OSDs from a pod IP today. Opening pod→storage-bond reachability via a Cilium
   `devices:` change is therefore mandatory, not optional, and comes with its own MTU question
   (resolved: keep `MTU: 1500` cluster-wide — Cilium's MTU is a single scalar in this chart version,
   not per-device, so jumbo frames on the new path aren't available without risking the proven-safe
   management path too).

**Approved 5-phase migration plan (full detail in session `ceph-storage-bond-migration-plan`,
2026-09-03):**
1. **Cilium: add `bond-storage` as a routed device, prove pod reachability** — before touching any
   Ceph config. Files: `kubernetes/apps/kube-system/cilium/app/helm/values.yaml`,
   `kubernetes/apps/kube-system/cilium/config/networks.yaml`. Validate with a pod-network debug pod
   reaching a live mon IP on `10.200.0.0/24` before proceeding.
2. **`CephCluster.addressRanges.public` → `10.200.0.0/24`, then rolling mon failover** — one mon at a
   time via `kubectl scale deploy/rook-ceph-mon-<x> --replicas=0`, confirming quorum and the new bound
   address after each before touching the next. Imperative/live, not GitOps-declarative — analogous to
   existing OSD-replacement operations in `ops/ceph/mod.just`.
3. **Rolling OSD pod restart** — one node at a time, `noout` + `ok-to-stop` scoped per node, so every
   OSD picks up the new network binding.
4. **Verification** — `ceph -s`/quorum/OSD health, a real `ceph-block` consumer smoke test (not CNPG —
   confirmed it's on `openebs-hostpath`), a minimum 2-week observation window before declaring
   `CephNodeNetworkPacketDrops` fixed (the alert's own history shows episodes days-to-weeks apart), and
   an etcd/kube-apiserver/CoreDNS regression check.
5. **(Optional, deferred) Harden the newly-opened pod→storage-bond reachability** — nothing today
   restricts which pods can reach Ceph's mon/OSD ports on `10.200.0.0/24` once Phase 1 lands (confirmed
   via `talos/patches/global/network-firewall.yaml` — no existing rule covers Ceph's ports). A Talos
   `NetworkRuleConfig` or `CiliumNetworkPolicy` scoped to CSI plugin pods would close this; not required
   for the fix itself, worth doing eventually given single-tenant home-lab risk is modest but nonzero.

Every phase has an explicit rollback and a "safe to stop here" boundary.

**Execution results (2026-09-03, same session):**
- **Phase 1.** Live interface names verified via `talosctl get links` (not guessed): management is
  `enp4s0` on cp-01, `eno1` on cp-02/cp-03/worker-01/worker-02 — the prior comment's claim that cp-03
  used `bond0` was stale/wrong. Used an explicit `devices: eno1 enp4s0 bond-storage` list rather than
  a wildcard, since a glob like `enp+` would also match `bond-storage`'s own slave NICs on some nodes
  (e.g. cp-01's `enp5s0f0np0`/`enp5s0f1np1`) — attaching Cilium directly to bond members, not just the
  master, would have been wrong. Pod-to-storage-bond reachability validated cleanly (0% loss, ~0.08ms
  RTT — same-L2, no routing hop) with zero regression on the management path.
- **Phase 2 — new blocker found and resolved, not anticipated by the two prerequisites above.**
  Changing `addressRanges.public` and failing over `mon.a` (→ `mon.f`, Rook always assigns a fresh
  identity, never reuses the old letter) produced a mon that silently bound to `10.60.0.201`, not
  `10.200.0.201` — `ceph -s` stayed `HEALTH_OK` throughout, no error surfaced. Root cause: Rook's
  `addressRanges` mon address selection reads the **Kubernetes Node object's** registered address, not
  the node's actual interfaces, and this cluster's kubelet is deliberately pinned to
  `10.60.0.0/24`-only (`talos/patches/global/machine-kubelet.yaml`, a real, unrelated, pre-existing
  constraint protecting kube-apiserver↔kubelet control traffic from routing over the storage bond) —
  so the Node object never exposes a `10.200.0.0/24` address for Rook to select. Confirmed via
  [rook/rook#14829](https://github.com/rook/rook/issues/14829) (closed `wontfix`) this is a known Rook
  limitation, not a bug in our config. Fix: the documented `network.rook.io/mon-ip` node annotation,
  applied declaratively to all 5 nodes (not just the 3 with mons at migration time — confirmed
  necessary live, since `mon.e`'s replacement landed on `cp-02` rather than its original node
  `worker-01`) via `talconfig.yaml`'s `nodeAnnotations` (talhelper field, same shape as the existing
  `nodeLabels`). Also confirmed empirically: the annotation is only read when Rook creates/recreates a
  mon's Deployment (a genuine failover), not on a plain pod restart — a simple `kubectl delete pod`
  reuses the stale `--public-addr` baked into the existing pod template. All 3 mons (`mon.g`/`.h`/`.i`)
  ended up correctly bound to their node's `10.200.0.0/24` address.
- **Phase 3.** All 10 OSDs restarted one node at a time (`noout` + `ok-to-stop` scoped per node); no
  annotation workaround needed here — OSD address discovery was already correctly finding the storage
  bond independently of the Node object (their `cluster_network` binding proved this pre-migration).
  Every OSD now shows a single unified `10.200.0.0/24` address for both public and cluster roles.
- **Phase 4.** `ceph -s`: `HEALTH_OK`, 33 pgs `active+clean`, 10/10 OSDs up/in throughout, zero data
  unavailability across the whole migration. Sampled 4 real `ceph-block` consumers (Grafana, Prometheus,
  Waha, victoria-logs) with live write/read tests or API checks — all confirmed healthy on their
  migrated mounts. `pgAdmin` (scaled to 0) confirmed indirectly via a successful volsync backup job.
  etcd/apiserver/CoreDNS: no regression. `CephNodeNetworkPacketDrops`
  (`rook-ceph`'s own shipped `PrometheusRule`, not authored in this repo) needed no changes — its
  expression is already interface-agnostic (`device!="lo"`), so it already covers `bond-storage`
  automatically; it only ever fired on the management NICs because that's where the ring-exhaustion
  problem actually was. **2-week observation window starts 2026-09-03** — watch
  `rate(node_network_receive_drop_total{device="bond-storage"}[5m])` /
  `rate(node_network_transmit_drop_total{device="bond-storage"}[5m])` (baseline at cutover: 0 on 4
  nodes, cumulative counter of 36 on cp-01 likely from bond/LACP negotiation at some point in its
  uptime, not actively growing) and the `CephNodeNetworkPacketDrops` alert itself before declaring this
  fixed.
- **Phase 5** remains optional/deferred, not done.

Known unknowns from planning that got resolved empirically during execution: the Cilium `devices:` glob
(resolved — explicit list, not a wildcard, see Phase 1 above); whether a stuck/failed mon canary stalls
Rook cluster-wide (didn't hit this — every failover completed cleanly, just slower than expected: Rook's
mon health-check waits a full ~10-minute timeout before creating a canary, confirmed via operator logs,
not a stall); exact pod labels (`app=rook-ceph-mon,mon=<id>` / `app=rook-ceph-osd,ceph-osd-id=<id>`
confirmed live via `--show-labels`, matched the plan's assumption).

**Pre-work done (2026-09-01) — mixed result, doesn't fully resolve the urgency question.**
CNPG Postgres was the originally suggested candidate but is **not applicable**: its actual storage
(`kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml`) is `openebs-hostpath`, local
disk, not `ceph-block` at all — no Ceph client I/O to investigate. Broadened the check to the
cluster's real `ceph-block` consumers (`victoria-logs`, `kube-prometheus-stack`'s Prometheus,
and the 8 apps on the shared `volsync` component) and, during that check, a live episode fired
(`cp-03`+`worker-02`, 2026-09-01 13:51:46-13:53:01 UTC — full detail in the e1000e packet-drops
entry above). Prometheus and `victoria-logs` were both directly ruled out for that episode (flat
traffic throughout); the actual cause was **not identified** among anything monitored, with an
unattributed 36 MiB/s Ceph-internal read (`ceph -s`, possibly scrub) as the leading unconfirmed
hypothesis.

**Net effect on urgency:** this is real evidence the ring-exhaustion failure mode isn't fully
solved by migrating individual apps off `ceph-block` — a fresh, unattributed episode fired *after*
the `/config` migration completed. That leans toward elevating this project's priority rather than
treating it as indefinitely deferrable, but it's not conclusive proof either (the episode's actual
trigger is still unknown, so it's not confirmed to be "another app doing what `sabnzbd` did" — it
could equally be Ceph-internal activity that `public_network`-to-storage-VLAN would also fix, since
that migration moves scrub/heartbeat-front traffic off the management VLAN too, not just
CSI/RBD client I/O).

**2026-09-03 — the user has now made the scheduling call explicitly: actively move toward this
project.** The 2026-09-03 episode (see "Update 2026-09-03" above) adds a second, mechanistically
distinct confirmed-Ceph data point (mon-quorum/OSD heartbeat-front, disambiguated from the
Cilium/L2 theory via live lease-holder checking) alongside the earlier `sabnzbd` RBD-client-PVC
case, plus a new collateral symptom (Prometheus's own rule evaluation stalling on its own
Ceph-backed PVC). That's enough for the user to decide this is worth actively pursuing now rather
than waiting for more evidence — see "Next steps to unblock a start" above for the two concrete
research items this unlocks next; nothing has been implemented against the live cluster yet.

---

### Prometheus Metric Hygiene: Drop Static and Low-Value Series

Some scraped metrics carry no useful information because their value never changes — hardware sensors stuck at a constant (e.g. a floating thermistor input), counters that never increment on this cluster, or labels that exist only on hardware this cluster doesn't have. These series consume TSDB storage and cardinality budget without benefit.

**How to identify candidates:**

Run this query in Prometheus to find series whose value did not change at all over the past 24 hours:

```promql
count by (__name__, instance) (
  changes(scrape_series_added[24h]) == 0
)
```

Or target specific metric families directly:

```promql
# hwmon sensors with a constant reading over 6 hours (likely stuck/phantom)
count by (chip, sensor, instance) (
  changes(node_hwmon_temp_celsius[6h]) == 0
)
```

For cardinality analysis, the Grafana **Prometheus** data source has a built-in **Cardinality Explorer** (Explore → Metrics → `prometheus_tsdb_head_series_not_created_total` or use the cardinality management page at `/-/tsdb-status`).

**Already addressed:**
- `nct6686.*;temp5` — M920Q floating thermistor input (~128°C constant); dropped via `metricRelabelings` on the node-exporter ServiceMonitor

**Candidates to evaluate:**
- Other `nct6686` high-numbered sensors (temp6+) if they appear on cp-02 with constant readings
- `node_hwmon_*` label combinations for sensors not present in the cluster hardware (e.g. `chip=~"acpitz.*"` if those are always 0 or identical to coretemp)
- Any `node_cpu_*` per-mode breakdowns for modes that are always zero on these nodes (e.g. `steal`, `guest` on bare-metal)

**How to drop a series:**

Add a `metricRelabelings` entry to the relevant ServiceMonitor in `helm/values.yaml`:

```yaml
prometheus-node-exporter:
  prometheus:
    monitor:
      metricRelabelings:
        - sourceLabels: [chip, sensor]
          regex: "nct6686.*;temp[6789]"
          action: drop
```

**Dependencies:** Grafana ✅ (Cardinality Explorer), kube-prometheus-stack ✅

---

### Scheduling Topology: Follow-up Fixes

Two gaps identified during the 2026-05-21 cluster audit that were not fully resolved by the `topology-spread` session.

#### kustomize-controller: both replicas co-located on talos-cp-02

Both `kustomize-controller` replicas currently run on `talos-cp-02`. The Flux spread uses `ScheduleAnyway` (soft) because 4 controllers × 2 replicas = 8 pods across 3 nodes forces an uneven 3/3/2 split — hard `DoNotSchedule` would permanently block the 8th pod. With a soft constraint the scheduler may still co-locate two replicas of the same controller when it scores that placement higher.

**Impact:** If `talos-cp-02` goes down, Flux loses both `kustomize-controller` replicas simultaneously. Leader election re-runs on surviving nodes within ~35 s, but `Kustomization` reconciliation pauses until a new leader is elected.

**Options to investigate:**
- Add `podAntiAffinity` (preferred, not required) scoped to `app.kubernetes.io/name: kustomize-controller` to discourage co-location of the same controller without blocking scheduling
- Use `matchLabelKeys: [pod-template-hash]` on the spread constraint so rolling restarts don't fight the constraint
- Accept as-is: `ScheduleAnyway` was chosen intentionally; the ~35 s failover window is acceptable for a homelab

#### envoy-gateway: single-replica control plane

The `envoy-gateway` pod (the Gateway API controller) is single-replica on `talos-cp-03`. The three Envoy proxy pods (`envoy-external`, `envoy-internal`) are correctly spread 1-per-node and are unaffected. If `talos-cp-03` goes down:
- Live traffic continues — proxy pods on cp-01 and cp-02 keep serving from their last received xDS snapshot
- **No new `HTTPRoute`, `Gateway`, or TLS changes take effect** until the control plane pod reschedules (~30–60 s)

**Options:**
- Set `deployment.replicas: 2` (or equivalent) in the envoy-gateway HelmRelease values and add a `podAntiAffinity` or `topologySpreadConstraint` to spread across nodes
- Accept as-is: brief control-plane unavailability on cp-03 loss does not drop live traffic; homelab risk tolerance is high

**Dependencies:** None — both fixes are independently implementable.

---

### Kubernetes Descheduler

Investigate deploying the [Kubernetes Descheduler](https://github.com/kubernetes-sigs/descheduler) to actively evict pods that violate spread constraints — a gap the scheduler alone cannot close.

**Why this matters:**
The Kubernetes scheduler enforces topology spread constraints and anti-affinity rules only at pod *creation* time. Once a pod is running, it is never moved — even if the constraint is later violated (e.g. after a node recovers, a rolling upgrade shifts replicas, or a pod is manually rescheduled). The Descheduler runs periodically, identifies violations, and evicts the offending pods so the scheduler can rebalance them.

This cluster has at least two known scheduling imbalances that the Descheduler could self-heal:
- Both `kustomize-controller` replicas co-located on `talos-cp-02` (see Scheduling Topology follow-up above)
- ESO pods post-upgrade landing on cp-02 and cp-03 only, leaving cp-01 light

**Key strategies to evaluate:**
- `RemovePodsViolatingTopologySpreadConstraint` — evicts pods that violate `topologySpreadConstraints`; the primary target for this cluster
- `RemovePodsViolatingInterPodAntiAffinity` — evicts pods that violate anti-affinity rules after the fact
- `LowNodeUtilization` — optional; redistributes pods from underutilised nodes; evaluate whether the cp-03 bias warrants this

**Deployment notes:**
- Helm chart via `kubernetes-sigs/descheduler` OCIRepository (`ghcr.io/kubernetes-sigs/charts/descheduler`)
- Deploy in `kube-system` (standard placement for scheduling infrastructure)
- Run as a `CronJob` on a short interval (e.g. every 5 min) rather than as a continuous `Deployment` — lower blast radius, easier to reason about eviction bursts
- The `RemovePodsViolatingTopologySpreadConstraint` strategy should be scoped to namespaces with `DoNotSchedule` constraints to avoid evicting workloads with soft (`ScheduleAnyway`) constraints unexpectedly

**Dependencies:** None — independently implementable. Existing topology spread constraints are already in place; the Descheduler is purely additive.

---

### Talos Config, Image Extensions & Patch Audit

Review the current Talos configuration end-to-end to identify missing extensions, suboptimal patches, and any node-specific tuning gaps. The schematic currently ships `intel-ucode` and `amd-ucode` with several extensions commented out; patches exist for kubelet, network, sysctls, NFS defaults, and machine features — but these were written incrementally and have not been audited holistically.

Areas to investigate:

**Image extensions (`talos/schematic.yaml`)**
- `siderolabs/iscsi-tools` — required if Rook/Ceph or TrueNAS iSCSI is added (storage roadmap item)
- `siderolabs/util-linux-tools` — provides `lsblk`, `blkid`, etc.; useful for storage debugging
- `siderolabs/drbd` — needed if DRBD-backed HA storage is considered
- `siderolabs/nfs-utils` (or confirm kernel NFS client suffices for NFS mounts)
- `siderolabs/i915-ucode` / `siderolabs/amd-gpu-firmware` — relevant if any node is repurposed to run GPU workloads
- `siderolabs/stargz-snapshotter` — lazy image pulling; worth evaluating for large workloads
- Check [factory.talos.dev](https://factory.talos.dev) for any new official extensions added since cluster was built

**Global patches (`talos/patches/global/`)**
- `machine-sysctls.yaml` — verify values are tuned for 10 GbE bonds (e.g. `net.core.rmem_max`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`)
- `machine-kubelet.yaml` — check `maxPods`, `evictionHard`, `kubeReserved` / `systemReserved` are appropriate for the hardware
- `machine-network.yaml` — confirm bond MTU TODO is addressed (jumbo frames / 9000 MTU for storage VLAN)
- `machine-network.yaml` — **[low/cosmetic]** bond member alias selectors on all three nodes use `glob(driver)` (e.g. `glob("ixgbe", link.driver)`) which matches both ports on the same NIC; Talos skips the alias silently. Tighten to `hardwareAddr` or exact interface `name` so per-member aliases actually resolve if ever needed.
- `machine-files.yaml` — audit NFS mount defaults; verify `nfsvers=4.2` and `nconnect=16` are still best practice
- `machine-time.yaml` — confirm NTP servers and stratum are appropriate for home lab

**Controller-plane patches (`talos/patches/controller/`)**
- `admission-controller-patch.yaml` — review enabled admission plugins against current Kubernetes best practices
- `cluster.yaml` — re-check etcd subnet advertising, Talos API + kubelet subnet restrictions
- `machine-features.yaml` (controller) — confirm KubePrism, `hostDNS`, and any other beta features are intentional

**Per-node considerations**
- cp-03 (MS-A2, 32c/92GB) may benefit from NUMA-aware kubelet configuration
- Confirm `installDisk` is consistent with actual disk layout (nvme0n1 vs nvme1n1) post-wipe

**Talos v1.14 — native LVM wipe commands (upgrade motivation):**
Talos v1.14.0 (in alpha as of 2026-06) adds `talosctl wipe lv <name>`, `talosctl wipe vg <name>`, and `talosctl wipe pv <name>` plus `LVMPhysicalVolumeStatus` / `LVMVolumeGroupStatus` / `LVMLogicalVolumeStatus` resources. These go through the controller's own deactivation path rather than fighting the `block.LVMActivationController` lock.

**Impact on `live-osd-cleanup`:** once v1.14 is stable, the `task talos:wipe-ceph-osds-live` step in `ops/bootstrap/mod.just` can be simplified from deploying privileged wipe pods (which fight the LVMActivationController and may require a node reboot) to a direct `talosctl wipe vg <ceph-vg-name>` call. Update `ops/bootstrap/mod.just` and `.taskfiles/talos/Taskfile.yaml` at that point.

Until then, the workaround (dd to zero the LVM PV header + node reboot) is documented in [QA.md → Why does task talos:wipe-ceph-osds-live fail after a cluster reset?](QA.md#why-does-task-taloswipe-ceph-osds-live-fail-after-a-cluster-reset).

Deliverable: a PR updating `schematic.yaml` and the relevant patch files with reasoned changes; update `talenv.yaml` if the schematic ID changes (re-register at factory.talos.dev).

---

### Migrate Remaining HelmRepositories to `home-operations/charts-mirror`

> **Status: partially done (2026-07-08).** `metrics-server` migrated — mirror had a matching `3.13.1`
> tag. `cilium` is **blocked**: the mirror's newest published tag is `1.18.6`, while this cluster runs
> `1.19.5` live (confirmed via `ghcr.io/v2/.../cilium/tags/list`, no pagination trick — that's genuinely
> the full tag list). Migrating now would pin Flux's source below the running CNI version — on a
> bare-metal cluster with no separate CNI fallback, that's a real downgrade risk, not a cosmetic
> source-kind change. Re-check `charts-mirror`'s tag list next time cilium is bumped; migrate once a
> tag ≥ the then-current version exists.

Two of our Flux chart sources still use the traditional `HelmRepository` kind (HTTP `index.yaml` polling). Every other chart source in the cluster has already been converted to `OCIRepository`. Migrating the two remaining outliers makes the source strategy uniform and unlocks cosign verification.

**Background — what the mirror is:**

`ghcr.io/home-operations/charts-mirror` is a community-maintained GitHub Actions pipeline ([home-operations/charts-mirror](https://github.com/home-operations/charts-mirror)) that:
- Re-publishes upstream Helm charts as OCI artifacts under a consistent `ghcr.io` namespace
- Signs every artifact with **cosign** (same key as the rest of the `home-operations` project)
- Tags charts with the same semver as upstream — `1.21.1`, `4.4.0`, etc. — so Renovate can track them with `datasource=docker` instead of `datasource=helm`

**Why OCI > HTTP `HelmRepository`:**

| Dimension | HTTP `HelmRepository` | OCI `OCIRepository` (mirror) |
|-----------|----------------------|-------------------------------|
| Flux polling | Downloads the full `index.yaml` on every interval | Fetches only the tagged digest — no index |
| Renovate datasource | `datasource=helm` (fetches index, brittle) | `datasource=docker` (registry API, reliable) |
| Supply-chain | No verification | `verify.provider: cosign` available |
| Upstream availability | Chart unavailable if upstream repo is down | Mirror caches last-pushed artifact |
| Source kind uniformity | Breaks the all-OCI convention | All sources become `OCIRepository` |

**Current state:**

| Chart | Current source | Current kind | Mirror equivalent |
|-------|---------------|--------------|-------------------|
| `cilium` | `https://helm.cilium.io` | `HelmRepository` | `oci://ghcr.io/home-operations/charts-mirror/cilium` — **blocked, mirror lags at `1.18.6` vs our live `1.19.5`** |
| `metrics-server` | ✅ migrated 2026-07-08 | `OCIRepository` | `oci://ghcr.io/home-operations/charts-mirror/metrics-server` |

Already on the mirror (no action needed): `external-dns`, `openebs`, `metrics-server`.
Already on their own OCI registries (fine as-is): `cert-manager` (quay.io/jetstack), `kube-prometheus-stack` (ghcr.io/prometheus-community), `coredns` (ghcr.io/coredns), `spegel` (ghcr.io/spegel-org), `envoy-gateway` (mirror.gcr.io/envoyproxy).

**Steps taken for `metrics-server` (same steps apply to `cilium` once its mirror tag catches up):**

1. Replaced `kubernetes/flux/meta/repos/helm/metrics-server.yaml` with an `OCIRepository` at
   `kubernetes/flux/meta/repos/oci/metrics-server.yaml`:
   ```yaml
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: OCIRepository
   metadata:
     name: metrics-server
     namespace: flux-system
   spec:
     interval: 1h
     layerSelector:
       mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
       operation: copy
     ref:
       # renovate: datasource=docker depName=ghcr.io/home-operations/charts-mirror/metrics-server
       tag: "3.13.1"
     url: oci://ghcr.io/home-operations/charts-mirror/metrics-server
     verify:
       provider: cosign
       matchOIDCIdentity:
         - issuer: https://token.actions.githubusercontent.com
           subject: ^https://github.com/home-operations/
   ```
2. **Important — this repo's OCI-sourced HelmReleases use `spec.chartRef`, not `spec.chart.spec.sourceRef`.**
   The original plan here assumed the same `chart.spec.sourceRef.kind: OCIRepository` shape used for
   `HelmRepository` sources, but every existing OCI-sourced `HelmRelease` in this cluster (e.g.
   `tailscale-operator`, `tuppr`, `silence-operator`) uses the top-level `chartRef` field instead — and
   the version pin lives entirely on the `OCIRepository`'s `ref.tag`, not on the `HelmRelease`:
   ```yaml
   spec:
     chartRef:
       kind: OCIRepository
       name: metrics-server
       namespace: flux-system
     interval: 1h
     valuesFrom: [...]
   ```
3. Updated `kustomization.yaml` in `flux/meta/repos/helm/` to drop the old file; added the new file to
   `flux/meta/repos/oci/kustomization.yaml`.
4. Validated with `kustomize build` against both repo dirs and the app's own kustomization — all built
   cleanly before committing.

**cilium — why it's genuinely blocked, not just deferred:** confirmed live that the `cilium` Flux
`HelmRelease` (`kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`) is real and active — not a
Helmfile-bootstrap leftover — via `kubectl get helmrelease cilium -n kube-system` showing
`Ready: True, "Helm upgrade succeeded ... chart cilium@1.19.5"` against live `cilium` pods. So this
source is genuinely in use and migrating it is a live-CNI version change, not a no-op source swap.
Queried `ghcr.io/v2/home-operations/charts-mirror/cilium/tags/list` directly (with an anonymous pull
token) and confirmed the full, unpaginated tag list stops at `1.18.6` — no `1.19.x` published yet.

**Dependencies:** None — each migration is independently deployable. Low risk for `metrics-server`
(done). `cilium` specifically carries live-CNI-downgrade risk until the mirror catches up — do not
migrate by copying the version-mismatch pattern above; re-verify the mirror's tag list first.

---

### Tailscale kubectl Authentication (RBAC)

Extend the deployed Tailscale operator so that Tailscale identity doubles as a `kubectl` credential. With this in place, running `tailscale configure kubeconfig home-lab` on any tailnet device writes a kubeconfig that authenticates via Tailscale — no kubeconfig file distribution, no service account tokens to rotate.

**How it works:**
The Tailscale Kubernetes operator exposes an OIDC-compatible identity endpoint. A `ClusterRoleBinding` maps the Tailscale user identity to a Kubernetes RBAC role. `kubectl` then authenticates transparently using the active Tailscale session.

**Deployment notes:**
- Add `rbac.yaml` to `kubernetes/apps/network/tailscale-operator/app/`:
  ```yaml
  apiVersion: rbac.authorization.k8s.io/v1
  kind: ClusterRoleBinding
  metadata:
    name: tailscale-user
  roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: ClusterRole
    name: cluster-admin
  subjects:
    - apiGroup: rbac.authorization.k8s.io
      kind: User
      name: "${TAILSCALE_USER}"   # Tailscale login email or identity
  ```
- Wire `TAILSCALE_USER` via `cluster-secrets` SOPS or a dedicated ExternalSecret (the bykaj reference used `substituteFrom` on the Kustomization)
- Reference: `bykaj/home-ops` `kubernetes/apps/network/tailscale-operator/app/rbac.yaml`

**On any tailnet device after deployment:**
```sh
tailscale configure kubeconfig home-lab
kubectl get nodes   # authenticated via Tailscale identity
```

**Dependencies:** `tailscale-operator` ✅ (deployed in this session)

---

### Cilium BGP Control Plane (replace L2 Announcement)

#### Incident background — how this was found

During the rook-ceph phase-2 rollout (`rook-ceph-bgp-investigation` session), neither
`https://grafana.${DOMAIN_CLUSTER}` nor the freshly-deployed `https://ceph.${DOMAIN_CLUSTER}` dashboard
were reachable from a real browser on the LAN, despite every layer looking healthy in-cluster: Gateway
`Programmed`, `HTTPRoute` `Accepted`/`ResolvedRefs`, TLS cert `Ready`, DNS resolving to the correct VIP,
and a direct in-cluster curl to the Service returning `200`.

**Root cause (confirmed, not guessed):** both affected `LoadBalancer` Services —
`kube-system/kube-api` (`10.60.0.230`) and `network/envoy-internal` (`10.60.0.231`) — had
`externalTrafficPolicy: Local`. `Local` policy means a node will *only* forward traffic to a backend pod
running on itself, never redirect to a pod on another node (this is what lets it preserve the real client
IP without SNAT in a traditional kube-proxy setup). Cilium's `CiliumL2AnnouncementPolicy` leader election
has **no awareness of which nodes actually run a backend pod for a given service** — it elects *any*
node matching `nodeSelector` as the ARP-announcing leader. At the time of the incident:

| Service | Backend nodes | L2-announcement leader | Leader has a local backend? |
|---|---|---|---|
| `kube-api` | cp-01, cp-02, cp-03 (the 3 actual control-plane nodes) | `talos-worker-02` | **No** |
| `envoy-internal` | cp-02, worker-01, worker-02 (3 of 5 envoy replicas) | `talos-cp-03` | **No** |

Both elected leaders had zero local backend for their respective service. Traffic arriving there had
nowhere to go and was silently dropped — while ARP and ICMP to the node still looked completely normal
(pinging the VIP correctly returns "Destination Host Unreachable" *from the announcing node's real IP*,
which is itself expected/healthy behaviour for an L2-announced VIP — ICMP isn't part of what Cilium's
eBPF LB hook redirects). This is exactly why the cluster looked fully healthy from every angle except the
one that mattered.

This is a **documented, known Cilium limitation**, not a misconfiguration unique to us — see
[Cilium L2 Announcements docs](https://docs.cilium.io/en/stable/network/l2-announcements/)
("incompatible with `externalTrafficPolicy: Local`... fix: set the policy to `Cluster`") and
[cilium/cilium#27800](https://github.com/cilium/cilium/issues/27800). A cross-check against
`tmp/home-ops-bykaj` showed the **identical** `Local` + `loadBalancer.mode: dsr` + L2-announcement pattern
— it doesn't break for them only because their `CLAUDE.md` states *"3-node control plane: All nodes are
control plane"*, so for their `kube-api` service every L2-eligible node is trivially also a backend node.
Our heterogeneous topology (3 CP + 2 pure workers) is exactly what exposes the gap their topology happens
to hide.

#### ✅ Immediate fix applied (commit pending)

Changed `externalTrafficPolicy: Local` → `Cluster` on both affected resources:

- `kubernetes/apps/kube-system/cilium/config/service.yaml` (`kube-api`)
- `kubernetes/apps/network/envoy-gateway/config/envoy.yaml` (`envoyService`, shared by `envoy-internal` +
  `envoy-external`)

This loses nothing here specifically: `loadBalancer.mode: dsr` (already set in `kube-system/cilium`'s
Helm values) preserves the real client source IP regardless of traffic policy — DSR's whole purpose is to
let the backend reply directly to the client using the VIP as source, bypassing the entry node. `Cluster`
policy only changes *which backends are eligible* (any node, not just the locally-receiving one); it
doesn't reintroduce SNAT the way it would under classic kube-proxy/iptables.

This is sufficient to fix the immediate bug. The remaining motivation below is about a **structurally
better mechanism**, not a follow-up bug fix.

#### Why go further than the `Cluster`-policy fix

L2 announcement still has two properties worth removing even with the policy bug fixed:

1. **Single point of announcement.** Exactly one node ARP-claims each VIP at a time (a Kubernetes
   `Lease`, "first come, first served"). If that node goes down, there's a re-election gap before another
   node claims the IP — and the chosen "leader" is still just whichever node won the lease race, with no
   load-spreading across multiple healthy nodes simultaneously.
2. **Confusing failure mode.** As this incident showed, when something *is* wrong, the symptoms look like
   a generic network outage (ARP/ICMP fine, TCP silently dropped) rather than pointing at the actual
   cause. A protocol that's aware of its own routing state surfaces failures more legibly.

Cilium's BGP Control Plane solves both: it's correctly endpoint-aware (a node automatically **withdraws**
its route the moment it has no local ready endpoint — no leader election, no blind spots), and multiple
nodes can advertise the same VIP **simultaneously**, with the router doing real load-balancing
(ECMP) across all of them.

#### Recurrence — Plex's dedicated LoadBalancer (2026-08-24)

Hit again, independently, while giving Plex its own LoadBalancer IP (`plex-deploy` session) — same
mechanism exactly: the L2-announcement leader for `media/plex` (`talos-worker-02`) didn't match the node
actually running the pod (`talos-cp-02`), so every external client got "connection refused" while
in-cluster access worked fine. Same immediate fix applied (`externalTrafficPolicy: Local` → omitted,
defaulting to `Cluster`). Full diagnosis in
[docs/QA.md → "A new LoadBalancer Service gets 'connection refused'..."](QA.md#a-new-loadbalancer-service-gets-connection-refused-from-some-clients-but-works-fine-from-inside-the-cluster--why).

Also checked whether Cilium has fixed this upstream since the original incident: **no** — the tracking
issue ([cilium/cilium#27800](https://github.com/cilium/cilium/issues/27800)) is still open, though a fix
is in progress ([cilium/cilium#46399](https://github.com/cilium/cilium/pull/46399), unmerged as of
2026-08-24). Worth checking again whenever `intel-device-plugins`/Cilium version bumps land via Renovate,
but not something to wait on — this cluster's own BGP migration (below) fixes the root cause directly
regardless of upstream's timeline, and doesn't depend on it landing at all.

**Decision:** considered pinning Plex's pod and a dedicated `CiliumL2AnnouncementPolicy` to the same
single node as a stopgap (deterministic, no leader-election ambiguity with only one candidate) — rejected
for now. It would trade away Plex's ability to reschedule across any of the 4 GPU-capable nodes for a
benefit that turned out to be unnecessary: real-client-IP preservation isn't what fixed Plex's "Local
connection" labeling (see the QA.md entry above) — that's driven by the advertised connection address's
own recognizability, which `Cluster` policy doesn't affect. Two independent hits of the same Cilium
limitation, on two different Services, in two different sessions, is a stronger argument for finishing
the BGP migration than for special-casing individual Services with node-pinning workarounds.

#### eBGP primer — for readers new to BGP

This section exists because BGP is unfamiliar territory going in. The goal is to have enough vocabulary
to read the CRDs below and reason about what they do, not to become a BGP expert.

**What BGP actually is.** BGP (Border Gateway Protocol) is the routing protocol that holds the entire
public internet together — it's how every Autonomous System (every ISP, cloud provider, large company)
tells its neighbours "I know how to reach these IP ranges." It is a **path-vector** protocol: routers
don't share a full network map, they just tell each neighbour "send traffic for prefix X to me," and
that announcement propagates outward. Crucially for us, the same protocol scales down perfectly fine to
"one router and five Kubernetes nodes on a home LAN" — it's just a much smaller AS-to-AS relationship.

**AS numbers (ASN).** Every BGP speaker belongs to an Autonomous System, identified by a number. Public
ASNs are globally registered (e.g. Cloudflare is AS13335); for anything internal/private — which is
exactly our case — there are reserved private ranges that will never collide with anything on the real
internet: the 16-bit range `64512–65534`, or the much larger 32-bit private range
`4200000000–4294967294`. We'll use small 16-bit numbers since the UniFi BGP UI is built around that range
(real-world UDM Pro Max BGP setups commonly use `65000`/`65001`-style numbers).

**eBGP vs iBGP.** This is the one distinction that actually matters for understanding our setup:
- **iBGP** (interior): peers share the *same* ASN — typically routers inside one organization's network.
- **eBGP** (exterior): peers have *different* ASNs — typically routers belonging to different
  organizations, peering at a boundary.

In our design, the UDM Pro Max gets its own ASN (e.g. `65000`) and all five Talos nodes share a different
ASN (e.g. `65001`). Since the UDM's ASN differs from the nodes' ASN, **every node-to-UDM session is
eBGP** — even though it's all inside one home network, BGP doesn't care about physical topology, only
about the AS relationship you define. (The nodes never peer with *each other* in this design — only with
the UDM — so there's no iBGP mesh to worry about at all.)

**Peering / neighbor sessions.** Two BGP speakers establish a **session** over plain TCP on port 179.
Each side is configured with the other's IP and expected ASN ahead of time (BGP doesn't auto-discover
peers the way, say, mDNS does — you tell each side explicitly who its neighbour is). Once the TCP
connection is up, the speakers exchange `OPEN` messages to confirm the ASN/capabilities match, then start
exchanging routes. `keepalive`/`hold` timers detect a dead peer (default hold time is 90s in most
implementations; Cilium's example config above shows a much faster `holdTimeSeconds: 9` /
`keepAliveTimeSeconds: 3`, more appropriate for fast failover on a LAN).

**Route advertisement.** Once peered, a speaker can announce "I can reach prefix `10.60.0.231/32`" to its
neighbour. The neighbour adds that to its routing table with the announcing speaker as the next hop. This
is the BGP equivalent of what Cilium's L2 announcement does with ARP — except it's an explicit routing
table entry, not a "whoever answers the ARP request wins" race, and it can span more than one physical L2
segment (not relevant for our flat home LAN, but it's *why* BGP doesn't have the L2-adjacency fragility
that came up earlier in this same investigation around DSR + routed clients).

**ECMP (Equal-Cost Multi-Path).** If the UDM learns the *same* prefix (`10.60.0.231/32`) from **multiple**
neighbours at once — because multiple Talos nodes are all simultaneously advertising it — it installs
multiple equal-cost routes and load-balances traffic across all of them (typically by hashing the
flow/5-tuple, so a given TCP connection consistently takes one path). This is the mechanism that gives
true redundancy: lose any one node, the UDM simply stops seeing a route via that neighbour and shifts
traffic to the survivors — no election, no lease, no gap.

#### How Cilium implements this

There is no separate BGP daemon to run. **Each node's existing Cilium agent embeds a [GoBGP](https://github.com/osrg/gobgp)
instance** that activates once BGP Control Plane is enabled and a config matches that node. Three CRDs
(Cilium v2 API — use this for all new config, not the deprecated v2alpha1 `CiliumBGPPeeringPolicy`):

- **`CiliumBGPClusterConfig`** — the "who peers with whom" config: which nodes run a BGP instance
  (`nodeSelector`), their local ASN, and the list of peers (remote address + remote ASN) each one
  connects to.
- **`CiliumBGPPeerConfig`** — referenced by a peer entry above; holds session-level tuning (timers,
  graceful restart, authentication) and — critically — a label selector (`families[].advertisements.matchLabels`)
  that decides *which* `CiliumBGPAdvertisement` resources actually get sent over that peering relationship.
- **`CiliumBGPAdvertisement`** — the "what to advertise" config: `Service` (LoadBalancer/ClusterIP/
  ExternalIP), `PodCIDR`, or `Interface` advertisement types, each with an optional `selector` to scope
  which Services qualify (mirrors what `loadBalancerIPs: true` does unconditionally in the current
  `CiliumL2AnnouncementPolicy`).

#### Concrete plan for this cluster

**UniFi side** — `Settings → Routing → BGP` on the UDM Pro Max (requires UniFi OS ≥ 4.1.13, confirmed
present on UDM Pro Max/Pro/SE/UXG-Enterprise):

| Field | Value |
|---|---|
| Local AS | `65000` |
| Router ID | `10.60.0.1` (UDM's own LAN IP) |
| Neighbors | all 5 node IPs: `10.60.0.201`–`.205` |
| Remote AS (each neighbor) | `65001` |
| Address family | IPv4 unicast |
| Max-paths | ≥5 (enables ECMP across all nodes, not just 2) |

Also required: a LAN firewall rule permitting TCP/179 between the UDM and the management subnet — easy
to miss, and called out by the one real-world UDM+BGP writeup found during research
([archy.net](https://www.archy.net/from-keepalived-to-haproxy-clustering-a-practical-guide/)).

**Cilium side** — enable the feature (`bgpControlPlane.enabled: true` in
`kubernetes/apps/kube-system/cilium/app/helm/values.yaml`; verify the exact flag against the installed
chart version's `values.schema.json` at implementation time), then add a new config directory
`kubernetes/apps/kube-system/cilium/config/bgp.yaml`:

```yaml
---
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: bgp-cluster
spec:
  nodeSelector:
    matchLabels:
      kubernetes.io/os: linux   # all 5 nodes — full ECMP coverage, unlike the L2 policy's leader-only model
  bgpInstances:
    - name: "instance-65001"
      localASN: 65001
      peers:
        - name: "udm-pro-max"
          peerASN: 65000
          peerAddress: 10.60.0.1
          peerConfigRef:
            name: "udm-peer"
---
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: udm-peer
spec:
  timers:
    holdTimeSeconds: 9
    keepAliveTimeSeconds: 3
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: "bgp"
---
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: lb-advertisements
  labels:
    advertise: bgp
spec:
  advertisements:
    - advertisementType: "Service"
      service:
        addresses:
          - LoadBalancerIP
      selector:
        matchLabels: {}   # advertise every LoadBalancer Service, matching today's loadBalancerIPs: true behaviour
```

(Field names verified against the [Cilium BGP Control Plane Resources docs](https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-configuration/)
at the time this was written — re-check against the installed Cilium version's CRD schema before applying,
since the BGP Control Plane is a comparatively young Cilium feature and field names have shifted between
minor versions.)

**What this replaces:** once BGP is confirmed working (all 5 nodes peered, `kube-api` and
`envoy-internal`/`envoy-external` VIPs reachable via ECMP), the `CiliumL2AnnouncementPolicy` and
`CiliumLoadBalancerIPPool`'s reliance on ARP leader election become unnecessary — though the IP pool
itself (`kubernetes/apps/kube-system/cilium/config/networks.yaml`) stays, since BGP still needs Cilium to
allocate the LoadBalancer IPs, it just changes *how those IPs get announced to the network*.

#### Trade-offs — be honest about the cost

This trades "works on any dumb switch via ARP, zero router config" for "a real routing protocol session
to operate and troubleshoot." Concretely: BGP sessions can flap (rapidly go up/down) if timers are
misconfigured; route policies/communities are an extra layer of indirection if ever needed; and debugging
"why isn't this VIP reachable" now involves checking BGP session state (`cilium bgp peers`,
`cilium bgp routes`) in addition to everything already in the Cilium/Gateway toolbox. None of this is
hard, but it is new surface area for a home lab. Given this session already covered a full rook-ceph
rollout plus the L2/traffic-policy investigation, treat this as a deliberate, separate follow-up rather
than something to rush.

#### Steps to implement

1. Confirm UDM Pro Max BGP UI is available (`Settings → Routing → BGP`) and add the LAN firewall rule for
   TCP/179 between the UDM and `10.60.0.0/24`.
2. Configure the UDM side per the table above.
3. Enable `bgpControlPlane.enabled: true` in Cilium's Helm values; verify the agent pods restart cleanly.
4. Add `kubernetes/apps/kube-system/cilium/config/bgp.yaml` with the three CRDs above (re-verify schema
   against the live cluster's installed Cilium CRD version first).
5. Verify peering: `cilium bgp peers` (via `cilium-dbg` in an agent pod, or the Cilium CLI) should show
   `ESTABLISHED` for all 5 nodes.
6. Verify route advertisement: `cilium bgp routes` should list the `kube-api` and `envoy-internal`/
   `envoy-external` VIPs, advertised only from nodes with a ready local backend.
7. Test reachability + failover: confirm dashboards load, then drain/cordon the node currently handling
   traffic and confirm the UDM's ECMP table converges to the survivors without a user-visible gap.
8. Once confirmed stable, remove `kubernetes/apps/kube-system/cilium/config/networks.yaml`'s
   `CiliumL2AnnouncementPolicy` section (keep the `CiliumLoadBalancerIPPool`) and update
   `l2announcements.enabled` to `false` in Cilium's Helm values.

**Dependencies:** None blocking — independently implementable. Builds on the `externalTrafficPolicy:
Cluster` fix already applied above (BGP Control Plane handles `Local` policy correctly, but there's no
reason to revert the `Cluster` fix once BGP lands — it remains the simpler, equally-correct choice and
keeps DSR's client-IP preservation either way).

---

### CSI Snapshots (external-snapshotter + Ceph VolumeSnapshotClass)

> **Status: ✅ DONE (2026-06-20).** Deployed `piraeusdatastore/snapshot-controller` (v5.1.1) as a
> cluster-singleton in its own `snapshot-controller` namespace
> (`kubernetes/apps/system/snapshot-controller/`), installing the controller Deployment and the
> three CRDs (`VolumeSnapshot`, `VolumeSnapshotContent`, `VolumeSnapshotClass`). Rook's
> `cephBlockPoolsVolumeSnapshotClass` is enabled in
> `kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml`, producing a
> VolumeSnapshotClass named **`ceph-block-snapshot`** (named explicitly rather than accepting the
> chart's own default of `ceph-block` — identical to the StorageClass name; distinct API kinds,
> no functional collision, but confusing in `kubectl get` output) backed by
> `rook-ceph.rbd.csi.ceph.com`. Not the cluster-default snapshot class — consumers (e.g. VolSync)
> reference it by name explicitly. Verified live via a full smoke test on disposable scratch
> resources (canary file → snapshot → restore into a new PVC → byte-for-byte integrity confirmed,
> then full teardown including `VolumeSnapshotContent` garbage collection).

**What "backup" buys that `ceph-block` replication does not:** `size=3`/`min_size=2` keeps three
*live, synchronously-updated* copies — it survives a **node/disk hardware failure** but a
`kubectl delete pvc`, a corrupt write, or an `rbd rm` propagates to all three replicas instantly.
Snapshots give local point-in-time rollback; VolSync (below) gives off-cluster, portable recovery.
This closes the 3-2-1 gap that replication alone leaves open.

**Unblocked VolSync's `copyMethod: Snapshot`** — see [VolSync (PVC Backup)](#volsync-pvc-backup),
now also live.

**Dependencies:** Rook-Ceph ✅.

---

### VolSync (PVC Backup)

> **Status: ✅ DONE.** VolSync backs up every stateful app's `ceph-block` PVC (except CNPG's —
> see below) to a local, NFS-direct Restic repository on TrueNAS. Canary `waha`
> (`kubernetes/apps/automation/waha/`) is fully cut over: its PVC (named **`waha`**, not
> `sessions`) was deliberately deleted and recreated by `components/volsync` from a
> verified-restorable backup, restoring real WhatsApp session data with no re-link needed.
>
> **Incident, 2026-06-22:** a first attempt wired waha straight to `existingClaim` +
> `dataSourceRef` on the wrong assumption that app-template names an unnamed PVC after the
> persistence map key (`sessions`); it actually names it after the release (`waha`). That
> commit reached production briefly before being reverted, and Helm's upgrade deleted the
> live, undeclared-by-the-new-template `waha` PVC in the process — the original ~4 days of
> WhatsApp session data was lost (recoverable only via re-linking the WhatsApp session, not a
> backup, since no backup pipeline existed yet at the time). Root cause and the corrected
> two-phase retrofit procedure are in
> [CLUSTER.md → VolSync → Canary](CLUSTER.md#volsync-pvc-backup).

**Why Restic + upstream `backube/volsync`, not Kopia + the `perfectra1n` fork:** Kopia mover and
its decoupled `KopiaMaintenance` CRD only exist in a community fork — verified directly against
upstream's CRD schema, which has zero `kopia` references anywhere. Adopting the fork would trade
the officially-maintained, cosign-eligible chart for a single-maintainer fork with no signatures
and a 4-year-stale upstream discussion (`backube/volsync#474`) about Kopia support with zero
momentum — for a feature whose only real edge (coordinated repo maintenance) Restic's own
`pruneIntervalDays` mostly covers. The NFS-direct design below was assumed fork-exclusive going
in; it isn't — upstream's Restic mover's `moverVolumes` already supports mounting a raw `nfs:`
volume directly (verified against the CRD schema), so there was no capability actually traded
away by staying on upstream.

**Why NFS-direct, not S3/B2:** backups land on `10.200.0.41:/mnt/tank/Cluster/volsync` directly
over the storage VLAN — restore time is bounded by LAN throughput, not internet upload/download,
which matters for the common case (accidental delete, bad deploy). Off-site protection against a
full NAS loss is handled **on TrueNAS itself** (e.g. a Cloud Sync Task mirroring that directory to
S3/B2) — deliberately out of Kubernetes/GitOps scope, since it's NAS-native functionality, not a
cluster concern.

**Jitter / staggering:** a `MutatingAdmissionPolicy`
(`kubernetes/apps/system/volsync/app/mutatingadmissionpolicy.yaml`, native CEL-based admission,
GA in `admissionregistration.k8s.io/v1` on this cluster) injects a random 0–30s sleep
`initContainer` into every backup Job — CEL match on the `volsync-src-` name prefix +
`app.kubernetes.io/created-by: volsync` label, verified upstream-genuine in VolSync's own shared
controller code, not fork-specific. Spreads backup start times so a growing number of apps on the
same schedule doesn't spike NFS/CPU load simultaneously. Deliberately scoped to backup (`src`)
Jobs only — restore (`dst`) Jobs are rare, one-shot events (manual trigger or bootstrap), not a
recurring thundering-herd risk, so jittering them would only delay getting data back with no
offsetting benefit.

**Bootstrap-restore pattern:** every app's PVC carries `dataSourceRef` pointing at its own
`${APP}-bootstrap` `ReplicationDestination` (manual `restore-once` trigger) — see
`kubernetes/components/volsync/pvc.yaml`. This makes restore-or-start-empty automatic on every
deploy or redeploy, with no manual step. **Bootstrap window caveat:** there's a gap between first
deploy and first completed backup where a deleted app has nothing to restore from — trigger a
manual backup immediately after deploying a new VolSync-enabled app:
```sh
kubectl patch replicationsource <app> -n <namespace> --type=merge \
  -p='{"spec":{"trigger":{"manual":"initial-'$(date +%s)'"}}}'
```

**CNPG exclusion:** `postgres-v17`'s PVC is **not** covered by VolSync — it already has dedicated
barman-cloud PITR (B2) + local `pg_dumpall` (NFS) backup paths, see
[CLUSTER.md → CloudNativePG → Backup strategy](CLUSTER.md#backup-strategy). Adding VolSync there
would be redundant, competing backup machinery for the same data, not complementary coverage.

**1Password:** one shared item, `volsync-restic`, holding a single `RESTIC_PASSWORD` field —
every app's Restic repository uses the same password; per-app isolation comes entirely from the
repository sub-path (`local:/mnt/repository/${APP}`), not from separate credentials. Losing this
password is permanent data loss for every app's backups.

**Manual TrueNAS-side prerequisite** (not GitOps): create dataset `tank/Cluster/volsync`, `chown
4000:4000`, and confirm the NFS export ACL allows `10.200.0.0/24` (the storage bond) — same as
the existing `postgres-backup-local` share. Verified live via Cilium's BPF NAT table that pod
traffic to TrueNAS masquerades through the egressing node's storage-bond IP, not its management
IP (`cilium-dbg bpf nat list` showed `10.42.x.x:port -> 10.200.0.41:2049 XLATE_SRC
10.200.0.20x:port`) — Cilium's masquerade follows the kernel's per-destination routing decision
here, not a single hardcoded device, so `10.60.0.0/24` is not needed in the export ACL.

**Files:** `kubernetes/apps/system/volsync/` (operator + jitter policy),
`kubernetes/components/volsync/` (per-app Kustomize Component: ExternalSecret + PVC +
ReplicationSource + ReplicationDestination, wired via `spec.components` +
`spec.postBuild.substitute` on the consuming app's `ks.yaml`). See
[CLUSTER.md → VolSync](CLUSTER.md#volsync-pvc-backup) for full architecture detail.

**Decided: Prometheus's `prometheus-db` PVC is explicitly excluded from VolSync scope.** Its real
PVC (`prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-
prometheus-0`, 20 Gi, `ceph-block`) is StatefulSet-generated via `volumeClaimTemplate` — confirmed
live that `dataSourceRef` is a schema-valid field there (`kubectl explain
prometheus.spec.storage.volumeClaimTemplate.spec`), so a bootstrap-restore mechanism is technically
buildable, but it would be inert on this already-running cluster (Kubernetes never retroactively
applies `volumeClaimTemplate` changes to PVCs that already exist) and only pays off on a genuine
from-scratch rebuild. Weighed against that: Prometheus's TSDB is short-term operational data, not
an archive (`retention: 14d` / `retentionSize: 18GB`, well under the 20 Gi PVC), continuously
regenerated, already protected day-to-day by 3× Ceph replication, and restoring a stale snapshot
into a live TSDB is operationally messy (block-compaction overlap). The restore complexity isn't
worth it for data this disposable — `waha` remains VolSync's only consumer, by design, not a
stepping stone to more.

**Dependencies:** CSI Snapshots ✅, external-secrets ✅, onepassword-connect ✅. (Historical —
this item is now closed.)

---

### Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository worth adopting. Each is independently implementable — ordered roughly by value vs. effort.

#### Kustomize Components (`kubernetes/components/`)

Reusable Kustomize Components (`apiVersion: kustomize.config.k8s.io/v1alpha1 / kind: Component`)
that apps include via **`spec.components` on the Flux `Kustomization` (`ks.yaml`)**, not the
plain `app/kustomization.yaml` — `postBuild.substitute` (for any `${VAR}` tokens the Component's
templates use) only exists on the Flux CRD, so declaring `components:` anywhere else leaves those
tokens unsubstituted. bykaj ships:
- `components/namespace/` — bundles namespace creation + `cluster-secrets` Secret per-app
  namespace + Flux alerts
- `components/keda/*-scaler/` — KEDA ScaledObject templates for Postgres, Redis, NFS, SMB
- `components/gpu/` — ResourceClaimTemplate for GPU workloads

**`components/volsync/` is built** — see [VolSync (PVC Backup)](#volsync-pvc-backup) above, the
first Component in this repo and the reference implementation for the `ks.yaml`-level wiring
pattern described above (see `kubernetes/apps/automation/waha/ks.yaml` for a concrete example).

**Steps to implement further Components:**
- The `namespace` Component is next highest priority: bundles namespace creation + cluster-secrets
  per-app, so apps never need separate namespace manifests or per-namespace secret wiring
- Add a Component only when the same boilerplate appears in 3+ apps — don't create early
- KEDA scalers once a real consumer exists (KEDA itself is deployed, operator-only) — see
  [KEDA NFS-Scaler (Future)](#keda-nfs-scaler-future) below

---

#### Multi-Domain Certificate Pipeline (`certificates-export` / `certificates-import`) ✅ COMPLETE (2026-08-04)

A two-phase push-pull pattern that makes TLS certificates resilient across cluster rebuilds and avoids Let's Encrypt rate limits when managing multiple domains. Sourced from `bykaj/home-ops` (`kubernetes/apps/network/certificates/`).

**Why this matters for us:**
Five domains (`vwn-app`, `vwn-casa`, `cluster-vwn-io`, `apps-vwn-io`, `vwn-io`) are now wildcard-certified via this pattern instead of one cert issued directly by cert-manager. Each rebuild used to risk the Let's Encrypt [duplicate certificate rate limit](https://letsencrypt.org/docs/rate-limits/) (5 identical certs per 7 days) once more than one domain was in play. With this pattern, certs are issued once and persisted in 1Password — rebuilds restore from 1Password in seconds. `envoy-gateway-config` now `dependsOn: certificates-import`, so the Gateway never applies before the TLS Secrets exist — closing the ordering gap that existed while the PushSecret backfill was still pending. Backfilling surfaced two follow-on fixes: a 1Password Connect token-permission 403 (vault access needed explicit create/edit rights, not just the token itself) and a duplicate-item creation race from ESO's 2-replica no-leader-election setup, both described in `docs/CLUSTER.md`'s External Secrets section.

**How it works:**

```
cert-manager issues Certificate
    ↓ creates TLS Secret in cluster
PushSecret (ESO) → writes Secret into 1Password as base64-encoded item
    (certificates-export Kustomization)

    ↑ on cluster rebuild / new node
ExternalSecret (ESO) ← reads item from 1Password, recreates TLS Secret
    refreshPolicy: CreatedOnce   — ESO won't overwrite once created
    creationPolicy: Orphan       — cert-manager retains ownership; rotations flow naturally
    (certificates-import Kustomization)
```

`envoy-gateway-config` gains `dependsOn: certificates-import`, ensuring the Gateway listeners never apply before the TLS Secrets exist.

**Directory layout:**

```
kubernetes/apps/network/certificates/
├── ks.yaml                        # two-doc: certificates-import (wait: true) → certificates-export
├── export/
│   ├── kustomization.yaml
│   ├── certificates.yaml          # cert-manager Certificate CRs (one per domain)
│   └── pushsecrets.yaml           # ESO PushSecret CRs (one per domain)
└── import/
    ├── kustomization.yaml
    └── externalsecrets.yaml       # ESO ExternalSecret CRs (one per domain)
```

**Flux ordering:**

```
certificates-import (wait: true)
    ↓ produces TLS Secrets
certificates-export (dependsOn: certificates-import)
    ↓ keeps 1Password in sync
envoy-gateway-config (dependsOn: certificates-import, cert-manager)
```

**Steps to implement (when adding a second domain):**

1. Create `kubernetes/apps/network/certificates/` with the layout above
2. For each domain, add one `Certificate` + one `PushSecret` (export) and one `ExternalSecret` (import)
3. Add `certificates` to `kubernetes/apps/network/kustomization.yaml`
4. Move `wildcard-production` `Certificate` from `envoy-gateway/config/` into `certificates/export/certificates.yaml`; remove `certificate.yaml` from `envoy-gateway/config/`
5. Update `envoy-gateway/ks.yaml`: replace `dependsOn: cluster-issuers` with `dependsOn: certificates-import`
6. Update `envoy-gateway/config/gateway.yaml` listeners to reference per-domain Secret names (e.g. `vwn-io-tls`) instead of `wildcard-production-tls`
7. Seed 1Password: on first deploy, `certificates-export` runs first and writes the certs; subsequent rebuilds restore from 1Password before cert-manager even runs

**Note on `creationPolicy: Orphan`:** The ExternalSecret creates the Secret but immediately releases ownership. cert-manager then annotates and manages it normally — renewal writes a new cert into the same Secret, which ESO's `refreshPolicy: CreatedOnce` leaves untouched. `PushSecret` picks up the renewed cert and writes it back into 1Password, keeping the vault copy current.

**Dependencies:** `external-secrets` + `onepassword-connect` ✅ (already deployed), `cert-manager` ✅. Defer until a second domain is added — the single-domain wildcard approach is correct and simpler for now.

---

#### Split Renovate Configuration (`.renovate/` directory)

Instead of a single `renovate.json5`, split config into files by concern so each section
is independently reviewable in PRs. Reference pattern: `bykaj/home-ops` uses
`allowedVersions.json5`, `autoMerge.json5`, `groups.json5`, `customManagers.json5`,
`labels.json5`, `semanticCommits.json5`, etc.

**When to do this:** defer until `renovate.json5` feels unwieldy — roughly 400+ lines, or
when adding KEDA scalers, VolSync rules, or complex `allowedVersions` blocks. As of 2026-05-22
the file is ~282 lines and well-structured; the split adds overhead without much benefit yet.

**How it actually works — important:**
This is NOT a simple file-cut. Each split file must be a valid **Renovate local preset**,
not a raw JSON5 fragment. Renovate loads them via `extends`, not by auto-scanning the directory.

**Steps to implement:**
1. Create `.renovate/` directory with one file per concern, each structured as a preset:
   ```json5
   // .renovate/groups.json5
   {
     description: "Package grouping rules",
     packageRules: [ /* grouping rules only */ ],
   }
   ```
   Suggested split for this repo:
   - `.renovate/renovate.json5` — root config: `$schema`, `extends`, `schedule`, `ignorePaths`, `ignoreDeps`, manager file-pattern overrides
   - `.renovate/groups.json5` — all `groupName` rules
   - `.renovate/autoMerge.json5` — all `automerge: true` rules
   - `.renovate/semanticCommits.json5` — commit message formatting + scope rules
   - `.renovate/labels.json5` — label rules
   - `.renovate/customManagers.json5` — regex custom manager

2. Update the root config to reference each split file via `extends`:
   ```json5
   extends: [
     "config:recommended",
     // ... other presets ...
     "local:.renovate/groups.json5",
     "local:.renovate/autoMerge.json5",
     "local:.renovate/semanticCommits.json5",
     "local:.renovate/labels.json5",
     "local:.renovate/customManagers.json5",
   ],
   ```

3. Delete the original `renovate.json5` once the root config lives at `.renovate/renovate.json5`.

**No cluster-level impact** — purely a repository ergonomics improvement. Validate by
triggering a Renovate dry-run after the split (check the Dependency Dashboard issue for errors).

---

#### Grafana-Operator: Full Native Migration (Future)

**Context:** the `unpoller` deployment (2026-07-03 session) needed a cleaner way to manage
grafana.com-sourced dashboards than the `sidecar.dashboards` ConfigMap-label pattern, and evaluated
`grafana-operator` (as bykaj's repo uses it) as the fix. Two integration modes exist; **this
cluster adopted the low-risk one** — see below — and this entry documents the road not taken.

**Mode adopted (done):** `grafana-operator` in **external mode** — a `Grafana` CR with
`spec.external.url` pointing at the *existing* `kube-prometheus-stack-grafana` Service, reusing the
existing `grafana-admin-secret` for auth. The operator only pushes `GrafanaDashboard`/
`GrafanaDatasource` CRs into the already-running Grafana over its HTTP API — the Grafana
Deployment, its `ceph-block` PVC, and its `grafana.db` (restored from NFS during the Phase 5
storage migration — see [Grafana](#grafana) above) are completely untouched. See
`kubernetes/apps/observability/grafana-operator/` and `kubernetes/apps/observability/unpoller/`.

**Mode NOT adopted — bykaj's model:** bykaj runs Grafana **natively** under the operator — a
`Grafana` CR that owns its own Deployment, its own PVC (`10Gi ceph-block` in their repo), its own
`GF_SECURITY_ADMIN_USER`/`PASSWORD` secret, and the Grafana `config` (`grafana.ini`-equivalent)
inline in `spec.config`. This is strictly more capable — the operator manages Grafana's full
lifecycle, not just dashboard content pushed over an API — but adopting it here means:

1. Disabling `kube-prometheus-stack`'s bundled Grafana (`grafana.enabled: false` in
   `kube-prometheus-stack/app/helm/values.yaml`) — the *currently running* instance goes away.
2. A brand-new Grafana comes up with an empty PVC. Anything only ever created via the Grafana UI
   (as opposed to GitOps-managed ConfigMaps/CRDs) does not come back automatically — this includes
   whatever drove the original NFS `grafana.db` restore. GitOps-managed content (ceph-mixin
   dashboards, `node-exporter-full`, unpoller's `GrafanaDashboard` CRs) migrates cleanly since it's
   already declarative.
3. Re-pointing everything that currently targets `kube-prometheus-stack-grafana` — the
   `envoy-internal` HTTPRoute (`grafana.${DOMAIN_CLUSTER}`), the Grafana `ServiceMonitor`, and any
   `NetworkPolicy`/firewall rule scoped to that Service name — at the new operator-owned Service.
4. A genuine stateful cutover on a live, working service, in the same risk class as the 2026-06-22
   VolSync/waha PVC incident (session log) — a wrong assumption about what Helm does to an existing
   PVC on a values change destroyed a live volume that time. Same blast-radius category here.

**When to revisit:** if Grafana's own config/plugins/lifecycle ever need to be GitOps-managed as
CRDs rather than Helm values — e.g. wanting `spec.config` drift-detection on `grafana.ini`, or
needing more `Grafana` CRs for a second isolated instance. Nothing today requires this; external
mode already satisfies the goal that prompted the evaluation (clean, Renovate-trackable dashboard
management).

**Migration cost:** high — stateful cutover, manual dashboard/datasource reconciliation for
anything not already GitOps-managed, re-pointing 2+ existing resources at a new Service name, and a
maintenance window (Grafana briefly unavailable during the swap).

**Reference:** `bykaj/home-ops` `kubernetes/apps/observability/grafana/instance/grafana.yaml`
(native `Grafana` CR) and `kubernetes/apps/observability/grafana/operator/helmrelease.yaml`.

---

#### Intel GPU: Device-Plugin → DRA Migration (Future)

bykaj schedules Intel iGPU access via DRA (`ResourceClaimTemplate`, `resource.k8s.io/v1`) instead of
this cluster's device-plugin extended-resource model (`gpu.intel.com/i915`, NFD-labeled nodeSelector).
DRA is GA as of Kubernetes 1.34 (this cluster runs v1.36.1) and is strictly more expressive — device
sharing via `adminAccess`, richer selection criteria — but the current device-plugin setup (deployed
2026-07-09, `intel-igpu-quicksync-passthrough` session) is freshly rolled out and healthy across all
4 GPU nodes.

**When to revisit:** once multiple GPU workloads need to contend for/share the same physical iGPU
(e.g. a maintenance job needing co-access without displacing a transcode session) — not urgent
before then. Note: no workload in this repo requests the GPU yet (Plex/Jellyfin are only planned,
per `docs/POTENTIAL-DEPLOYMENTS.md` — not deployed).

**Full phased plan (research → dual-run → first consumer on DRA → any remaining consumers →
decommission device-plugin):** see [dra-gpu-migration-plan.md](dra-gpu-migration-plan.md).

**Reference:** `bykaj/home-ops` `kubernetes/components/gpu/resourceclaimtemplate.yaml`,
`kubernetes/apps/media/{plex,jellyfin}/ks.yaml`.

---

#### KEDA NFS-Scaler (Future)

**KEDA the operator is deployed** (2026-07-09, `kubernetes/apps/system/keda/`, chart v2.20.1 via
`ghcr.io/home-operations/charts-mirror`, own `keda` namespace, Prometheus metrics/ServiceMonitors
enabled for the metric-server/operator/webhooks components). No `ScaledObject` exists yet — this
was a scoped, operator-only deployment; the nfs-scaler pattern below still has no real consumer.

**Compatibility note (unverified until first live reconcile):** chart v2.20.1 is the newest tag on
the mirror and is tested upstream against Kubernetes v1.33–v1.35; this cluster runs v1.36.1, one
minor ahead of KEDA's stated tested ceiling. `kustomize build` validated cleanly but cannot catch
an API-server-level incompatibility — watch the `HelmRelease` go `Ready` on the first reconcile
after this is pushed, and check `kubectl -n keda get helmrelease keda` / pod logs if it doesn't.

bykaj's `components/keda/nfs-scaler/` scales an NFS-backed Deployment to `0` replicas whenever a
Prometheus blackbox probe shows the NAS's NFS export is unreachable, then restores the original
replica count once it recovers — avoids crash-looping pods during a NAS reboot/network blip. A
blackbox-exporter (needed for the NFS-reachability probe) is still not deployed (planned-only entry
in `docs/POTENTIAL-DEPLOYMENTS.md`), and this repo's only current NFS consumer
(`postgres-backup-local`) is a CronJob the pattern doesn't apply to — this cluster is Ceph-first,
not NFS-first.

**When to revisit:** once a real NFS-backed Deployment exists (most likely a media app like
Plex/Jellyfin using an NFS media mount, per `docs/POTENTIAL-DEPLOYMENTS.md` — not committed).

**Full phased plan (verify KEDA/blackbox-exporter prerequisites → pilot on one workload → expand →
promote to a reusable Component):** see [keda-nfs-scaler-plan.md](keda-nfs-scaler-plan.md).

**Reference:** `bykaj/home-ops` `kubernetes/components/keda/nfs-scaler/scaledobject.yaml`,
`kubernetes/apps/media/{plex,jellyfin}/ks.yaml`.

---

#### Dedicated `envoy-services` Gateway (Future)

A third Gateway alongside `envoy-external` and `envoy-internal`, purpose-built for LAN infrastructure proxying (Proxmox, PBS, NAS, home appliances). Currently deferred — all LAN services route through `envoy-internal` with TLS terminated at the gateway (see [CLUSTER.md → Scenario 4](CLUSTER.md#scenario-4--lan-resource-proxy-external-services)).

**When to revisit:**
- You need IP-level ACLs: a dedicated CiliumLB IP lets UniFi firewall rules restrict Proxmox/PBS to the admin VLAN without affecting `envoy-internal` cluster-app traffic
- A LAN host requires TLS passthrough (e.g. Proxmox with its own ACME cert via a `TLSRoute`): adding a `TLS: Passthrough` listener to `envoy-internal` widens its surface area; a dedicated gateway contains the change to a separate resource
- `envoy-internal` HTTPRoutes grow too large and you want independent observability/audit surfaces per gateway

**Migration cost:** low — HTTPRoutes only need `parentRefs.name` changed from `envoy-internal` to `envoy-services`. Claim one IP from the `10.60.0.230–249` Cilium pool, create the `Gateway` resource in `envoy-gateway/config/gateway.yaml`, and add an ExternalDNS annotation targeting `services.${DOMAIN_CLUSTER}`.

**Overhead:** one additional Envoy proxy Deployment (3 replicas × ~256 Mi each) and one IP from the Cilium pool.

**Reference:** `bykaj/home-ops` `kubernetes/apps/network/external-services/` uses this pattern with an `envoy-services` gateway on a dedicated IP.

---

### Dragonfly: Snapshot Persistence (Future)

`kubernetes/apps/database/dragonfly/` currently runs with no persistence by design — HA comes from
3 in-memory replicas (`spec.replicas`) plus `spec.topologySpreadConstraints`, not disk replication,
which was the whole point of choosing Dragonfly over Valkey/Redis on this cluster's `ceph-block`
(RWO-only) storage. Not needed today: the only planned consumer (a paused paperless-ngx plan) only
uses it for non-durable Celery/Channels traffic.

**When to revisit:** a future consumer needs to survive a full cluster restart without a cold cache
(e.g. a job queue where in-flight work would otherwise be lost).

**How**: the `Dragonfly` CRD has a native `spec.snapshot` field — no redesign needed, just an
addition to `cluster.yaml`:

```yaml
spec:
  snapshot:
    dir: s3://<bucket>/dragonfly/          # S3-compatible target, not a local PVC
    cron: "0 * * * *"                       # hourly, adjust as needed
    enableOnMasterOnly: true                 # avoid replicas racing/clobbering the same prefix
```

Prefer the **S3 `dir`** form over `persistentVolumeClaimSpec` — it keeps the deployment disk-free,
preserving the same rationale that led to choosing Dragonfly in the first place, and can reuse the
same Backblaze B2 bucket + S3-compatible credential pattern `plugin-barman-cloud` already uses for
CNPG's WAL archiving (`kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml`), via a
new same-namespace `ExternalSecret` (or extending the existing `cloudnative-pg` 1Password item's S3
fields, if scoping allows) supplying `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` through
`spec.env` on the `Dragonfly` CR. `enableOnMasterOnly: true` is a solid default either way — without
it, every replica would write to the same `dir`/prefix concurrently.

The `persistentVolumeClaimSpec` alternative (one `ceph-block` PVC per pod) works too, but
reintroduces the RWO-disk dependency this design deliberately avoided — only reach for it if S3
access turns out to be unavailable/undesirable at the time.

---

## Completed

| Area                          | Notes                                           |
|-------------------------------|-------------------------------------------------|
| Renovate: Mend app → self-hosted workflow | `.github/workflows/renovate.yaml` (2026-09-05): `renovatebot/github-action` v46.2.5 / Renovate 44.65.5 pinned, bot App token via 1Password, every 6 h + push-on-config + dispatch (`dryRun`, `logLevel`); `renovate-pr-review.yml` author gate moved to `qnimbus-homelab-assistant[bot]`. In-cluster runner parked — see [above](#renovate-on-an-in-cluster-runner) |
| Image pre-pull workflow (bykaj `image-pull.yaml`) | `.github/workflows/image-pull.yaml` (2026-09-05): diffs `flux-local get cluster --enable-images` between `main` and the PR, `talosctl image pull`s new ones on `home-lab` via a Talos `ServiceAccount` cert (`os:admin` — no confirmed narrower role covers image pull), Spegel fans the layer out cluster-wide. Reused tuppr's existing `kubernetesTalosAPIAccess` mechanism (`talos/patches/controller/machine-features.yaml`, control-plane-only, `allowedKubernetesNamespaces` extended to `actions-runner-system`) instead of a static talosconfig secret. Originally ran on a dedicated zero-RBAC `home-lab-image-pull` scale set; consolidated into `home-lab` 2026-09-06 (see ARC runner consolidation row below) |
| ARC runner consolidation (`home-lab`, `home-lab-readonly`, `home-lab-image-pull` → one `home-lab`) | 2026-09-06: dropped the privileged/zero-permission split built across the Renovate and image-pull sessions in favor of bykaj's single cluster-admin runner shape, per user request. `home-lab` gained a Talos `ServiceAccount` (`os:admin`); `renovate-pr-review.yml` and `image-pull.yaml`'s `pull` job both now run there. Trade-off accepted knowingly: both are `pull_request`-triggered, so they now run with full cluster-admin instead of scoped access — see `runners/home-lab/rbac.yaml` |
| Persistent Storage (OpenEBS + Rook-Ceph) | OpenEBS LocalPV live; **Longhorn removed**, superseded by Rook-Ceph v1.19.6 (`ceph-block` default SC, `size=3`/`min_size=2`); the per-node dedicated disks (cp-01/cp-02: Kingston SNV3S1000G, cp-03: Crucial CT2000P310SSD8) are now wiped-to-raw Ceph OSDs on the `10.200.0.0/24` storage bond. Longhorn 3-replica ran 2026-05-23 → 2026-06-08 |
| Pod Topology: scheduling concentration on cp-03   | Fixed imbalance; CoreDNS + Envoy proxies spread to 3 replicas 1/node (`DoNotSchedule`); Flux/cert-manager/ESO at 2 replicas + topology spread; stateful workloads (Prometheus/Alertmanager) accepted on cp-03 |
| Talos machine configs         | 3 CP nodes, patches, schematic registered       |
| Bootstrap go-task Taskfile    | Replaces scripts/bootstrap.sh                   |
| SOPS age key + rules          | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | All bootstrap steps complete                    |
| kubernetes/ directory         | Helmfile + Flux structure in place              |
| Cilium                        | Running via Helmfile bootstrap                  |
| CoreDNS                       | Running via Helmfile bootstrap                  |
| cert-manager                  | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | Reconciling from private repo via GitHub App auth (`provider: github`, `flux-github-app` ExternalSecret) — migrated off SSH deploy key |
| Renovate                      | `renovate.json5` in place; GitHub App installed; Talos/k8s tracked via `separateMinorPatch` rules (PRs target tuppr CRDs) |
| Talos + Kubernetes upgrades   | tuppr deployed; Talos v1.13.2; Kubernetes v1.36.1; upgrades now fully automated via Renovate PRs + tuppr |
| OpenEBS OCIRepository fix     | Transient timing race (HelmRelease checked source 30s before artifact was stored); forced reconcile cleared it; added `crds: CreateReplace` to HelmRelease |
| External Secrets + 1Password Connect | ESO + 1Password Connect deployed; `ClusterSecretStore` live; `external-secrets`, `onepassword-connect`, `onepassword-store` Kustomizations all Ready |
| Cluster-Level Variable Substitution | `cluster-vars` Kustomization live; `cluster-settings` ConfigMap + `cluster-secrets` SOPS Secret in `flux-system`; `substituteFrom` patch on `cluster-apps` covers all child Kustomizations |
| Global HelmRelease Defaults Patch   | Nested patch on `cluster-apps` injects `crds: CreateReplace`, `timeout: 10m`, and upgrade remediation into all HelmReleases; `CLAUDE.md` convention note updated |
| Envoy Gateway + Cilium L2 LoadBalancer | Envoy Gateway v1.8.0; `envoy-external` (10.60.0.230) + `envoy-internal` (10.60.0.231); wildcard production cert via DNS-01; HTTP→HTTPS redirect on both Gateways |
| Cloudflare Tunnel (cloudflared)        | 2-replica HA deployment in `network` namespace; `*.vwn.io` + `vwn.io` → `envoy-external`; token via ExternalSecret from 1Password |
| Flux GitHub Webhook Receiver           | `flux-receiver` Kustomization in `flux-system`; ExternalSecret token from 1Password; HTTPRoute on `envoy-external`; GitHub webhook configured — reconcile latency ~5 min → seconds |
| ExternalDNS (Split-DNS)                | `external-dns-cloudflare` (watches `envoy-external`, `--cloudflare-proxied`, `txtOwnerId: k8s`) + `external-dns-unifi` (webhook sidecar, watches all gateways + services, `txtOwnerId: k8s-internal`); shared OCIRepository `ghcr.io/home-operations/charts-mirror/external-dns` v1.21.1; CF token mapped from `API_TOKEN` → `CF_API_TOKEN` via ESO `data[]` |
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi `ceph-block` PVCs (migrated off Longhorn in Phase 5; grafana `grafana.db` restored from NFS); node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; Pushover receiver live (see Alertmanager Receiver) |
| metrics-server                         | `kube-system`; HelmRelease `v3.13.0` (HelmRepository `https://kubernetes-sigs.github.io/metrics-server`); `kubectl top` and HPA resource metrics enabled; `--kubelet-insecure-tls` flag set; migration to `home-operations/charts-mirror` OCIRepository tracked in roadmap |
| GitHub Actions Self-Hosted Runners (ARC + Claude PR Review) | ARC `gha-runner-scale-set-controller@0.14.1` + `home-lab` scale set deployed in `actions-runner-system`; Flux HelmReleases Ready; listener pod active; Renovate PR auto-review via `claude-code-action` wired |
| ExternalSecrets `dataFrom` + `rewrite` migration | All 9 ExternalSecrets migrated to `dataFrom.extract` + `rewrite.regexp` pattern; 1Password field renames completed; all 12 cluster ExternalSecrets `SecretSynced: True` |
| Flux Render CI (offline render on PRs) | `flux-render.yaml`: `flux-local test` gate + post-render kubeconform (`scripts/validate-rendered.sh`) + rendered-diff sticky PR comment; `pipx:flux-local` in `.mise.toml`, `task flux:*`. flate migration tracked above (blocked by flate#828/#937) |

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8, now a Ceph OSD disk) logs `nvme nvme1: using unchecked data buffer`. This is a one-time boot message — the Crucial P310 does not advertise the NVMe "metadata-in-data-buffer" feature; the driver falls back to a simpler DMA path silently. Confirmed count of 1, no I/O errors. Watch for additional occurrences or any `I/O error` / `nvme reset` lines: `talosctl dmesg --nodes 10.60.0.201 | grep -i nvme`. Also watch for OSD faults on cp-03 specifically: `kubectl -n rook-ceph get pods -l app=rook-ceph-osd -o wide | grep cp-03` (and `ceph osd tree` in the toolbox).
