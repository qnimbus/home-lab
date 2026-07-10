# KEDA NFS-Scaler Adoption Plan

> **Status**: 📐 Planning — not scheduled. No `ScaledObject` exists yet.
> **Foundation**: KEDA the operator was deployed 2026-07-09 (`kubernetes/apps/system/keda/`, chart
> v2.20.1, operator-only — no scalers). `blackbox-exporter` (v11.15.1) + a `Probe` targeting the
> NAS's NFS port were deployed 2026-07-10 (`kubernetes/apps/observability/blackbox-exporter/`) —
> both prerequisites for the `probe_success` metric this pattern needs are now in place. **Still
> missing:** a real NFS-backed long-running workload to protect — see Prerequisites below.

---

## Why this exists

Comparing this cluster against `bykaj/home-ops` surfaced a Kustomize Component at
`kubernetes/components/keda/nfs-scaler/` used by their Plex and Jellyfin apps: a KEDA
`ScaledObject` that scales a Deployment to `0` replicas whenever a Prometheus probe shows their
NAS's NFS export (port 2049) is unreachable, then restores the original replica count once it
recovers (`restoreToOriginalReplicaCount: true`). The goal is to stop NFS-backed pods from
crash-looping or hanging indefinitely when the NAS reboots or the network blips, instead of
letting Kubernetes retry a doomed mount over and over.

**This is not an urgent problem for this cluster today**, and the reason is architectural: this
repo's default storage path is **Ceph (`ceph-block`)**, not NFS. A grep across `kubernetes/apps`
turns up exactly **one** NFS consumer in the entire live tree —
`kubernetes/apps/database/cloudnative-pg/postgres-backup-local` — and it's a CronJob writing
`pg_dumpall` backups to TrueNAS (`10.200.0.41:/mnt/tank/Cluster/cloudnative-pg`), not a
long-running Deployment. A CronJob that fails once when NFS is down and retries on its next
schedule doesn't have the crash-loop failure mode this pattern exists to prevent — KEDA's
`scaleTargetRef.kind: Deployment` doesn't even apply to it.

