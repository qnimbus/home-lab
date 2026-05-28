---
name: project-cluster-versions
description: Current verified Talos and Kubernetes versions across all three nodes
metadata:
  type: project
---

As of 2026-05-28, all three nodes run:

- Talos: v1.13.2 (upgraded from v1.13.0 on 2026-05-15 via tuppr TalosUpgrade CR)
- Kubernetes: v1.36.1 (upgraded from v1.36.0 on 2026-05-15 via tuppr KubernetesUpgrade CR)
- Kernel: 6.18.29-talos (amd64)
- containerd: v2.2.3

Both TalosUpgrade and KubernetesUpgrade CRs show phase=Completed.

**Why:** Observed live during cp-02 incident investigation on 2026-05-28.
**How to apply:** Use these versions when diagnosing version skew issues or checking talosctl compatibility (client is v1.13.0, server is v1.13.2 — within acceptable ±1 minor skew).
