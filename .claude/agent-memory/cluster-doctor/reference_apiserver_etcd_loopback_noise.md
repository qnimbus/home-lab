---
name: reference_apiserver_etcd_loopback_noise
description: kube-apiserver logs a constant stream of 127.0.0.1:2379 grpc dial-cancellation warnings on this cluster even when etcd is completely healthy — do not treat as the root cause without corroborating etcd-side evidence
metadata:
  type: reference
---

Observed 2026-06-18 during a transient (self-resolved within minutes) cluster-wide
TLS-handshake-timeout incident on the API server VIP and all three CP node IPs.

Every kube-apiserver static pod, on all three CP nodes, continuously logs lines like:

```
W... logging.go:55] [core] [Channel #NNNNN SubChannel #NNNNN] grpc: addrConn.createTransport
  failed to connect to {Addr: "127.0.0.1:2379", ...}. Err: connection error: desc =
  "transport: Error while dialing: dial tcp 127.0.0.1:2379: operation was canceled"
```

and occasionally:

```
Err: connection error: desc = "transport: authentication handshake failed: context canceled"
```

This recurs on a steady ~30s cadence and accumulates into the thousands of lines over the
apiserver's uptime (confirmed on a pod running 8-32h). At first glance this looks like the
apiserver cannot reach its local etcd — a plausible root cause for an API-unreachable incident,
especially with concurrent Ceph OSD disk I/O as a tempting explanation for etcd being slow.

It is misleading. In the same incident, etcd's own logs (`talosctl logs etcd`) showed completely
normal operation throughout: fast compactions (55-70ms), small DB size (~90MB), routine
snapshot/purge cycles, and successful 3-peer hash checks every minute. `talosctl service etcd`
reported `Running`/`HEALTH OK` on all three nodes the entire time. There was no evidence of disk
contention, slow fsync, or election churn anywhere in etcd's own logs.

Conclusion: this log pattern is most likely an apiserver-internal gRPC health-check/keepalive
channel that uses an aggressively short dial context, and "operation was canceled" /
"context canceled" here describes the *client's own context* expiring — not etcd refusing or
failing to accept the connection. Treat this log pattern as background noise on this cluster
unless corroborated by etcd-side symptoms (slow apply warnings, missed heartbeats, leader
election churn, large DB size, slow fsync warnings) — checking `talosctl logs etcd` directly is
the fast way to rule it in or out.

The actual incident this was investigated under had no found root cause: by the time diagnosis
reached the "check live TLS handshake" step (`curl -k https://10.60.0.2:6443/healthz` and per-CP
IP), the API was already responding normally (~5-10ms handshakes, correct 401 on
unauthenticated request) on the VIP and all three CP IPs. Node load averages were trivial
(0.2-0.5) and memory pressure was non-existent (60-85GB available) on all three CPs at the time of
the check — ruling out resource starvation as an ongoing cause, though it cannot rule out a
transient spike that had already passed.

See also [[reference_talos_native_vip]] for a related false-lead (kube-vip pod search) hit in the
same investigation.
