---
name: project-cp02-notready-20260528
description: Root cause analysis for cp-02 NotReady event at 17:50 UTC on 2026-05-28
metadata:
  type: project
---

## Incident: talos-cp-02 NotReady at ~17:50 UTC on 2026-05-28

### Timeline

- **17:43 UTC**: tuppr pod (running since 2026-05-24) last validated upgrade CRs successfully.
- **17:49:27 UTC**: tuppr lost leader election lease — kube-api connection timed out (`net/http: request canceled, Client.Timeout exceeded`). Pod exited with error code 1 (`leader election lost`).
- **17:49:28 UTC**: Kubernetes restarted the tuppr pod (restart count went to 1).
- **17:50:04 UTC**: Newly-started tuppr validated TalosUpgrade CR targeting v1.13.2. This re-triggered a machine config apply to cp-02 (the node that still needed its Talos upgrade — TalosUpgrade CR shows nodes were upgraded sequentially).
- **~17:50-19:12 UTC**: cp-02 NotReady with taints `node.kubernetes.io/unreachable:NoSchedule|NoExecute`. Etcd remained online (etcd is managed by Talos machined, persists through kubelet downtime).
- **17:55-18:00 UTC**: FailedScheduling events for pods that had topology spread constraints requiring cp-02.
- **18:01 UTC onward**: FluxInstance reconciliation failures (helm-controller, notification-controller evicted from cp-02).
- **19:12:09 UTC**: cp-02 completed reboot, kubelet came online (new boot-id: `2b46c536-1b32-4db4-b94a-a5628efd4e73`).
- **19:12:16 UTC**: NodeReady event; all taints cleared.
- **19:13 UTC**: Longhorn disk schedulable.

### Root Cause

The cp-02 NotReady was caused by a **planned Talos v1.13.2 upgrade reboot** initiated by tuppr after its pod restarted. The upgrade itself was healthy and expected — cp-02 was the last node in the rolling upgrade sequence. The reboot took approximately 82 minutes, which is longer than typical but may include the time for the machine config to be applied before the actual reboot.

The previous tuppr pod had been running since 2026-05-24 (4 days). Its crash was caused by a momentary kube-api connectivity interruption that caused leader election renewal to time out. This is a tuppr operational detail, not a cluster failure.

### Post-recovery State

- All three nodes Ready, no taints
- All three etcd members are voters (no learners)
- All Flux Kustomizations reconciled successfully by ~18:55 UTC
- FluxInstance health checks recovered after cp-02 came back
- Longhorn disk and node both schedulable on cp-02

### What to watch for next time

- tuppr restarts are not inherently dangerous, but if the upgrade CRs are already completed, re-validation should be a no-op. If tuppr re-triggers upgrades on already-upgraded nodes, that indicates a bug.
- The 82-minute NotReady window is longer than expected for a Talos reboot (normally 5-10 min). Worth checking if there was a delay between config apply and actual reboot initiation.

**Why:** Documented to distinguish planned upgrade reboots from spontaneous failures in future incidents.
**How to apply:** When cp-02 goes NotReady and etcd is still responding, first check if tuppr is in an active upgrade phase before escalating.
