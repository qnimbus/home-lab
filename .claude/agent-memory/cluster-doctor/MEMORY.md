# Memory Index

- [Node Disk Inventory](reference_disk_inventory.md) — STALE (3-CP/Longhorn era, pre Rook-Ceph + 5-node expansion) — verified per-node NVMe assignments, needs re-verification
- [Talos native VIP, not kube-vip pod](reference_talos_native_vip.md) — VIP is Talos's built-in networkInterfaces.vip feature; no kube-vip pod/DaemonSet exists on this cluster — don't search kube-system for it
- [apiserver-to-etcd loopback grpc noise](reference_apiserver_etcd_loopback_noise.md) — constant 127.0.0.1:2379 dial-cancel warnings in kube-apiserver logs are background noise even when etcd is fully healthy; corroborate with etcd's own logs before treating as root cause
- [Envoy Gateway + external-dns topology](reference_envoy_gateway_external_dns_topology.md) — gateway-name flag doesn't scope the `service` source; Gateway API ResolvedRefs doesn't validate cert SAN coverage; DNS orphan-record forensics pattern
