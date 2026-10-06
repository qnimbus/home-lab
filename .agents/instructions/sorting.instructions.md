# YAML key order

Applies to every key you write: a new file, or a key added to an existing
file. Don't move existing keys unless the user asks for the file to be
sorted.

- **Alphabetical at every level**, unless a rule below says otherwise.
- **`name` first in a list item** whose items are maps (`- name: cilium`,
  then `localASN`, `peers`). An object reference keeps `apiVersion`, `kind`,
  `name`, `namespace`.
- **Never reorder a Helm values file** (a `values.yaml` fed to a
  `configMapGenerator`), even when asked to sort its folder. The ConfigMap's
  hash changes and triggers a `helm upgrade`, for no functional gain.
- **Never sort YAML embedded in a string** (a config file under
  `configMap.data.*`).
- **The `add-app` templates take precedence**
  (`.agents/skills/add-app/SKILL.md`). Where one orders keys differently (a
  container `securityContext`, an ExternalSecret's `spec` and
  `spec.target`), its order is the convention. That skill lists every case.

## Kubernetes manifests

| Where                                        | Order                                                                                                        |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Top level                                    | `apiVersion`, `kind`, `metadata`, `spec`                                                                     |
| `metadata`                                   | `name`, `namespace`, `annotations`, `labels`                                                                 |
| Any `resources` block (container, CRD field) | `requests`, `limits`                                                                                         |
| ExternalSecret `spec.data[]`                 | `secretKey`, `remoteRef` (a PushSecret's `spec.data[].match` mirrors it)                                     |
| `kustomization.yaml` (Kustomize, not Flux)   | `apiVersion`, `kind`, `namespace`, `components`, `resources`, `configMapGenerator`, `generatorOptions`, rest |
| PrometheusRule rule                          | `alert` or `record`, `expr`, `for`, `keep_firing_for`, `labels`, `annotations`                               |
| ScaledObject `spec.triggers[]`               | `type`, rest                                                                                                 |
| OCIRepository `spec.ref`                     | `tag`, `digest`                                                                                              |
| OCIRepository `spec.verify`                  | `provider`, `matchOIDCIdentity`                                                                              |
| HelmRelease `spec`                           | `interval`, `chartRef`, rest                                                                                 |
| Flux Kustomization `spec` (`ks.yaml`)        | `targetNamespace`, rest, `healthChecks`, `healthCheckExprs`                                                  |

"Rest" is alphabetical.

## HelmReleases on app-template

Only when the sidecar `ocirepository.yaml` has the `url`
`oci://ghcr.io/bjw-s-labs/helm/app-template`. Check that first.

- `spec`: `interval`, `chartRef`, `dependsOn`, rest, `values` last.
- `spec.values`: `defaultPodOptions`, rest.
- Every section under `spec.values`: `enabled`, the section's "First" keys
  (`annotations`, `labels` when it has no row), rest, its "Last" keys.

| Section                                          | First                                                                                  | Last                             |
| ------------------------------------------------ | -------------------------------------------------------------------------------------- | -------------------------------- |
| `controllers.*`                                  | `type`, `annotations`, `labels`, controller-specific (`cronjob`, `statefulset`), `pod` | `initContainers`, `containers`   |
| `controllers.*.containers.*`, `initContainers.*` | `image`                                                                                |                                  |
| `controllers.*.containers.*.probes.*`            | `custom`                                                                               | `spec`                           |
| `service.*`                                      | `type`, `annotations`, `labels`                                                        |                                  |
| `persistence.*`                                  | `type`, `annotations`, `labels`                                                        | `globalMounts`, `advancedMounts` |

The named items under `persistence`, `service`, `configMaps` and the like
(`persistence.config`, `persistence.data`) may be in any order.
