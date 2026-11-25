set default-list
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

# Labeler and Label Sync run on `${{ vars.RUNNER || 'home-lab' }}`: unset means the in-cluster
# runner, ubuntu-24.04 the GitHub-hosted fallback (e.g. while the cluster is down). Renovate is
# always GitHub-hosted; Image Pull always in-cluster, since it needs talosctl access to the nodes.

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

# Claude Review's verdict comments come from the bot App. The author check matters: the repo is
# public, so anyone can post a comment that starts with **Verdict**.
review_bot := "qnimbus-homelab-assistant"

[doc("Rebase and merge open PRs one by one, showing Claude Review's verdict: ask (each, default) or a PR number")]
[script]
merge target="ask":
    # Serial on purpose: each merge moves main, so the next PR is rebased onto the new main
    # and its checks rerun before it is merged. Always asks: the verdict is shown, the
    # decision is yours.
    case "{{ target }}" in
        ask) prs=$(gh pr list --state open --search 'draft:false' --json number --jq '.[].number' | sort -n) ;;
        *[!0-9]*) just log error "Target must be ask or a PR number" "target" "{{ target }}"; exit 1 ;;
        *)
            if [[ $(gh pr view "{{ target }}" --json state --jq .state) != OPEN ]]; then
                just log error "PR is not open" "pr" "{{ target }}"
                exit 1
            fi
            prs="{{ target }}"
            ;;
    esac
    if [[ -z "$prs" ]]; then
        just log info "No open PRs"
        exit 0
    fi
    for pr in $prs; do
        just github _show-pr "$pr"
        if ! gum confirm "Rebase and merge #$pr?"; then
            just log info "Skipped" "pr" "$pr"
            continue
        fi
        just github _rebase-merge "$pr"
    done

[private]
[script]
_show-pr pr:
    # Title, author and the latest Claude Review verdict, flagged when the PR was pushed to
    # after that review.
    gh pr view "{{ pr }}" --json title,author,commits,comments \
        | jq -r --arg bot "{{ review_bot }}" '
            .commits[-1].committedDate as $pushed
            | ([.comments[]
                | select(.author.login == $bot and (.body | startswith("**Verdict**")))]
                | last) as $review
            | "#{{ pr }} \(.title)",
              "  author:  \(.author.login)",
              if $review == null then "  verdict: none yet"
              else
                "  verdict: \($review.body | split("\n")[0] | sub("^\\*\\*Verdict\\*\\*: *"; ""))"
                + (if $review.createdAt < $pushed then " (from before the last push)" else "" end),
                "  review:  \($review.url)"
              end'

[private]
[script]
_rebase-merge pr:
    # Rebases a PR that is behind main, waits for its checks, then merges it. Merging to main
    # is the deploy.
    title=$(gh pr view "{{ pr }}" --json title --jq .title)
    if [[ $(gh pr view "{{ pr }}" --json mergeStateStatus --jq .mergeStateStatus) == BEHIND ]]; then
        gh pr update-branch "{{ pr }}" --rebase
        # Give GitHub time to register the new head's checks, or --watch sees the old run.
        sleep 10
    fi
    if ! gh pr checks "{{ pr }}" --watch --fail-fast; then
        just log error "Checks failed, stopping" "pr" "{{ pr }}"
        exit 1
    fi
    gh pr merge "{{ pr }}" --rebase --delete-branch
    just log info "Merged" "pr" "{{ pr }}" "title" "$title"
