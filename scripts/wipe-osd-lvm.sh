#!/bin/bash
# Wipe stale Ceph LVM on a running Talos node OSD disk.
# Runs inside a privileged pod with /dev and /run mounted from the host.
# DISK_BYID env var: the /dev/disk/by-id/<...> path of the OSD disk to wipe.
#
# Strategy: write directly to the raw block device, bypassing the DM layer.
# Talos's block.LVMActivationController locks the entire VG (physical disk +
# all LVs) as a unit — dmsetup remove and talosctl wipe disk both refuse or
# hang. dd, wipefs, and sgdisk open the physical fd with O_RDWR, which the
# kernel allows even when a DM device is mapped on top.
#
# After this script exits, ceph-* dm devices remain in the kernel DM table
# until the node is rebooted. Reboot before enabling Rook-Ceph if DM devices
# were present (see QA.md → "Why does task talos:wipe-ceph-osds-live fail?").
# Talos v1.14 will add 'talosctl wipe vg' to handle this natively.
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

# Clear all remaining filesystem and partition signatures.
# wipefs and sgdisk also write directly to the physical device — they do not
# go through the DM layer and succeed even with active dm-* holders.
wipefs -a "${DISK}"
sgdisk --zap-all "${DISK}"

if [ "${DM_PRESENT}" = "true" ]; then
  echo "=== DONE: ${DISK} is clean (reboot this node before Rook-Ceph OSD provisioning) ==="
else
  echo "=== DONE: ${DISK} is clean ==="
fi
