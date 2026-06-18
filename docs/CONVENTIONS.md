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
    drift-detection.flux.home.arpa/disabled: "true"
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

## ExternalSecret conventions

All `ExternalSecret` resources in this repo must use the `dataFrom.extract` + `rewrite.regexp`
pattern rather than listing individual `data` entries. This keeps 1Password item fields short and
prefix-free while the resulting Kubernetes Secret keys carry the application prefix.

### Pattern

```yaml
spec:
  dataFrom:
    - extract:
        key: <1password-item-name>
      rewrite:
        - regexp:
            source: (.*)
            target: APP_$1   # adds APP_ prefix to every extracted field
```

With this pattern, a 1Password field named `API_KEY` becomes `APP_API_KEY` in the Kubernetes
Secret. Name 1Password fields **without** the application prefix — the rewrite adds it.

### When to add a `template` block

If the application's expected env var names don't all share a single prefix (or differ in any
other way from the rewritten key names), add a `template` section to remap:

```yaml
spec:
  target:
    template:
      engineVersion: v2   # required for {{ .KEY }} syntax
      data:
        EXPECTED_KEY_NAME: "{{ .PREFIXED_KEY }}"
```

The template runs **after** the rewrite — reference keys by their post-rewrite names. Always set
`engineVersion: v2`; the v1 default uses a different interpolation format and is deprecated.

See `kubernetes/apps/tailscale/tailscale-operator/app/externalsecret.yaml` for a live example of
this pattern with both `rewrite` and `template`.

### 1Password field naming

Name fields in the 1Password item without any application-specific prefix. Examples for an app
named `myapp`:

| 1Password field | Kubernetes Secret key (after `MYAPP_$1` rewrite) |
|---|---|
| `API_KEY` | `MYAPP_API_KEY` |
| `DASHBOARD_USERNAME` | `MYAPP_DASHBOARD_USERNAME` |
| `DASHBOARD_PASSWORD` | `MYAPP_DASHBOARD_PASSWORD` |

---

## Cluster-wide variables (cluster-settings)

`kubernetes/flux/vars/cluster-settings.yaml` is a `ConfigMap` in `flux-system` that holds cluster-scoped values. The `cluster-apps` Kustomization injects it via `postBuild.substituteFrom` into every child Kustomization (unless the Kustomization carries `substitution.flux.home.arpa/disabled: "true"`). Variables are available as `${VAR_NAME}` placeholders in **any YAML file** the Kustomization manages — including HelmRelease manifests.

### Current variables

| Key | Value | Use for |
|---|---|---|
| `CLUSTER_NAME` | `home-lab` | App labels, dashboard titles |
| `CLUSTER_TIMEZONE` | `Europe/Amsterdam` | Container `TZ` env var |

### Rules

- **Use `${CLUSTER_TIMEZONE}` instead of hardcoding a timezone string** in any HelmRelease `env:` block. Every container that honours `TZ` should reference this variable — one place to change the cluster timezone.
- **Never hardcode `Europe/Amsterdam`** (or any other cluster-specific literal that already has a `cluster-settings` entry) directly in app manifests.
- To add a new cluster-wide value, add it to `cluster-settings.yaml` and document it in the table above.
- Variable substitution does **not** apply to Kustomizations labeled `substitution.flux.home.arpa/disabled: "true"` — check before adding `${…}` syntax to resources managed by such a Kustomization.

---

## CRD bootstrap pattern — raw monitoring and gateway manifests

Flux's kustomize-controller performs a **server-side dry-run** against every resource
in a Kustomization path before applying any of them.  If a resource uses a CRD that
does not yet exist on the API server, the entire Kustomization fails:

```
no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
ensure CRDs are installed first
```

### The wrong fix — `dependsOn: kube-prometheus-stack`

Adding `dependsOn: kube-prometheus-stack` to every app that contains a `ServiceMonitor`
is wrong for two reasons:
1. It means the app cannot deploy on a vanilla cluster without Prometheus.
2. It creates circular dependency risks (e.g. `kube-prometheus-stack` depends on
   `rook-ceph-cluster` for PVC storage; if Ceph's operator also depends on Prometheus,
   nothing starts).

### The correct fix — CRD pre-bootstrap phase

`bootstrap/helmfile.d/00-crds.yaml` runs **before** Flux reconciles anything.
It renders each chart with `--include-crds` and filters the output to CRDs only via a
`yq` post-renderer, installing zero controllers:

```yaml
helmDefaults:
  args: [--include-crds, --no-hooks]
  postRenderer: bash
  postRendererArgs: [-c, "yq ea --exit-status 'select(.kind == \"CustomResourceDefinition\")' -"]
```

The bootstrap task invokes it as:

```sh
helmfile -f helmfile.d/00-crds.yaml template --quiet \
  | yq ea 'select(.kind == "CustomResourceDefinition")' \
  | kubectl apply --server-side -f -
```

`helmfile template` (not `sync`) renders the charts without writing Helm release
Secrets — so no namespace needs to exist yet.  The `yq` filter is applied in the
shell pipeline rather than as a Helm post-renderer (Helm 4 requires post-renderers
to be registered plugins, not arbitrary executables).  `--server-side` ensures the
apply is idempotent across re-bootstraps.  By the time Flux first reconciles,
`monitoring.coreos.com/v1` and `gateway.networking.k8s.io/v1` CRDs are already
registered — dry-run passes everywhere.

### Which charts belong in `00-crds.yaml`

Add a chart when **all three** conditions hold:
1. The chart is **managed by Flux** (not in `01-apps.yaml`).
2. The chart installs CRDs.
3. A Kustomization path that runs **before** this chart is deployed contains a **raw
   manifest** of that CRD kind (a `ServiceMonitor.yaml`, `HTTPRoute.yaml`, etc.).

Do **not** add charts whose CRDs are consumed only by Kustomizations that already
`dependsOn` the chart's own Kustomization (e.g. `rook-ceph-cluster` depends on
`rook-ceph-operator` — the sequencing is already correct without a CRD pre-install).

### Version pinning

The version in `00-crds.yaml` **must match** the corresponding
`kubernetes/flux/meta/repos/oci/<chart>.yaml` OCIRepository tag.  Both carry identical
`# renovate: datasource=docker` comments so Renovate bumps them in the same PR.

### Kustomizations with Helm-rendered ServiceMonitors

Some HelmReleases (e.g. `metrics-server`, `rook-ceph-operator`) emit `ServiceMonitor`
resources via chart values (`serviceMonitor.enabled: true`).  Helm validates CRDs at
install time — if the CRD is missing the HelmRelease fails.  With `00-crds.yaml` in
place, the CRD is always present at bootstrap time so `serviceMonitor.enabled: true`
is safe in any HelmRelease without adding `dependsOn: kube-prometheus-stack`.

---

## Community research before new deployments

Before planning any new application deployment or writing a new Kustomization, search **[kubesearch.dev](https://kubesearch.dev/)** for the chart or app name. This indexes public home-lab GitOps repos and surfaces real-world `HelmRelease`, `values.yaml`, and `ExternalSecret` patterns used by other home labbers running the same stack (Talos + Flux + Cilium).

Use findings as **research input only** — verify against upstream docs, understand *why* each value is set, and adopt only what fits this cluster's hardware and constraints. Community configs carry others' baggage; treat them as data points, not templates.
