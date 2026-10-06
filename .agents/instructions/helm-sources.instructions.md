# Helm/OCI chart source placement

Every app on an OCI chart owns an `ocirepository.yaml` next to its
`helmrelease.yaml` (e.g.
`kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`). There
is no shared source directory.

Prefer the upstream's own registry, then
`ghcr.io/home-operations/charts-mirror` (check its tags: the mirror can
lag upstream). Upstreams often publish OCI charts without saying so in
their README, so check the chart repo's release workflow for a `helm push`
before concluding there is none.

There are no `HelmRepository` sources, and the bootstrap helmfiles only
read `ocirepository.yaml`. If a chart has no OCI build in either place,
stop and ask the user rather than adding a `HelmRepository`: bootstrap
can't install such a release.
