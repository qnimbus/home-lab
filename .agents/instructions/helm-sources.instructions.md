# Helm/OCI chart source placement

`OCIRepository` sources are defined **locally, per-app**, co-located with
the `HelmRelease` that consumes them (e.g.
`kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`) — not
centralized. There is no shared `oci/` registry directory; every app on an
OCI chart owns its own `ocirepository.yaml` next to its `helmrelease.yaml`.

`HelmRepository` sources (classic, non-OCI chart repos — currently
`cilium`, `external-secrets`, `intel`, `onepassword-connect`) remain
centralized in `kubernetes/flux/meta/repos/helm/`. There's no per-app
equivalent to migrate these to: a `HelmRepository` is an index, not a chart
reference, so centralizing it avoids re-declaring the same repo URL in
every consuming app.

When adding a new app:

- Chart pulled via an OCI registry (`oci://...`) → new `ocirepository.yaml`
  in the app's own `app/` directory.
- Chart pulled via a classic Helm repo → check
  `kubernetes/flux/meta/repos/helm/` for an existing `HelmRepository`
  first; only add a new one there if the repo isn't already registered.
