set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[doc('Dump an app database from its <app>-postgres CNPG cluster to a local pg_dump custom-format file — e.g. `just k8s database dump default forgejo`. FILE defaults to ~/cnpg-backups/<db>-<timestamp>.dump; DB defaults to the app name.')]
dump ns app file="" db="":
    #!/usr/bin/env bash
    set -euo pipefail

    DB="{{ if db == '' { app } else { db } }}"
    FILE="{{ file }}"
    CLUSTER="{{ app }}-postgres"
    NS="{{ ns }}"
    if [ -z "${FILE}" ]; then
        FILE="${HOME}/cnpg-backups/${DB}-$(date +%Y%m%d-%H%M%S).dump"
    fi
    # just runs module recipes with cwd set to the module's own directory
    # (kubernetes/apps/database/), not the invoker's shell — resolve relative
    # paths against invocation_directory() so a bare filename means what the
    # user expects.
    case "${FILE}" in
        /*) ;;
        *) FILE="{{ invocation_directory() }}/${FILE}" ;;
    esac
    mkdir -p "$(dirname "${FILE}")"

    POD=$(kubectl get pod -n "${NS}" -l "cnpg.io/cluster=${CLUSTER},role=primary" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -z "${POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for ${CLUSTER} in namespace ${NS}"
        exit 1
    fi

    if ! kubectl exec "${POD}" -n "${NS}" -c postgres -- psql -U postgres -At -c \
        "select 1 from pg_database where datname = '${DB}';" | grep -q 1; then
        gum log -t rfc3339 -s -l error "Database '${DB}' does not exist on ${CLUSTER}"
        exit 1
    fi

    # -Fc (custom format): compressed, and restorable selectively via pg_restore --
    # unlike plain SQL, it doesn't need to be replayed statement-by-statement.
    gum log -t rfc3339 -s -l info "Dumping database '${DB}' from ${POD} to ${FILE}..." stage dump
    kubectl exec "${POD}" -n "${NS}" -c postgres -- \
        pg_dump -U postgres -Fc -d "${DB}" > "${FILE}"

    SIZE=$(du -h "${FILE}" | cut -f1)
    gum log -t rfc3339 -s -l info "Dump complete: ${FILE} (${SIZE})" stage done

[doc('DESTRUCTIVE: restore a local pg_dump custom-format file into an app database on its <app>-postgres CNPG cluster, dropping/recreating its objects — e.g. `just k8s database restore default forgejo ~/cnpg-backups/forgejo-20260915-103441.dump`. DB defaults to the app name and must already exist.')]
restore ns app file db="":
    #!/usr/bin/env bash
    set -euo pipefail

    DB="{{ if db == '' { app } else { db } }}"
    FILE="{{ file }}"
    CLUSTER="{{ app }}-postgres"
    NS="{{ ns }}"

    # just runs module recipes with cwd set to the module's own directory
    # (kubernetes/apps/database/), not the invoker's shell — resolve relative
    # paths against invocation_directory() so a bare filename means what the
    # user expects.
    case "${FILE}" in
        /*) ;;
        *) FILE="{{ invocation_directory() }}/${FILE}" ;;
    esac

    if [ ! -f "${FILE}" ]; then
        gum log -t rfc3339 -s -l error "File not found: ${FILE}"
        exit 1
    fi

    POD=$(kubectl get pod -n "${NS}" -l "cnpg.io/cluster=${CLUSTER},role=primary" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -z "${POD}" ]; then
        gum log -t rfc3339 -s -l error "No primary pod found for ${CLUSTER} in namespace ${NS}"
        exit 1
    fi

    if ! kubectl exec "${POD}" -n "${NS}" -c postgres -- psql -U postgres -At -c \
        "select 1 from pg_database where datname = '${DB}';" | grep -q 1; then
        gum log -t rfc3339 -s -l error \
            "Database '${DB}' does not exist on ${CLUSTER} in namespace ${NS} — the Cluster's bootstrap creates it (POSTGRES_DATABASE), so check the app's ks.yaml, then re-run."
        exit 1
    fi

    gum log -t rfc3339 -s -l warn \
        "This restores '${FILE}' into database '${DB}' on live ${CLUSTER}-rw (namespace ${NS}) using --clean --if-exists — existing objects in '${DB}' will be dropped and recreated. Other databases on ${CLUSTER} are untouched." stage warn
    gum confirm "Proceed with restore into '${DB}'?" || exit 0

    # DROP TABLE/etc. from --clean refuses to run while any other session holds a
    # lock (e.g. the app's own connection pool) — force-disconnect everyone else
    # first, same as nfs-restore-from-backup.
    gum log -t rfc3339 -s -l info "Terminating other active connections to '${DB}' so --clean can proceed..." stage terminate
    kubectl exec "${POD}" -n "${NS}" -c postgres -- psql -U postgres -At -c \
        "select pg_terminate_backend(pid) from pg_stat_activity where datname = '${DB}' and pid <> pg_backend_pid();" >/dev/null

    START=$(date +%s)
    gum log -t rfc3339 -s -l info "Restoring into '${DB}'..." stage restore
    LOG="$(mktemp)"
    kubectl exec -i "${POD}" -n "${NS}" -c postgres -- \
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
