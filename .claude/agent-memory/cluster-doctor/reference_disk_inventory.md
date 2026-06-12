---
name: reference_disk_inventory
description: Verified per-node NVMe device assignments — system disk vs Longhorn storage disk on all three control-plane nodes (last verified 2026-05-13)
metadata:
  type: reference
---

Verified via `talosctl get disks` + `talosctl get mounts` on 2026-05-13.

The system disk is always identifiable as the device whose p4 partition is mounted as EPHEMERAL (/var).
The Longhorn storage disk has p1 mounted at /var/mnt/longhorn-storage.

## cp-01 (10.60.0.204, Lenovo M920Q #1)

| Device   | Model                    | Size  | Role                                    |
|----------|--------------------------|-------|-----------------------------------------|
| nvme0n1  | IRP-SSDPR-P44N-01T-30    | 1 TB  | Longhorn storage (/var/mnt/longhorn-storage, p1) |
| nvme1n1  | KINGSTON SNV3S1000G       | 1 TB  | Talos system disk (EPHEMERAL /var, p4)  |

Note: physical slot order is reversed from user's expectation — the Kingston (nvme1n1) is the system disk, the GoodRam IRDM PRO NANO (nvme0n1) is the Longhorn disk.

## cp-02 (10.60.0.205, Lenovo M920Q #2)

| Device   | Model               | Size  | Role                                   |
|----------|---------------------|-------|----------------------------------------|
| nvme0n1  | KINGSTON SNV3S1000G | 1 TB  | Talos system disk (EPHEMERAL /var, p4) |

Only one NVMe present. No Longhorn storage disk installed yet. Roadmap: install second drive to enable 3-replica Longhorn.

## cp-03 (10.60.0.201, Minisforum MS-A2)

| Device   | Model              | Size  | Role                                    |
|----------|--------------------|-------|-----------------------------------------|
| nvme0n1  | AirDisk 128GB SSD  | 128GB | Talos system disk (EPHEMERAL /var, p4)  |
| nvme1n1  | CT2000P310SSD8     | 2 TB  | Longhorn storage (/var/mnt/longhorn-storage, p1) |

CT2000P310SSD8 is a Crucial P310 2TB.
