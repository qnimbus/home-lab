# gpu

A Kustomize component that gives an app a claim on the nodes' Intel iGPU, through Dynamic Resource Allocation and the driver in [`apps/system/intel-gpu-resource-driver`](../../apps/system/intel-gpu-resource-driver/).

## Use case

Hardware transcoding or other GPU work in a pod. Find what uses it with `grep -rl components/gpu kubernetes/apps --include=ks.yaml`.

## What it creates

| Resource                | Name         | Purpose                                                     |
| ----------------------- | ------------ | ----------------------------------------------------------- |
| `ResourceClaimTemplate` | `${APP}-gpu` | A claim per pod on every `gpu.intel.com` device of its node |

## Usage

In the app's `ks.yaml`:

```yaml
spec:
  components:
    - ../../../../components/gpu
  postBuild:
    substitute:
      APP: *app
```

In the app's `helmrelease.yaml` (app-template), name the claim on the pod and hand it to the container:

```yaml
defaultPodOptions:
  resourceClaims:
    - name: gpu
      resourceClaimTemplateName: "${APP}-gpu"
controllers:
  <app>:
    containers:
      app:
        resources:
          claims:
            - name: gpu
```

| Variable | Required | Default | Purpose                    |
| -------- | -------- | ------- | -------------------------- |
| `APP`    | yes      | —       | Claim template name prefix |

## Caveats

- **The namespace needs the `resource.kubernetes.io/admin-access: "true"` label.** The claim sets `adminAccess: true`, and Kubernetes only admits such a claim in a labelled namespace. Without the label the pod's claim is rejected. [`media`](../../apps/media/namespace.yaml) carries it.
- `adminAccess` does not reserve the device: another claim can use the same GPU at the same time.
- No `dependsOn` on the driver is needed for the dry-run: `ResourceClaimTemplate` is a built-in kind. Without the driver the pod stays `Pending` until its claim can be allocated.
