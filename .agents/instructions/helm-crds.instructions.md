# CRDs installed by Helm releases

A Helm chart can install CRDs in two fundamentally different ways, and their
lifecycle differs significantly:

- **From the chart's `crds/` directory.** Helm treats these CRDs specially.
  During installation, Helm creates them when they do not already exist.
  Helm does not normally upgrade or delete CRDs from `crds/`.

  Flux extends Helm's CRD handling with the HelmRelease
  `install.crds` and `upgrade.crds` policies:

  - `Skip`: do not install/update CRDs.
  - `Create`: create CRDs when missing, but do not replace existing CRDs.
  - `CreateReplace`: create missing CRDs and replace existing CRDs.

  The Flux defaults are `Create`, so **existing `crds/` CRDs are not upgraded
  unless `CreateReplace` is explicitly configured**.

  CRDs in `crds/` therefore do not need `helm.sh/resource-policy: keep` to
  protect them from Helm uninstall; Helm's special CRD handling already means
  they are not deleted by a normal Helm uninstall.

- **From `templates/`.** These are ordinary Helm-managed resources. They are
  part of the Helm release manifest, can be updated during upgrades, and can
  be deleted when the Helm release is uninstalled.

  This is particularly dangerous for CRDs: deleting a CRD also deletes all
  custom resources of that kind across the cluster.

## Rule: templated CRDs carry `helm.sh/resource-policy: keep`

Any CRD rendered from a chart's `templates/` directory MUST have:

```yaml
metadata:
  annotations:
    helm.sh/resource-policy: keep
```

The `keep` policy prevents Helm from deleting the CRD during operations such
as uninstall, or when the resource disappears from the rendered release.

It does **not** prevent Helm from updating the CRD while the CRD remains part
of the rendered release.

Use the first option that applies:

1. **The chart adds the annotation itself.**

   Examples include charts where the CRD is already configured with the
   `helm.sh/resource-policy: keep` annotation, such as Rook's relevant CRDs,
   CNPG, or cert-manager when its CRD retention option is enabled.

   Nothing needs to be added to the HelmRelease.

2. **The chart exposes a value for CRD annotations.**

   For example, KEDA supports:

   ```yaml
   values:
     crds:
       additionalAnnotations:
         helm.sh/resource-policy: keep
   ```

   Prefer the chart's supported value over a post-renderer when available.

3. **Otherwise use a Helm post-renderer.**

   For example:

   ```yaml
   spec:
     postRenderers:
       - kustomize:
           patches:
             - patch: |
                 - op: add
                   path: /metadata/annotations/helm.sh~1resource-policy
                   value: keep
               target:
                 kind: CustomResourceDefinition
   ```

   This approach is used for charts such as `keda-add-ons-http`,
   `snapshot-controller`, and `rook-ceph-operator` where the chart does not
   otherwise provide a suitable CRD annotation setting.

When using a post-renderer, keep it consistent across Helm operations. The
post-rendered result is part of what Helm applies and stores for the release.

## Helm ownership and `keep`

Helm ownership metadata and the `keep` policy are separate concepts.

A kept resource normally retains its Helm ownership metadata, for example:

```yaml
metadata:
  annotations:
    meta.helm.sh/release-name: <release>
    meta.helm.sh/release-namespace: <namespace>
    helm.sh/resource-policy: keep
```

`helm.sh/resource-policy: keep` does not mean that Helm will automatically
adopt any arbitrary existing CRD. A later installation of the same release
can reuse a kept CRD when its Helm ownership metadata still identifies that
release. Do not assume that an unrelated existing CRD will be automatically
adopted.

## HelmRelease removal is potentially destructive

A HelmRelease is normally uninstalled by Flux when the HelmRelease itself is
deleted from the cluster or from Flux's desired state.

Therefore treat the following as potentially equivalent to a Helm uninstall:

- deleting a HelmRelease;
- pruning/removing it from a Kustomization;
- renaming a HelmRelease;
- moving a HelmRelease to another namespace;
- otherwise changing the desired state so that the old HelmRelease is
  removed.

Before performing any of these operations, check whether the release owns
templated CRDs and whether those CRDs have `helm.sh/resource-policy: keep`.

A Helm uninstall can otherwise delete those CRDs and consequently delete
every custom resource of those kinds cluster-wide.

## Pre-flight audit

Before moving, renaming, or removing a HelmRelease, this audit can identify
Helm-owned CRDs that do not currently have the `keep` policy:

```bash
kubectl get crd -o json | jq -r '.items[]
  | select(.metadata.annotations["meta.helm.sh/release-name"]
      and .metadata.annotations["helm.sh/resource-policy"] != "keep")
  | .metadata.annotations["meta.helm.sh/release-namespace"] + "/" + .metadata.annotations["meta.helm.sh/release-name"]' \
  | sort | uniq -c
```

