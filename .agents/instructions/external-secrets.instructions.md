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
            target: <APP>_$1 # the app's name in capitals: PLEX_$1
```

A 1Password field named `API_KEY` becomes `PLEX_API_KEY` in the Kubernetes
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
      data:
        EXPECTED_KEY_NAME: "{{ .PREFIXED_KEY }}"
```

The template runs **after** the rewrite — reference keys by their
post-rewrite names. A wrong key renders an empty value with no error.

## Exception: discrete `data` + `remoteRef.property`

Use explicit entries only when both hold: the Secret needs specific fields
of an item rather than all of them, and each key must be the bare field
name, with no prefix (as in `flux-system/flux-instance`):

```yaml
spec:
  data:
    - secretKey: githubAppID
      remoteRef:
        key: <1password-item-name>
        property: githubAppID
```

In every other case use `extract` + `rewrite`.
