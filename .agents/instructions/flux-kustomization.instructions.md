# Flux Kustomization conventions

For a Flux `Kustomization`'s `spec` (`kubernetes/apps/**/ks.yaml`).

## `dependsOn`: structural ordering only, not runtime readiness

Add `dependsOn` only when the target's _existence_ (a CRD, or an object
another Kustomization creates) is required for this Kustomization's own
dry-run apply to succeed. Not to wait for something to become ready at
runtime.

### Use it for

- **Operator → CRD consumer**: a Kustomization defining a CR
  (`ClusterIssuer`, `ScaledObject`, a CNPG `Cluster`) whose CRD another
  app's Helm chart installs. Not needed when bootstrap's CRD-only phase
  already installs that CRD: check the chart list in
  `bootstrap/kubernetes/helmfile/crds.yaml` first.
- **An app's own two-stage split** (`tuppr` → `tuppr-upgrade`,
  `grafana-operator` → `grafana-operator-instance`): two `Kustomization`
  documents in one `ks.yaml`, the operator (HelmRelease + `healthChecks`
  on it), then the CRD instances (`dependsOn` the operator). Flux dry-runs
  every resource in a Kustomization before applying any of them, so the
  two can never share one.
- **The storage behind a PVC** (accepted exception): `rook-ceph-cluster`
  for `ceph-block`, `csi-driver-nfs` for `nfs`, `csi-driver-smb` for an SMB
  volume (its Kustomization also creates the mount credentials). Runtime
  ordering, kept deliberately: it keeps a fresh bootstrap from piling up
  `Pending` PVCs and timed-out Helm installs while Ceph comes up. The cost:
  a not-Ready storage Kustomization also pauses reconciliation of its
  dependents.
- **Restoring certificates before cert-manager sees them** (accepted
  exception): `network/certificates-export` depends on
  `certificates-import` (`wait: true`). A `Certificate` that finds no
  Secret makes cert-manager issue a new one from Let's Encrypt instead of
  adopting the copy restored from 1Password.
- **LAN-only `DNSEndpoint`s after the Cloudflare exclusion** (accepted
  exception): a Kustomization holding a `DNSEndpoint` for a private address
  (`network/external-services`, `mail/smtp-relay`) depends on
  `external-dns-unifi` (structural: the CRD) and on
  `external-dns-cloudflare`, whose `excludeDomains` is all that keeps the
  record out of public DNS. A commit that adds a zone to the exclusion and
  the first record under it then can't publish the record first. Once
  published it would stay: external-dns no longer sees an excluded zone's
  records to delete them.

### Don't use it for

- Waiting on External Secrets: neither `dependsOn: onepassword-store` for
  the store to sync, nor `dependsOn: external-secrets` for the webhook. The
  operator retries a store on its own, and Flux retries a dry-run that fails
  while the webhook isn't serving. The dry-run itself only needs the
  `ExternalSecret` CRD.
- If a dependent genuinely can't tolerate the secret being briefly absent,
  move the `ExternalSecret` into an upstream Kustomization the dependent
  already depends on and gate it there (`wait: true`, or `healthChecks` as
  `grafana-operator` does for `grafana`). Example:
  `rook-ceph-dashboard-password`'s `ExternalSecret` lives in the Rook
  operator's Kustomization, not the CephCluster one that reads it. When no
  such upstream Kustomization exists, skip the dependency entirely.

## `commonMetadata.labels: {app.kubernetes.io/name: *app}`: don't add

It stamps the label onto every resource the Kustomization renders, not just
Pods, and nothing selects on it: no `NetworkPolicy`, `PodDisruptionBudget`,
Flux `Alert`, Grafana dashboard selector or justfile recipe. Leave it out
unless a real selector need shows up.
