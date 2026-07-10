# Intel GPU: Device-Plugin → DRA Migration Plan

> **Status**: 📐 Planning — not scheduled. No cluster changes required by this document.
> **Foundation**: `intel-device-plugins-operator` + `intel-device-plugins-gpu` (chart `0.36.0`) already
> deployed and healthy on cp-02/cp-03/worker-01/worker-02 (`intel-igpu-quicksync-passthrough` session,
> 2026-07-09). This plan does **not** touch that deployment until Phase 2 at the earliest.

---

## Why this exists

Comparing this cluster's GPU wiring against `bykaj/home-ops` surfaced that they schedule Intel
iGPU access via **DRA (Dynamic Resource Allocation)** — a `ResourceClaimTemplate`
(`resource.k8s.io/v1`) consumed through `resourceClaims` on the pod spec — while this cluster uses
the older **device-plugin extended-resource** model (`gpu.intel.com/i915: 1` under
`resources.limits`, gated by an NFD-applied node label). Both reach the same outcome today (Quick
Sync transcode passthrough), but DRA is strictly more expressive and is what bykaj uses for Plex
and Jellyfin.

**This is not an urgent problem.** The current setup is freshly deployed and healthy across all 4
GPU nodes. DRA's payoff — device sharing (`adminAccess`), richer selection criteria, avoiding the
older API's node-label + extended-resource indirection — only matters once there are multiple GPU
workloads contending for the same iGPU. Revisit this plan **when that becomes true**, e.g. Plex and
Jellyfin (or a future transcode consumer) are deployed on the same node and need to share one
physical iGPU, or a maintenance job (like bykaj's `plex-image-cleanup`) needs GPU co-access without
displacing the main workload.

---

## Current state (device-plugin model)

```
node-feature-discovery (NFD)
    └── NodeFeatureRule labels GPU-capable nodes: intel.feature.node.kubernetes.io/gpu=true
            ↓
intel-device-plugins-operator (installs GpuDevicePlugin CRD)
            ↓
intel-device-plugins-gpu (GpuDevicePlugin CR, nodeSelector on the NFD label)
            ↓
kubelet advertises extended resource: gpu.intel.com/i915: <sharedDevNum>
            ↓
Pod requests: resources.limits: { gpu.intel.com/i915: 1 }
```

Files: `kubernetes/apps/intel-device-plugins/intel-device-plugins/{operator,gpu}/app/`,
`kubernetes/apps/node-feature-discovery/`. Ordering is enforced via the multi-doc `ks.yaml` +
`dependsOn`/`wait: true` pattern this repo already uses elsewhere (operator → CRD instance).

**Known limitation:** `sharedDevNum` is a flat count — Kubernetes has no idea two pods sharing a
slot are safe to co-schedule vs. contending for the same encode engine. There's no way to express
"pod A needs exclusive access" vs. "pod B is fine sharing." It's a counter, not a real device model.

---

## Target state (DRA model)

```
DRA GPU resource driver (kubelet plugin, per-node DaemonSet)
    └── publishes ResourceSlice objects describing actual GPU devices per node
            ↓
ResourceClaimTemplate (per-app, e.g. "${APP}-gpu")
    spec.spec.devices.requests[].deviceClassName: gpu.intel.com
    allocationMode: All | ExactCount
    adminAccess: true|false   ← lets a second claim share a device already claimed elsewhere
            ↓
Pod: resourceClaims: [{ name: gpu, resourceClaimTemplateName: "${APP}-gpu" }]
            ↓
kube-scheduler + DRA plugin resolve the claim to a specific device at schedule time
```

DRA became GA in Kubernetes **1.34** (structured parameters model, `resource.k8s.io/v1`). This
cluster runs **v1.36.1** — fully supported, no feature-gate flips needed.

**What's NOT yet confirmed** (first thing Phase 0 must establish): whether the Intel
`intel-device-plugins-for-kubernetes` project ships a DRA-mode driver at a version compatible with
the `0.36.0` operator chart already deployed here, and whether it's distributed via the same
`intel.github.io/helm-charts` repository or a separate chart/manifest set. bykaj's `ks.yaml`
references a Kustomization named `intel-gpu-resource-driver` in a `system` namespace — treat that
as a lead to investigate, not a confirmed component name or version.

---

## Phased plan

### Phase 0 — Research & validation (no cluster changes)

- [ ] Confirm Intel ships a DRA-mode GPU driver compatible with kernel/iGPU generation in use here
      (UHD 630 class, per existing `nodeFeatureRule` targeting) and identify its Helm chart /
      manifest source and version.
- [ ] Confirm the DRA driver's `deviceClassName` value and whether it still depends on NFD labeling
      for node selection, or does its own device discovery independently (this determines whether
      NFD stays in the dependency chain or becomes removable).
- [ ] Decide the target Flux layout: likely mirrors the existing operator/CRD-instance split —
      driver-DaemonSet Kustomization (`wait: true`) → per-app `ResourceClaimTemplate` instances,
      following this repo's documented multi-doc `ks.yaml` convention (see CLAUDE.md → GitOps
      Conventions → "Multi-document ks.yaml for operator + CRD instances").
