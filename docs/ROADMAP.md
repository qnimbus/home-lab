# Home Lab — Cluster Roadmap <!-- omit from toc -->

Pending work items for the cluster, roughly in priority / dependency order. Update this file as tasks are started, completed, or reprioritized.

## Contents  <!-- omit from toc -->

- [In Progress](#in-progress)
  - [Future Storage Options](#future-storage-options)
  - [Grafana](#grafana)
  - [Alertmanager Receiver](#alertmanager-receiver)
  - [Scheduling Topology: Follow-up Fixes](#scheduling-topology-follow-up-fixes)
  - [Kubernetes Descheduler](#kubernetes-descheduler)
  - [Talos Config, Image Extensions \& Patch Audit](#talos-config-image-extensions--patch-audit)
  - [GitHub Actions Self-Hosted Runners (ARC + Claude PR Review)](#github-actions-self-hosted-runners-arc--claude-pr-review)
  - [Researched Patterns (bykaj/home-ops)](#researched-patterns-bykajhome-ops)
- [Completed](#completed)

---

## In Progress

### Future Storage Options

Both stages are optional — Longhorn covers all current workload needs. Implement only if requirements emerge.

- **Stage 3 — Rook/Ceph**: S3-compatible object storage, `ReadWriteMany` block volumes, or more granular replication controls. The 3-disk hardware layout supports a 3-OSD Ceph cluster directly. Costs ~2–3 GB RAM per OSD node. Not required unless Longhorn's RWO-only model becomes a blocker.
- **Stage 4 — NFS/SMB CSI**: Deploy `csi-driver-nfs` and/or `csi-driver-smb` for ReadWriteMany workloads (photo libraries, shared media) when a NAS is added. Wire credentials via ExternalSecret from 1Password (ESO + 1Password Connect already deployed — no blocker).

---

### Grafana

Deploy Grafana as a follow-up to kube-prometheus-stack. Grafana is currently disabled in the kube-prometheus-stack HelmRelease (`grafana.enabled: false`) to keep the initial deployment scope small.

**Deployment notes:**
- Enable via `grafana.enabled: true` in `kubernetes/apps/observability/kube-prometheus-stack/app/helm/values.yaml`, or deploy as a standalone chart with Prometheus as a data source
- Add a Longhorn PVC for dashboard persistence
- Wire the admin password via ExternalSecret from 1Password
- HTTPRoute on `envoy-internal` (LAN-only)
- Pre-built dashboards exist for Longhorn, Flux, and node-exporter in the kube-prometheus-stack chart (`forceDeployDashboards: true` once Grafana is enabled)

**Dependencies:** kube-prometheus-stack ✅

---

### Alertmanager Receiver

Wire an Alertmanager notification receiver so cluster alerts reach a human. Alertmanager is deployed and running; it currently has no routes configured so all alerts are silently dropped.

**Alerting rules to add at minimum:**
- `kube_pod_status_phase{phase=~"Failed|Unknown"} > 0` — stale pod accumulation
- `kube_helmrelease_ready == 0` — Flux HelmRelease degraded
- `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15` — disk pressure
- `longhorn_volume_robustness == 2` — degraded Longhorn volume

**Deployment notes:**
- Receiver options: Discord webhook, SMTP, or Pushover (archive precedent)
- Receiver credentials via ExternalSecret from 1Password (ESO already running)
- Add `alertmanager.config` to `helm/values.yaml` with routes + receiver; keep the secret itself in 1Password

**Dependencies:** kube-prometheus-stack ✅, onepassword-connect ✅

---

### Scheduling Topology: Follow-up Fixes

Two gaps identified during the 2026-05-21 cluster audit that were not fully resolved by the `topology-spread` session.

#### kustomize-controller: both replicas co-located on talos-cp-02

Both `kustomize-controller` replicas currently run on `talos-cp-02`. The Flux spread uses `ScheduleAnyway` (soft) because 4 controllers × 2 replicas = 8 pods across 3 nodes forces an uneven 3/3/2 split — hard `DoNotSchedule` would permanently block the 8th pod. With a soft constraint the scheduler may still co-locate two replicas of the same controller when it scores that placement higher.

**Impact:** If `talos-cp-02` goes down, Flux loses both `kustomize-controller` replicas simultaneously. Leader election re-runs on surviving nodes within ~35 s, but `Kustomization` reconciliation pauses until a new leader is elected.

**Options to investigate:**
- Add `podAntiAffinity` (preferred, not required) scoped to `app.kubernetes.io/name: kustomize-controller` to discourage co-location of the same controller without blocking scheduling
- Use `matchLabelKeys: [pod-template-hash]` on the spread constraint so rolling restarts don't fight the constraint
- Accept as-is: `ScheduleAnyway` was chosen intentionally; the ~35 s failover window is acceptable for a homelab

#### envoy-gateway: single-replica control plane

The `envoy-gateway` pod (the Gateway API controller) is single-replica on `talos-cp-03`. The three Envoy proxy pods (`envoy-external`, `envoy-internal`) are correctly spread 1-per-node and are unaffected. If `talos-cp-03` goes down:
- Live traffic continues — proxy pods on cp-01 and cp-02 keep serving from their last received xDS snapshot
- **No new `HTTPRoute`, `Gateway`, or TLS changes take effect** until the control plane pod reschedules (~30–60 s)

**Options:**
- Set `deployment.replicas: 2` (or equivalent) in the envoy-gateway HelmRelease values and add a `podAntiAffinity` or `topologySpreadConstraint` to spread across nodes
- Accept as-is: brief control-plane unavailability on cp-03 loss does not drop live traffic; homelab risk tolerance is high

**Dependencies:** None — both fixes are independently implementable.

---

### Kubernetes Descheduler

Investigate deploying the [Kubernetes Descheduler](https://github.com/kubernetes-sigs/descheduler) to actively evict pods that violate spread constraints — a gap the scheduler alone cannot close.

**Why this matters:**
The Kubernetes scheduler enforces topology spread constraints and anti-affinity rules only at pod *creation* time. Once a pod is running, it is never moved — even if the constraint is later violated (e.g. after a node recovers, a rolling upgrade shifts replicas, or a pod is manually rescheduled). The Descheduler runs periodically, identifies violations, and evicts the offending pods so the scheduler can rebalance them.

This cluster has at least two known scheduling imbalances that the Descheduler could self-heal:
- Both `kustomize-controller` replicas co-located on `talos-cp-02` (see Scheduling Topology follow-up above)
- ESO pods post-upgrade landing on cp-02 and cp-03 only, leaving cp-01 light

**Key strategies to evaluate:**
- `RemovePodsViolatingTopologySpreadConstraint` — evicts pods that violate `topologySpreadConstraints`; the primary target for this cluster
- `RemovePodsViolatingInterPodAntiAffinity` — evicts pods that violate anti-affinity rules after the fact
- `LowNodeUtilization` — optional; redistributes pods from underutilised nodes; evaluate whether the cp-03 bias warrants this

**Deployment notes:**
- Helm chart via `kubernetes-sigs/descheduler` OCIRepository (`ghcr.io/kubernetes-sigs/charts/descheduler`)
- Deploy in `kube-system` (standard placement for scheduling infrastructure)
- Run as a `CronJob` on a short interval (e.g. every 5 min) rather than as a continuous `Deployment` — lower blast radius, easier to reason about eviction bursts
- The `RemovePodsViolatingTopologySpreadConstraint` strategy should be scoped to namespaces with `DoNotSchedule` constraints to avoid evicting workloads with soft (`ScheduleAnyway`) constraints unexpectedly

**Dependencies:** None — independently implementable. Existing topology spread constraints are already in place; the Descheduler is purely additive.

---

### Talos Config, Image Extensions & Patch Audit

Review the current Talos configuration end-to-end to identify missing extensions, suboptimal patches, and any node-specific tuning gaps. The schematic currently ships `intel-ucode` and `amd-ucode` with several extensions commented out; patches exist for kubelet, network, sysctls, NFS defaults, and machine features — but these were written incrementally and have not been audited holistically.

Areas to investigate:

**Image extensions (`talos/schematic.yaml`)**
- `siderolabs/iscsi-tools` — required if Rook/Ceph or TrueNAS iSCSI is added (storage roadmap item)
- `siderolabs/util-linux-tools` — provides `lsblk`, `blkid`, etc.; useful for storage debugging
- `siderolabs/drbd` — needed if DRBD-backed HA storage is considered
- `siderolabs/nfs-utils` (or confirm kernel NFS client suffices for NFS mounts)
- `siderolabs/i915-ucode` / `siderolabs/amd-gpu-firmware` — relevant if any node is repurposed to run GPU workloads
- `siderolabs/stargz-snapshotter` — lazy image pulling; worth evaluating for large workloads
- Check [factory.talos.dev](https://factory.talos.dev) for any new official extensions added since cluster was built

**Global patches (`talos/patches/global/`)**
- `machine-sysctls.yaml` — verify values are tuned for 10 GbE bonds (e.g. `net.core.rmem_max`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`)
- `machine-kubelet.yaml` — check `maxPods`, `evictionHard`, `kubeReserved` / `systemReserved` are appropriate for the hardware
- `machine-network.yaml` — confirm bond MTU TODO is addressed (jumbo frames / 9000 MTU for storage VLAN)
- `machine-network.yaml` — **[low/cosmetic]** bond member alias selectors on all three nodes use `glob(driver)` (e.g. `glob("ixgbe", link.driver)`) which matches both ports on the same NIC; Talos skips the alias silently. Tighten to `hardwareAddr` or exact interface `name` so per-member aliases actually resolve if ever needed.
- `machine-files.yaml` — audit NFS mount defaults; verify `nfsvers=4.2` and `nconnect=16` are still best practice
- `machine-time.yaml` — confirm NTP servers and stratum are appropriate for home lab

**Controller-plane patches (`talos/patches/controller/`)**
- `admission-controller-patch.yaml` — review enabled admission plugins against current Kubernetes best practices
- `cluster.yaml` — re-check etcd subnet advertising, Talos API + kubelet subnet restrictions
- `machine-features.yaml` (controller) — confirm KubePrism, `hostDNS`, and any other beta features are intentional

**Per-node considerations**
- cp-03 (MS-A2, 32c/92GB) may benefit from NUMA-aware kubelet configuration
- Confirm `installDisk` is consistent with actual disk layout (nvme0n1 vs nvme1n1) post-wipe

Deliverable: a PR updating `schematic.yaml` and the relevant patch files with reasoned changes; update `talenv.yaml` if the schematic ID changes (re-register at factory.talos.dev).

---

### GitHub Actions Self-Hosted Runners (ARC + Claude PR Review)

Deploy **Actions Runner Controller (ARC)** to run GitHub Actions jobs in-cluster, then wire up `claude-code-action` to automatically review Renovate PRs using the `pr-upgrade-reviewer` agent.

#### Why

Renovate opens PRs constantly. The `pr-upgrade-reviewer` agent already knows how to assess upgrade risk, breaking changes, and merge safety — but today it must be invoked manually. Self-hosted runners mean:
- Reviews run on our own hardware (no GitHub-hosted runner minutes consumed)
- The runner has direct cluster access (kubectl, talosctl) for richer context
- `ANTHROPIC_API_KEY` stays inside the cluster, never leaving our network
- Future CI jobs (linting, schema validation, dry-run applies) can also use the runners

#### Architecture

Two ARC components, matching the multi-document `ks.yaml` operator-plus-instance pattern:

```
actions-runner-system/
├── ks.yaml                          # two-doc: controller + runners (dependsOn controller)
└── actions-runner-controller/
    ├── app/
    │   ├── kustomization.yaml
    │   ├── ocirepository.yaml       # gha-runner-scale-set-controller
    │   └── helmrelease.yaml         # controller only — no values needed
    └── runners/
        ├── kustomization.yaml
        └── home-lab/
            ├── kustomization.yaml
            ├── ocirepository.yaml   # gha-runner-scale-set
            ├── helmrelease.yaml     # runner pool config (minRunners, maxRunners, image)
            ├── externalsecret.yaml  # GitHub App credentials from 1Password
            └── rbac.yaml            # ServiceAccount + ClusterRoleBinding + Talos SA
```

**OCI sources** (both at `oci://ghcr.io/actions/actions-runner-controller-charts/`):
- `gha-runner-scale-set-controller` — the cluster-wide controller
- `gha-runner-scale-set` — one scale set per repo (or org)

Reference: bykaj/home-ops uses both at chart version `0.14.1`.

#### Key configuration decisions

**Runner mode — `kubernetes` not `docker`**
Set `containerMode.type: kubernetes` in the scale set values. Each job runs as a **pod** (not a Docker container), which avoids Docker-in-Docker and integrates naturally with cluster RBAC. A work volume (25 Gi `openebs-hostpath` PVC) is provisioned per job and cleaned up automatically.

**Authentication — GitHub App (not PAT)**
Create a GitHub App scoped to this repo with `Actions: Read/Write` and `Administration: Read` permissions. Store three values in 1Password under item `actions-runner`:
```
ACTIONS_RUNNER_APP_ID          → github_app_id
ACTIONS_RUNNER_INSTALLATION_ID → github_app_installation_id
ACTIONS_RUNNER_PRIVATE_KEY     → github_app_private_key
```
The `ExternalSecret` maps these to a `home-lab-runner-secret` Secret that the scale set HelmRelease references via `githubConfigSecret`.

**Cluster access — RBAC + Talos ServiceAccount**
The runner ServiceAccount gets `cluster-admin` (homelab; acceptable risk). Additionally, a Talos `ServiceAccount` CRD (`talos.dev/v1alpha1`) with `os:admin` role is created and its secret mounted at `/var/run/secrets/talos.dev` — this gives runner jobs direct `talosctl` access, useful for cluster validation steps.

**Runner image**
bykaj uses `ghcr.io/home-operations/actions-runner` (community image with common tools pre-installed). Evaluate whether the standard `ghcr.io/actions/runner` base image suffices or whether the home-operations variant is preferable. Set `ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER=false` so jobs can run directly in the runner container without a nested job container.

#### Renovate PR auto-review workflow

Once runners are live, add a workflow at `.github/workflows/renovate-pr-review.yml`:

```yaml
name: Auto-review Renovate PRs
on:
  pull_request:
    types: [opened, reopened]
    branches: [main]

jobs:
  review:
    if: github.actor == 'renovate[bot]'
    runs-on: home-lab               # matches the runner scale set's runnerGroup/label
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: anthropic-ai/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            Review PR #${{ github.event.pull_request.number }} using the
            pr-upgrade-reviewer agent. Assess upgrade risk, breaking changes,
            and whether it is safe to merge. Post findings as a PR comment.
```

`ANTHROPIC_API_KEY` is stored in 1Password and injected into the runner pod via an `ExternalSecret` → Kubernetes Secret → runner env.

#### Steps to implement

1. **Create GitHub App**: `github.com/settings/apps` → scoped to this repo → note App ID + Installation ID → generate private key
2. **Add 1Password item** `actions-runner` with the three credential fields above; also add `ANTHROPIC_API_KEY` field
3. **Add OCI sources** to `kubernetes/flux/meta/repos/oci/` (or inline in `app/ocirepository.yaml` per bykaj pattern)
4. **Create `kubernetes/apps/actions-runner-system/`** directory with the layout above
5. **Add namespace** `actions-runner-system` to `kubernetes/flux/cluster/` (or via a `namespace.yaml` in the app kustomization)
6. **Wire into cluster-apps** by adding to the parent `kustomization.yaml` under `kubernetes/apps/`
7. **Add workflow file** at `.github/workflows/renovate-pr-review.yml`
8. **Verify**: open a test PR, confirm runner pod spawns, confirm Claude posts a comment

#### Dependencies

- `openebs-hostpath` StorageClass ✅ (work volume PVC per job)
- `external-secrets` + `onepassword-connect` ✅ (GitHub App credentials + ANTHROPIC_API_KEY)
- GitHub App created (manual step, pre-deploy)

---

### Researched Patterns (bykaj/home-ops)

Patterns observed in the [`bykaj/home-ops`](https://github.com/bykaj/home-ops) repository worth adopting. Each is independently implementable — ordered roughly by value vs. effort.

#### Kustomize Components (`kubernetes/components/`)

Reusable Kustomize Components (`apiVersion: kustomize.config.k8s.io/v1alpha1 / kind: Component`)
that apps include in their `app/kustomization.yaml` via `components:` references. bykaj ships:
- `components/namespace/` — bundles namespace creation + `cluster-secrets` Secret per-app
  namespace + Flux alerts
- `components/volsync/` — VolSync backup PVC + ReplicationSource/Destination templates
- `components/keda/*-scaler/` — KEDA ScaledObject templates for Postgres, Redis, NFS, SMB
- `components/gpu/` — ResourceClaimTemplate for GPU workloads

**Steps to implement:**
- Create `kubernetes/components/` as app count grows
- The `namespace` Component is highest priority: bundles namespace creation + cluster-secrets
  per-app, so apps never need separate namespace manifests or per-namespace secret wiring
- Add a Component only when the same boilerplate appears in 3+ apps — don't create early
- Natural order: `components/namespace/` first (after cluster-vars lands), then
  `components/volsync/` when backup is added, then KEDA scalers if KEDA is deployed

---

#### Multi-Domain Certificate Pipeline (`certificates-export` / `certificates-import`)

A two-phase push-pull pattern that makes TLS certificates resilient across cluster rebuilds and avoids Let's Encrypt rate limits when managing multiple domains. Sourced from `bykaj/home-ops` (`kubernetes/apps/network/certificates/`).

**Why this matters for us:**
Currently we have one domain (`${CLUSTER_DOMAIN}`) and one wildcard cert issued directly by cert-manager in `envoy-gateway/config/certificate.yaml`. That is fine for one domain. As soon as a second domain is added, each rebuild risks hitting the Let's Encrypt [duplicate certificate rate limit](https://letsencrypt.org/docs/rate-limits/) (5 identical certs per 7 days). With this pattern, certs are issued once and persisted in 1Password — rebuilds restore from 1Password in seconds.

**How it works:**

```
cert-manager issues Certificate
    ↓ creates TLS Secret in cluster
PushSecret (ESO) → writes Secret into 1Password as base64-encoded item
    (certificates-export Kustomization)

    ↑ on cluster rebuild / new node
ExternalSecret (ESO) ← reads item from 1Password, recreates TLS Secret
    refreshPolicy: CreatedOnce   — ESO won't overwrite once created
    creationPolicy: Orphan       — cert-manager retains ownership; rotations flow naturally
    (certificates-import Kustomization)
```

`envoy-gateway-config` gains `dependsOn: certificates-import`, ensuring the Gateway listeners never apply before the TLS Secrets exist.

**Directory layout:**

```
kubernetes/apps/network/certificates/
├── ks.yaml                        # two-doc: certificates-import (wait: true) → certificates-export
├── export/
│   ├── kustomization.yaml
│   ├── certificates.yaml          # cert-manager Certificate CRs (one per domain)
│   └── pushsecrets.yaml           # ESO PushSecret CRs (one per domain)
└── import/
    ├── kustomization.yaml
    └── externalsecrets.yaml       # ESO ExternalSecret CRs (one per domain)
```

**Flux ordering:**

```
certificates-import (wait: true)
    ↓ produces TLS Secrets
certificates-export (dependsOn: certificates-import)
    ↓ keeps 1Password in sync
envoy-gateway-config (dependsOn: certificates-import, cert-manager)
```

**Steps to implement (when adding a second domain):**

1. Create `kubernetes/apps/network/certificates/` with the layout above
2. For each domain, add one `Certificate` + one `PushSecret` (export) and one `ExternalSecret` (import)
3. Add `certificates` to `kubernetes/apps/network/kustomization.yaml`
4. Move `wildcard-production` `Certificate` from `envoy-gateway/config/` into `certificates/export/certificates.yaml`; remove `certificate.yaml` from `envoy-gateway/config/`
5. Update `envoy-gateway/ks.yaml`: replace `dependsOn: cluster-issuers` with `dependsOn: certificates-import`
6. Update `envoy-gateway/config/gateway.yaml` listeners to reference per-domain Secret names (e.g. `vwn-io-tls`) instead of `wildcard-production-tls`
7. Seed 1Password: on first deploy, `certificates-export` runs first and writes the certs; subsequent rebuilds restore from 1Password before cert-manager even runs

**Note on `creationPolicy: Orphan`:** The ExternalSecret creates the Secret but immediately releases ownership. cert-manager then annotates and manages it normally — renewal writes a new cert into the same Secret, which ESO's `refreshPolicy: CreatedOnce` leaves untouched. `PushSecret` picks up the renewed cert and writes it back into 1Password, keeping the vault copy current.

**Dependencies:** `external-secrets` + `onepassword-connect` ✅ (already deployed), `cert-manager` ✅. Defer until a second domain is added — the single-domain wildcard approach is correct and simpler for now.

---

#### Split Renovate Configuration (`.renovate/` directory)

Instead of a single `renovate.json5`, split config into files by concern so each section
is independently reviewable in PRs. Reference pattern: `bykaj/home-ops` uses
`allowedVersions.json5`, `autoMerge.json5`, `groups.json5`, `customManagers.json5`,
`labels.json5`, `semanticCommits.json5`, etc.

**When to do this:** defer until `renovate.json5` feels unwieldy — roughly 400+ lines, or
when adding KEDA scalers, VolSync rules, or complex `allowedVersions` blocks. As of 2026-05-22
the file is ~282 lines and well-structured; the split adds overhead without much benefit yet.

**How it actually works — important:**
This is NOT a simple file-cut. Each split file must be a valid **Renovate local preset**,
not a raw JSON5 fragment. Renovate loads them via `extends`, not by auto-scanning the directory.

**Steps to implement:**
1. Create `.renovate/` directory with one file per concern, each structured as a preset:
   ```json5
   // .renovate/groups.json5
   {
     description: "Package grouping rules",
     packageRules: [ /* grouping rules only */ ],
   }
   ```
   Suggested split for this repo:
   - `.renovate/renovate.json5` — root config: `$schema`, `extends`, `schedule`, `ignorePaths`, `ignoreDeps`, manager file-pattern overrides
   - `.renovate/groups.json5` — all `groupName` rules
   - `.renovate/autoMerge.json5` — all `automerge: true` rules
   - `.renovate/semanticCommits.json5` — commit message formatting + scope rules
   - `.renovate/labels.json5` — label rules
   - `.renovate/customManagers.json5` — regex custom manager

2. Update the root config to reference each split file via `extends`:
   ```json5
   extends: [
     "config:recommended",
     // ... other presets ...
     "local:.renovate/groups.json5",
     "local:.renovate/autoMerge.json5",
     "local:.renovate/semanticCommits.json5",
     "local:.renovate/labels.json5",
     "local:.renovate/customManagers.json5",
   ],
   ```

3. Delete the original `renovate.json5` once the root config lives at `.renovate/renovate.json5`.

**No cluster-level impact** — purely a repository ergonomics improvement. Validate by
triggering a Renovate dry-run after the split (check the Dependency Dashboard issue for errors).

---

## Completed

| Area                          | Notes                                           |
|-------------------------------|-------------------------------------------------|
| Persistent Storage (OpenEBS + Longhorn 3-replica) | OpenEBS LocalPV live; Longhorn 3-replica active since 2026-05-23; all 3 nodes have dedicated storage disks (cp-01/cp-02: Kingston SNV3S1000G, cp-03: Crucial CT2000P310SSD8); cp-02 Crucial P310 installed via M.2 A/E adapter |
| Pod Topology: scheduling concentration on cp-03   | Fixed imbalance; CoreDNS + Envoy proxies spread to 3 replicas 1/node (`DoNotSchedule`); Flux/cert-manager/ESO at 2 replicas + topology spread; stateful workloads (Prometheus/Alertmanager) accepted on cp-03 |
| Talos machine configs         | 3 CP nodes, patches, schematic registered       |
| Bootstrap go-task Taskfile    | Replaces scripts/bootstrap.sh                   |
| SOPS age key + rules          | `age.key` generated, `.sops.yaml` configured    |
| Cluster bootstrapped          | All bootstrap steps complete                    |
| kubernetes/ directory         | Helmfile + Flux structure in place              |
| Cilium                        | Running via Helmfile bootstrap                  |
| CoreDNS                       | Running via Helmfile bootstrap                  |
| cert-manager                  | Running via Helmfile bootstrap                  |
| Flux (operator + instance)    | Reconciling from private repo via SSH           |
| Renovate                      | `renovate.json5` in place; GitHub App installed; Talos/k8s tracked via `separateMinorPatch` rules (PRs target tuppr CRDs) |
| Talos + Kubernetes upgrades   | tuppr deployed; Talos v1.13.2; Kubernetes v1.36.1; upgrades now fully automated via Renovate PRs + tuppr |
| OpenEBS OCIRepository fix     | Transient timing race (HelmRelease checked source 30s before artifact was stored); forced reconcile cleared it; added `crds: CreateReplace` to HelmRelease |
| External Secrets + 1Password Connect | ESO + 1Password Connect deployed; `ClusterSecretStore` live; `external-secrets`, `onepassword-connect`, `onepassword-store` Kustomizations all Ready |
| Cluster-Level Variable Substitution | `cluster-vars` Kustomization live; `cluster-settings` ConfigMap + `cluster-secrets` SOPS Secret in `flux-system`; `substituteFrom` patch on `cluster-apps` covers all child Kustomizations |
| Global HelmRelease Defaults Patch   | Nested patch on `cluster-apps` injects `crds: CreateReplace`, `timeout: 10m`, and upgrade remediation into all HelmReleases; `CLAUDE.md` convention note updated |
| Envoy Gateway + Cilium L2 LoadBalancer | Envoy Gateway v1.7.3; `envoy-external` (10.60.0.230) + `envoy-internal` (10.60.0.231); wildcard production cert via DNS-01; HTTP→HTTPS redirect on both Gateways |
| Cloudflare Tunnel (cloudflared)        | 2-replica HA deployment in `network` namespace; `*.vwn.io` + `vwn.io` → `envoy-external`; token via ExternalSecret from 1Password |
| Flux GitHub Webhook Receiver           | `flux-receiver` Kustomization in `flux-system`; ExternalSecret token from 1Password; HTTPRoute on `envoy-external`; GitHub webhook configured — reconcile latency ~5 min → seconds |
| ExternalDNS (Split-DNS)                | `external-dns-cloudflare` (watches `envoy-external`, `--cloudflare-proxied`, `txtOwnerId: k8s`) + `external-dns-unifi` (webhook sidecar, watches all gateways + services, `txtOwnerId: k8s-internal`); shared OCIRepository `ghcr.io/home-operations/charts-mirror/external-dns` v1.21.1; CF token mapped from `API_TOKEN` → `CF_API_TOKEN` via ESO `data[]` |
| kube-prometheus-stack                  | Prometheus + Alertmanager in `observability` namespace; 20 Gi + 1 Gi Longhorn PVCs; node-exporter on all 3 nodes; full-cluster scraping (`*SelectorNilUsesHelmValues: false`); HTTPRoutes on `envoy-internal`; Grafana + receiver deferred |
| metrics-server                         | `kube-system`; HelmRelease `v3.13.0` (OCIRepository `ghcr.io/kubernetes-sigs/charts/metrics-server`); `kubectl top` and HPA resource metrics enabled; `--kubelet-insecure-tls` flag set |

> **[Monitor — cp-03 storage disk]** At boot, `nvme1` (the Crucial CT2000P310SSD8 Longhorn disk) logs `nvme nvme1: using unchecked data buffer`. This is a one-time boot message — the Crucial P310 does not advertise the NVMe "metadata-in-data-buffer" feature; the driver falls back to a simpler DMA path silently. Confirmed count of 1, no I/O errors, XFS mount clean. Watch for additional occurrences or any `I/O error` / `nvme reset` lines: `talosctl dmesg --nodes 10.60.0.203 | grep -i nvme`. Also watch for Longhorn replica faults on cp-03 specifically: `kubectl -n longhorn-system get replicas -o wide | grep cp-03`.
