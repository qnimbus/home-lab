---
name: envoy-gateway-upgrade-quirks
description: Envoy Gateway upgrade patterns, breaking changes, and gotchas discovered during PR reviews for this cluster
metadata:
  type: project
---

## Tag naming convention changed at v1.8.0

Prior to v1.8.0, the `docker.io/envoyproxy/gateway-helm` OCI image used `v`-prefixed tags (e.g. `v1.7.3`).
From v1.8.0 onward, both `1.8.0` (no prefix, used by Helm OCI) and `v1.8.0` (prefixed, used for git/release assets) are published but with **different digests** — they are not the same image.
Renovate correctly picked `1.8.0` (the Helm chart OCI format) when upgrading from `v1.7.3`.
The OCIRepository in this cluster (`kubernetes/flux/meta/repos/oci/envoy-gateway.yaml`) tracks the `tag:` field — confirm the tag exists on Docker Hub before merging any Renovate PR for this component.

**Why:** The naming change can be confusing; the `v`-prefixed and unprefixed tags are different artifacts.
**How to apply:** When reviewing future Envoy Gateway PRs, check Docker Hub for both variants and note which digest Renovate chose.

## v1.8.0 Breaking Changes (minor bump, high impact)

1. **CRD sub-chart split**: EG CRDs moved into a sub-chart to prevent Helm release secret size limits. `crds: CreateReplace` (injected cluster-wide by the `cluster-apps` patch) should handle this, but verify the Helm release reconciles cleanly post-merge.

2. **Gateway API CRDs bumped to v1.5.1**: The bundled Gateway API CRDs are updated. Since EG installs these via the chart, `crds: CreateReplace` ensures they are updated.

3. **DirectResponse body template syntax**: If `%` characters appear in any `DirectResponse` HTTPFilter bodies, they will now be interpreted as Envoy command operators. The cluster currently only uses `RequestRedirect` filters, so this is not affected.

4. **SecurityPolicy timeout `0s`**: Now means infinite timeout, not immediate timeout. Cluster does not use SecurityPolicy timeouts currently.

5. **samplingFraction 100x increase**: Existing `samplingFraction` values now sample 100x more. Cluster does not configure `samplingFraction` in its `EnvoyProxy` resource.

6. **OIDC filter structure change**: OIDC now generates a single native filter chain. Affects clusters using EnvoyPatchPolicy targeting OIDC-generated resources. Cluster does not use OIDC or EnvoyPatchPolicy.

7. **SecurityPolicy IR/xDS resource naming**: If you reference generated resource names in EnvoyPatchPolicy, update patch targets. Not applicable here.

8. **Logging encoder**: Production JSON logging is now default. Cosmetic change only.

## Cluster-specific notes

- HelmRelease values (`helmrelease.yaml`) only set `config.envoyGateway.provider.kubernetes.deploy.type: GatewayNamespace` — minimal footprint, no custom values that conflict with v1.8.0 changes.
- `EnvoyProxy` CR (`envoy.yaml`): uses `telemetry.metrics.prometheus: {}` — `samplingFraction` not configured, safe.
- `ClientTrafficPolicy` (`envoy.yaml`): uses `clientIPDetection`, `http2`, `tls`, `targetSelectors` — none of these are affected by v1.8.0 breaking changes.
- `Gateways`: standard HTTP/HTTPS listeners with TLS cert refs — no change.
- `HTTPRoutes`: only `RequestRedirect` filters — not affected by DirectResponse template change.
- `ks.yaml`: correct operator+config split with `dependsOn`, health checks on both Gateway objects — compliant with CLAUDE.md conventions.

## Image availability

- `docker.io/envoyproxy/gateway-helm:1.8.0` confirmed published (digest `sha256:3dbacb3abbc60dd0b0d4e998bbf34c2987669999ff40d18a035e46eea8b3410e`, 2026-05-13).
- Release tag `v1.8.0` exists in GitHub with signed release assets.
