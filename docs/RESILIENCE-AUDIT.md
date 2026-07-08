# Cluster Resilience Audit (FMEA) <!-- omit from toc -->

> **Living document, audit-generated** — regenerated per-component by the `resilience-audit` skill (`.claude/commands/resilience-audit.md`), not hand-maintained. Re-run a component's section after significant architecture changes to it; the skill updates that section in place rather than appending a duplicate.
> Last audited: **2026-07-08** · Components covered: 1 (pilot pass — see [Backlog](#backlog-not-yet-audited) for the rest)

This document catalogs, per cluster component, the ways it can fail: what breaks (blast radius), how we'd notice (detection), what already limits the damage (mitigation), how to recover, and — critically — whether that recovery has ever actually been exercised or is still theoretical. It does not duplicate the runbooks in [CLUSTER.md](CLUSTER.md), [QA.md](QA.md), or [ROADMAP.md](ROADMAP.md); it links to them and adds the piece those docs don't: an explicit severity/gap assessment across the whole cluster in one consistent shape.

## Contents <!-- omit from toc -->

- [Summary](#summary)
- [Rook-Ceph](#rook-ceph)
- [Backlog (not yet audited)](#backlog-not-yet-audited)
- [How to Re-Audit](#how-to-re-audit)

---

## Summary

| Component | Worst Severity | Tested | Open Gaps |
|---|---|---|---|
| Rook-Ceph | **Critical** | Mixed — single-OSD loss and the VLAN-200 network fallback are live-drilled; mon-quorum loss and concurrent multi-failure are untested | 3 |

---

## Rook-Ceph

_Last audited: 2026-07-08_

**Distributed block storage** — provides the default `ceph-block` StorageClass (`size=3`/`min_size=2`) across 10 OSDs on 5 nodes. See [CLUSTER.md → Rook-Ceph](CLUSTER.md#rook-ceph-v1196-operator-chart-rook-ceph) for full topology. `ceph-block` currently backs `kube-prometheus-stack` (Prometheus, Alertmanager, Grafana), `pgadmin`, and `victoria-logs`. Notably, **CloudNativePG deliberately does *not* use `ceph-block`** — it runs on `openebs-hostpath` with its own streaming-replication + barman PITR backup instead (see [CLUSTER.md → OpenEBS](CLUSTER.md#openebs-v440-openebs)), so Postgres is out of scope for the Ceph-specific gaps below. Operational recipes live in `ops/ceph/mod.just` (`just ceph status`, `df`, `osd-tree`, `ok-to-stop`, `osd-out`, `osd-purge`, `osd-lvm-wipe`).

| Failure Mode | Blast Radius | Detection | Existing Mitigation | Recovery Procedure | Tested | Severity |
|---|---|---|---|---|---|---|
| Single OSD/disk failure | None if within replication — Ceph auto-backfills the missing copy from the other 2 replicas; affected PVCs stay read/write throughout | `HEALTH_WARN` (osd down), ceph-mixin alerts → Alertmanager → Pushover | `size=3`/`min_size=2` absorbs 1 OSD loss with zero I/O interruption | `just ceph osd-out` → `osd-purge` → replace disk → `just ceph osd-lvm-wipe <node>` (`ops/ceph/mod.just`) | **Drilled** — worker-02 OSD disk swap, 2026-06-25 (Kingston→Crucial); worker-02 OSD onboarding, 2026-06-18 | Info |
| Storage-network (VLAN-200/bond-storage) NIC or link failure | Degraded replication throughput, not an outage — cluster stays `HEALTH_OK`/functional on the fallback VLAN | Ceph network alerts (`CephNodeNetworkPacketDrops`, noisy/misleadingly-named per [QA.md](QA.md#why-did-a-ceph-alert-cephnodenetworkpacketdrops-fire-for-packet-drops-on-a-management-nic-when-ceph-traffic-runs-on-the-storage-vlan)) + node-level link-down alerts | Fleet-wide VLAN-200 fallback path (`bond-storage` X520/X710 LACP with a tagged-VLAN escape hatch) | Documented fallback + restore procedure; silence-operator silences kept (deactivated) for reference | **Drilled** — real incident: cp-02 X520 hardware fault (2026-07-02) → fleet fallback → cp-03 replacement verified good → all 5 nodes restored to `bond-storage` (2026-07-07) | Info |
| Full-cluster **graceful** shutdown/cold-start | None — planned maintenance path | N/A (operator-initiated) | Documented flag-freeze sequence (`noout`/`norecover`/`norebalance`/`nobackfill`/`nodown`/`pause`) before shutdown, CP-first/workers-last ordering on restart | [CLUSTER.md → Full-Cluster Shutdown / Cold Start](CLUSTER.md#full-cluster-shutdown-cold-start) | **Partial** — procedure is fully documented and has an accompanying single-node maintenance drill pattern, but no session log confirms a full 5-node cold start was executed end-to-end | Warning |
| Two simultaneous OSD/node failures exceeding `min_size` | PGs with both surviving copies on the two down OSDs go **inactive** — affected `ceph-block` PVCs (Prometheus, Alertmanager, Grafana, pgadmin, victoria-logs) block I/O until a 3rd copy is available | `HEALTH_ERR`, inactive-PG alerts | Rook PDBs block *operator-initiated* double-loss (a drain is refused if it would breach redundancy) — **no protection against two unplanned/concurrent failures** (e.g. two nodes losing power together) | None documented. No off-Ceph backup exists for the `ceph-block`-backed apps listed above (`volsync` currently only covers `waha`, per `kubernetes/apps/system/volsync/ks.yaml`) | **Untested** — never drilled, no documented procedure | **Critical** |
| Mon quorum loss (2 of 3 mons down) | Total storage outage — **every** `ceph-block` PVC blocks new I/O cluster-wide (new ops require quorum even if existing mounts are unaffected momentarily) | `HEALTH_WARN`/`HEALTH_ERR` mon-down alerts | 3-mon quorum tolerates exactly 1 mon down; mons run `hostNetwork` on the management subnet, separate from OSD `cluster_network` | None documented — no mon-store-recovery runbook exists in this repo (the existing quorum-loss runbook in `CLUSTER.md` covers **etcd**, a different quorum, not Ceph mons) | **Untested** — no procedure written, no drill | **Critical** |
| Unplanned/ungraceful power loss (vs. the documented graceful path) | Unknown — Ceph is generally crash-consistent (OSD/mon journal replay), but this has never been verified against this cluster's actual hardware/disks | None — offline by definition until nodes return | None beyond Ceph's own crash-consistency guarantees; no UPS is documented for any node | Only the **graceful** shutdown/cold-start runbook exists ([CLUSTER.md](CLUSTER.md#full-cluster-shutdown-cold-start)); no "what if power just dropped" recovery runbook | **Untested** | **Critical** |
| Rook operator crash-loop or bad Helm upgrade | Operator stops reconciling `CephCluster`/`CephBlockPool` — existing data/OSDs keep serving I/O, but capacity/topology changes and CRD updates stall | Flux `HelmRelease` failure → `flux-alerts` → Alertmanager → Pushover (cluster-wide, not Ceph-specific) | Cluster-wide HelmRelease defaults: 3 retries then automatic rollback to last good revision (`kubernetes/flux/cluster/ks.yaml` patch, see CLAUDE.md) | Automatic Flux rollback; manual `just ceph status`/`osd-tree` to confirm data plane is unaffected | **Partial** — the rollback mechanism is exercised cluster-wide for other charts, but not specifically drilled for Rook-Ceph | Warning |
| Capacity exhaustion (OSDs approach full/near-full ratio) | Ceph blocks writes cluster-wide once OSDs cross the `full` threshold (not just the affected pool) | `ceph df`/`ceph osd df` (manual only) — no confirmed proactive near-full alert wired to Alertmanager | None proactive — no capacity-planning cadence or quota enforcement found | Manual: free space or add capacity (`osdsPerDevice`/more nodes); no documented step-by-step | **Untested** | Warning |

---

## Backlog (not yet audited)

- **etcd / control-plane quorum** — the etcd-loss runbook already exists in `CLUSTER.md`, but it hasn't been run through this FMEA lens (blast radius framing, severity, cross-check against the graceful vs. unplanned distinction found in the Rook-Ceph pass above).
- **Flux/GitOps reconciliation** — what happens if `source-controller` (single replica, no HA per `CLUSTER.md`) or the Git remote itself is unreachable; how the cluster behaves mid-reconcile.
- **Network core (VLANs, kube-vip VIP, Cilium)** — VIP failover (`cp-01`/`cp-02`/`worker-01` compete), Cilium agent loss, pod-CIDR/service-CIDR issues. Partially covered by the Rook-Ceph network row above but deserves its own pass.
- **CoreDNS** — cluster DNS single point of failure characteristics, replica count, upstream resolver fallback.
- **External Secrets + 1Password Connect** — `onepassword-connect` runs as a single replica (per `CLUSTER.md`); what happens if it's unreachable, and whether already-synced Secrets keep working.
- **CloudNativePG** — the Postgres backup/PITR path is *already* the best-documented recovery story in the repo (live-drilled twice — see `ROADMAP.md`); worth formalizing into this FMEA shape mainly to capture what's still a gap (e.g. `openebs-hostpath` node-local capacity exhaustion).
- **Ingress/edge (envoy-gateway, cloudflared, external-dns)** — external reachability failure modes: what happens if the tunnel drops, DNS records go stale, or the gateway pod is lost.
- **Talos node OS layer** — boot failures beyond the documented M920q NVMe issue, disk failure on a non-OSD (system) disk, Talos upgrade failure mid-fleet.
- **Alerting pipeline itself** — if `kube-prometheus-stack`/Alertmanager/Pushover routing breaks, every other component's "Detection" cell in this document silently stops being true. Arguably worth auditing early since it undermines every other section's mitigation claims.

## How to Re-Audit

Run the `resilience-audit` skill (`.claude/commands/resilience-audit.md`) with a component name to refresh its section, or pick the next item from the Backlog above to add a new one.
