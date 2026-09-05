#!/usr/bin/env bash

# Post-render schema check for the Flux tree.
#
# scripts/validate.sh validates the SOURCE manifests. This script validates what Flux would
# actually apply: flux-local renders every Kustomization and HelmRelease (Helm templating with
# the in-tree values, postBuild substitution) and kubeconform checks the result with the same
# flags. Run by .github/workflows/flux-render.yaml (passes the file its container step rendered)
# and by `task flux:validate` (renders here first).
#
# Usage: validate-rendered.sh [rendered.yaml | -]
#   With a file argument (or `-` for stdin) the render step is skipped and that input is validated.
#
# Quirks handled below (all measured on this repo, 2026-09-05):
# - Documents without `kind`: helm 4 (the mise-pinned version) prints its "Pulled:/Digest:" pull
#   summary into the template stream and flux-local emits it as a document. The CI container
#   image bundles helm 3 and never produces these; dropped here so local and CI agree.
# - ConfigMapList: the dragonfly-operator chart emits a ConfigMapList carrying
#   metadata.annotations, which kubeconform's strict ListMeta schema rejects. Kustomize flattens
#   List kinds before Flux applies them, so it is not a real error; the kind is skipped.
# - SOPS-encrypted cluster-secrets: flux-local substitutes placeholder values (no age key
#   needed), so ${VAR}s sourced from it resolve and cause no false positives. The ${...} strings
#   that remain in the render are Grafana/Rook template variables, i.e. legitimate content.

set -euo pipefail

# resolve a relative file argument against the caller's cwd before cd'ing to the repo root
input=""
if [[ $# -ge 1 && "$1" != "-" ]]; then
  input="$(realpath "$1")"
elif [[ $# -ge 1 ]]; then
  input="-"
fi

root_dir="$(git rev-parse --show-toplevel)"
cd "$root_dir"

flux_path="${FLUX_PATH:-kubernetes/flux/cluster}"
schemas_dir="$root_dir/scripts/schemas"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for cmd in kubeconform yq; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "ERROR - $cmd is not installed" >&2
    exit 1
  fi
done
if [[ ! -d "$schemas_dir" ]]; then
  echo "ERROR - Flux OpenAPI schemas not found in $schemas_dir (run: task validate:update)" >&2
  exit 1
fi

if [[ "$input" == "-" ]]; then
  rendered="$tmp/rendered.yaml"
  cat > "$rendered"
  if [[ ! -s "$rendered" ]]; then
    echo "ERROR - nothing received on stdin" >&2
    exit 1
  fi
elif [[ -n "$input" ]]; then
  rendered="$input"
  if [[ ! -s "$rendered" ]]; then
    echo "ERROR - rendered file $rendered is missing or empty" >&2
    exit 1
  fi
else
  if ! command -v flux-local &> /dev/null; then
    echo "ERROR - flux-local is not installed (run: mise install)" >&2
    exit 1
  fi
  rendered="$tmp/rendered.yaml"
  echo "INFO - Rendering $flux_path with flux-local"
  # `build` takes the path positionally; only `test`/`diff` accept --path
  flux-local build all --enable-helm --output-file "$rendered" "$flux_path"
fi

# drop documents without a kind (helm 4 pull summaries, see header) — one yq pass; the counts
# below are for the log line only, so they use grep on the `---` doc separators flux-local
# emits before every document rather than a second parse
filtered="$tmp/filtered.yaml"
yq 'select(.kind != null)' "$rendered" > "$filtered"
total=$(grep -c '^---' "$rendered" || true)
kept=$(grep -c '^kind:' "$filtered" || true)
dropped=$((total - kept))

echo "INFO - Validating $kept rendered documents ($dropped without kind dropped)"
kubeconform -strict -ignore-missing-schemas -skip=Secret,ConfigMapList -summary \
  -schema-location default \
  -schema-location "$schemas_dir/{{.ResourceKind}}{{.KindSuffix}}.json" \
  "$filtered"
echo "INFO - Rendered manifests pass kubeconform"
