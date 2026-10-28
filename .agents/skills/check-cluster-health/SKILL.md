---
name: check-cluster-health
description: Use when asked to check cluster health, find what's broken, triage an alert, or verify nothing regressed before/after a change — a live, read-only sweep of Flux, workloads, nodes, and Ceph, cross-checked against active Silences so known/accepted noise isn't reported as a new incident ("is the cluster healthy", "anything broken", "is everything OK")
context: fork
---

# Check cluster health

A live, read-only triage sweep. Each run re-inspects the live cluster from scratch — it doesn't
persist findings or state between runs, so always re-check rather than trusting a prior report.

**Read-only.** This skill only runs `kubectl get/describe/logs/exec` (exec limited to read
commands like `ceph status`), `flux get`, `helm list/get`, and the scripts in `scripts/` (which
run only those). Never `apply`, `patch`, `delete`,
`scale`, `rollout restart`, or anything else that changes cluster state — this repo is GitOps-only
(see `README.md`); fixes go through Git, not kubectl. If a real problem is found, report it and
propose the Git-based fix; only take a live corrective action if the user explicitly asks for one.

`KUBECONFIG` is set automatically by mise (`.mise/config.toml` → `[env]`); no manual export
needed. It points at `kubeconfig` in the checkout's root. A Claude Code worktree gets a copy of it
through `.worktreeinclude`; one made with plain `git worktree add` doesn't, and `kubectl` then
falls back to `localhost:8080`.

Scripts live next to this file in `scripts/`; run them from the repo root as
`bash .agents/skills/check-cluster-health/scripts/<name>.sh`. From a worktree session, run every
command as a plain call of its own: no `cd`, no `bash -c`, no exported variables. The worktree
isolation check refuses those, and it also refuses any command containing the word `git`, which is
why the sources below are listed with `flux get`.

## Step 1: Fast sweep

These are cheap and cover most real incidents:

```bash
# Nodes
kubectl get nodes -o wide

# Flux — the two CR kinds the user is most likely asking about
kubectl get kustomizations -A
kubectl get helmreleases -A

# Flux sources (Git/OCI/Helm repos) — a stuck source blocks every Kustomization/HelmRelease using it
flux get sources all -A

# Anything not Running/Succeeded
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded

# Certificates and ExternalSecrets — easy to miss, both fail silently from the app's point of view
kubectl get certificates -A
kubectl get externalsecrets -A

# PVCs not Bound
kubectl get pvc -A | grep -v Bound

# Recent warning events, fleet-wide, minus known self-resolving noise (see below)
bash .agents/skills/check-cluster-health/scripts/warning-events.sh
```

`warning-events.sh` drops four warnings that fire routinely and resolve on their own, once they
have. The first two come from every kopiur backup run:

