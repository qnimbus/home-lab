---
name: add-app
description: Use when deploying a new application to the cluster — scaffolding a Flux Kustomization plus app-template HelmRelease under kubernetes/apps/ (new app, new service, "add X to the cluster")
---

# Add a New Application

Scaffolds `kubernetes/apps/<namespace>/<app>/` with a Flux Kustomization (`ks.yaml`) and an app-template HelmRelease. Every value below comes from current repo conventions — when in doubt, mirror a recent real app instead of inventing structure:

| Reference app                       | Shows                                                                 |
| ----------------------------------- | --------------------------------------------------------------------- |
| `kubernetes/apps/default/whoami`    | Minimal stateless app + route                                         |
| `kubernetes/apps/default/homepage`  | Secrets from two 1Password items, config files via configMapGenerator |
| `kubernetes/apps/default/paperless` | Custom probes, dragonfly dependency, kopiur-backed persistence        |

**The templates below are leading, key order included.** Keep their order when writing new files, and don't "sort" existing files away from it. The orders themselves are in `.agents/instructions/sorting.instructions.md`.

Files beyond these templates (`Service`, `PersistentVolumeClaim`, `ScaledObject`, …) still get a `# yaml-language-server` line, built per `.agents/instructions/yaml-schemas.instructions.md`.

## Step 1: Gather details

Ask the user (AskUserQuestion) for anything not already given:

