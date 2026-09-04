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

# ── OSD lifecycle — gated; permanent, data-path operations ───────────────────

# Read: no confirmation needed — safe to run at any time
[doc('List all PGs currently mapped to a specific OSD — 0 data rows means safe to purge')]
osd-pg-ls id:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph pg ls-by-osd {{ id }}

# Marks the OSD as "not in" the CRUSH map so Ceph migrates its PGs elsewhere.
# Run this first when the disk is still readable; idempotent if already out.
# For a physically-removed disk (osd.8 / dead Kingston on worker-02), PGs have
# already remapped — you can skip straight to osd-purge.
[doc('Mark an OSD out — Ceph remaps its PGs to other OSDs. Run before osd-purge when the disk is still physically present.')]
osd-out id:
    #!/usr/bin/env bash
    set -euo pipefail
    gum log -t rfc3339 -s -l info "Current state of osd.{{ id }}:" stage check
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd tree | grep -E "osd\.{{ id }}([^0-9]|$)" || true
    echo
    gum log -t rfc3339 -s -l warn "Marking osd.{{ id }} out triggers PG remapping — Ceph will backfill away from this OSD." stage warn
    gum confirm "Mark osd.{{ id }} out?" || exit 0
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd out {{ id }}
    gum log -t rfc3339 -s -l info "osd.{{ id }} marked out — monitor backfill with 'just ceph status'." stage done

# Permanently removes the OSD from the CRUSH map, auth keyring, and OSD map.
# PG lines in `ceph pg ls-by-osd` start with a digit (pool.pg format, e.g. 1.1a);
# the header and "listed N pgs" footer do not — so grep -c "^[0-9]" gives an
# accurate live-PG count without parsing the full table.
[doc('Permanently purge an OSD (CRUSH map + auth + OSD map). Blocks if any PGs remain. Requires double confirmation.')]
osd-purge id:
    #!/usr/bin/env bash
    set -euo pipefail
    gum log -t rfc3339 -s -l info "Checking osd.{{ id }} state and PG count..." stage check
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd tree | grep -E "osd\.{{ id }}([^0-9]|$)" || true
    echo
    pg_count=$(kubectl -n {{ ns }} exec {{ toolbox }} -- ceph pg ls-by-osd {{ id }} 2>/dev/null | grep -c "^[0-9]" || echo 0)
    if [ "${pg_count}" -gt 0 ]; then
        gum log -t rfc3339 -s -l error "osd.{{ id }} still has ${pg_count} PG(s) — purging now risks data loss. Run 'just ceph osd-out {{ id }}' and wait for backfill to complete first." stage abort
        exit 1
    fi
    gum log -t rfc3339 -s -l info "PG count: 0 — safe to purge." stage check
    gum log -t rfc3339 -s -l warn "osd-purge is PERMANENT: removes osd.{{ id }} from the CRUSH map, auth keyring, and OSD map." stage warn
    gum confirm "Permanently purge osd.{{ id }}?" || exit 0
    gum confirm "Second confirmation — this cannot be undone. Purge osd.{{ id }}?" || exit 0
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph osd purge {{ id }} --yes-i-really-mean-it
    gum log -t rfc3339 -s -l info "osd.{{ id }} purged. If a replacement disk was installed and may carry stale LVM, run 'just ceph osd-lvm-wipe <node>' before Rook provisions new OSDs. Verify cluster state with 'just ceph status' and 'just ceph osd-tree'." stage done

