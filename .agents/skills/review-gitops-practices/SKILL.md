---
name: review-gitops-practices
description: Use when asked to review the GitOps repo for best practices, audit manifest/Flux conventions, or suggest improvements — a static, read-only sweep of Kustomize/Flux structure, HelmRelease/workload hygiene, and secrets handling, checked against both this repo's own documented conventions and community Kubernetes/Flux/GitOps best practices ("review the repo", "any best-practice gaps", "how can we improve this", "audit the manifests", "is this following best practices")
context: fork
---

# Review GitOps practices

A static, read-only review of files in this repo — not a live cluster check (that's
`check-cluster-health`) and not a chart/app scaffold (that's `add-app`). Each run re-derives
findings from scratch by reading the tree; it doesn't persist state between runs.

**Note on the "real" audit skill.** Flux itself publishes an official `gitops-repo-audit` skill
(OCI artifact `ghcr.io/fluxcd/agent-skills`, installed via `flux-operator skills install --agent
claude-code`) that regenerates the living `docs/REPO-AUDIT.md` — this repo used it for at least
eight prior audit passes (see `docs/SESSIONS-ARCHIVE.md` and `docs/REPO-AUDIT.md`'s own header).
It isn't currently installed (`flux-operator` isn't in `.mise/config.toml`), and `scripts/validate.sh`

- `scripts/schemas/` in this repo are vendored leftovers from it. This skill is a **lighter,
  complementary alternative** — it reports findings in chat and never touches `docs/REPO-AUDIT.md`.
  If the user wants the full regenerate-the-living-doc workflow back, point them at reinstalling the
  real one instead of asking this skill to fake it.

## Step 1: Structural validation (reuse existing scripts, don't reinvent)

```bash
# Source-manifest schema validation against Flux OpenAPI schemas (kubeconform-based)
bash scripts/validate.sh -d kubernetes

# dependsOn graph health: cycles, dangling refs, duplicate edges
uv run --with pyyaml python3 scripts/depgraph.py --check
```

`scripts/validate-rendered.sh` (post-Helm-render validation, catches broken values/wiring that
source-level validation can't see) needs `flux-local`, which also isn't in the mise toolchain —
skip it locally unless the user has it installed; CI (`flux-render.yaml`) already covers this on
every PR.

**A nonzero `validate.sh` exit is not automatically a real finding.** It validates _source_
manifests, before Flux resolves `postBuild.substitute` — any `${APP}`, `${VOLSYNC_CLAIM}`,
`${DOMAIN_*}` placeholder still literal in a `metadata.name` or `hostnames` field fails
kubeconform's schema/DNS-label check even though Flux would apply it correctly post-substitution.
This is a known, standing false-positive category (see `docs/REPO-AUDIT.md` § Validation
Results) — read each reported error before treating it as a gap; only an error unrelated to an
unresolved `${...}` placeholder is a real one.

## Step 2: Flux/Kustomize hygiene

```bash
# prune should be true (default) on every Kustomization — flag explicit opt-outs
grep -rn "prune: false" kubernetes/apps kubernetes/flux --include=ks.yaml

# Deprecated Flux API versions (current stable: kustomize.toolkit.fluxcd.io/v1,
# source.toolkit.fluxcd.io/v1, helm.toolkit.fluxcd.io/v2)
grep -rn "toolkit\.fluxcd\.io/v1beta\|toolkit\.fluxcd\.io/v2beta" kubernetes --include="*.yaml"

# Drift-detection opt-outs — cluster-apps injects driftDetection.mode: enabled globally;
# this label is the only way to fully disable it (see docs/CONVENTIONS.md § Drift Detection)
grep -rl "drift-detection.flux.home.arpa/disabled" kubernetes/apps --include="*.yaml" \
  || echo "No opt-outs — all HelmReleases inherit the global default"

# Legacy HelmRepository + chart.spec pattern vs OCIRepository/chartRef (the preferred pattern)
grep -rl "kind: HelmRepository" kubernetes/flux/meta/repos/helm/*.yaml 2>/dev/null

# ks.yaml boilerplate this repo has deliberately dropped — see add-app skill's Common mistakes
grep -rn "^  wait: false\|commonMetadata:\|^  timeout:" kubernetes/apps/*/*/ks.yaml
```

## Step 3: Workload best practices (app-template HelmReleases)

Spot-check, not exhaustive — scoped to HelmReleases using the app-template `controllers:` key;
non-app-template HelmReleases (`cilium`, `external-secrets`, operators, etc.) use a different
values schema and legitimately won't match these:

```bash
apps=$(grep -rl "controllers:" kubernetes/apps --include=helmrelease.yaml)

for f in $apps; do grep -q "runAsNonRoot" "$f" || echo "NO-NONROOT: $f"; done
for f in $apps; do grep -q "readOnlyRootFilesystem" "$f" || echo "NO-READONLY-FS: $f"; done
for f in $apps; do grep -q "requests:" "$f" || echo "NO-RESOURCE-REQUESTS: $f"; done
for f in $apps; do grep -q "probes:" "$f" || echo "NO-PROBES: $f"; done

# Mutable image tags (Renovate pins digests here — `latest` should never appear)
grep -rn 'tag: *"\?latest"\?' kubernetes/apps --include="*.yaml"
```

Cross-check any hit against `docs/CONVENTIONS.md` § app-template v5 before flagging — a missing
`readOnlyRootFilesystem`/`runAsNonRoot` on an image that genuinely can't run non-root is a known,
accepted exception (`.agents/skills/add-app/SKILL.md` documents dropping the pod
`securityContext` only when the image requires it).

## Step 4: Secrets & supply chain

```bash
# Plaintext Secret manifests (expect only cert/decryption target-type references, never a real one)
grep -rl "kind: Secret" kubernetes/ --include="*.yaml" | \
  xargs -I{} sh -c 'grep -q "sops:\|ENC\[" "$1" || echo "CHECK: $1"' _ {}

# ExternalSecrets not using the dataFrom.extract + rewrite.regexp convention
# (docs/CONVENTIONS.md § ExternalSecret conventions — bare `data:` is the documented exception
# only when every field is already unique and unambiguous)
for f in $(grep -rl "kind: ExternalSecret" kubernetes/apps --include="*.yaml"); do
  grep -q "dataFrom:" "$f" || echo "NO-DATAFROM: $f"
done

# OCIRepository sources without cosign verification (informational — coverage tracking,
# not every upstream ships signatures)
total=$(find kubernetes -iname "ocirepository.yaml" | wc -l)
cosign=$(grep -rl "provider: cosign" kubernetes --include=ocirepository.yaml | wc -l)
echo "cosign verify: $cosign / $total OCIRepositories"

# NetworkPolicy / CiliumNetworkPolicy coverage (Cilium is the CNI — either kind counts)
grep -rl "kind: NetworkPolicy" kubernetes --include="*.yaml" | wc -l
grep -rl "kind: CiliumNetworkPolicy" kubernetes --include="*.yaml" | wc -l
```

## Step 5: Don't re-report known/accepted findings

Before writing up anything as a new gap, check whether it's already tracked:

```bash
grep -n "^| I\|^| W\|^### " docs/REPO-AUDIT.md | head -40
grep -n "^-\|^### " docs/ROADMAP.md | head -40
```

`docs/REPO-AUDIT.md`'s Recommendations table and `docs/ROADMAP.md` are where this repo's owner
already decided which gaps are deliberate/low-priority (e.g. zero application-level
`NetworkPolicy`s is a known, accepted posture for this single-tenant homelab behind
Tailscale/internal ingress — not a new finding). Cite the existing entry instead of re-litigating
it; only report something as new if it isn't already there.

## Step 6: Report

Structure findings in three buckets, most important first:

- **🔴 Worth fixing** — deviates from _both_ this repo's own documented convention (`AGENTS.md`,
  `docs/CONVENTIONS.md`, the sibling skills) _and_ general Kubernetes/Flux/GitOps practice, with no
  accepted-exception match in Step 5. Include the file path and a concrete suggested change.
- **🟡 Known/accepted or intentional pattern** — matches an existing `docs/REPO-AUDIT.md`/
  `docs/ROADMAP.md` entry, or one of the repo-specific deliberate tradeoffs below. Say which, don't
  re-argue it.
- **🟢 Already solid** — name what's working well (e.g. universal `dataFrom`/SOPS secrets handling,
  zero `dependsOn` cycles, no `latest` tags) so the user knows it's a deliberate baseline, not an
  oversight you missed checking.

