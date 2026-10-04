# CRDs installed by Helm releases

A chart installs CRDs in one of two ways, and their lifecycle differs:

- **From `crds/`.** Not ordinary release resources: a Helm uninstall leaves
  them, and they carry no `meta.helm.sh/*` annotations. `cluster-apps`
  (`kubernetes/clusters/main/apps.yaml`) patches every HelmRelease to
  `install.crds` and `upgrade.crds: CreateReplace` (Flux's own defaults are
  `Create` and `Skip`), so they are created and updated with the chart.
  They are never deleted, not even when the chart stops shipping them.
- **From `templates/`.** Ordinary release resources: updated on upgrade and
  **deleted on uninstall**. Deleting a CRD deletes every custom resource of
  that kind, cluster-wide.

To tell which a chart uses: `helm template` without `--include-crds`
renders only the templated CRDs; with the flag it adds those from `crds/`.

Don't set `install.crds` or `upgrade.crds` on a HelmRelease: the patch
overwrites them. To stop a release managing its `crds/` CRDs, label the
HelmRelease `crds.flux.home.arpa/disabled: "true"`; the patch then sets both
to `Skip`.

## Rule: templated CRDs carry `helm.sh/resource-policy: keep`

`keep` stops Helm deleting the CRD on uninstall, or when the chart stops
rendering it. It doesn't stop updates. Use the first option that applies:

1. **The chart adds it itself** (CNPG, Rook's `ceph.rook.io` CRDs,
   cert-manager with its CRD retention option). Nothing to add.
2. **The chart has a value for CRD annotations**, as KEDA does:

   ```yaml
   values:
     crds:
       additionalAnnotations:
         helm.sh/resource-policy: keep
   ```

3. **Otherwise a post-renderer**, as `keda-add-ons-http`,
   `snapshot-controller` and `rook-ceph-operator` (for its subchart's
   `csi.ceph.io` CRDs) do:

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

A templated CRD without `keep` that isn't listed under the exceptions below
is a defect: add `keep` when you find one, in the same change.

### Accepted exceptions

Deliberately unprotected, because losing their CRDs is recoverable. Don't
add protection just to clear the exception.

- **`external-secrets`**: Flux re-applies the `ExternalSecret`s and the
  operator refills the Secrets from 1Password. `PushSecret`s use
  `deletionPolicy: None`, so nothing is deleted in 1Password.
- **`tailscale-operator`**: only the `subnet-router` Connector is at stake.

Only the user decides on a new exception. It is added here with the reason
its loss is recoverable.

## One release per CRD

helm-controller takes ownership of any existing resource a chart renders
(`install.disableTakeOwnership` defaults to `false`; leave it), whatever
release its annotations name. That is what lets a new release adopt a kept
CRD, as `system/snapshot-controller` did after its move. It also means two
releases rendering the same CRD never fail. They take turns overwriting it:
templated CRDs on every drift-detection reconcile, `crds/` CRDs on every
upgrade of either release. With different chart versions the schema flips
too, and the older one makes the API server drop fields it doesn't know,
which shows up as odd operator bugs. Uninstalling either release deletes an
unkept CRD from under the other.

The usual cause is a chart bundling CRDs another release owns:
VolumeSnapshot CRDs in storage/CSI charts, Gateway API CRDs in gateway and
CNI charts, `monitoring.coreos.com` in Prometheus charts.

**When adding a chart, or changing a value that controls which CRDs it
installs**, check before committing:

1. Render the chart's CRDs with the release's values:

   ```bash
   yq '.spec.values' <app>/app/helmrelease.yaml > "$TMP/values.yaml"
   helm template <release> oci://<chart-url> --version <tag> --include-crds \
     -f "$TMP/values.yaml" | yq 'select(.kind=="CustomResourceDefinition") | .metadata.name'
   ```

2. `kubectl get crd <name>` for each. Any hit is a duplicate, with or
   without Helm annotations. The owner is `meta.helm.sh/release-name`, or
   otherwise the chart whose `crds/` ships it.
3. Switch the copy off in the new release and name the owner in a comment,
   as `system/openebs` does for the VolumeSnapshot CRDs
   (`openebs-crds.csi.volumeSnapshots.enabled: false`). If there is no such
   value and the copies are in `crds/`, use the
   `crds.flux.home.arpa/disabled` label, as `external-dns-cloudflare` does
   for the CRDs `external-dns-unifi` owns. The label skips every `crds/`
   CRD of the release, so only use it when another release owns all of
   them. If the copies are templated and can't be switched off, stop
   and ask the user rather than installing a second copy.

The `check-cluster-health` skill runs a live check for templated duplicates.

## Removing, renaming or moving a HelmRelease

Each of these uninstalls the old release: deleting the HelmRelease, pruning
it from its Kustomization, renaming it, moving it to another namespace.
First list the Helm-owned CRDs that lack `keep`:

```bash
kubectl get crd -o json | jq -r '.items[]
  | select(.metadata.annotations["meta.helm.sh/release-name"]
      and .metadata.annotations["helm.sh/resource-policy"] != "keep")
  | .metadata.annotations["meta.helm.sh/release-namespace"] + "/" + .metadata.annotations["meta.helm.sh/release-name"]' \
  | sort | uniq -c
```

Expected output: the two exceptions above. Anything else is a templated CRD
to protect before the move, with one caveat: a CRD a chart once templated
and has since moved to `crds/` keeps its old annotations. Check which of the
two it is now, and don't add `keep` to a `crds/` CRD just because it shows
up here.

## What `keep` costs

A kept CRD outlives its release, and `CreateReplace` never deletes either.
So CRDs are left behind when an app is removed for good, and when a chart
upgrade drops or renames one (watch for this in Renovate PRs and release
notes). Cleanup is manual and deliberate:

1. For a dropped or renamed CRD, follow the chart's migration path first.
2. Confirm no objects remain: `kubectl get <plural>.<group> -A`.
3. Only then `kubectl delete crd <plural>.<group>`.

Never delete a CRD just because its HelmRelease or chart is gone.
