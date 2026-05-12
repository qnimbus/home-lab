# Cluster Q&A — Operational Knowledge Log

Concise answers to questions that came up during cluster operation. Each entry captures the *why* so it's useful months later.

---

## Networking

### Why does the Talos console for cp-03 show many `eth0: renamed from tmp<random>` kernel messages?

**Short answer:** Normal CNI activity — not errors.

**Detail:** Each message represents Cilium creating a veth pair for a newly scheduled pod. The kernel assigns a temporary name (`tmp<hex>`) to the host-side interface; the CNI then renames the pod-side end to `eth0` inside the pod's network namespace. The kernel logs that rename at the host level, which is why it surfaces in the Talos console.

Bursts of these messages (e.g. many within a second) indicate pods being created or rescheduled in rapid succession — common after a DaemonSet rollout, Longhorn stabilising after initial deployment, or a deployment restart. cp-03 (32c, 92 GB) attracts the most pods due to scheduler resource-fit, so it generates these more frequently than the M920Q nodes.

**Actionable only if:** the same burst pattern repeats continuously over minutes, which would suggest a pod CrashLoopBackOff cycling through restarts. In that case, check `kubectl get pods -A | grep -v Running`.
