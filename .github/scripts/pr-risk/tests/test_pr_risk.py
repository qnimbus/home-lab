"""Offline tests for pr_risk.py's collectors and plumbing: release notes, Konflate polling, model
input budgets, the Jev client and publishing. No network, no git, no API key. The v2 decision
model (findings, evidence, policy) is tested in test_v2.py.

    uv run --no-project --python 3.13 -m unittest discover .github/scripts/pr-risk/tests
"""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent))

import pr_risk as p  # noqa: E402
import surfaces  # noqa: E402


def load(name):
    return json.loads((FIX / name).read_text())


# The shape of a Renovate PR body with release notes (from #178), `{notes}` filled per test.
RENOVATE_BODY = """This PR contains the following updates:

| Package | Update | Change |
|---|---|---|
| foo | minor | `v0.8.2` → `v0.9.0` |

---

### Release Notes

<details>
<summary>foo/foo (ghcr.io/foo/foo)</summary>

### [`v0.9.0`](https://example.invalid/v0.9.0)

{notes}

</details>

---

### Configuration

🚦 **Automerge**: Disabled by config. Please merge this manually once you are satisfied.

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box
"""


def crd(rows):
    return {"diff": {"resources": [{"kind": "CustomResourceDefinition", "title": "CustomResourceDefinition x.example.io",
                                    "unified": [{"kind": k, "html": h} for k, h in rows]}]}}  # fmt: skip


class TestReleaseNotesAndConfig(unittest.TestCase):
    def test_release_notes_extracted(self):
        body = RENOVATE_BODY.format(notes="- BREAKING: dropped `foo.bar`")
        notes = p.release_notes(body, "renovate")
        self.assertTrue(notes.startswith("foo/foo (ghcr.io/foo/foo)"))
        self.assertIn("dropped `foo.bar`", notes)
        self.assertNotIn("Configuration", notes)
        self.assertNotIn("<details>", notes)
        desc = p.clean_description(body, "renovate")
        self.assertIn("`v0.8.2` → `v0.9.0`", desc)
        self.assertNotIn("BREAKING", desc)  # notes go to their own field
        self.assertEqual(p.release_notes(body, "owner"), "")
        self.assertEqual(p.release_notes(load("bundle_179/meta.json")["body"], "renovate"), "")

    def test_raw_state_carries_notes_and_config_only_with_notes(self):
        meta = {"title": "t", "body": "", "author_kind": "renovate"}
        conf = {"kubernetes/apps/a/b/app/helmrelease.yaml": "values: {}\n"}
        state, _ = p.raw_state(meta, [], "", "", [{"version": "v1", "text": "notes"}], conf)
        self.assertEqual(state["release_notes"], "notes")
        self.assertIn("# kubernetes/apps/a/b/app/helmrelease.yaml", state["config"])
        state, _ = p.raw_state(meta, [], "", "", [], conf)
        self.assertNotIn("config", state)
        state, _ = p.raw_state(meta, [], "", "", [], conf, invariants=True)  # setting_conflict needs both
        self.assertIn("invariants", state)
        self.assertIn("# kubernetes/apps/a/b/app/helmrelease.yaml", state["config"])

    def test_config_paths(self):
        files = [
            {"status": "M", "path": "kubernetes/apps/observability/smartctl-exporter/app/ocirepository.yaml"},
            {"status": "M", "path": "kubernetes/components/postgres/cluster.yaml"},
            {"status": "M", "path": "docker/nas/00-exporters/docker-compose.yaml"},
            {"status": "D", "path": "kubernetes/apps/media/gone/app/helmrelease.yaml"},
            {"status": "M", "path": "kubernetes/apps/media/README.md"},
            {"status": "M", "path": ".github/workflows/validate.yaml"},
            {"status": "M", "path": ".github/actions/setup-mise/action.yaml"},
            {"status": "M", "path": ".github/scripts/pr-risk/pr_risk.py"},
        ]
        self.assertEqual(p.config_paths(files), [
            "kubernetes/apps/observability/smartctl-exporter/app/helmrelease.yaml",
            "kubernetes/components/postgres/cluster.yaml",
            "docker/nas/00-exporters/docker-compose.yaml",
            ".github/workflows/validate.yaml",
            ".github/actions/setup-mise/action.yaml",
        ])  # fmt: skip

    def test_workflow_config_214(self):
        """#214: a setup-node major bump was collected with `config.json` = {}, so nothing could
        say whether its breaking changes (automatic caching, npm auth) touch this repo. The
        config of an action is its step's inputs, plus what it reads from the repository root."""
        workflow = "      - uses: actions/setup-node@8207627 # v7.0.0\n        with:\n          node-version: \"24\"\n"

        def fake_git(*args, check=True):
            if args[0] == "ls-tree":
                return mock.Mock(returncode=0, stdout=".github\n.mise\nREADME.md\nkubernetes\n")
            known = args[1].endswith(":.github/workflows/validate.yaml")
            return mock.Mock(returncode=0 if known else 128, stdout=workflow if known else "")

        with mock.patch.object(p, "git", side_effect=fake_git):
            config = p.collect_config([{"status": "M", "path": ".github/workflows/validate.yaml"}], "HEAD")
            other = p.collect_config([{"status": "M", "path": "kubernetes/components/postgres/cluster.yaml"}], "HEAD")
        self.assertEqual(config, {".github/workflows/validate.yaml": workflow, p.ROOT_LISTING: ".github\n.mise\nREADME.md\nkubernetes\n"})
        self.assertNotIn(p.ROOT_LISTING, other)  # only an action reads the repository root
        self.assertEqual(next(iter(config)), p.ROOT_LISTING)  # first, so the size budget never drops it
        self.assertTrue(p.config_fits(config, 10_000, 5_000))
        self.assertFalse(p.config_fits({"a": "x" * 5_001}, 10_000, 5_000))  # cut
        self.assertFalse(p.config_fits({"a": "x" * 4_000, "b": "x" * 4_000, "c": "x" * 4_000}, 10_000, 5_000))  # one left out

    def test_generator_files_197(self):
        """#197: configarr's config is `resources/config.yml`, fed in by a configMapGenerator, so
        Jev judged whether "config uses" a Prowlarr setting without it."""
        root = HERE.parent.parent.parent.parent
        d = "kubernetes/apps/downloads/configarr/app"
        self.assertEqual(p.generator_files((root / d / "kustomization.yaml").read_text(), d), [f"{d}/resources/config.yml"])
        kus = ("resources:\n  - ./helmrelease.yaml\nconfigMapGenerator:\n  - name: a-values\n    files:\n      - values.yaml=./helm/values.yaml\n"
               "  - files:\n      - config.yaml=./resources/config.yaml\n    name: b\nsecretGenerator:\n  - name: s\n    files:\n      - ./x.env\n"
               "generatorOptions:\n  disableNameSuffixHash: true\n")  # fmt: skip
        self.assertEqual(p.generator_files(kus, "k/a/app"), ["k/a/app/helm/values.yaml", "k/a/app/resources/config.yaml", "k/a/app/x.env"])

        shown = {}

        def fake_git(*args, check=True):
            path = args[1].split(":", 1)[1]
            f = root / path
            shown[path] = f.exists()
            return mock.Mock(returncode=0 if f.exists() else 128, stdout=f.read_text() if f.exists() else "")

        with mock.patch.object(p, "git", side_effect=fake_git):
            config = p.collect_config([{"status": "M", "path": f"{d}/helmrelease.yaml"}], "HEAD")
        self.assertEqual(list(config), [f"{d}/helmrelease.yaml", f"{d}/resources/config.yml"])

    def test_may_break(self):
        self.assertEqual(p.may_break({"labels": ["type/major"], "title": "x"}), "Major update")
        self.assertIn("0.x", p.may_break({"labels": ["type/minor"], "title": "feat(container)!: x", "author_kind": "renovate"}))
        self.assertIn("breaking", p.may_break({"labels": [], "title": "feat(ci)!: x", "author_kind": "owner"}))
        self.assertIsNone(p.may_break({"labels": ["type/minor"], "title": "feat(container): x", "author_kind": "renovate"}))


