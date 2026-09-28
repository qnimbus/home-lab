---
name: review-gitops-practices
description: Use when asked to review the GitOps repo for best practices, audit manifest/Flux conventions, or suggest improvements — a static, read-only sweep of Kustomize/Flux structure, HelmRelease/workload hygiene, and secrets handling, checked against both this repo's own documented conventions and community Kubernetes/Flux/GitOps best practices ("review the repo", "any best-practice gaps", "how can we improve this", "audit the manifests", "is this following best practices")
context: fork
---

# Review GitOps practices

A static, read-only review of files in this repo — not a live cluster check (that's
`check-cluster-health`) and not a chart/app scaffold (that's `add-app`). Each run re-derives
findings from scratch by reading the tree; it doesn't persist state between runs.

**Relation to `gitops-repo-audit`.** Flux's official `gitops-repo-audit` skill is installed
alongside this one (from `ghcr.io/fluxcd/agent-skills`, see `.agents/skills/catalog.yaml`). Use
it for a full generic audit. This skill is the lighter, repo-specific pass: it checks this repo's
own conventions, reuses that skill's vendored scripts for validation, and reports in chat only.

## Step 1: Structural validation (reuse existing scripts, don't reinvent)

```bash
# Schema validation, same invocation as CI (.github/workflows/validate.yaml)
bash .agents/skills/gitops-repo-audit/scripts/validate.sh \
  -d kubernetes \
  -E .github/validate.env \
  -e kubernetes/talos

# Deprecated Flux API versions
bash .agents/skills/gitops-repo-audit/scripts/check-deprecated.sh -d kubernetes

# Dangling dependsOn references (namespace defaults to the app's namespace dir)
names=$(mktemp)
for f in kubernetes/apps/*/*/ks.yaml; do
  ns=$(cut -d/ -f3 <<<"$f")
  yq -N "(.metadata.namespace // \"$ns\") + \"/\" + .metadata.name" "$f"
done | sort -u >"$names"
for f in kubernetes/apps/*/*/ks.yaml; do
  ns=$(cut -d/ -f3 <<<"$f")
  yq -N "(.metadata.namespace // \"$ns\") as \$own | .spec.dependsOn[]? | (.namespace // \$own) + \"/\" + .name" "$f" |
    while read -r d; do grep -qx "$d" "$names" || echo "DANGLING: $f -> $d"; done
done
rm "$names"
```

Post-Helm-render checks (broken values/wiring that source-level validation can't see) run
in-cluster: konflate (`kubernetes/apps/flux-system/konflate/`) renders every PR with flate and
posts a "Konflate" check plus a diff comment. Locally, `flate test all` (flate is in the mise
toolchain) runs the same render.

**A `validate.sh` error on a `${VAR}` is usually a missing placeholder, not a manifest bug.**
`-E .github/validate.env` fills Flux substitution variables with schema-valid placeholders before
validation. A new variable in a pattern-checked field (hostname, IP, CIDR, resource name) that
isn't in that file fails validation even though Flux would apply it fine. The fix is a new line
in `.github/validate.env`, not a manifest change. Variables with a `${VAR:=default}` don't need
an entry.

## Step 2: Flux/Kustomize hygiene

```bash
# prune should be true (default) on every Kustomization — flag explicit opt-outs
grep -rn "prune: false" kubernetes/apps kubernetes/clusters --include=ks.yaml --include=apps.yaml

# Drift-detection opt-outs — cluster-apps injects driftDetection.mode: enabled globally;
# this label is the only way to fully disable it (see CLAUDE.md's cluster-apps defaults)
grep -rl "drift-detection.flux.home.arpa/disabled" kubernetes/apps --include="*.yaml" \
  || echo "No opt-outs — all HelmReleases inherit the global default"

# Legacy HelmRepository + chart.spec pattern vs OCIRepository/chartRef (the preferred pattern)
grep -rl "kind: HelmRepository" kubernetes 2>/dev/null

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

Cross-check any hit against the `add-app` skill's HelmRelease template before flagging — a missing
`readOnlyRootFilesystem`/`runAsNonRoot` on an image that genuinely can't run non-root is a known,
accepted exception (`.agents/skills/add-app/SKILL.md` documents dropping the pod
`securityContext` only when the image requires it).

## Step 4: Secrets & supply chain

```bash
# Plaintext Secret manifests (expect only cert/decryption target-type references, never a real one)
grep -rl "kind: Secret" kubernetes/ --include="*.yaml" | \
  xargs -I{} sh -c 'grep -q "sops:\|ENC\[" "$1" || echo "CHECK: $1"' _ {}

# ExternalSecrets not using the dataFrom.extract + rewrite.regexp convention
# (.agents/instructions/external-secrets.instructions.md — bare `data:` is the documented
# exception only when every field is already unique and unambiguous)
for f in $(grep -rl "kind: ExternalSecret" kubernetes/apps --include="*.yaml"); do
  grep -q "dataFrom:" "$f" || echo "NO-DATAFROM: $f"
done

# OCIRepository sources without cosign verification (informational — coverage tracking,
# not every upstream ships signatures)
total=$(find kubernetes -iname "ocirepository.yaml" | wc -l)
cosign=$(grep -rl "provider: cosign" kubernetes --include=ocirepository.yaml | wc -l)
echo "cosign verify: $cosign / $total OCIRepositories"

# NetworkPolicies: none by design, except the dragonfly component's metrics allow rule
# (CLAUDE.md § Network policies). Anything else listed here is a deviation.
grep -rl "kind: NetworkPolicy\|kind: CiliumNetworkPolicy" kubernetes --include="*.yaml"
```

## Step 5: Don't re-report known/accepted findings

Before writing up anything as a new gap, check whether it's already a documented decision:

- `CLAUDE.md`: e.g. no NetworkPolicies by design, the `flux-system` namespace-component exception,
  the cluster-apps defaults and their opt-out labels.
- `.agents/instructions/*.md` and the sibling skills' **Common mistakes** lists (`add-app`,
  `tidy-folder`).
- Folder READMEs, which record per-area trade-offs (`find kubernetes -name README.md`), e.g.
  `components/postgres` (single instance, PDB off) and `apps/system-upgrade` (tuppr's
  `dependsOn` on kube-prometheus-stack).
- Open issues: `gh issue list --state open`.

Cite the existing decision instead of re-litigating it; only report something as new if it isn't
already there.

## Step 6: Report

Structure findings in three buckets, most important first:

- **🔴 Worth fixing** — deviates from _both_ this repo's own documented convention (`AGENTS.md`,
  `.agents/instructions/`, `CLAUDE.md`, the sibling skills) _and_ general Kubernetes/Flux/GitOps practice, with no
  accepted-exception match in Step 5. Include the file path and a concrete suggested change.
- **🟡 Known/accepted or intentional pattern** — matches a documented decision from Step 5, or
  one of the repo-specific deliberate tradeoffs below. Say which, don't re-argue it.
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
- **Treating zero `NetworkPolicy`s as a gap.** It's a documented decision (CLAUDE.md § Network
  policies). Low cosign coverage is informational too, since not every upstream signs charts.
- **Grading `grep -rl "controllers:"` results as exhaustive.** It only catches app-template
  HelmReleases; a HelmRelease with a different values schema (`cilium`, CRD operators, etc.)
  missing the same field is not comparable and shouldn't be silently folded into the same count.
- **Treating this as a live-cluster check.** Nothing here touches the cluster — `kubectl`,
  `kubeconform`, and `grep` against files on disk only. Use `check-cluster-health` for runtime
  state (Ready conditions, pod health, actual Ceph status).
- **Writing findings into files.** This skill reports in chat only. `docs/` and `ops/` are
  retired; don't recreate an audit document there.
