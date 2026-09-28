# alerts

A Kustomize component that sends Flux reconciliation errors to Alertmanager. Adapted from [bykaj/home-ops](https://github.com/bykaj/home-ops/tree/main/kubernetes/components/alerts).

## What it creates

One copy per namespace:

| Resource                                      | Name           | Details                                                                                                            |
| --------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `Provider` (`notification.toolkit.fluxcd.io`) | `alertmanager` | `type: alertmanager`, posting to `kube-prometheus-stack-alertmanager` in `observability`                           |
| `Alert` (`notification.toolkit.fluxcd.io`)    | `alertmanager` | `error` events from `FluxInstance`, `GitRepository`, `HelmRelease`, `Kustomization` and `OCIRepository`, all names |

Alertmanager routes `severity=error` to the `pushover` receiver (see [observability](../../apps/observability/README.md)).

## Usage

Nothing to do. [`cluster-settings`](../cluster-settings/kustomization.yaml) pulls this component in, and every namespace's `kustomization.yaml` already includes `cluster-settings`, so a new namespace is covered automatically.

## Why one per namespace

An `Alert`'s `eventSources` entry without a `namespace` only matches objects in the Alert's own namespace, and `namespace` has no wildcard; `name: "*"` only wildcards the name. The single `flux-system/flux-errors` Alert this replaced therefore never saw the Kustomizations and HelmReleases in any other namespace. Putting one Alert in each namespace covers everything without listing namespaces by hand.

## Gotchas

- **The Provider address needs the `/api/v2/alerts/` path.** Posting to the Alertmanager root returns `405 Method Not Allowed`. v1beta3 Providers have no Ready condition, so a wrong address fails silently: look for `failed to send notification` in the `notification-controller` logs.
- **`exclusionList` drops transient network errors** (DNS lookups of GitHub, TCP dial timeouts or unreachable hosts). Source-controller hits these on IPv6 blips to ghcr.io and docker.io, and they clear on the next retry.
- **Test it** by applying a throwaway Kustomization with a nonexistent `path` in any namespace, then check Alertmanager and `kubectl -n flux-system logs deploy/notification-controller` for `dispatching event` without a following `failed to send notification`.
