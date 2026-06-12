---
name: project-etcd-members
description: etcd member IDs and voter/learner state as of 2026-05-28
metadata:
  type: project
---

As of 2026-05-28 (verified via `talosctl etcd members --nodes 10.60.0.201`):

| Member ID          | Hostname     | Peer URL                      | Learner |
|--------------------|--------------|-------------------------------|---------|
| 654effef1e8c668d   | talos-cp-03  | https://10.60.0.201:2380      | false   |
| 77310cfc912f87ab   | talos-cp-02  | https://10.60.0.205:2380      | false   |
| a5a07a9260dd4f06   | talos-cp-01  | https://10.60.0.204:2380      | false   |

All three members are full voters. No learner state. Peer URLs use the management subnet (10.60.0.x), not the storage subnet.

**Why:** Recorded to have baseline member IDs for quorum troubleshooting. The historical cp-03 learner issue (noted in agent instructions) has been resolved.
**How to apply:** If an etcd member goes missing from the list or shows learner=true, that indicates a quorum risk requiring immediate attention.