- [ ] Confirm whether the existing `gpu.intel.com/i915` device-plugin and a DRA driver can run
      side-by-side on the same nodes without double-claiming/conflicting over the same physical
      device (needed for Phase 1's dual-run validation).

**Exit criteria:** a concrete component name + chart version + confirmed no hardware conflict with
the running device plugin.

### Phase 1 — Deploy DRA driver alongside the existing device plugin (dual-run, no consumer migration)

- [ ] Deploy the DRA driver on a subset of nodes (or all 4, if Phase 0 confirms no conflict) without
      changing any workload's resource requests. There are no current GPU consumers in this repo to
      disturb, but this should still be a no-op for any unrelated workload on the same nodes.
- [ ] Create a throwaway test Pod with a `ResourceClaimTemplate` (analogous to bykaj's
      `components/gpu/resourceclaimtemplate.yaml`) and confirm it schedules and can actually reach
      the iGPU (e.g. `vainfo`/`intel_gpu_top` inside the pod, or a trivial ffmpeg VAAPI transcode).
- [ ] Validate `adminAccess: true` behavior with two simultaneous test pods sharing one device claim.

**Exit criteria:** a real pod, unrelated to production workloads, provably transcodes via DRA.

### Phase 2 — First real GPU consumer, deployed straight onto DRA

**Correction to earlier drafts of this plan:** as of this writing, **no workload in this repo
requests `gpu.intel.com/i915`** (`grep -rn "gpu.intel.com" kubernetes/apps/` returns nothing) —
`docs/CLUSTER.md` does not list Plex or Jellyfin as deployed, they only appear in
`docs/POTENTIAL-DEPLOYMENTS.md` as planned. The `intel-device-plugins-gpu` HelmRelease was rolled
out ahead of any consumer (its own values file comments: "no consumer exists yet"). So there is
nothing today to "migrate off" the device-plugin path — Phase 2 is really "deploy the cluster's
first GPU-using workload, and have it consume DRA from day one" rather than a swap.

- [ ] When the first GPU-consuming app lands (most likely Plex or Jellyfin, per
      `docs/POTENTIAL-DEPLOYMENTS.md` — but treat that as a guess, not a commitment made by this
      plan) build it against `resourceClaims` + `ResourceClaimTemplate` directly, skipping
      `resources.limits.gpu.intel.com/i915` entirely.
- [ ] Add a `components/gpu/` Kustomize Component (mirroring bykaj's, adapted to this repo's
      `postBuild.substitute` `${APP}` pattern) and wire it via the consumer's `ks.yaml`
      `spec.components`, per CLAUDE.md's documented Component-wiring rule (Components only take
      effect declared on the Flux `Kustomization`, not the plain `app/kustomization.yaml`).
- [ ] Run it for a real workload cycle (a full transcode session) before touching anything else.
- [ ] If a device-plugin consumer somehow exists by the time this phase starts (plans change),
      swap its `resources.limits.gpu.intel.com/i915` for the DRA claim instead of deploying fresh.

**Exit criteria:** one real workload running GPU work exclusively through DRA, stable for at least a
few days.

