# Cluster Troubleshooting — Kubernetes Upgrade Notes

**Last updated:** 2026-05-13
**Status:** ✅ Resolved — cluster running v1.36.0; next target: v1.37.x
**Talos version:** `v1.13.0` (stable throughout)

---

## Before you begin — tooling

This runbook uses two complementary tools. Use them in preference to raw `kubectl` wherever possible.

### kubernetes-debugger agent

Invoke the agent any time a phase produces unexpected output or a step fails. It is Talos-aware, knows this cluster's topology, and will guide diagnosis without guessing.

To invoke: type `@kubernetes-debugger` in Claude Code and describe the symptom.

Use the agent at these natural gates (marked **[AGENT]** in the phases below):
- Before starting, to verify current cluster state matches the baseline table
- After any phase that touches a running workload or node config
- Whenever a `talosctl` or `kubectl` command returns unexpected output

### kubernetes MCP server

The kubernetes MCP server provides structured, authenticated cluster queries without shelling out. Commands marked **[MCP]** below can be run directly as MCP tool calls instead of via `kubectl`.

Available MCP tools for this runbook:

| MCP tool | Replaces |
|----------|---------|
| `resources_list apiVersion=v1 kind=Node` | `kubectl get nodes -o wide` |
| `resources_list apiVersion=batch/v1 kind=Job namespace=system-upgrade` | `kubectl get jobs -n system-upgrade` |
| `pods_list_in_namespace namespace=system-upgrade` | `kubectl get pods -n system-upgrade` |
| `resources_list apiVersion=upgrade.coreos.com/v1alpha1 kind=KubernetesUpgrade` | `kubectl get kubernetesupgrade -n system-upgrade` |
| `resources_list apiVersion=upgrade.coreos.com/v1alpha1 kind=TalosUpgrade` | `kubectl get talosupgrade -n system-upgrade` |
| `events_list namespace=system-upgrade` | `kubectl get events -n system-upgrade --sort-by=.lastTimestamp` |
| `pods_log namespace=system-upgrade pod=<name>` | `kubectl logs -n system-upgrade <pod>` |
| `nodes_top` | `kubectl top nodes` |

`talosctl` commands have no MCP equivalent — always run those via Bash.

---

## Current Cluster State

| Component | Version | State |
|-----------|---------|-------|
| Talos | v1.13.0 | ✅ Running on all 3 nodes |
| kube-apiserver | v1.36.0 | ✅ Stable on all 3 nodes |
| kube-controller-manager | v1.36.0 | ✅ Running |
| kube-scheduler | v1.36.0 | ✅ Running |
| kubelet | v1.36.0 | ✅ Running |
| etcd | v3.6.9 (Talos-managed) | ✅ 3-member cluster, healthy |
| `KubernetesUpgrade` CRD | target `v1.36.0` | ✅ Completed |
| `TalosUpgrade` CRD | target `v1.13.0` | ✅ Completed |

**Git state:** `talenv.yaml` and `kubernetesupgrade.yaml` both declare `v1.36.0`. In sync.

---

## Next Session: v1.37.0 Upgrade Plan

Work through these phases in order. Do not skip ahead — each phase is a prerequisite for the next.

---

### Phase 0 — Verify baseline **[AGENT] [MCP]**

Before touching anything, confirm the cluster matches the Current Cluster State table above.

**Via MCP:**
```
resources_list  apiVersion=v1  kind=Node
```
Expected: 3 nodes (`talos-cp-01/02/03`), all `Ready`, `VERSION = v1.36.0`.

**Via Bash — all 3 apiservers CONTAINER_RUNNING on v1.36.0:**
```bash
talosctl -e 10.60.0.201,10.60.0.202,10.60.0.203 \
  -n 10.60.0.201,10.60.0.202,10.60.0.203 \
  --talosconfig talos/clusterconfig/talosconfig \
  containers --kubernetes | grep kube-apiserver | grep -v pause
```
Expected: 3 lines, all `CONTAINER_RUNNING`, image tag `v1.36.0`.

