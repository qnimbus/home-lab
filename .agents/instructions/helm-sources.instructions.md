# Helm/OCI chart source placement

`OCIRepository` sources are defined **locally, per-app**, co-located with
the `HelmRelease` that consumes them (e.g.
`kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`) — not
centralized. There is no shared `oci/` registry directory; every app on an
OCI chart owns its own `ocirepository.yaml` next to its `helmrelease.yaml`.

Prefer the upstream's own registry, then
`ghcr.io/home-operations/charts-mirror` (check its tags: the mirror can
lag upstream, as it did for cilium). Upstreams often publish OCI charts
without saying so in their README, so check the chart repo's release
workflow for a `helm push` before concluding there is none.

There are no classic `HelmRepository` sources: the centralized
`kubernetes/flux/meta` and its `cluster-meta` Kustomization are gone, and
the bootstrap helmfiles only read `ocirepository.yaml`. If a chart
has no OCI build in either place, stop and ask the user rather than adding
a `HelmRepository`, since bootstrap can't install such a release.
