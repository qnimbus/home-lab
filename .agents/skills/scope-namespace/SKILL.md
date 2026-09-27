---
name: scope-namespace
description: Use when moving a kubernetes/apps/<group> app-group's Flux Kustomization CRs out of flux-system into their own namespace (namespace-scoped Kustomizations) — extending the pattern already applied to default and development to another namespace. Also covers migrating an app off the shared postgres-v17 CNPG cluster onto its own dedicated components/postgres cluster, which commonly comes up in the same move.
---

# Scope a namespace to its own Kustomizations

Moves an app-group's Flux `Kustomization` CRs out of the centralized
`flux-system` namespace into their own namespace-scoped tree. Already applied to `kubernetes/apps/default`
and `kubernetes/apps/development` — use those two as reference
implementations (`development` is now just the wrapper — forgejo moved to
`default` — so per-app `ks.yaml` examples live in `default`). For Step 3,
`kubernetes/apps/database/pgadmin` is the reference for the
relocate-and-keep-shared-cluster path (3a), and
`kubernetes/apps/default/forgejo` (`ks.yaml` and `app/helmrelease.yaml`)
is the reference for actually migrating an app off the shared cluster (3b).

Read `kubernetes/components/namespace/` (Namespace placeholder, nesting
the `cluster-settings` ConfigMap component) before starting — every step
below depends on understanding what it and the wrapper's `namespace:` field
actually do.

## Step 1: Wrapper `kustomization.yaml`

Add to `kubernetes/apps/<group>/kustomization.yaml`:

```yaml
namespace: <group>
components:
  - ../../components/namespace
```

