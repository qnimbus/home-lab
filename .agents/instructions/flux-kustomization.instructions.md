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
  record out of public DNS. A dependent isn't applied until its dependency
  has applied the same Git revision and is Ready, so a commit that adds a
  zone to the exclusion and the first record under it can't publish the
  record first. Once published it would stay: the zone is excluded, so
  external-dns no longer sees the record to delete it.

### Don't use it for

- Waiting on a `ClusterSecretStore`/`ExternalSecret` backend to sync (e.g.
  `dependsOn: onepassword-store`). External Secrets Operator retries on its
  own; Flux's dry-run only needs the `ExternalSecret` CRD, not a synced
  store.
- Waiting on the External Secrets webhook (`dependsOn: external-secrets`
  for an app that ships an `ExternalSecret`). The dry-run fails while the
  webhook isn't serving, and Flux retries until it is.
- If a dependent genuinely can't tolerate the secret being briefly absent,
  move the `ExternalSecret` into an upstream Kustomization the dependent
  already depends on and gate it there (`wait: true`, or `healthChecks` as
  `grafana-operator` does for `grafana`), rather than adding a dependency
  purely for secret timing. Example: `rook-ceph-dashboard-password`'s
  `ExternalSecret` lives in the Rook operator's Kustomization
  (`wait: true`), not the CephCluster one that reads it. Only when no such
  upstream Kustomization exists, skip the dependency entirely.

## `commonMetadata.labels: {app.kubernetes.io/name: *app}`: don't add

It stamps the label onto every resource the Kustomization renders, not just
Pods, and nothing selects on it: no `NetworkPolicy`, `PodDisruptionBudget`,
Flux `Alert`, Grafana dashboard selector or justfile recipe. Leave it out
unless a real selector need shows up.
