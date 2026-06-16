#!/bin/bash
# Wipe stale Ceph LVM on a running Talos node OSD disk.
# Runs inside a privileged pod with /dev and /run mounted from the host.
# DISK_BYID env var: the /dev/disk/by-id/<...> path of the OSD disk to wipe.
set -e

DISK=$(readlink -f "${DISK_BYID}")
echo "=== Wiping Ceph LVM on ${DISK} (${DISK_BYID}) ==="

# Step 1: remove all ceph-* device-mapper targets so LVM VGs can be torn down
find /dev/mapper -maxdepth 1 -name 'ceph--*' \
  -exec dmsetup remove --force {} \; 2>/dev/null || true
sleep 1

# Step 2: deactivate and remove all ceph-* VGs (discovered dynamically)
for vg in $(vgs --noheadings -o vg_name 2>/dev/null | grep 'ceph-' | tr -d ' '); do
  echo "  removing VG: ${vg}"
  vgchange -an "${vg}" 2>/dev/null || true
  vgremove -ffy "${vg}" 2>/dev/null || true
done || true

# Step 3: remove PV label and zero all disk signatures
pvremove -ffy "${DISK}" 2>/dev/null || true
wipefs -a "${DISK}"
sgdisk --zap-all "${DISK}"
echo "=== DONE: ${DISK} is clean ==="
