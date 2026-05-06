# Home Lab — Cluster Roadmap

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

---

## In Progress

_(nothing currently in progress)_

---

## Pending

### External Secrets + 1Password Connect

Deploy [External Secrets Operator](https://external-secrets.io/) and a [1Password Connect](https://developer.1password.com/docs/connect/) server so that application secrets can be pulled from 1Password at runtime without ever touching Git.

Rough steps:
- Deploy 1Password Connect server (HelmRelease in `kubernetes/apps/`)
- Deploy External Secrets Operator (HelmRelease, likely `external-secrets` namespace)
- Create a `ClusterSecretStore` pointing to the Connect server
- Validate with a test `ExternalSecret` before wiring up real app secrets

Dependency chain: `cert-manager` → `external-secrets` → `onepassword-connect` → apps

---

### Configure Renovate dependency management

Set up [Renovate](https://docs.renovatebot.com/) to automatically open PRs for version bumps across the repo.

Rough steps:
- Add `renovate.json` (or `renovate.json5`) at the repo root with a base config
- Verify `# renovate: datasource=...` annotations in `talenv.yaml` and Helmfile lock files are picked up
- Ensure Helm chart versions in `kubernetes/` HelmReleases are tracked
- Configure automerge policy (e.g. patch-level digest bumps for trusted sources)

---

## Completed

| Area                          | Notes                                           |
|-------------------------------|-------------------------------------------------|
| Talos machine configs         | 3 CP nodes, patches, schematic registered       |
| Bootstrap go-task Taskfile    | Replaces scripts/bootstrap.sh                   |
| SOPS age key + rules          | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | All bootstrap steps complete                    |
| kubernetes/ directory         | Helmfile + Flux structure in place              |
| Cilium                        | Running via Helmfile bootstrap                  |
| CoreDNS                       | Running via Helmfile bootstrap                  |
| cert-manager                  | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | Reconciling from private repo via SSH           |
