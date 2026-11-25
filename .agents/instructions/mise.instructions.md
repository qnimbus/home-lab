# mise tool conventions

For `.mise/config.toml`, `.mise/mise.lock` and `.mise/locks/`.

## Backends: no plugins

A tool goes on a backend mise ships: a registry short name (`kubectl`), or
`aqua:`, `github:`, `pypi:` or `npm:`. Never a plugin: no `[plugins]`
section, no `vfox:`/`asdf:` tool, no plugin-provided backend such as
`krew:`. A kubectl plugin with GitHub releases goes on `github:`, as
`github:elsesiy/kubectl-view-secret` does.

Why: Renovate regenerates the lockfile with `MISE_SAFE=1` on a fresh
runner, and safe mode refuses to install plugins. One plugin fails the lock
for every tool, so each mise PR then carries a stale lockfile and validate's
locked install fails.

## Dependency locks under `.mise/locks/`

The `pypi:` and `npm:` tools (`yamllint`, `pypi:ansible`,
`pypi:ansible-core`, `oxfmt`) carry a dependency lock per version,
`.mise/locks/<tool>/<version>/`. `mise lock` writes them; never edit one by
hand. Each must match the version in `.mise/config.toml`, or every
`mise lock` fails with `Python lock does not match the requested tool`.

Renovate's other managers leave them alone only because its default
`ignorePaths` lists `**/.mise/locks/**`. An `ignorePaths` in
`.renovaterc.json5` replaces that list, so it has to repeat the entry:
without it, the `pep621` and `npm` managers bump a lock on its own.

Renovate writes the pypi locks through the post-upgrade task in
`.renovaterc.json5` (`installTools` mise, python and uv: containerbase
installs uv with pip). A new pypi tool goes on that task's command and on
`RENOVATE_ALLOWED_COMMANDS` in `.github/workflows/renovate.yaml`, which must
match it exactly.

## Testing a change the way Renovate runs it

Run on a copy of `.mise/` outside the repo: a worktree under
`.claude/worktrees/` also loads the main checkout's `.mise/config.toml`.
Point the global config at an empty file, so plugins installed on the
workstation don't mask or cause a failure:

```sh
d=$(mktemp -d) && git archive HEAD .mise | tar x -C "$d" && cd "$d" && touch empty.toml &&
  MISE_SAFE=1 MISE_DATA_DIR="$d/data" MISE_CACHE_DIR="$d/cache" MISE_CONFIG_DIR="$d/cfg" \
  MISE_GLOBAL_CONFIG_FILE="$d/empty.toml" MISE_SYSTEM_CONFIG_FILE="$d/empty.toml" \
  MISE_TRUSTED_CONFIG_PATHS="$d" mise lock
```
