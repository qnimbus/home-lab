#!/bin/bash
# Wipe stale Ceph LVM on a running Talos node OSD disk.
# Runs inside a privileged pod with /dev and /run mounted from the host.
# DISK_BYID env var: the /dev/disk/by-id/<...> path of the OSD disk to wipe.
#
# Strategy: write directly to the raw block device, bypassing the DM layer.
# Talos's block.LVMActivationController locks the entire VG (physical disk +
# all LVs) as a unit — dmsetup remove and talosctl wipe disk both refuse or
# hang. `dd` opens the physical fd O_RDWR (no O_EXCL), which the kernel allows
# even when a DM device is mapped on top — so it can zero the LVM PV header.
# `wipefs -a` and `sgdisk`, however, open O_EXCL and FAIL with EBUSY while a
# ceph-* dm holder is active; that is expected and non-fatal (see below) — the
# queued reboot clears the DM table and the zeroed PV header keeps the disk clean.
#
# After this script exits, ceph-* dm devices remain in the kernel DM table
# until the node is rebooted. When they were present this script prints the
# sentinel line "REBOOT_REQUIRED=1"; the calling task (talos:wipe-ceph-osds-live)
# parses that and reboots the node automatically — staggered and etcd-quorum-safe
# — so no manual reboot is needed (see QA.md → "Why does task
# talos:wipe-ceph-osds-live fail?"). Talos v1.14 will add 'talosctl wipe vg'
# to handle this natively and remove the reboot entirely.
set -e

DISK=$(readlink -f "${DISK_BYID}")
echo "=== Wiping Ceph LVM on ${DISK} (${DISK_BYID}) ==="

DM_PRESENT=false
if ls /dev/mapper/ceph--* >/dev/null 2>&1; then
  DM_PRESENT=true
  echo "  NOTE: ceph-* dm devices are active — node reboot required after this wipe"
fi

# Zero the LVM PV header on the raw physical device.
# Destroys the PV signature the LVMActivationController reads on boot.
echo "  Zeroing LVM PV metadata (first 16 MiB of ${DISK})..."
dd if=/dev/zero of="${DISK}" bs=1M count=16 oflag=direct conv=notrunc 2>&1

# Clear residual filesystem/partition signatures on the raw device.
if [ "${DM_PRESENT}" = "true" ]; then
  # A ceph-* dm holder is still mapped, so wipefs/sgdisk (O_EXCL) will fail EBUSY.
  # Emit the reboot sentinel FIRST — before the steps that can fail — so the calling
  # task (talos:wipe-ceph-osds-live) always sees it and reboots this node. The reboot
  # clears the kernel DM table; with the PV header already zeroed the disk comes up
  # clean, so the signature clear below is best-effort only and must not abort (set -e).
  echo "REBOOT_REQUIRED=1"
  wipefs -a "${DISK}" 2>&1 || echo "  (wipefs deferred — device busy under active dm-*; clears on reboot)"
  sgdisk --zap-all "${DISK}" 2>&1 || echo "  (sgdisk deferred — device busy under active dm-*; clears on reboot)"
  echo "=== DONE: PV header zeroed on ${DISK}; node reboot queued to clear stale dm-* entries ==="
else
  # No dm holder — the device is free, so these must succeed (keep them fatal).
  wipefs -a "${DISK}"
  sgdisk --zap-all "${DISK}"
  echo "=== DONE: ${DISK} is clean ==="
fi
