# Renovate conventions

Prefer Renovate's built-in managers over manual `# renovate:
datasource=...` annotations. `renovate.json5` already enables `flux`,
`helm-values`, `kubernetes`, and `kustomize`, each scoped to
`kubernetes/**/*.yaml`. These parse dependency versions directly from the
manifest structure — no comment needed.

## Don't add a `# renovate:` comment to a field a native manager already covers

Concretely: an `OCIRepository`/`HelmRelease`/`HelmRepository`/
`GitRepository`'s version field (e.g. `spec.ref.tag`) is read natively by
the `flux` manager from `spec.url` plus that field — a manual comment on
top is redundant, and risks the custom regex manager (see below) detecting
the same dependency a second time from the same line.

## Reserve `# renovate: datasource=...` for files with no native manager

The custom regex manager (`.renovate/customManagers.json5`) exists
specifically for cases Renovate has no built-in support for — e.g.
`talos/talenv.yaml`, shell scripts, `.env` files, or a version string
embedded in a `postBuild.substitute` value. Only add the comment there.

## Before adding a new manual comment, check

1. Does an already-enabled manager (`flux`, `helm-values`, `kubernetes`,
   `kustomize`, or one of Renovate's other defaults, e.g.
   `github-actions`/`docker-compose`) already parse this field natively?
   Check `docs.renovatebot.com/modules/manager/<name>/` for what it
   matches.
2. If yes — leave the comment out; centralized/native tracking already
   covers it.
3. If no — add the comment, matching the existing
   `# renovate: datasource=<ds> depName=<name>` format so
   `.renovate/customManagers.json5` picks it up.
