---
name: helm-crds
description: Use when adding a Helm chart that ships CRDs, changing a value that controls which CRDs a chart installs, removing, renaming or moving a HelmRelease (to another namespace or Kustomization), or cleaning up CRDs a removed app or chart upgrade left behind ("move X to namespace Y", "rename the release", "remove app X", "is this CRD still needed")
---

# Helm-installed CRDs: checks and procedures

The rules are in `.agents/instructions/helm-crds.instructions.md`. This skill holds the steps for the three tasks where those rules bite. `$TMP` is a scratch directory.

## Which kind of CRD does a chart ship?

`helm template` without `--include-crds` renders only the templated CRDs; with the flag it adds those from `crds/`.

## Adding `helm.sh/resource-policy: keep` to templated CRDs

Use the first option that applies:

1. **The chart adds it itself** (CNPG, Rook's `ceph.rook.io` CRDs, cert-manager with its CRD retention option). Nothing to add.
2. **The chart has a value for CRD annotations**, as KEDA does:

   ```yaml
   values:
     crds:
       additionalAnnotations:
         helm.sh/resource-policy: keep
   ```

3. **Otherwise a post-renderer**, as `keda-add-ons-http`, `snapshot-controller` and `rook-ceph-operator` (for its subchart's `csi.ceph.io` CRDs) do:

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

## Adding a chart, or changing which CRDs it installs: duplicate check

Run before committing.

1. Render the chart's CRDs with the release's values:

   ```bash
   yq '.spec.values' <app>/app/helmrelease.yaml > "$TMP/values.yaml"
   helm template <release> oci://<chart-url> --version <tag> --include-crds \
     -f "$TMP/values.yaml" | yq 'select(.kind=="CustomResourceDefinition") | .metadata.name'
   ```

2. `kubectl get crd <name>` for each. Any hit is a duplicate, with or without Helm annotations. The owner is `meta.helm.sh/release-name`, or otherwise the chart whose `crds/` ships it.
3. Switch the copy off in the new release and name the owner in a comment, as `system/openebs` does for the VolumeSnapshot CRDs (`openebs-crds.csi.volumeSnapshots.enabled: false`). If there is no such value and the copies are in `crds/`, label the HelmRelease `crds.flux.home.arpa/disabled: "true"`, as `external-dns-cloudflare` does for the CRDs `external-dns-unifi` owns. The label skips every `crds/` CRD of the release, so only use it when another release owns all of them. If the copies are templated and can't be switched off, stop and ask the user rather than installing a second copy.

The `check-cluster-health` skill runs a live check for templated duplicates.

## Removing, renaming or moving a HelmRelease: pre-move check

Each of these uninstalls the old release: deleting the HelmRelease, pruning it from its Kustomization, renaming it, moving it to another namespace. First list the Helm-owned CRDs that lack `keep`:

```bash
kubectl get crd -o json | jq -r '.items[]
  | select(.metadata.annotations["meta.helm.sh/release-name"]
      and .metadata.annotations["helm.sh/resource-policy"] != "keep")
  | .metadata.annotations["meta.helm.sh/release-namespace"] + "/" + .metadata.annotations["meta.helm.sh/release-name"]' \
  | sort | uniq -c
```

Expected output: the two accepted exceptions (`external-secrets`, `tailscale-operator`). Anything else is a templated CRD to protect before the move, with one caveat: a CRD a chart once templated and has since moved to `crds/` keeps its old annotations. Check which of the two it is now, and don't add `keep` to a `crds/` CRD just because it shows up here.

The new release adopts a kept CRD on install, whatever release its annotations name, as `system/snapshot-controller` did after its move.

## Cleaning up a CRD that was left behind

For a CRD whose app was removed for good, or that a chart upgrade dropped or renamed:

1. For a dropped or renamed CRD, follow the chart's migration path first.
2. Confirm no objects remain: `kubectl get <plural>.<group> -A`.
3. Only then `kubectl delete crd <plural>.<group>`.
