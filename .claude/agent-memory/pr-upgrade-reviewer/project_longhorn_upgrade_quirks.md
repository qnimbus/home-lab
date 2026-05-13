---
name: project-longhorn-upgrade-quirks
description: Longhorn-specific upgrade gotchas discovered during PR risk reviews — CRD migration requirements, hotfix images, values drift, and PSA notes
metadata:
  type: project
---

Longhorn has well-documented upgrade constraints between minor versions that frequently catch Helm-based GitOps setups.

**Why:** Multiple upgrade paths have blocking pre-conditions (CRD storage version migration, hotfix image replacements) that Renovate PRs do not encode — they only bump the chart version.

**How to apply:** Always verify the CRD storedVersions migration requirement and hotfix image status for every Longhorn minor bump before approving the Renovate PR.

## v1.9.0 → v1.10.0 (BLOCKING pre-condition)

CRD storage version migration is REQUIRED before upgrading. If the cluster was ever at v1.3.0 or earlier, CRDs may still carry `v1beta1` in `status.storedVersions`. v1.10.0 removes the `v1beta1` API entirely — a Helm upgrade that encounters any CRD with `v1beta1` in storedVersions will abort with:
```
cannot patch "backingimagedatasources.longhorn.io" ... v1beta1 was previously a storage version
```
Operator must verify and migrate storedVersions to `v1beta2` only before merging.

Hotfix note: `longhorn-manager:v1.10.0` image has a nil-pointer regression (share-manager pod backoff logic, issue #11939). Fixed in v1.10.0-hotfix-1; however since this PR skips 1.10.x entirely and lands on 1.11.2 (which backports the fix), the hotfix image pin is NOT required for this specific upgrade path.

## v1.11.0 (two hotfix images)

v1.11.0 base release had TWO known regressions requiring hotfix images:
- `longhorn-instance-manager:v1.11.0` → proxy connection leaks → high memory (issue #12573) — fixed in v1.11.1+
- `longhorn-manager:v1.11.0` → CNI label deadlock (webhook waits for CNI, CNI waits for webhook) (issue #12578) — fixed in v1.11.0-hotfix-1
Since this PR targets v1.11.2 (not v1.11.0), these regressions are already resolved.

## v1.9.0 setting rename

`orphan-auto-deletion` renamed to `orphan-resource-auto-deletion`. The `orphanAutoDeletion` key used in the repo's values.yaml maps to the OLD name and is auto-migrated during upgrade, so no manual values change is required. Longhorn handles the migration internally.

## crds: CreateReplace missing in this repo

The HelmRelease for Longhorn in qnimbus/home-lab does NOT have `crds: CreateReplace` in its install/upgrade blocks. Longhorn ships substantial CRD changes between minors. Without this flag Helm never updates CRDs on upgrade, silently leaving old schemas in-cluster. This is a standing concern independent of the specific version being merged.

## PSA label requirement

Longhorn-system namespace requires `pod-security.kubernetes.io/enforce: privileged`. Confirmed present in namespace.yaml (from prior session longhorn-psa-fix). Verify this is still present in the qnimbus repo before merging.

## values.yaml comment stale after chart bump

The comment at the top of values.yaml references `v1.9.x` chart values URL. After merging this PR the comment should be updated to reference `v1.11.x`.

## Longhorn upgrade path enforcement — ONE MINOR VERSION AT A TIME (BLOCKING)

**Correction (confirmed 2026-05-13 by live upgrade attempt)**: Direct upgrades across more than one minor version are NOT supported. Longhorn enforces this in the manager binary itself (not the pre-upgrade job), in `util.checkLHUpgradePath` (`util.go:238`). The binary runs this check at startup — regardless of whether `preUpgradeChecker.jobEnabled` is `false`.

Observed fatal error when attempting 1.9.0 → 1.11.2:
```
level=fatal msg="Error starting manager: failed to upgrade since upgrading from v1.9.0 to v1.11.2 for minor version is not supported"
```

**Required staged path**: 1.9.x → 1.10.x → 1.11.x. Each hop is a separate Helm chart version bump, separate reconcile cycle.

**Practical consequence for Renovate PRs**: Renovate may open a PR jumping multiple minor versions (e.g. 1.9.0 → 1.11.2 as it did in PR #19). These PRs cannot be merged directly — an intermediate-version commit to helmrelease.yaml is required first.

**Recommended action when reviewing a multi-minor Longhorn PR**:
1. Flag as BLOCKING: staged upgrade required
2. Advise operator to: merge/push intermediate hop (e.g. 1.10.2) → reconcile → confirm → then push final target version
3. Each hop must have `crds: CreateReplace` in place (already addressed in this repo after 2026-05-13 session)