Remove `./namespace.yaml` from `resources:` and delete the file if present.
It collides with the component's own placeholder `Namespace` object —
`kustomize build` fails outright ("namespace transformation produces ID
conflict") if both exist.

## Step 2: Per-app `ks.yaml` — every doc that actually belongs in `<group>`

- Remove `metadata.namespace: flux-system`; the wrapper's `namespace:
<group>` field now stamps it. **Keep** `spec.targetNamespace: <group>`
  (add it if missing) — every `ks.yaml` sets it explicitly.
- For every `dependsOn` entry, add explicit `namespace: flux-system` if the
  target lives there — true for virtually all shared infra
  (`onepassword-store`, `rook-ceph-cluster`, `cloudnative-pg-cluster`,
  `envoy-gateway-config`, etc.), but verify per name, don't
  assume:
  ```bash
  grep -rn "name: &app <dep-name>$" kubernetes/apps --include=ks.yaml -A1
  ```

## Step 3: Sibling Kustomizations targeting a _different_ namespace

Some apps have a second doc in the same `ks.yaml` — e.g. `<app>-db` — whose
real `targetNamespace` is a shared namespace like `database`, not `<group>`.
**A label cannot protect these.** `metadata.namespace` is set by the
wrapper's own plain `namespace: <group>` field — a built-in Kustomize
transformer with no label/selector support at all. Leaving such a doc in the
wrapper silently relocates it.

If the app is backed by the shared `postgres-v17` CNPG cluster (a
`kind: Database` doc, not a full `Cluster`), you have two options — decide
which one before touching anything:

- **3a. Keep using the shared cluster** — just relocate the sibling doc so
  it stops being caught by the wrapper's transformer.
- **3b. Migrate onto a dedicated `components/postgres` cluster instead** —
  the direction this repo is actually heading (see
  `kubernetes/components/postgres/README.md`'s intro). More work up front,
  but removes the app from `postgres-v17` entirely instead of just
  relocating its pointer.

### 3a. Relocate the sibling doc, keep the shared cluster

1. Create `kubernetes/apps/<shared-ns>/<app>/{ks.yaml,kustomization.yaml}`
   (`kustomization.yaml` is just `resources: [./ks.yaml]` — see
   `kubernetes/apps/database/pgadmin/`).
2. Paste the sibling doc there unchanged — keep its explicit
   `metadata.namespace: flux-system` / `spec.targetNamespace: <shared-ns>`.
3. Add `./<app>` to `kubernetes/apps/<shared-ns>/kustomization.yaml`'s
   `resources:`.
4. Remove that doc from the original `ks.yaml`, leaving only the app's own.
5. `spec.path` in the moved doc keeps pointing at its original manifests
   directory (e.g. `./kubernetes/apps/<group>/<app>/db`) — only the `ks.yaml`
   pointer moves, never the manifests themselves.
6. Fix `namespace` on any `dependsOn` between the two split halves, in
   either direction.

### 3b. Migrate off `postgres-v17` onto a dedicated cluster

This is exactly what happened for `forgejo` — use its current `ks.yaml` /
`app/helmrelease.yaml` as the worked reference, not just this checklist.

1. **Decide fresh-start vs. carry-forward data first.** A dedicated cluster
   bootstrapped with the `components.postgres/cnpg: init` label starts
   _empty_ — the shared cluster's existing data for this app is not carried
   over automatically. If the app has real data worth keeping, dump it
   before doing anything else:
   ```sh
   just k8s database dump <db>                       # from postgres-v17 (default)
   ```
   and restore it into the new cluster once it exists:
   ```sh
   just k8s database restore <db> <file> <app>-postgres <group>
   ```
   (see `kubernetes/apps/database/mod.just` — these recipes already handle
   both the shared and per-app-dedicated naming conventions.) If the app is
   genuinely low-value / not yet in real use, a fresh start (no
   dump/restore) is fine — that's what forgejo did.
2. Remove the old `<app>-db` sibling entirely (its `Database` CR + its own
   `ExternalSecret`) — don't relocate it per 3a, delete it.
3. **Leave the shared cluster's own role/database alone.** Do not remove the
   app's entry from `postgres-v17`'s `Cluster.spec.managed.roles`, and don't
   delete anything through the shared `Cluster` object itself. Abandoning
   (stop using) the old database is safe and sufficient; actively editing
   the live shared `Cluster` spec risks the _other_ apps still on it
   (whichever haven't been migrated yet) for no benefit — decommissioning
   that entry is a separate, deliberate step for whenever `postgres-v17`
   itself is actually being decommissioned, not a side effect of migrating
   one consumer off it.
4. Add `../../../../components/postgres` to the app's own `ks.yaml`
   `components:` list. Remove any `dependsOn` entries that only existed for
   the shared cluster (`cloudnative-pg-cluster`, the old `<app>-db`).
5. Add the `components.postgres/cnpg: init` label (see this component's
   README's "Adding a net-new DB" section) and a `healthCheckExprs` block
   for the new `Cluster` — copy both from `forgejo/ks.yaml`.
6. Add `dependsOn: []` as a placeholder on the app's own `HelmRelease` if it
   doesn't already have one. The component's `kustomization.yaml` appends
   to `/spec/dependsOn/-` via a JSON6902 patch — that `add` fails outright
   ("doc is missing path") if the array doesn't already exist, so every
   consuming app needs the empty placeholder.
7. Point the app's own config at the new cluster: `HOST` is
   `${APP}-postgres-rw` (bare — same namespace as the app itself, no
   `.namespace` suffix needed; spelling the namespace out works too but is
   redundant). Prefer reading
   `NAME`/`USER`/`PASSWORD` from the generated `${APP}-postgres-app`
   Secret's `dbname`/`username`/`password` keys (however the chart supports
   secret-sourced config — Gitea's `additionalConfigFromEnvs` +
   `GITEA__DATABASE__NAME`/`__USER`/`__PASSWD` was forgejo's mechanism, an
   app-template chart would just use `envFrom`/`secretKeyRef`) rather than
   hardcoding literals that happen to match today's defaults.
8. Drop `components/keda/postgres-scaler` from the app's `components:` if
   present — its `ScaledObject` gates on the _shared_ cluster's `${PG_HOST}`
   blackbox probe, meaningless for a dedicated cluster's own health. Either
   remove it (what forgejo did) or build a real `Probe` against
   `${APP}-postgres-rw` first — see `components/postgres/README.md`'s
   "Known gaps" section.
9. **Verify the backup, not the `Cluster.status` fields.** After
   `just k8s db-backup <group> <app>`, check the `Backup` CR itself
   (`kubectl get backup -n <group> -o yaml`) — `phase: completed`, a real
   WAL LSN range, `online: true`. Do **not** check
   `Cluster.status.lastSuccessfulBackup`/`firstRecoverabilityPoint` — those
   are permanently empty for any CNPG-plugin-interface backup (confirmed on
   both `postgres-v17` and `forgejo-postgres`; see
   [cloudnative-pg/plugin-barman-cloud#380](https://github.com/cloudnative-pg/plugin-barman-cloud/issues/380)).
   Empty there is normal, not a sign anything failed. Once a real backup
   exists, drop the `cnpg: init` label.
10. No backup-failure alerting exists yet for dedicated clusters (the shared
    cluster's dead-man's-switch `PrometheusRule` has no equivalent here) —
    known, accepted gap, not something to build as part of a single app's
    migration. See `components/postgres/README.md`'s "Known gaps" section.

## Step 4: `${VAR}` coverage

```bash
grep -rn '\${' kubernetes/apps/<group>/*/app 2>/dev/null
```

Every var used must resolve from either:

- `kubernetes/components/cluster-settings/configmap.yaml` — the already-duplicated,
  fleet-wide plaintext values. Add a new key here **only** if the value is
  safe to declassify to plaintext, and confirm with the user first. This
  file is committed in cleartext and duplicated into every namespace that
  includes the component — never add a genuinely sensitive value to it
  without explicit sign-off.
- the app's own `postBuild.substitute` / `substituteFrom`.

## Step 5: Verify

```bash
mise exec -- kustomize build --load-restrictor LoadRestrictionsNone kubernetes/apps/<group>
mise exec -- kustomize build --load-restrictor LoadRestrictionsNone kubernetes/apps   # full tree
```

The `--load-restrictor` flag is required locally because
`components/namespace` lives outside
`kubernetes/apps/<group>` — Flux sets the equivalent option internally, so
this is a local-validation-only requirement, not something to add to any
committed manifest.

Confirm in the output:

- Relocated `Kustomization` CRs show `metadata.namespace: <group>` (not
  written in the source `ks.yaml`) and `spec.targetNamespace: <group>`.
- Any Step 3 sibling still shows its original `flux-system`/`<shared-ns>`
  values, untouched.
- `${VAR}`s resolve to real values in the app's own build
  (`kustomize build kubernetes/apps/<group>/<app>/app`) — not left as
  literal `${...}` strings. That build will never show a `namespace:` field
  either way (it's injected later, at Flux reconcile time, from
  `spec.targetNamespace` — not something plain `kustomize build` can
  simulate); don't mistake its absence for a bug.

## Step 6: Before deploying — protect stateful apps from prune-on-delete

This step is about what happens on the _live cluster_ when the commit lands,
not about the files themselves — easy to skip because nothing in a local
`kustomize build` will ever catch it.

Relocating a Kustomization CR's own `metadata.namespace` (`flux-system` →
`<group>`) is not an in-place rename from Flux's or Kubernetes' point of
view — `Kustomization/flux-system/<app>` and `Kustomization/<group>/<app>`
are two entirely different objects (identity is `(namespace, name)`, not
`name` alone). When `cluster-apps` next reconciles and finds the old one is
no longer in the desired manifest set, it **deletes** it. Flux's own docs
confirm deleting a Kustomization CR triggers garbage collection of
everything in its `.status.inventory` whenever `spec.prune: true` — which is
the default, and unlikely to have been changed for any existing app. The
docs do not cover (and don't promise is safe) the race between the new
Kustomization adopting those same resources and the old one's
finalizer-triggered prune deleting them first.

For a stateless app this just risks a brief involuntary teardown+recreate
(short downtime, no lasting harm). For an app with **any persistent
resource** — a PVC from `components/nfs-config` or in the app's own `pvc.yaml`, a
`components/postgres` `Cluster` and its storage, anything else backed by
real data — this is a genuine data-loss risk, not a theoretical one. Check
first:

```bash
grep -nE "components/(nfs-config|postgres)" kubernetes/apps/<group>/<app>/ks.yaml
grep -rl "kind: PersistentVolumeClaim" kubernetes/apps/<group>/<app>   # PVC declared in the app's own manifests
```

The first pattern only knows today's components — confirm the current set
with `grep -rl "kind: PersistentVolumeClaim" kubernetes/components` and add
any new one. `components/nfs-config` is the easy one to miss: its `/config`
PVC has no backup, and the `nfs` StorageClass is `reclaimPolicy: Delete`
with no `onDelete` parameter, so csi-driver-nfs's default (`delete`) removes
the volume's directory on the NAS as soon as the PVC is pruned. Confirm a
group's live reclaim policies with:

```bash
kubectl get pv -o custom-columns=NAME:.metadata.name,RECLAIM:.spec.persistentVolumeReclaimPolicy,CLAIM:.spec.claimRef.name,NS:.spec.claimRef.namespace | grep -E "NAME|<group>"
```

If the app has persistent state, before pushing the namespace-relocation
commit, patch the **currently-live** old Kustomization object (not
anything in git) to orphan instead of prune on deletion:

```sh
kubectl patch kustomization <app> -n flux-system --type merge -p '{"spec":{"deletionPolicy":"Orphan"}}'
```

This is a one-time, out-of-band, live-cluster action — never add
`deletionPolicy: Orphan` to the committed `ks.yaml` itself (that would
disable pruning for this app going forward, not just for this one
transition; nothing needs cleaning up afterward either, since the old
object ceases to exist once deleted). Once set, the old CR's deletion
leaves its Deployment/Service/PVC/Cluster/etc. alone, and the new
Kustomization's first reconcile just adopts them via normal server-side
apply — no teardown, no recreate, no data at risk.

(`kubernetes/apps/database/cloudnative-pg`'s existing `postgres-v17` cluster
and this note both exist because of a real prior incident — see the
`CNPG_V17_CURRENT_CLUSTER` comment in that app's `ks.yaml` — this class of
mistake has already cost a PITR recovery once in this cluster's history.)

## Step 7: Fix `dependsOn` references elsewhere in the repo

Step 1's wrapper `namespace: <group>` transformer relocates the app's
`Kustomization` CR itself, not just its rendered resources — confirmed live
when cert-manager's migration broke four other Kustomizations
(`cloudnative-pg-operator`, `plugin-barman-cloud`,
`intel-device-plugins-operator`, `certificates-export`) that each
`dependsOn` it. Flux defaults an omitted `dependsOn[].namespace` to the
_referencing_ Kustomization's own namespace, not the target's — so any
bare `dependsOn: [{name: <app>}]` elsewhere in the repo that pointed at an
app now moving out of `flux-system` silently starts resolving against the
wrong namespace, and fails with `dependency '<referencer-ns>/<app>' not
found` on the next reconcile.

Find every candidate before pushing:

```bash
grep -rln "name: <app>\$" kubernetes/apps --include=ks.yaml
```

For each hit outside `<group>` itself, check whether it's a `dependsOn`
entry (not just a `healthChecks`/`metadata.name` match) and, if so, add or
fix explicit `namespace: <group>`. Also check for a `dependsOn` on any
Kustomization _deleted_ as part of this migration (e.g. two app-groups
merged into one, like `cluster-issuers` folding into `cert-manager`) —
remove those entries outright rather than repointing them.

`kustomize build` has no visibility into cross-file `dependsOn`
resolution at all — verify against the live cluster after deploying:

```bash
kubectl get kustomization -A | grep -i "not found\|False"
```

## Common mistakes

- **Removing `spec.targetNamespace`.**
  There is no fallback to the CR's own `metadata.namespace` for the app's
  own build (`spec.path`) — verified against Flux source
  (`fluxcd/pkg/kustomize/kustomize_generator.go`: `kus.Namespace` is only
  ever set from `spec.targetNamespace`). Without it, the app's actual
  HelmRelease/ExternalSecret/etc. end up with no namespace at all.
- **Trusting a clean `kustomize build kubernetes/apps` as proof `spec.patches`
  works.** The CLI has zero visibility into Flux's own `spec.patches`
  reconcile-time behavior — it only catches structural
  errors, never this class of bug.
- **Assuming a label can gate the wrapper's own `namespace:` field.** It
  can't — see Step 3.
- **Declassifying a value into `components/cluster-settings/configmap.yaml`
  without asking first.**
- **Pushing a namespace relocation for a stateful app without orphaning the
  old CR first (Step 6).** The PVC/Cluster's own identity never changes —
  the risk is Flux pruning it as a side effect of deleting the superseded
  `flux-system` Kustomization, not the resource actually moving anywhere.
- **Reading a non-match on the Step 6 grep as "stateless" without checking
  the components list.** `components/nfs-config` apps match neither
  `volsync` nor `postgres`, yet own an unbacked-up PVC on a
  `reclaimPolicy: Delete` StorageClass — hit for real in the `downloads`
  migration (`prowlarr`/`sonarr`/`radarr`/`sabnzbd`).
- **Treating an empty `Cluster.status.lastSuccessfulBackup`/
  `firstRecoverabilityPoint` as a failed backup (Step 3b.9).** It's
  permanently empty for CNPG-plugin-interface backups on _every_ cluster in
  this repo, dedicated or shared — check the `Backup` CR itself instead.
- **Actively editing `postgres-v17`'s live `Cluster` spec (e.g. removing a
  `managed.roles` entry) when migrating one app off it (Step 3b.3).**
  Abandoning the old database is enough; the shared cluster still serves
  other, unmigrated apps until it's actually decommissioned.
- **Forgetting `dependsOn: []` on the HelmRelease before adding
  `components/postgres` (Step 3b.6).** Its dependency-injection patch is a
  JSON6902 append — it errors outright if there's no existing array to
  append to, it doesn't create one.
- **Forgetting that other Kustomizations elsewhere in the repo can `dependsOn`
  an app inside `<group>` with a bare, namespace-less reference (Step 7).**
  Migrating the target's CR out of `flux-system` breaks every such reference
  silently — no `kustomize build` catches it, only a live reconcile does.