- **`MissingDependency` on the `Snapshot`** ("waiting for VolumeSnapshot `<ns>/<name>-snap` to
  become readyToUse"). kopiur checks the Ceph snapshot it has just created about a second later,
  before the snapshot can be ready; it's usually ready within a minute or two. It's dropped once the
  `Snapshot` has reached `Succeeded`. If one still shows, check that `Snapshot`'s `status.phase`:
  still running before the message's "staging fails at" time is expected. Only a `Failed` phase, or a
  run still waiting past that time, is a finding.
- **`VolumeFailedDelete`** on the PV behind kopiur's temporary `<name>-src` PVC, usually "is still
  attached to node". kopiur deletes that PVC as soon as the backup finishes, while the volume is
  still being detached, so the CSI provisioner's first 3–4 delete attempts fail. A delete that
  races ceph-csi's own trash cleanup can also fail once with "image ID is empty, cannot remove … from
  trash". Either succeeds a few seconds later. The event is dropped once the PV no longer exists,
  whatever the message and whatever created the PV. A PV that still exists is a finding, and so is
  a leftover `-src` PVC.

The third comes from the GitHub runners in `actions-runner-system`:

- **`FailedScheduling` "waiting for ephemeral volume"** on a runner pod. Each runner gets its own
  temporary `-work` PVC, and the scheduler waits for it to be provisioned, usually a few seconds. The
  event is dropped once the pod is no longer `Pending`, whichever namespace it is in. A pod still
  `Pending` is a finding.

The fourth comes from the certificate PushSecrets in `network`:

- **`Errored` "set secret failed"** on a PushSecret. ESO's 1Password Connect provider writes each
  `data` entry as a separate read-modify-write of the whole item. When the `tls.crt` write's new
  item version hasn't reached Connect yet, the `tls.key` write is based on the old version and
  1Password rejects it. ESO retries and succeeds a few seconds later, so roughly one such event per
  hourly sync round is normal. It's dropped while the PushSecret is `Ready`; a PushSecret that isn't
  `Ready` is a finding. The event carries no reason, so the filter can't tell this race from any
  other push error that clears on retry. The reason is in the controller log, on whichever replica
  ran the sync:
  `kubectl -n external-secrets logs -l app.kubernetes.io/name=external-secrets --since=2h | grep "status 400"`
  shows `error updating 1Password Item: status 400: Unable to update item` for this race. Any other
  error there, even on a `Ready` PushSecret, is a finding.

For Kustomizations/HelmReleases, `READY` + `STATUS`/`MESSAGE` columns are the signal. `Unknown` that
persists for more than a couple of reconcile intervals is as bad as `False` — Flux only shows
`Unknown` while genuinely mid-reconcile, briefly.

**Suspended is not broken** — check before flagging a `False`/`Unknown` resource as an incident:

```bash
kubectl get kustomizations,helmreleases -A -o json | \
  jq -r '.items[] | select(.spec.suspend==true) | "\(.kind)/\(.metadata.namespace)/\(.metadata.name) suspended"'
```

**A CRD rendered by more than one Helm release** has two owners that silently overwrite each other
(see [helm-crds](../../instructions/helm-crds.instructions.md#one-release-per-crd)). Any output line
is a finding; empty output is healthy. It reads every release's stored manifest, so it takes about ten
seconds, and it can't see duplicates shipped from charts' `crds/` directories:

```bash
bash .agents/skills/check-cluster-health/scripts/duplicate-crds.sh
```

**A Deployment showing both `Available` and `Progressing` conditions as `True` is a normal rollout
state, not stuck** — Kubernetes sets both during and briefly after a healthy rollout. Only worry if
`Progressing` has been `True` for a long time with no new ReplicaSet activity, or `Available` is
`False`.

## Step 2: Pods with flapping containers

Phase-based filtering in Step 1 misses a pod that's technically `Running` but crash-looping. Get
restart count **and** the timestamp of the last restart in one shot — a long-lived pod can
accumulate a large cumulative restart count over weeks without being currently broken, so recency
matters more than the raw number:

```bash
kubectl get pods -A -o json | jq -r '
  .items[] | . as $p |
  (($p.status.containerStatuses // [])[0]) as $c |
  select($c != null and $c.restartCount > 5) |
  "\($p.metadata.namespace)/\($p.metadata.name): \($c.restartCount) restarts, last at \($c.lastState.terminated.finishedAt // "unknown")"'

# CrashLoopBackOff / ImagePullBackOff right now
kubectl get pods -A -o json | jq -r '
  .items[] | . as $p | ($p.status.containerStatuses // [])[] |
  select(.state.waiting.reason as $r | $r=="CrashLoopBackOff" or $r=="ImagePullBackOff" or $r=="ErrImagePull") |
  "\($p.metadata.namespace)/\($p.metadata.name): \(.state.waiting.reason)"'
```

A pod with a high restart count but a `lastState.terminated.reason` of `Completed` and a last-restart
timestamp from hours/days ago is not an active incident — treat it as background noise unless the
timestamp is recent or climbing during the session.

## Step 3: Ceph

```bash
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status
# If not HEALTH_OK:
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
```

`HEALTH_WARN` while a Rook/Ceph HelmRelease is mid-upgrade is expected, not a fault — check
`kubectl -n rook-ceph get helmrelease rook-ceph-cluster rook-ceph-operator` for an in-flight upgrade
before treating a `WARN` as an incident. A `health:` line listing `(muted: ...)` items is also
expected — those are deliberately silenced Ceph health checks, not active problems.

**A volume stuck in the RBD trash** never shows up in `ceph status`, an event or a Flux status.
When a PVC is deleted while a snapshot or clone still depends on its image, ceph-csi moves the
image to the trash and queues an `rbd_support` task that removes it once nothing depends on it.
If the dependant is never deleted, the task retries forever:

```bash
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rbd trash ls --long ceph-blockpool
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph rbd task list
```

Empty output and `[]` are healthy, and so is an entry whose `DELETED_AT` is minutes old. An entry
older than a day, or a task with a high `retry_attempts` and a `retry_message` such as `RBD image
has snapshots`, is a finding. Name what holds it:

```bash
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rbd snap ls --all --pool ceph-blockpool --image-id <id>
```

Each snapshot in the `trash` namespace names the `csi-snap-…` image cloned from it. Report whether
any VolumeSnapshot (`kubectl get volumesnapshotcontents`) or PV still refers to that image, and
whether another image is a clone of it (`rbd children`). Don't delete anything: removing an
orphaned image is a separate, deliberate step the user decides on.

## Step 4 (only if Steps 1–3 don't explain a reported symptom): Alertmanager

Metric-only alerts (thermal, disk-fill prediction, network drops) don't show up as broken
Kustomizations/pods. Check what's actually firing and unsilenced, through the API server's service
proxy (no port-forward to start and stop):

```bash
kubectl get --raw '/api/v1/namespaces/observability/services/kube-prometheus-stack-alertmanager:9093/proxy/api/v2/alerts?active=true&silenced=false&inhibited=false' |
  jq -r '.[] | "\(.labels.alertname) [\(.labels.severity // "-")] \(.labels.namespace // "-")"'
```

## Step 5: Filter out already-accepted noise

Check `kubernetes/apps/observability/silence-operator/silences/` before reporting an alert as new —
each file is a `Silence` custom resource (`observability.giantswarm.io/v1alpha2`) documenting a
known, accepted condition. Only entries listed in that directory's own `kustomization.yaml` are
actually applied; read a file's header comment for why it exists and whether it's still active. An
alert matching an active Silence is known and already explained — don't re-diagnose it from
scratch.

## Step 6: Report

Structure findings as:

- **🔴 Needs attention** — Ready=False/Unknown persisting, a HelmRelease install/upgrade genuinely
  failed (not mid-upgrade), CrashLoopBackOff, unbound PVC, an unsilenced firing alert. Include
  namespace/name, the actual status message, and (if obvious) which Git-tracked file would fix it —
  but don't edit it without being asked.
- **🟡 Known/expected** — anything explained by an active Silence, an in-flight upgrade, or one of
  the normal-but-noisy states above (suspended resource, Available+Progressing both True, muted
  Ceph health checks, stale-but-not-recent pod restarts). Say which.
- **✅ Healthy** — a one-line summary of what was checked and came back clean (nodes, Flux, Ceph,
  certs, secrets).

If nothing is wrong, say so plainly — don't manufacture findings to justify the sweep.

## Common mistakes

- **Reporting `Available` + `Progressing` both `True` as stuck** — that's a normal Deployment
  rollout state.
- **Flagging a pod by cumulative restart count alone** — check `lastState.terminated.finishedAt`;
  a pod that restarted 100 times over 3 days but not recently is not an active incident.
- **Not checking `spec.suspend`** before flagging a non-Ready Kustomization/HelmRelease —
  deliberately suspended resources are not incidents.
- **Reporting kopiur's per-backup warnings** — `MissingDependency` for a `Snapshot` that is still
  within its deadline or has already `Succeeded`, or `VolumeFailedDelete` for a PV that is already
  gone. Both fire on every backup run. Likewise a runner pod's `FailedScheduling` "waiting for
  ephemeral volume" once the pod is running, and a PushSecret's `set secret failed` event when the
  PushSecret is `Ready` again.
- **Skipping the Silence check** — an alert matching an active `Silence` CR is already known and
  accepted; re-diagnosing it from scratch wastes time and risks a wrong root cause.
- **Treating Ceph `HEALTH_WARN` as an incident during an in-flight Rook upgrade**, or treating
  `(muted: ...)` health checks as active problems — both are expected, transient or intentional.
- **Taking `HEALTH_OK` to mean Ceph has nothing pending** — a volume stuck in the RBD trash keeps
  `rbd_support` retrying without ever raising a health check.
- **Taking remediation action directly** (`kubectl apply`, restarting a pod, patching a PVC) — this
  repo is GitOps-only; report findings and propose the Git change instead, unless explicitly asked
  to act live.
