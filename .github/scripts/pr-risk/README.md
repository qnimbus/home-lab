# PR risk classifier

`.github/workflows/pr-risk.yaml` answers one question about a PR: can it merge as-is?

| Label         | Meaning                                                                                                      |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| `risk/safe`   | Merge as-is.                                                                                                 |
| `risk/review` | Check the 🟡 findings in the comment first (a changelog to read, a breaking change that seems not to apply). |
| `risk/risky`  | Plan it: a migration the release notes ask for, a data-loss path, a conflict, a render failure.              |

`risk/uncertain` is added when the evidence is thin. It is advisory and fails open. A crash, a missing key, or Jev or Konflate being down leaves the labels as they are, and the job never fails because of them.

For now it only runs on demand, while the in-cluster runner's outbound network is fixed (the runner pods intermittently tried IPv6 and couldn't reach 1Password):

```bash
gh workflow run pr-risk.yaml -f pr=174
```

## How a verdict is made

Code decides. [Jev](https://docs.typesafe.ai) only advises.

Only **findings about this change** raise the level. **Context** that holds for every change to an app is shown in the comment but doesn't: the app's path tier, Jev's blast radius, a major version number, a CRD being touched, files also changed on `main`. The first version counted those as findings and sent nearly every platform bump to review. On the 2026-09-28 runs it labelled a routine external-dns webhook bump (chore-only release notes) risky and a Postgres digest bump review.

1. **Hard rules** (`pr_risk.py`, no model):
   - **Git.** A textual conflict with `main` is risky. These are review:
     - deleted deployed files
     - binaries
     - `dependsOn`, `prune`, `wait`, `suspend` or `healthChecks` edits in a `ks.yaml`
   - **Version.** A `type/major` label, or a `!:` title, means the release notes decide (below). Renovate's `!:` also marks 0.x minor bumps, which it labels `type/minor`. When the PR has no release notes, which is common for charts mirrored to OCI, that's review: someone has to read the upstream changelog.
   - **Path tiers** are context: they order the model's diff budget and make a real finding risky. Only `NEVER_SAFE` paths (Talos, bootstrap), which Konflate doesn't render, block `safe`. When every file is inert (`INERT`: docs, agent and dev tooling), the PR can be safe without Jev.
   - **Konflate.** Rule IDs map to levels in `KONFLATE_RULES`, and unknown rules count as review.
     - Render failures are risky, except that network or chart-fetch failures in Konflate's own environment are review plus uncertain.
     - A missing upstream image is risky.
     - `immutable-field` on a Job is review, or context for a Helm hook that Helm deletes and recreates (`before-hook-creation`/`hook-succeeded`).
     - A CRD whose served or storage versions change is review. Other CRD changes are context: new fields and description churn can't break existing resources.
2. **Jev** answers narrow yes/no questions. It can only **raise** the level.
   - The raw-diff call covers change kind, blast radius, removals, storage, secrets, exposure, Flux substitution, description match, prompt injection, and overlap with `main`.
   - **Breaking changes.** For Renovate PRs the release notes go to Jev in their own field, next to the config the app runs with (the sibling `helmrelease.yaml`, or the compose file). `breaking_notes` asks whether the notes describe a breaking change or a manual step. `breaking_affects_config` asks whether this repo's config uses what it breaks. Both yes is risky (plan the migration). Breaking notes that don't touch the config are review.
   - **Where the notes come from** (`collect`, into `release_notes.json`):
     1. Renovate's `### Release Notes`, split per version. A section only counts if it says something: tailscale's are all "Please refer to the changelog available at …". It also has to be about this package. Its heading link must be a release tag that names the package, or, for a container image only, any tag or changelog. Renovate gave plugin-barman-cloud's _chart_ 0.7.0 → 0.8.0 the _app's_ v0.8.0 notes, a year older and with an unrelated breaking change.
     2. Otherwise the GitHub releases between the two versions, from the repos in Renovate's update table and, for a chart, its org's `helm-charts` and `charts` monorepos. Renovate links the app's repo for prometheus-community's charts. A tag must name the chart (`prometheus-smartctl-exporter-0.17.1`), and a bare `v1.2.3` only counts for an image, so a guessed repo can't produce wrong notes. Releases that all repeat one text (piraeus's chart description) don't count.
     3. Otherwise none, and a major or 0.x bump asks for the changelog, with the reason.

     Versions go to Jev oldest first: when the notes don't fit, the newest are left out, not the ones right after the version running now. On 2026-09-28 this gave all five open Renovate PRs usable notes, where the PR bodies had two.

   - The rendered-diff call runs only when Konflate has a fresh render. It covers availability, data loss, sensitive RBAC grants (Secrets, wildcards, escalate/bind/impersonate, cluster-admin), exposure, privileges, and CRD fields removed, renamed or narrowed. For a human PR it also asks about changes the title doesn't explain. A Renovate title only names the version, so that question fence-sat on every chart bump. CRD `description:` text is left out of the model's input, which keeps CRD-heavy chart bumps inside the budget. When that is all a PR changes in its CRDs, the CRD question isn't asked: the first live run (#177) showed Jev an empty "changed" CRD and got an unsure 0.41, which alone kept the PR from `safe`.
   - Blast radius measures impact, not likelihood, so it's context. A PR becomes risky when a high blast radius (≥ 2.5) comes with an independent, certain finding from git, Konflate or Jev.