**Via Bash:**
```bash
kubectl get kubernetesupgrade,talosupgrade -n system-upgrade -o wide
```
Expected: both `Completed`, targets `v1.36.0` / `v1.13.0`.

If any of these differ from expectations, **invoke `@kubernetes-debugger`** before continuing.

---

### Phase 1 — Pre-flight checks

**Confirm kubelet image is available:**
```bash
token=$(curl -s "https://ghcr.io/token?scope=repository:siderolabs/kubelet:pull&service=ghcr.io" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
curl -o /dev/null -sw "%{http_code}\n" \
  -H "Authorization: Bearer ${token}" \
  "https://ghcr.io/v2/siderolabs/kubelet/manifests/v1.37.0"
```
Expected: `200`. If `404`, the image has not been built yet — do not proceed.

**Dry-run the component upgrade to check for removed APIs or flags:**
```bash
talosctl -e 10.60.0.201 -n 10.60.0.201 \
  --talosconfig talos/clusterconfig/talosconfig \
  upgrade-k8s --to v1.37.0 --dry-run
```
Expected: no errors about removed feature gates or API versions. If issues are reported, resolve them in `talos/patches/controller/cluster.yaml` before proceeding.

> Talos v1.13.0 is compatible with Kubernetes v1.36.

---

### Phase 2 — Staggered apiserver upgrade (cp-01 → cp-02 → cp-03) **[AGENT]**

Do **not** use `talosctl upgrade-k8s` for the apiserver — it patches all 3 nodes in rapid succession.
Use `talosctl patch mc` per node with a **strategic merge patch** (not JSON RFC 6902 — multi-doc configs reject it).

**cp-01 (10.60.0.201):**
```bash
talosctl -e 10.60.0.201 -n 10.60.0.201 \
  --talosconfig talos/clusterconfig/talosconfig \
  patch mc \
  --patch '{"cluster":{"apiServer":{"image":"registry.k8s.io/kube-apiserver:v1.37.0"}}}'
```

Wait for v1.37.0 to appear as `CONTAINER_RUNNING` with a **stable PID for at least 2 minutes**:
```bash
talosctl -e 10.60.0.201 -n 10.60.0.201 \
  --talosconfig talos/clusterconfig/talosconfig \
  containers --kubernetes | grep kube-apiserver | grep -v pause
```
Expected: `registry.k8s.io/kube-apiserver:v1.37.0   <pid>   CONTAINER_RUNNING` — same PID across multiple checks.

Also verify HTTP health and all 3 nodes still Ready:
```bash
curl -sk -o /dev/null -w "cp-01 HTTP %{http_code}\n" https://10.60.0.201:6443/healthz
```
```
resources_list  apiVersion=v1  kind=Node
```

> **[AGENT]** If cp-01's apiserver enters a crash loop — **stop immediately**, do not patch cp-02 or cp-03. Invoke `@kubernetes-debugger` with the output of:
> `talosctl -e 10.60.0.201 -n 10.60.0.201 --talosconfig talos/clusterconfig/talosconfig logs --kubernetes kube-system/kube-apiserver-talos-cp-01:kube-apiserver 2>&1 | tail -60`

Repeat the same patch + 2-minute stability verification for **cp-02 (10.60.0.202)** then **cp-03 (10.60.0.203)** in order.

---

### Phase 3 — Upgrade remaining components

Once all 3 apiservers are stable on v1.37.0, upgrade controller-manager, scheduler, and kubelets.
`upgrade-k8s` detects the apiserver is already at v1.37.0 and skips it:

```bash
talosctl -e 10.60.0.201 -n 10.60.0.201 \
  --talosconfig talos/clusterconfig/talosconfig \
  upgrade-k8s --to v1.37.0
```

