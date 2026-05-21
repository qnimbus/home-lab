---
name: flux-operator-upgrade-quirks
description: Flux Operator (controlplaneio-fluxcd/flux-operator) upgrade patterns, breaking changes, and CVEs discovered during PR review
metadata:
  type: project
---

## Key upgrade facts for flux-operator / flux-instance charts (OCIRepository-based delivery)

### v0.39.0 — Operator flag removed (breaking for customised deployments)
The `--disable-wait-interruption` controller flag and its corresponding `DISABLE_WAIT_INTERRUPTION` env var were **removed** in v0.39.0 (`operator: remove --disable-wait-interruption and DISABLE_WAIT_INTERRUPTION`). If this flag is set anywhere in the FluxInstance spec or Helm values, the upgrade will fail at pod startup. The qnimbus/home-lab repo does NOT set this flag, so it is not affected.

### v0.40.0 — CVE security fix (Web UI only)
CVE-2026-23990 (GHSA-4xh5-jcj2-ch8q): Web UI Impersonation Bypass via Empty OIDC Claims. Fixed by strict RBAC validation for impersonation. Only affects clusters using the Flux Operator Web UI with OIDC/SSO. The qnimbus/home-lab repo does not use the Web UI feature.

### v0.28.0 — New install.yaml size jump (73KB → 78KB)
New RBAC and CRD resources added. The operator chart now includes additional resources. No user action needed; handled automatically by the Helm upgrade.

### v0.30.0 — Flux v2.7 / source-watcher controller onboarded
The `source-watcher` controller is a new Flux component added in Flux v2.7. The operator now manages it. If the FluxInstance spec has a `components` allowlist that does not include `source-watcher`, the controller will not be deployed. Most installs that use the default component list are unaffected.

### v0.41.0 — K8s v1.35 dependency bump
Updated Kubernetes client dependencies to v1.35.0. No API removals affecting standard workloads.

### v0.49.0 — K8s v1.36 dependency bump
Updated Kubernetes client dependencies to v1.36.0. No API removals affecting standard workloads.

### CRD growth across releases
The CRD schema archive size grew from ~16KB (v0.23.0) to ~19KB (v0.30.0+), indicating new CRD fields were added. The `crds: CreateReplace` Helm upgrade strategy (set globally in the cluster-apps patch) ensures these schema additions are applied automatically.

### Image availability — confirmed
All releases from v0.24.0 through v0.49.0 have published GitHub Release assets including `install.yaml`, confirming the OCI images were properly published. No unreleased-tag concern for this PR.

**Why:** Discovered during review of qnimbus/home-lab PR #21 upgrading flux-operator + flux-instance from 0.23.0 to 0.49.0.

**How to apply:** When reviewing future flux-operator PRs, check whether any removed flags/env vars are in use, whether the Web UI CVE is relevant, and whether the FluxInstance `components` list would exclude new controllers.
