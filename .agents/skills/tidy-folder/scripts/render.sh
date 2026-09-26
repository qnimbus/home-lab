#!/usr/bin/env bash
# Render every kustomization under a dir into a normalized snapshot:
# comments dropped, keys sorted, one document per line, lines sorted. Two
# snapshots differ only if the change was semantic, not cosmetic. Exception:
# generated ConfigMaps (e.g. Helm values) carry their source file verbatim,
# comments included, so stripping those shows up in their data and hash name.
# A `kind: Component` can't be built on its own, so it's rendered through a
# throwaway wrapper kustomization; its patches then have nothing to match, and
# only the resources it adds show up.
#
# Usage: render.sh <dir> <out-file>
set -euo pipefail

dir="${1:?dir}"
out="${2:?output file}"
: >"${out}"
wrap="$(mktemp -d)"
trap 'rm -rf "${wrap}"' EXIT

while IFS= read -r ks; do
    d="$(dirname "${ks}")"
    target="${d}"
    if [[ "$(yq '.kind' "${ks}")" == "Component" ]]; then
        target="${wrap}/$(echo "${d}" | tr / _)"
        mkdir -p "${target}"
        printf 'apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\ncomponents:\n  - %s\n' \
            "$(python3 -c 'import os, sys; print(os.path.relpath(*sys.argv[1:]))' "${d}" "${target}")" \
            >"${target}/kustomization.yaml"
    fi
    if ! rendered="$(kustomize build --load-restrictor LoadRestrictionsNone "${target}" 2>&1)"; then
        echo "BUILD FAILED: ${d}" >>"${out}"
        printf "%s\n" "${rendered}" >>"${out}"
        continue
    fi
    echo "${rendered}" |
        yq ea -o=json -I=0 'sort_keys(..)' |
        sed "s|^|${d}\t|" >>"${out}"
done < <(find "${dir}" -name kustomization.yaml | sort)

sort -o "${out}" "${out}"
