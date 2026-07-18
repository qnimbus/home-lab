set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

cluster_yaml := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml"
ks_yaml      := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/ks.yaml"
live_primary_label := "cnpg.io/cluster=postgres-v17,role=primary"
pitr_scratch_name := "postgres-v17-pitr-scratch"
pitr_scratch_primary_label := "cnpg.io/cluster=" + pitr_scratch_name + ",role=primary"

[private]
default:
    just --list --justfile {{ source_file() }}

[doc('Configure postgres-v17 to recover from the latest S3 backup after a full reset, and bump CNPG_V17_CURRENT_CLUSTER so it archives forward under a fresh prefix (edits cluster.yaml + ks.yaml — still requires commit + Flux to take effect)')]
restore-from-backup:
    #!/usr/bin/env bash
    set -euo pipefail
    if kubectl get cluster postgres-v17 -n database >/dev/null 2>&1; then
        gum log -t rfc3339 -s -l warn \
            "postgres-v17 already exists and is running — CNPG only reads spec.bootstrap at creation time, so this edit has no effect until the object is deleted and recreated. Did you mean to run this against a genuinely fresh/reset cluster?"
        gum confirm "Continue anyway?" || exit 0
    fi

    last_server=$(git -C "{{ justfile_dir() }}" log -p -- "{{ ks_yaml }}" \
        | grep -oP 'CNPG_V17_CURRENT_CLUSTER:\s*"\K[^"]+' | head -1)
    if [ -z "${last_server}" ]; then
        gum log -t rfc3339 -s -l error "No prior CNPG_V17_CURRENT_CLUSTER found in git history of ks.yaml"
        exit 1
    fi

    new_server="postgres-v17-$(date +%Y%m%d)"
    if [ "${new_server}" = "${last_server}" ]; then
        gum log -t rfc3339 -s -l error \
            "Minted serverName '${new_server}' is identical to the last one — a restore already ran today. Pick a distinct value manually (e.g. append '-2') and edit ks.yaml yourself."
        exit 1
    fi

    # Two different serverNames, two different lifetimes: 'last_server' is the
    # RECOVERY SOURCE (read-only, never archived to again — it's where the lost
    # cluster's backups already live in S3). 'new_server' is what the recovered
    # cluster will archive its OWN future WAL/backups under, going forward. They
    # must differ, or the recovered cluster's new WAL stream lands in the same S3
    # prefix it just restored from — see the DISASTER RECOVERY comment in cluster.yaml.
    gum log -t rfc3339 -s -l warn \
        "This changes TWO files. cluster.yaml: postgres-v17 will recover from the S3 backups archived under serverName '${last_server}' — that's the recovery SOURCE, read-only, never written to again. ks.yaml: CNPG_V17_CURRENT_CLUSTER moves to '${new_server}' — that's the prefix the recovered cluster archives its OWN future backups under, so it never collides with the one it just restored from." stage warn

    gum confirm "Apply both edits — recover from '${last_server}', archive forward as '${new_server}'?" || exit 0

    export LAST_SERVER="${last_server}"
    yq -i '
      .spec.bootstrap.recovery.source = "postgres-v17-source" |
      .spec.externalClusters = [{
        "name": "postgres-v17-source",
        "plugin": {
          "name": "barman-cloud.cloudnative-pg.io",
          "parameters": {
            "barmanObjectName": "cloudnative-pg-backup",
            "serverName": strenv(LAST_SERVER)
          }
        }
      }]
    ' "{{ cluster_yaml }}"

    export NEW_SERVER="${new_server}"
    yq -i '(select(.metadata.name == "cloudnative-pg-cluster").spec.postBuild.substitute.CNPG_V17_CURRENT_CLUSTER) = strenv(NEW_SERVER)' "{{ ks_yaml }}"

    gum log -t rfc3339 -s -l info \
        "Changed cluster.yaml (recovery source = '${last_server}') and ks.yaml (CNPG_V17_CURRENT_CLUSTER = '${new_server}') — review both with 'git diff', stage/commit via /git-stage + /git-commit, then let Flux reconcile."

