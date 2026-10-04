# Renovate conventions

Prefer Renovate's built-in managers over manual `# renovate:` comments.
`.renovaterc.json5` enables `flux`, `helm-values`, `kubernetes` and
`kustomize` for files under `kubernetes/` (each manager's
`managerFilePatterns` gives its exact scope), next to Renovate's defaults
such as `github-actions` and `docker-compose`. These read versions from the
manifest structure, so no comment is needed.

## No `# renovate:` comment on a field a native manager covers

An `OCIRepository`/`HelmRelease`/`GitRepository` version field (e.g.
`spec.ref.tag`) is read by the `flux` manager from `spec.url` plus that
field; an `image:` by `kubernetes` or `helm-values`. A comment on top makes
the custom regex manager detect the same dependency a second time.

## Where the comment does belong

On a version no native manager parses: `kubernetes/talos/version.yaml`,
a version field of a custom resource (tuppr's `TalosUpgrade`), a
non-image version inside a Helm values file (`distribution.version` of
`flux-instance`), a shell script.

Use the existing format, on the line above the value:

```yaml
# renovate: datasource=<datasource> depName=<name>
```

The regex manager that matches it is not defined in this repo. It comes from
the `home-operations/renovate-presets` that `.renovaterc.json5` extends.

If unsure whether a manager covers a field, check
`docs.renovatebot.com/modules/manager/<name>/` before adding a comment.
