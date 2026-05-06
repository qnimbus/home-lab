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

### Talos + Kubernetes Upgrade Strategy

Research and implement a repeatable upgrade path for Talos Linux and Kubernetes. Renovate intentionally does not track these versions — a dedicated mechanism is needed.

Options to evaluate:
- **[system-upgrade-controller](https://github.com/rancher/system-upgrade-controller)** (SUC) — runs as a DaemonSet; applies Talos upgrades node-by-node via `Plan` CRDs; already referenced in `CLAUDE.md` as the intended upgrade path
- **Manual `talosctl upgrade` + `talosctl upgrade-k8s`** — imperative, full control, lower automation; suitable until SUC is deployed
- **Renovate + `allowedVersions` fence** — re-enable Talos/k8s tracking in Renovate but gate on a `allowedVersions` constraint so PRs are informational only; operator still applies the upgrade manually

Rough steps (if going SUC route):
- Deploy `system-upgrade-controller` as a HelmRelease in `system-upgrade` namespace
- Grant the controller Talos API access (ServiceAccount + RBAC in `system-upgrade` namespace — already noted in `CLAUDE.md`)
- Define `Plan` CRDs for Talos upgrades (referencing `factory.talos.dev` installer image) and Kubernetes upgrades
- Test single-node cordon/drain/upgrade cycle before rolling out to all three CPs

Dependency chain: cluster stable → `system-upgrade-controller` → Talos `Plan` → k8s `Plan`

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
| Renovate                      | `renovate.json5` in place; GitHub App installed; Talos/k8s versions intentionally excluded (managed separately) |