[doc('Remove the disaster-recovery bootstrap config from cluster.yaml once the recovered cluster is healthy')]
undo-restore:
    gum confirm "Remove spec.bootstrap and spec.externalClusters from cluster.yaml?" || exit 0
    yq -i 'del(.spec.bootstrap, .spec.externalClusters)' "{{ cluster_yaml }}"
    gum log -t rfc3339 -s -l info "Reverted — review with 'git diff', then commit via /git-stage + /git-commit."

[doc('List Backup CRs for postgres-v17, newest first — phase=completed entries are valid PITR recovery points for pitr-restore')]
pitr-list-backups:
    #!/usr/bin/env bash
    set -euo pipefail

    # Backup CRs carry .spec.cluster.name, not a cnpg.io/cluster label — filter via jq.
    mapfile -t rows < <(kubectl get backups.postgresql.cnpg.io -n database -o json \
        | jq -r '.items | map(select(.spec.cluster.name == "postgres-v17")) | sort_by(.status.startedAt) | reverse | .[]
            | "\(.metadata.name)\t\(.status.phase // "-")\t\(.status.startedAt // "-")\t\(.status.stoppedAt // "-")\t\(.status.error // "-")"')

    if [ "${#rows[@]}" -eq 0 ]; then
        gum log -t rfc3339 -s -l warn "No Backup CRs found for cluster postgres-v17"
        exit 0
    fi

    printf '%-32s %-12s %-26s %-26s %s\n' "NAME" "PHASE" "STARTED" "STOPPED" "ERROR"
    printf '%s\n' "${rows[@]}" | awk -F'\t' '{printf "%-32s %-12s %-26s %-26s %s\n", $1, $2, $3, $4, $5}'

[doc('Prompt for a completed Backup CR and recover it (optionally forwarding to a specific target time) into a disposable single-instance scratch cluster — never archives WAL back to the live S3 prefix, never touches postgres-v17 itself. Follow with `just cnpg pitr-dump`, then `just cnpg pitr-cleanup`.')]
pitr-restore:
    #!/usr/bin/env bash
    set -euo pipefail

    if kubectl get cluster {{ pitr_scratch_name }} -n database >/dev/null 2>&1; then
        gum log -t rfc3339 -s -l warn "Scratch cluster '{{ pitr_scratch_name }}' already exists." stage guard
        gum confirm "Delete it now and continue?" || exit 0
        kubectl delete cluster {{ pitr_scratch_name }} -n database --wait=true --timeout=120s
    fi

    gum log -t rfc3339 -s -l info "Fetching completed Backup CRs for postgres-v17..." stage discover
    mapfile -t backups < <(kubectl get backups.postgresql.cnpg.io -n database -o json \
        | jq -r '.items[] | select(.spec.cluster.name == "postgres-v17" and .status.phase == "completed") | "\(.metadata.name)\t\(.status.startedAt)\t\(.status.stoppedAt)"')
    if [ "${#backups[@]}" -eq 0 ]; then
        gum log -t rfc3339 -s -l error "No completed Backup CRs found — nothing to recover from. Run 'just cnpg pitr-list-backups' to check." stage discover
        exit 1
    fi

    choice=$(printf '%s\n' "${backups[@]}" \
        | awk -F'\t' '{printf "%-32s started=%-26s stopped=%-26s\n", $1, $2, $3}' \
        | gum choose --header "Select a backup to recover from:")
    if [ -z "${choice}" ]; then
        gum log -t rfc3339 -s -l warn "No backup selected — aborting" stage discover
        exit 0
    fi
    backup_name=$(awk '{print $1}' <<< "${choice}")
    stopped_at=$(printf '%s\n' "${backups[@]}" | awk -F'\t' -v n="${backup_name}" '$1 == n {print $3}')

    # Default target = just after this backup's own end, so with no forwarding
    # you reproduce exactly that backup's state and nothing replayed afterward.
    default_target=$(date -u -d "${stopped_at} + 30 seconds" +"%Y-%m-%d %H:%M:%S.%6N+00:00")
    target_time=$(gum input \
        --header "Recovery target time (UTC) — accept the default to recover exactly this backup, or move it later to fast-forward WAL replay past it:" \
        --value "${default_target}")
    if [ -z "${target_time}" ]; then
        gum log -t rfc3339 -s -l warn "No target time provided — aborting" stage target
        exit 0
    fi

    current_server=$(yq '(select(.metadata.name == "cloudnative-pg-cluster") | .spec.postBuild.substitute.CNPG_V17_CURRENT_CLUSTER)' "{{ ks_yaml }}")
    if [ -z "${current_server}" ] || [ "${current_server}" = "null" ]; then
        gum log -t rfc3339 -s -l error "Could not read CNPG_V17_CURRENT_CLUSTER from {{ ks_yaml }}" stage target
        exit 1
    fi
    image_name=$(yq '.spec.imageName' "{{ cluster_yaml }}")

    gum log -t rfc3339 -s -l warn \
        "About to kubectl apply a disposable Cluster '{{ pitr_scratch_name }}' in namespace 'database': recovers backup '${backup_name}' (serverName '${current_server}') to target time '${target_time}'. This is an out-of-band apply, outside Flux/Git. It has no spec.plugins/isWALArchiver, so it can never write back into the live archive. It never touches the live postgres-v17 cluster." stage warn
    gum confirm "Apply this scratch recovery cluster?" || exit 0

    kubectl apply -f - <<MANIFEST
    apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    metadata:
      name: {{ pitr_scratch_name }}
      namespace: database
    spec:
      instances: 1
      imageName: ${image_name}
      enableSuperuserAccess: true
      superuserSecret:
        name: cloudnative-pg-secret
      bootstrap:
        recovery:
          source: postgres-v17-source
          recoveryTarget:
            targetTime: "${target_time}"
      externalClusters:
        - name: postgres-v17-source
          plugin:
            name: barman-cloud.cloudnative-pg.io
            parameters:
              barmanObjectName: cloudnative-pg-backup
              serverName: ${current_server}
      resources:
        requests:
          cpu: 100m
          memory: 512Mi
        limits:
          memory: 1Gi
      storage:
        size: 20Gi
        storageClass: openebs-hostpath
    MANIFEST

    gum log -t rfc3339 -s -l info "Waiting for {{ pitr_scratch_name }} to become healthy (pulling base backup + replaying WAL)..." stage wait
    kubectl wait cluster {{ pitr_scratch_name }} -n database --for=condition=Ready --timeout=5m

    gum log -t rfc3339 -s -l info "Scratch cluster ready. Next: 'just cnpg pitr-dump' to extract a database, then 'just cnpg pitr-cleanup' when done." stage done

[doc('Prompt for a database inside the postgres-v17-pitr-scratch recovery cluster and pg_dump it locally — run after `just cnpg pitr-restore`. Defaults to ~/cnpg-backups/<db>-pitr-<timestamp>.dump if FILE is omitted.')]
pitr-dump file="":
    #!/usr/bin/env bash
    set -euo pipefail

    if ! kubectl get cluster {{ pitr_scratch_name }} -n database >/dev/null 2>&1; then
        gum log -t rfc3339 -s -l error "No scratch cluster '{{ pitr_scratch_name }}' found — run 'just cnpg pitr-restore' first" stage guard
        exit 1
    fi

    POD=$(kubectl get pod -n database -l "{{ pitr_scratch_primary_label }}" -o jsonpath='{.items[0].metadata.name}')
    if [ -z "${POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for {{ pitr_scratch_name }} — is it still recovering?" stage guard
        exit 1
    fi

    mapfile -t dbs < <(kubectl exec -n database "${POD}" -c postgres -- psql -U postgres -At -c \
        "select datname from pg_database where datname not in ('postgres','template0','template1') order by 1;")
    if [ "${#dbs[@]}" -eq 0 ]; then
        gum log -t rfc3339 -s -l error "No user databases found on the recovered instance" stage discover
        exit 1
    fi

    DB=$(printf '%s\n' "${dbs[@]}" | gum choose --header "Select a database to dump from the recovered instance:")
    if [ -z "${DB}" ]; then
        gum log -t rfc3339 -s -l warn "No database selected — aborting" stage discover
        exit 0
    fi

    FILE="{{ file }}"
    if [ -z "${FILE}" ]; then
        FILE="${HOME}/cnpg-backups/${DB}-pitr-$(date +%Y%m%d-%H%M%S).dump"
    fi
    # just runs module recipes with cwd set to the module's own directory
    # (ops/cnpg/), not the invoker's shell — resolve relative paths against
    # invocation_directory() so a bare filename means what the user expects.
    case "${FILE}" in
        /*) ;;
        *) FILE="{{ invocation_directory() }}/${FILE}" ;;
    esac
    mkdir -p "$(dirname "${FILE}")"

    gum log -t rfc3339 -s -l info "Dumping '${DB}' from recovered instance ${POD} to ${FILE}..." stage dump
    kubectl exec -n database "${POD}" -c postgres -- pg_dump -U postgres -Fc -d "${DB}" > "${FILE}"

    SIZE=$(du -h "${FILE}" | cut -f1)
    gum log -t rfc3339 -s -l info "Dump complete: ${FILE} (${SIZE}). Restore into the live cluster with 'just cnpg restore ${DB} ${FILE}', then run 'just cnpg pitr-cleanup'." stage done

[doc('Delete the postgres-v17-pitr-scratch recovery cluster and its PVCs/pods — leaves any pg_dump files already extracted (e.g. ~/cnpg-backups/) untouched.')]
pitr-cleanup:
    #!/usr/bin/env bash
    set -euo pipefail

    if ! kubectl get cluster {{ pitr_scratch_name }} -n database >/dev/null 2>&1; then
        gum log -t rfc3339 -s -l info "No scratch cluster '{{ pitr_scratch_name }}' found — nothing to clean up" stage guard
        exit 0
    fi

    gum confirm "Delete scratch cluster '{{ pitr_scratch_name }}' and its PVCs/pods? (pg_dump files already extracted are untouched)" || exit 0

    kubectl delete cluster {{ pitr_scratch_name }} -n database --wait=true --timeout=120s
    kubectl delete pvc,pods -n database -l "cnpg.io/cluster={{ pitr_scratch_name }}" --ignore-not-found --wait=true --timeout=60s

    remaining=$(kubectl get pvc,pods -n database -l "cnpg.io/cluster={{ pitr_scratch_name }}" --no-headers 2>/dev/null | wc -l)
    if [ "${remaining}" -gt 0 ]; then
        gum log -t rfc3339 -s -l warn "Some resources still remain — check manually: kubectl get pvc,pods -n database -l cnpg.io/cluster={{ pitr_scratch_name }}" stage cleanup
    else
        gum log -t rfc3339 -s -l info "Scratch cluster and all artifacts removed" stage done
    fi

[doc('Dump a single database on postgres-v17 to a local pg_dump custom-format file — e.g. `just cnpg dump firefly`. Defaults to ~/cnpg-backups/<db>-<timestamp>.dump if FILE is omitted.')]
dump db file="":
    #!/usr/bin/env bash
    set -euo pipefail

    DB="{{ db }}"
    FILE="{{ file }}"
    if [ -z "${FILE}" ]; then
        FILE="${HOME}/cnpg-backups/${DB}-$(date +%Y%m%d-%H%M%S).dump"
    fi
    # just runs module recipes with cwd set to the module's own directory
    # (ops/cnpg/), not the invoker's shell — resolve relative paths against
    # invocation_directory() so a bare filename means what the user expects.
    case "${FILE}" in
        /*) ;;
        *) FILE="{{ invocation_directory() }}/${FILE}" ;;
    esac
    mkdir -p "$(dirname "${FILE}")"

    POD=$(kubectl get pod -n database -l "{{ live_primary_label }}" -o jsonpath='{.items[0].metadata.name}')
    if [ -z "${POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for postgres-v17"
        exit 1
    fi

    if ! kubectl exec "${POD}" -n database -c postgres -- psql -U postgres -At -c \
        "select 1 from pg_database where datname = '${DB}';" | grep -q 1; then
        gum log -t rfc3339 -s -l error "Database '${DB}' does not exist on postgres-v17"
        exit 1
    fi

    # -Fc (custom format): compressed, and restorable selectively via pg_restore --
    # unlike plain SQL, it doesn't need to be replayed statement-by-statement.
    gum log -t rfc3339 -s -l info "Dumping database '${DB}' from ${POD} to ${FILE}..." stage dump
    kubectl exec "${POD}" -n database -c postgres -- \
        pg_dump -U postgres -Fc -d "${DB}" > "${FILE}"

    SIZE=$(du -h "${FILE}" | cut -f1)
    gum log -t rfc3339 -s -l info "Dump complete: ${FILE} (${SIZE})" stage done

[doc('DESTRUCTIVE: restore a local pg_dump custom-format file into an existing database on postgres-v17-rw, dropping/recreating its objects — e.g. `just cnpg restore firefly ~/cnpg-backups/firefly-20260712-153000.dump`. The target database must already exist (created via its CNPG Database CRD); other databases on postgres-v17 are untouched.')]
restore db file:
    #!/usr/bin/env bash
    set -euo pipefail

    DB="{{ db }}"
    FILE="{{ file }}"

    # just runs module recipes with cwd set to the module's own directory
    # (ops/cnpg/), not the invoker's shell — resolve relative paths against
    # invocation_directory() so a bare filename means what the user expects.
    case "${FILE}" in
        /*) ;;
        *) FILE="{{ invocation_directory() }}/${FILE}" ;;
    esac

    if [ ! -f "${FILE}" ]; then
        gum log -t rfc3339 -s -l error "File not found: ${FILE}"
        exit 1
    fi

    POD=$(kubectl get pod -n database -l "{{ live_primary_label }}" -o jsonpath='{.items[0].metadata.name}')
    if [ -z "${POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for postgres-v17"
        exit 1
    fi

    if ! kubectl exec "${POD}" -n database -c postgres -- psql -U postgres -At -c \
        "select 1 from pg_database where datname = '${DB}';" | grep -q 1; then
        gum log -t rfc3339 -s -l error \
            "Database '${DB}' does not exist on postgres-v17 — create it via a CNPG Database CRD first (see kubernetes/apps/finance/firefly-iii/db/database.yaml for the pattern), then re-run."
        exit 1
    fi

    gum log -t rfc3339 -s -l warn \
        "This restores '${FILE}' into database '${DB}' on live postgres-v17-rw using --clean --if-exists — existing objects in '${DB}' will be dropped and recreated. Other databases on postgres-v17 are untouched." stage warn
    gum confirm "Proceed with restore into '${DB}'?" || exit 0

    # DROP TABLE/etc. from --clean refuses to run while any other session holds a
    # lock (e.g. the app's own connection pool) — force-disconnect everyone else
    # first, same as nfs-restore-from-backup.
    gum log -t rfc3339 -s -l info "Terminating other active connections to '${DB}' so --clean can proceed..." stage terminate
    kubectl exec "${POD}" -n database -c postgres -- psql -U postgres -At -c \
        "select pg_terminate_backend(pid) from pg_stat_activity where datname = '${DB}' and pid <> pg_backend_pid();" >/dev/null

    START=$(date +%s)
    gum log -t rfc3339 -s -l info "Restoring into '${DB}'..." stage restore
    LOG="$(mktemp)"
    kubectl exec -i "${POD}" -n database -c postgres -- \
        pg_restore -U postgres -d "${DB}" --clean --if-exists < "${FILE}" > "${LOG}" 2>&1 || true

    # --clean emits harmless NOTICEs for DROP statements targeting objects that
    # don't exist yet (e.g. restoring into a freshly-created, empty database).
    unexpected=$(grep -iE 'ERROR|FATAL' "${LOG}" | grep -vi 'does not exist, skipping' || true)
    if [ -n "${unexpected}" ]; then
        gum log -t rfc3339 -s -l error "Unexpected ERROR/FATAL lines found in restore output:" stage restore
        cat "${LOG}"
        rm -f "${LOG}"
        exit 1
    fi
    rm -f "${LOG}"

    END=$(date +%s)
    DURATION=$((END - START))
    gum log -t rfc3339 -s -l info "Restore of '${DB}' completed in ${DURATION}s" stage done

[doc('Restore the latest NFS pg_dumpall backup into a disposable scratch Postgres pod and verify it — never touches postgres-v17-rw. Set KEEP_SCRATCH=1 to skip auto-teardown for manual inspection.')]
nfs-restore-drill:
    #!/usr/bin/env bash
    set -euo pipefail

    POD="nfs-restore-drill"
    NS="database"
    SCRATCH_PW="drill-$(date +%s)" # throwaway — pod has no Service, never reachable outside kubectl exec

    cleanup() {
        gum log -t rfc3339 -s -l info "Cleaning up scratch pod..." stage cleanup
        kubectl delete pod "${POD}" -n "${NS}" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1 || \
            gum log -t rfc3339 -s -l warn "Cleanup did not confirm deletion — check 'kubectl get pod ${POD} -n ${NS}' manually" stage cleanup
    }
    if [ "${KEEP_SCRATCH:-0}" != "1" ]; then
        trap cleanup EXIT
    else
        gum log -t rfc3339 -s -l warn "KEEP_SCRATCH=1 set — scratch pod will NOT be auto-deleted; clean up manually: kubectl delete pod ${POD} -n ${NS}" stage start-pod
    fi

    gum confirm "Spin up a disposable scratch Postgres pod and restore the latest NFS backup into it? (live postgres-v17 is never touched)" || exit 0

    START=$(date +%s)

    gum log -t rfc3339 -s -l info "Starting scratch postgres:17 pod with NFS backups mounted read-only..." stage start-pod
    kubectl run "${POD}" -n "${NS}" --restart=Never --image=docker.io/library/postgres:17 \
        --overrides='{
          "spec": {
            "volumes": [{"name": "backups", "nfs": {"server": "10.200.0.41", "path": "/mnt/tank/Cluster/cloudnative-pg", "readOnly": true}}],
            "containers": [{
              "name": "'"${POD}"'",
              "image": "docker.io/library/postgres:17",
              "env": [{"name": "POSTGRES_PASSWORD", "value": "'"${SCRATCH_PW}"'"}],
              "volumeMounts": [{"name": "backups", "mountPath": "/backups", "readOnly": true}]
            }]
          }
        }'

    kubectl wait pod "${POD}" -n "${NS}" --for=condition=Ready --timeout=120s

    gum log -t rfc3339 -s -l info "Waiting for postgres to accept connections..." stage start-pod
    ready=0
    for _ in $(seq 1 30); do
        if kubectl exec "${POD}" -n "${NS}" -- pg_isready -U postgres >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 2
    done
    if [ "${ready}" != "1" ]; then
        gum log -t rfc3339 -s -l error "postgres never became ready to accept connections" stage start-pod
        exit 1
    fi

    gum log -t rfc3339 -s -l info "Discovering latest backup file from /backups/last/ (not assuming a filename)..." stage discover
    LATEST=$(kubectl exec "${POD}" -n "${NS}" -- bash -c 'ls -t /backups/last/*.sql.gz 2>/dev/null | head -1')
    if [ -z "${LATEST}" ]; then
        gum log -t rfc3339 -s -l error "No .sql.gz files found under /backups/last/ — check the CronJob ran and the NFS mount is correct" stage discover
        exit 1
    fi
    gum log -t rfc3339 -s -l info "Using backup file: ${LATEST}" stage discover

    gum log -t rfc3339 -s -l info "Restoring into the scratch instance via psql (this is NOT postgres-v17-rw)..." stage restore
    kubectl exec "${POD}" -n "${NS}" -- bash -c \
        "gunzip -c '${LATEST}' | psql -U postgres -v client_min_messages=warning" \
        > /tmp/nfs-restore-drill.log 2>&1 || true

    # pg_dumpall --clean, replayed by connecting as the very role it drops/recreates,
    # always throws harmless, well-documented self-referential errors for that one
    # role: DROP ROLE postgres fails ("current user cannot be dropped"), which means
    # CREATE ROLE postgres then fails too ("already exists"), and the dump's recorded
    # "GRANTED BY postgres" can't be replayed until that role actually holds admin on
    # the predefined role being granted. None of this is data loss — filter only
    # these, fail on anything else.
    unexpected=$(grep -iE 'ERROR|FATAL' /tmp/nfs-restore-drill.log \
        | grep -viE 'current user cannot be dropped|role "postgres" already exists|permission denied to grant privileges as role' \
        || true)
    if [ -n "${unexpected}" ]; then
        gum log -t rfc3339 -s -l error "Unexpected ERROR/FATAL lines found in restore output:" stage restore
        echo "${unexpected}"
        exit 1
    fi
    rm -f /tmp/nfs-restore-drill.log

    END=$(date +%s)
    DURATION=$((END - START))
    gum log -t rfc3339 -s -l info "Restore completed cleanly in ${DURATION}s (this run's RTO)" stage restore

    gum log -t rfc3339 -s -l info "Comparing catalog state: scratch (restored) vs live postgres-v17 (read-only exec, no password needed)..." stage verify
    LIVE_POD=$(kubectl get pod -n "${NS}" -l "{{ live_primary_label }}" -o jsonpath='{.items[0].metadata.name}')

    echo "--- databases: scratch vs live ---"
    diff <(kubectl exec "${POD}" -n "${NS}" -- psql -U postgres -At -c "select datname from pg_database order by 1;") \
         <(kubectl exec "${LIVE_POD}" -n "${NS}" -c postgres -- psql -U postgres -At -c "select datname from pg_database order by 1;") \
        && gum log -t rfc3339 -s -l info "Database lists match" stage verify \
        || gum log -t rfc3339 -s -l warn "Database lists differ — see diff above" stage verify

    echo "--- roles: scratch vs live ---"
    diff <(kubectl exec "${POD}" -n "${NS}" -- psql -U postgres -At -c "select rolname from pg_roles order by 1;") \
         <(kubectl exec "${LIVE_POD}" -n "${NS}" -c postgres -- psql -U postgres -At -c "select rolname from pg_roles order by 1;") \
        && gum log -t rfc3339 -s -l info "Role lists match" stage verify \
        || gum log -t rfc3339 -s -l warn "Role lists differ — see diff above" stage verify

    gum log -t rfc3339 -s -l warn \
        "Verification above is catalog-level (databases/roles) only. Per-app table row-count parity is only meaningful once real app data exists on postgres-v17 — re-run after the per-app provisioning roadmap item lands. Set KEEP_SCRATCH=1 to inspect the restored data manually before teardown (e.g. for a one-off canary-table row-count check)." stage verify

    gum log -t rfc3339 -s -l info "Drill complete in ${DURATION}s total. Record this RTO + pass/fail in docs/ROADMAP.md." stage done

[doc('DESTRUCTIVE: restore the latest NFS pg_dumpall backup directly into postgres-v17-rw, dropping and recreating every database. Only safe when postgres-v17 has no data worth keeping — verify with this recipe before running.')]
nfs-restore-from-backup:
    #!/usr/bin/env bash
    set -euo pipefail

    POD="nfs-restore-from-backup"
    NS="database"

    cleanup() {
        gum log -t rfc3339 -s -l info "Cleaning up restore helper pod..." stage cleanup
        kubectl delete pod "${POD}" -n "${NS}" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1 || \
            gum log -t rfc3339 -s -l warn "Cleanup did not confirm deletion — check 'kubectl get pod ${POD} -n ${NS}' manually" stage cleanup
    }
    trap cleanup EXIT

    # Resolved by label, not a fixed name — cnpg.io/cluster,role=primary always
    # points at whichever instance currently holds the primary role, even after a
    # failover/switchover has moved it off postgres-v17-1.
    LIVE_POD=$(kubectl get pod -n "${NS}" -l "{{ live_primary_label }}" -o jsonpath='{.items[0].metadata.name}')
    if [ -z "${LIVE_POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for postgres-v17"
        exit 1
    fi

    gum log -t rfc3339 -s -l warn \
        "THIS IS DESTRUCTIVE: pg_dumpall --clean drops and recreates EVERY database on postgres-v17-rw, including 'app' and any other live data. Only run this immediately after a fresh/empty bootstrap, or when you have verified (as below) that nothing of value would be lost." stage warn

    echo "--- current databases on postgres-v17-rw ---"
    kubectl exec -n "${NS}" "${LIVE_POD}" -c postgres -- psql -U postgres -At -c "select datname from pg_database order by 1;"

    gum confirm "Restore the latest NFS backup directly into postgres-v17-rw? This drops/recreates every database listed above." || exit 0

    gum log -t rfc3339 -s -l info "Starting helper pod with NFS backups mounted read-only..." stage start-pod
    kubectl run "${POD}" -n "${NS}" --restart=Never --image=docker.io/library/postgres:17 \
        --overrides='{
          "spec": {
            "volumes": [{"name": "backups", "nfs": {"server": "10.200.0.41", "path": "/mnt/tank/Cluster/cloudnative-pg", "readOnly": true}}],
            "containers": [{
              "name": "'"${POD}"'",
              "image": "docker.io/library/postgres:17",
              "command": ["sleep", "infinity"],
              "env": [
                {"name": "PGHOST", "value": "postgres-v17-rw.database.svc.cluster.local"},
                {"name": "PGUSER", "valueFrom": {"secretKeyRef": {"name": "cloudnative-pg-secret", "key": "username"}}},
                {"name": "PGPASSWORD", "valueFrom": {"secretKeyRef": {"name": "cloudnative-pg-secret", "key": "password"}}}
              ],
              "volumeMounts": [{"name": "backups", "mountPath": "/backups", "readOnly": true}]
            }]
          }
        }'

    kubectl wait pod "${POD}" -n "${NS}" --for=condition=Ready --timeout=60s

    gum log -t rfc3339 -s -l info "Discovering latest backup file from /backups/last/..." stage discover
    LATEST=$(kubectl exec "${POD}" -n "${NS}" -- bash -c 'ls -t /backups/last/*.sql.gz 2>/dev/null | head -1')
    if [ -z "${LATEST}" ]; then
        gum log -t rfc3339 -s -l error "No .sql.gz files found under /backups/last/" stage discover
        exit 1
    fi
    kubectl exec "${POD}" -n "${NS}" -- bash -c "stat -c 'file=%n  modified=%y' '${LATEST}'"

    gum confirm "Confirmed backup file timestamp above — proceed with restore into postgres-v17-rw?" || exit 0

    # DROP DATABASE refuses to run while any other session — even idle — is connected
    # (e.g. pgAdmin keeps a persistent connection open per database it has browsed).
    # Force-disconnect everyone else right before the restore so the dump's DROP
    # DATABASE statements can proceed.
    gum log -t rfc3339 -s -l info "Terminating other active connections to postgres-v17-rw so DROP DATABASE can proceed..." stage terminate
    kubectl exec -n "${NS}" "${LIVE_POD}" -c postgres -- psql -U postgres -At -c \
        "select pg_terminate_backend(pid) from pg_stat_activity where pid <> pg_backend_pid() and datname is not null;" >/dev/null

    START=$(date +%s)
    gum log -t rfc3339 -s -l info "Restoring into postgres-v17-rw..." stage restore
    kubectl exec "${POD}" -n "${NS}" -- bash -c \
        "gunzip -c '${LATEST}' | psql -v client_min_messages=warning" \
        > /tmp/nfs-restore-from-backup.log 2>&1 || true

    # See nfs-restore-drill for the three self-referential errors from replaying
    # pg_dumpall --clean while connected as the role it drops/recreates. Restoring
    # straight onto a live CNPG cluster adds one more: streaming_replica can't be
    # dropped because it permanently holds EXECUTE grants on file-access functions
    # (used by CNPG's instance manager/replication tooling) — that role is reconciled
    # by the CNPG operator independently of this dump, so leaving it untouched is fine.
    unexpected=$(grep -iE 'ERROR|FATAL' /tmp/nfs-restore-from-backup.log \
        | grep -viE 'current user cannot be dropped|role "postgres" already exists|permission denied to grant privileges as role|role "streaming_replica" (already exists|cannot be dropped because some objects depend on it)' \
        || true)
    if [ -n "${unexpected}" ]; then
        gum log -t rfc3339 -s -l error "Unexpected ERROR/FATAL lines found in restore output:" stage restore
        echo "${unexpected}"
        exit 1
    fi
    rm -f /tmp/nfs-restore-from-backup.log

    END=$(date +%s)
    DURATION=$((END - START))
    gum log -t rfc3339 -s -l info "Restore completed cleanly in ${DURATION}s (this run's RTO)" stage restore

    echo "--- databases on postgres-v17-rw after restore ---"
    kubectl exec -n "${NS}" "${LIVE_POD}" -c postgres -- psql -U postgres -At -c "select datname from pg_database order by 1;"

    gum log -t rfc3339 -s -l info "Restore complete in ${DURATION}s. Verify application connectivity, then record RTO + pass/fail in docs/ROADMAP.md." stage done
