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

- **No NetworkPolicy**, same as everywhere else (see `CLAUDE.md`). The operator generates none per instance, so the component ships no rule to open the metrics port through one. Don't add such a rule: alone, it selects the pod and drops everything else, which makes the instance unreachable on 6379 and to the operator's own readiness check.
- **The HelmRelease must already have `spec.dependsOn`**, even if empty (`dependsOn: []`). The component's patch appends to that list and fails if it's missing.
- The spread constraint counts the instances of every app together and spreads them evenly over the nodes (`DoNotSchedule`).
