---
name: eso-upgrade-quirks
description: External Secrets Operator upgrade quirks — chart versioning change (0.x→1.x→2.x), v2.0 breaking change, sprig removal, installCRDs key, image availability confirmed
metadata:
  type: project
---

ESO switched from 0.x chart versioning to semver-aligned versioning starting at v1.0.0 (Nov 2025). Chart version now matches app version (chart 2.5.0 = app v2.5.0).

**v1.0.0 (Nov 2025):** No CRD API changes; go module restructure, esoctl additions, no Helm values renames. Largely additive.

**v2.0.0 (Feb 2026):** BREAKING — removed Alibaba and Device42 providers. Not relevant for 1Password-only deployments. Validating webhook `failurePolicy` is now dynamic.

**v2.3.0:** Removed `sprig` library dependency from ESO templating. `getHostByName` template function removed. Any ExternalSecret `template:` blocks using sprig-only functions (e.g., `htpasswd`) will break. This cluster's ExternalSecrets use no `template:` blocks — unaffected.

**`installCRDs` key** (in values.yaml): Still valid and unchanged through v2.5.0. No rename required.

**`replicaCount`, `topologySpreadConstraints`** for main/webhook/certController: All still valid in v2.5.0. No renames.

**1Password provider**: No breaking changes from 0.18.2 through 2.5.0 for `onepassword.connectHost` + `auth.secretRef.connectTokenSecretRef` pattern (ESO Connect v1 API). The 1Password native SDK provider is separate.

**Image availability**: `ghcr.io/external-secrets/external-secrets:v2.5.0` confirmed available (HTTP 200).

**CRD API version**: ESO CRDs are at `external-secrets.io/v1` through 0.18.x → 2.5.x. No API group/version change.

**Rollback**: CRDs can be downgraded if needed; no storedVersions migration required for this upgrade range.

**Why this matters:** Renovate jumped from 0.18.2 to 2.5.0 in a single PR — looks alarming but the breaking changes across the boundary are provider removals (Alibaba/Device42) not relevant to this cluster.
