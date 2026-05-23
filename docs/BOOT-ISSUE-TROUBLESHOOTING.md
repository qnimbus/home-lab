## Lenovo M920q: Booting from NVMe in A+E WiFi Slot

The M920q's A+E WiFi slot NVMe **won't appear as a selectable boot device in BIOS** — this is a known limitation [^1][^2]. The workaround is to remove competing boot entries so the firmware falls through to the UEFI fallback boot path on your A+E slot drive.

---

### Step 1: Remove Old UEFI Boot Entries

Two approaches depending on what tools are available in your live environment.

#### Option A: efibootmgr (preferred, requires network to install on Alpine)

Boot from a **live Linux USB** (any distro works), then use `efibootmgr`:

```bash
# List all boot entries
efibootmgr -v

# Example output:
# Boot0000* Talos Linux    HD(1,GPT,...)/File(\EFI\systemd\systemd-bootx64.efi)
# Boot0001* ISO Boot       ...
# Boot0002* ubuntu         ...

# Delete entries by number (repeat for each unwanted entry)
sudo efibootmgr -b 0000 -B
sudo efibootmgr -b 0001 -B
# ... delete all entries except the one for your A+E slot drive
```

The `-b` flag selects the boot number, and `-B` deletes it [^6].

#### Option B: Direct efivars manipulation (works on Alpine Linux without network)

If `efibootmgr` is unavailable (e.g. Alpine Linux booted via JetKVM virtual media with no network configured), manipulate the EFI variable files directly. The efivars filesystem is mounted at `/sys/firmware/efi/efivars/` automatically.

> **JetKVM root cause note**: When using JetKVM, its virtual media registers as a UEFI boot entry (e.g. `Boot0016 — JetKVM Virtual Media`). If the ISO is still mounted in JetKVM at boot time, this entry wins and the machine always boots to maintenance mode — even after Talos is correctly installed. **Eject the ISO from JetKVM's virtual media before rebooting.**

```sh
# UEFI boot entries use this standard GUID
GUID="8be4df61-93ca-11d2-aa0d-00e098032b8c"

# List all boot entries and decode their labels
# Note: labels are UTF-16LE; 'strings -e l' is not supported in BusyBox.
# Use 'tr -d '\000'' to strip null bytes and reveal readable ASCII.
for f in /sys/firmware/efi/efivars/Boot????-${GUID}; do
  entry=$(basename "$f" | grep -o 'Boot[0-9A-Fa-f]*')
  label=$(tr -d '\000' < "$f" 2>/dev/null | strings | tail -1)
  echo "$entry: $label"
done

# Example output:
# Boot0000: Talos Linux
# Boot0016: JetKVM Virtual Media

# Delete all entries EXCEPT Boot0000 (Talos Linux)
# chattr -i removes the immutable flag that UEFI sets on efivars files
for entry in 0009 000A 0010 0011 0012 0013 0014 0015 0016; do
  f="/sys/firmware/efi/efivars/Boot${entry}-${GUID}"
  [ -f "$f" ] && chattr -i "$f" && rm "$f" && echo "Deleted Boot${entry}"
done
```

After deleting competing entries, eject the JetKVM ISO, then power-cycle (not just reboot — a real ACPI power cycle so BIOS POST runs). The machine will boot Talos via the UEFI fallback path.

---

### Step 2: Ensure UEFI Fallback Boot Path Exists

When all NVRAM boot entries are removed, UEFI falls back to `\EFI\BOOT\BOOTX64.EFI` on available drives [^4][^7][^8].

**For Talos Linux**, verify the fallback bootloader exists on your A+E slot drive's EFI partition:

```bash
# Mount the EFI partition from the A+E slot drive
mount /dev/<a+e-drive-partition1> /mnt

# Check for fallback bootloader
ls /mnt/EFI/BOOT/
# Should contain: BOOTX64.EFI (or similar)

# If missing, copy from Talos's systemd-boot location:
cp /mnt/EFI/systemd/systemd-bootx64.efi /mnt/EFI/BOOT/BOOTX64.EFI
```

---

### Step 3: M920q-Specific BIOS Settings

Configure these settings in BIOS (F1 at boot):

| Setting | Value |
|---------|-------|
| **WiFi** | **Enabled** (required for A+E slot to work) [^2] |
| **Secure Boot** | Disabled [^2] |
| **CSM** | Disabled [^1] |
| **Boot Mode** | UEFI (not Legacy) [^3] |

In **Boot Order**, the A+E slot drive may appear under **"Other"** — ensure that category is enabled [^1].

---

### Step 4: Alternative — Manual Boot Entry Creation

If removing entries doesn't work, you can **create a boot entry** pointing to the A+E slot drive from a live Linux environment:

```bash
# Find the A+E slot drive (usually shows as nvme1n1 or similar)
lsblk

# Create boot entry (adjust disk/partition as needed)
sudo efibootmgr --create \
  --disk /dev/nvme1n1 \
  --part 1 \
  --label "Talos Linux" \
  --loader '\EFI\systemd\systemd-bootx64.efi'
```

Or use `bootctl install` after mounting the EFI partition [^5].

---

### Step 5: EFI Shell Fallback

If you end up at an EFI shell, you can boot manually [^3]:

```
Shell> fs0:
fs0:\> ls EFI\Linux\
fs0:\> EFI\Linux\talos-A.efi
```

Try different `fsX:` numbers until you find the A+E slot drive.

---

### Key Insight

The M920q's behavior is quirky: **once the machine successfully boots from the A+E slot drive once, it tends to remember and continue working** even after changing BIOS settings back [^1]. The challenge is getting that first successful boot.

If you're reinstalling Talos, doing a **fresh install with no other storage devices connected** can help the firmware recognize the A+E slot drive as bootable [^2].

[^1]: [Lenovo Thinkcentre/ThinkStation Tiny (Project TinyMiniMicro) Reference Thread | ServeTheHome Forums](https://forums.servethehome.com/index.php?threads/lenovo-thinkcentre-thinkstation-tiny-project-tinyminimicro-reference-thread.34925/page-42) (40%)
[^2]: [Adding additional boot storage to Lenovo M920Q via Wi-Fi Slot (w/ A+E Key Adapter)](https://www.reddit.com/r/homelab/comments/1m5452n/adding_additional_boot_storage_to_lenovo_m920q/) (28%)
[^3]: [How to Configure UEFI Boot for Talos Linux](https://oneuptime.com/blog/post/2026-03-03-configure-uefi-boot-for-talos-linux/view) (9%)
[^4]: [Boot-US: Glossary: UEFI fallback](https://www.boot-us.de/eng/gloss_uefi2.htm) (7%)
[^5]: [EFI boot order entry missing - bare metal · siderolabs/talos · Discussion #11127](https://github.com/siderolabs/talos/discussions/11127) (6%)
[^6]: [Install efibootmgr on Linux & Manage UEFI Boot](https://linuxconfig.org/how-to-manage-efi-boot-manager-entries-on-linux) (6%)
[^7]: [Managing EFI Boot Loaders for Linux: EFI Boot Loader Installation](https://www.rodsbooks.com/efi-bootloaders/installation.html) (3%)
[^8]: [/efi/Boot/bootx64.efi: why is it there? : r/archlinux - Reddit](https://www.reddit.com/r/archlinux/comments/pv51om/efibootbootx64efi_why_is_it_there/) (1%)
