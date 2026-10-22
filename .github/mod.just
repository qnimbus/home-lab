set default-list
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

# Renovate, Labeler and Label Sync run on `${{ vars.RUNNER || 'home-lab' }}`: unset means the
# in-cluster runner, ubuntu-24.04 the GitHub-hosted fallback (e.g. while the cluster is down).
# Image Pull ignores it — it needs talosctl access to the nodes.

[doc('Delete container-step Secrets whose runner pod no longer exists')]
[script]
prune-secrets ns="actions-runner-system":
    # The runner's Kubernetes container hook stores each container step's env (tokens included)
    # in a Secret labelled runner-pod=<runner pod>, and only deletes it in its job cleanup. A
    # runner pod that dies mid-job leaves it behind; secrets of live runners are left alone.
    pods=$(kubectl get pods -n "{{ ns }}" --no-headers -o custom-columns=NAME:.metadata.name)
    pruned=0
    while read -r secret pod; do
        [[ -z "$secret" ]] && continue
        if ! grep -qxF "$pod" <<< "$pods"; then
            kubectl delete secret -n "{{ ns }}" "$secret"
            pruned=$((pruned + 1))
        fi
    done < <(kubectl get secrets -n "{{ ns }}" -l runner-pod --no-headers \
        -o custom-columns=NAME:.metadata.name,POD:.metadata.labels.runner-pod)
    just log info "Pruned stray runner step Secrets" "namespace" "{{ ns }}" "count" "$pruned"

[doc('Show which runner the RUNNER repo variable selects')]
[script]
runner:
    if value=$(gh variable get RUNNER 2>/dev/null); then
        just log info "RUNNER is set" "value" "$value"
    else
        just log info "RUNNER is not set, workflows use the in-cluster runner" "runner" "home-lab"
    fi

[doc('Unset the RUNNER repo variable, so workflows run on the in-cluster runner')]
[script]
runner-cluster:
    if gh variable get RUNNER >/dev/null 2>&1; then
        gh variable delete RUNNER
    fi
    just log info "Workflows run on the in-cluster runner" "runner" "home-lab"

[doc('Set the RUNNER repo variable to ubuntu-24.04 (GitHub-hosted fallback)')]
runner-hosted:
    gh variable set RUNNER --body ubuntu-24.04
    just log info "Workflows run on GitHub-hosted runners" "runner" "ubuntu-24.04"

[doc('Rebase and merge risk/safe PRs one by one: all, ask (confirm each), or a PR number')]
[script]
merge-safe target="all":
    # Serial on purpose: each merge moves main, so the next PR is rebased onto the new main
    # and its checks rerun before it is merged. Merging to main is the deploy.
    case "{{ target }}" in
        all|ask) prs=$(gh pr list --label risk/safe --state open --json number --jq '.[].number' | sort -n) ;;
        *[!0-9]*) just log error "Target must be all, ask or a PR number" "target" "{{ target }}"; exit 1 ;;
        *)
            if ! gh pr view "{{ target }}" --json labels --jq '.labels[].name' | grep -qx 'risk/safe'; then
                just log error "PR is not labelled risk/safe" "pr" "{{ target }}"
                exit 1
            fi
            prs="{{ target }}"
            ;;
    esac
    if [[ -z "$prs" ]]; then
        just log info "No open risk/safe PRs"
        exit 0
    fi
    for pr in $prs; do
        title=$(gh pr view "$pr" --json title --jq .title)
        if [[ "{{ target }}" == ask ]] && ! gum confirm "Rebase and merge #$pr: $title?"; then
            just log info "Skipped" "pr" "$pr"
            continue
        fi
        if [[ $(gh pr view "$pr" --json mergeStateStatus --jq .mergeStateStatus) == BEHIND ]]; then
            gh pr update-branch "$pr" --rebase
            # Give GitHub time to register the new head's checks, or --watch sees the old run.
            sleep 10
        fi
        if ! gh pr checks "$pr" --watch --fail-fast; then
            just log error "Checks failed, stopping" "pr" "$pr"
            exit 1
        fi
        gh pr merge "$pr" --rebase --delete-branch
        just log info "Merged" "pr" "$pr" "title" "$title"
    done
