# actions-runner-system

GitHub's [Actions Runner Controller](https://github.com/actions/actions-runner-controller) (ARC) and the repo's one self-hosted runner scale set, `home-lab`. It's a general-purpose runner: CI jobs on it can use `kubectl`, `flux` and `talosctl` against this cluster.

## Apps

| App                         | What it does                                                   | Notes                                                                  |
| --------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `actions-runner-controller` | ARC controller (`gha-runner-scale-set-controller` chart)       | Installs the ARC CRDs; they aren't in the bootstrap CRD phase          |
| `actions-runner-home-lab`   | The `home-lab` runner scale set (`gha-runner-scale-set` chart) | `dependsOn` the controller for those CRDs; scales to zero between jobs |

## How it fits together

- **Which workflows use it.** Image Pull always runs on `home-lab`, since it needs `talosctl`. Renovate, Labeler and Label Sync run on `${{ vars.RUNNER || 'home-lab' }}`, so they can be moved to GitHub-hosted runners while the cluster is down (see Operating).
- **GitHub auth.** The scale set registers as a GitHub App. The 1Password item `actions-runner` holds `APP_ID`, `INSTALLATION_ID` and `PRIVATE_KEY`, which [externalsecret.yaml](./actions-runner-controller/runners/home-lab/externalsecret.yaml) maps onto the key names ARC expects.
- **Jobs** run in Kubernetes container mode: each runner gets a work-volume PVC on `openebs-hostpath`.
- **Talos access** needs no talosconfig in 1Password. The `talos.dev` ServiceAccount in [talos-serviceaccount.yaml](./actions-runner-controller/runners/home-lab/talos-serviceaccount.yaml) makes Talos mint a Secret `home-lab` with a client certificate for role `os:admin`, mounted at `/var/run/secrets/talos.dev`. Talos only does this because `KubeTalosAPIAccessConfig` in [controlplane.yaml.j2](../../talos/controlplane.yaml.j2) allows this namespace and role. `os:admin` is requested because no narrower Talos role is known to cover image pulls.
- **`NODE` is the pod's own host IP**, so `talosctl` targets whichever node the runner landed on. Any node will do: Spegel shares a pulled layer peer-to-peer, so the other nodes fetch it from that one when they need it.

## Operating

```bash
just github runner            # show where RUNNER-aware workflows run
just github runner-hosted     # move them to GitHub-hosted runners (cluster down)
just github runner-cluster    # back to the in-cluster runner
just github prune-secrets     # delete step Secrets left behind by runner pods that died mid-job
```

## Gotchas

- **The runner is cluster-admin, on purpose** ([rbac.yaml](./actions-runner-controller/runners/home-lab/rbac.yaml)). One general-purpose runner replaced a split into scoped runners on 2026-09-06, for simplicity. The cost: Image Pull triggers on `pull_request` and runs here, so a bug in a workflow, or a leaked bot-App key, gets full cluster-admin.
- **Talos access only works when the runner pod lands on a control-plane node.** Talos accepts `KubeTalosAPIAccessConfig` on control planes only, so the runner template's `nodeSelector` keeps runner pods on control planes. Don't drop it: a job on a worker can't reach the Talos API. See [the Talos README](../../talos/README.md).
- The controller's ServiceAccount name is fixed (`serviceAccount.name`) because the scale set refers to it by name in `controllerServiceAccount`. Rename both or neither.
- The two charts must stay on the same version. Renovate bumps them together (the `actions-runner-controller` group in [.renovaterc.json5](../../../.renovaterc.json5)).
- The runner's container hook keeps each container step's env, tokens included, in a Secret labelled `runner-pod=<pod>`, and deletes it only in its own job cleanup. That's why `prune-secrets` exists.
