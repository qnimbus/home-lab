set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[doc('List kopiur snapshots in a namespace, oldest first — e.g. `just k8s kopiur snapshots automation`')]
snapshots ns:
    kubectl get snapshots.kopiur.home-operations.com -n "{{ ns }}" --sort-by=.metadata.creationTimestamp
