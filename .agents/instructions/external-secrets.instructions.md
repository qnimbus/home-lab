# ExternalSecret conventions

Default to `dataFrom.extract` + `rewrite.regexp` rather than listing
individual `data` entries:

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
Secret. Name 1Password fields **without** the application prefix: the
rewrite adds it.

## Remapping with `template`

When the app expects env var names that differ from the rewritten keys, add
a `template` to remap them:

```yaml
spec:
  target:
    template:
      data:
        EXPECTED_KEY_NAME: "{{ .PREFIXED_KEY }}"
```

The template runs **after** the rewrite, so reference keys by their
post-rewrite names. A wrong key renders an empty value with no error.

## Exception: discrete `data` + `remoteRef.property`

Only when both hold: the Secret needs specific fields of an item rather
than all of them, and each key must be the bare field name, with no prefix
(as in `flux-system/flux-instance`):

```yaml
spec:
  data:
    - secretKey: githubAppID
      remoteRef:
        key: <1password-item-name>
        property: githubAppID
```
