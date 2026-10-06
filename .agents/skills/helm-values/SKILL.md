---
name: helm-values
description: Use when checking whether a value in a HelmRelease's spec.values just restates a chart default — before adding a value that might be one, when removing leftovers from a helmrelease.yaml, or when asked "is this a default", "can this value go", "clean up the values of X"
---

# Helm values: is this a chart default?

The rule is in `.agents/instructions/helm-values.instructions.md`: `spec.values` holds only what differs from the chart's defaults. This skill holds the check. `$TMP` is a scratch directory.

The chart's `values.yaml` is not enough to tell: library charts such as app-template set defaults in their templates. Render the release with and without the value and compare. Take `<chart-url>` and `<tag>` from the sidecar `ocirepository.yaml`.

```bash
yq '.spec.values' <app>/app/helmrelease.yaml > "$TMP/with.yaml"
yq 'del(.<path.to.value>)' "$TMP/with.yaml" > "$TMP/without.yaml"
for v in with without; do
  helm template <release> oci://<chart-url> --version <tag> -n <namespace> \
    -f "$TMP/$v.yaml" > "$TMP/out-$v.yaml"
done
diff "$TMP/out-with.yaml" "$TMP/out-without.yaml"
```

- **No diff:** the value is a default. Remove it. Nothing rendered changes, so the workload doesn't restart.
- **A diff:** the value does something. Keep it.
- **The render fails without it:** it isn't a default (for example `service.<name>.controller` once a release has a second controller).

Before removing a default, check the folder's `README.md` under Gotchas: a value listed there is a declared exception and stays.
