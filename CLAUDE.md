# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Repository overview

This is a personal home infrastructure monorepo, not an application. It manages a bare-metal Talos/Kubernetes cluster (GitOps via Flux), Docker Compose stacks on a TrueNAS host (GitOps via doco-cd), and the Ansible/Talos/just tooling used to bootstrap and operate all of it. There is no app to build or test in the traditional sense — "correctness" means manifests render and lint cleanly; validation happens via `kustomize build`, `yamllint`, `flux-schema` (the `gitops-repo-audit` skill's vendored `scripts/validate.sh`), `kubeconform`, `actionlint`, `zizmor`, and `shellcheck`, split between lefthook pre-commit hooks and GitHub Actions (`.github/workflows/validate.yaml`); rendered PR diffs come from konflate, running in-cluster.

Tool versions are pinned via mise (`.mise/config.toml`); `mise install` provisions `just`, `flux2`, `flux-operator`, `kubectl`, `kustomize`, `helm`, `helmfile`, `talos`, `1password-cli`, `sops`/`age`, `flate`, `minijinja`, `ansible`, `yq`, etc. mise also sets `KUBECONFIG`, `TALOSCONFIG`, and `FLATE_PATH` to repo-local paths. `mise`'s `postinstall` hook runs `lefthook install` and installs the Ansible collections from `ansible/requirements.yaml`.

## Commands

`just` (from `.justfile`) is the command runner; it imports modules as `mod`s, so most recipes are namespaced:

```bash
just                             # list all recipes/groups
just k8s <recipe>                # kubernetes/mod.just — day-2 cluster operations
just k8s database <recipe>       # kubernetes/apps/database/mod.just — CNPG dump/restore
just talos <recipe>              # kubernetes/talos/mod.just — Talos node operations
just bootstrap <recipe>          # bootstrap/mod.just — end-to-end bring-up
just docker <recipe>             # docker/mod.just — NAS doco-cd operations
just github <recipe>             # .github/mod.just — `RUNNER` repo variable: runner | runner-cluster | runner-hosted
```

Frequently used `just k8s` recipes: `sync hr|ks|gitrepo|ocirepo|es` (force Flux/ExternalSecrets reconciliation), `sync-hr`/`sync-ks`/`sync-es <ns> <name>` (single resource), `apply-ks`/`delete-ks <ns> <ks>` (render+apply/delete a Flux Kustomization locally via `flate`), `toolbox` (shell into rook-ceph-tools), `view-secret <ns> [secret]`, `browse-pvc <ns> <claim>`, `debug-node <node>`, `db-backup <ns> <app>` (manual CNPG backup of a dedicated `<app>-postgres` cluster), `prune-pods`, `cron-minute <name>` (stable pseudo-random cron minute). `just k8s database dump|restore` wraps `pg_dump`/`pg_restore` against a CNPG cluster.

Frequently used `just talos` recipes: `apply-node`, `render-config`, `upgrade-node`, `upgrade-k8s`, `reboot-node`, `health`, `nodes`, `disks`, `gen-talosconfig` (disaster recovery from 1Password).

`just bootstrap cluster` runs the full sequence: apply Talos config to nodes → bootstrap Kubernetes → fetch kubeconfig → apply base manifests/CRDs (kustomize + helmfile) → sync apps helmfile → fetch kubeconfig again. `just bootstrap nas` runs the Ansible playbook that (re)deploys doco-cd on TrueNAS. `just docker reconcile-nas` restarts doco-cd on the NAS via Ansible.

### Validating a single Kubernetes app

```bash
kustomize build kubernetes/apps/<namespace>/<app>/app     # must render (${APP}-style vars staying literal is expected)
yamllint --config-file .yamllint.yaml kubernetes/apps/<namespace>/<app>
```

### Validating a single Docker Compose stack

```bash
docker compose -f docker/nas/NN-<app>/docker-compose.yaml config --quiet   # unset ${VAR} warnings are expected
```

### Pre-commit hooks (lefthook, `.lefthook.yaml`)

Run automatically on `git commit`, staged-file-scoped: `mise fmt`, `mise lock` (regenerates `.mise/mise.lock` for `linux-x64,linux-arm64,macos-arm64`), `oxfmt` for JSON/Markdown/YAML (`*.sops.yaml` excluded) followed by `yamllint` on the formatted YAML (`.yamllint.yaml`; its `braces`/`quoted-strings` rules are set to agree with oxfmt), `shellcheck` for `*.sh`, `actionlint` and `zizmor` for GitHub Actions workflows/actions, and Renovate's `renovate-config-validator` for `renovate.json5` (also run in CI via `lefthook run`).

## Architecture

### `kubernetes/` — Flux-managed cluster state

`kubernetes/clusters/main/apps.yaml` defines one top-level Flux `Kustomization`, `cluster-apps`, which points at `./kubernetes/apps` and recurses: it finds the top-most `kustomization.yaml` in each app directory and applies everything it references.

`cluster-apps` injects cluster-wide defaults via Kustomize patches onto _every_ Kustomization/HelmRelease it manages, so individual apps don't repeat that boilerplate:

- `postBuild.substituteFrom` the `cluster-settings` ConfigMap, looked up in the Kustomization's own namespace (it comes from `components/cluster-settings`, which every namespace's `kustomization.yaml` pulls in) — opt out with `substitution.flux.home.arpa/disabled: "true"`, but only for an app with its own `substituteFrom` (the patch replaces the whole list) or one whose files bootstrap reads verbatim (see `kubernetes/clusters/README.md`).
- default `retryInterval: 2m`/`timeout: 15m`, and `deletionPolicy: WaitForTermination`: deleting a Kustomization deletes its resources and waits (up to `timeout`) until they're actually gone. It deletes even with `prune: false`, so moving an app without losing its data still needs a temporary `deletionPolicy: Orphan` patched onto the old live Kustomization first.
- HelmRelease install/upgrade `CreateReplace`/`RetryOnFailure`/`RemediateOnFailure` strategy, and `driftDetection: enabled` (opt out with `drift-detection.flux.home.arpa/disabled: "true"`).
- a label-driven patch: a Flux Kustomization tagged `components.postgres/cnpg=init` gets its CNPG `Cluster` rewritten to a plain `initdb` bootstrap instead of Barman recovery, for brand-new databases with no prior backup.

