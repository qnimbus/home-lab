# CLAUDE.md

@AGENTS.md

## Repository overview

A personal home infrastructure monorepo, not an application: a bare-metal Talos/Kubernetes cluster (GitOps via Flux), Docker Compose stacks on a TrueNAS host (GitOps via doco-cd), and the Ansible/Talos/just tooling that bootstraps and operates both. "Correct" means manifests render and lint cleanly. Validation is split between lefthook pre-commit hooks and GitHub Actions (`.github/workflows/validate.yaml`): `kustomize build`, `yamllint`, `flux-schema` (the `gitops-repo-audit` skill's vendored `scripts/validate.sh`), `kubeconform`, `actionlint`, `zizmor` and `shellcheck`. Rendered PR diffs come from konflate, running in-cluster.

mise pins the tools (`.mise/config.toml`) and sets `KUBECONFIG`, `TALOSCONFIG` and `FLATE_PATH` to repo-local paths. Its `postinstall` hook runs `lefthook install` and installs the Ansible collections from `ansible/requirements.yaml`.

## Commands

`just` (`.justfile`) is the command runner. Recipes are namespaced by module; `just` lists them all.

| Module              | File                                | For                                                                     |
| ------------------- | ----------------------------------- | ----------------------------------------------------------------------- |
| `just k8s`          | `kubernetes/mod.just`               | day-2 cluster operations                                                |
| `just k8s database` | `kubernetes/apps/database/mod.just` | `dump`/`restore`: `pg_dump`/`pg_restore` against a CNPG cluster         |
| `just talos`        | `kubernetes/talos/mod.just`         | Talos node operations                                                   |
| `just bootstrap`    | `bootstrap/mod.just`                | end-to-end bring-up                                                     |
| `just docker`       | `docker/mod.just`                   | NAS doco-cd operations                                                  |
| `just github`       | `.github/mod.just`                  | the `RUNNER` repo variable: `runner`, `runner-cluster`, `runner-hosted` |

Recipes whose name doesn't say it all:

- `just k8s sync hr|ks|gitrepo|ocirepo|es` forces Flux/ExternalSecrets reconciliation; `sync-hr`/`sync-ks`/`sync-es <ns> <name>` does one resource.
- `just k8s apply-ks`/`delete-ks <ns> <ks>` renders a Flux Kustomization locally via `flate` and applies/deletes it.
- `just k8s db-backup <ns> <app>` takes a manual CNPG backup of an `<app>-postgres` cluster.
- `just k8s cron-minute <name>` gives a stable pseudo-random cron minute.
- `just talos gen-talosconfig` recovers the talosconfig from 1Password.
- `just bootstrap cluster` brings the cluster up end to end. `just bootstrap nas` runs the Ansible playbook that (re)deploys doco-cd on TrueNAS; `just docker reconcile-nas` restarts it.

Validating one app or stack:

```bash
kustomize build kubernetes/apps/<namespace>/<app>/app     # must render (${APP}-style vars staying literal is expected)
yamllint --config-file .yamllint.yaml kubernetes/apps/<namespace>/<app>
docker compose -f docker/nas/NN-<app>/docker-compose.yaml config --quiet   # unset ${VAR} warnings are expected
```

Pre-commit hooks (lefthook, `.lefthook.yaml`) run on `git commit`, on staged files: `mise fmt`, `mise lock`, `oxfmt` for JSON/Markdown/YAML (`*.sops.yaml` excluded) followed by `yamllint` (its `braces`/`quoted-strings` rules are set to agree with oxfmt), `shellcheck`, `actionlint`, `zizmor`, and `renovate-config-validator` for `.renovaterc.json5`. CI runs the same hooks via `lefthook run`.

## Architecture

### `kubernetes/` — Flux-managed cluster state

`kubernetes/clusters/main/apps.yaml` defines one top-level Flux `Kustomization`, `cluster-apps`, which points at `./kubernetes/apps` and recurses: it finds the top-most `kustomization.yaml` in each app directory and applies everything it references.

`cluster-apps` patches cluster-wide defaults onto _every_ Kustomization/HelmRelease it manages, so apps don't repeat them:

- `postBuild.substituteFrom` the `cluster-settings` ConfigMap, looked up in the Kustomization's own namespace (it comes from `components/cluster-settings`, which every namespace's `kustomization.yaml` pulls in). Opt out with `substitution.flux.home.arpa/disabled: "true"`, but only for an app with its own `substituteFrom` (the patch replaces the whole list) or one whose files bootstrap reads verbatim (see `kubernetes/clusters/README.md`).
- `retryInterval: 2m`, `timeout: 15m`, and `deletionPolicy: WaitForTermination`: deleting a Kustomization deletes its resources and waits (up to `timeout`) until they're gone. It deletes even with `prune: false`, so moving an app without losing its data needs a temporary `deletionPolicy: Orphan` patched onto the old live Kustomization first.
- HelmRelease install/upgrade `CreateReplace`/`RetryOnFailure`/`RemediateOnFailure` (`crds.flux.home.arpa/disabled: "true"` sets the CRD policy to `Skip`, for a release whose `crds/` CRDs another release owns), and `driftDetection: enabled` (opt out with `drift-detection.flux.home.arpa/disabled: "true"`).
- a Flux Kustomization labelled `components.postgres/cnpg=init` gets its CNPG `Cluster` rewritten to a plain `initdb` bootstrap instead of Barman recovery, for a new database with no backup yet.