This is a useful safety check, but it is **not a complete determination of
whether every CRD is safe to delete**. It only identifies CRDs carrying Helm
release ownership metadata that lack the `keep` annotation.

In particular, do not interpret every result as necessarily being a
dangerous templated CRD: CRDs from a chart's `crds/` directory can also have
Helm ownership metadata depending on how they were installed. Determine the
CRD's actual source and lifecycle before deciding that `keep` is required.

## Accepted exceptions

The following releases are deliberately left without CRD protection because
losing their CRDs is considered recoverable in this repository.

### `external-secrets`

The `ExternalSecret` resources and the Kubernetes Secrets they create would
be affected if the CRDs were deleted, but Flux will re-apply the
`ExternalSecret` resources when the release is restored and External Secrets
Operator will refill the Secrets from 1Password.

The upstream 1Password data is not stored in these Kubernetes CRDs.

`PushSecret` resources use:

```yaml
deletionPolicy: None
```

so deleting the Kubernetes resources does not delete the corresponding
1Password secrets.

Do not add protection to this release merely to eliminate the exception;
the exception is intentional.

### `tailscale-operator`

The only relevant custom resource currently at stake is the `subnet-router`
Connector. Losing its CRD is considered recoverable.

Do not add protection to this release merely to eliminate the exception;
the exception is intentional.

### Adding another exception

If another release must intentionally remain without CRD protection, add it to
this section together with a concise explanation of why losing its CRDs and
custom resources is considered recoverable.

Do **not** silently leave a templated CRD unprotected.

## What `keep` costs

`helm.sh/resource-policy: keep` protects against accidental deletion, but it
also means that removing an application does not necessarily remove its CRDs.

When an application is intentionally and permanently removed:

1. Remove/uninstall the HelmRelease.
2. Confirm that no custom resources of the affected kinds remain.
3. Delete the now-unused CRDs manually.

For example:

```bash
kubectl get crd -o name | grep <group>

kubectl get <plural>.<group> -A
```

The second command must show no remaining objects before deleting the CRD.

Only then:

```bash
kubectl delete crd <plural>.<group> ...
```

Remember that CRDs are cluster-scoped and deleting a CRD deletes all custom
resources of that kind.

This manual cleanup is intentional. A kept CRD should not be removed
automatically merely because its application was removed.

For example, VolSync's CRDs previously remained in the cluster after the
application was removed until they were manually cleaned up on 2026-09-27.

## When a chart stops shipping a CRD

A chart upgrade can stop rendering a CRD because the chart removed, renamed,
or otherwise changed its CRD implementation.

For a templated CRD protected with:

```yaml
helm.sh/resource-policy: keep
```

the old CRD can remain in the cluster after the upgrade even though the new
chart no longer renders it. It is then effectively orphaned from the new
release and may retain the old Helm ownership metadata.

Do not automatically delete such a CRD.

When a Renovate chart update or release notes indicate that a CRD has been
removed or renamed:

1. Determine whether the old CRD still exists.
2. Determine whether any custom resources of that kind remain.
3. Determine whether the new chart provides a replacement CRD or a migration
   path.
4. Follow the chart/operator's migration instructions when applicable.
5. Only delete the old CRD manually after confirming that it is no longer
   required.

A kept CRD is therefore a deliberate safety mechanism, not a substitute for
CRD lifecycle management.

## Agent decision rule

When modifying a HelmRelease, upgrading a chart, or removing/moving an
application:

1. Determine where each CRD comes from:
   `crds/` or `templates/`.
2. For `crds/` CRDs, inspect the HelmRelease's `install.crds` and
   `upgrade.crds` settings. Do not assume existing CRDs are upgraded;
   `CreateReplace` is required for replacement of existing CRDs.
3. For templated CRDs, ensure `helm.sh/resource-policy: keep` is present,
   unless the release is an explicitly documented exception above.
4. Prefer a chart-provided CRD annotation setting over a post-renderer.
5. If a post-renderer is required, apply it consistently to all relevant
   CRDs.
6. Before removing, renaming, or moving a release, verify the CRD protection.
7. Never delete a CRD merely because the corresponding HelmRelease or chart
   was removed.
8. For intentional application removal, manually verify that no custom
   resources remain before deleting kept CRDs.
9. If a chart update removes or renames a CRD, investigate the migration and
   usage before deleting the old CRD.
10. If an unprotected templated CRD is discovered and it is not an explicit
    exception, treat that as something that must be fixed rather than silently
    accepting the risk.
