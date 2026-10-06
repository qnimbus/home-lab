# YAML schema comments

Every Kubernetes manifest document carries a `yaml-language-server` modeline
as its first line after `---`, one per document in multi-document files:

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/<group>/<kind>_<version>.json
apiVersion: <group>/<version>
kind: <Kind>
```

## Where the schemas come from

`schemas.clustrs.dev` is published from this cluster by
`kubernetes/apps/system/crd-schema-publisher`: every installed CRD at the
version the cluster serves, plus the Kubernetes built-ins. Don't point
manifests at third-party catalogs (`kubernetes-schemas.pages.dev`,
datreeio, yannh): they lag installed versions and miss kinds we use.

## Building the URL

- `<group>` is the `apiVersion` before the `/`; core kinds (`apiVersion: v1`)
  use `core`: `core/service_v1.json`, `core/persistentvolumeclaim_v1.json`.
- `<kind>` is lowercased, `<version>` is the `apiVersion` after the `/`:
  `kopiur.home-operations.com/snapshotschedule_v1alpha1.json`.
- A new CRD's schema appears within a minute or so of the CRD being
  installed. Check it resolves before committing:
  `curl -sI <url> | grep -i content-type` must say `application/json`. The
  site answers unknown paths with its HTML index page and a `200`, so the
  status code alone proves nothing.

## Exceptions

- Kustomize files (`kustomize.config.k8s.io`): `https://json.schemastore.org/kustomization`.
- HelmReleases on the app-template chart (sidecar `ocirepository.yaml`
  pointing at `oci://ghcr.io/bjw-s-labs/helm/app-template`) use bjw-s's
  `https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json`,
  which validates `spec.values` against the chart's values schema (the
  generic one leaves it free-form). It tracks bjw-s's `main`, not our
  pinned chart version, and its HelmRelease part lags Flux
  (`healthCheckExprs`, `postRenderStrategy`, `waitStrategy` today). A
  release that needs one of those uses
  `https://schemas.clustrs.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json`.
- Non-Kubernetes YAML keeps its own schemastore schema (GitHub workflows,
  helmfile, lefthook). Docker Compose files and Talos/Jinja templates get
  none.
