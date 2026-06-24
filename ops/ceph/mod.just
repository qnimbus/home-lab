set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

# Every recipe is a thin wrapper around the in-cluster Ceph CLI, which only
# exists inside the Rook toolbox pod (toolbox.enabled: true in the
# rook-ceph-cluster HelmRelease). Centralise the namespace + deploy here so a
# rename only touches these two lines.
ns      := "rook-ceph"
toolbox := "deploy/rook-ceph-tools"

[private]
default:
    just --list --justfile {{ source_file() }}

# ── Reads — no confirmation (safe, side-effect-free) ─────────────────────────

[doc('ceph status + health detail — the first thing to run when an alert fires')]
status:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph status
    echo
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph health detail

[doc('Capacity: pool-level (ceph df) and per-OSD (ceph osd df) usage')]
df:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph df
    echo
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd df

[doc('ceph osd tree — host/OSD topology and up/in state')]
osd-tree:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd tree

[doc('ceph osd ok-to-stop <id> — can this OSD be drained without losing data availability? (the gate that the retired size=1 pool used to jam for every OSD)')]
ok-to-stop id:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd ok-to-stop {{ id }}

[doc('List all recorded daemon crashes (ceph crash ls)')]
crash-ls:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash ls

[doc('List only crashes not yet archived (ceph crash ls-new) — these are what raise the RECENT_CRASH HEALTH_WARN / CephDaemonCrash alert')]
crash-ls-new:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash ls-new

[doc('Full backtrace + metadata for one crash (ceph crash info <id>) — read this before archiving')]
crash-info id:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash info {{ id }}

# ── Acknowledgements — gated (stateful: they clear the RECENT_CRASH warning) ──

# Archiving does NOT delete the crash record (it stays in `ceph crash ls`); it
# moves the crash out of `ls-new` so it stops raising RECENT_CRASH. Gated
# because acknowledging a crash you haven't read can mask a real, ongoing fault.
[doc('Acknowledge ONE crash so it stops raising the alert (ceph crash archive <id>) — shows crash-info first, then confirms')]
crash-archive id:
    #!/usr/bin/env bash
    set -euo pipefail
    gum log -t rfc3339 -s -l info "Crash details for {{ id }}:" stage info
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash info "{{ id }}"
    gum confirm "Archive this crash? (record is kept; it just stops raising RECENT_CRASH)" || exit 0
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash archive "{{ id }}"
    gum log -t rfc3339 -s -l info "Archived {{ id }} — re-check with 'just ceph status'" stage done

# This is the recipe that motivated the module: the CephDaemonCrash alert this
# session was cleared by running `ceph crash archive-all` by hand. archive-all
# acknowledges EVERY outstanding crash at once, so it lists them first and
# confirms — otherwise a fresh, unrelated crash could be silenced unseen.
[doc('Acknowledge ALL outstanding crashes (ceph crash archive-all) — clears the CephDaemonCrash alert; lists new crashes and confirms first')]
crash-archive-all:
    #!/usr/bin/env bash
    set -euo pipefail
    new=$(kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash ls-new)
    if [ -z "${new}" ] || ! echo "${new}" | grep -q .; then
        gum log -t rfc3339 -s -l info "No new (unarchived) crashes — nothing to do." stage done
        exit 0
    fi
    gum log -t rfc3339 -s -l warn "About to archive ALL of these crashes:" stage list
    echo "${new}"
    gum confirm "Archive every crash listed above? Records are kept; they just stop raising RECENT_CRASH." || exit 0
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph crash archive-all
    gum log -t rfc3339 -s -l info "All crashes archived — the CephDaemonCrash alert resolves on the next eval. Verify with 'just ceph status'." stage done

# ── Escape hatch ─────────────────────────────────────────────────────────────

# Anything the named recipes don't cover. NOT gated — you own whatever you type,
# so keep mutations (pool/auth/osd changes) for ops you understand. Example:
#   just ceph cmd osd pool ls detail
[doc('Run an arbitrary read-only-by-convention ceph subcommand in the toolbox: just ceph cmd <args...>')]
cmd *args:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph {{ args }}