# Real shapes from 2026-09-28's open PRs: #171's table row, #170's pointer-only notes.
ROW_171 = ("| [ghcr.io/piraeusdatastore/helm-charts/snapshot-controller](https://redirect.github.com/piraeusdatastore/helm-charts) "
           "([source](https://redirect.github.com/kubernetes-csi/external-snapshotter)) | minor | `5.1.1` → `5.3.0` |")  # fmt: skip
POINTER_NOTES = "\n\n".join(
    f"### [`v{v}`](https://redirect.github.com/tailscale/tailscale/releases/tag/v{v})\n\n"
    f"[Compare Source](https://redirect.github.com/tailscale/tailscale/compare/x...v{v})\n\n"
    "Please refer to the changelog available at <https://tailscale.com/changelog>"
    for v in ("1.102.4", "1.102.3", "1.98.9")
)


def rel(tag, body=None, **kw):
    return {"tag_name": tag, "body": body or f"- feat: the change shipped in {tag}", **kw}


def one_page(*releases):
    """A fake github_pages: every repo has these releases, on one page."""
    return lambda path: [list(releases)]


def renovate_meta(row, notes=None):
    body = "| Package | Update | Change |\n|---|---|---|\n" + row + "\n"
    if notes is not None:
        body += "\n---\n\n### Release Notes\n\n<details>\n<summary>x</summary>\n\n" + notes + "\n\n</details>\n"
    return {"author_kind": "renovate", "body": body + "\n---\n\n### Configuration\n\nstuff\n"}


