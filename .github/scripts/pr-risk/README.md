# PR risk classifier (`pr-risk/v2`)

`.github/workflows/pr-risk.yaml` answers one question about a PR: **can it merge as-is, on the evidence available now?**

| Label            | Meaning                                                                                                                          |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `risk/safe`      | Merge as-is: every surface is identified, the evidence covers it, and nothing needs a look.                                      |
| `risk/review`    | A bounded check first: a possible or non-grave finding, an obligation, or one piece of evidence a human can fetch (a changelog). |
| `risk/risky`     | Plan it: a concrete defect (conflict, render failure, immutable field), or a grave mechanism (data loss, privilege escalation).  |
| `risk/uncertain` | Added alongside: required evidence is missing, so the verdict can't be earned. An epistemic state, not a fourth severity.        |

It is advisory and fails open. A crash, Jev or Konflate being down, or a missing key leaves the labels as they are, and the job never fails because of them.

It runs on every same-repo, non-draft PR to `main` (opened, pushed to, reopened, marked ready, or its title or body edited), and on demand for any open same-repo PR:

```bash
gh workflow run pr-risk.yaml -f pr=174
```

From 2026-09-28 it ran on demand only, while the in-cluster runner intermittently failed to reach 1Password over IPv6 (`bea8f4e`); the PR trigger came back on 2026-09-30.

## The model

> Reach, stakes and activation describe the change. Findings describe what can go wrong. Evidence describes how well we know. Policy turns those into a verdict.

v1 folded all of that into one `Signal.level`, so a path tier, a model's blast-radius score and a real defect were the same kind of number. v2 keeps them apart, and only findings and evidence reach the policy.

### Context: surfaces

`surfaces.py` maps every changed path to a **surface**, first match wins: an app (`default/paperless`), a component (`component:postgres`), `flux:cluster`, `talos`, `ci:workflows`, `workstation:hooks`, `docs`, and so on. Each has:

| Dimension         | Values                                                                            | Meaning                                                                        |
| ----------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **reach**         | `none` < `workstation` < `ci` < `app` < `shared` < `cluster` < `host`             | How far a real mechanism propagates.                                           |
| **stakes**        | a set of `data`, `credentials`, `trust_boundary`, `control_plane`, `availability` | What is exposed. Content can add one: an app with `persistence:` holds `data`. |
| **activation**    | `pre_merge`, `reconcile`, `operation`, `manual`, `latent`                         | When it takes effect. Workflows run `pre_merge`; tuppr starts an `operation`.  |
| **reversibility** | `revert` < `revert_with_toil` < `non_reversible`                                  | Whether `git revert` restores the state. Findings can lower it.                |

None of these is a finding. A clean Cilium patch bump is `cluster` reach with `control_plane` stakes and nothing wrong with it: **safe**. Reach only decides how grave a real finding's consequence is (below). Executable tooling isn't inert: `.mise/`, `.lefthook.yaml`, `.claude/settings.json` and `.mcp.json` are `workstation:hooks` (they run code on a workstation, before merge), and `.agents/**` is `agents`, not `docs`.

### Findings

A finding is what can go wrong. Each one has:

