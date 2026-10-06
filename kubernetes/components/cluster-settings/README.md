# cluster-settings

The per-namespace wiring every namespace pulls in: the `cluster-settings` ConfigMap that feeds Flux's `${VAR}` substitution, plus the namespace's Flux alerts from [`alerts`](../alerts/README.md).

## What it creates

One copy per namespace:

| Resource               | Name               | Purpose                                                                      |
| ---------------------- | ------------------ | ---------------------------------------------------------------------------- |
| `ConfigMap`            | `cluster-settings` | Cluster-wide values: domains, host addresses, CIDRs, the timezone            |
| `Provider` and `Alert` | `alertmanager`     | Flux errors from this namespace to Alertmanager, from the `alerts` component |

## Usage

In the namespace's `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <namespace>
components:
  - ../../components/cluster-settings
resources:
  - ./namespace.yaml
  - ./<app>/ks.yaml
```

Nothing else is needed. `cluster-apps` ([apps.yaml](../../clusters/main/apps.yaml)) patches `postBuild.substituteFrom` onto every Flux Kustomization, and Flux looks the ConfigMap up in the Kustomization's own namespace. That lookup is why each namespace needs its own copy.

A Kustomization labelled `substitution.flux.home.arpa/disabled: "true"` is skipped by that patch. Use it only for an app with its own `substituteFrom` (the patch replaces the whole list) or one whose files bootstrap reads verbatim.

## Values

[configmap.yaml](./configmap.yaml) is the list. By suffix:

| Keys               | Hold                                                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `DOMAIN_*`         | DNS zones. Which one a hostname goes under: [dns-naming](../../../.agents/instructions/dns-naming.instructions.md) |
| `*_HOST`           | IP addresses of devices outside the cluster, one per network the device is on                                      |
| `*_CIDR`           | Networks, for allow-lists                                                                                          |
| `LB_IP_*`          | Reserved LoadBalancer addresses                                                                                    |
| `CLUSTER_TIMEZONE` | For the apps that need local time: [timezones](../../../.agents/instructions/timezones.instructions.md)            |

## Caveats

- **Everything here is plaintext in Git**, and the repo is public. A value that must reach `${VAR}` substitution without being committed comes from an ExternalSecret through the app's own `substituteFrom`, as [`network/cloudflare-tunnel`](../../apps/network/cloudflare-tunnel/) does.
- **`MAIL_FROM_ADDRESS` must be an identity verified in AWS SES**, the upstream of [`mail/smtp-relay`](../../apps/mail/smtp-relay/). SES rejects any `From` address outside a verified domain or identity, so the value follows the SES console, not `DOMAIN_CLUSTER` or another in-cluster domain.
- `TAILSCALE_CIDR` is Tailscale's CGNAT range for client addresses. It is the same for every tailnet, not something this tailnet chose.
- The ConfigMap is labelled `reconcile.fluxcd.io/watch: Enabled`, so a changed value reconciles the Kustomizations that substitute from it right away, not at their next interval.
- A variable a manifest uses but nothing defines is substituted as an empty string, without an error. Check the render after adding one.
