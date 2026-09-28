# PR risk classifier

`.github/workflows/pr-risk.yaml` labels a PR `risk/safe`, `risk/review` or `risk/risky`, plus `risk/uncertain` when the evidence is thin. It is advisory and fails open. A crash, an outage or a missing key leaves the labels as they are, and the job never fails because of them.

For now it only runs on demand, while the in-cluster runner's outbound network is fixed (the runner pods intermittently tried IPv6 and couldn't reach 1Password):

```bash
gh workflow run pr-risk.yaml -f pr=174
```

## How a verdict is made

Code decides. [Jev](https://docs.typesafe.ai) only advises.

1. **Hard rules** (`pr_risk.py`, no model):
   - **Git.** A textual conflict with `main` is risky. These are review:
     - files also changed on `main` since the branch point
     - deleted deployed files
     - binaries
     - `dependsOn`, `prune`, `wait`, `suspend` or `healthChecks` edits in a `ks.yaml`
   - **PR.** A `type/major` label, or a `!:` title, is review.
   - **Path tiers.** Cluster foundation (`FOUNDATION`) is review and never safe. Shared or directly deployed paths (`SHARED`) are review. When every file is inert (`INERT`: docs, agent and dev tooling), the PR can be safe without Jev.
   - **Konflate.** Rule IDs map to levels in `KONFLATE_RULES`, and unknown rules count as review.
     - Render failures are risky, except that network or chart-fetch failures in Konflate's own environment are review plus uncertain.
     - A missing upstream image is risky.
     - CRD changes are review.
2. **Jev** answers narrow yes/no questions in two calls. It can only **raise** the level.
   - The raw-diff call covers change kind, blast radius, storage, secrets, exposure, Flux substitution, breaking notes, description match, prompt injection, and overlap with `main`.
   - The rendered-diff call runs only when Konflate has a fresh render. It covers availability, data loss, RBAC, exposure, privileges, CRD schema, and changes the title doesn't explain.
   - Blast radius measures impact, not likelihood. On its own it only asks for review. A PR becomes risky when a high blast radius (≥ 2.5) comes with an independent, certain finding, such as a major bump, a Konflate caution or a storage change.
3. **`safe` must be earned.** No hard rule fired, every model answer is a clear no, the description matches, confidence is high, and Konflate rendered the PR's current head (when the PR touches Flux resources). Anything short of that is `review`. Fence-sitting answers add `risk/uncertain`.

Thresholds live in `THRESHOLDS`. Tune them with the backtest before trusting the labels.

The first backtest ran on 2026-09-28 with `jev-1.13.0`, over 113 merged PRs:

|        | Count                                  |
| ------ | -------------------------------------- |
| risky  | 11 (8 of them later reverted or fixed) |
| review | 87                                     |
| safe   | 15                                     |

Across all 1,058 direct commits, 9 of the 10 later-reverted ones were flagged review or above. The miss was a paperless-ngx memory-limit bump (`cf4bee2`), and resource limits have no question of their own yet. The main knob left is `blast_review` (1.5), which currently sends most shared-platform bumps to review.

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

# One PR, end to end. A minimal event JSON is enough (see backtest.py for its shape)
python3 .github/scripts/pr-risk/pr_risk.py collect --base origin/main --event event.json \
  --out /tmp/pr --konflate-url https://konflate.cluster.vwn.io
python3 .github/scripts/pr-risk/pr_risk.py classify --input /tmp/pr --dry-run \
  --jev-fixture .github/scripts/pr-risk/tests/fixtures/jev_179.json   # omit it to call Jev for real
```

## Calibration and rollout

`backtest.py` replays history.

- `prs` mode covers merged PRs, reusing Konflate's renders, which it keeps.
- `commits` mode covers direct commits on `main`, where most past incidents landed.
- Positives come from git: reverted commits (strong), and `fix(...)` commits touching the same files within 48 h (weak).
- The report prints a verdict × truth grid, recall, precision and every **false safe**.

```bash
git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
TYPESAFE_API_KEY=$(op read op://homelab/jev/API_KEY) \
  python3 .github/scripts/pr-risk/backtest.py prs --konflate-url https://konflate.cluster.vwn.io
```

Rollout:

1. Shadow: read the job summaries for a few weeks next to Konflate's comment.
2. `labels`: once the backtest shows no false safes.
3. `comment`.

GitHub auto-merge isn't available here (no rulesets on this plan). If you ever want the verdict to gate anything, the lever is a check-run that fails on `risky`, because Renovate's automerge (`ignoreTests: false`) waits for checks.
