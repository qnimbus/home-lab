#!/usr/bin/env bash
# CRDs rendered by more than one Helm release, one line per CRD with its
# releases. Empty output is healthy. Reads every release's stored manifest, so
# it takes about ten seconds, and it can't see CRDs shipped from a chart's
# crds/ directory.
#
# Usage: duplicate-crds.sh
set -euo pipefail

helm list -A -o json | jq -r '.[] | "\(.namespace) \(.name)"' | while read -r ns name; do
  helm get manifest "$name" -n "$ns" | yq -N 'select(.kind=="CustomResourceDefinition") | .metadata.name' |
    sed "s|^|$ns/$name |"
done | awk '{r[$2]=r[$2]" "$1; c[$2]++} END {for (k in c) if (c[k]>1) print k ":" r[k]}'
