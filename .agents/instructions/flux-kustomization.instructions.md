# Flux Kustomization conventions

Guidance for what belongs in a Flux `Kustomization` CR's `spec`
(`kubernetes/apps/**/ks.yaml`).

## `dependsOn`: structural ordering only, not runtime readiness

Add `dependsOn` only when the target's _existence_ — a CRD, or an object
another Kustomization creates — is required for this Kustomization's own
dry-run apply to succeed. Not to wait for something to become functionally
ready at runtime.

### Use it for

- **Operator → CRD consumer**: a Kustomization defining a CR
  (`ClusterIssuer`, `ScaledObject`, `Grafana`, a `postgresql.cnpg.io/v1
Cluster`, etc.) whose CRD is installed by another app's Helm chart, when
  that CRD isn't already installed by the bootstrap pipeline's CRD-only
  pre-install phase (a helmfile step that applies CRDs cluster-wide before
  Flux ever reconciles). Check that phase's chart list first — if the CRD
  is pre-installed, no `dependsOn` is needed at all.
- **An app's own two-stage split** (e.g. `tuppr` → `tuppr-upgrade`,
  `grafana-operator` → `grafana-operator-instance`): structure this as two
  `Kustomization` documents in one multi-doc `ks.yaml` file — the operator
  doc (HelmRelease + `healthChecks` on it) followed by the CRD-instance doc
  (`dependsOn` the operator doc). Flux dry-runs every resource in a
  Kustomization before applying any of them, so the operator and its CRD
  instances can never share one Kustomization.
- **The storage behind a PVC** (accepted exception): `rook-ceph-cluster`
  for `ceph-block`, `csi-driver-nfs` for `nfs`. This is runtime ordering,
  not structural (a PVC's dry-run doesn't need its StorageClass), but it's
  kept deliberately: it keeps a fresh bootstrap from piling up `Pending`
  PVCs and timed-out Helm installs while Ceph comes up. The cost is that a
  not-Ready storage Kustomization also pauses reconciliation of its
  dependents.
- **Restoring certificates before cert-manager sees them** (accepted
  exception): `network/certificates-export` depends on
  `certificates-import` (`wait: true`). Also runtime ordering, but a
  `Certificate` that finds no Secret makes cert-manager issue a new one
  from Let's Encrypt instead of adopting the copy restored from 1Password.
  The dependency closes that race on a fresh cluster.
- **LAN-only `DNSEndpoint`s after the Cloudflare exclusion** (accepted
  exception): a Kustomization holding a `DNSEndpoint` for a private address
  (`network/nas`) depends on `external-dns-cloudflare` as well as
  `external-dns-unifi`. Only the second is structural (the CRD).
  external-dns-cloudflare reads every `DNSEndpoint`, and its
  `excludeDomains` is all that keeps the record out of public DNS. A
  dependent isn't applied until its dependency has applied the same Git
  revision and is Ready, so a commit that adds a zone to the exclusion and
  the first record under it can't publish the record before the exclusion
  is running. Once published it would stay: the zone is excluded, so
  external-dns no longer sees the record to delete it.

### Don't use it for

- Waiting on a `ClusterSecretStore`/`ExternalSecret` backend to sync (e.g.
  `dependsOn: onepassword-store`). External Secrets Operator retries and
  backs off on its own; Flux's dry-run only needs the `ExternalSecret` CRD
  to exist, not the referenced store to have synced yet.
- If the race is real — a specific dependent genuinely can't tolerate the
  secret being briefly absent — prefer relocating the async-producing
  resource into an upstream Kustomization the dependent already depends on
  for other reasons, and gate it there (`wait: true`, or listed in that
  Kustomization's `healthChecks` as `grafana-operator` does for `grafana`), rather than adding a new
  dependency purely for secret timing. Example: `rook-ceph-dashboard-password`'s
  `ExternalSecret` lives in the Rook operator's Kustomization (`wait:
true`), not the CephCluster one that actually reads it. Only fall back to
  skipping the dependency entirely when no suitable earlier Kustomization
  exists to relocate into.

## `commonMetadata.labels: {app.kubernetes.io/name: *app}` — don't add

This gets stamped onto every resource the Kustomization renders
(`HelmRelease`, `ExternalSecret`, `ClusterIssuer`, etc.), not just Pods.
Nothing in this repo selects on it: no `NetworkPolicy`/`PodDisruptionBudget`
exists, the Flux `Alert`s (`components/alerts`) match `eventSources` by kind
and wildcard name rather than label, Grafana's dashboard selectors use an unrelated label, and no justfile
recipe filters by it. It's boilerplate without a consumer — leave it out
unless a real selector need for it shows up.
