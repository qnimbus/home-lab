# Memory Index

- [Cluster Version State](project_cluster_versions.md) — Talos v1.13.2 / K8s v1.36.1 on all 3 nodes as of 2026-05-28; upgraded via tuppr
- [cp-02 NotReady Incident 2026-05-28](project_cp02_notready_20260528.md) — Root cause: tuppr pod lost kube-api connection, crashed, restarted, triggered machine config re-apply which rebooted cp-02 for Talos v1.13.2 upgrade
- [tuppr Restart Behaviour](feedback_tuppr_restart_behaviour.md) — tuppr losing leader election causes immediate pod restart; on reconnect it re-validates upgrade CRs and may re-trigger applies if node versions don't match
- [Etcd Member State](project_etcd_members.md) — All 3 members are voters (no learners); peer URLs use mgmt subnet 10.60.0.x
- worker-02's recurring hard-downs (5+ occurrences, 06-02→06-21) — RESOLVED 2026-06-22, root cause was a failing external power brick (MemTest86 hardware isolation), now replaced. Full writeup: `docs/history/cp02-worker02-hardware-faults.md` in the repo. Do not re-investigate as a node/Talos-layer fault if it resurfaces — check the brick first.
- [2026-08-19 e1000e CRC link flap](project_20260819_e1000e_crc_link_flap.md) — cp-03 stuck at 10Mbit fixed by reboot (now 1000Mbit, cluster/etcd healthy); worker-02 steady CRC rate at correct gigabit still needs physical cable/connector inspection