Each namespace directory (`kubernetes/apps/<namespace>/kustomization.yaml`) lists its own `namespace.yaml` (the Namespace, with `kustomize.toolkit.fluxcd.io/prune: disabled` and any namespace-specific labels such as PodSecurity levels) first in `resources`, pulls in `components/cluster-settings`, and sets `namespace: <namespace>`, which stamps `metadata.namespace` onto every child Flux Kustomization — so `ks.yaml` files don't set that themselves. Each `ks.yaml` does set `spec.targetNamespace` explicitly, to its namespace directory. **Exception: `flux-system`** has no `namespace.yaml`. The namespace comes from bootstrap, and a `namespace.yaml` would make Flux manage the `flux-system` Namespace itself. Don't "fix" this by adding one.

Each app lives at `kubernetes/apps/<namespace>/<app>/`:

```text
<app>/
├── ks.yaml                # Flux Kustomization — path, dependsOn, postBuild.substitute (APP etc.), optional components
└── app/
    ├── kustomization.yaml
    ├── ocirepository.yaml     # pins the chart version (app-template: oci://ghcr.io/bjw-s-labs/helm/app-template)
    ├── helmrelease.yaml       # values: controllers/service/route/persistence, built on bjw-s-labs/app-template
    ├── httproute.yaml         # optional — Gateway API route
    ├── externalsecret.yaml    # optional — pulls 1Password fields via the `onepassword` ClusterSecretStore
    └── resources/             # optional — files wired in via configMapGenerator
```

`kubernetes/components/` holds reusable kustomize components: `cluster-settings` (per-namespace wiring above; it also pulls in `alerts`), `alerts` (a Flux `Provider` + `Alert` per namespace that sends Flux errors to Alertmanager — an `Alert` only sees its own namespace, see its README), `postgres` (a dedicated CNPG cluster per app, parameterized via the consuming `ks.yaml`'s `postBuild.substitute` — see its README), `dragonfly` (a dedicated Dragonfly per app, `${APP}-dragonfly`, plus an optional `authentication` sub-component; the operator lives in `apps/database/dragonfly`), `keda/*` (`http-scaler`, `smb-scaler`), and `nfs-config`. `kubernetes/talos/` holds Talos machine-config Jinja templates (rendered with `minijinja-cli` + 1Password `op inject`, see `.justfile`'s `template` recipe) and `version.yaml` (pinned Talos/Kubernetes versions used by `kubernetes/talos/mod.just`).
Scaffolding a new cluster app should follow the `add-app` skill (`.agents/skills/add-app/SKILL.md`) — mirror a recent real app in this repo rather than inventing structure.

### `docker/` — Compose stacks on the TrueNAS host

