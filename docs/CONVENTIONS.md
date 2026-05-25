# GitOps Conventions — Extended Reference

Supplement to [CLAUDE.md](../CLAUDE.md). See CLAUDE.md for structural rules: Kustomization layout, naming, dependency ordering, multi-document `ks.yaml`, and `crds: CreateReplace`.

---

## Documentation comments in YAML resources

All cluster YAML files (Talos patches, HelmRelease values, StorageClasses, Kustomizations, node configs) should carry comments that explain the *why*, not the *what*. The resource name and field names already say what — comments are for context that would otherwise be lost.

**Always comment:**
- Non-default values, especially when deviating from upstream chart defaults — explain the reason
- Provisional settings that need to change later (e.g. replica counts awaiting hardware) — include the trigger condition: `# 2 replicas until talos-cp-02 storage disk installed; bump to 3 when ready`
- Workarounds for known bugs or cluster-specific constraints — include a reference if one exists
- StorageClass and PersistentVolume resources — explain the intended use case and any operational implications (e.g. manual PV cleanup required for Retain policy)
- Values that look wrong but are intentional (e.g. `allowScheduling: false` on a node, `isDefaultClass: false` on a provisioner)

**Do not comment:**
- Fields whose purpose is self-evident from the field name and value
- Boilerplate that every Kubernetes resource has (`apiVersion`, `kind`, `metadata.name`)
- Comments that restate the YAML in prose ("sets the replica count to 2")

---

## app-template v5 (bjw-s/app-template)

Most application HelmReleases in this repo use the `bjw-s/app-template` OCIRepository
(`ghcr.io/bjw-s-labs/helm/app-template`, currently `5.x`). This is a generic **library chart** —
it provides a schema for deploying any containerised app, not an application itself.

**Current version: 5.x** — write all new app values against this schema. Do not copy values
from v4 examples found in the community; the schemas are incompatible in several areas.

### Key v5 rules

- **`rawResources`** — each raw manifest must be nested under a `manifest:` key:
  ```yaml
  rawResources:
    my-resource:
      manifest:
        apiVersion: ...
        kind: ...
        metadata: ...
  ```
  Omitting `manifest:` silently produces an invalid resource (v4 behaviour).

- **Default ServiceAccount** — a ServiceAccount is automatically created for each controller.
  Disable with `global.createDefaultServiceAccount: false` if not needed.

- **`automountServiceAccountToken`** — defaults to `false` (security improvement).
  Apps that need K8s API access must explicitly opt in:
  ```yaml
  defaultPodOptions:
    automountServiceAccountToken: true
  ```

- **`NetworkPolicy`** — `controller` and `podSelector` are mutually exclusive; set only one.

- **`ServiceMonitor` / `PodMonitor`** — `jobLabel` defaults to `app.kubernetes.io/name`
  (was metadata name in v4). Adjust Grafana dashboards or PrometheusRule selectors accordingly.

Full schema reference: [bjw-s app-template docs](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)

---

## Drift Detection

All HelmReleases get `driftDetection: { mode: enabled }` by default via the global `cluster-apps`
patch (`kubernetes/flux/cluster/ks.yaml`). Flux detects and reverts any out-of-band mutation to
Helm-managed resources on every reconciliation interval — `kubectl edit`, operator mutations, manual
`helm upgrade`, accidental deletes.

### Opt-out label

To fully disable drift detection on a specific HelmRelease, add this label to the **HelmRelease**
resource (not the Kustomization):

```yaml
metadata:
  labels:
    driftDetection.flux.home.arpa/disabled: "true"
```

Use this only when an external controller **writes to `.spec` fields** of Helm-managed resources
(not just `.status`). Examples: VPA mutating `resources.requests`, a custom operator that
self-tunes its own CRD spec.

### Ignore rules (preferred over full opt-out)

For targeted exclusions — where drift detection should stay on but skip specific paths — add
`spec.driftDetection.ignore` directly to the HelmRelease YAML. These rules **survive the global
patch** (the patch only writes `mode`; `ignore` is a different sub-field under strategic merge).

```yaml
spec:
  driftDetection:
    # mode: not needed — injected by global patch
    ignore:
      - paths: ["/spec/replicas"]
        target:
          kind: Deployment
      - paths: ["/spec/resources/requests/cpu", "/spec/resources/requests/memory"]
        target:
          kind: Deployment
```

Common `ignore` scenarios:

| Controller | Path to ignore | Why |
|---|---|---|
| HPA | `/spec/replicas` on `Deployment`/`StatefulSet` | HPA owns the replica count |
| VPA | `/spec/*/resources/requests` on `Deployment` | VPA mutates resource requests at runtime |
| Kubernetes auto-assign | `/spec/ports/*/nodePort` on `Service` | Kubernetes assigns nodePort; Flux would clear and re-assign a different port |
| Mutating webhook | `/metadata/annotations` or `/metadata/labels` on target resource | Webhook injects annotations Flux doesn't know about |

### What drift detection does NOT watch

Drift detection only tracks **Helm-managed resources** (those with helm-controller's server-side
apply field ownership). Pods, EphemeralRunners, and any resource created by a subordinate
controller are outside Flux's ownership graph and are never reverted.

---

## Community research before new deployments

Before planning any new application deployment or writing a new Kustomization, search **[kubesearch.dev](https://kubesearch.dev/)** for the chart or app name. This indexes public home-lab GitOps repos and surfaces real-world `HelmRelease`, `values.yaml`, and `ExternalSecret` patterns used by other home labbers running the same stack (Talos + Flux + Cilium).

Use findings as **research input only** — verify against upstream docs, understand *why* each value is set, and adopt only what fits this cluster's hardware and constraints. Community configs carry others' baggage; treat them as data points, not templates.
