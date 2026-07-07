---
name: node-exporter-duplicate-mountpoint-alerts
description: Talos machine.files writes under /etc create phantom duplicate node_filesystem_* mountpoint rows sharing the real partition's device/values
metadata:
  type: reference
---

Any Talos `machine.files` entry with `path: /etc/<file>` (e.g. `talos/patches/global/machine-files.yaml`'s
`/etc/nfsmount.conf` overwrite, added during the VolSync NFS-defaults work) is **not a separate
mount** — `talosctl get mounts` only ever shows `EPHEMERAL` (`/var`) and `u-local-hostpath`
(`/var/mnt/local-hostpath`) per node. `/etc` lives on the same EPHEMERAL-backed overlay as `/var`.

However, node-exporter's filesystem collector still emits a **separate `mountpoint` label** for
files it discovers under distinct paths in `/proc/mounts`-adjacent enumeration, producing two
"mountpoints" — `/var` and `/etc/nfsmount.conf` (or whatever bind-style path) — for the *same*
`device` (`/dev/nvme1n1pN`) with byte-for-byte identical `node_filesystem_size_bytes` /
`_free_bytes` / `_avail_bytes` values. Any size/capacity-based alert rule that doesn't dedupe on
`device` (e.g. ceph-mixin's `CephNodeDiskspaceWarning`, which only groups on
`(cluster, instance)` + joins `nodename`) fires **twice simultaneously, with identical
`predict_linear` values**, for what is one underlying condition.

Confirmed via direct query during the 2026-06-23 worker-02 incident:
```
node_filesystem_size_bytes{instance="10.60.0.205:9100",device="/dev/nvme1n1p4"}
  -> two series, mountpoint="/var" and mountpoint="/etc/nfsmount.conf", identical value
```
Both `ALERTS{alertname="CephNodeDiskspaceWarning"}` series had identical `startsAt` timestamps.

**Diagnostic shortcut:** if a Ceph/node disk-space alert fires as an exact-duplicate pair sharing
`device` and `nodename` but different `mountpoint`, treat it as one incident, not two. Check
`talconfig.yaml`/`talos/patches/**/machine-files.yaml` for any `/etc/*` file writes — those are
the likely source of the phantom second mountpoint.

See also [[project_worker02_disk_pressure_burst]] for the specific 2026-06-22/23 incident this was
diagnosed under, and [[reference_disk_inventory]] (stale, needs re-verification) for per-node
EPHEMERAL partition sizing context.