# Zeroes the LVM PV header + partition signatures on the replacement disk for a
# single node. Mirrors `just bootstrap live-osd-cleanup` but scoped to one node
# instead of all nodes — use for day-2 OSD replacements rather than running the
# all-nodes bootstrap wipe. Requires jq + yq.
# If ceph-* dm devices are active on the node when this runs, a reboot of THAT
# NODE is needed before Rook will see the disk as clean (wipe-osd-lvm.sh prints
# a reminder). See `bootstrap live-osd-cleanup` for the bootstrap-phase variant.
[doc('Wipe stale LVM on a single OSD node via a privileged pod — run after osd-purge if the replacement disk carried leftover Ceph metadata from prior use')]
osd-lvm-wipe node:
    #!/usr/bin/env bash
    set -euo pipefail
    ROOK_HR="{{ justfile_dir() }}/kubernetes/apps/rook-ceph/rook-ceph/cluster/app/helmrelease.yaml"
    WIPE_SCRIPT="{{ justfile_dir() }}/scripts/wipe-osd-lvm.sh"

    DISK_BYID=$(yq ".spec.values.cephClusterSpec.storage.nodes[] | select(.name == \"{{ node }}\") | .devices[0].name" "${ROOK_HR}")
    # Same Ceph image the cluster is pinned to, so the wipe pod never pulls a retired tag.
    CEPH_IMAGE=$(yq '.spec.values.cephImage.repository + ":" + .spec.values.cephImage.tag' "${ROOK_HR}")
    if [ -z "${DISK_BYID}" ] || [ "${DISK_BYID}" = "null" ]; then
        gum log -t rfc3339 -s -l error "Node '{{ node }}' not found in Rook-Ceph HelmRelease storage.nodes" stage abort
        exit 1
    fi

    SHORT=$(echo "{{ node }}" | sed 's/talos-//')
    POD_NAME="wipe-osd-lvm-${SHORT}"
    gum log -t rfc3339 -s -l info "Node: {{ node }} | OSD disk: ${DISK_BYID}" stage check
    gum log -t rfc3339 -s -l warn "Spawns a privileged pod on {{ node }} to zero the LVM PV header and clear all partition signatures on ${DISK_BYID}." stage warn
    gum confirm "Run LVM wipe on {{ node }}?" || exit 0

    # Clean up any previous wipe pod from a prior run
    kubectl delete pod -n {{ ns }} "${POD_NAME}" --ignore-not-found --wait=false &>/dev/null || true

    SCRIPT=$(cat "${WIPE_SCRIPT}")
    jq -n \
      --arg name      "${POD_NAME}" \
      --arg node      "{{ node }}" \
      --arg image     "${CEPH_IMAGE}" \
      --arg script    "${SCRIPT}" \
      --arg disk_byid "${DISK_BYID}" \
      '{
        apiVersion: "v1", kind: "Pod",
        metadata: {name: $name, namespace: "rook-ceph", labels: {app: "osd-lvm-wiper"}},
        spec: {
          restartPolicy: "Never", nodeName: $node, hostPID: true, hostNetwork: true,
          tolerations: [{operator: "Exists"}],
          containers: [{
            name: "wipe", image: $image,
            command: ["bash", "-c", $script],
            env: [{name: "DISK_BYID", value: $disk_byid}],
            securityContext: {privileged: true},
            volumeMounts: [
              {name: "dev", mountPath: "/dev"},
              {name: "run", mountPath: "/run"}
            ]
          }],
          volumes: [
            {name: "dev", hostPath: {path: "/dev"}},
            {name: "run", hostPath: {path: "/run"}}
          ]
        }
      }' | kubectl apply -f -

    gum log -t rfc3339 -s -l info "Waiting for wipe pod to complete (up to 3 min)..." stage wait
    DEADLINE=$(($(date +%s) + 180))
    while true; do
        PHASE=$(kubectl get pod -n {{ ns }} "${POD_NAME}" \
            -o jsonpath='{.status.phase}' 2>/dev/null || echo "unknown")
        [ "${PHASE}" = "Succeeded" ] && break
        if [ "${PHASE}" = "Failed" ]; then
            gum log -t rfc3339 -s -l error "Wipe pod failed — logs:" stage abort
            kubectl logs -n {{ ns }} "${POD_NAME}" || true
            kubectl delete pod -n {{ ns }} "${POD_NAME}" --ignore-not-found &>/dev/null || true
            exit 1
        fi
        if [ "$(date +%s)" -gt "${DEADLINE}" ]; then
            gum log -t rfc3339 -s -l warn "Timed out waiting for wipe pod" stage warn
            break
        fi
        sleep 5
    done

    kubectl logs -n {{ ns }} "${POD_NAME}" || true
    kubectl delete pod -n {{ ns }} "${POD_NAME}" --ignore-not-found &>/dev/null || true
    gum log -t rfc3339 -s -l info "LVM wipe complete. If DM devices were active, reboot {{ node }} before triggering Rook OSD provisioning." stage done

# ── Escape hatch ─────────────────────────────────────────────────────────────

# Anything the named recipes don't cover. NOT gated — you own whatever you type,
# so keep mutations (pool/auth/osd changes) for ops you understand. Example:
#   just ceph cmd osd pool ls detail
[doc('Run an arbitrary read-only-by-convention ceph subcommand in the toolbox: just ceph cmd <args...>')]
cmd *args:
    kubectl -n {{ ns }} exec {{ toolbox }} -- ceph {{ args }}