Verify all nodes Ready after completion:
```bash
kubectl get nodes -o wide
```
Expected: all 3 nodes `Ready`, `VERSION = v1.37.0`.

---

### Phase 4 — Sync Git and clean machine configs **[MCP]**

Update these two files, then regenerate and apply:

| File | Field | New value |
|------|-------|-----------|
| `talos/talenv.yaml` | `kubernetesVersion` | `v1.37.0` |
| `kubernetes/apps/system-upgrade/tuppr/upgrade/kubernetesupgrade.yaml` | `spec.kubernetes.version` | `v1.37.0` |

```bash
task talos:genconfig
```

Apply to **one node at a time** — if the apply triggers a reboot, wait for `Ready` before proceeding:
```bash
task talos:apply IP=10.60.0.201
# wait for Ready if rebooted
task talos:apply IP=10.60.0.202
# wait for Ready if rebooted
task talos:apply IP=10.60.0.203
```

> **tuppr cleanup required before reconciling.** After `upgrade-k8s` advances the cluster ahead of Git, tuppr sees a mismatch and starts failing "downgrade" jobs. Before committing and pushing, delete the stuck resource and all jobs so Flux can recreate it cleanly:
> ```bash
> kubectl delete kubernetesupgrade kubernetes -n system-upgrade
> kubectl delete jobs -n system-upgrade --all
> ```
> Then commit, push, and reconcile:

```bash
flux reconcile source git flux-system && flux reconcile kustomization tuppr-upgrade
```

Final verification:
```bash
kubectl get kubernetesupgrade,talosupgrade -n system-upgrade -o wide
```
Expected: both `Completed`, targets `v1.37.0` / `v1.13.0`.

---

## Lessons Learned — v1.34.7 Incident (2026-05-12)

### gRPC connection flood → staggered apiserver upgrades required

`kube-apiserver v1.34.7` opens ~100 gRPC channels to etcd simultaneously at startup. This overwhelms etcd's TLS handshake queue, causing the `rbac/bootstrap-roles` PostStartHook to time out fatally. On three nodes upgraded in rapid succession the backoff timers synchronise, creating waves that prevent recovery indefinitely.

**Rule:** Always upgrade the apiserver one node at a time via `talosctl patch mc`, with a 2-minute stable-PID window before touching the next node. This applies to v1.34+ and should be assumed for v1.35 until proven otherwise.

### Strategic merge patches — not JSON RFC 6902

talhelper v1.12+ generates multi-document machine configs. `talosctl patch mc` rejects JSON RFC 6902 patches (array of `{op, path, value}` objects) against multi-doc configs.

**Rule:** Always use the strategic merge form:
```bash
--patch '{"cluster":{"apiServer":{"image":"registry.k8s.io/kube-apiserver:v1.35.4"}}}'
```

### Feature gate audit before each minor upgrade

`MutatingAdmissionPolicy=true` and `admissionregistration.k8s.io/v1alpha1` runtime-config were both removed in v1.34. Leaving them in `talos/patches/controller/cluster.yaml` would have caused an "unknown feature gate" startup error on any v1.34+ apiserver.

**Rule:** Before each minor upgrade, check the target release notes for removed feature gates and deprecated API groups. Run `talosctl upgrade-k8s --dry-run` — it will flag removed flags and API versions before any change is made.

### Apply-with-reboot is staggered — same discipline as apiserver patches

When `task talos:apply` reports "Applied configuration with a reboot", all 3 nodes rebooting simultaneously risks losing etcd quorum (3-node cluster needs 2 members).

**Rule:** Apply configs one node at a time and wait for `Ready` before proceeding to the next, even for non-apiserver config changes that require a reboot.

---

## Root Cause (v1.34.7 incident — historical reference)