class TestReleaseNoteSources(unittest.TestCase):
    def test_sections_oldest_first(self):
        sections = p.note_sections(p.release_notes(RENOVATE_BODY.format(notes="x") + "", "renovate") + "\n\n### [`v0.8.5`](u)\n\n- fix: older one here")
        self.assertEqual([s["version"] for s in sections], ["v0.8.5", "v0.9.0"])
        self.assertFalse(p.note_sections("## Breaking changes\n\ntext"))  # a heading needs a version

    def test_pointer_only_notes_are_not_notes(self):
        sections = p.note_sections(POINTER_NOTES)
        self.assertEqual(len(sections), 3)
        self.assertFalse(any(p.substantive(s["text"]) for s in sections))
        self.assertTrue(p.substantive("### v1\n\n- Drop support for `foo.bar`"))
        row = "| [ghcr.io/home-operations/charts-mirror/tailscale-operator](https://redirect.github.com/tailscale/tailscale) | minor | `1.98.4` → `1.102.4` |"
        notes = p.gather_release_notes(renovate_meta(row, POINTER_NOTES), get=one_page(rel("v1.102.4")))
        self.assertEqual(notes["source"], "none")  # a chart can't use the app's bare tags either
        self.assertIn("app's releases, not the chart's", notes["reason"])
        img = "| [ghcr.io/tailscale/tailscale](https://redirect.github.com/tailscale/tailscale) | minor | `v1.98.4` → `v1.102.4` |"
        notes = p.gather_release_notes(renovate_meta(img, POINTER_NOTES), get=one_page())
        self.assertIn("only point elsewhere", notes["reason"])

    def test_renovate_table(self):
        (u,) = p.renovate_updates(ROW_171)
        self.assertEqual(u["repos"], ["piraeusdatastore/helm-charts", "kubernetes-csi/external-snapshotter"])
        self.assertEqual((u["from"], u["to"], u["type"]), ("5.1.1", "5.3.0", "minor"))

    def test_monorepo_prefix_and_range(self):
        releases = [rel("cloudnative-pg-v0.29.1"), rel("plugin-barman-cloud-v0.8.0"), rel("cloudnative-pg-v0.29.0"),
                    rel("cloudnative-pg-v0.28.3"), rel("cloudnative-pg-v0.28.2"), rel("cloudnative-pg-v0.30.0-rc1", prerelease=True)]  # fmt: skip
        row = ("| [ghcr.io/cloudnative-pg/charts/cloudnative-pg](https://cloudnative-pg.io) "
               "([source](https://redirect.github.com/cloudnative-pg/charts)) | minor | `0.28.2` → `0.29.1` |")  # fmt: skip
        notes = p.gather_release_notes(renovate_meta(row), get=one_page(*releases))
        self.assertEqual(notes["source"], "github")
        self.assertFalse(notes["partial"])  # saw 0.28.2, so the range is complete
        self.assertEqual([s["version"] for s in notes["sections"]], ["cloudnative-pg-v0.28.3", "cloudnative-pg-v0.29.0", "cloudnative-pg-v0.29.1"])

    def test_chart_ignores_app_tags(self):
        row = ("| [ghcr.io/cloudnative-pg/charts/plugin-barman-cloud](https://cloudnative-pg.io) "
               "([source](https://redirect.github.com/cloudnative-pg/plugin-barman-cloud)) | minor | `0.7.0` → `0.8.0` |")  # fmt: skip
        notes = p.gather_release_notes(renovate_meta(row), get=one_page(rel("v0.8.0"), rel("v0.7.1")))
        self.assertEqual(notes["source"], "none")

    def test_renovate_notes_for_the_app_are_dropped_for_a_chart(self):
        # #177: Renovate gave chart 0.7.0 → 0.8.0 the app's v0.8.0 notes (2025, unrelated breaking change)
        row = ("| [ghcr.io/cloudnative-pg/charts/plugin-barman-cloud](https://cloudnative-pg.io) "
               "([source](https://redirect.github.com/cloudnative-pg/plugin-barman-cloud)) | minor | `0.7.0` → `0.8.0` |")  # fmt: skip
        app_notes = ("### [`v0.8.0`](https://redirect.github.com/cloudnative-pg/plugin-barman-cloud/blob/HEAD/CHANGELOG.md#080-2025-10-27)\n\n"
                     "##### ⚠ BREAKING CHANGES\n\n- **rbac:** Resource names have been prefixed to avoid cluster conflicts.")  # fmt: skip
        chart = [rel("plugin-barman-cloud-v0.8.0"), rel("plugin-barman-cloud-v0.7.1"), rel("cloudnative-pg-v0.29.1"), rel("plugin-barman-cloud-v0.7.0")]
        notes = p.gather_release_notes(renovate_meta(row, app_notes), get=lambda path: [chart] if path == "/repos/cloudnative-pg/charts/releases" else [])
        self.assertEqual(notes["source"], "github")
        self.assertEqual([s["version"] for s in notes["sections"]], ["plugin-barman-cloud-v0.7.1", "plugin-barman-cloud-v0.8.0"])
        self.assertIn("app's releases, not the chart's", notes["reason"])

    def test_trusted_section(self):
        chart = p.renovate_updates(ROW_171)
        image = [{"package": "ghcr.io/foo/bar", "repos": [], "type": "minor", "from": "1", "to": "2"}]
        tag = {"version": "5.3.0", "text": "### [`5.3.0`](https://redirect.github.com/o/r/releases/tag/snapshot-controller-5.3.0)"}
        changelog = {"version": "v0.8.0", "text": "### [`v0.8.0`](https://redirect.github.com/o/r/blob/HEAD/CHANGELOG.md#080)"}
        self.assertTrue(p.trusted_section(tag, chart))
        self.assertFalse(p.trusted_section(changelog, chart))
        self.assertTrue(p.trusted_section(changelog, image))
        self.assertTrue(p.trusted_section(changelog, []))  # no table: nothing to judge by

    def test_candidate_repos_guess_chart_monorepos(self):
        (u,) = p.renovate_updates("| [ghcr.io/prometheus-community/charts/prometheus-smartctl-exporter](https://redirect.github.com/"
                                  "prometheus-community/smartctl_exporter) | minor | `0.16.1` → `0.17.1` |")  # fmt: skip
        self.assertEqual(p.candidate_repos(u), ["prometheus-community/smartctl_exporter", "prometheus-community/helm-charts", "prometheus-community/charts",
                                                "prometheus-community/helm"])  # fmt: skip

    def test_chart_released_from_the_orgs_helm_repo(self):
        (u,) = p.renovate_updates("| [ghcr.io/coredns/charts/coredns](https://coredns.io) ([source](https://redirect.github.com/"
                                  "coredns/coredns)) | patch | `1.48.1` → `1.48.2` |")  # fmt: skip
        releases = {"/repos/coredns/helm/releases": [[{"tag_name": "coredns-1.48.2", "body": "feat: add optional autoscaler replicas"},
                                                      {"tag_name": "coredns-1.48.1", "body": "Bump to CoreDNS 1.14.7"}]]}  # fmt: skip
        sections, reason, partial = p.github_release_sections(u, get=lambda path: releases.get(path, []))
        self.assertEqual([s["version"] for s in sections], ["coredns-1.48.2"])
        self.assertEqual(reason, "GitHub releases of coredns/helm")

    def test_unlinked_package_is_its_own_repo_when_listed(self):
        (u,) = p.renovate_updates("| Package | Update | Change |\n|---|---|---|\n| siderolabs/talos | patch | `v1.14.1` → `v1.14.2` |")
        self.assertEqual((u["package"], u["repos"], u["to"]), ("siderolabs/talos", [], "v1.14.2"))
        self.assertEqual(p.candidate_repos(u), ["siderolabs/talos"])
        releases = {"/repos/siderolabs/talos/releases": [[{"tag_name": "v1.14.2", "body": "Fixes a kubelet restart loop on upgrade"},
                                                          {"tag_name": "v1.14.1", "body": "older"}]]}  # fmt: skip
        sections, reason, partial = p.github_release_sections(u, get=lambda path: releases.get(path, []))
        self.assertEqual(([s["version"] for s in sections], reason), (["v1.14.2"], "GitHub releases of siderolabs/talos"))
        # a Docker Hub image is named like a repo, but its namespace is not a GitHub owner
        (u,) = p.renovate_updates("| traefik/whoami | patch | `v1.11.0` → `v1.11.1` |")
        self.assertEqual(p.candidate_repos(u), [])
        notes = p.gather_release_notes(renovate_meta("| traefik/whoami | patch | `v1.11.0` → `v1.11.1` |"), get=lambda path: self.fail("looked up"))
        self.assertEqual((notes["source"], notes["unlisted"]), ("none", ["traefik/whoami"]))
        self.assertIn("not in REPO_PACKAGES", notes["reason"])
        # a registry path is not a repo: only the org's chart repos are guessed
        (u,) = p.renovate_updates("| ghcr.io/home-operations/charts-mirror/ceph-csi-drivers | minor | `1.0.5` → `1.1.0` |")
        self.assertEqual(p.candidate_repos(u), ["home-operations/helm-charts", "home-operations/charts", "home-operations/helm"])

    def test_paging_stops_once_from_is_reached(self):
        seen = []

        def get(path):
            for page in ([rel("x-1.3.0"), rel("other-9.0.0")], [rel("x-1.2.0"), rel("x-1.1.0")], [rel("x-1.0.0")]):
                seen.append(page)
                yield page

        u = {"package": "ghcr.io/o/charts/x", "repos": ["o/helm-charts"], "type": "minor", "from": "1.1.0", "to": "1.3.0"}
        sections, reason, partial = p.github_release_sections(u, get)
        self.assertEqual([s["version"] for s in sections], ["x-1.2.0", "x-1.3.0"])
        self.assertEqual(len(seen), 2)
        u["from"] = "0.9.0"  # older than every page: the range may be incomplete, and says so
        seen.clear()
        self.assertFalse(partial)  # 1.1.0 was seen: the range is complete
        _, reason, partial = p.github_release_sections(u, get)
        self.assertIn("back to x-1.0.0 only", reason)
        self.assertTrue(partial)

    def test_image_uses_bare_tags(self):
        row = "| [ghcr.io/kashalls/external-dns-unifi-webhook](https://redirect.github.com/kashalls/external-dns-unifi-webhook) | minor | `v0.8.2` → `v0.9.0` |"
        notes = p.gather_release_notes(renovate_meta(row), get=one_page(rel("v0.9.0"), rel("v0.8.3"), rel("v0.8.2")))
        self.assertEqual([s["version"] for s in notes["sections"]], ["v0.8.3", "v0.9.0"])

    # #176: chart 0.28.2 → 0.29.1 with CI-chore notes, while the render moved the operator 1.29.1 → 1.30.1.
    ROW_176 = ("| [ghcr.io/cloudnative-pg/charts/cloudnative-pg](https://redirect.github.com/cloudnative-pg/charts) | minor | `0.28.2` → `0.29.1` |")
    NOTES_176 = "### [`v0.29.1`](https://redirect.github.com/cloudnative-pg/charts/releases/tag/cloudnative-pg-v0.29.1)\n\n- ci: add cert manager to renovate"
    IMAGE_176 = {"name": "ghcr.io/cloudnative-pg/cloudnative-pg", "from": "1.29.1", "to": "1.30.1", "refs": ["Deployment database/cloudnative-pg"]}

    def test_image_a_chart_deploys_gets_its_own_notes(self):
        asked = []

        def get(path):
            asked.append(path)
            return [[rel("v1.30.1"), rel("v1.29.3"), rel("v1.30.0"), rel("v1.29.2"), rel("v1.29.1")]]

        notes = p.gather_release_notes(renovate_meta(self.ROW_176, self.NOTES_176), get=get, images=[self.IMAGE_176])
        self.assertEqual(asked, ["/repos/cloudnative-pg/cloudnative-pg/releases"])  # the chart's notes came from Renovate
        self.assertEqual(notes["source"], "renovate")
        # the chart's notes, then the image's: the new line only, not the old line's later patches
        self.assertEqual([s["version"] for s in notes["sections"]], ["v0.29.1", "cloudnative-pg v1.30.0", "cloudnative-pg v1.30.1"])
        self.assertTrue(notes["sections"][1]["text"].startswith("### cloudnative-pg v1.30.0"))
        self.assertEqual([(i["name"], i["covered"]) for i in notes["images"]], [(self.IMAGE_176["name"], True)])
        self.assertIn("image cloudnative-pg 1.29.1 → 1.30.1: GitHub releases of cloudnative-pg/cloudnative-pg", notes["reason"])

    def test_image_notes_that_cannot_be_found_are_not_covered(self):
        meta = renovate_meta(self.ROW_176, self.NOTES_176)
        notes = p.gather_release_notes(meta, get=one_page(rel("v1.29.1")), images=[self.IMAGE_176])
        self.assertEqual([s["version"] for s in notes["sections"]], ["v0.29.1"])
        self.assertFalse(notes["images"][0]["covered"])
        # the range doesn't reach back to the running version: found, but not covered
        notes = p.gather_release_notes(meta, get=one_page(rel("v1.30.1"), rel("v1.30.0")), images=[self.IMAGE_176])
        self.assertEqual(len(notes["sections"]), 3)
        self.assertFalse(notes["images"][0]["covered"])
        # a registry whose namespace isn't a GitHub owner is listed, never guessed
        quay = {"name": "quay.io/jetstack/cert-manager-controller", "from": "v1.18.0", "to": "v1.19.0", "refs": []}
        notes = p.gather_release_notes(meta, get=lambda path: self.fail("looked up"), images=[quay])
        self.assertIn("IMAGE_REPOS", notes["images"][0]["reason"])
        self.assertFalse(notes["images"][0]["covered"])

    def test_build_variant_is_not_part_of_the_version(self):
        meta = renovate_meta(self.ROW_176, self.NOTES_176)
        get = one_page(rel("v3.15.0"), rel("v3.14.1"), rel("v3.14.0"))
        for old, new in (("v3.14.0-distroless", "v3.15.0-distroless"), ("distroless-v3.14.0", "distroless-v3.15.0@sha256:abc")):
            notes = p.gather_release_notes(meta, get=get, images=[{"name": "quay.io/prometheus/prometheus", "from": old, "to": new}])
            self.assertEqual([s["version"] for s in notes["sections"]], ["v0.29.1", "prometheus v3.15.0"], old)
            self.assertEqual([(i["from"], i["to"], i["covered"]) for i in notes["images"]], [("v3.14.0", "v3.15.0", True)])

    def test_images_the_notes_already_cover_are_not_looked_up(self):
        get = lambda path: self.fail("looked up")  # noqa: E731
        meta = renovate_meta(self.ROW_176, self.NOTES_176)
        for img in (
            {"name": "ghcr.io/cloudnative-pg/cloudnative-pg", "from": "1.30.0", "to": "1.30.1"},  # a patch
            {"name": "ghcr.io/cloudnative-pg/cloudnative-pg", "from": "v0.28.2", "to": "v0.29.1"},  # the chart's number line: released together
            {"name": "ghcr.io/cloudnative-pg/charts/cloudnative-pg", "from": "0.28.2", "to": "0.29.1"},  # the updated package itself
            {"name": "docker.io/library/postgres", "from": "17.4-alpine", "to": "18.0-alpine"},  # not a plain version
            {"name": "ghcr.io/x/y", "from": None, "to": "1.2.0"},  # new
            {"name": "registry.k8s.io/sig-storage/csi-provisioner", "from": "v6.2.0", "to": "v6.3.0"},  # IMAGE_IGNORE: a CSI sidecar
        ):
            self.assertNotIn("images", p.gather_release_notes(meta, get=get, images=[img]), img)
        self.assertNotIn("images", p.gather_release_notes(meta, get=get))  # a bundle collected without a render
        owner = {"author_kind": "owner", "body": meta["body"]}
        self.assertEqual(p.gather_release_notes(owner, get=get, images=[self.IMAGE_176])["source"], "none")

    def test_repeated_boilerplate_is_not_a_changelog(self):
        body = "Deploys a Snapshot Controller in a cluster. Snapshot Controllers are often bundled with the distribution."
        releases = [rel("snapshot-controller-5.3.0", body), rel("snapshot-controller-5.2.0", body), rel("snapshot-controller-5.1.1", body)]
        notes = p.gather_release_notes(renovate_meta(ROW_171), get=one_page(*releases))
        self.assertEqual(notes["source"], "none")
        self.assertIn("repeat one text", notes["reason"])

    def test_next_repo_when_target_release_missing(self):
        calls = []

        def get(path):
            calls.append(path)
            return [[rel("snapshot-controller-5.3.0", "- feat: add groupsnapshot conversion webhook"),
                     rel("snapshot-controller-5.2.0", "- fix: tolerate missing CRDs on startup")]] if "external-snapshotter" in path else []  # fmt: skip

        notes = p.gather_release_notes(renovate_meta(ROW_171), get=get)
        self.assertEqual(calls, ["/repos/piraeusdatastore/helm-charts/releases", "/repos/kubernetes-csi/external-snapshotter/releases"])
        self.assertEqual(notes["source"], "github")

    def test_renovate_notes_win_when_substantive(self):
        tagged = "### [`5.3.0`](https://redirect.github.com/piraeusdatastore/helm-charts/releases/tag/snapshot-controller-5.3.0)\n\n- feat: something real"
        notes = p.gather_release_notes(renovate_meta(ROW_171, tagged), get=lambda path: self.fail("fetched"))
        self.assertEqual(notes["source"], "renovate")

    def test_budget_keeps_oldest(self):
        sections = [{"version": f"v1.{i}", "text": f"### v1.{i}\n" + "x" * 90} for i in range(5)]
        text, cut = p.budget_notes(sections, 300, 6_000)
        self.assertTrue(cut)
        self.assertIn("### v1.0", text)
        self.assertNotIn("### v1.4", text)
        self.assertIn("newer versions left out for size: v1.3, v1.4", text)


