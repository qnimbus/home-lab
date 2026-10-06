# dragonfly

A Kustomize component that gives an app its own Dragonfly instance (Redis-compatible), run by the operator in [`apps/database/dragonfly`](../../apps/database/dragonfly).

## What it creates

| Resource     | Name               | Purpose                                                           |
| ------------ | ------------------ | ----------------------------------------------------------------- |
| `Dragonfly`  | `${APP}-dragonfly` | One replica, reachable at `${APP}-dragonfly.<namespace>.svc:6379` |
| `PodMonitor` | `${APP}-dragonfly` | Scrapes the instance's metrics on its `admin` port (9999)         |

It also patches the app's HelmRelease to depend on `dragonfly-operator` in `database`.

## Usage

```yaml
spec:
  components:
    - ../../../../components/dragonfly
  postBuild:
    substitute:
      APP: <app>
```

Add a `healthCheckExprs` entry for the `Dragonfly` (`status.phase == 'Ready'`) when the app can't start without it, as [`paperless`](../../apps/default/paperless/ks.yaml) does.

| Variable                    | Required                   | Purpose                                          |
| --------------------------- | -------------------------- | ------------------------------------------------ |
| `APP`                       | yes                        | Names the instance and its PodMonitor            |
| `DRAGONFLY_PASSWORD_SECRET` | with `authentication` only | Secret whose `password` key becomes the password |

For a password, also add `../../../../components/dragonfly/authentication`.

## Caveats

- **No NetworkPolicy**, same as everywhere else (see `CLAUDE.md`). Operator v1.7.0 stopped generating a policy per instance, so the component no longer ships the `-allow-metrics` rule that opened port 9999 through it. Don't add it back: alone, that rule selects the pod and drops everything else, which made a new instance unreachable on 6379 and to the operator's own readiness check.
