# cert-manager

[cert-manager](https://cert-manager.io) and the two Let's Encrypt `ClusterIssuer`s every certificate in the cluster is issued from. Both solve the DNS-01 challenge through Cloudflare, so nothing has to be reachable from the internet. The certificates themselves live with their consumers; the gateways' wildcards are in [network](../network/README.md#certificates).

## Apps

Both Kustomizations are in [cert-manager/ks.yaml](./cert-manager/ks.yaml).

| App                    | What it does                                                                        | Notes                                                        |
| ---------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `cert-manager`         | The chart and its alert rules                                                       | Installed by bootstrap before Flux; opts out of substitution |
| `cert-manager-issuers` | `letsencrypt-production`, `letsencrypt-staging` and the Cloudflare token they share | `dependsOn` `cert-manager` for the CRD                       |

## How it fits together

- **Bootstrap installs the chart first** (`bootstrap/kubernetes/helmfile/apps.yaml`), reading the version from [ocirepository.yaml](./cert-manager/app/ocirepository.yaml) and the values from [helmrelease.yaml](./cert-manager/app/helmrelease.yaml). Flux then adopts that release. Bootstrap reads those files verbatim, which is why `cert-manager` opts out of `${VAR}` substitution (see [clusters](../../clusters/README.md)). `cert-manager-issuers` doesn't: its zones come from `cluster-settings`.
- **The issuers are a second Kustomization because Flux dry-runs every resource before applying any.** In one Kustomization with the chart, a missing `ClusterIssuer` CRD would fail the dry-run before the HelmRelease was ever applied.
- **`cert-manager-issuers` is Ready once `letsencrypt-production` has registered its ACME account.** A `ClusterIssuer` has no status Flux understands on its own, so `healthCheckExprs` reads its `Ready` condition. The staging issuer is left out of `healthChecks` on purpose: nothing issues from it day to day, and an outage of Let's Encrypt's staging endpoint shouldn't mark the Kustomization failed.
- **The Cloudflare token** is the `API_TOKEN` field of the 1Password item `cloudflare-tunnel`, which other apps read too (`grep -rl "key: cloudflare-tunnel" kubernetes/apps`). Rotating it re-renders all of their Secrets. cert-manager reads the Secret on every challenge, so it needs no restart.

## Operating

```bash
kubectl get clusterissuer                          # both should be Ready
kubectl get certificate,certificaterequest -A      # what is issued, and what is stuck
kubectl get order,challenge -A                     # an issuance in progress
kubectl logs -n cert-manager deploy/cert-manager   # the controller: ACME and DNS-01 errors
just k8s sync-hr cert-manager cert-manager
```

Try a new `Certificate` against `letsencrypt-staging` first. Its rate limits are far higher, and its certificates are not trusted by browsers.

## Gotchas

- **A new domain goes into `dnsZones` of both issuers** in [clusterissuer.yaml](./cert-manager/issuers/clusterissuer.yaml), as its `${DOMAIN_*}` variable. A `Certificate` for a zone neither lists is never issued: its challenge finds no matching solver.
- **Propagation checks go to Cloudflare's DNS-over-HTTPS resolvers only** (`dns01RecursiveNameservers`, `dns01RecursiveNameserversOnly`). Before asking Let's Encrypt to validate, cert-manager looks for the challenge record itself. The cluster's and the LAN's resolvers don't reliably show that record, so the check bypasses both. Don't remove the two values: issuance can then stall waiting for a record that is already public.
- **Depend on `cert-manager`, not on `cert-manager-issuers`, for the CRDs.** A chart that creates its own `Issuer` and `Certificate`s needs only the first. To find what depends on either: `grep -rn "name: cert-manager" kubernetes/apps --include=ks.yaml`.
- **The CRDs are chart templates (`crds.enabled`), protected by the chart's default `crds.keep: true`**, which puts `helm.sh/resource-policy: keep` on each one. Don't set `crds.keep: false`: uninstalling the release would then delete every `Certificate` in the cluster. See [helm-crds](../../../.agents/instructions/helm-crds.instructions.md).
- **The webhook runs two replicas behind a PodDisruptionBudget.** It validates every cert-manager resource, Flux's dry-runs included, so a single replica on a draining node would fail every Kustomization that holds a `Certificate` until it came back.
- **`CertManagerCertExpirySoon` fires at 21 days, not at expiry.** cert-manager renews a 90-day certificate 30 days before it expires, so one with less than 21 days left has been failing to renew for over a week.
- **`CertManagerAbsent` keys on `job="cert-manager"`.** The chart's ServiceMonitor takes the job name from the `app.kubernetes.io/name` label, which is `cert-manager` for the controller only (the webhook and cainjector report under their own names).