Each namespace directory's `kustomization.yaml` lists its own `namespace.yaml` first in `resources` (the Namespace, with `kustomize.toolkit.fluxcd.io/prune: disabled` and any namespace-specific labels such as PodSecurity levels), pulls in `components/cluster-settings`, and sets `namespace: <namespace>`. That stamps `metadata.namespace` onto every child Flux Kustomization, so `ks.yaml` files don't set it. Each `ks.yaml` does set `spec.targetNamespace` explicitly. **Exception: `flux-system`** has no `namespace.yaml`. The namespace comes from bootstrap, and a `namespace.yaml` would make Flux manage the `flux-system` Namespace itself. Don't "fix" this by adding one.

Each app lives at `kubernetes/apps/<namespace>/<app>/`. Scaffold a new one with the `add-app` skill, mirroring a recent real app:

```text
<app>/
├── ks.yaml                # Flux Kustomization — path, dependsOn, postBuild.substitute (APP etc.), optional components
└── app/
    ├── kustomization.yaml
    ├── ocirepository.yaml     # pins the chart version (app-template: oci://ghcr.io/bjw-s-labs/helm/app-template)
    ├── helmrelease.yaml       # values: controllers/service/persistence, built on bjw-s-labs/app-template
    ├── httproute.yaml         # optional — Gateway API route; always this file, never app-template's `route:` value
    ├── externalsecret.yaml    # optional — pulls 1Password fields via the `onepassword` ClusterSecretStore
    └── resources/             # optional — files wired in via configMapGenerator
```

`kubernetes/components/` holds reusable kustomize components (`alerts`, `dragonfly`, `postgres`, `kopiur` and `nfs-volume` have a README):

- `cluster-settings`: the per-namespace wiring above; it also pulls in `alerts`.
- `alerts`: a Flux `Provider` + `Alert` per namespace that sends Flux errors to Alertmanager. An `Alert` only sees its own namespace.
- `postgres`: a dedicated CNPG cluster per app, parameterized via the consuming `ks.yaml`'s `postBuild.substitute`.
- `dragonfly`: a dedicated Dragonfly per app (`${APP}-dragonfly`), plus an optional `authentication` sub-component. The operator lives in `apps/database/dragonfly`.
- `kopiur/backup`: a PVC per app that is backed up to the NAS and refilled from the latest backup when created.
- `gpu`: a `ResourceClaimTemplate` (`${APP}-gpu`) for the Intel GPU.
- `keda/http-scaler`, `keda/smb-scaler`, `nfs-volume`.

