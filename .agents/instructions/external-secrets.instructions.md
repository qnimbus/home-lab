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

## Exception: an item several apps read

A 1Password item shared by several apps keeps one prefix in all of them,
named after the item rather than the app: every ExternalSecret reading
`cloudflare-tunnel` rewrites to `CF_$1`. The same field then has the same
name wherever it is used. Find an item's prefix before adding a consumer:
`grep -rn -A5 "key: <1password-item-name>" kubernetes`.

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