1. **App name** and **namespace** (existing dirs: `ls kubernetes/apps/`)
2. **Image** repository + tag (upstream's current release)
3. **Port** the app listens on, and whether it gets a **route** (hostname); internal (`envoy-internal`, default) or public (`envoy-external`)
4. **Persistence** — does the app store state? (→ kopiur backup component)
5. **Secrets** — env vars from 1Password? (→ ExternalSecret). Get the 1Password item name AND its exact field names — never guess field names
6. **Config files** — mounted config? (→ configMapGenerator + `resources/`)
7. **Dependencies** — other Flux Kustomizations this app needs

## Step 2: Create the files

Layout:

```
kubernetes/apps/<namespace>/<app>/
├── ks.yaml
└── app/
    ├── kustomization.yaml
    ├── ocirepository.yaml
    ├── helmrelease.yaml
    ├── httproute.yaml           # only if routed
    ├── externalsecret.yaml      # only if secrets
    └── resources/               # only if config files
```

### ks.yaml

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <app>
spec:
  targetNamespace: <namespace>
  interval: 1h
  path: "./kubernetes/apps/<namespace>/<app>/app"
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

**Namespace:** always set `spec.targetNamespace` explicitly, normally to the namespace directory the app lives in. Don't set `metadata.namespace`: the `namespace:` field in the namespace's `kustomization.yaml` stamps it, `flux-system` included.

**`wait`:** leave it unset. Add `wait: true` only when another Kustomization will `dependsOn` this one and this one has no `healthChecks`/`healthCheckExprs` (with `healthChecks`, `wait: true` makes Flux ignore them). Depending on another app, such as `kopiur` for persistence, doesn't call for `wait`.

Don't add `commonMetadata` or `timeout`: app-template sets the `app.kubernetes.io/*` labels on the workloads, and `cluster-apps` sets the timeout.

**If the app has persistence**, add these to `spec` (components use `${APP}` and `${KOPIUR_*}` substitutions — see `kubernetes/components/kopiur/README.md` for all knobs and their defaults):

```yaml
components:
  - ../../../../components/kopiur/backup
postBuild:
  substitute:
    APP: <app>
    # Optional overrides, only when defaults don't fit:
    # KOPIUR_CLAIM: <app>-data      # PVC name (default: <app>)
    # KOPIUR_CAPACITY: 15Gi         # default: 5Gi
    # KOPIUR_SCHEDULE: "H 3 * * *"  # default: hourly, H * * * *
    # KOPIUR_COPYMETHOD: Direct     # default: Snapshot — Direct for PVCs without CSI snapshots (openebs-hostpath, nfs, static PVs)
    # KOPIUR_MOVER_UID: "65534"     # default: 1000 — must match the pod's runAsUser
    # KOPIUR_MOVER_GID: "65534"     # default: 1000 — must match the pod's runAsGroup
```

Don't add a `dependsOn` on `kopiur`/`kopiur-repository` for the backup component: until the kopiur CRDs and the `nas` ClusterRepository exist (fresh cluster), the first apply fails and Flux's retry picks it up. That one-off failure on bootstrap is accepted over carrying a dependency every backed-up app would need.

Add user-specified dependencies to `dependsOn`. Include `postBuild.substitute.APP` whenever any component is used; omit `components`/`postBuild` entirely otherwise.

### app/kustomization.yaml

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./externalsecret.yaml # only if secrets
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml # only if routed
```

**If the app mounts config files**, put them in `resources/` and append:

```yaml
configMapGenerator:
  - name: <app>-config
    files:
      - config.yaml=./resources/config.yaml
generatorOptions:
  disableNameSuffixHash: true
  annotations:
    kustomize.toolkit.fluxcd.io/substitute: disabled # only if the files have their own ${...} syntax
```

Flux substitutes `${VAR}` in a generated ConfigMap like anywhere else, and replaces a variable it doesn't know with nothing. Leave the annotation off when the config files use cluster variables (`${DOMAIN_CLUSTER}` and the like, as homepage's do). Add it when a file has `${...}` of its own that must reach the app untouched (a shell script, an app's own templating).

Name a generated ConfigMap that holds app config `<app>-config` (not `-configmap`); one that holds Helm values for `valuesFrom` is `<app>-values`. Only the `-values` kind gets the `reconcile.fluxcd.io/watch: "Enabled"` label: helm-controller reacts to it for ConfigMaps a HelmRelease references in `valuesFrom`, and ignores it on a mounted one, where Reloader does the restart.

### app/ocirepository.yaml

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: <app>
spec:
  interval: 1h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: <version>
    digest: sha256:<digest>
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
  verify:
    provider: cosign
    matchOIDCIdentity:
      - issuer: https://token.actions.githubusercontent.com
        subject: ^https://github.com/bjw-s-labs/
```

The chart is pinned by tag and digest and its cosign signature is verified against bjw-s-labs' GitHub Actions identity; Renovate updates tag and digest together.

**Never write `<version>` or `<digest>` from memory** — use the pair the rest of the repo is on:

```bash
/usr/bin/grep -l "bjw-s-labs/helm/app-template" kubernetes/apps/*/*/app/ocirepository.yaml \
  | xargs yq -o=json -I0 '.spec.ref | pick(["tag", "digest"])' | sort | uniq -c | sort -rn | head -1
```

### app/helmrelease.yaml

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <app>
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: <app>
  values:
    defaultPodOptions:
      securityContext:
        runAsGroup: 1000
        runAsNonRoot: true
        runAsUser: 1000
    controllers:
      <app>:
        annotations:
          reloader.stakater.com/auto: "true" # only if the pod reads a Secret or ConfigMap
        containers:
          app:
            image:
              repository: <image-repo>
              tag: <image-tag>@sha256:<digest>
            probes:
              liveness:
                enabled: true
              readiness:
                enabled: true
            resources:
              requests:
                cpu: 10m
              limits:
                memory: 256Mi
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop:
                  - ALL
    service:
      app:
        ports:
          http:
            port: <port>
```

**The pod `securityContext` goes under `defaultPodOptions`**, not under `controllers.<app>.pod`. It then sits at the top of `values` and covers every controller of the release. Use `controllers.<app>.pod.securityContext` only for a controller that must differ from the others in the same release. Adjust `runAsUser`/`runAsGroup` (and capabilities) to what the image requires; drop the pod `securityContext` only if the image genuinely can't run non-root.

**Pin the image by digest**, in the `tag` value: `<image-tag>@sha256:<digest>`. Renovate keeps a digest current once it is there, updating tag and digest together, but it doesn't add one to a bare tag. Look the digest up, never write it from memory:

```bash
docker buildx imagetools inspect <image-repo>:<image-tag> --format '{{.Manifest.Digest}}'
```

**Optional value blocks** (top-level under `values`, after `defaultPodOptions`, alphabetical: `controllers`, `persistence`, `service`):

Persistence (pairs with the kopiur block in ks.yaml; also add `fsGroup: 1000` + `fsGroupChangePolicy: OnRootMismatch` to `defaultPodOptions.securityContext`):

```yaml
persistence:
  data:
    existingClaim: "${KOPIUR_CLAIM:=${APP}}"
    globalMounts:
      - path: /data
  tmpfs: # writable /tmp for readOnlyRootFilesystem
    type: emptyDir
    globalMounts:
      - path: /tmp
```

Config file mount (pairs with configMapGenerator):

```yaml
persistence:
  config:
    type: configMap
    name: <app>-config
    globalMounts:
      - path: /config/config.yaml
        subPath: config.yaml
        readOnly: true
```

Secrets: add to the container:

```yaml
envFrom:
  - secretRef:
      name: <app>-secret
```

### app/httproute.yaml (only if routed)

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>
spec:
  hostnames:
    - "<app>.${DOMAIN_CLUSTER}"
  parentRefs:
    - name: envoy-internal
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: <app>
          port: <port>
```

A route is always its own `httproute.yaml`, never app-template's `route:` value. That gives every app the same form whatever its chart (kube-prometheus-stack, forgejo and the `external-services` devices have routes too), applies a hostname or annotation change without a Helm upgrade, and lets the route point at a Service the release doesn't own, as the KEDA HTTP scaler apps do. For a public app use `envoy-external` and `${DOMAIN_APP}` (`.agents/instructions/dns-naming.instructions.md`). `backendRefs` names the Service, which app-template calls `<app>` when the release has one.

### app/externalsecret.yaml (only if secrets)

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <app>
spec:
  refreshInterval: 5m
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: <app>-secret
    template:
      data:
        SOME_ENV_VAR: "{{ .<APP>_field_name }}"
  dataFrom:
    - extract:
        key: <1password-item>
      rewrite:
        - regexp:
            source: "(.*)"
            target: "<APP>_$1"
```

Convention: `metadata.name` is `<app>`, the generated Secret is `<app>-secret`, and `dataFrom.extract` + `rewrite` prefixes 1Password fields with the app's name in capitals (`<APP>` is `PLEX` for plex) for use in `template.data` (see homepage for a multi-item example). The `.<APP>_<field>` references must use the item's real field names (from Step 1) — a wrong field name renders an empty value with no error. If the field names weren't provided and you can't ask, insert `<FIXME: 1password field name>` placeholders and call them out.

## Step 3: Register in the namespace kustomization

Add `./<app>/ks.yaml` to `kubernetes/apps/<namespace>/kustomization.yaml` `resources`, in alphabetical position among the app entries (`namespace.yaml` stays first; leave existing entries where they are).

**New namespace?** Create `kubernetes/apps/<namespace>/` with a `namespace.yaml` and `kustomization.yaml` copied from an existing namespace (e.g. `automation`) — set `metadata.name` in `namespace.yaml` to the new namespace and keep its `kustomize.toolkit.fluxcd.io/prune: disabled` annotation, and keep the `components/cluster-settings` component (it also brings the namespace's Flux alerts from `components/alerts`) and the `namespace:` field (no per-namespace kopiur secret is needed: the operator projects the repository password into mover namespaces).

## Step 4: Verify

```bash
kustomize build kubernetes/apps/<namespace>/<app>/app   # must render; ${APP} vars staying literal is expected
yamllint --config-file .yamllint.yaml kubernetes/apps/<namespace>/<app>
```

Show the user the created files and get confirmation before committing. Commit style: `feat(<app>): deploy`.

## Common mistakes

- **Using volsync** — this repo migrated to kopiur; `components/volsync` no longer exists.
- **Forgetting `reloader.stakater.com/auto`** on a controller whose pod reads a Secret or ConfigMap (env, `envFrom`, or a mount): a rotated secret or changed config then doesn't restart the pod. Leave it off a controller that reads neither (see `whoami`).
- **`readOnlyRootFilesystem: true` without a tmpfs** — apps that write to `/tmp` will crash; mount an emptyDir.
- **Alphabetizing what `sorting.instructions.md` orders differently**, e.g. moving `capabilities` before `readOnlyRootFilesystem`, or `dataFrom` to the top of an ExternalSecret.
- **Restating a chart default** — e.g. `strategy: Recreate` on an app-template controller. Leave it out unless something depends on it, and then say so in the namespace README (`.agents/instructions/helm-values.instructions.md`).
- **Adding a NetworkPolicy/CiliumNetworkPolicy by default** — the cluster runs without them (see CLAUDE.md's "Network policies"); only add one if the user asks.