| Field         | Values                                                                                                                                                      |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code`        | a stable reason code (below)                                                                                                                                |
| `kind`        | `integrity` (known-bad state), `mechanism` (a way harm happens), `obligation` (a human must confirm), `intent`, `evidence` (a gap, see the ledger)          |
| `certainty`   | `established`, `probable`, `possible`, `ruled_out`                                                                                                          |
| `consequence` | `none`, `degradation`, `availability_loss`, `reconciliation_failure`, `data_loss`, `security_exposure`, `privilege_escalation`, `irreversible_state_change` |
| `surface`     | where it lands                                                                                                                                              |
| `evidence`    | ids of the evidence records it rests on                                                                                                                     |

### Evidence ledger

Every surface tracks each evidence source it needs, as `sufficient`, `limited` (a bounded gap a human can close with one check) or `insufficient` (the property can't be established). A source that doesn't apply is absent.

| Source          | Needed when                                                                                                  | Lowered by                                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `git`           | always                                                                                                       | `ev.merge_result_unknown`, `ev.opaque_content` (insufficient)                                                       |
| `render`        | Flux surfaces (Konflate renders them); Talos, bootstrap, ansible                                             | `ev.render_missing`, `ev.render_incomplete` (insufficient); `ev.unrendered_surface` (limited); `ev.unknown_signal`  |
| `release_notes` | the PR crosses a major or 0.x boundary, or the render moves an image a chart deploys across a minor or major | `ev.release_notes_missing`, `ev.release_notes_partial` (limited)                                                    |
| `model`         | every surface but `docs`                                                                                     | `ev.model_unavailable`, `ev.model_indecisive`, `ev.model_input_truncated`, `ev.manipulation_attempt` (insufficient) |
| `invariants`    | always (the deterministic rules ran)                                                                         | `ev.self_evaluation` (limited): the PR changes this classifier                                                      |

A surface's sufficiency is its worst source. Evidence is per surface, so a stale render of one app doesn't make a README change in the same PR uncertain.

`ev.unrendered_surface` is also how the classifier says "the render doesn't show what matters": for a surface that starts an operation (tuppr's Talos and Kubernetes upgrades render as one changed line), and for a configuration change (not a version bump) to a controller with `control_plane` stakes, such as Cilium, Rook or Longhorn, whose effect only shows at runtime.

### Policy (`policy.py`)

| Rule   | When                                                                                                                            | Verdict                                         |
| ------ | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **R1** | any `integrity` finding that is established or probable, or a `mechanism` finding that is established or probable **and grave** | `risky` (plus `uncertain` if evidence is short) |
| **R2** | otherwise, any surface's evidence is `insufficient`                                                                             | `review` + `uncertain`                          |
| **R3** | otherwise, any remaining finding (possible, non-grave, obligation, intent), a `limited` surface, or a `non_reversible` change   | `review`                                        |
| **R4** | none of the above                                                                                                               | `safe`                                          |

A consequence is **grave** when it is `data_loss`, `security_exposure` or `privilege_escalation`; `availability_loss` or `reconciliation_failure` on a surface of reach `shared` or wider; or `irreversible_state_change` on a surface with `data` stakes. So scaling one app to zero is review, and scaling Dragonfly to zero is risky. Reach never escalates on its own: it only grades a finding that exists.

The policy reads findings and the ledger, nothing else: no path tier, no model score, no blast radius.

### Reason codes

Codes are defined in `taxonomy.py` (`CODES`, `CONTEXT_CODES`), and every rule declares the codes it may emit (the registry refuses anything else). Context codes (`ctx.*`) are informational and never escalate.

| Family       | Codes                                                                                                                                                                                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| integrity    | `integrity.merge_conflict`, `render_failed`, `image_unresolvable`, `apply_rejected`, `dependency_unsatisfiable`, `semantic_merge_hazard`                                                                                                                                                                |
| data         | `data.volume_removed`, `volume_identity_changed`, `path_changed`, `recovery_path_changed`, `forward_only_migration`, `engine_major_upgrade`                                                                                                                                                             |
| availability | `avail.capacity_reduced`, `drain_blocked`, `writes_blocked`, `resource_envelope_changed`, `traffic_newly_restricted`, `startup_dependency_changed`                                                                                                                                                      |
| compat       | `compat.breaking_change_applies`, `breaking_change_elsewhere`, `setting_conflict`, `version_pair_split`, `crd_version_dropped`, `crd_storage_version_moved`, `crd_conversion_changed`, `crd_schema_narrowed`                                                                                            |
| lifecycle    | `lifecycle.resource_removed`, `release_reinstalled`, `crd_removed`, `crd_unprotected`, `crd_second_owner`, `namespace_removed`                                                                                                                                                                          |
| recon        | `recon.structural_dependency_removed`, `prune_changed`, `suspension_changed`, `health_gate_changed`, `deletion_policy_changed`, `substitution_unresolved`, `component_contract_broken`, `cluster_defaults_changed`                                                                                      |
| security     | `sec.rbac_widened`, `privilege_added`, `exposure_widened`, `secret_material_in_git`                                                                                                                                                                                                                     |
| execution    | `exec.pre_merge_privileged`, `workflow_privilege_widened`, `review_bypass_widened`, `workstation_hook_changed`                                                                                                                                                                                          |
| intent       | `intent.unexplained_change`, `bot_diff_out_of_shape`                                                                                                                                                                                                                                                    |
| evidence     | `ev.render_missing`, `render_incomplete`, `unrendered_surface`, `release_notes_missing`, `release_notes_partial`, `model_unavailable`, `model_indecisive`, `model_input_truncated`, `opaque_content`, `merge_result_unknown`, `stale_base`, `manipulation_attempt`, `self_evaluation`, `unknown_signal` |
| context      | `ctx.version_boundary`, `release_notes_unlisted`, `crd_touched`, `crd_added`, `base_overlap`, `large_changeset`, `helm_hook_recreated`, `networkpolicy_removed`, `unrendered_surface`, `runner_privileged`, `resource_envelope`, `operand_restart`, `change_exercised`                                  |

Four codes extend the design's list: `compat.crd_conversion_changed` (a dropped conversion webhook isn't a narrowed schema, #171), `integrity.merge_conflict` (the design names the case but not the code), `compat.crd_storage_version_moved` (a storage-version move is an obligation, a dropped served version is a mechanism), and `ev.model_unavailable` (an outage, kept apart from `ev.model_indecisive`). `intent.bot_diff_out_of_shape`, `avail.writes_blocked` and `ev.stale_base` are reserved: nothing emits them yet.

## Where facts come from

### Deterministic rules (`rules.py`)

YAML is read line by line with its enclosing keys worked out from indentation (standard library only), for both the git diff and Konflate's rendered rows, so one rule covers raw and rendered changes. YAML in Markdown, agent docs and scripts is treated as an example, not a manifest.

| Rule                                                                   | Codes                                                                                                                         | What it checks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git.merge`                                                            | `integrity.merge_conflict`, `ev.merge_result_unknown`                                                                         | `git merge-tree`: exit 1 is a conflict (**risky**), any other failure is unknown (**uncertain**).                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `git.removals`                                                         | `lifecycle.resource_removed`, `lifecycle.release_reinstalled`, `data.volume_identity_changed`                                 | Deleted deployed files; an app directory moved (Flux uninstalls the old release).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `git.opaque`, `git.overlap`, `git.size`                                | `ev.opaque_content`, `ctx.base_overlap`, `ctx.large_changeset`                                                                |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `flux.kustomization`                                                   | `recon.*`, `data.recovery_path_changed`                                                                                       | `dependsOn` removals, `prune`, `suspend`, `wait`/health checks, `deletionPolicy`, `substituteFrom` removals, the `substitution.flux.home.arpa/disabled` opt-out, the `components.postgres/cnpg=init` label.                                                                                                                                                                                                                                                                                                                                                         |
| `flux.cluster_defaults`                                                | `recon.cluster_defaults_changed`                                                                                              | `kubernetes/clusters/**` patches every Kustomization/HelmRelease; a changed or removed cluster-settings value changes every app that substitutes it (a new one changes nothing).                                                                                                                                                                                                                                                                                                                                                                                    |
| `flux.components`                                                      | `recon.component_contract_broken`                                                                                             | `collect` works out, at base and head, the `${VAR}`s (no default) each used component needs that neither the ks.yaml's `substitute` nor cluster-settings provides. Newly missing: **risky**.                                                                                                                                                                                                                                                                                                                                                                        |
| `storage.identity`                                                     | `data.volume_identity_changed`, `integrity.apply_rejected`, `data.recovery_path_changed`, `data.engine_major_upgrade`         | `existingClaim`/`claimName`/`KOPIUR_CLAIM` pointed elsewhere; a size that shrinks or a storage class that changes (immutable on a PVC); controller type switched to/from StatefulSet; changes to backup objects (`ObjectStore`, `ScheduledBackup`, …) and recovery settings (not a CRD's schema, which names the same keys without setting anything, #176); a PostgreSQL major version.                                                                                                                                                                             |
| `availability.envelope`                                                | `avail.resource_envelope_changed`, `avail.capacity_reduced`, `avail.drain_blocked`, `ctx.resource_envelope`                   | CPU/memory/ephemeral-storage requests and limits, replica counts (incl. CNPG `instances`, KEDA bounds), PDBs. A lower limit, a new limit, or a request/limit that at least doubles is a possible degradation; scaling to zero is established.                                                                                                                                                                                                                                                                                                                       |
| `availability.netpol`                                                  | `avail.traffic_newly_restricted`, `ctx.networkpolicy_removed`                                                                 | Adding a network policy (or enabling a chart's) is a possible restriction: the cluster has none, so the first one drops everything else. Removing one is context.                                                                                                                                                                                                                                                                                                                                                                                                   |
| `availability.operands`                                                | `ctx.operand_restart`                                                                                                         | An operator's image changes on a surface whose registry entry names its `operands` (`database/cloudnative-pg`): rolling out the operator restarts them, which no render shows (#176). Context only, so a patch bump stays safe.                                                                                                                                                                                                                                                                                                                                     |
| `crd.lifecycle`                                                        | `compat.crd_*`, `lifecycle.crd_*`, `lifecycle.release_reinstalled`, `ctx.crd_*`                                               | A served version dropped, or the schema narrowed for existing objects (a property removed, a type changed, an enum value removed, a property newly required; not new optional fields, whatever they require inside) (**risky**), the storage version moved, the conversion webhook changed or dropped (review), `helm.sh/resource-policy: keep` removed, a new CRD (check no other release owns it), a HelmRelease removed while another is added. Description-only churn is nothing, including description prose whose `description:` line Konflate folded (#186). |
| `security.rbac`                                                        | `sec.rbac_widened`                                                                                                            | New `*` verbs or resources, `escalate`/`bind`/`impersonate`, a `cluster-admin` binding, anonymous subjects: established escalation (**risky**). New access to Secrets: possible (review).                                                                                                                                                                                                                                                                                                                                                                           |
| `security.privileges`                                                  | `sec.privilege_added`                                                                                                         | `privileged`, host namespaces, `allowPrivilegeEscalation`, root, added capabilities, hostPath, compose `network_mode: host`, the Docker socket: an obligation (review).                                                                                                                                                                                                                                                                                                                                                                                             |
| `security.exposure`                                                    | `sec.exposure_widened`                                                                                                        | A route on `envoy-external`, a LoadBalancer Service, a Cloudflare tunnel hostname: an obligation (review). Whether it's unauthenticated is Jev's question; a yes is a mechanism (**risky**).                                                                                                                                                                                                                                                                                                                                                                        |
| `security.secrets`                                                     | `sec.secret_material_in_git`                                                                                                  | Secret-shaped strings on added lines (private keys with key material, tokens), and `kind: Secret` with literal values (not `op://`, templates or public keys).                                                                                                                                                                                                                                                                                                                                                                                                      |
| `exec.surfaces`                                                        | `exec.*`, `ev.self_evaluation`, `ctx.runner_privileged`                                                                       | Workflow steps or triggers (a pinned action bump alone is a dependency bump); `pull_request_target`/`workflow_run` (**risky**); new write permissions; CI scripts; Renovate automerge scope; lefthook, mise hooks/tasks (tool pins alone are not), agent hooks and MCP servers.                                                                                                                                                                                                                                                                                     |
| `konflate.render`                                                      | see below                                                                                                                     |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `evidence.unrendered`, `evidence.release_notes`, `evidence.invariants` | `ev.unrendered_surface`, `ev.release_notes_*`, `ctx.version_boundary`, `ctx.release_notes_unlisted`, `ctx.unrendered_surface` |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

### Konflate

`collect` polls for a finished render of exactly the PR's head SHA. Only Konflate's structured fields are used; its free text is matched for infrastructure errors but never reaches the model.

| Konflate                                                                          | v2                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| unreachable, no URL                                                               | `ev.render_missing` (insufficient) **and** an outage: nothing is published                                                                                                                                     |
| stale, not rendered                                                               | `ev.render_missing` (insufficient): evidence about this run, not an outage                                                                                                                                     |
| render failure the PR caused                                                      | `integrity.render_failed` (**risky**)                                                                                                                                                                          |
| failure in Konflate's environment (network, chart pull)                           | `ev.render_incomplete`, and a `dangling-dependson` on a resource that only looks removed because its render failed is the same gap (#175), not a finding                                                       |
| `removed-pvc`, `removed-namespace`, `removed-crd`                                 | `data.volume_removed`, `lifecycle.namespace_removed`, `lifecycle.crd_removed`                                                                                                                                  |
| `pvc-shrink`, `immutable-field` (non-Job)                                         | `integrity.apply_rejected`                                                                                                                                                                                     |
| `immutable-field` on a Job                                                        | context (`ctx.helm_hook_recreated`) for a Helm hook Helm deletes and recreates (kube-prometheus-stack admission, Envoy Gateway certgen); otherwise a probable mechanism, or possible without the rendered diff |
| `dangling-dependson`, `image-not-found`                                           | `integrity.dependency_unsatisfiable`, `integrity.image_unresolvable`                                                                                                                                           |
| `removed-statefulset`                                                             | `lifecycle.resource_removed` with `data_loss`                                                                                                                                                                  |
| `rbac-widened`, `privileged`, `replicas-zero`, `suspends`/`resumes`, `not-pruned` | `sec.rbac_widened` (possible), `sec.privilege_added`, `avail.capacity_reduced`, `recon.suspension_changed`, `recon.prune_changed`                                                                              |
| `removed-networkpolicy`, `large-changeset`, `major-*-bump`                        | context                                                                                                                                                                                                        |
| any other rule                                                                    | `ev.unknown_signal`: limited (review), or insufficient (uncertain) when Konflate calls it blocking                                                                                                             |

### Release notes

`collect` writes `release_notes.json`:

1. Renovate's `### Release Notes`, split per version. A section only counts if it says something: tailscale's are all "Please refer to the changelog available at …". It also has to be about this package. Its heading link must be a release tag that names the package, or, for a container image only, any tag or changelog. Renovate gave plugin-barman-cloud's _chart_ 0.7.0 → 0.8.0 the _app's_ v0.8.0 notes, a year older and with an unrelated breaking change. The exception is a chart released with its app under the app's bare tags (flux-operator, #210): when the render moves an image over exactly the chart's versions and that image's repo is one Renovate links for the chart, a bare tag there is the chart's too, for these notes and for the GitHub lookup. A sibling chart without an image of its own (flux-instance) qualifies the same way. Without a render nothing shows this, and the notes are dropped as before.
2. Otherwise the GitHub releases between the two versions, from the repos in Renovate's update table and, for a chart, its org's `helm-charts`, `charts` and `helm` repos. A package the table links nothing for is looked up as its own repo when `REPO_PACKAGES` lists it (`siderolabs/talos`); a Docker Hub image is named the same way, so the shape alone isn't enough. One that isn't listed gets a `ctx.release_notes_unlisted` line in the comment saying to add it. A tag must name the chart (`prometheus-smartctl-exporter-0.17.1`), and a bare `v1.2.3` only counts for an image, so a guessed repo can't produce wrong notes. Releases that all repeat one text (piraeus's chart description) don't count.
3. Otherwise none.

A chart has two versions: its own, which the steps above are about, and the app's, which only the render shows. #176's chart notes were CI chores while the operator inside went 1.29.1 → 1.30.1. So `collect` gathers the notes after Konflate's render, and for every image the render moves across a minor or major it adds that image's own GitHub releases, headed with the image's name (`cloudnative-pg v1.30.0`) and limited to the new release line (the old line's later patches are backports). The repo is the image's own for `ghcr.io/<owner>/<name>`, and otherwise what `IMAGE_REPOS` lists: other registries' namespaces aren't GitHub owners. An image is left alone when it is itself the updated package, when it moves over the same versions as the chart (released together, so the chart's notes are the app's), when `IMAGE_IGNORE` lists it (the CSI sidecars every storage chart bundles), or when its tag isn't a plain version once a known build variant is taken off (`v3.14.0-distroless`, `15.0.9-rootless`, `distroless-v1.39.1`). `release_notes.json` lists these images under `images`; one whose releases weren't found, or don't reach back to the running version, is `ev.release_notes_partial` on the surface that runs it, whatever the chart's own version does. A bundle collected without a render has no `images`, so a replay looks nothing up.

Versions go to Jev oldest first: when the notes don't fit, the newest are left out, not the ones right after the version running now. A version boundary (`type/major`, or `!:` in the title; Renovate's `!:` also marks 0.x minor bumps) with no usable notes is `ev.release_notes_missing`, and notes that only reach part of the range are `ev.release_notes_partial`: a bounded gap, so review. Part of the range means the GitHub release list ended, or hit the 1,000-release page limit, before a release at or below the old version was seen (`partial` in `release_notes.json`).

