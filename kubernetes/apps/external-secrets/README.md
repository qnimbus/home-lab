# external-secrets

Where every runtime secret in the cluster comes from. The External Secrets Operator turns `ExternalSecret` resources into Kubernetes Secrets, reading the 1Password `homelab` vault through a 1Password Connect server that runs next to it. Apps reach it through one `ClusterSecretStore`, `onepassword`; [external-secrets.instructions.md](../../../.agents/instructions/external-secrets.instructions.md) says how to write an `ExternalSecret` against it.

## Apps

| Kustomization         | What it does                                                                                          | Notes                                                                    |
| --------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `external-secrets`    | The operator, its admission webhook and its cert-controller                                           | Installs the `external-secrets.io` CRDs. Two replicas of each component. |
| `onepassword-connect` | 1Password Connect: the `api` and `sync` containers in one pod                                         | In-cluster only, no route. Reads `onepassword-connect-secrets`.          |
| `onepassword-store`   | The [`onepassword` ClusterSecretStore](./external-secrets/stores/onepassword/clustersecretstore.yaml) | Lives in `external-secrets/ks.yaml`, after the operator.                 |

## How it fits together

```text
ExternalSecret ─▶ operator ─▶ ClusterSecretStore onepassword ─▶ onepassword-connect:8080 ─▶ 1Password
PushSecret     ─▶ operator ─▶                  (same path, writing)
```

- **The one Secret that can't come from an `ExternalSecret`** is `onepassword-connect-secrets`: Connect's credentials file and the access token the store authenticates with. Bootstrap creates it from 1Password with `op inject` ([secrets.yaml](../../../bootstrap/kubernetes/kustomize/manifests/external-secrets/secrets.yaml)). Flux doesn't manage it, so nothing in this folder recreates or rotates it.
- **Bootstrap installs this namespace before Flux exists**, from the same files Flux reconciles later: both releases from their `app/` folder, then the ClusterSecretStore with a plain `kubectl apply` ([apps.yaml](../../../bootstrap/kubernetes/helmfile/apps.yaml)). Flux itself needs a secret from 1Password to start.
- **`onepassword-store` is a second Kustomization** because Flux dry-runs everything in a Kustomization before applying any of it, and the `ClusterSecretStore` CRD only exists once the operator's chart is installed.

Other apps don't `dependsOn` anything here; see [flux-kustomization.instructions.md](../../../.agents/instructions/flux-kustomization.instructions.md).

## Operating

```bash
kubectl get clustersecretstore onepassword                 # Ready = Connect reachable and the token valid
kubectl get externalsecret -A | grep -v SecretSynced       # everything that isn't synced
just k8s sync es                                           # force-sync every ExternalSecret
just k8s sync-es <ns> <name>                               # force-sync one
kubectl -n external-secrets logs deploy/onepassword-connect -c connect-api
```

To see what reads a 1Password item: `grep -rn -A5 "key: <item>" kubernetes`.

## Gotchas

- **Keep `leaderElect: true` while the operator has two replicas.** Without it both replicas reconcile. A `PushSecret` to 1Password is "find the item by title, else create it", which isn't atomic, so two replicas pushing an item that doesn't exist yet each create one and leave duplicates in the vault. With it only the leader reconciles, which also halves the calls to Connect. When the leader pod goes away, new syncs and pushes wait for the lease to move (about 15s); Secrets that are already synced are unaffected.
- **The second replica is there for node failures.** Each component's two pods are forced onto different nodes (`topologySpreadConstraints` with `DoNotSchedule`), so losing a node leaves a webhook serving admission and a standby operator ready. The spread is per component, not across the three: `matchLabelKeys: pod-template-hash` narrows the shared `app.kubernetes.io/instance` selector to one ReplicaSet, so one node can hold a pod of each.
- **Connect logs at `warn`.** At the chart's `info` it logs every request, the kubelet's probes included, which dominates this namespace's log volume. `warn` still shows authentication and upstream errors. Set it back to `info` in [values.yaml](./onepassword-connect/app/helm/values.yaml) when debugging a lookup.
- **Connect is a single replica**, and every sync goes through it. While it is down, existing Secrets stay as they are; new and changed `ExternalSecret`s wait and retry.
- **`onepassword-store` keeps `wait: true` although nothing depends on it.** It makes the Kustomization not Ready while the store is, so a broken store (Connect unreachable, token rejected) reaches Alertmanager through the namespace's Flux Alert. Nothing else alerts on the store. Flux only looks when it reconciles, so this can lag by up to its interval.
- **The `onepassword-connect` release is labelled `crds.flux.home.arpa/disabled`.** The chart ships the 1Password operator's `OnePasswordItem` CRD in `crds/`, and the operator isn't installed. Bootstrap's helmfile doesn't read the label and installs the CRD on a fresh cluster; it is unused there too.
- **All three Kustomizations carry `substitution.flux.home.arpa/disabled`.** Bootstrap reads these files verbatim, so a `${VAR}` here would work under Flux and break the next bootstrap. Don't add one; see [clusters/README.md](../../clusters/README.md).
- **The operator's CRDs are templated without `helm.sh/resource-policy: keep`**, so uninstalling, renaming or moving the `external-secrets` release deletes every `ExternalSecret` and `PushSecret` in the cluster. That is an accepted exception ([helm-crds.instructions.md](../../../.agents/instructions/helm-crds.instructions.md)): Flux re-applies them and the operator refills the Secrets. Use the `helm-crds` skill before touching the release.
- **A wrong key in a `target.template` renders an empty value, with no error.** The `ExternalSecret` still reports `SecretSynced`. Check the Secret's content, not its status.
