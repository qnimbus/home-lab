# CRDs installed by Helm releases

A Helm chart can install CRDs in two fundamentally different ways, and their
lifecycle differs significantly:

- **From the chart's `crds/` directory.** Helm treats these CRDs specially.
  They are created during installation when they do not already exist, but
  they are not ordinary Helm release resources and are not deleted by a
  normal Helm uninstall.

  Flux extends Helm's CRD handling with the HelmRelease
  `install.crds` and `upgrade.crds` policies:

  - `Skip`: do not create or update CRDs.
  - `Create`: create missing CRDs, but do not update or delete existing CRDs.
  - `CreateReplace`: create missing CRDs and update/replace existing CRDs,
    but do not delete CRDs that are no longer present in the chart.

  Flux's upstream defaults are:

  - `install.crds`: `Create`
  - `upgrade.crds`: `Skip`

  **This repository overrides those defaults globally.** The `cluster-apps`
  Kustomization in `kubernetes/flux/cluster/ks.yaml` patches HelmReleases
  with:

  ```yaml
  install:
    crds: CreateReplace
  upgrade:
    crds: CreateReplace
  ```

  Therefore, for HelmReleases covered by that patch, CRDs supplied by the
  chart's `crds/` directory are both installed and updated/replaced when the
  chart changes.

  Do not add per-HelmRelease `install.crds` or `upgrade.crds` settings merely
  to obtain this behavior; the cluster-wide patch already provides it.

  `CreateReplace` still does **not** delete a CRD when the chart stops
  shipping it. Such a CRD remains in the cluster and may require manual
  cleanup after confirming that no custom resources of that kind remain.

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

A later install adopts a kept CRD, but not because of that metadata.
helm-controller takes ownership of any existing resource a chart renders
(`install.disableTakeOwnership` defaults to `false`), whatever release its
annotations name, and rewrites them to the new release. Moving
`snapshot-controller` into `system` relied on this: the new
`system/snapshot-controller` release adopted CRDs annotated for
`snapshot-controller/snapshot-controller`.

The flip side: two HelmReleases that render the same CRD don't conflict with
an error. Each takes it over on its own install or upgrade, and uninstalling
either one deletes it unless it's kept. Render each CRD from exactly one
release, and leave `disableTakeOwnership` at its default.

## One release per CRD

Because helm-controller takes ownership silently, two releases rendering the
same CRD never fail. They take turns overwriting it: templated CRDs flip on
every drift-detection reconcile, `crds/` CRDs on every upgrade of either
release through the cluster-wide `CreateReplace`. With different chart
versions the schema flips too, and the older one makes the API server drop
fields it doesn't know, which surfaces as odd operator bugs rather than a
conflict. Uninstalling either release deletes an unkept CRD from under the
other.

The usual cause is a chart that bundles CRDs another release already owns:
VolumeSnapshot CRDs in storage/CSI charts, Gateway API CRDs in gateway and
CNI charts, `monitoring.coreos.com` in Prometheus charts.

**Whenever you add a chart, or change a value that controls which CRDs a
chart installs**, check before committing:

1. Render the chart's CRDs with the release's values:

   ```bash
   yq '.spec.values' <app>/app/helmrelease.yaml > "$TMP/values.yaml"
   helm template <release> oci://<chart-url> --version <tag> --include-crds \
     -f "$TMP/values.yaml" | yq 'select(.kind=="CustomResourceDefinition") | .metadata.name'
   ```

2. Check each name against the cluster: `kubectl get crd <name>`. Any hit is a
   duplicate, whether or not it carries Helm annotations (`crds/` CRDs have
   none). The owner is `meta.helm.sh/release-name`, or otherwise the chart
   whose `crds/` ships it.
3. Switch the copy off in the new release, and say who owns it in a comment,
   as `system/openebs` does for the VolumeSnapshot CRDs that
   `snapshot-controller` owns (`openebs-crds.csi.volumeSnapshots.enabled:
false`). If the chart can't switch them off, raise it rather than
   installing a second copy.

The `check-cluster-health` skill runs a live check for templated duplicates.

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
whether every CRD is safe to delete**.

It only identifies CRDs carrying Helm release ownership metadata that lack the
`keep` annotation. In practice those are templated CRDs: CRDs from `crds/`
don't get `meta.helm.sh/*` annotations (none of the ~90 on this cluster
have them). The exception is a CRD a chart used to template and has since
moved to `crds/`: it keeps the annotations from when it was templated.
Following the steps below catches that case.

For a result from this audit:

1. Identify the owning HelmRelease.
2. Determine whether the CRD comes from the chart's `crds/` directory or
   `templates/`.
3. Check the effective HelmRelease CRD policy.
4. Only treat an unprotected templated CRD as a violation of the rule.

Do not add `helm.sh/resource-policy: keep` to a `crds/` CRD merely because it
appears in this audit.

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

The same consideration applies to CRDs from the chart's `crds/` directory:
the repository's `CreateReplace` policy updates existing CRDs but deliberately
does not delete CRDs that disappear from the chart.

A kept CRD is therefore a deliberate safety mechanism, not a substitute for
CRD lifecycle management.

## Agent decision rule

When modifying a HelmRelease, upgrading a chart, or removing/moving an
application:

1. **Determine where each CRD comes from:** `crds/` or `templates/`.

2. **For `crds/` CRDs**, use the repository's existing cluster-wide
   `CreateReplace` policy as the expected behavior. Do not add redundant
   per-HelmRelease CRD settings unless there is a specific reason to override
   the cluster-wide policy.

3. **When adding a chart or changing its CRD values**, confirm none of its
   CRDs already exist (see "One release per CRD") and switch off any copy.

4. **For templated CRDs**, ensure
   `helm.sh/resource-policy: keep` is present, unless the release is an
   explicitly documented exception above.

5. **Prefer a chart-provided CRD annotation setting** over a post-renderer.

6. **If a post-renderer is required**, apply it consistently to all relevant
   CRDs.

7. **Before removing, renaming, or moving a release**, verify the CRD source
   and protection status.

8. **Never delete a CRD merely because the corresponding HelmRelease or
   chart was removed.**

9. **For intentional application removal**, manually verify that no custom
   resources remain before deleting kept CRDs.

10. **If a chart update removes or renames a CRD**, investigate the migration
    and usage before deleting the old CRD.

11. **If an unprotected templated CRD is discovered and it is not an explicit
    exception**, treat that as something that must be fixed rather than
    silently accepting the risk.