`kube-apiserver v1.34.7` opens ~100 gRPC channels to etcd **simultaneously at startup**
(channels #1–#108 visible in logs within the first 100 ms). This overwhelms etcd's TLS
handshake queue even on a **single node** — it is not a multi-node thundering-herd issue.

The TLS handshake failures delay the internal etcd client, which delays informer cache
sync, which causes the RBAC bootstrap PostStartHook to time out fatally:

```
F0512 hooks.go:204  PostStartHook "rbac/bootstrap-roles" failed:
    unable to initialize roles: timed out waiting for the condition
```

`F` = Fatal. The kubelet restarts the container with exponential backoff. The backoff
timers on three nodes re-synchronise over time, causing periodic thundering-herd waves
that prevent the multi-node cluster from ever reaching a stable state.

**What was NOT the cause:**
- Talos v1.13.0 — stable throughout; etcd, kubelet, and containerd never failed
- etcd data corruption — 3-member cluster maintained quorum throughout
- Feature gate flags (`MutatingAdmissionPolicy=true`, `v1alpha1` runtime-config) — admission
  controllers loaded successfully on every startup attempt; these were a red herring

---

## Diagnostic Commands

Commands marked **[MCP]** can be run as MCP tool calls instead of raw kubectl. Commands marked **[Bash]** require the terminal — they use talosctl or have no MCP equivalent.

```bash
# [MCP] resources_list apiVersion=v1 kind=Node
# — or via Bash:
kubectl get nodes -o wide

# [Bash] Check all apiserver container states and versions
talosctl -e 10.60.0.201,10.60.0.202,10.60.0.203 \
  -n 10.60.0.201,10.60.0.202,10.60.0.203 \
  --talosconfig talos/clusterconfig/talosconfig \
  containers --kubernetes | grep kube-apiserver | grep -v pause

# [MCP] pods_log namespace=kube-system pod=kube-apiserver-talos-cp-01
# — or via Bash (full crash log from a specific node):
talosctl -e <node-ip> -n <node-ip> \
  --talosconfig talos/clusterconfig/talosconfig \
  logs --kubernetes kube-system/kube-apiserver-<hostname>:kube-apiserver

# [Bash] Check etcd health (no MCP equivalent for talosctl etcd)
talosctl -e 10.60.0.201 -n 10.60.0.201 \
  --talosconfig talos/clusterconfig/talosconfig etcd status

# [Bash] Bypass VIP when it is down
kubectl --server=https://10.60.0.201:6443 --insecure-skip-tls-verify get nodes

# [Bash] Check apiserver HTTP health per node (401 = up; 000 = down)
for ip in 10.60.0.2 10.60.0.201 10.60.0.202 10.60.0.203; do
  code=$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 3 \
    "https://${ip}:6443/healthz")
  echo "apiserver ${ip} → HTTP ${code}"
done

# [Bash] Check kubelet image availability (authenticated — unauthenticated always returns 401)
token=$(curl -s "https://ghcr.io/token?scope=repository:siderolabs/kubelet:pull&service=ghcr.io" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
curl -o /dev/null -sw "%{http_code}\n" \
  -H "Authorization: Bearer ${token}" \
  "https://ghcr.io/v2/siderolabs/kubelet/manifests/<version>"
# 200 = exists, 404 = not built by siderolabs

# [MCP] events_list namespace=system-upgrade
# — shows all recent tuppr/job events:
kubectl get events -n system-upgrade --sort-by=.lastTimestamp
```

---

## kubelet Image Availability (as of 2026-05-13)

siderolabs does NOT build `ghcr.io/siderolabs/kubelet` for every Kubernetes upstream patch.

| Minor | Latest available |
|-------|-----------------|
| v1.33 | v1.33.11 ✅ |
| v1.34 | v1.34.7 ✅ |
| v1.35 | v1.35.4 ✅ (v1.35.5 was 404 as of 2026-05-13) |
| v1.36 | v1.36.0 ✅ (v1.36.1 was 404 as of 2026-05-13) |
