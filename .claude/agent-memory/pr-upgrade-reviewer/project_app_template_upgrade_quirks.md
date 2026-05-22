---
name: app-template-upgrade-quirks
description: bjw-s-labs app-template chart breaking changes across major versions; values that break on 4->5 migration
metadata:
  type: project
---

## app-template v4 -> v5 breaking changes (common library 4.x -> 5.x)

**Why:** Major version bump; upstream common library introduced several opt-in security defaults and restructured rawResources. These require values.yaml changes in any HelmRelease using app-template.

**How to apply:** When reviewing any PR that bumps app-template from 4.x to 5.x, audit the HelmRelease values for each affected app against this list before approving.

### Breaking changes in v5.0.0

1. **rawResources structure** — entire K8s manifest must be wrapped in a `manifest:` key. Old layout used flat top-level keys. If any app uses `rawResources:`, the structure must be updated.

2. **Default ServiceAccount creation** — a dedicated unprivileged ServiceAccount is now created automatically per deployment. Can conflict with apps that define their own SA or rely on `default`. Disable with `global.createDefaultServiceAccount: false` if not wanted.

3. **automountServiceAccountToken defaults to false** — apps that need API access must now set `defaultPodOptions.automountServiceAccountToken: true` explicitly.

4. **ServiceMonitor/PodMonitor jobLabel** — now defaults to `app.kubernetes.io/name` (was metadata name).

5. **Minimum K8s version: 1.31** / **Helm 3.18** required.

6. **NetworkPolicy controller/podSelector** — `controller` and `podSelector` are now mutually exclusive.

### New in v5.0.0
- HPA support
- PodMonitor support alongside ServiceMonitor
- Container/Pod resizePolicy (K8s 1.35+/1.36+)
- Native `ephemeral` persistence type

### v5.0.1 fixes (not breaking)
- ServiceAccount name resolution with `global.nameOverride`
- Allow omitting namespace in route parentRefs
- Allow setting namespace on rawResources

### cloudflared HelmRelease assessment (as of PR #33, 2026-05-22)
The cloudflared values.yaml does NOT use:
- rawResources
- explicit serviceAccount configuration
- ServiceMonitor/PodMonitor
- NetworkPolicy
- automountServiceAccountToken

The automatic SA creation (breaking change #2) will create a new SA object. This is benign for cloudflared since it does not need K8s API access. The automountServiceAccountToken defaulting to false (#3) is also benign and actually improves security.

Values changes required in cloudflared helmrelease.yaml: NONE — the existing values structure is compatible with v5.

**Image availability:** app-template-5.0.1 GitHub release confirmed published 2026-05-14T18:22:19Z. OCI tag present at ref `app-template-5.0.1` in bjw-s-labs/helm-charts git.
