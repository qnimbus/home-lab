set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

cluster_yaml := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/cluster/app/cluster.yaml"
ks_yaml      := justfile_dir() + "/kubernetes/apps/database/cloudnative-pg/ks.yaml"

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
