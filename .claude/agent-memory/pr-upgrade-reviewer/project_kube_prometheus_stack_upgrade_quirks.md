---
name: kube-prometheus-stack-upgrade-quirks
description: kube-prometheus-stack chart upgrade patterns — CRD update requirements per major version, distroless image change at v85, Grafana password change at v79
metadata:
  type: project
---

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
`crds.upgradeJob.enabled: true` is the safer path for bulk jumps.
