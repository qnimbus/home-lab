set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

cluster_yaml := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml"
ks_yaml      := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/ks.yaml"
live_primary_label := "cnpg.io/cluster=postgres-v17,role=primary"

[private]
default:
    just --list --justfile {{ source_file() }}

[doc('Configure postgres-v17 to recover from the latest S3 backup after a full reset (edits cluster.yaml — still requires commit + Flux to take effect)')]
restore-from-backup:
    #!/usr/bin/env bash
    set -euo pipefail
    if kubectl get cluster postgres-v17 -n database >/dev/null 2>&1; then
        gum log -t rfc3339 -s -l warn \
            "postgres-v17 already exists and is running — CNPG only reads spec.bootstrap" \
            "at creation time, so this edit has no effect until the object is deleted and" \
            "recreated. Did you mean to run this against a genuinely fresh/reset cluster?"
        gum confirm "Continue anyway?" || exit 0
    fi

    last_server=$(git -C "{{ justfile_dir() }}" log -p -- "{{ ks_yaml }}" \
        | grep -oP 'CNPG_V17_CURRENT_CLUSTER:\s*"\K[^"]+' | head -1)
    if [ -z "${last_server}" ]; then
        gum log -t rfc3339 -s -l error "No prior CNPG_V17_CURRENT_CLUSTER found in git history of ks.yaml"
        exit 1
    fi

    gum confirm "Configure postgres-v17 to recover from S3 backups archived under serverName '${last_server}'?" || exit 0

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

    gum log -t rfc3339 -s -l info \
        "cluster.yaml updated — review with 'git diff', stage/commit via /git-stage" \
        "+ /git-commit, then let Flux reconcile."

[doc('Remove the disaster-recovery bootstrap config from cluster.yaml once the recovered cluster is healthy')]
undo-restore:
    gum confirm "Remove spec.bootstrap and spec.externalClusters from cluster.yaml?" || exit 0
    yq -i 'del(.spec.bootstrap, .spec.externalClusters)' "{{ cluster_yaml }}"
    gum log -t rfc3339 -s -l info "Reverted — review with 'git diff', then commit via /git-stage + /git-commit."

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
    if ! kubectl exec "${POD}" -n "${NS}" -- bash -c \
        "gunzip -c '${LATEST}' | psql -U postgres --set ON_ERROR_STOP=on -v client_min_messages=warning" \
        > /tmp/nfs-restore-drill.log 2>&1; then
        gum log -t rfc3339 -s -l error "Restore failed — see output below" stage restore
        cat /tmp/nfs-restore-drill.log
        exit 1
    fi
    if grep -qiE 'ERROR|FATAL' /tmp/nfs-restore-drill.log; then
        gum log -t rfc3339 -s -l error "psql exited 0 but ERROR/FATAL lines were found in output:" stage restore
        grep -iE 'ERROR|FATAL' /tmp/nfs-restore-drill.log
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
        "Verification above is catalog-level (databases/roles) only. Per-app table row-count parity" \
        "is only meaningful once real app data exists on postgres-v17 — re-run after the per-app" \
        "provisioning roadmap item lands. Set KEEP_SCRATCH=1 to inspect the restored data manually" \
        "before teardown (e.g. for a one-off canary-table row-count check)." stage verify

    gum log -t rfc3339 -s -l info "Drill complete in ${DURATION}s total. Record this RTO + pass/fail in docs/ROADMAP.md." stage done