3. **`safe` must be earned.** No hard rule fired, every model answer is a clear no, the description matches, `change_kind` confidence is high, and Konflate rendered the PR's current head (when the PR touches Flux resources). Anything short of that is `review`. Fence-sitting answers add `risk/uncertain`.

Thresholds live in `THRESHOLDS`. Tune them with the backtest before trusting the labels.

The first backtest ran on 2026-09-28 with `jev-1.13.0`, over 113 merged PRs:

|        | Count                                  |
| ------ | -------------------------------------- |
| risky  | 11 (8 of them later reverted or fixed) |
| review | 87                                     |
| safe   | 15                                     |

Across all 1,058 direct commits, 9 of the 10 later-reverted ones were flagged review or above. The miss was a paperless-ngx memory-limit bump (`cf4bee2`), and resource limits have no question of their own yet.

That backtest predates the findings-versus-context split above, which removed `blast_review` and the path-tier floors. Replaying the eight manual runs of 2026-09-28 with their recorded Jev answers: #169 (Postgres digest), #178 (external-dns webhook) and #180 (mise tools) went from review/risky to safe, #179 (0.x chart, no release notes) to review for its changelog alone. #172 (kube-prometheus-stack) stayed review only on `immutable-field` for its admission Jobs; they are `before-hook-creation,hook-succeeded` hooks, which now count as context, but its render was gone so the replay couldn't show that. #170 and #171 (tailscale-operator, snapshot-controller) stayed risky on answers to the old, broader CRD and RBAC questions, and need a live run. Re-run the backtest before switching labels on.

## Security model

- The trigger is `workflow_dispatch` with a PR number. It only runs for open, same-repo PRs; the job fetches the PR from the API and stops otherwise. The repo is private, so only push-access actors (you and the Renovate App) open PRs. To run on every PR again, switch the trigger back to `pull_request` on `main` (types `opened, synchronize, reopened, ready_for_review, edited`) and read the event from `$GITHUB_EVENT_PATH`.
- The checkout is the **base** branch, so the classifier always comes from `main`. PR content is read as git objects (`git diff --no-ext-diff --no-textconv`, `git merge-tree`) and is never executed.
- The job runs on the in-cluster `home-lab` runner, because Konflate is internal-only. That runner is cluster-admin, which is exactly why nothing from the PR runs.
- Everything the PR author wrote is untrusted input to the model: the title, body, diff and the rendered YAML. Hard rules come only from Konflate's structured fields. `addressed_to_reviewer` is a prompt-injection tripwire, and a hit makes the PR risky.
- What leaves the cluster: PR diffs and rendered manifests (hostnames, internal IPs) go to TypeSafe. Secrets are ExternalSecret references, so they don't.

## Settings

| Repo variable           | Default                                              | Meaning                                                                                                                     |
| ----------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `PR_RISK_MODE`          | `shadow`                                             | `shadow`: job summary + artifact only. `labels`: also sync `risk/*` labels. `comment`: also a sticky comment.               |
| `PR_RISK_RUNNER`        | `home-lab`                                           | Kept separate from `RUNNER`. On a GitHub-hosted runner Konflate is unreachable, so results are raw-diff-only and uncertain. |
| `JEV_MODEL`             | `jev-1.13.0`                                         | Pinned, because thresholds are tuned per model version.                                                                     |
| `KONFLATE_URL`          | `http://konflate.flux-system.svc.cluster.local:8080` |                                                                                                                             |
| `KONFLATE_WAIT_SECONDS` | `480`                                                | How long to wait for Konflate to render the current head SHA.                                                               |

The Jev key is read from 1Password at `op://GitHub/jev/API_KEY`, using the same service account as the other workflows.

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

Questions a run wasn't asked have no recorded answer, so a replay after rewording or adding questions is only approximate.

## Calibration and rollout

`backtest.py` replays history.

- `prs` mode covers merged PRs, reusing Konflate's renders, which it keeps.
- `commits` mode covers direct commits on `main`, where most past incidents landed.
- Positives come from git: reverted commits (strong), and `fix(...)` commits touching the same files within 48 h (weak).
- The report prints a verdict × truth grid, recall, precision and every **false safe**.

```bash
git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
TYPESAFE_API_KEY=$(op read op://GitHub/jev/API_KEY) \
  python3 .github/scripts/pr-risk/backtest.py prs --konflate-url https://konflate.cluster.vwn.io
```

Rollout:

1. Shadow: read the job summaries for a few weeks next to Konflate's comment.
2. `labels`: once the backtest shows no false safes.
3. `comment`.

GitHub auto-merge isn't available here (no rulesets on this plan). If you ever want the verdict to gate anything, the lever is a check-run that fails on `risky`, because Renovate's automerge (`ignoreTests: false`) waits for checks.
