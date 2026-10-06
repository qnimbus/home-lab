# flux-system

Flux itself, plus the apps that feed it events and report on it. flux-operator runs the Flux controllers described by the `FluxInstance`, and that instance syncs [`kubernetes/clusters/main`](../../clusters/main), whose `cluster-apps` Kustomization reconciles everything under `kubernetes/apps`, this folder included.

There is deliberately no `namespace.yaml` here. The namespace comes from bootstrap, and listing it would put the `flux-system` Namespace under Flux's own management.

## Apps

| App             | What it does                                                                                      | Notes                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `flux-operator` | Installs and manages the Flux distribution from the `FluxInstance` CR                             | Also installed by bootstrap, see below                                          |
| `flux-instance` | The `FluxInstance`: Flux version, controller tuning, Git sync, plus Flux dashboards and alerts    | Pulls the repo as a GitHub App (`flux-github-app` Secret)                       |
| `flux-receiver` | GitHub push webhook that reconciles the `flux-system` GitRepository and Kustomization immediately | Public: `flux-webhook.${DOMAIN_APP}/hook/…`                                     |
| `konflate`      | Renders each PR with flate and posts a "Konflate" check plus a rendered-diff comment              | UI public at `konflate.${DOMAIN_APP}`, internal at `konflate.${DOMAIN_CLUSTER}` |

Flux's own error alerts aren't an app here: every namespace gets a `Provider` and `Alert` from [`components/alerts`](../../components/alerts/README.md) through `cluster-settings`.

## How it fits together

- **Bootstrap.** `bootstrap/kubernetes/helmfile/apps.yaml` installs `flux-operator` and then `flux-instance` straight from these folders' `ocirepository.yaml` and `helm/values.yaml`, so Flux adopts the exact releases bootstrap created. The helmfile reads the files verbatim, so keep them free of `${VAR}`. Both Kustomizations opt out of cluster-settings substitution (`substitution.flux.home.arpa/disabled`) so Flux renders them the same way and a stray `${VAR}` breaks straight away.
- **Git credentials.** Bootstrap places `flux-github-app` from `bootstrap/kubernetes/kustomize/manifests/flux-system/secrets.yaml`; once running, `flux-instance`'s ExternalSecret takes it over from the 1Password `GitHub App` item.
- **Change delivery.** A push to `main` hits the Receiver and triggers a reconcile at once; otherwise the instance's sync interval picks it up.
- **konflate PR filter.** Only non-draft PRs labelled `area/kubernetes` (set by [`.github/labeler.yaml`](../../../.github/labeler.yaml)) are rendered. konflate re-evaluates on the `labeled` and `ready_for_review` webhooks, so a PR renders as soon as the label lands or it leaves draft.
- **konflate routes.** The UI has no auth, which is fine because the repo is public, so its rendered manifests are too. `konflate.${DOMAIN_APP}` is the public UI and the host `publicUrl` links to from PR comments. The chart's own route serves the same UI and the read-only `/mcp` endpoint on the internal gateway. GitHub's `POST /hooks` deliveries arrive on a separate host, `konflate-webhook.${DOMAIN_APP}`, the URL the GitHub App delivers to.
- **konflate secrets** come from two vaults. The webhook secret (`KF_*`) comes from the `konflate` item via the cluster-wide `onepassword` store, which only reads `homelab`. The GitHub App credentials (`GH_*`) are read straight from the `github-bot` item in the CI-side `GitHub` vault, with no copy in `homelab`, through the namespaced `onepassword-github` SecretStore. That store authenticates with a service account that can read only the `GitHub` vault; its token is bootstrapped from `homelab` (`onepassword-github-cluster-sa`). Keeping the store namespaced keeps CI credentials out of every other namespace.

## Controller tuning

All in [`flux-instance/app/helm/values.yaml`](./flux-instance/app/helm/values.yaml):

- **helm-, kustomize- and notification-controller run 2 replicas**, so losing a node means a leader-election failover (~35s lease) instead of a pod reschedule (~5–6 min). They share the `app.kubernetes.io/part-of: flux` pod label and spread over it by hostname.
- **source-controller stays at 1 replica**: only the leader serves artifacts, so a second replica never becomes Ready. It and flux-operator are kept out of the spread label on purpose, since extra pods in the group would skew the per-node count.
- **The spread is `ScheduleAnyway`, not `DoNotSchedule`.** During a Talos/Kubernetes upgrade each node is down in turn, and a hard constraint would leave replicas `Pending` for the whole run, stalling reconciliation.
- **kustomize-controller runs `--concurrent=20`** against 10 for helm- and source-controller: there are more Kustomizations than HelmReleases, and dependency chains unblock faster. All its args sit in one patch, so the effective value doesn't depend on which of two patches lands last.

## Operating

```bash
just k8s sync gitrepo                   # re-fetch the repo now (also: ks, hr, ocirepo, es)
just k8s sync-ks flux-system <name>     # reconcile one Kustomization here
just k8s apply-ks flux-system <name>    # render with flate and apply locally
flux get kustomizations -A --status-selector ready=false
```

Flux itself is upgraded by bumping `instance.distribution.version` (Renovate does this). The operator and instance charts move separately through their `ocirepository.yaml` tags.

## Gotchas

- **No NetworkPolicies**, same as every other namespace (see `CLAUDE.md`). Both charts have theirs switched off (`instance.cluster.networkPolicy: false` in `flux-instance`, `web.networkPolicy.create: false` in `flux-operator`): the operator's defaults only admitted cross-namespace ingress on 8080, which silently broke Prometheus scraping konflate's metrics port 8081.
- **flux-operator's `serviceMonitor.create` is load-bearing.** `flux-instance`'s PodMonitor only selects the four controllers, not the operator, and without the ServiceMonitor `flux_instance_info` is never scraped, so `FluxInstanceAbsent` in [`prometheusrule.yaml`](./flux-instance/app/prometheusrule.yaml) would fire permanently.
- **Nothing here depends on `external-secrets`**, although `flux-instance`, `flux-receiver` and `konflate` ship ExternalSecrets. Their dry-run fails while the ESO webhook isn't serving, and Flux retries until it is, as it does for every other app with an ExternalSecret.
