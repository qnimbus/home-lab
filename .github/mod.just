set default-list
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

# Renovate, Labeler and Label Sync run on `${{ vars.RUNNER || 'home-lab' }}`: unset means the
# in-cluster runner, ubuntu-24.04 the GitHub-hosted fallback (e.g. while the cluster is down).
# Image Pull ignores it — it needs talosctl access to the nodes.

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
