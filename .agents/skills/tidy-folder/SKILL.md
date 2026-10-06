---
name: tidy-folder
description: Use when asked to document, tidy up, or review a single namespace folder (kubernetes/apps/<ns>) or component folder (kubernetes/components/<name>) — writes or tightens its README.md, moves inline YAML comments into that README (or drops them), and checks the folder's YAML for convention and consistency problems ("write a README for observability", "clean up the postgres component", "tidy kubernetes/apps/media", "move the comments into docs")
---

# Tidy a folder

Works on one folder, either a **namespace** (`kubernetes/apps/<ns>`) or a **component** (`kubernetes/components/<name>`, including nested ones like `keda/http-scaler`). Three outcomes:

1. A short `README.md` at the folder root that says what the folder is for and how it's used.
2. No explanatory comments left in the folder's manifests. Useful ones move into the README; the rest are deleted.
3. YAML that follows the repo's conventions and is consistent with itself. Mechanical fixes are applied, anything else is reported.

Scripts live next to this file in `scripts/`. `$S` below is `.agents/skills/tidy-folder/scripts`, `$D` the target folder, `$T` a scratch dir.

## Step 1: Snapshot and read

```bash
bash $S/render.sh $D $T/before.txt          # normalized render of every kustomization under $D
python3 $S/comments.py list $D              # every comment, tagged [full] / [inline] / [embedded]
```

Then read every file in the folder, the existing `README.md` if there is one, and, for a component, how it's consumed:

```bash
grep -rln "components/<name>" kubernetes --include=ks.yaml     # consumers
grep -n "<name>" kubernetes/clusters/main/apps.yaml                    # label-driven patches (e.g. cnpg=init)
grep -rhoE '\$\{[A-Z_]+(:=[^}]*)?\}' $D | sort -u                     # substitution variables and defaults
```

`BUILD FAILED` lines in `before.txt` are pre-existing and belong in the report. Don't try to fix them silently.

## Step 2: Sort the comments

For every comment from `comments.py list`, decide:

| Comment says…                                                                                                    | Do                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Why** something is set a non-obvious way, a constraint, a gotcha, "don't remove this"                          | Move to README                                                                                        |
| How a piece relates to something outside the file (another app, a patch, the NAS, a just recipe)                 | Move to README                                                                                        |
| What the field already says ("# enable metrics"), a unit hint ("# 7 days"), or `TODO`/history with no effect now | Drop. List `TODO`s in the report so they aren't lost                                                  |
| A commented-out manifest or block (dormant YAML)                                                                 | **Ask** whether to delete it (git keeps history) or restore it. Never paraphrase code into the README |
| A pointer into `docs/`, `ops/` or `.claude/agent-memory/`                                                        | Drop the pointer. Keep the substance only if it's still true                                          |

Hold an existing comment to the same bar as README prose: verify it against the current manifests before carrying it over. A comment describing a setting that has since changed is just wrong.

What `comments.py` never touches:

- **Directives**: `# yaml-language-server:`, `# renovate:`, `# yamllint`. They aren't listed.
- **`*.sops.yaml`**: skipped entirely.
- **App config**: files fed to a `configMapGenerator`/`secretGenerator` other than Helm `values.yaml` (homepage `config/`, configarr `resources/config.yml`, …). They're in the app's own format, and a comment labelling an opaque ID belongs next to it. Leave them unless the user asks, then run with `--include-app-config`.
- **`[embedded]`**: `#` lines inside block scalars. Inline kustomize `patch: |-` blocks (e.g. the PSA label patch in a namespace `kustomization.yaml`) are manifests, so treat them like any other comment and edit by hand. Config, scripts and queries inside a string (fluent-bit config, shell) are app config: leave them.
- **Non-YAML files** (`*.just`, `*.sh`, `.conf`, `.js`/`.css`). Just `[doc()]` attributes and recipe comments feed `just --list`. Out of scope by default. Mention them in the report.

## Step 3: Check the YAML

The sources of truth are `.agents/instructions/*.md`, `CLAUDE.md`, and `add-app`'s templates plus its **Common mistakes** list. Don't restate those rules. Apply them. Check:

**Every file**

- Starts with `---`. Every manifest document carries a `# yaml-language-server: $schema=` line built as `yaml-schemas.instructions.md` describes. Fix a missing or third-party one in the folder you're tidying, and confirm the URL returns `application/json`.
- Key order follows `sorting.instructions.md`. Its app-template rules apply only when the sidecar `ocirepository.yaml` points at `app-template`.
- `yamllint --config-file .yamllint.yaml $D` is clean.

**Namespace**

