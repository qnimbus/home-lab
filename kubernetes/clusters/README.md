# clusters

Flux's entry point for the cluster. The FluxInstance syncs `./kubernetes/clusters/main` (set in [flux-instance's values](../apps/flux-system/flux-instance/app/helm/values.yaml)). That path holds one Kustomization, [`cluster-apps`](./main/apps.yaml), which applies `./kubernetes/apps` recursively and patches cluster-wide defaults onto everything beneath it, so no app repeats that boilerplate.

## Defaults patched onto every app

| Patch                                                                                | Applies to                                              | Opt out                                                                                          |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `postBuild.substituteFrom` `cluster-settings`                                        | every Flux Kustomization                                | label the Kustomization `substitution.flux.home.arpa/disabled: "true"`                           |
| `deletionPolicy: WaitForTermination`, `retryInterval: 2m`, `timeout: 15m`            | every Flux Kustomization                                | none                                                                                             |
| install/upgrade `CreateReplace` CRDs, retry and remediation strategy, `timeout: 15m` | every HelmRelease                                       | none                                                                                             |
| `driftDetection.mode: enabled`                                                       | every HelmRelease                                       | label the HelmRelease `drift-detection.flux.home.arpa/disabled: "true"`                          |
| CNPG `Cluster` bootstraps with `initdb` instead of Barman recovery                   | Kustomizations labelled `components.postgres/cnpg=init` | remove the label once the first backup exists (see [postgres](../components/postgres/README.md)) |

To find the opt-outs in use: `grep -rl "flux.home.arpa/disabled" kubernetes/apps`.

## Gotchas

- **A patch overrides the same field in an app's `ks.yaml`.** A per-app `timeout` or `retryInterval` is silently replaced with the default. An app that needs its own `substituteFrom` has to opt out of the patch and list `cluster-settings` itself, as `network/cloudflare-tunnel` does, because the patch replaces the whole list.
- **Opt out of substitution only for a reason.** There are two: the app has its own `substituteFrom` (above), or bootstrap reads its files. The bootstrap helmfile installs some releases straight from their `app/` folder and applies `cilium/config` and the onepassword ClusterSecretStore, all verbatim; see `bootstrap/kubernetes/helmfile/`. Opting those out makes Flux render them the way bootstrap does, so a stray `${VAR}` breaks in Flux right away instead of only at the next bootstrap. An app with nothing to substitute doesn't need the label.
- **`WaitForTermination` deletes even with `prune: false`.** Deleting a Kustomization removes its resources and waits (up to `timeout`) until they're gone. To move an app without losing its data, first patch `deletionPolicy: Orphan` onto the old live Kustomization.