End with a short, ranked "Suggested improvements" list — 3-5 items max, each tied to a 🔴 finding,
ordered by actual impact for a single-tenant homelab (a real security/data-loss gap before a
cosmetic labeling gap).

## Common mistakes (repo-specific false positives to avoid)

- **Flagging `generatorOptions.disableNameSuffixHash: true` as a missing-rollout-trigger bug.**
  This repo deliberately mounts config via `configMapGenerator` without a hash suffix, and
  compensates with `reloader.stakater.com/auto: "true"` triggering the pod restart instead — see
  `.agents/skills/add-app/SKILL.md`. Intentional, not an oversight.
- **Flagging missing `wait`/`commonMetadata`/`timeout` in `ks.yaml`.** All three were deliberately
  dropped as boilerplate (see `add-app`'s Common mistakes) — their _absence_ is the convention.
- **Treating zero `NetworkPolicy`/low cosign coverage as urgent.** Both are existing, explicitly
  accepted low-priority gaps for this cluster (see Step 5) — report them as known, not new.
- **Grading `grep -rl "controllers:"` results as exhaustive.** It only catches app-template
  HelmReleases; a HelmRelease with a different values schema (`cilium`, CRD operators, etc.)
  missing the same field is not comparable and shouldn't be silently folded into the same count.
- **Treating this as a live-cluster check.** Nothing here touches the cluster — `kubectl`,
  `kubeconform`, and `grep` against files on disk only. Use `check-cluster-health` for runtime
  state (Ready conditions, pod health, actual Ceph status).
- **Writing findings into `docs/REPO-AUDIT.md`.** That document is owned by the (currently
  uninstalled) official `gitops-repo-audit` skill — this skill reports in chat only, so the two
  don't drift out of sync or fight over the same file.
