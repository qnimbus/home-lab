# YAML key order

These rules apply to every key you write: a new file, or a key added to an
existing file (put it where the rules place it). Don't move keys that are
already there unless the user asks for the file to be sorted.

- **Default: alphabetical at every level**, however deeply nested, unless a
  rule below or in another instructions file says otherwise.
- **`name` comes first in a list item.** When the items of a list are maps
  with a `name` key, `name` leads and the rest follows alphabetically
  (`- name: cilium`, then `localASN`, `peers`). The exception is an object
  reference (`apiVersion`, `kind`, `name`, `namespace`, as in a
  `healthChecks` entry), which keeps that order.
- **Never reorder a Helm values file**, even when asked to sort its folder.
  This is a `values.yaml` fed to a `configMapGenerator`: any change to it
  changes the ConfigMap's hash and triggers a `helm upgrade` of the
  release, for no functional gain.
- **YAML embedded in a string is never sorted** (e.g. a config file under
  `configMap.data.*`).
- **The `add-app` skill's templates take precedence**
  (`.agents/skills/add-app/SKILL.md`). Where a template orders keys
  differently, as in a container `securityContext` or an ExternalSecret's
  `spec` and `spec.target`, the template's order is the convention. That
  skill lists every such case.

## Kubernetes manifests

- Top level: `apiVersion`, `kind`, `metadata`, `spec`.
- `metadata`: `name`, `namespace`, `annotations`, `labels`.
- Any `resources` block (container resources in a manifest, chart values, a
  CRD field such as kopiur's `moverDefaults`): `requests` before `limits`.
- An ExternalSecret's `spec.data` entries: `secretKey` before `remoteRef`.
  A `PushSecret`'s `spec.data[].match` mirrors that order.
- An `OCIRepository`'s `spec.ref`: `tag` before `digest`.
- An `OCIRepository`'s `spec.verify`: `provider` before `matchOIDCIdentity`.
- A `HelmRelease`'s `spec`: `interval` first, then `chartRef`, then the rest
  alphabetically. app-template releases refine this below.
- A Flux `Kustomization`'s `spec` (`ks.yaml`): `targetNamespace` first, then
  the rest alphabetically, then `healthChecks` and `healthCheckExprs` last,
  in that order.

## HelmReleases on app-template

Only for a HelmRelease whose sidecar `ocirepository.yaml` has a `url` of
`oci://ghcr.io/bjw-s-labs/helm/app-template`. Check that first; other
HelmReleases follow the rules above.

- `spec`: `interval`, `chartRef`, `dependsOn`, any other key alphabetically
  (`driftDetection`, `install`, `postRenderers`, `upgrade`), `values` last.
- `spec.values`: `defaultPodOptions` first, then alphabetical
  (`controllers`, `persistence`, `service`).
- Within every section under `spec.values`: `enabled` first, then the
  section's "First" keys from the table (`annotations`, `labels` when the
  section has no row), then the remaining keys alphabetically, then its
  "Last" keys.

| Section                                          | First                                                                                  | Last                             |
| ------------------------------------------------ | -------------------------------------------------------------------------------------- | -------------------------------- |
| `controllers.*`                                  | `type`, `annotations`, `labels`, controller-specific (`cronjob`, `statefulset`), `pod` | `initContainers`, `containers`   |
| `controllers.*.containers.*`, `initContainers.*` | `image`                                                                                |                                  |
| `service.*`                                      | `type`, `annotations`, `labels`                                                        |                                  |
| `persistence.*`                                  | `type`, `annotations`, `labels`                                                        | `globalMounts`, `advancedMounts` |

The named items under `persistence`, `service`, `configMaps` and
the like (`persistence.config`, `persistence.data`) may be in any order.
Only the keys within each item are sorted.