### Phase 3 — Migrate any remaining device-plugin consumers (if applicable)

- [ ] Re-run `grep -rn "gpu.intel.com" kubernetes/apps/` — if Phase 2's app was the only consumer,
      this phase is a no-op and Phase 4 can start immediately.
- [ ] For each remaining consumer, repeat Phase 2's swap: update its `ks.yaml`'s `dependsOn` from
      `intel-gpu-resource-driver`/`intel-device-plugins-operator` to whatever the DRA driver's
      Kustomization is named, and swap the resource request for a `ResourceClaimTemplate`.
- [ ] Migrate one app at a time, not in bulk. If both Plex and Jellyfin end up deployed before this
      phase runs, migrate Jellyfin first as the lower-stakes validation (Plex has active users).
- [ ] Watch for transcode regressions across a real usage window (a few days, spanning normal peak
      usage) before calling each migration done.

**Exit criteria:** every GPU-consuming workload in the cluster transcoding via DRA claims,
device-plugin extended-resource requests removed from every HelmRelease.

### Phase 4 — Decommission the device-plugin path

- [ ] Confirm no remaining workload requests `gpu.intel.com/i915` (`grep -r "gpu.intel.com" kubernetes/apps/`).
- [ ] Remove `kubernetes/apps/intel-device-plugins/` (operator + gpu HelmReleases).
- [ ] Decide NFD's fate: if the DRA driver depends on NFD's `intel.feature.node.kubernetes.io/gpu`
      label for node targeting, keep NFD. If the DRA driver does independent device discovery and
      nothing else in the cluster consumes NFD labels, remove `kubernetes/apps/node-feature-discovery/`
      too — check for other consumers of NFD labels first, don't assume GPU is the only reason it's
      installed.
- [ ] Update `docs/CLUSTER.md` (Key Architectural Decisions / hardware sections) and the recent
      sessions table to reflect the new GPU scheduling model, and roll the superseded
      `intel-igpu-quicksync-passthrough` context forward rather than leaving stale references.

**Exit criteria:** device-plugin manifests removed from Git, cluster state matches Git (no manual
cleanup needed since Flux prune handles the actual resource teardown).

---

## Rollback

Every phase up to Phase 3 is additive (DRA driver + one migrated consumer) — the device-plugin path
keeps running untouched, so rollback is just reverting the consumer's HelmRelease values back to
`resources.limits.gpu.intel.com/i915` and letting Flux reconcile. Phase 4 is the only destructive
step (removing the device-plugin manifests) and should not happen until Phase 3's exit criteria have
held stable for a real usage window.

## Risk / blast radius

- **Phases 0–2**: none to low — no live workloads today request the GPU, dual-run and first-consumer
  deployment carry no migration risk.
- **Phase 3**: medium, and only applies if a device-plugin consumer exists by then — touches
  user-facing media apps' GPU scheduling. Migrate lower-stakes apps (e.g. Jellyfin) before
  higher-stakes ones (e.g. Plex), one at a time, with a soak period between them.
- **Phase 4**: low — pure manifest removal after Phase 3 is already proven stable; Flux prune
  handles cleanup declaratively.

## Dependencies

- Kubernetes v1.36.1 (already satisfied — DRA GA since 1.34).
- cert-manager (device-plugin operator's admission webhook already depends on it; confirm whether
  the DRA driver has the same requirement in Phase 0).
- Whatever the DRA driver's own prerequisites turn out to be (Phase 0 unknown).

## Reference

- `bykaj/home-ops`: `kubernetes/components/gpu/resourceclaimtemplate.yaml`,
  `kubernetes/apps/media/{plex,jellyfin}/ks.yaml` (`dependsOn: intel-gpu-resource-driver`).
- This cluster's current device-plugin deployment:
  `kubernetes/apps/intel-device-plugins/`, `kubernetes/apps/node-feature-discovery/`.
- Kubernetes DRA docs (structured parameters, GA in 1.34): verify current upstream docs at
  implementation time rather than relying on this snapshot, since DRA is a recently-stabilized API
  and guidance may have shifted.