`kubernetes/talos/` holds the Talos machine-config Jinja templates (rendered with `minijinja-cli` + 1Password `op inject`, see `.justfile`'s `template` recipe) and `version.yaml`, the pinned Talos/Kubernetes versions `kubernetes/talos/mod.just` uses.

### `docker/` — Compose stacks on the TrueNAS host

Deployed by [doco-cd](https://github.com/kimdre/doco-cd), which runs on TrueNAS, polls this repo's `main` over a read-only SSH deploy key, and auto-discovers one-directory-deep stacks under `docker/nas/` (config: `docker/nas/.doco-cd.yaml`). Each stack is `docker/nas/NN-<app>/docker-compose.yaml` with image tags inline (Renovate's `docker-compose` manager tracks them). The `NN-` prefix is ordering only: renaming or renumbering a directory deletes and recreates the stack, anonymous volumes included, so keep it stable. Currently deployed: `00-exporters` (node-exporter + its `sensors-textfile` sidecar, smartctl-exporter; scraped by kube-prometheus-stack).

doco-cd itself (`docker/nas/.doco-cd/docker-compose.app.yaml`) is **not** self-managed: `just bootstrap nas` places it, and a doco-cd version bump needs that re-run after merging.

### `bootstrap/` and `ansible/` — initial provisioning

`bootstrap/mod.just` orchestrates cluster bring-up (Talos config → K8s bootstrap → kubeconfig → base Secrets/CRDs via `bootstrap/kubernetes/{kustomize,helmfile}` → apps via helmfile) and NAS bootstrap (`bootstrap/docker/nas/bootstrap.yaml`, using `ansible/inventory.yaml`). The helmfiles carry no versions or values of their own: they read each release's chart, version and values from its `kubernetes/apps/<ns>/<app>/app/` manifests, so bootstrap installs exactly what Flux later reconciles. See `bootstrap/README.md` and its per-area READMEs.

### GitOps flow

Renovate (`.renovaterc.json5`, extends `home-operations/renovate-presets`) opens PRs for dependency updates: chart versions, image tags, Talos/K8s versions, mise tools, GitHub Actions.

On a PR, konflate (`kubernetes/apps/flux-system/konflate/`) receives a GitHub webhook, renders the PR with flate, and posts a "Konflate" check plus a rendered-diff comment. Its UI is public at `konflate.${DOMAIN_APP}` (no auth; the repo is public) and internal at `konflate.${DOMAIN_CLUSTER}`.

`.github/workflows/pr-risk.yaml` (every same-repo PR, or `workflow_dispatch` with a PR number) labels a PR's merge risk (`risk/*`). It is advisory and fail-open, and `PR_RISK_MODE` (`shadow` by default, or `comment`) controls what it publishes. Its model, rules and policy live in `.github/scripts/pr-risk/` (see its README).

**Merging to `main` is the deploy.** Flux reconciles `kubernetes/apps` on its own interval, and doco-cd polls and redeploys the `docker/nas` stacks. There is no separate deploy step.

### Secrets

Runtime secrets are never committed in plaintext.

- **Kubernetes:** External Secrets Operator + 1Password Connect (`ClusterSecretStore: onepassword`) create Secrets from `ExternalSecret` resources. A value that must reach `${VAR}` substitution without going into the plaintext `cluster-settings` ConfigMap comes from an ExternalSecret too, via that app's own `substituteFrom` (see `network/cloudflare-tunnel`).
- **Docker Compose:** secrets go under `external_secrets` in `docker/nas/.doco-cd.yaml` as `op://homelab/<item>/<field>` references, resolved at deploy time by doco-cd's 1Password service account and consumed as `${VAR_NAME}`. Its own service-account token and deploy key are placed on the host by `just bootstrap nas`.
- **Locally:** `op` (1Password CLI) serves `just template`, bootstrap and Talos flows via `op inject`.

### Network policies

The cluster runs **without NetworkPolicies**. The CNI is Cilium, but nothing sets a default-deny, and apps don't ship their own policies. Don't add one to a new app unless the user asks.

Flux and Dragonfly follow the same rule: the policies their operators would create are switched off or gone. Don't re-enable them; `kubernetes/apps/flux-system/README.md` and `kubernetes/components/dragonfly/README.md` say what broke.

Why: this is a single-user homelab running trusted workloads, so a compromised pod moving to other services is a small risk. The cost is real, though. Once any policy selects a pod, all other traffic to it in that direction is dropped. Traffic nobody anticipated then times out silently, and operator-generated policies don't appear in Git. Partial coverage gives the costs without the protection. If that trade-off changes, enforce it deliberately: a namespace-wide default-deny plus explicit allow rules for DNS, Prometheus, the gateway and the Kubernetes API, rather than one-off policies.