### Workflow runs

For a same-repo PR, GitHub runs the PR's own copy of a workflow it changes, on the PR's head. `collect` writes `checks.json`: for each changed file under `.github/workflows/`, the latest `pull_request` run on exactly the head SHA, with its conclusion and every job or step that didn't succeed (`not_run`). It waits up to `CHECKS_WAIT_SECONDS` for a run still in progress, since Validate and this workflow start together, and only when the run can be used: workflows are the PR's only surface Jev is asked about, so the wait never comes on top of Konflate's. A run that isn't listed gets one more poll (a workflow without a `pull_request` trigger never has one); a poll GitHub didn't answer is retried.

A run counts as having **exercised the change** only when it is green and nothing in it was skipped, because a skipped job or step may be the changed one. It is used in one place: it discharges `compat.breaking_change_elsewhere` (below). A composite action under `.github/actions/` has no run of its own, and `pr-risk.yaml`'s run is this one, so neither is looked up.

### Jev (`semantic.py`)

[Jev](https://docs.typesafe.ai) (`jev-1.13.0`, pinned) is an analyst, not the classifier. It is asked narrow yes/no (`noul`) questions, and only when their subject is present in the diff or the render: the resource-envelope question only when requests or limits change, the network-policy question only when a policy is added, the CRD-schema question only when a CRD's schema (not just its descriptions) changes. What code can establish (change kind, reach) isn't asked; v1's `change_kind` and `blast_radius` are gone. A docs-only PR makes no call. A Renovate bump of one image asks three questions.

| Area           | Questions                                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| compatibility  | `breaking_notes`, `breaking_affects_config`, `forward_only_migration`, `setting_conflict` (against the repo's rules in `semantic.INVARIANTS`), `version_pair_split`, `crd_schema_narrowed` |
| availability   | `resource_envelope_risk`, `reduces_availability`, `traffic_newly_restricted`, `startup_dependency_changed`                                                                                 |
| data           | `data_loss_risk`, `stateful_identity_change`, `recovery_path_changed`, `forward_only_migration`                                                                                            |
| security       | `widens_rbac`, `adds_privileges`, `widens_exposure`, `unauthenticated_external_exposure`                                                                                                   |
| reconciliation | `structural_dependency_removed`, `component_contract_broken`, `cluster_defaults_changed`, `semantic_overlap`                                                                               |
| intent         | `description_matches`, `unexplained_change` (human PRs only: a Renovate title only names the version), `manipulation_attempt`                                                              |

An answer ≥ 0.70 is a **probable** finding, ≤ 0.20 is **ruled out** (recorded as evidence), strictly between 0.35 and 0.65 is **indecisive** (`ev.model_indecisive`: missing evidence, so uncertain), and the rest is a **possible** finding. `breaking_notes` alone counts as no up to 0.35: five chore-only bumps answered 0.21-0.26 in the live backtest. Jev can add findings; it can never remove or lower a deterministic one. RBAC and privilege answers are review-level obligations only, and a `crd_schema_narrowed` yes is at most possible, because the deterministic rules own those facts. An indecisive answer to such a capped question is a possible finding too, not missing evidence: #176's 0.60 made the PR uncertain where a yes would only have made it review. #192 was risky on a 0.81 for purely additive CRD fields.

**Breaking changes** keep v1's logic, as typed findings: breaking notes whose broken setting this repo's `config` uses are `compat.breaking_change_applies` (integrity, probable: **risky**, plan the migration); breaking notes that don't touch the config are `compat.breaking_change_elsewhere` (review); unclear applicability is a possible finding (review), and uncertain if Jev is on the fence.

`config` is what `collect` writes to `config.json`: an app's `helmrelease.yaml` and the files its generators read, a changed component or compose file, and, for a workflow or composite action, the file itself (an action's configuration is its step's `with:` inputs) plus the file names in the repository root, which is what tells Jev there is no `package.json` for setup-node to cache. Before #214 a workflow had no config, so `breaking_affects_config` wasn't asked and a major action bump could only say "there is no config to check it against".

`compat.breaking_change_elsewhere` asks for the notes to be skimmed. When workflows are the only surface Jev was asked about and every changed workflow file's own run exercised the change (above), and `config` went to Jev whole (nothing cut for size), that check has been done: the finding is recorded as `ruled_out` with the run as `checks` evidence, a `ctx.change_exercised` line names the run, and the PR can be **safe** (policy 2.3). A run never lowers `compat.breaking_change_applies`: a break can be silent (a cache that is no longer restored), and a green run only shows the workflow didn't fail.

**Manipulation.** The PR's title, body, diff and rendered YAML are untrusted, and every question says so. A `manipulation_attempt` yes invalidates Jev's evidence for the surfaces that call covered (`ev.manipulation_attempt`, insufficient): the PR can't be safe and is normally review + uncertain. It is not risky merely because the text exists; any finding Jev did raise stays.

## Security model

- **The repository is public** (`gh repo view qnimbus/home-lab --json visibility` says `PUBLIC`; v1's README said private). What follows from that:
  - For a same-repo PR, GitHub runs the PR's own copy of this workflow file, so a PR that edits `pr-risk.yaml` changes what runs on the cluster-admin runner; the classifier code still comes from `main`. That is why only push-access actors' PRs run at all.
  - Anyone can open a PR from a fork, and forks can't be trusted. The job only classifies open PRs whose head is in this repository (the job's `if` for PR events, "Resolve PR" for manual runs), so only push-access actors (the owner and the Renovate App) get classified, and `workflow_dispatch` itself needs write access.
  - Secret material committed in a PR is already published when the PR is pushed; merging makes it permanent in `main`'s history. `sec.secret_material_in_git` is an established integrity finding (**risky**: rotate it) in a public repository and a review obligation in a private one. The visibility comes from the PR payload (`base.repo.visibility`), with `REPO_VISIBILITY` as the fallback and "public" as the default.
  - Workflow artifacts of a public repository are downloadable by anyone signed in, for 30 days. `collect` scans the diff for secret-shaped strings (private keys with key material, GitHub/AWS/Slack/1Password/API tokens, JWTs, age keys) before anything is cut, and redacts them from `pr.diff`, `base_overlap.diff`, `config.json` and the PR title and body. The same redaction is applied to everything sent to Jev.
  - `secrets.json` is that scan's result: a list of `{path, kind}` for each hit on an added line, never the value. It is `[]` for a normal PR. A non-empty list is what raises `sec.secret_material_in_git` (risky: rotate it), and it's kept because the redacted diff no longer shows what was found.
  - The rest of the bundle is public already: the PR (title, body, diff), files at the PR's head, and Konflate's render, which Konflate also serves without auth. Konflate's service account can't read Secrets, so values Flux substitutes from Secrets (`CLOUDFLARE_TUNNEL_ID`, `TAILSCALE_USER`) never reach the render. No credential the workflow holds (the Jev key, the GitHub token) is written to the bundle. `checks.json` holds run ids and step names, which anyone can read on a public repository; reading them is why the job has `actions: read`.
- The checkout is the **base** branch, so the classifier always comes from `main`, and a PR that changes it gets `ev.self_evaluation`. PR content is read as git objects only (`git diff --no-ext-diff --no-textconv`, `git merge-tree`, `git show`, `git ls-tree`, `git grep` against a commit) and is never executed or checked out.
- The job runs on the in-cluster `home-lab` runner, because Konflate is internal-only. That runner is cluster-admin, which is exactly why nothing from the PR runs, and why workflow changes are a pre-merge execution surface in their own right.
- What leaves the cluster: PR diffs and rendered manifests (hostnames, internal IPs), minus anything secret-shaped, go to TypeSafe. The API key is read from 1Password at `op://GitHub/jev/API_KEY` and only ever sent as the bearer token.

## Settings

| Repo variable           | Default                                              | Meaning                                                                                                             |
| ----------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `PR_RISK_MODE`          | `shadow` (set: `comment`)                            | `shadow`: job summary + artifact only. `labels`: also sync `risk/*` labels. `comment`: also a sticky comment.       |
| `PR_RISK_RUNNER`        | `home-lab`                                           | Kept separate from `RUNNER`. On a GitHub-hosted runner Konflate is unreachable: an outage, so nothing is published. |
| `JEV_MODEL`             | `jev-1.13.0`                                         | Pinned, because the answer bands (`semantic.THRESHOLDS`) are tuned per model version.                               |
| `KONFLATE_URL`          | `http://konflate.flux-system.svc.cluster.local:8080` |                                                                                                                     |
| `KONFLATE_WAIT_SECONDS` | `480`                                                | How long to wait for Konflate to render the current head SHA.                                                       |
| `CHECKS_WAIT_SECONDS`   | `240`                                                | How long to wait for the PR's own runs of the workflows it changes. Only a PR that changes one waits.               |

**Where to see why a PR got its label**: the run's job summary (Actions → PR Risk → the run) shows the full comment, in every mode; the `pr-risk-<n>` artifact has `result.json`, `comment.md` and `jev_request.json` (each Jev call's payload as sent: state, questions, model; a call that failed has its `error` there and isn't shown as sent in the comment); in `comment` mode the same text is a sticky comment on the PR.

Only `status: classified` results are published. `classify` exits 3 when Jev (needed by some surface) or Konflate (for a PR it should render) is down; the summary still shows what it would have said, and Publish is skipped.

## Output

`result.json` (schema `pr-risk/v2`, policy version in `policy`):

```yaml
schema: pr-risk/v2
status: classified | unavailable
classification: safe | review | risky
uncertain: false
rule: R1 | R2 | R3 | R4
why: "findings to check: `avail.resource_envelope_changed`"
dimensions: { reach: app, stakes: [availability], activation: [reconcile], reversibility: revert }
surfaces: [{ id, paths, reach, stakes, activation, reversibility, rendered, evidence: { git: sufficient, … }, sufficiency }]
findings: [{ id, code, kind, certainty, consequence, surface, evidence: [e-003], description }]
evidence: [{ id, source, fact, surface, quality }]   # source: git, render, release_notes, model, invariants, checks
context: [{ code, detail, surface }]
jev: { model, usage, errors, asked, answers, sent }   # raw answers, for replay; sent: per call, field sizes and each question as worded
konflate: { state, head, rules, … }
release_notes: { source, versions, reason, sent }   # sent: the notes text Jev got
run_url                                          # in Actions only
verdict, available                               # v1 names, kept while v1 CSVs are compared
```

The comment leads with the verdict and the rule that produced it, then a table of findings (surface, code, certainty, consequence), the missing evidence when uncertain, the context, and, folded, the evidence per surface, where the release notes came from, the size of each field Jev got, its answers next to each question as it was worded for this PR (without notes, `breaking_notes` is asked about `description` for a human PR and not at all for Renovate's, whose description is only the update table), and the release notes as sent (the first 6,000 characters, as a code block so upstream's @mentions notify nobody). No numeric level is shown as if it were a risk score.

## Second opinion

The `review-pr-risk` agent skill (`.agents/skills/review-pr-risk/`) reviews one PR independently in this vocabulary, reaching its own verdict before it reads the workflow's result, then compares the two finding by finding and says which part of the classifier caused any disagreement. Ask Claude Code for "a second opinion on the risk of PR 189".

## Running locally

```bash
# Offline tests (fixtures stand in for git, Konflate and Jev)
uv run --no-project --python 3.13 -m unittest discover .github/scripts/pr-risk/tests

# One PR, end to end
git fetch origin main '+refs/pull/<pr>/head:refs/remotes/origin/pr/<pr>'
gh api repos/qnimbus/home-lab/pulls/<pr> | jq '{pull_request: .}' > /tmp/event.json
GH_TOKEN=$(gh auth token) \
  python3 .github/scripts/pr-risk/pr_risk.py collect --base origin/main --event /tmp/event.json \
  --out /tmp/pr --konflate-url https://konflate.cluster.vwn.io   # the token only lifts GitHub's rate limit
TYPESAFE_API_KEY=$(op read op://GitHub/jev/API_KEY) \
  python3 .github/scripts/pr-risk/pr_risk.py classify --input /tmp/pr --dry-run
# or, offline: classify ... --jev-fixture .github/scripts/pr-risk/tests/fixtures/jev_179.json

# Re-classify a workflow run after a policy change: its artifact is the whole bundle
gh run download <run-id> -D /tmp/run
python3 .github/scripts/pr-risk/pr_risk.py classify --input /tmp/run/pr-risk-<pr> --dry-run \
  --jev-fixture /tmp/run/pr-risk-<pr>/result.json   # replays that run's Jev answers
```

A replay only has answers to the questions that run asked. A question the new policy asks and the old run didn't is unanswered, which is `ev.model_indecisive`, so the replay says uncertain rather than guessing. v1 artifacts replay with their questions mapped to v2 names (`addressed_to_reviewer` → `manipulation_attempt`, `unexpected_changes` → `unexplained_change`, `crd_schema_change` → `crd_schema_narrowed`).

## Calibration

`backtest.py` replays history.

- `prs` mode covers merged PRs, reusing Konflate's renders, which it keeps (`git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'` first).
- `commits` mode covers direct commits on `main`, where most past incidents landed. There's no render for those.
- Positives come from git: reverted commits (strong), and `fix(...)` commits touching the same files within 48 h (weak, and noisy: much of this repo's history is iteration).
- `--no-jev` answers every question with a clear no: the verdict from deterministic rules alone, which Jev can only raise. A false safe there is one only Jev can catch.
- `--baseline <csv>` compares with an earlier run (v1's CSV, or a v2 run before a policy change).
- `--keep <dir>` keeps each item's bundle, `result.json` and `comment.md` (`<dir>/pr-<n>/`), the same as a workflow artifact.
- `replay --keep <dir>` re-classifies a kept run with its recorded Jev answers, for free, and lists every verdict that moves: the way to try a policy change.
- Weak positives ignore follow-ups that are themselves version bumps, and overlap only through shared files (bootstrap helmfiles, docs, Renovate and mise config): one bootstrap fix used to label six chart bumps.

The report prints the verdict × truth grid, recall, precision and every **false safe** with its reach, context and gaps, then verdicts by reach and by finding source, findings by reason code, evidence gaps by code, uncertainty by surface, and the reason codes on positives.

```bash
git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
TYPESAFE_API_KEY=$(op read op://GitHub/jev/API_KEY) \
  python3 .github/scripts/pr-risk/backtest.py prs --konflate-url https://konflate.cluster.vwn.io
python3 .github/scripts/pr-risk/backtest.py commits --no-jev --baseline pr-risk-backtest-v1.csv
```

### Live Jev (2026-09-30, `jev-1.13.0`, 126 merged PRs, replayed on policy 2.1)

| safe | review | risky | uncertain | strong positives flagged | weak false safes            |
| ---- | ------ | ----- | --------- | ------------------------ | --------------------------- |
| 80   | 45     | 1     | 18        | 1/1 (#11)                | 6, all unrelated follow-ups |

The one risky PR is #186 (dragonfly-operator 1.7.0 drops the CRD's `networkPolicyEnabled`, the release that stopped per-instance NetworkPolicies). Jev's extra reviews are mostly breaking notes whose applicability it can't rule out, which the breaking-notes logic keeps at review by design; 14 of the 18 uncertain answers are `breaking_notes`/`breaking_affects_config` on the fence.

### Deterministic only (2026-09-30, policy 2.0, `--no-jev`)

Deterministic rules only, every Jev question answered no. Jev can only raise these verdicts.

| Run                                      | safe | review | risky | strong positives flagged | false safe (strong) |
| ---------------------------------------- | ---- | ------ | ----- | ------------------------ | ------------------- |
| `commits`: all 1,112 direct commits      | 634  | 450    | 28    | 10/10                    | 0                   |
| `prs`: 126 merged PRs (10 with a render) | 107  | 19     | 0     | 1/1                      | 0                   |

Every strong positive is caught for a stated reason:

- **Controller configuration** (`ev.unrendered_surface`, limited): the five Longhorn `storageNetwork` attempts, and Cilium's toFQDNs grace period (`6b68e8e`) and BGP layout (`0cf712a`).
- **tuppr operations** (`ev.unrendered_surface`): the Kubernetes downgrade (`1b541a9`) and a kubelet bump (#11).
- **A changed backup object** (`data.recovery_path_changed`): CNPG's Backblaze region (`bf62c46`).
- **The resource envelope** (`avail.resource_envelope_changed`): paperless-ngx's memory limit going from 4Gi to 12Gi (`cf4bee2`), v1's one false safe.

v1, with Jev, flagged 9 of the 10.

I read every false safe. None of the 210 weak positives that stay safe (a non-Renovate `fix(...)` within 48 hours on the same files) points to a mechanism v2 misses; this history is mostly iteration. Checking the risky verdicts turned up false positives that are fixed and now covered by tests:

- YAML examples in Markdown were read as manifests (`e45cdf0`).
- `op://` Secret templates and PEM placeholders were read as secrets.
- Envoy Gateway's certgen hook, which has no delete policy, was treated as an immutable-field failure (#184).
- Chart pins in the bootstrap helmfile, and mise tool pins, were flagged.
- Adding a namespace to `kubernetes/apps/kustomization.yaml` was flagged.

What remains risky is mostly planned migrations and moves: storage-class switches, app renames and moves that reinstall a release, and new cluster-admin bindings.

## Rollout

1. **Shadow**: done; the backtests above.
2. **`labels`** (2026-09-30): no material historical incident is an unexplained false safe; first live run #189, `risk/safe`.
3. **`comment`** (now, from 2026-09-30): labels plus the scorecard as a sticky PR comment.

GitHub auto-merge isn't available here (no rulesets on this plan). If you ever want the verdict to gate anything, the lever is a dedicated check-run that fails on `risky` (Renovate's automerge, `ignoreTests: false`, waits for checks), not this advisory workflow failing.

## Known gaps

- **Not yet calibrated with live Jev.** The v2 backtests ran with `--no-jev`: no tokens spent, nothing sent out, and they show what the deterministic rules catch alone. The answer bands in `semantic.THRESHOLDS` come from v1, whose questions were broader; v2's questions are new text. Run the live backtest before `labels`.
- **The YAML reader is indentation-based.** Flow mappings are read as one value, anchors and aliases aren't followed, block scalars' contents aren't seen as values, and Helm templating isn't evaluated. The render covers Flux surfaces; the raw-diff rules are a second pass, not a parser.
- **Rendered resources are mapped to surfaces by name** (`Kind ns/name` → `ns/app`). A finding that can't be placed is judged at the PR's widest reach, which errs towards risky.
- **Component contracts** are checked for components a changed ks.yaml uses and consumers of a changed component; a Kustomization with its own `substituteFrom` is skipped (what it provides can't be told from git), and nested components aren't followed.
- **RBAC**: aggregated ClusterRoles, and bindings to broad roles other than `cluster-admin`, aren't recognised as escalation.
- **Resource envelope**: the thresholds (any lower limit, a new limit, at least double) are judgement, not tuned; requests going down aren't flagged.
- **Reserved codes**: `intent.bot_diff_out_of_shape`, `avail.writes_blocked` and `ev.stale_base` are in the taxonomy but nothing emits them yet.
- **Konflate only keeps recent renders**: the PR backtest had fresh renders for 10 of 126 merged PRs; the rest were judged on the raw diff, as `ignored`.