- `kustomization.yaml` lists every `*/ks.yaml` in the folder, with no dangling entries. The `namespace:` field and the `components/cluster-settings` component are present, and `./namespace.yaml` is listed first in `resources`, except in `flux-system`, which has none (see `CLAUDE.md`). `namespace.yaml` keeps `kustomize.toolkit.fluxcd.io/prune: disabled`.
- Each `ks.yaml` has a `spec.path` that matches its own directory and an explicit `spec.targetNamespace` (the folder's namespace unless it deliberately deploys elsewhere). It has no `wait: false`, `commonMetadata` or `timeout`, and has `wait: true` only when something depends on it and it has no `healthChecks`. `dependsOn` is structural only (`flux-kustomization.instructions.md`) and every target exists. `postBuild.substitute.APP` is set when `components` is used, and `healthCheckExprs` is paired with `healthChecks`.
- Every `app/kustomization.yaml` references files that exist, and every manifest in `app/` is referenced. Report orphans: they're often dormant resources.
- Sources, secrets and Renovate comments follow `helm-sources`, `external-secrets` and `renovate` instructions. There's no NetworkPolicy.

**Component**

- `kind: Component` (`kustomize.config.k8s.io/v1alpha1`).
- Every `${VAR}` is either required (`APP`) or has a `:=default`, and the README's variable table matches the grep from Step 1 exactly, defaults included.

**Consistency across siblings**: the same thing should be done the same way throughout the folder: intervals, `reloader.stakater.com/auto`, security contexts, `&app` anchors, quoting, and whether `dependsOn`/`healthChecks` entries spell out `namespace`. Report the outliers.

When the folder's majority disagrees with a documented convention, or two conventions disagree (e.g. `add-app`'s `ks.yaml` template vs. what most siblings do), report the divergence. Per `AGENTS.md`, propose whether it should become the convention. Don't pick a side silently.

**Fix vs. report**: apply fixes that are mechanical and unambiguous: key order, missing `---`/schema line, redundant boilerplate (`wait: false`, `commonMetadata`, `timeout`), stale file references in the README. Report everything that changes behaviour (`dependsOn`, `wait`, secrets, renames, orphan files) with a concrete suggested change, and ask before applying it.

## Step 4: Write the README

**Models to follow.** `kubernetes/components/nfs-config/README.md` is the target style: purpose first, short sections, tables for inventories, caveats at the end. `kubernetes/apps/system-upgrade/README.md` shows how to lay out a namespace with a real workflow (layout table → how it happens → operating). `kubernetes/components/postgres/README.md` is the component with more to explain: usage caveats, paired variables with a table of their combinations, and a bootstrap flow, still under 100 lines.

**Namespace skeleton** (drop sections that would be empty):

```markdown
# <namespace>

<1–3 sentences: what this namespace is for and how its apps relate.>

## Apps

| App | What it does | Notes | ← one row per ks.yaml; Notes = the one thing to know (deps, exposure, storage)

## How it fits together ← only if there's a real flow: data paths, dependency order, cross-app wiring

## Operating ← just recipes / commands actually used for this namespace

## Gotchas ← the "why" harvested from comments, one bullet each
```

**Component skeleton**: `# <name>` + purpose, `## Use case` (and when **not** to use it), `## What it creates` (Resource | Name | Purpose), `## Usage` (minimal `ks.yaml` + HelmRelease snippet), variables table (Variable | Required | Default | Purpose), `## Caveats`.

**Style rules**

- Aim for a README someone reads in two minutes: roughly 40–100 lines. Only a genuine multi-step workflow justifies more.
- Each fact appears once. Link to a file (`[values.yaml](./tuppr/app/helm/values.yaml)`) instead of repeating what the YAML says.
- Explain _why_ and _what to watch out for_, not _what_. The manifests already say what.
- Don't put anything in that rots: versions, image tags, digests, counts, hardcoded consumer lists. Give a `grep` command instead. An incident date is fine as a one-clause anchor for a non-obvious setting ("rebootMode stays `default` since the 2026-09-25 power-cycle NIC failure"). Don't retell the incident.
- Plain sentences, bold only for real warnings, relative links. Never cite `docs/` or `ops/` (retired).
- Example YAML in a README must follow current conventions (`add-app`, sorting), since people copy it.

**Existing README**: tighten it, don't rewrite it. Keep every warning and load-bearing fact, fold in harvested comments, fix claims that no longer match the files (paths, variable defaults, examples), and cut repetition and narrative. List what you cut in the report so the user can object.

## Step 5: Strip and verify

Run `strip` only once the README is written: it removes the comments from the working tree.

```bash
python3 $S/comments.py strip $D             # full-line + inline comments; [embedded] ones by hand
python3 $S/comments.py list $D              # only intentional [embedded] lines may remain
bash $S/render.sh $D $T/after.txt && diff $T/before.txt $T/after.txt
yamllint --config-file .yamllint.yaml $D
```

The render snapshot has sorted keys and no comments, so the diff must be empty **except** for:

- generated ConfigMaps whose source file lost comments (Helm `values.yaml`), plus the hash-suffixed name referenced in `valuesFrom`, and
- the fixes you deliberately applied in Step 3.

Anything else is a regression. Find it and fix it before reporting. Stripping comments from a Helm values file changes the ConfigMap hash, which re-runs a (no-op) `helm upgrade` for that release. Mention that in the report.

For a component, `render.sh` renders only the resources it adds, not its patches. If a patch file changed beyond comments, render one consumer with `flate build ks --namespace <ns> --output yaml <ks>` (what `just k8s apply-ks` runs) to confirm it still applies.

## Step 6: Report

- **README**: created or tightened, its sections, and anything cut from an existing one.
- **Comments**: how many were moved, dropped, or left (embedded/app config/non-YAML), the TODOs found, and the commented-out blocks awaiting a decision.
- **Fixed**: the mechanical fixes applied, file by file.
- **Findings**: behaviour-changing issues with the suggested change. Mark pre-existing build failures.
- **Conventions to decide**: divergences worth documenting or rejecting (per `AGENTS.md`).

Don't commit unless asked. If asked: `docs(<folder>): add README and move inline comments` (split out `fix`/`refactor` commits for Step 3 changes). Never push.