class TestCrds(unittest.TestCase):
    def test_new_fields_are_not_a_version_change(self):
        self.assertEqual(p.crd_version_changes(crd([("add", "        newField:"), ("ctx", "    served: true")])), [])

    def test_dropped_or_moved_versions_are(self):
        for rows in ([("del", "    served: true")], [("del", "    storage: true")], [("add", "    served: false")]):
            self.assertEqual(p.crd_version_changes(crd(rows)), ["CustomResourceDefinition x.example.io"], rows)

    def test_per_resource_cap_only_when_over_budget(self):
        big = crd([("add", "    field%d: x" % i) for i in range(400)])
        self.assertFalse(p.budget_rendered(big, 60_000, 1_000)[1])
        self.assertTrue(p.budget_rendered(big, 5_000, 1_000)[1])

    def test_descriptions_left_out_of_model_input(self):
        text = p.render_resource(crd([
            ("ctx", "            spec:"),
            ("del", "              description: |-"),
            ("del", "                Old words."),
            ("add", "              description: New words"),
            ("add", "              type: string"),
        ])["diff"]["resources"][0], 8_000)  # fmt: skip
        self.assertNotIn("words", text)
        self.assertIn("+              type: string", text)
        self.assertIn("(3 description lines left out)", text)
        self.assertNotIn("only description text changed", text)

    # #177 (plugin-barman-cloud 0.7.0 → 0.8.0): a longer description, nothing else. Jev saw an
    # empty "changed" CRD and answered crd_schema_change 0.41, which alone made the PR uncertain.
    DESCRIPTION_ONLY = [
        ("ctx", "                                key:"),
        ("del", "                                  description: The key to select."),
        ("add", "                                  description: |-"),
        ("add", "                                    The key to select from the ConfigMap's Data field."),
        ("add", ""),
        ("add", "                                    Keys in the BinaryData field are not currently propagated."),
        ("ctx", "                                  type: string"),
    ]

    def test_description_only_crd_says_so(self):
        r = crd(self.DESCRIPTION_ONLY)
        self.assertFalse(p.crd_schema_changed(r["diff"]["resources"][0]))  # the blank line stays in the block
        text = p.render_resource(r["diff"]["resources"][0], 8_000)
        self.assertIn("(only description text changed; the schema itself is unchanged)", text)
        self.assertNotIn("\n+", text)

    def test_description_only_crd_is_not_asked_about(self):
        self.assertFalse(p.any_crd_schema_change(crd(self.DESCRIPTION_ONLY)))
        self.assertTrue(p.any_crd_schema_change(crd(self.DESCRIPTION_ONLY + [("add", "                                  pattern: ^x$")])))


