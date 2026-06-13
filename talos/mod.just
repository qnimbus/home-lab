set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

[private]
default:
    just --list

[doc('Reset all nodes to maintenance mode (destructive — wipes STATE, EPHEMERAL, and Ceph OSD disks)')]
reset-cluster:
    task talos:reset

[doc('Reset a single node back to maintenance mode')]
reset-node node:
    gum confirm "Reset node {{ node }}? This wipes STATE + EPHEMERAL." || exit 0
    talosctl reset --nodes "{{ node }}" --graceful=false --reboot \
        --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL

[doc('Reboot a single node')]
reboot-node node:
    gum confirm "Reboot node {{ node }}?" || exit 0
    talosctl reboot --nodes "{{ node }}"

[doc('Power off a single node')]
shutdown-node node:
    gum confirm "Shut down node {{ node }}?" || exit 0
    talosctl shutdown --nodes "{{ node }}"

[doc('Upgrade Talos on a single node — reads image from talenv.yaml')]
upgrade-node node:
    task talos:upgrade-node IP="{{ node }}"

[doc('Check cluster health')]
health:
    talosctl health
