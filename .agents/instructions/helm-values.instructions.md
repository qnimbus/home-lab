# Helm values: don't restate defaults

A HelmRelease's `spec.values` holds only what differs from the chart's
defaults. A value that equals the default is left out.

Why: a restated default reads as a decision. The next reader has to work
out whether it matters, and it keeps overriding the chart after upstream
changes the default for a good reason. A short `values` block also shows at
a glance what is particular to this app.

The same goes for the other layers a manifest inherits from:

- what `cluster-apps` patches onto every Kustomization and HelmRelease
  (`kubernetes/clusters/main/apps.yaml`; see `CLAUDE.md`),
- a component's `${VAR:=default}`: don't set the variable to its default in
  `postBuild.substitute`,
- Kubernetes and Flux API defaults.

## Checking whether a value is a default

The chart's `values.yaml` is not enough: library charts such as app-template
set defaults in their templates. Render the release with and without the
value and compare:

```bash
yq '.spec.values' <app>/app/helmrelease.yaml > "$TMP/with.yaml"
yq 'del(.<path.to.value>)' "$TMP/with.yaml" > "$TMP/without.yaml"
for v in with without; do
  helm template <release> oci://<chart-url> --version <tag> -n <namespace> \
    -f "$TMP/$v.yaml" > "$TMP/out-$v.yaml"
done
diff "$TMP/out-with.yaml" "$TMP/out-without.yaml"
```

No diff means the value is a default: remove it. Removing it changes nothing
that is rendered, so the workload does not restart.

Example: `strategy: Recreate` on an app-template controller. The chart
already renders a Deployment with `Recreate`.

## When to state a default anyway

Only when something outside the chart depends on the value and would break
silently if the default changed:

- another manifest relies on it (a probe, a second release, a route),
- the default is known to differ between chart versions and the release must
  not follow it,
- the value is a safety setting whose absence would be read as "not
  considered" (rare; prefer a README note over a restated value).

Such a value is a declared exception. Say why in the folder's `README.md`
under Gotchas, naming the value and what depends on it, as `media` does for
Plex's `secureConnections=1`. No inline comment: `tidy-folder` moves those
into the README anyway.

A restated default with no such note is a leftover. Remove it when the file
is touched; don't sweep the repo for them unasked.

## Not covered

- Values the `add-app` templates set. The template is the convention, even
  where a line happens to match a chart default.
- Values that only look like defaults. `resources`, `securityContext` and
  probes have no useful chart default here; set them.
