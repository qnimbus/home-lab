---
name: feedback-tuppr-restart-behaviour
description: tuppr pod losing leader election causes immediate restart and may re-trigger upgrade applies
metadata:
  type: feedback
---

When tuppr loses its kube-api connection long enough to fail leader lease renewal, it exits with error code 1 (`leader election lost`). Kubernetes restarts it immediately. On reconnect, tuppr re-validates all upgrade CRs and may re-initiate machine config applies if it determines a node's Talos version doesn't match the TalosUpgrade target.

This is expected behaviour — not a bug in typical operation. However:

- A tuppr restart mid-upgrade (e.g. during rolling upgrade of 3 nodes) can cause the upgrade to resume from the current node, which means that node gets its reboot initiated after the tuppr restart.
- The Kubernetes event stream will show `node.kubernetes.io/unreachable` taints and FailedScheduling events for pods with topology spread constraints — this is expected collateral, not a second failure.
- etcd remains healthy throughout a Talos upgrade reboot because machined manages etcd independently of kubelet.

**Why:** Observed during cp-02 incident on 2026-05-28 where tuppr pod (running 4 days) lost leader election due to momentary kube-api timeout, restarted, then re-triggered Talos upgrade reboot on cp-02.
**How to apply:** When a node goes NotReady and etcd is still responding, check tuppr logs for `leader election lost` and subsequent upgrade activity before treating the NotReady as an unplanned failure.