class TestGlobsAndSurfaces(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(p.matches("kubernetes/apps/media/plex/app/helmrelease.yaml", ["kubernetes/apps/**"]))
        self.assertTrue(p.matches("README.md", ["**/*.md"]))
        self.assertTrue(p.matches("a/b/README.md", ["**/*.md"]))
        self.assertFalse(p.matches("kubernetes/apps/media/plex/ks.yaml", ["kubernetes/apps/*/kustomization.yaml"]))
        self.assertTrue(p.matches("kubernetes/apps/system/openebs/ks.yaml", ["kubernetes/apps/system/{openebs,kopiur}/**"]))
        self.assertFalse(p.matches("kubernetes/apps/system/openebs-x/ks.yaml", ["kubernetes/apps/system/{openebs,kopiur}/**"]))

    def test_surfaces(self):
        """(surface id, reach). Reach is context: how far a real finding would propagate."""
        cases = {
            "kubernetes/talos/version.yaml": ("talos", "host"),
            "kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml": ("rook-ceph/rook-ceph", "cluster"),
            "kubernetes/apps/rook-ceph/README.md": ("docs", "none"),  # docs win over location
            "kubernetes/components/postgres/cluster.yaml": ("component:postgres", "shared"),
            "kubernetes/apps/media/kustomization.yaml": ("namespace:media", "shared"),
            "docker/nas/00-exporters/docker-compose.yaml": ("nas:00-exporters", "app"),
            ".github/workflows/validate.yaml": ("ci:workflows", "ci"),
            ".github/workflows/pr-risk.yaml": ("pr-risk", "ci"),
            ".github/labels.yaml": ("docs", "none"),
            ".mise/config.toml": ("workstation:hooks", "workstation"),  # not inert: mise runs hooks
            ".lefthook.yaml": ("workstation:hooks", "workstation"),
            ".justfile": ("workstation:tooling", "workstation"),
            ".agents/skills/add-app/SKILL.md": ("agents", "workstation"),  # agent instructions aren't plain docs
            "kubernetes/apps/media/plex/app/helmrelease.yaml": ("media/plex", "app"),
            "kubernetes/apps/kube-system/cilium/app/helmrelease.yaml": ("kube-system/cilium", "cluster"),
            "kubernetes/apps/database/cloudnative-pg/app/helmrelease.yaml": ("database/cloudnative-pg", "shared"),
            "kubernetes/clusters/main/apps.yaml": ("flux:cluster", "cluster"),
            "some/new/thing.py": ("repo", "workstation"),
        }
        for path, (sid, reach) in cases.items():
            sd, got = surfaces.classify_path(path)
            self.assertEqual((got, sd.reach), (sid, reach), path)

    def test_content_adds_stakes(self):
        files = [{"status": "M", "path": "kubernetes/apps/media/plex/app/helmrelease.yaml"}]
        (plain,) = surfaces.build_surfaces(files, {})
        (held,) = surfaces.build_surfaces(files, {"media/plex": "persistence:\n  config:\n    existingClaim: plex"})
        self.assertNotIn("data", plain.stakes)
        self.assertIn("data", held.stakes)


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


class TestCollectChecks(unittest.TestCase):
    HEAD = "19d5bacfd0268bf3164862a1946532cfb9c87186"
    FILES = [{"status": "M", "path": ".github/workflows/validate.yaml"}]

    def run_checks(self, pages, jobs=None, files=None, wait=60):
        clock, pages, asked = {"t": 0.0}, iter(pages), []

        def get(path):
            asked.append(path)
            return jobs if "/jobs" in path else next(pages)

        out = p.collect_checks(self.FILES if files is None else files, "o/r", self.HEAD, wait, get=get,
                               sleep=lambda s: clock.__setitem__("t", clock["t"] + s), now=lambda: clock["t"])  # fmt: skip
        return out, asked

    def run_of(self, status="completed", conclusion="success", path=".github/workflows/validate.yaml", **kw):
        return {"id": 7, "path": path, "head_sha": self.HEAD, "status": status, "conclusion": conclusion, "html_url": "https://x/7", **kw}

    def jobs(self, *steps, job="success"):
        return {"total_count": 1, "jobs": [{"name": "validate", "conclusion": job, "steps": [{"name": n, "conclusion": c} for n, c in steps]}]}

    def test_waits_for_the_run_then_reads_its_steps(self):
        pages = [{"workflow_runs": [self.run_of("in_progress", None)]}, {"workflow_runs": [self.run_of()]}]
        out, asked = self.run_checks(pages, self.jobs(("Setup Node.js", "success"), ("Post Setup Node.js", "success")))
        self.assertEqual(out, [{"path": ".github/workflows/validate.yaml", "run_id": 7, "url": "https://x/7", "status": "completed",
                                "conclusion": "success", "not_run": []}])  # fmt: skip
        self.assertIn(f"head_sha={self.HEAD}&event=pull_request", asked[0])

    def test_skipped_steps_are_named(self):
        out, _ = self.run_checks([{"workflow_runs": [self.run_of()]}], self.jobs(("Setup Node.js", "skipped"), ("Lint", "success")))
        self.assertEqual(out[0]["not_run"], ["validate / Setup Node.js"])

    def test_gives_up_on_a_run_that_stays_in_progress(self):
        out, asked = self.run_checks([{"workflow_runs": [self.run_of("in_progress", None)]}] * 50, wait=30)
        self.assertEqual((out[0]["conclusion"], out[0]["not_run"]), (None, None))
        self.assertFalse(any("/jobs" in a for a in asked))

    def test_only_this_head_and_only_changed_workflows(self):
        runs = [self.run_of(head_sha="0" * 40), self.run_of(path=".github/workflows/labeler.yaml")]
        self.assertEqual(self.run_checks([{"workflow_runs": runs}] * 2)[0], [])
        self.assertEqual(self.run_checks([None] * 50, wait=30)[0], [])  # the API never answered

    def test_no_call_without_a_changed_workflow(self):
        files = [{"status": "M", "path": "kubernetes/apps/default/whoami/app/helmrelease.yaml"},
                 {"status": "M", "path": ".github/actions/setup-mise/action.yaml"},  # a composite action has no run of its own
                 {"status": "M", "path": ".github/workflows/pr-risk.yaml"},  # the classifier's own run is this one
                 {"status": "D", "path": ".github/workflows/gone.yaml"}]  # fmt: skip
        self.assertEqual(self.run_checks([], files=files), ([], []))

    def test_no_wait_when_the_run_cannot_be_used(self):
        """With an app in the PR nothing reads the run (semantic.exercised), and the wait would
        stack on Konflate's 480 s inside a 15-minute job."""
        files = self.FILES + [{"status": "M", "path": "kubernetes/apps/default/whoami/app/helmrelease.yaml"}]
        out, asked = self.run_checks([{"workflow_runs": [self.run_of("in_progress", None)]}] * 50, files=files)
        self.assertEqual((out[0]["status"], len(asked)), ("in_progress", 1))
        docs = self.FILES + [{"status": "M", "path": "README.md"}]  # no model needed for docs: still waits
        out, _ = self.run_checks([{"workflow_runs": [self.run_of("in_progress", None)]}, {"workflow_runs": [self.run_of()]}], self.jobs(), files=docs)
        self.assertEqual(out[0]["not_run"], [])

    def test_failed_poll_and_unlisted_run_are_retried(self):
        done = {"workflow_runs": [self.run_of()]}
        out, _ = self.run_checks([None, None, done], self.jobs())  # GitHub didn't answer: retried until the deadline
        self.assertEqual(out[0]["conclusion"], "success")
        out, _ = self.run_checks([{"workflow_runs": []}, done], self.jobs())  # not listed yet: one more poll
        self.assertEqual(out[0]["conclusion"], "success")
        out, asked = self.run_checks([{"workflow_runs": []}] * 50)  # a push-only workflow: two polls, not the whole wait
        self.assertEqual((out, len(asked)), ([], 2))

    def test_own_run_is_never_waited_for(self):
        with mock.patch.dict(p.os.environ, {"GITHUB_RUN_ID": "7"}):
            out, asked = self.run_checks([{"workflow_runs": [self.run_of("in_progress", None)]}] * 2)
        self.assertEqual((out, len(asked)), ([], 2))  # not listed, as far as it can tell: one more poll, no more


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
