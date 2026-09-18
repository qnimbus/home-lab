#!/usr/bin/env bash

# Validates renovate.json5 and every local preset it extends (.renovate/*.json5)
# with Renovate's own config-validator: catches JSON5 syntax errors, unknown
# config options, and wrong value types before they reach a live run.
#
# Pinned to the same release .github/workflows/renovate.yaml runs, so a config
# that passes here behaves identically in CI. Bump both together.

set -o pipefail

# renovate: datasource=npm depName=renovate
renovate_version="44.65.5"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root" || exit 1

if ! command -v npx &> /dev/null; then
  echo "ERROR - npx is not installed (needs Node.js)" >&2
  exit 1
fi

npx --yes --package "renovate@${renovate_version}" renovate-config-validator \
  renovate.json5 .renovate/*.json5
