---
name: kube-prometheus-stack-upgrade-quirks
description: kube-prometheus-stack chart upgrade patterns — CRD update requirements per major version, distroless image change at v85, Grafana password change at v79, operator/KSM version crossings through chart 88.5.0
metadata:
  type: project
---

**Correction (2026-08-19, PR #80 review):** Grafana is **enabled** in this cluster
(`grafana.enabled: true` in `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml`,
with `admin.existingSecret: grafana-admin-secret`, `forceDeployDashboards: true`, ceph-mixin +
node-exporter-full dashboards wired via the sidecar). Earlier notes in this file said Grafana was
disabled — that was stale by the time of this review. Always re-check `grafana.enabled` in the
live values.yaml rather than trusting this memory's earlier assumption; the `admin.existingSecret`
override means the v79 default-password change is a non-issue either way.

Every minor-major bump of kube-prometheus-stack (chart version X.0.0) bumps the embedded
prometheus-operator and requires CRDs to be updated manually — or via the built-in
`crds.upgradeJob.enabled` mechanism (available since chart 68.4.0).

This cluster uses `crds: CreateReplace` globally via the `cluster-apps` Flux patch, which tells
Helm to apply CRD updates during `helm upgrade`. However, Helm's CRD update path does NOT handle
conversion webhooks or schema migrations for large CRD changes; the upstream UPGRADE.md recommends
`kubectl apply --server-side` as the safe path.

**The `crds.upgradeJob.enabled` value (chart-native, off by default) is the recommended
alternative** — it creates a pre-upgrade Job that applies the CRDs server-side before Helm
touches the main resources. Using this avoids the race condition where the Helm CRD apply and
the operator rollout happen in the same transaction.

## Prometheus-Operator versions crossed (75.10.0 -> 85.2.1)

| Chart version | Prometheus-Operator | CRD update required |
|---|---|---|
| 76.0.0 | v0.84.1 | yes |
| 77.0.0 | v0.85.0 | yes |
| 78.0.0 | v0.86.0 | yes |
| 79.0.0 | (no bump) | no — only Grafana default password change |
| 80.0.0 | v0.87.0 | yes |
| 81.0.0 | v0.88.0 | yes |
| 82.0.0 | v0.89.0 | yes |
| 83.0.0 | v0.90.1 | yes |
| 84.0.0 | (no bump) | no — Grafana v12 → v13 subchart |
| 85.0.0 | (no bump) | no — distroless images by default |
| 87.0.1 | v0.92.0 | (baseline confirmed live via `kubectl get deploy` 2026-08-19) |
| 88.0.0 | v0.93.0 | yes — single minor step from 87.0.1's baseline |

## Key behavioral changes in this span

- **v79**: Grafana default admin password changes from `prom-operator` to a randomly generated
  secret. Grafana is disabled in this cluster (`grafana.enabled: false`) so this is not applicable.

- **v84**: Grafana subchart bumped from v12 to v13. Grafana is disabled in this cluster, not
  applicable.

- **v85**: `prometheus` and `prometheus-node-exporter` images now default to distroless variants.
  Private registry operators must also sync the distroless-suffixed tags. This cluster pulls
  directly from upstream registries, so not a concern — but note that distroless images lack a
  shell, so `kubectl exec` into Prometheus for debugging will not work.

## Values used in this cluster that were checked

The cluster values.yaml uses: `tolerations`, `podMonitorSelectorNilUsesHelmValues`,
`probeSelectorNilUsesHelmValues`, `ruleSelectorNilUsesHelmValues`,
`scrapeConfigSelectorNilUsesHelmValues`, `serviceMonitorSelectorNilUsesHelmValues`,
`retention`, `retentionSize`, `resources`, `storageSpec`, `kubeProxy.enabled: false`,
`kubeEtcd.enabled: false`. All of these remain valid keys at v85.2.1.

**Why:** kube-prometheus-stack uses a Helm-version-major bumping convention where every
prometheus-operator minor bump triggers a chart major bump. So 10 chart major versions can
correspond to only 7 prometheus-operator minor bumps — don't treat every chart major as a
heavy migration.

**How to apply:** When reviewing future kube-prometheus-stack PRs, check the UPGRADE.md sections
for each chart major version crossed and count how many prometheus-operator CRD updates are
required. The `crds: CreateReplace` global Flux patch handles Helm-level CRD delivery but
`crds.upgradeJob.enabled: true` is the safer path for bulk jumps. **This cluster already sets
`crds.upgradeJob.enabled: true`** (confirmed 2026-08-19) — treat that as satisfied by default in
future reviews unless the diff shows it removed.

## PR #80 review (2026-08-19): chart 87.0.1 → 88.5.0, labeled "major"

Renovate's major label is triggered purely by the chart-major-version boundary at 88.0.0 — the
actual breaking surface was thin. Findings, for reuse in future reviews of this component:

- **prometheus-operator v0.92.0 → v0.93.0** (crossed at chart 88.0.0 — confirmed the running
  cluster was on v0.92.0 via `kubectl get deploy -n observability -l
  app=kube-prometheus-stack-operator`). v0.93.0 breaking changes per upstream CHANGELOG: CRD
  int/uint type validation tightening (rejects negative values — none set in this repo's specs),
  Thanos-sidecar compaction default flip for Prometheus ≥3.9/Thanos ≥0.41 (Thanos not used here),
  new default `spec.shards: 1` (not set here), remote-write v2.0 metadata behavior change
  (`remoteWrite` not configured here). None applied.
- **kube-state-metrics chart v7.8.1 → v8.0.0** (crossed at kube-prometheus-stack chart 87.18.0).
  Only breaking change: dropped CiliumNetworkPolicy support — this repo doesn't set
  `kube-state-metrics.networkPolicy`, not applicable. KSM app image only moved v2.19.1 → v2.20.0
  (a minor bump despite the chart major).
- **Grafana subchart v12.7.2 → v12.10.3** across many patch releases in this span — stays within
  the same Grafana chart major line (the v11→v12 boundary was already crossed at
  kube-prometheus-stack chart 84.0.0, per the table above). No breaking notes surfaced for this
  patch range.
- Additive-only features landed in this span with no impact on existing config: exposed
  ThanosRuler/Alertmanager/Prometheus/prometheus-operator `featureGates` spec fields
  (87.7.0–87.10.0), per-replica Gateway API HTTPRoute support (87.11.0 — this repo defines its own
  standalone `HTTPRoute` objects in `app/httproute.yaml` rather than using the chart's built-in
  route feature, so not applicable), `externalUrl` TLS support (88.3.0), kube-scheduler resource
  metrics scraping (87.17.0 — pre-existing `kubeScheduler.enabled` default, not changed by this
  bump).
- No CRD field removals/renames were called out anywhere in the 87.1.0→88.5.0 changelog span.
- Verified via `docker manifest inspect ghcr.io/prometheus-community/charts/kube-prometheus-stack:88.5.0`
  that the target OCI tag is actually published — not an instance of the "Renovate PR opened before
  image push" pitfall this repo has hit before with other components.
- This repo's `AlertmanagerConfig` (`app/alertmanagerconfig.yaml`) and `ScrapeConfig`
  (`app/scrapeconfig-truenas.yaml`) CRs both still use `monitoring.coreos.com/v1alpha1`. Neither
  API version was touched by the v0.93.0 changelog, but this is worth a standing watch item on
  future prometheus-operator bumps since `AlertmanagerConfig` v1alpha1 has been the older of two
  API versions upstream for a long time.
