# keda

Two Kustomize components that scale an app to zero with [KEDA](../../apps/system/README.md): `http-scaler` while nobody is using it, `smb-scaler` while the NAS is unreachable.

Find what uses them with `grep -rl components/keda kubernetes/apps --include=ks.yaml`.

## What they create

| Component     | Resource       | Name                | Scales the app to zero                                        |
| ------------- | -------------- | ------------------- | ------------------------------------------------------------- |
| `http-scaler` | `ScaledObject` | `${APP}`            | After 30 minutes without requests; the next request starts it |
| `smb-scaler`  | `ScaledObject` | `${APP}-smb-scaler` | While the blackbox probe of `${NAS_HOST}:445` fails           |

Both target the workload named `${APP}`. `APP` is the only variable an app sets; `NAS_HOST` comes from [`cluster-settings`](../cluster-settings/README.md).

**KEDA allows one ScaledObject per workload**, so an app takes one of the two, or its own `scaledobject.yaml`.

## http-scaler

For tools a person opens now and then. Not for a service other workloads call: the first request after an idle period waits for the pod to start.

```yaml
spec:
  components:
    - ../../../../components/keda/http-scaler
  dependsOn:
    - name: keda-add-ons-http
      namespace: system
  postBuild:
    substitute:
      APP: *app
```

The app also brings, in its own `app/` folder:

- an `InterceptorRoute` named `${APP}`, which the trigger refers to. Its CRD comes from the `keda-add-ons-http` chart and bootstrap doesn't pre-install it, hence the `dependsOn`;
- an HTTPRoute whose `backendRefs` point at `keda-add-ons-http-interceptor-proxy` in `system`, not at the app's Service, and its namespace in the add-on's ReferenceGrant;
- drift detection that ignores `/spec/replicas` on the HelmRelease, or Flux puts the replicas back.

[`default`](../../apps/default/README.md) has a worked example and [`system`](../../apps/system/README.md) the add-on's side of it.

## smb-scaler

For an app that is useless, or harmful, without its SMB shares on the NAS. It needs only the component and `APP`. `restoreToOriginalReplicaCount` puts the app back at its own replica count if the ScaledObject is removed.

The app's HelmRelease must ignore `/spec/replicas` in drift detection here too.

## Caveats

- **Set `gethomepage.dev/external: "true"` on the HTTPRoute of an `http-scaler` app.** Scaled to zero it has no pods, so homepage's pod-status lookup reports "not found" (an amber dot) and logs an error on every refresh. Don't use `siteMonitor` instead: its requests pass the interceptor and wake the app.
- `http-scaler`'s `cooldownPeriod` is long on purpose: its consumers are on-demand tools, and a generous window avoids a cold start after every short pause. It is fixed in the component; change it there if it stops fitting a consumer.
- `smb-scaler`'s `cooldownPeriod: 30` is one window on top of the [`nas-smb` probe](../../apps/observability/blackbox-exporter/app/probes.yaml)'s 30s scrape interval, so a single failed scrape doesn't cold-restart the app.
- `http-scaler` hardcodes the add-on's namespace in `scalerAddress`, and `smb-scaler` the Prometheus address in `observability`. Moving either means updating the component.