**Why build the plan anyway:** bykaj mounts NFS directly for Plex/Jellyfin media libraries (see
their `persistence.media` blocks, `type: nfs`, `server: ${NAS_HOST}`, `path: /mnt/vault/Media`).
`docs/POTENTIAL-DEPLOYMENTS.md` lists Plex, Jellyfin, and other media apps as planned for this
cluster too, following the same reference pattern we studied. If/when those land using
NFS-backed media mounts (as opposed to Ceph, which doesn't apply well to bulk media libraries),
this failure mode becomes real. This plan exists so the pattern is ready to adopt at that point,
not invented from scratch under pressure during an actual NAS outage.

---

## Current state vs. proposed state

**Current:**
```
Deployment (NFS-backed volume, e.g. future Plex/Jellyfin media mount)
    ↓ NAS reboots / network blip
kubelet retries mount indefinitely
    ↓
Pod stuck in ContainerCreating / CrashLoopBackOff until NAS recovers
    (no automatic backoff at the workload level; only container-level restart policy applies)
```

**Proposed:**
```
Prometheus blackbox-exporter probes NAS NFS port (2049) on an interval
    ↓ exposes probe_success{instance="<nas>:2049"}
KEDA ScaledObject (prometheus trigger, minReplicaCount: 0, maxReplicaCount: 1)
    ↓ NAS down: probe_success == 0 → scales Deployment to 0
    ↓ NAS up:   probe_success == 1 → scales back to original replica count
Deployment never attempts to mount NFS while the NAS is confirmed unreachable
```

Illustrative `ScaledObject` (bykaj's shape, ported to this repo's Prometheus/NAS naming — see
Open Questions for what's unverified here):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ${KEDA_NAME:=${APP}}-nfs-scaler
spec:
  advanced:
    restoreToOriginalReplicaCount: true
  cooldownPeriod: 0
  minReplicaCount: 0
  maxReplicaCount: 1
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ${KEDA_NAME:=${APP}}
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090
        query: probe_success{instance=~"${NAS_HOST}:2049"}
        threshold: "1"
        ignoreNullValues: "0"
```

---

## Prerequisites

1. **KEDA itself.** ✅ Deployed 2026-07-09 (`kubernetes/apps/system/keda/`, chart v2.20.1 via
   `ghcr.io/home-operations/charts-mirror`, operator-only, own `keda` namespace). Unverified until
   the first live reconcile: chart v2.20.1 is tested upstream against Kubernetes v1.33–v1.35; this
   cluster runs v1.36.1, one minor ahead — watch `kubectl -n keda get helmrelease keda` go `Ready`
   after this is pushed.
2. **A working NFS/NAS health probe.** ✅ Deployed (`kubernetes/apps/observability/blackbox-exporter/`,
   chart v11.15.1 via `ghcr.io/prometheus-community/charts`). Uses a `monitoring.coreos.com/v1`
   `Probe` CR (`app/probes.yaml`, `tcp_connect` module) rather than the chart's own
   `serviceMonitor.targets` — Probe is the idiomatic prometheus-operator CRD for this and needed no
   `dependsOn: kube-prometheus-stack` since its CRDs are pre-installed cluster-wide via
   `ops/bootstrap/helmfile.d/00-crds.yaml` (see `docs/CONVENTIONS.md` → "CRD bootstrap pattern").
   Also added an SMB probe (445) on the same NAS host, and a Postgres probe (5432) — but pointed at
   this cluster's own CloudNativePG `-rw` Service (`${PG_HOST}`), **not** the NAS, since Postgres
   here runs in-cluster (bykaj's `${DB_HOST}` was similarly distinct from their `${NAS_HOST}`).
   Both host variables come from `cluster-secrets.sops.yaml` (see `docs/CONVENTIONS.md` →
   "Cluster-wide secrets"), not hardcoded values — metric `probe_success{instance="<nas-ip>:2049"}`
   is exactly what a future `ScaledObject`'s `prometheus` trigger would query. A companion
   `PrometheusRule` (`BlackboxProbeFailed`, generic across all three probes) also alerts
   independently of KEDA. **Not yet live-verified**: this is unpushed/uncommitted at time of
   writing — `helm template` and `kustomize build` both pass, but `probe_success` hasn't been
   observed in a real Prometheus after reconcile.
3. **Confirmed Prometheus query surface.** This cluster's Prometheus lives at
   `kube-prometheus-stack-prometheus.observability.svc.cluster.local` (verified via
   `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml`), **not**
   `prometheus-operated.observability.svc.cluster.local` like bykaj's — the two repos name the
   in-cluster Prometheus Service differently. Use the confirmed name, don't copy bykaj's literally.
4. **A NAS host variable convention.** ✅ Resolved — matches bykaj directly now. `NAS_HOST` was added
   to `kubernetes/flux/vars/cluster-secrets.sops.yaml` (SOPS-encrypted, not `cluster-settings.yaml`,
   since a NAS host IP is treated as sensitive here) and is available as `${NAS_HOST}` in any app
   Kustomization via the existing `postBuild.substituteFrom` wiring — see `docs/CONVENTIONS.md` →
   "Cluster-wide secrets". `blackbox-exporter`'s Probes (Prerequisite 2) use it. The two pre-existing
   NFS consumers (`postgres-backup-local`, `components/volsync`'s `VOLSYNC_NFS_SERVER`) still
   hardcode `10.200.0.41` in plaintext — not retroactively migrated to `${NAS_HOST}`, since that
   was out of scope for the change that introduced the variable. A future `ScaledObject`'s
   `prometheus` trigger query should use `${NAS_HOST}` too, not a hardcoded IP.
5. **A `components/keda/` directory.** Doesn't exist yet. Only `components/volsync/` exists today
   as this repo's first (and so far only) Kustomize Component. `docs/ROADMAP.md`'s
   "Researched Patterns" section already flags `namespace` as the next Component to build before
   `keda` scalers — check whether that's landed by the time this plan is picked up, since the
   `namespace` Component may change how `${APP}`/postBuild wiring is expected to look.

---

## Phased rollout

### Phase 0 — Verify prerequisites, no cluster changes

- [ ] Confirm KEDA v2.19.0 is actually available and current on `ghcr.io/home-operations/charts-mirror`
      (re-check `docs/POTENTIAL-DEPLOYMENTS.md`'s version pin against upstream at implementation time).
- [x] Confirm `prometheus-blackbox-exporter`'s TCP probe module config for NFS (port 2049) — deployed
      as a plain `tcp_connect` check (handshake only, no NFS-protocol payload validation). Structural
      validation done (`helm template`, `kustomize build`); **live `probe_success` behavior against a
      real NAS outage is still unverified** — see Risk section for why a false-positive here is
      broad-blast-radius.
- [ ] Decide the NAS-host variable convention (see Prerequisite 4) before writing any reusable
      Component — retrofitting a hardcoded value into a shared Component later means editing every
      consumer.
- [ ] Identify the actual first NFS-backed Deployment this will protect (most likely Plex/Jellyfin's
      media mount, per `docs/POTENTIAL-DEPLOYMENTS.md` — but that's not committed, treat as a guess).

**Exit criteria:** KEDA and blackbox-exporter deployed and healthy; a real `probe_success` metric
visible in Prometheus for the NAS's NFS port; NAS-host variable convention decided.

### Phase 1 — Pilot on one low-stakes NFS-backed workload

- [ ] Do **not** pilot this on `postgres-backup-local` — it's a CronJob, not a Deployment, and the
      pattern doesn't apply to it (see Why This Exists). Pilot only applies once a real NFS-backed
      Deployment exists.
- [ ] Attach a standalone `ScaledObject` (not yet a Component) directly in the pilot app's `app/`
      directory, to validate the trigger and query before generalizing it.
- [ ] Force a real test: stop the NAS's NFS service (planned maintenance window, not a live-traffic
      test) and confirm the Deployment scales to 0 within the probe interval, then scales back
      correctly (`restoreToOriginalReplicaCount`) once NFS returns — verify the *original* replica
      count is restored, not just "some" replica count, for apps that might run >1 replica.

**Exit criteria:** one real workload demonstrably scales to 0 during an NFS outage and recovers
automatically without manual intervention.

### Phase 2 — Expand to remaining NFS consumers

- [ ] Re-grep `kubernetes/apps` for NFS-backed Deployments/StatefulSets at implementation time —
      the current single-consumer (`postgres-backup-local`, a non-applicable CronJob) will likely
      have changed by the time this phase starts.
- [ ] Apply the same standalone-`ScaledObject`-per-app pattern to each, one at a time, with a soak
      period between apps — don't bulk-roll this across every NFS consumer in one change.

**Exit criteria:** every NFS-backed long-running workload in the cluster has scale-to-zero
protection against NAS outages.

### Phase 3 — Promote to a reusable Kustomize Component

- [ ] Only do this once 2+ apps use the same `ScaledObject` shape (per this repo's own stated
      Component threshold in `docs/ROADMAP.md`: "Add a Component only when the same boilerplate
      appears in 3+ apps — don't create early").
- [ ] Build `kubernetes/components/keda/nfs-scaler/` mirroring bykaj's structure
      (`scaledobject.yaml` + `kustomization.yaml`), wired via `spec.components` on each consuming
      app's Flux `ks.yaml` — **not** the plain `app/kustomization.yaml** (per CLAUDE.md/ROADMAP.md's
      already-documented rule: `postBuild.substitute` only exists on the Flux CRD, so Components
      declared elsewhere leave `${VAR}` tokens unsubstituted).
- [ ] Migrate existing standalone `ScaledObject` instances from Phase 1/2 onto the Component.

**Exit criteria:** `components/keda/nfs-scaler/` exists, is consumed by every relevant app via
`ks.yaml`, and no per-app duplicated `ScaledObject` YAML remains.

---

## Risk / blast radius

- **Wrong or flaky Prometheus query** — highest-risk failure mode. If `probe_success` reports 0
  spuriously (probe misconfigured, probe pod itself down, Prometheus scrape gap), KEDA will scale a
  perfectly healthy Deployment to zero. `ignoreNullValues: "0"` (as used by bykaj) means a *missing*
  metric is treated as a failed condition, not ignored — worth deliberately confirming that's the
  desired failure direction here (fail-closed: no data → scale down) versus fail-open, before
  copying it verbatim.
- **`minReplicaCount: 0` on the wrong workload class** — this pattern is only safe for stateless-ish
  services where "no replicas for a while" is an acceptable degradation, not for anything with
  in-memory session state other services depend on being continuously available, or singleton
  workloads other apps have hard `dependsOn`/health-check expectations on.
- **KEDA itself misbehaving** — since KEDA becomes a scaling authority over production Deployments,
  a KEDA outage, crash, or metrics-server-adjacent bug could leave a `ScaledObject`-managed
  Deployment stuck at 0 with no automatic recovery path visible without checking KEDA's own health
  first. Document this as an operational gotcha before rollout (add to `docs/QA.md`), so a future
  "app X reports 0/0 replicas" incident is diagnosed correctly.
- **`cooldownPeriod: 0`** — bykaj's value means KEDA re-evaluates and can scale back up the instant
  the probe succeeds again, with no debounce. If the NAS flaps (up/down/up within seconds), the
  Deployment could thrash. Worth testing this specific behavior in Phase 1 rather than assuming
  bykaj's value is automatically correct for our NAS's actual reliability profile.

---

## Rollback

Every phase is additive and reversible independently:
- **Phase 0–1**: deleting the pilot `ScaledObject` (or its Flux-managed resource) immediately
  returns the workload to unconditioned normal scheduling — no data loss, no destructive step.
- **Phase 2**: same, per-app, one at a time.
- **Phase 3**: removing the `components/keda/nfs-scaler/` Component reference from a consumer's
  `ks.yaml` reverts that app to whatever scaling behavior existed before (likely: none, a static
  replica count) — Flux prune handles cleanup of the `ScaledObject` object itself.

No phase requires uninstalling KEDA or blackbox-exporter to roll back an individual app's adoption
of the pattern; only abandoning the whole initiative would warrant removing those.

---

## Open questions / unverified assumptions

- **Whether Plex/Jellyfin (or any future media app) will actually use NFS for media**, as opposed
  to some other approach — `docs/POTENTIAL-DEPLOYMENTS.md` lists them as planned but doesn't commit
  to a storage backend. If a future media deployment uses Ceph or a CSI-based NFS/SMB driver
  instead of a raw `type: nfs` mount, this whole pattern may not apply the same way (KEDA scaling
  a CSI-backed PVC's Deployment during a storage outage is a different risk profile than a raw NFS
  mount hanging).
- **Whether `prometheus-blackbox-exporter`'s TCP probe genuinely detects "NFS export unreachable"**
  versus just "TCP port 2049 accepts a connection" — an NFS server can accept TCP connections while
  still failing actual mount/RPC calls (e.g. mid-restart, export table not yet loaded). A pure
  TCP-connect probe may not catch every real-world NFS-unavailable scenario bykaj's pattern is
  presumably tuned against. Not verified against bykaj's actual blackbox `Probe` config, only their
  `ScaledObject` was inspected in this research pass.
- **Chart-mirror currency for KEDA v2.19.0** — this repo has a documented history of
  `ghcr.io/home-operations/charts-mirror` lagging upstream (metrics-server migration hit this).
  Not verified whether KEDA's mirror entry is current as of this writing.
- **Whether a shared `NAS_HOST`-style substitution variable is worth introducing** just for this
  pattern, or whether it should piggyback on some other planned convention change — not decided,
  flagged as a Phase 0 decision rather than asserted here.

## Reference

- `bykaj/home-ops`: `kubernetes/components/keda/nfs-scaler/scaledobject.yaml`,
  `kubernetes/apps/media/{plex,jellyfin}/ks.yaml` (component wiring).
- This cluster's only current NFS consumer:
  `kubernetes/apps/database/cloudnative-pg/postgres-backup-local/app/helmrelease.yaml` (CronJob,
  not applicable to this pattern as-is).
- This cluster's Prometheus Service name:
  `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml`.
- Planned-but-undeployed dependencies: `docs/POTENTIAL-DEPLOYMENTS.md` (`keda`,
  `prometheus-blackbox-exporter` entries).
