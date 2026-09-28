"""Offline tests for pr_risk.py: no network, no git, no API key.

    uv run --no-project --python 3.13 -m unittest discover .github/scripts/pr-risk/tests
"""

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent))

import pr_risk as p  # noqa: E402


def load(name):
    return json.loads((FIX / name).read_text())


def fresh(summary_file):
    return {"state": "fresh", "summary": load(summary_file)}


def levels(signals, source=None):
    return [s.level for s in signals if source is None or s.source == source]


class Bundle:
    """A copy of bundle_179 that a test can edit before classifying."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copytree(FIX / "bundle_179", self.dir, dirs_exist_ok=True)

    def edit(self, name, fn):
        path = self.dir / name
        path.write_text(json.dumps(fn(json.loads(path.read_text()))))

    def classify(self, fixture=None, key=None):
        return p.classify(self.dir, key=key, model=p.JEV_MODEL_DEFAULT, fixture=fixture)

    def cleanup(self):
        shutil.rmtree(self.dir)


def clear_jev():
    """A Jev fixture where every answer is a confident, clean 'no'."""
    fx = load("jev_179.json")
    for call in fx.values():
        for a in call["answers"].values():
            if "noul" in a:
                a["noul"] = 0.03
        call["answers"].get("description_matches", {})["noul"] = 0.95
    fx["raw"]["answers"]["blast_radius"].update(score=0.8, confidence=0.8)
    return fx


class TestGlobsAndTiers(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(p.matches("kubernetes/apps/media/plex/app/helmrelease.yaml", ["kubernetes/apps/**"]))
        self.assertTrue(p.matches("README.md", ["**/*.md"]))
        self.assertTrue(p.matches("a/b/README.md", ["**/*.md"]))
        self.assertFalse(p.matches("kubernetes/apps/media/plex/ks.yaml", ["kubernetes/apps/*/kustomization.yaml"]))
        self.assertTrue(p.matches("kubernetes/apps/system/openebs/ks.yaml", ["kubernetes/apps/system/{openebs,kopiur}/**"]))
        self.assertFalse(p.matches("kubernetes/apps/system/openebs-x/ks.yaml", ["kubernetes/apps/system/{openebs,kopiur}/**"]))

    def test_tiers(self):
        cases = {
            "kubernetes/talos/version.yaml": "foundation",
            "kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml": "foundation",
            "kubernetes/apps/rook-ceph/README.md": "inert",  # docs win over location
            "kubernetes/components/postgres/cluster.yaml": "shared",
            "kubernetes/apps/media/kustomization.yaml": "shared",
            "docker/nas/00-exporters/docker-compose.yaml": "shared",
            ".github/workflows/validate.yaml": "shared",
            ".github/labels.yaml": "inert",
            ".mise/config.toml": "inert",
            "kubernetes/apps/media/plex/app/helmrelease.yaml": "app",
        }
        for path, want in cases.items():
            self.assertEqual(p.tier(path), want, path)


class TestKonflateSignals(unittest.TestCase):
    def test_clean_render(self):
        s, info = p.konflate_signals(fresh("konflate_summary_179.json"), True)
        self.assertEqual(s, [])
        self.assertEqual(info["head"], "fa8b518")

    def test_immutable_job_is_review(self):
        s, info = p.konflate_signals(fresh("konflate_summary_172.json"), True)
        self.assertEqual(levels(s), [1, 1])
        self.assertEqual(info["rules"], ["immutable-field", "immutable-field"])

    def test_immutable_non_job_is_risky(self):
        k = fresh("konflate_summary_172.json")
        k["summary"]["diff"]["warnings"][0]["resource"] = "StatefulSet default/forgejo"
        self.assertEqual(max(levels(p.konflate_signals(k, True)[0])), 2)

    def test_infra_failures_are_uncertain_not_risky(self):
        s, _ = p.konflate_signals(fresh("konflate_summary_175.json"), True)
        failure = [x for x in s if "fetch sources" in x.reason]
        self.assertEqual(len(failure), 1)
        self.assertEqual(failure[0].level, 1)
        self.assertTrue(failure[0].uncertain)
        self.assertIn(2, levels(s))  # dangling-dependson is risky in its own right

    def test_real_failure_is_risky(self):
        k = fresh("konflate_summary_175.json")
        k["summary"]["diff"]["failures"] = [{"parent": "HelmRelease x/y", "message": "values don't meet the schema"}]
        k["summary"]["diff"]["warnings"] = None
        s, _ = p.konflate_signals(k, True)
        self.assertEqual(levels(s), [2])

    def test_unknown_rule_is_review(self):
        k = fresh("konflate_summary_179.json")
        k["summary"]["diff"]["warnings"] = [{"level": "caution", "rule": "brand-new-rule", "resource": "X a/b"}]
        s, _ = p.konflate_signals(k, True)
        self.assertEqual(levels(s), [1])
        self.assertIn("unknown rule", s[0].reason)

    def test_blocking_and_missing_image(self):
        k = fresh("konflate_summary_178.json")
        k["summary"]["diff"]["warnings"] = [{"level": "blocking", "rule": "image-not-found", "resource": "Deployment a/b"}]
        k["summary"]["diff"]["images"][0]["upstream"] = "missing"
        self.assertEqual(levels(p.konflate_signals(k, True)[0]), [2, 2])

    def test_unavailable(self):
        s, _ = p.konflate_signals({"state": "stale", "summary": {"reason": "rendering"}}, True)
        self.assertEqual(levels(s), [1])
        self.assertTrue(s[0].uncertain)
        self.assertEqual(p.konflate_signals({"state": "skipped", "summary": {}}, False)[0], [])


class TestKonflateFetch(unittest.TestCase):
    HEAD = "fa8b5186bf82ba379efa242c6445f6ab668eea34"

    def run_fetch(self, responses, wait=60):
        clock = {"t": 0.0}
        calls = iter(responses)

        def fake_http(url, **kw):
            if url.endswith("/diff"):
                return 200, {}, load("konflate_diff_179.json")
            return next(calls)

        with mock.patch.object(p, "http_json", side_effect=fake_http):
            return p.konflate_fetch(
                179, self.HEAD, "http://k", wait,
                sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
                now=lambda: clock["t"],
            )  # fmt: skip

    def test_polls_through_202_and_stale_sha(self):
        stale = copy.deepcopy(load("konflate_summary_179.json"))
        stale["diff"]["headSha"] = "0123456789abcdef"
        ok = load("konflate_summary_179.json")
        state, summary, diff = self.run_fetch([(202, {}, {"status": "running"}), (200, {}, stale), (200, {"X-Konflate-Render-Status": "ok"}, ok)])
        self.assertEqual(state, "fresh")
        self.assertEqual(summary["renderStatus"], "ok")
        self.assertEqual(len(diff["diff"]["resources"]), 3)

    def test_gives_up(self):
        state, summary, _ = self.run_fetch([(202, {}, {})] * 50, wait=30)
        self.assertEqual(state, "stale")
        self.assertIn("rendering", summary["reason"])

    def test_refresh_error_is_not_fresh(self):
        bad = copy.deepcopy(load("konflate_summary_179.json"))
        bad["refreshError"] = "fetch failed"
        state, _, _ = self.run_fetch([(200, {}, bad)] * 50, wait=30)
        self.assertEqual(state, "stale")

    def test_unreachable(self):
        with mock.patch.object(p, "http_json", side_effect=OSError("connection refused")):
            state, summary, _ = p.konflate_fetch(179, self.HEAD, "http://k", 60, sleep=lambda s: None)
        self.assertEqual(state, "unavailable")


class TestDiffBudgets(unittest.TestCase):
    def test_priority_and_truncation(self):
        big = "+" + "x" * 50 + "\n"
        diff = (
            "diff --git a/README.md b/README.md\n" + big * 20
            + "diff --git a/kubernetes/talos/version.yaml b/kubernetes/talos/version.yaml\n" + big * 2
            + "diff --git a/.mise/mise.lock b/.mise/mise.lock\n" + big * 5
        )  # fmt: skip
        text, truncated, omitted = p.budget_diff(diff, total=400, per_file=10_000)
        self.assertTrue(text.startswith("diff --git a/kubernetes/talos"))
        self.assertNotIn("mise.lock", text + "".join(omitted))  # dropped, not "omitted"
        self.assertEqual(omitted, ["README.md"])
        self.assertTrue(truncated)

    def test_rendered_strips_html_and_orders_by_kind(self):
        text, truncated = p.budget_rendered(load("konflate_diff_179.json"), 60_000, 8_000)
        self.assertNotIn("<span", text)
        self.assertIn("+      expr: smartctl_device_smart_status != 1", text)
        self.assertLess(text.index("OCIRepository"), text.index("PrometheusRule"))
        self.assertFalse(truncated)

    def test_renovate_description_cleaned(self):
        body = json.loads((FIX / "bundle_179" / "meta.json").read_text())["body"]
        cleaned = p.clean_description(body, "renovate")
        self.assertIn("0.16.1", cleaned)
        self.assertNotIn("rebase", cleaned.lower())
        self.assertNotIn("renovate-debug", cleaned)
        self.assertIn("<!-- hidden -->", p.clean_description("x <!-- hidden -->", "owner"))


class TestJevClient(unittest.TestCase):
    def test_retries_then_succeeds(self):
        responses = iter([(529, {"Retry-After": "1"}, "overloaded"), (200, {}, {"answers": {}, "model": "m"})])
        sleeps = []
        with mock.patch.object(p, "http_json", side_effect=lambda *a, **k: next(responses)):
            r = p.call_jev({}, {}, key="k", model="m", sleep=sleeps.append)
        self.assertEqual(r["model"], "m")
        self.assertEqual(sleeps, [1.0])

    def test_401_does_not_retry(self):
        with mock.patch.object(p, "http_json", return_value=(401, {}, {"error": "bad key"})) as h:
            with self.assertRaises(p.JevError):
                p.call_jev({}, {}, key="k", model="m", sleep=lambda s: None)
        self.assertEqual(h.call_count, 1)


class TestDecision(unittest.TestCase):
    def setUp(self):
        self.b = Bundle()

    def tearDown(self):
        self.b.cleanup()

    def test_real_fixture_is_review(self):
        r = self.b.classify(fixture=load("jev_179.json"))
        self.assertEqual(r["verdict"], "review")
        self.assertIn("risk/uncertain", r["labels"])  # unexpected_changes fence-sits
        self.assertEqual(r["change_kind"], "version_bump")

    def test_safe_is_earned(self):
        self.b.edit("meta.json", lambda m: {**m, "title": "fix(container): update image foo (1.0.1 ➔ 1.0.2)"})
        r = self.b.classify(fixture=clear_jev())
        self.assertEqual(r["verdict"], "safe", r["signals"])
        self.assertEqual(r["labels"], ["risk/safe"])

    def test_not_safe_without_konflate(self):
        self.b.edit("meta.json", lambda m: {**m, "title": "fix: x"})
        self.b.edit("konflate.json", lambda k: {"state": "stale", "summary": {"reason": "rendering"}})
        r = self.b.classify(fixture=clear_jev())
        self.assertEqual(r["verdict"], "review")
        self.assertTrue(r["uncertain"])

    def test_not_safe_without_jev(self):
        self.b.edit("meta.json", lambda m: {**m, "title": "fix: x"})
        r = self.b.classify(key=None)
        self.assertEqual(r["verdict"], "review")
        self.assertTrue(r["uncertain"])
        self.assertIn("raw", r["jev"]["errors"])

    def test_model_cannot_lower_hard_rule(self):
        self.b.edit("conflict.json", lambda c: {"conflict": True, "files": ["x"]})
        self.assertEqual(self.b.classify(fixture=clear_jev())["verdict"], "risky")

    def test_foundation_never_safe(self):
        self.b.edit("meta.json", lambda m: {**m, "title": "fix: x"})
        self.b.edit("files.json", lambda f: [{**f[0], "path": "kubernetes/apps/rook-ceph/rook-ceph/app/ocirepository.yaml"}])
        r = self.b.classify(fixture=clear_jev())
        self.assertEqual(r["verdict"], "review")

    def test_injection_is_risky(self):
        fx = clear_jev()
        fx["raw"]["answers"]["addressed_to_reviewer"]["noul"] = 0.97
        r = self.b.classify(fixture=fx)
        self.assertEqual(r["verdict"], "risky")
        self.assertTrue(any("prompt injection" in s["reason"] for s in r["signals"]))

    def test_fence_sitting_is_uncertain(self):
        self.b.edit("meta.json", lambda m: {**m, "title": "fix: x"})
        fx = clear_jev()
        fx["raw"]["answers"]["storage_change"]["noul"] = 0.5
        r = self.b.classify(fixture=fx)
        self.assertEqual(r["verdict"], "review")
        self.assertTrue(r["uncertain"])

    def test_inert_only_shortcut(self):
        self.b.edit("files.json", lambda f: [{"status": "M", "path": "README.md", "additions": 1, "deletions": 0}])
        self.b.edit("konflate.json", lambda k: {"state": "skipped", "summary": {}})
        (self.b.dir / "konflate_diff.json").unlink()
        self.b.edit("meta.json", lambda m: {**m, "title": "docs: typo"})
        self.assertEqual(self.b.classify(key=None)["verdict"], "safe")

    def test_comment_golden(self):
        r = self.b.classify(fixture=load("jev_179.json"))
        md = p.render_comment(r)
        self.assertTrue(md.startswith(p.COMMENT_MARKER))
        self.assertIn("PR risk: **review** · uncertain", md)
        self.assertIn("| pr | 🟡 Major update", md)
        self.assertIn("kind **version_bump** · jev-1.13.0", md)
        self.assertIn("/#/pr/179", md)


class FakeGitHub(p.GitHub):
    def __init__(self, labels, comments):
        self.labels, self.comments, self.calls = labels, comments, []

    def req(self, method, path, data=None):
        self.calls.append((method, path.split("?")[0]))
        if method == "GET" and path.endswith("/labels?per_page=100"):
            return [{"name": n} for n in self.labels]
        if method == "GET":
            return self.comments
        return {}


class TestPublish(unittest.TestCase):
    def test_labels_idempotent(self):
        gh = FakeGitHub(["risk/review", "area/kubernetes"], [])
        self.assertEqual(p.sync_labels(gh, 1, ["risk/review"]), [])
        self.assertEqual([c for c in gh.calls if c[0] != "GET"], [])

    def test_labels_swap(self):
        gh = FakeGitHub(["risk/safe", "risk/uncertain", "area/kubernetes"], [])
        self.assertEqual(p.sync_labels(gh, 1, ["risk/risky"]), ["-risk/safe", "-risk/uncertain", "+risk/risky"])
        self.assertIn(("DELETE", "/issues/1/labels/risk%2Fsafe"), gh.calls)

    def test_comment_upsert(self):
        body = p.COMMENT_MARKER + "\nhello"
        mine = {"id": 7, "user": {"login": "github-actions[bot]"}, "body": body}
        konflate = {"id": 8, "user": {"login": "qnimbus-homelab-assistant[bot]"}, "body": "<!-- konflate:pr-1 -->"}
        self.assertEqual(p.upsert_comment(FakeGitHub([], [konflate, mine]), 1, body), "unchanged")
        gh = FakeGitHub([], [konflate, mine])
        self.assertEqual(p.upsert_comment(gh, 1, body + "!"), "updated")
        self.assertIn(("PATCH", "/issues/comments/7"), gh.calls)
        self.assertEqual(p.upsert_comment(FakeGitHub([], [konflate]), 1, body), "created")


if __name__ == "__main__":
    unittest.main()
