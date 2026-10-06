# CRDs installed by Helm releases

The `helm-crds` skill has the commands and snippets for everything below.
Use it when adding a chart, when removing, renaming or moving a
HelmRelease, and when cleaning up a leftover CRD.

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

Don't set `install.crds` or `upgrade.crds` on a HelmRelease: the patch
overwrites them. To stop a release managing its `crds/` CRDs, label the
HelmRelease `crds.flux.home.arpa/disabled: "true"`; the patch then sets both
to `Skip`.

## Rule: templated CRDs carry `helm.sh/resource-policy: keep`

`keep` stops Helm deleting the CRD on uninstall, or when the chart stops
rendering it. It doesn't stop updates. Some charts add it themselves;
otherwise set it through a chart value (as `keda` does) or a post-renderer
(as `keda-add-ons-http` does).

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
(`install.disableTakeOwnership` defaults to `false`; leave it), so two
releases rendering the same CRD never fail. They take turns overwriting it,
the schema flips between their chart versions, and uninstalling either
deletes an unkept CRD from under the other.

The usual cause is a chart bundling CRDs another release owns:
VolumeSnapshot CRDs in storage/CSI charts, Gateway API CRDs in gateway and
CNI charts, `monitoring.coreos.com` in Prometheus charts.

**When adding a chart, or changing a value that controls which CRDs it
installs**, run the skill's duplicate check before committing, and switch
the copy off in the new release. If a templated copy can't be switched off,
stop and ask the user rather than installing a second copy.

## Removing, renaming or moving a HelmRelease

Each of these uninstalls the old release: deleting the HelmRelease, pruning
it from its Kustomization, renaming it, moving it to another namespace. The
uninstall deletes the release's templated CRDs that lack `keep`, and with
them every object of those kinds. Run the skill's pre-move check first.

## Never delete a CRD just because its HelmRelease or chart is gone

A kept CRD outlives its release, and `CreateReplace` never deletes either.
So CRDs are left behind when an app is removed for good, and when a chart
upgrade drops or renames one (watch for this in Renovate PRs and release
notes). Cleanup is manual and deliberate; the skill has the steps.
