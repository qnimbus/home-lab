# PR Upgrade Reviewer — Memory Index

- [Longhorn Upgrade Quirks](project_longhorn_upgrade_quirks.md) — CRD storedVersions migration (v1.9→v1.10), hotfix images for v1.10.0 and v1.11.0, orphan setting rename, missing crds:CreateReplace pattern
- [Flux Operator Upgrade Quirks](project_flux_operator_upgrade_quirks.md) — v0.39 flag removal, v0.40 CVE, v0.30 source-watcher controller, v0.49 K8s 1.36 bump; image availability confirmed for 0.23→0.49
- [ESO Upgrade Quirks](project_eso_upgrade_quirks.md) — chart 0.x→2.x versioning change, v2.0 removed Alibaba/Device42 (irrelevant here), v2.3 removed sprig (no template blocks in this cluster), installCRDs key unchanged; v2.5.0 image confirmed available
- [kube-prometheus-stack Upgrade Quirks](project_kube_prometheus_stack_upgrade_quirks.md) — CRD update required at each prometheus-operator bump (v76–v83); distroless images default at v85; Grafana password change at v79 (Grafana disabled here); crds.upgradeJob.enabled is preferred for bulk jumps
- [app-template Upgrade Quirks](project_app_template_upgrade_quirks.md) — v4->v5: rawResources restructured, auto-SA creation, automountServiceAccountToken=false default, min K8s 1.31/Helm 3.18; cloudflared values are v5-compatible with no changes required
