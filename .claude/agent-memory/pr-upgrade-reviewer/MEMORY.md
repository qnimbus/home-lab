# PR Upgrade Reviewer — Memory Index

- [Longhorn Upgrade Quirks](project_longhorn_upgrade_quirks.md) — CRD storedVersions migration (v1.9→v1.10), hotfix images for v1.10.0 and v1.11.0, orphan setting rename, missing crds:CreateReplace pattern
- [Flux Operator Upgrade Quirks](project_flux_operator_upgrade_quirks.md) — v0.39 flag removal, v0.40 CVE, v0.30 source-watcher controller, v0.49 K8s 1.36 bump; image availability confirmed for 0.23→0.49
- [ESO Upgrade Quirks](project_eso_upgrade_quirks.md) — chart 0.x→2.x versioning change, v2.0 removed Alibaba/Device42 (irrelevant here), v2.3 removed sprig (no template blocks in this cluster), installCRDs key unchanged; v2.5.0 image confirmed available
- [kube-prometheus-stack Upgrade Quirks](project_kube_prometheus_stack_upgrade_quirks.md) — operator/KSM version map through chart 88.5.0; Grafana is enabled here (corrected); crds.upgradeJob.enabled already set; PR #80 (87.0.1→88.5.0) findings
- [app-template Upgrade Quirks](project_app_template_upgrade_quirks.md) — v4->v5: rawResources restructured, auto-SA creation, automountServiceAccountToken=false default, min K8s 1.31/Helm 3.18; cloudflared values are v5-compatible with no changes required
- [cloudflared Upgrade Quirks](project_cloudflared_upgrade_quirks.md) — calver "major" labels on year boundary; v2026.2.0 removed proxy-dns (not used here); v2026.4.0 changed edge-ip-version default from IPv4 to auto
- [Envoy Gateway Upgrade Quirks](project_envoy_gateway_upgrade_quirks.md) — v1.8.0 tag naming changed (no v-prefix for Helm OCI); CRDs moved to sub-chart; 6 breaking changes (OIDC, samplingFraction, DirectResponse, SecurityPolicy timeout) — none affect this cluster's config
