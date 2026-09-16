# ExternalSecret conventions

Default to the `dataFrom.extract` + `rewrite.regexp` pattern rather than
listing individual `data` entries. This keeps 1Password item fields short
and prefix-free while the resulting Kubernetes Secret keys carry the
application prefix.

## Pattern

```yaml
spec:
  dataFrom:
    - extract:
        key: <1password-item-name>
      rewrite:
        - regexp:
            source: (.*)
            target: APP_$1 # adds APP_ prefix to every extracted field
```

A 1Password field named `API_KEY` becomes `APP_API_KEY` in the Kubernetes
Secret. Name 1Password fields **without** the application prefix — the
rewrite adds it.

## When to add a `template` block

If the application's expected env var names don't all share a single
prefix (or otherwise differ from the rewritten key names), add a
`template` section to remap:

```yaml
spec:
  target:
    template:
      engineVersion: v2 # required for {{ .KEY }} syntax
      data:
        EXPECTED_KEY_NAME: "{{ .PREFIXED_KEY }}"
```

The template runs **after** the rewrite — reference keys by their
post-rewrite names. Always set `engineVersion: v2`; the v1 default uses a
different interpolation format and is deprecated.

## Exception: discrete `data` + `remoteRef.property`

`extract` pulls every field of an item and relies on `rewrite` to keep keys
collision-free — overkill when an item's fields are already few, unique,
and unambiguous. In that case, use the explicit form instead:

```yaml
spec:
  data:
    - secretKey: githubAppID
      remoteRef:
        key: <1password-item-name>
        property: githubAppID
```

Reach for `extract` + `rewrite` by default; drop to explicit
`data`/`remoteRef` only when every field is already named individually and
collision risk is a non-issue.