Deployed GitOps-style by [doco-cd](https://github.com/kimdre/doco-cd), which runs on TrueNAS itself, polls this repo's `main` over a read-only SSH deploy key, and auto-discovers one-directory-deep stacks under `docker/nas/` (config: `docker/nas/.doco-cd.yaml`). Each stack is `docker/nas/NN-<app>/docker-compose.yaml` with image tags inline (Renovate's native `docker-compose` manager tracks them); the `NN-` prefix is ordering only — renaming/renumbering a directory deletes and recreates the stack (including anonymous volumes), so keep it stable. Currently deployed: `00-exporters` (node-exporter + its `sensors-textfile` sidecar, smartctl-exporter; scraped by kube-prometheus-stack). doco-cd itself (`docker/nas/.doco-cd/docker-compose.app.yaml`) is **not** self-managed: `just bootstrap nas` places it, and a doco-cd version bump needs that re-run after merging. Compose-level secrets go under `external_secrets` in `docker/nas/.doco-cd.yaml` as `op://homelab/<item>/<field>` references, resolved by doco-cd's 1Password service account and consumed as `${VAR_NAME}`.

### `bootstrap/` and `ansible/` — initial provisioning

`bootstrap/mod.just` orchestrates cluster bring-up end to end (Talos config → K8s bootstrap → kubeconfig → base Secrets/CRDs via `bootstrap/kubernetes/{kustomize,helmfile}` → apps via helmfile) and NAS bootstrap (`bootstrap/docker/nas/bootstrap.yaml`, using `ansible/inventory.yaml`). The helmfiles carry no versions or values of their own: they read each release's chart, version and values from its `kubernetes/apps/<ns>/<app>/app/` manifests, so bootstrap installs exactly what Flux later reconciles. `bootstrap/README.md` and its per-area READMEs document the process.

### `.agents/` — shared agent conventions

`AGENTS.md` imports the files in `.agents/instructions/`: YAML key ordering (`sorting`), Flux Kustomization `dependsOn`/`commonMetadata` rules (`flux-kustomization`), Helm chart source placement, OCI only (`helm-sources`), keeping Helm-templated CRDs on uninstall and what that costs (`helm-crds`), ExternalSecret patterns (`external-secrets`), when to use `# renovate:` comments (`renovate`), and which `yaml-language-server` schema URL each manifest carries (`yaml-schemas`). These apply whenever YAML in this repo is written or reordered. `.agents/skills/` holds task skills (`add-app`, `check-cluster-health`, `review-gitops-practices`, `tidy-folder`, …); they're exposed to Claude Code through the `.claude/skills` symlink.

### GitOps flow

Renovate watches the repository for dependency updates (chart versions, image tags, Talos/K8s versions, tool versions in `.mise/config.toml`, GitHub Actions, compose `.env` tags, etc.) and opens PRs (`.renovaterc.json5`, extends `config:recommended`). On PRs, konflate (`kubernetes/apps/flux-system/konflate/`) receives a GitHub webhook, renders the PR with flate, and posts a "Konflate" check plus a rendered-diff comment; its UI is internal-only at `konflate.${DOMAIN_CLUSTER}`. `.github/workflows/pr-risk.yaml` (manual `workflow_dispatch` with a PR number, for now) classifies a PR's merge risk (`risk/*` labels) from git facts, path tiers, Konflate's structured signals and TypeSafe's Jev model. It's advisory and fail-open: code decides, the model can only raise the level. `PR_RISK_MODE` (`shadow` by default) controls whether it publishes, and its path tiers and thresholds live in `.github/scripts/pr-risk/` (see its README). Merging to `main` is what actually changes cluster/NAS state: Flux reconciles `kubernetes/apps` on its own interval, and doco-cd polls and redeploys the `docker/nas` stacks. There is no separate "deploy" step — pushing to `main` is the deploy.

### Secrets

Runtime secrets are never committed in plaintext. In Kubernetes, External Secrets Operator + 1Password Connect (`ClusterSecretStore: onepassword`) inject them as Kubernetes Secrets from `ExternalSecret` resources. A value that must reach `${VAR}` substitution without going into the plaintext `cluster-settings` ConfigMap comes from an ExternalSecret too, via that app's own `substituteFrom` (see `network/cloudflare-tunnel`). In Docker Compose land, doco-cd resolves `op://` references declared in `docker/nas/.doco-cd.yaml` at deploy time; its own service-account token and deploy key are placed on the host by `just bootstrap nas`. `op` (1Password CLI) is also used locally for `just template`/bootstrap/Talos flows via `op inject`.

### Network policies

The cluster runs **without NetworkPolicies by default**. The CNI is Cilium, but nothing sets a default-deny, and apps don't ship their own policies. Don't add one to a new app unless the user asks.

- **Flux:** `flux-system` follows the same rule. flux-operator's built-in policies are switched off (`instance.cluster.networkPolicy: false` in `flux-instance`, `web.networkPolicy.create: false` in `flux-operator`). They allowed cross-namespace ingress only on port 8080, which silently blocked Prometheus from scraping konflate on 8081. konflate's GitHub webhooks only worked because they also happen to arrive on 8080.
- **Dragonfly (the one exception):** the Dragonfly operator generates a restrictive policy for every instance (`${APP}-dragonfly`, owned by the `Dragonfly` CR). `components/dragonfly` adds `${APP}-dragonfly-allow-metrics` so Prometheus can still scrape port 9999. Any new port that needs to reach those pods needs a similar allow rule next to it.

Why: this is a single-user homelab running trusted workloads, so the main thing policies would protect against (a compromised pod moving to other services) is a small risk. The cost is real, though. Once any policy selects a pod, all other traffic to it in that direction is dropped. Traffic nobody anticipated then times out silently instead of erroring, and operator-generated policies don't appear in Git, so reviewing the repo won't reveal them. Partial coverage gives the costs of NetworkPolicies without the protection. If that trade-off changes, enforce it deliberately: a namespace-wide default-deny plus explicit allow rules for DNS, Prometheus, the gateway and the Kubernetes API, rather than one-off policies.
