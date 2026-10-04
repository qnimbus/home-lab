#!/usr/bin/env python3
"""Classify a pull request's merge risk: risk/safe, risk/review or risk/risky (+ risk/uncertain).

v2 (pr-risk/v2): reach, stakes and activation describe the change; findings describe what can go
wrong, each with a reason code, a certainty and a consequence; an evidence ledger per surface says
how well it is known; a small deterministic policy turns those into the verdict. Jev (TypeSafe's
System One model) answers narrow semantic questions scoped to what the diff contains. It can add
findings or show evidence is missing, never remove a deterministic finding. See README.md.

Subcommands (standard library only, so the workflow runs it with a bare `uv run`):

  collect   read the PR as git objects (never checks out or executes it) plus Konflate's render
            of it, into a bundle directory
  classify  bundle -> result.json + comment.md (+ Jev calls, or --jev-fixture for offline runs)
  publish   apply labels / the sticky comment, according to PR_RISK_MODE
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy  # noqa: E402
import rules  # noqa: E402
import semantic  # noqa: E402
from rules import INFRA_FAILURE, Facts, may_break, recreated_hook, redact, row_text, scan_secrets  # noqa: E402,F401
from surfaces import build_surfaces, classify_path, surface_id  # noqa: E402
from taxonomy import (  # noqa: E402
    POLICY_VERSION,
    REACH,
    SCHEMA,
    Assessment,
    finding_json,
    glob_re,  # noqa: F401 - re-exported for tests
    matches,
    max_reach,
    worst_reversibility,
)

# ── Tunables ─────────────────────────────────────────────────────────────────────────────────

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL_DEFAULT = "jev-1.13.0"  # pinned: the answer bands in semantic.THRESHOLDS are tuned against one model version
KONFLATE_URL_DEFAULT = "http://konflate.flux-system.svc.cluster.local:8080"
KONFLATE_UI = "https://konflate.cluster.vwn.io"

# Character budgets for Jev state. Jev allows 32k tokens for state + the longest question; at
# ~3.5 chars/token each call stays near 25k tokens.
BUDGET = {
    "description": 4_000,
    "release_notes": 16_000,
    "release_notes_per_version": 6_000,
    "config": 10_000,
    "config_per_file": 5_000,
    "diff": 60_000,  # release notes and config come out of this, so the call stays in budget
    "diff_per_file": 12_000,
    "base_changes": 15_000,
    "rendered": 60_000,
    "rendered_per_resource": 8_000,
    "line": 400,
}
THRESHOLDS = semantic.THRESHOLDS

LEVELS = ["safe", "review", "risky"]
LABELS = {"safe": "risk/safe", "review": "risk/review", "risky": "risk/risky"}
UNCERTAIN_LABEL = "risk/uncertain"
COMMENT_MARKER = "<!-- pr-risk -->"
DROP_FROM_DIFF = ["**/*.lock", ".mise/mise.lock"]  # generated; noise for the model
RENDER_PRIORITY = [
    {"CustomResourceDefinition"},
    {"ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding", "ServiceAccount"},
    {"PersistentVolumeClaim", "PersistentVolume", "StorageClass", "VolumeSnapshot", "VolumeSnapshotClass"},
    {"StatefulSet", "Deployment", "DaemonSet", "CronJob", "Job"},
    {"HTTPRoute", "Gateway", "Service", "NetworkPolicy", "CiliumNetworkPolicy"},
    {"HelmRelease", "Kustomization", "OCIRepository", "GitRepository"},
]


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────


def reach(path: str) -> str:
    return classify_path(path)[0].reach


def rendered_path(path: str) -> bool:
    return classify_path(path)[0].rendered


def log(msg: str) -> None:
    print(f"pr-risk: {msg}", file=sys.stderr)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Diff drivers and textconv come from config/.gitattributes and could run programs: off.
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        errors="replace",
        check=check,
    )


def http_json(url: str, *, data=None, headers=None, timeout=10.0, method=None):
    """Returns (status, headers, parsed body or text). Raises only on transport errors."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status, hdrs = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read(), e.code, dict(e.headers or {})
    text = raw.decode(errors="replace")
    try:
        return status, hdrs, json.loads(text) if text else None
    except json.JSONDecodeError:
        return status, hdrs, text


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


# ── collect ──────────────────────────────────────────────────────────────────────────────────


def parse_name_status(z: str) -> list[dict]:
    parts, files, i = z.split("\0"), [], 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        if status[0] in "RC":
            files.append({"status": status[0], "old_path": parts[i + 1], "path": parts[i + 2]})
            i += 3
        else:
            files.append({"status": status[0], "path": parts[i + 1]})
            i += 2
    return files


def parse_numstat(z: str) -> dict[str, tuple]:
    """path -> (additions, deletions, binary). Renames come as `a\td\t\0old\0new\0`."""
    parts, out, i = z.split("\0"), {}, 0
    while i < len(parts) and parts[i]:
        add, dele, path = parts[i].split("\t", 2)
        if path == "":
            path, i = parts[i + 2], i + 3
        else:
            i += 1
        binary = add == "-"
        out[path] = (0 if binary else int(add), 0 if binary else int(dele), binary)
    return out


def collect_git(base: str, head: str, out: Path) -> dict:
    mb = git("merge-base", base, head).stdout.strip()
    diff_args = ["--no-ext-diff", "--no-textconv", "-M", mb, head]
    files = parse_name_status(git("diff", "-z", "--name-status", *diff_args).stdout)
    numstat = parse_numstat(git("diff", "-z", "--numstat", *diff_args).stdout)
    for f in files:
        add, dele, binary = numstat.get(f["path"], (0, 0, False))
        f.update(additions=add, deletions=dele, binary=binary)
    (out / "files.json").write_text(json.dumps(files, indent=2))

    # Secret-shaped strings are found before anything is cut, then their values leave the bundle:
    # the artifact is downloadable, and the diff goes to Jev.
    diff = git("diff", *diff_args).stdout
    (out / "secrets.json").write_text(json.dumps(scan_secrets(diff)))
    (out / "pr.diff").write_text(redact(diff[:5_000_000]))

    # Rebase/merge risk: files the base branch also changed since the branch point.
    pr_paths = {f["path"] for f in files} | {f["old_path"] for f in files if "old_path" in f}
    base_paths = set(filter(None, git("diff", "-z", "--name-only", mb, base).stdout.split("\0")))
    overlap = sorted(pr_paths & base_paths)
    (out / "overlap.json").write_text(json.dumps(overlap))
    if overlap:
        base_diff = git("diff", "--no-ext-diff", "--no-textconv", mb, base, "--", *overlap).stdout
        (out / "base_overlap.diff").write_text(redact(base_diff[:1_000_000]))

    # Textual conflict, without touching the working tree (git >= 2.38). Exit 1 = conflicts;
    # anything else means the merge result is unknown, which is not the same as a conflict.
    mt = git("merge-tree", "--write-tree", "--name-only", "--no-messages", base, head, check=False)
    conflict = {0: False, 1: True}.get(mt.returncode)
    conflict_files = mt.stdout.splitlines()[1:] if mt.returncode == 1 else []
    (out / "conflict.json").write_text(json.dumps({"conflict": conflict, "files": conflict_files}))

    (out / "config.json").write_text(json.dumps({k: redact(v) for k, v in collect_config(files, head).items()}))
    (out / "components.json").write_text(json.dumps(collect_components(files, mb, head)))

    commits = int(git("rev-list", "--count", f"{mb}..{head}").stdout.strip() or 0)
    return {
        "merge_base": mb,
        "base_sha": git("rev-parse", base).stdout.strip(),
        "head_sha": git("rev-parse", head).stdout.strip(),
        "commits": commits,
    }


WORKFLOW_FILE = re.compile(r"\.github/(workflows|actions)/.+\.ya?ml\Z")
ROOT_LISTING = "(repository root: file names)"


def config_paths(files: list[dict]) -> list[str]:
    """The configuration each changed app runs with, so the model can tell whether a breaking
    change in the release notes touches a setting this repo uses. A Renovate bump changes the
    version in ocirepository.yaml, but the values live in the sibling helmrelease.yaml. An
    action's configuration is its step's `with:` inputs, in the workflow file itself (#214)."""
    out = []
    for f in files:
        path = f["path"]
        if f["status"] == "D" or reach(path) == "none" or not path.endswith((".yaml", ".yml")):
            continue
        if path.startswith("kubernetes/apps/"):
            out.append(path.rsplit("/", 1)[0] + "/helmrelease.yaml")
        if path.startswith(("kubernetes/", "docker/")) and not path.endswith(("ocirepository.yaml", "kustomization.yaml")):
            out.append(path)
        if WORKFLOW_FILE.match(path):
            out.append(path)
    return list(dict.fromkeys(out))


def generator_files(kustomization: str, directory: str) -> list[str]:
    """The files a kustomization.yaml's configMapGenerator/secretGenerator read, as repo paths.
    Much of an app's real config lives there, not in its HelmRelease: configarr's
    `resources/config.yml` (#197), and a dozen apps' `values.yaml=./helm/values.yaml`."""
    out, block, files_indent = [], None, None
    for line in kustomization.splitlines():
        s, indent = line.strip(), len(line) - len(line.lstrip())
        if not s or s.startswith("#"):
            continue
        if indent == 0:
            block = s.rstrip(":") if s in ("configMapGenerator:", "secretGenerator:") else None
            files_indent = None
            continue
        if block is None:
            continue
        if re.match(r"(-\s+)?files:\s*$", s):
            files_indent = indent + (2 if s.startswith("-") else 0)
            continue
        if files_indent is not None and indent > files_indent and s.startswith("- "):
            item = s[2:].strip().strip("\"'")
            out.append(os.path.normpath(os.path.join(directory, item.split("=", 1)[-1])))
        elif files_indent is not None and indent <= files_indent:
            files_indent = None
    return list(dict.fromkeys(out))


def collect_config(files: list[dict], head: str) -> dict[str, str]:
    def show(path):
        r = git("show", f"{head}:{path}", check=False)  # a git object, never checked out
        return r.stdout if r.returncode == 0 else None

    config = {}
    for path in config_paths(files):
        text = show(path)
        if text is not None:
            config[path] = text
    # Files generated into ConfigMaps/Secrets next to each changed app's manifests.
    for directory in dict.fromkeys(p.rsplit("/", 1)[0] for p in config_paths(files) if p.startswith("kubernetes/apps/")):
        kustomization = show(f"{directory}/kustomization.yaml")
        for path in generator_files(kustomization or "", directory):
            if path not in config and (text := show(path)) is not None:
                config[path] = text
    # What an action reads besides its inputs: setup-node only caches when there is a
    # package.json (#214). Names only, from the tree.
    if any(WORKFLOW_FILE.match(path) for path in config):
        tree = git("ls-tree", "--name-only", head, check=False)
        if tree.returncode == 0:
            config = {ROOT_LISTING: tree.stdout, **config}  # first: the size budget cuts from the end
    return config


# ── Workflow runs ────────────────────────────────────────────────────────────────────────────
# A workflow is a pre-merge surface: for a same-repo PR, GitHub has already run the PR's copy of
# a changed workflow on the PR's head. That run is evidence about the change, when it finished
# green and nothing in it was skipped (a skipped job or step may be the one that changed).

WORKFLOW_RUN_FILE = re.compile(r"\.github/workflows/[^/]+\.ya?ml\Z")


def collect_checks(files: list[dict], repo: str, head_sha: str, wait: float, *, get=None, sleep=time.sleep, now=time.monotonic) -> list[dict]:
    """The latest pull_request run, on exactly `head_sha`, of each workflow file the PR changes:
    [{path, run_id, url, status, conclusion, not_run}]. `not_run` lists the jobs and steps that
    didn't succeed (skipped, mostly), or is None when the jobs couldn't be read. Waits up to
    `wait` seconds for runs still in progress; this run itself is never one of them.

    It only waits when the runs can be used (semantic.exercised): workflows are the PR's only
    surface the model is asked about. Otherwise the wait would come on top of Konflate's, for
    evidence nothing reads. A run that isn't listed gets one more poll, not the whole wait: a
    workflow without a pull_request trigger never has one."""
    paths = [f["path"] for f in files if f["status"] != "D" and WORKFLOW_RUN_FILE.match(f["path"]) and surface_id(f["path"]) == "ci:workflows"]
    if not paths or not repo:
        return []
    defs = [classify_path(f["path"])[0] for f in files]
    if any(sd.model_required and sd.id != "ci:workflows" for sd in defs):
        wait = 0.0
    get = get or github_get
    own = os.environ.get("GITHUB_RUN_ID")
    start, delay, polls = now(), 15.0, 0
    while True:
        body = get(f"/repos/{repo}/actions/runs?head_sha={head_sha}&event=pull_request&per_page=100")
        polls += 1
        runs: dict[str, dict] = {}
        for r in (body or {}).get("workflow_runs") or []:  # newest first
            if r.get("path") in paths and r.get("head_sha") == head_sha and str(r.get("id")) != own:
                runs.setdefault(r["path"], r)
        pending = [path for path, r in runs.items() if r.get("status") != "completed"]
        if body is None:
            pending = ["the run list (GitHub didn't answer)"]
        elif not pending and polls == 1:
            pending = [path for path in paths if path not in runs]
        if not pending or now() - start + delay > wait:
            break
        log(f"checks: waiting for {', '.join(pending)}; retrying in {int(delay)}s")
        sleep(delay)
    out = []
    for path, r in runs.items():
        not_run = None
        if r.get("conclusion") == "success":
            jobs = get(f"/repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100") or {}
            listed = jobs.get("jobs")
            if isinstance(listed, list) and len(listed) == jobs.get("total_count"):
                not_run = [j.get("name") for j in listed if j.get("conclusion") != "success"]
                not_run += [f"{j.get('name')} / {s.get('name')}" for j in listed for s in j.get("steps") or [] if s.get("conclusion") != "success"]
        out.append({"path": path, "run_id": r["id"], "url": r.get("html_url"), "status": r.get("status"),
                    "conclusion": r.get("conclusion"), "not_run": not_run})  # fmt: skip
    return out


# ── Component contracts ──────────────────────────────────────────────────────────────────────
# A component (kubernetes/components/<c>) reads `${VAR}`s its consumer's ks.yaml substitutes.
# For every Kustomization that uses a changed component, or whose ks.yaml changed, work out the
# variables the component needs with no default that nothing provides, at base and at head.

VAR_REF = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[=-])?")
SETTINGS_KEY = re.compile(r"^\s{2}([A-Z][A-Z0-9_]*):", re.M)


def required_vars(text: str) -> set[str]:
    return {m.group(1) for m in VAR_REF.finditer(text) if not m.group(2)}


def ks_documents(text: str) -> list[dict]:
    """Per Kustomization document: its name, components, substituted keys, and whether it
    brings its own substituteFrom (then what it provides can't be told from git)."""
    out = []
    for doc in re.split(r"(?m)^---\s*$", text):
        if "kind: Kustomization" not in doc or "kustomize.toolkit.fluxcd.io" not in doc:
            continue
        name = re.search(r"(?m)^  name:\s*(?:&\w+\s+)?(\S+)", doc)
        comps, subs, block = [], set(), None
        for line in doc.splitlines():
            indent = len(line) - len(line.lstrip())
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if block and indent <= block[1]:
                block = None
            if block and block[0] == "components" and s.startswith("- "):
                comps.append(s[2:].strip().strip("\"'"))
            elif block and block[0] == "substitute" and indent == block[1] + 2 and re.match(r"[A-Za-z_][A-Za-z0-9_]*:", s):
                subs.add(s.split(":", 1)[0])
            if s == "components:" or s == "substitute:":
                block = (s[:-1], indent)
        out.append({"name": name.group(1) if name else "?", "components": comps, "substitute": subs, "own_sources": "substituteFrom:" in doc})
    return out


def collect_components(files: list[dict], base: str, head: str) -> list[dict]:
    def show(rev, path):
        r = git("show", f"{rev}:{path}", check=False)
        return r.stdout if r.returncode == 0 else None

    def component_text(rev, cdir):
        r = git("ls-tree", "--name-only", f"{rev}:{cdir}", check=False)
        names = [n for n in r.stdout.splitlines() if n.endswith((".yaml", ".yml"))] if r.returncode == 0 else []
        return "\n".join(show(rev, f"{cdir}/{n}") or "" for n in names) if names else None

    changed_dirs = {f["path"].rsplit("/", 1)[0] for f in files if f["path"].startswith("kubernetes/components/")}
    ks_paths = {f["path"] for f in files if f["path"].endswith("/ks.yaml") and f["path"].startswith("kubernetes/apps/") and f["status"] != "D"}
    for cdir in sorted(changed_dirs):
        r = git("grep", "-l", "-F", cdir.removeprefix("kubernetes/"), head, "--", "kubernetes/apps", check=False)
        ks_paths |= {line.split(":", 1)[1] for line in r.stdout.splitlines() if line.endswith("/ks.yaml")}
    if not ks_paths:
        return []
    settings = {rev: set(SETTINGS_KEY.findall(show(rev, "kubernetes/components/cluster-settings/configmap.yaml") or "")) for rev in (base, head)}
    cache: dict = {}
    out = []
    for ks in sorted(ks_paths):
        per_rev = {}
        for rev in (base, head):
            text = show(rev, ks)
            per_rev[rev] = {d["name"]: d for d in ks_documents(text)} if text else {}
        for name, doc in per_rev[head].items():
            for comp in doc["components"]:
                cdir = os.path.normpath(os.path.join(os.path.dirname(ks), comp))
                entry = {"ks": ks, "doc": name, "component": cdir, "unknown": doc["own_sources"]}
                for rev, key in ((head, "missing_head"), (base, "missing_base")):
                    d = per_rev[rev].get(name)
                    if d is None or comp not in d["components"]:
                        entry[key] = []
                        continue
                    if (rev, cdir) not in cache:
                        cache[(rev, cdir)] = component_text(rev, cdir)
                    text = cache[(rev, cdir)]
                    if text is None:
                        entry["unknown"] = True
                        entry[key] = []
                        continue
                    entry[key] = sorted(required_vars(text) - d["substitute"] - settings[rev])
                out.append(entry)
    return out


def author_kind(login: str) -> str:
    if "renovate" in login or login == "qnimbus-homelab-assistant[bot]":
        return "renovate"
    return "owner" if login == os.environ.get("GITHUB_REPOSITORY_OWNER", "qnimbus") else "other"


def repo_visibility(pr: dict) -> str:
    """public | private | internal, from the PR's base repository; public when unknown, which is
    both the conservative answer and, for qnimbus/home-lab, the actual one."""
    repo = (pr.get("base") or {}).get("repo") or {}
    if repo.get("visibility"):
        return repo["visibility"]
    if "private" in repo:
        return "private" if repo["private"] else "public"
    return os.environ.get("REPO_VISIBILITY") or "public"


def konflate_fetch(pr: int, head_sha: str, url: str, wait: float, *, sleep=time.sleep, now=time.monotonic):
    """Poll Konflate until it has a finished render of exactly `head_sha`, or give up.

    Returns (state, summary, diff): state is fresh | unavailable | not_rendered | stale.
    """
    start, delay, last = now(), 10.0, "no response"
    while True:
        elapsed = now() - start
        try:
            status, headers, body = http_json(
                f"{url}/api/prs/{pr}/summary", headers={"Accept": "application/json"}
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return "unavailable", {"reason": f"Konflate unreachable: {e}"}, None
        if status == 200 and isinstance(body, dict):
            rendered = ((body.get("diff") or {}).get("headSha") or (body.get("pr") or {}).get("headSha") or "")
            if body.get("refreshError"):
                last = "last refresh failed"
            elif len(rendered) >= 7 and head_sha.startswith(rendered):
                diff = None
                if body.get("status") == "ready":
                    ds, _, dbody = http_json(f"{url}/api/prs/{pr}/diff", timeout=30)
                    diff = dbody if ds == 200 and isinstance(dbody, dict) else None
                body["renderStatus"] = headers.get("X-Konflate-Render-Status") or headers.get(
                    "x-konflate-render-status"
                )
                return "fresh", body, diff
            else:
                last = f"render is of {rendered[:7] or '?'}, want {head_sha[:7]}"
        elif status == 202:
            last = "rendering"
        elif status == 404:
            last = "not rendered (no area/kubernetes label yet?)"
            if elapsed > min(120, wait):
                return "not_rendered", {"reason": last}, None
        else:
            return "unavailable", {"reason": f"Konflate answered {status}"}, None
        if elapsed + delay > wait:
            return "stale", {"reason": f"gave up after {int(elapsed)}s: {last}"}, None
        log(f"konflate: {last}; retrying in {int(delay)}s")
        sleep(delay)
        delay = min(delay * 1.5, 20.0)


def cmd_collect(a) -> None:
    event = json.loads(Path(a.event).read_text())
    collect(event, a.base, a.head or event["pull_request"]["head"]["sha"], Path(a.out), a.konflate_url, a.konflate_wait, a.checks_wait)


def collect(event: dict, base: str, head: str, out: Path, konflate_url: str | None, konflate_wait: float, checks_wait: float = 0.0) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pr = event["pull_request"]
    facts = collect_git(base, head, out)
    login = pr["user"]["login"]
    meta = {
        "number": pr["number"],
        "title": redact(pr.get("title") or ""),  # public already, but it goes to Jev and the artifact
        "body": redact(pr.get("body") or ""),
        "author": login,
        "author_kind": author_kind(login),
        "labels": [lbl["name"] for lbl in pr.get("labels", [])],
        "repo_visibility": repo_visibility(pr),
        **facts,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    notes = gather_release_notes(meta)
    (out / "release_notes.json").write_text(json.dumps(notes, indent=2))
    log(f"release notes: {notes['source']}, {len(notes['sections'])} version(s) ({notes['reason']})")

    files = json.loads((out / "files.json").read_text())
    relevant = any(rendered_path(f["path"]) for f in files)
    if not relevant:
        state, summary, diff = "skipped", {"reason": "PR renders no Flux resources"}, None
    elif not konflate_url:
        state, summary, diff = "unavailable", {"reason": "no Konflate URL"}, None
    else:
        state, summary, diff = konflate_fetch(meta["number"], facts["head_sha"], konflate_url, konflate_wait)
    (out / "konflate.json").write_text(json.dumps({"state": state, "summary": summary}, indent=2))
    if diff:
        (out / "konflate_diff.json").write_text(json.dumps(diff))
    repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name") or os.environ.get("GITHUB_REPOSITORY", "")
    checks = collect_checks(files, repo, facts["head_sha"], checks_wait)
    (out / "checks.json").write_text(json.dumps(checks, indent=2))
    log(f"collected {len(files)} files; konflate {state}; {len(checks)} workflow run(s)")


# ── Jev state ────────────────────────────────────────────────────────────────────────────────


def split_diff(diff: str) -> list[dict]:
    chunks = []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        if not part.startswith("diff --git "):
            continue
        m = re.match(r"diff --git a/(.*?) b/(.*)", part.splitlines()[0])
        chunks.append({"path": m.group(2) if m else "?", "text": part})
    return chunks


def clip_lines(text: str, width: int) -> str:
    return "\n".join(line if len(line) <= width else line[:width] + " …" for line in text.splitlines())


def budget_diff(diff: str, total: int, per_file: int) -> tuple[str, list[str], list[str]]:
    """Widest-reach files first; returns (text, paths cut or left out, paths left out)."""
    chunks = [c for c in split_diff(diff) if not matches(c["path"], DROP_FROM_DIFF) and "\nBinary files " not in c["text"]]
    chunks.sort(key=lambda c: -REACH.index(reach(c["path"])))
    out, used, cut, omitted = [], 0, [], []
    for c in chunks:
        text = clip_lines(c["text"], BUDGET["line"])
        if len(text) > per_file:
            text = text[:per_file] + "\n… (file truncated)\n"
            cut.append(c["path"])
        if used + len(text) > total:
            omitted.append(c["path"])
            continue
        out.append(text)
        used += len(text)
    return "".join(out), list(dict.fromkeys(cut + omitted)), omitted


DESCRIPTION_KEY = re.compile(r"^(\s*)description:")


CONVERSION_KEY = re.compile(r"^(\s*)conversion:\s*$")
YAML_STRUCTURE = re.compile(r"""^\s*(-\s+)?("[^"]*"|'[^']*'|[\w$.\-/]+):(\s|$)|^\s*-(\s|$)|^\s*[\]\[{}]""")


def visible_rows(r: dict):
    """Yield (row, text, kind) for a resource's unfolded rows and hunk markers. For a CRD, kind
    is "description" for a `description:` key, its continuation lines (blank ones included)
    and prose whose `description:` line Konflate folded or left out (#186: "This is a beta
    field and requires enabling …" counted as schema), "conversion" for the conversion block
    (compat.crd_conversion_changed covers it), and "" for the schema. Folded rows still drive
    the tracking; they just aren't yielded."""
    crd = r.get("kind") == "CustomResourceDefinition"
    desc_indent = conv_indent = None
    for u in r.get("unified") or []:
        if u.get("hunk"):
            desc_indent = None
            if not u.get("folded"):
                yield u, "", ""
            continue
        text, kind = row_text(u), ""
        if crd:
            indent = len(text) - len(text.lstrip())
            if conv_indent is not None and text.strip() and indent <= conv_indent:
                conv_indent = None
            if desc_indent is not None and (not text.strip() or indent > desc_indent):
                kind = "description"
            else:
                desc_indent = None
                if m := DESCRIPTION_KEY.match(text):
                    desc_indent, kind = len(m.group(1)), "description"
                elif m := CONVERSION_KEY.match(text):
                    conv_indent, kind = len(m.group(1)), "conversion"
                elif conv_indent is not None:
                    kind = "conversion"
                elif text.strip() and not YAML_STRUCTURE.match(text):
                    kind = "description"  # prose: a description whose key line isn't in the diff
        if not u.get("folded"):
            yield u, text, kind


def crd_schema_changed(r: dict) -> bool:
    """Whether a CRD's diff changes anything besides description text."""
    return any(u.get("kind") in ("add", "del") and not desc for u, _, desc in visible_rows(r))


def any_crd_schema_change(kdiff: dict | None) -> bool:
    resources = ((kdiff or {}).get("diff") or {}).get("resources") or []
    return any(r.get("kind") == "CustomResourceDefinition" and crd_schema_changed(r) for r in resources)


def crd_version_changes(kdiff: dict | None) -> list[str]:
    """CRDs whose served or storage versions change: what can break existing custom resources or
    their controllers. New fields and description churn, the bulk of a chart bump's CRD diff,
    can't."""
    out = []
    for h in rules.render_hunks(kdiff):
        if h.kind == "CustomResourceDefinition" and any(rules.crd_versions(h.lines)) and h.path not in out:
            out.append(h.path)
    return out


def render_resource(r: dict, per_resource: int) -> str:
    """A CRD's diff is mostly `description:` text; it goes, so the budget holds the schema."""
    lines = [f"### {r.get('status', '?')} {r.get('title') or r.get('kind', '?')} (from {r.get('parent') or '-'})"]
    skipped, conversion = 0, 0
    for u, text, kind in visible_rows(r):
        if u.get("hunk"):
            lines.append("@@")
        elif kind == "description":
            skipped += 1
        elif kind == "conversion":
            conversion += u.get("kind") in ("add", "del")
        else:
            lines.append({"add": "+", "del": "-"}.get(u.get("kind"), " ") + text)
    if skipped:
        lines.append(f"({skipped} description lines left out)")
    if conversion:
        # Not a schema change: said so, so the schema question isn't answered about it (#171).
        lines.append(f"({conversion} lines of the conversion strategy changed; that is assessed separately and is not a schema change)")
    if r.get("kind") == "CustomResourceDefinition" and not crd_schema_changed(r):
        # Said outright: an empty "changed" CRD left the model unsure (#177, `crd_schema_change` 0.41)
        lines.append("(only description text changed; the schema itself is unchanged)")
    text = clip_lines("\n".join(lines), BUDGET["line"])
    if len(text) > per_resource:
        text = text[:per_resource] + "\n… (resource truncated)"
    return text


def budget_rendered(kdiff: dict | None, total: int, per_resource: int) -> tuple[str, list[str]]:
    """Returns (text, titles of resources cut or left out)."""
    resources = ((kdiff or {}).get("diff") or {}).get("resources") or []

    def rank(r):
        return next((i for i, kinds in enumerate(RENDER_PRIORITY) if r.get("kind") in kinds), len(RENDER_PRIORITY))

    # The per-resource cap only matters when everything doesn't fit: one big new CRD in an
    # otherwise small diff shouldn't be cut (tailscale-operator: 8.1k chars in a 10k diff).
    if sum(len(render_resource(r, total)) + 1 for r in resources) <= total:
        per_resource = total
    out, used, cut = [], 0, []
    for r in sorted(resources, key=rank):
        text = render_resource(r, per_resource) + "\n"
        if text.rstrip().endswith("(resource truncated)"):
            cut.append(r.get("title") or "?")
        if used + len(text) > total:
            out.append(f"### {r.get('status')} {r.get('title')} (omitted: budget)\n")
            cut.append(r.get("title") or "?")
            continue
        out.append(text)
        used += len(text)
    return "".join(out), list(dict.fromkeys(cut))


def file_line(f: dict) -> str:
    moved = f" (from {f['old_path']})" if f.get("old_path") else ""
    return f"{f['status']} {f['path']}{moved} +{f.get('additions', 0)}/-{f.get('deletions', 0)} [{surface_id(f['path'])}, reach {reach(f['path'])}]"


RENOVATE_FOOTER = re.compile(r"\n---\s*\n+### Configuration.*", re.S)
RENOVATE_NOTES = re.compile(r"\n### Release Notes\s*\n(.*)", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HTML_MARKUP = re.compile(r"</?(details|summary)>")


def clean_description(body: str, kind: str) -> str:
    """Renovate's configuration footer ("Please merge this manually…", rebase checkbox) reads as
    text addressed to a reviewer, and its release notes go to `release_notes`, so what remains is
    the update table. Human PRs keep everything, HTML comments included, so the manipulation
    question can see hidden text."""
    if kind == "renovate":
        body = HTML_COMMENT.sub("", RENOVATE_NOTES.sub("", RENOVATE_FOOTER.sub("", body)))
    return body.strip() or "(empty)"


def release_notes(body: str, kind: str) -> str:
    """The release notes Renovate copies into its PR body, or "" when it found none (common for
    charts mirrored to OCI registries without a source URL)."""
    if kind != "renovate":
        return ""
    m = RENOVATE_NOTES.search(RENOVATE_FOOTER.sub("", body or ""))
    notes = HTML_MARKUP.sub("", HTML_COMMENT.sub("", m.group(1))) if m else ""
    return notes.strip().removesuffix("---").strip()


# ── Release notes: sections, substance, GitHub fallback ──────────────────────────────────────
# Renovate's notes are the first source. They are split per version so the budget can keep the
# oldest versions (the ones right after what runs now, where a jump's breaking changes are),
# and they only count when a version says something: tailscale's say "Please refer to the
# changelog available at …" for every release. Without usable notes, collect() looks up the
# GitHub releases between the two versions itself.

NOTE_HEADING = re.compile(r"(?m)^#{2,4} \[?`?([\w.-]*\d[\w.+-]*)`?\]?(?:\(.*)?$")  # ### [`v0.9.0`](…)
POINTER = re.compile(r"(?i)\b(refer to|see|available at|moved to|can be found)\b.*\b(changelog|release notes|releases)\b")
LINKS = re.compile(r"\[([^\]]*)\]\([^)]*\)|https?://\S+|<[^>]+>")


def note_sections(notes: str) -> list[dict]:
    """Renovate's notes, one section per version heading, oldest first (Renovate lists newest
    first). Text before the first heading (the package summary line) is dropped."""
    heads = list(NOTE_HEADING.finditer(notes))
    sections = [
        {"version": m.group(1), "text": notes[m.start() : heads[i + 1].start() if i + 1 < len(heads) else len(notes)].strip()}
        for i, m in enumerate(heads)
    ]
    return sections[::-1]


def substantive(text: str) -> bool:
    """Whether a version's notes say anything beyond a heading, a compare link or a pointer to
    a changelog elsewhere: some line with three or more words of its own."""
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("[Compare Source]") or POINTER.search(line):
            continue
        if len(re.findall(r"[A-Za-z]{2,}", LINKS.sub(r"\1", line))) >= 3:
            return True
    return False


RENOVATE_ROW = re.compile(  # the package is a link, or plain text when Renovate has no homepage for it
    r"(?m)^\|\s*(?:\[([^\]]+)\]\(([^)]+)\)|([^\s|\[][^|]*?))(?:\s*\(\[source\]\(([^)]+)\)\))?\s*\|\s*(\w+)\s*\|\s*`([^`]+)`\s*→\s*`([^`]+)`\s*\|"
)
# Packages Renovate names by their GitHub repo and links nothing for (`depName=` in a
# `# renovate:` comment). Listed, not matched by shape: a Docker Hub image (`traefik/whoami`,
# `fireflyiii/core`) looks the same, and its namespace is not a GitHub owner.
REPO_PACKAGES = {"siderolabs/talos", "fluxcd/flux2"}
BARE_REPO = re.compile(r"^[\w-]+/[\w.-]+$")  # the shape only: an unlisted one is reported, not looked up
GITHUB_REPO = re.compile(r"^https://(?:redirect\.)?github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?(?:[#?].*)?$")
TAG_VERSION = re.compile(r"(.*?)(v?\d+(?:\.\d+)+)")


def renovate_updates(body: str) -> list[dict]:
    """The rows of Renovate's update table: package, GitHub repos it links, from, to."""
    out = []
    for m in RENOVATE_ROW.finditer(body or ""):
        linked, link, plain, source, kind, old, new = m.groups()
        package = linked or plain
        repos = [g.group(1) for u in (link, source) if u and (g := GITHUB_REPO.match(u))]
        out.append({"package": package, "repos": list(dict.fromkeys(repos)), "type": kind, "from": old, "to": new})
    return out


def vkey(version: str) -> tuple | None:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", version)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_chart(package: str) -> bool:
    return any(x in package for x in ("/charts/", "/charts-mirror/", "helm-charts", "/helm/"))


def tag_version(tag: str, package: str) -> str | None:
    """The version a release tag stands for, if the tag is about this package. A monorepo tag
    must name it (`snapshot-controller-5.3.0`, `cloudnative-pg-v0.29.1`). A bare `v1.2.3` only
    counts for a container image: for a chart it is the app's version, which is a different
    number line (plugin-barman-cloud's app has a v0.8.0 of its own, years before chart 0.8.0).
    Wrong notes are worse than none: they can read as a confident "nothing breaking"."""
    m = TAG_VERSION.fullmatch(tag)
    if not m:
        return None
    prefix, version = m.group(1).rstrip("-_/@"), m.group(2)
    if prefix:
        return version if prefix == package.rsplit("/", 1)[-1] else None
    return None if is_chart(package) else version


def candidate_repos(update: dict) -> list[str]:
    """The repos Renovate's table links, then, for a chart, its org's usual chart monorepos:
    Renovate often links the app's repo for a chart (prometheus-community's charts link
    smartctl_exporter, not helm-charts). A wrong guess costs a lookup, never wrong notes:
    tag_version() only accepts tags that name the chart. A package Renovate links nothing for
    is its own repo when REPO_PACKAGES lists it (`siderolabs/talos`)."""
    repos = list(update["repos"])
    if not repos and update["package"] in REPO_PACKAGES:
        repos.append(update["package"])
    m = re.match(r"^[^/]+/([\w.-]+)/(?:charts|helm-charts|charts-mirror)/", update["package"])
    if m and is_chart(update["package"]):
        repos += [f"{m.group(1)}/helm-charts", f"{m.group(1)}/charts", f"{m.group(1)}/helm"]
    return list(dict.fromkeys(repos))


def github_release_sections(update: dict, get=None) -> tuple[list[dict], str, bool]:
    """Releases in (from, to] from the first candidate repo that has a matching release for
    `to`, oldest first, with the reason when none qualify. The third value is whether the range
    is incomplete: the listing ended (or hit the page limit) before a release at or below
    `from` was seen, so versions right after the running one may be missing."""
    get = get or github_pages
    lo, hi = vkey(update["from"]), vkey(update["to"])
    if not (lo and hi) or lo >= hi:
        return [], f"{update['from']} → {update['to']} isn't a version range", False
    repos = candidate_repos(update)
    if not repos:
        return [], "no GitHub repo to look in", False
    for repo in repos:
        found, reached_from = [], False
        for page in get(f"/repos/{repo}/releases"):
            for rel in page:
                v = tag_version(rel.get("tag_name") or "", update["package"])
                if not v or not vkey(v) or rel.get("draft") or rel.get("prerelease"):
                    continue
                if vkey(v) <= lo:
                    reached_from = True
                elif vkey(v) <= hi:
                    found.append((vkey(v), {"version": rel["tag_name"], "text": f"### {rel['tag_name']}\n\n{(rel.get('body') or '').strip()}"}))
            if reached_from:  # releases come newest first: everything in range has been seen
                break
        if not any(k == hi for k, _ in found):
            continue  # the target release isn't here: not this package's repo
        sections = [s for _, s in sorted(found, key=lambda x: x[0])]
        bodies = {s["text"].split("\n", 2)[-1] for s in sections}
        if len(sections) > 1 and len(bodies) == 1:
            return [], f"{repo}'s releases repeat one text, not a changelog", False
        if not any(substantive(s["text"]) for s in sections):
            return [], f"{repo}'s releases only point elsewhere", False
        partial = "" if reached_from else f", back to {sections[0]['version']} only"
        return sections, f"GitHub releases of {repo}{partial}", not reached_from
    return [], "no release tagged for this package in " + ", ".join(repos), False


def github_api() -> tuple[str, dict]:
    """(API root, headers). The token (GITHUB_TOKEN or GH_TOKEN) is optional: what is read here
    is public, it only lifts the rate limit."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return os.environ.get("GITHUB_API_URL", "https://api.github.com"), headers


def github_get(path: str) -> dict | None:
    """One GitHub API object, or None when it can't be read."""
    api, headers = github_api()
    try:
        status, _, body = http_json(f"{api}{path}", headers=headers, timeout=15)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log(f"github {path}: {e}")
        return None
    if status != 200 or not isinstance(body, dict):
        log(f"github {path}: HTTP {status}")
        return None
    return body


def github_pages(path: str, pages: int = 10):
    """Yield the pages of a GitHub list, newest first for releases."""
    api, headers = github_api()
    for page in range(1, pages + 1):
        try:
            status, _, body = http_json(f"{api}{path}?per_page=100&page={page}", headers=headers, timeout=15)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"github {path}: {e}")
            return
        if status != 200 or not isinstance(body, list):
            if status != 404:  # 404: a guessed repo that doesn't exist
                log(f"github {path}: HTTP {status}")
            return
        yield body
        if len(body) < 100:
            return


TAG_LINK = re.compile(r"/releases/tag/([^)\s#?]+)")


def trusted_section(section: dict, updates: list[dict]) -> bool:
    """Whether a Renovate notes section is about a package this PR updates, judged by its
    heading link with the same rule as the GitHub lookup. Renovate gave plugin-barman-cloud's
    chart 0.7.0 → 0.8.0 the app's v0.8.0 notes, a year older and with an unrelated breaking
    change; those link the app's CHANGELOG.md, and a changelog without a tag is only trusted
    for a container image. Without a parsed update table there is nothing to judge by."""
    if not updates:
        return True
    m = TAG_LINK.search(section["text"].split("\n", 1)[0])
    if m:
        tag = urllib.parse.unquote(m.group(1))
        return any(tag_version(tag, u["package"]) for u in updates)
    return any(not is_chart(u["package"]) for u in updates)


def gather_release_notes(meta: dict, get=None) -> dict:
    """{source: renovate | github | none, sections (oldest first), reason, unlisted}. Renovate's
    notes win when a version has substance; otherwise each updated package's GitHub releases are
    tried. `partial`: some package's fetched releases don't reach back to its `from` version
    (see github_release_sections). `unlisted`: packages without notes that are named like a GitHub repo, link nothing and
    aren't in REPO_PACKAGES, so nobody looked (ctx.release_notes_unlisted says what to do)."""
    if meta.get("author_kind") != "renovate":
        return {"source": "none", "sections": [], "reason": "not a Renovate PR"}
    updates = renovate_updates(meta.get("body") or "")
    sections = note_sections(release_notes(meta.get("body") or "", "renovate"))
    trusted = [s for s in sections if trusted_section(s, updates)]
    if any(substantive(s["text"]) for s in trusted):
        return {"source": "renovate", "sections": trusted, "reason": "Renovate's PR body"}
    if len(trusted) < len(sections):
        why = "Renovate's notes are the app's releases, not the chart's"
    else:
        why = "Renovate's notes only point elsewhere" if sections else "Renovate found no release notes"
    fetched, reasons, unlisted, partial = [], [], [], False
    for update in updates:
        got, reason, short = github_release_sections(update, get)
        fetched += got
        partial |= short
        if not got and not candidate_repos(update) and BARE_REPO.match(update["package"]):
            unlisted.append(update["package"])
            reason += " (named like a repo, not in REPO_PACKAGES)"
        reasons.append(f"{update['package'].rsplit('/', 1)[-1]}: {reason}")
    if fetched:
        return {"source": "github", "sections": fetched, "reason": f"{why}; " + "; ".join(reasons), "unlisted": unlisted, "partial": partial}
    return {"source": "none", "sections": [], "reason": f"{why}; " + ("; ".join(reasons) or "no update table"), "unlisted": unlisted}


def budget_notes(sections: list[dict], total: int, per_version: int) -> tuple[str, bool]:
    """Oldest versions first, newest dropped when over budget, with a note saying which."""
    out, used, left_out = [], 0, []
    for s in sections:
        text = s["text"] if len(s["text"]) <= per_version else s["text"][:per_version] + "\n… (truncated)"
        if used + len(text) > total:
            left_out.append(s["version"])
            continue
        out.append(text)
        used += len(text)
    if left_out:
        out.append(f"(newer versions left out for size: {', '.join(left_out)})")
    return "\n\n".join(out), bool(left_out)


def budget_config(config: dict[str, str], total: int, per_file: int) -> str:
    out, used = [], 0
    for path, text in config.items():
        text = f"# {path}\n" + (text if len(text) <= per_file else text[:per_file] + "\n… (truncated)")
        if used + len(text) > total:
            out.append(f"# {path} (omitted for size)")
            continue
        out.append(text)
        used += len(text)
    return "\n".join(out)


def config_fits(config: dict[str, str], total: int, per_file: int) -> bool:
    """Whether budget_config sends all of it: no file cut, none left out."""
    return all(len(text) <= per_file for text in config.values()) and sum(len(f"# {path}\n") + len(text) for path, text in config.items()) <= total


def raw_state(meta, files, diff, base_diff, sections=(), config=None, scale=1.0, invariants=False) -> tuple[dict, list[str]]:
    """The raw-diff call's input; returns (state, paths cut or left out). Secret-shaped strings
    are redacted here too, for bundles collected before collect() did it."""
    notes, _ = budget_notes(list(sections), int(BUDGET["release_notes"] * scale), int(BUDGET["release_notes_per_version"] * scale))
    config = {k: redact(v) for k, v in (config or {}).items()}
    conf = budget_config(config, int(BUDGET["config"] * scale), int(BUDGET["config_per_file"] * scale)) if notes or invariants else ""
    diff_budget = max(int(BUDGET["diff"] * scale) - len(notes) - len(conf), 8_000)
    text, cut, omitted = budget_diff(redact(diff), diff_budget, int(BUDGET["diff_per_file"] * scale))
    state = {
        "title": redact(meta.get("title", "")),
        "description": clean_description(redact(meta.get("body") or ""), meta.get("author_kind", "other"))[: BUDGET["description"]],
        "author": meta.get("author_kind", "other"),
        "files": [file_line(f) for f in files],
        "diff": text + (f"\n(omitted for size: {', '.join(omitted)})" if omitted else ""),
    }
    if notes:
        state["release_notes"] = notes
    if conf:
        state["config"] = conf
    if invariants:
        state["invariants"] = semantic.INVARIANTS
    if base_diff:
        state["base_changes"] = redact(base_diff)[: int(BUDGET["base_changes"] * scale)]
    return state, cut


def rendered_state(meta, kinfo, kdiff, scale=1.0) -> tuple[dict, list[str]]:
    text, cut = budget_rendered(kdiff, int(BUDGET["rendered"] * scale), int(BUDGET["rendered_per_resource"] * scale))
    return {
        "title": redact(meta.get("title", "")),
        "konflate": {k: kinfo.get(k) for k in ("resources", "crds", "images", "rules", "routine")},
        "rendered_diff": text,
    }, cut


# ── Jev client ───────────────────────────────────────────────────────────────────────────────


class JevError(Exception):
    pass


def call_jev(state: dict, questions: dict, *, key: str, model: str, sleep=time.sleep) -> dict:
    payload = {"state": state, "model": model, "questions": questions}
    headers = {"Authorization": f"Bearer {key}"}
    for attempt in range(3):
        try:
            status, hdrs, body = http_json(JEV_URL, data=payload, headers=headers, timeout=30)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            status, hdrs, body = 0, {}, str(e)
        if status == 200 and isinstance(body, dict) and "answers" in body:
            return body
        retryable = status in (0, 408, 429, 529) or status >= 500
        if not retryable or attempt == 2:
            raise JevError(f"HTTP {status}: {str(body)[:500]}")
        retry_after = hdrs.get("Retry-After") or hdrs.get("retry-after")
        sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * 2**attempt)
    raise JevError("unreachable")


def ask(name, build, questions, *, key, model, fixture, answer=None):
    """build(scale) -> (state, cut). Returns (response | None, cut, error | None). `answer`
    (tests) is called as answer(name, state, questions) in place of the API."""
    state, cut = build(1.0)
    if answer is not None:
        try:
            return answer(name, state, questions), cut, None
        except JevError as e:
            return None, cut, str(e)
    if fixture is not None:
        return fixture.get(name), cut, None if name in fixture else "not in fixture"
    if not key:
        return None, cut, "TYPESAFE_API_KEY not set"
    try:
        return call_jev(state, questions, key=key, model=model), cut, None
    except JevError as e:
        if "HTTP 422" in str(e) and re.search(r"token|length|size|long", str(e), re.I):
            state, cut = build(0.5)
            try:
                return call_jev(state, questions, key=key, model=model), cut or ["(whole input halved)"], None
            except JevError as e2:
                return None, cut, str(e2)
        return None, cut, str(e)


# ── classify ─────────────────────────────────────────────────────────────────────────────────


def konflate_info(k: dict) -> dict:
    """Structured fields only; Konflate's free text (details, failure messages) stays out of
    the model's input."""
    state, summary = k.get("state"), k.get("summary") or {}
    info = {"state": state, "reason": summary.get("reason")}
    if state == "fresh":
        d = summary.get("diff") or {}
        info.update(
            head=(d.get("headSha") or "")[:7],
            resources=(d.get("impact") or {}).get("resources", 0),
            crds=(d.get("impact") or {}).get("crds", 0),
            routine=bool(d.get("routine")),
            rules=[w.get("rule") for w in d.get("warnings") or []],
            images=[f"{i.get('name')} {i.get('from') or '∅'}→{i.get('to') or '∅'}" for i in d.get("images") or []],
            url=summary.get("reviewUrl"),
        )
    return info


def load_bundle(d: Path) -> dict:
    meta = read_json(d / "meta.json")
    b = {
        "meta": meta,
        "files": read_json(d / "files.json", []),
        "overlap": read_json(d / "overlap.json", []),
        "conflict": read_json(d / "conflict.json", {"conflict": None, "files": []}),
        "konflate": read_json(d / "konflate.json", {"state": "unavailable", "summary": {"reason": "not collected"}}),
        "kdiff": read_json(d / "konflate_diff.json"),
        "diff": (d / "pr.diff").read_text(errors="replace") if (d / "pr.diff").exists() else "",
        "base_diff": (d / "base_overlap.diff").read_text(errors="replace") if (d / "base_overlap.diff").exists() else "",
        "config": read_json(d / "config.json", {}),
        "components": read_json(d / "components.json", []),
        "secrets": read_json(d / "secrets.json", []),
        "checks": read_json(d / "checks.json", []),  # absent in bundles from before it was collected
    }
    # collect() writes release_notes.json; older bundles and fixtures fall back to the PR body
    notes = read_json(d / "release_notes.json")
    if notes is None:
        notes = gather_release_notes({**meta, "body": meta.get("body") or ""}, get=lambda path: [])
        if notes["source"] == "none" and meta.get("author_kind") == "renovate":
            notes["reason"] = notes["reason"].split(";")[0] + "; GitHub releases not checked (bundle predates release_notes.json)"
    b["notes"] = notes
    return b


def surface_texts(files: list[dict], diff: str, config: dict) -> dict[str, str]:
    texts: dict[str, list[str]] = {}
    for c in split_diff(diff):
        texts.setdefault(surface_id(c["path"]), []).append(c["text"])
    for path, text in config.items():
        texts.setdefault(surface_id(path), []).append(text)
    return {k: "\n".join(v) for k, v in texts.items()}


def chars(v) -> int:
    return len(v) if isinstance(v, str) else len(json.dumps(v, ensure_ascii=False))


def classify(d: Path, *, key: str | None, model: str, fixture: dict | None = None, answer=None, requests: dict | None = None) -> dict:
    """`requests`, when given, is filled with each Jev call's payload as sent ({call: {model,
    state, questions}}): cmd_classify writes it to jev_request.json."""
    t0 = time.monotonic()
    b = load_bundle(d)
    meta, files, konflate, kdiff, notes = b["meta"], b["files"], b["konflate"], b["kdiff"], b["notes"]
    surfaces = build_surfaces(files, surface_texts(files, b["diff"], b["config"]))
    f = Facts(meta, files, b["overlap"], b["conflict"], konflate, kdiff, b["diff"], b["base_diff"], b["config"], notes,
              b["components"], b["secrets"], surfaces, checks=b["checks"],
              config_complete=config_fits({k: redact(v) for k, v in b["config"].items()}, BUDGET["config"], BUDGET["config_per_file"]))  # fmt: skip
    a = Assessment(surfaces)
    ran = rules.evaluate(f, a)
    rules.compute_presence(f)
    f.presence["crd_schema"] = {"*"} if konflate.get("state") == "fresh" and any_crd_schema_change(kdiff) else set()
    kinfo = konflate_info(konflate)

    # Jev: only when something needs it (docs-only PRs don't), and only about what is there.
    calls = semantic.plan(
        f,
        has_notes=bool(notes["sections"]),
        has_config=bool(b["config"]),
        has_base_changes=bool(b["base_diff"]),
        human=meta.get("author_kind") != "renovate",
        rendered_ok=konflate.get("state") == "fresh" and bool(kdiff),
    )
    builders = {
        "raw": lambda sc, q=None: raw_state(meta, files, b["diff"], b["base_diff"], notes["sections"], b["config"], sc,
                                            invariants="setting_conflict" in (q or {})),  # fmt: skip
        "rendered": lambda sc, q=None: rendered_state(meta, kinfo, kdiff, sc),
    }
    jobs = {c.name: (c, c.payload(bool(notes["sections"]))) for c in calls}
    sent: dict[str, dict] = {}

    def build(name, scale, questions):  # the last state built is the one sent (a 422 rebuilds it at half size)
        state, cut = builders[name](scale, questions)
        sent[name] = state
        return state, cut

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            n: pool.submit(ask, n, lambda sc, n=n, q=qs: build(n, sc, q), qs, key=key, model=model, fixture=fixture, answer=answer)
            for n, (c, qs) in jobs.items()
        }
        results = {n: fu.result() for n, fu in futures.items()}

    jev = {"model": None, "usage": {}, "errors": {}, "answers": {}, "asked": {n: sorted(qs) for n, (_, qs) in jobs.items()}}
    # For the comment: each question as worded for this PR (breaking_notes is about `description`
    # when there are no notes) and the size of each input field. The full payload is `requests`.
    # A call that failed (no key, Jev down) answered nothing: it isn't listed as sent, and its
    # payload in `requests` carries the error instead.
    failed = {n: err for n, (_, _, err) in results.items() if err}
    jev["sent"] = {
        n: {"fields": {k: chars(v) for k, v in sent.get(n, {}).items()}, "questions": {q: spec["instructions"]["question"] for q, spec in qs.items()}}
        for n, (_, qs) in jobs.items()
        if n not in failed
    }
    if requests is not None:
        requests.update({n: {"model": model, "state": sent.get(n), "questions": qs, **({"error": failed[n]} if n in failed else {})}
                         for n, (_, qs) in jobs.items()})  # fmt: skip
    for name, (resp, cut, err) in results.items():
        call = jobs[name][0]
        if err:
            jev["errors"][name] = err
            log(f"jev {name}: {err}")
        used = semantic.interpret(f, a, call, None if err else resp, err, cut)
        if not err and resp:
            jev["model"] = resp.get("model") or jev["model"]
            jev["usage"][name] = resp.get("usage")
            jev["answers"][name] = used

    verdict = policy.decide(a)
    labels = [LABELS[verdict.classification]] + ([UNCERTAIN_LABEL] if verdict.uncertain else [])
    # An outage isn't evidence about the PR. Without Jev where a surface needs it, or with
    # Konflate unreachable for a PR it should render, the verdict isn't published (fail-open).
    rendered_needed = any(s.rendered for s in surfaces)
    outage = [n for n, down in (("Jev", "raw" in jev["errors"]), ("Konflate", rendered_needed and konflate.get("state") == "unavailable")) if down]
    sas = list(a.surfaces.values())
    dims = {
        "reach": max_reach(s.surface.reach for s in sas),
        "stakes": sorted({x for s in sas for x in s.surface.stakes}),
        "activation": sorted({x for s in sas for x in s.surface.activation}),
        "reversibility": worst_reversibility(s.reversibility for s in sas),
    }
    return {
        "schema": SCHEMA,
        "policy": POLICY_VERSION,
        "status": "unavailable" if outage else "classified",
        "classification": verdict.classification,
        "uncertain": verdict.uncertain,
        "rule": verdict.rule,
        "why": verdict.why,
        "dimensions": dims,
        "surfaces": [s.to_json() for s in sas],
        "findings": [finding_json(x) for x in a.findings],
        "evidence": [vars(e) for e in a.evidence],
        "context": a.context,
        "labels": labels,
        "number": meta.get("number"),
        "head_sha": meta.get("head_sha"),
        "outage": outage,
        "rules_run": ran,
        "konflate": kinfo,
        "jev": jev,
        "release_notes": {"source": notes["source"], "versions": [s["version"] for s in notes["sections"]], "reason": notes["reason"],
                          "sent": "" if "raw" in failed else (sent.get("raw") or {}).get("release_notes", "")},  # fmt: skip
        "thresholds": THRESHOLDS,
        "seconds": round(time.monotonic() - t0, 2),
        # v1 names, kept while backtest CSVs and dashboards from before v2 are compared.
        "verdict": verdict.classification,
        "available": not outage,
    }


# ── comment ──────────────────────────────────────────────────────────────────────────────────

ICON = {"safe": "🟢", "review": "🟡", "risky": "🔴"}
ACTION = {"safe": "merge as-is", "review": "check the findings before merging", "risky": "plan before merging"}
CERTAINTY_MARK = {"established": "established", "probable": "probable", "possible": "possible"}
EVIDENCE_COLUMNS = ["git", "render", "release_notes", "model"]
QUALITY_MARK = {"sufficient": "✓", "limited": "◐ limited", "insufficient": "✗ insufficient"}


NOTES_IN_COMMENT = 6_000  # characters of release notes shown in the comment; all of it is in jev_request.json


def cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def fenced(text: str) -> list[str]:
    """Upstream text as a code block: shown, not rendered, so its @mentions notify nobody and
    its markup can't pass for ours. The fence is longer than any backtick run inside."""
    fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", text)), default=0))
    return [fence + "text", text, fence]


def render_comment(r: dict) -> str:
    c = r["classification"]
    if r["status"] == "unavailable":
        head = f"### ⚪ PR risk unavailable: {' and '.join(r['outage'])} down, no labels changed. It would have said **{c}**."
    else:
        head = f"### {ICON[c]} PR risk: **{c}**, {ACTION[c]}" + (" · ⚠️ uncertain" if r["uncertain"] else "")
    out = [COMMENT_MARKER, head, "", f"**Why ({r['rule']}):** {r['why']}.", ""]

    material = [x for x in r["findings"] if x["kind"] != "evidence" and x["certainty"] != "ruled_out"]
    if material:
        out += ["| Surface | Finding | Certainty | Consequence | What |", "|---|---|---|---|---|"]
        order = {"established": 0, "probable": 1, "possible": 2}
        for x in sorted(material, key=lambda x: (order.get(x["certainty"], 3), x["code"])):
            conseq = "—" if x["consequence"] == "none" else x["consequence"].replace("_", " ")
            out.append(f"| `{x['surface'] or 'PR'}` | `{x['code']}` | {x['certainty']} | {conseq} | {cell(x['description'])} |")
        out.append("")
    gaps = [x for x in r["findings"] if x["kind"] == "evidence"]
    if gaps:
        quality = {e["id"]: e["quality"] for e in r["evidence"]}
        out += ["**Missing evidence**" if r["uncertain"] else "**Evidence gaps**", ""]
        seen = set()
        for x in gaps:
            q = next((quality[e] for e in x["evidence"] if e in quality), "limited")
            line = f"- `{x['code']}` ({q}) on `{x['surface'] or 'PR'}`: {x['description']}"
            if line not in seen:
                seen.add(line)
                out.append(line)
        out.append("")
    if not material and not gaps:
        out += ["_No findings, and the evidence covers every surface._", ""]

    dims = r["dimensions"]
    ctx = [f"reach **{dims['reach']}**", "stakes " + (", ".join(dims["stakes"]) or "none"),
           "activation " + (", ".join(dims["activation"]) or "none"), f"reversibility **{dims['reversibility']}**"]  # fmt: skip
    out.append("**Context:** " + " · ".join(ctx))
    if r["context"]:
        out += [""] + [f"- `{x['code']}`: {cell(x['detail'])}" for x in r["context"]]
    out.append("")

    rows = []
    for s in r["surfaces"]:
        ev = s["evidence"]
        cols = " | ".join(QUALITY_MARK.get(ev[k], ev[k]) if k in ev else "—" for k in EVIDENCE_COLUMNS)
        rows.append(f"| `{s['id']}` | {s['reach']} | {cols} |")
    details = ["<details><summary>Evidence by surface</summary>", "",
               "| Surface | Reach | Git | Render | Release notes | Jev |", "|---|---|---|---|---|---|", *rows, ""]  # fmt: skip
    rn = r.get("release_notes") or {}
    if rn.get("source"):
        got = "none" if rn["source"] == "none" else f"{rn['source']}, {', '.join(rn.get('versions') or [])}"
        details += [f"Release notes: {got} ({cell(rn.get('reason') or '')})", ""]
    sent = r["jev"].get("sent") or {}  # absent in results from before it was recorded
    for call, s in sent.items():
        if s.get("fields"):
            details += [f"Jev `{call}` input, in characters: " + " · ".join(f"`{k}` {n:,}" for k, n in s["fields"].items()), ""]
    answer_rows = []
    for call, answers in (r["jev"].get("answers") or {}).items():
        for q, ans in answers.items():
            val = ans.get("noul")
            asked = cell((sent.get(call) or {}).get("questions", {}).get(q, ""))
            answer_rows.append(f"| {call} | `{q}` | {asked} | {val:.2f} |" if isinstance(val, float) else f"| {call} | `{q}` | {asked} | {val} |")
    if answer_rows:
        details += ["Jev answers (noul: 0 no, 1 yes):", "", "| call | question | as asked | answer |", "|---|---|---|---|", *answer_rows, ""]
    notes = rn.get("sent") or ""
    if notes:
        shown = notes if len(notes) <= NOTES_IN_COMMENT else notes[:NOTES_IN_COMMENT] + "\n… (cut here; Jev got all of it)"
        details += [f"<details><summary>Release notes as sent to Jev ({len(notes):,} characters)</summary>", "", *fenced(shown), "", "</details>", ""]
    if sent:
        where = f"[this run]({r['run_url']})" if r.get("run_url") else "the run"
        details += [f"The full request is `jev_request.json` in the `pr-risk-{r['number']}` artifact of {where}.", ""]
    details.append("</details>")
    out += details

    k = r["konflate"]
    # Not Konflate's reviewUrl: it follows the host of the request, which in the workflow is the
    # in-cluster Service (http://konflate.flux-system.svc.cluster.local:8080), useless in a comment.
    link = f" · [rendered diff]({KONFLATE_UI}/#/pr/{r['number']})" if k.get("state") == "fresh" else ""
    render = f"Konflate @{k.get('head')}" if k.get("state") == "fresh" else f"Konflate {k.get('state')}"
    errors = "; ".join(f"{n}: {e[:120]}" for n, e in (r["jev"].get("errors") or {}).items())
    model = r["jev"].get("model") or "Jev not used"
    out += ["", f"<sub>{r['schema']} · policy {r['policy']} · {model}{' (' + errors + ')' if errors else ''} · {render} · advisory only{link}</sub>", ""]
    return "\n".join(out)


def cmd_classify(a) -> None:
    d = Path(a.input)
    fixture = read_json(Path(a.jev_fixture)) if a.jev_fixture else None
    if fixture and "jev" in fixture:  # a previous result.json: replay its answers
        fixture = {n: {"answers": ans, "model": fixture["jev"].get("model")} for n, ans in fixture["jev"]["answers"].items()}
    key = os.environ.get("TYPESAFE_API_KEY") or None
    model = os.environ.get("JEV_MODEL") or JEV_MODEL_DEFAULT
    requests: dict = {}
    result = classify(d, key=key, model=model, fixture=fixture, requests=requests)
    if os.environ.get("GITHUB_RUN_ID"):
        result["run_url"] = "{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}".format(**os.environ)
    comment = render_comment(result)
    (d / "result.json").write_text(json.dumps(result, indent=2))
    if fixture is None:  # a replay sends nothing: the run's own record of what was sent stays
        (d / "jev_request.json").write_text(json.dumps(requests, indent=2, ensure_ascii=False))
    (d / "comment.md").write_text(comment)
    if a.dry_run:
        print(comment)
    print(json.dumps({"classification": result["classification"], "uncertain": result["uncertain"], "rule": result["rule"],
                      "labels": result["labels"], "status": result["status"]}))  # fmt: skip
    if result["status"] != "classified":
        log(f"{' and '.join(result['outage'])} unavailable: no verdict, labels left as they are")
        sys.exit(3)


# ── publish ──────────────────────────────────────────────────────────────────────────────────


class GitHub:
    def __init__(self, token: str, repo: str, api: str = "https://api.github.com"):
        self.base, self.headers = f"{api}/repos/{repo}", {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def req(self, method: str, path: str, data=None):
        status, _, body = http_json(self.base + path, data=data, headers=self.headers, method=method, timeout=20)
        if status >= 300:
            raise RuntimeError(f"{method} {path}: HTTP {status}: {str(body)[:300]}")
        return body


def sync_labels(gh: GitHub, pr: int, want: list[str]) -> list[str]:
    have = {lbl["name"] for lbl in gh.req("GET", f"/issues/{pr}/labels?per_page=100")}
    ops = []
    for name in sorted(n for n in have if n.startswith("risk/") and n not in want):
        gh.req("DELETE", f"/issues/{pr}/labels/{urllib.parse.quote(name, safe='')}")
        ops.append(f"-{name}")
    add = [n for n in want if n not in have]
    if add:
        gh.req("POST", f"/issues/{pr}/labels", {"labels": add})
        ops += [f"+{n}" for n in add]
    return ops


def upsert_comment(gh: GitHub, pr: int, body: str, bot: str = "github-actions[bot]") -> str:
    page = 1
    while True:
        comments = gh.req("GET", f"/issues/{pr}/comments?per_page=100&page={page}")
        for c in comments:
            if c["user"]["login"] == bot and c["body"].startswith(COMMENT_MARKER):
                if c["body"].strip() == body.strip():
                    return "unchanged"
                gh.req("PATCH", f"/issues/comments/{c['id']}", {"body": body})
                return "updated"
        if len(comments) < 100:
            break
        page += 1
    gh.req("POST", f"/issues/{pr}/comments", {"body": body})
    return "created"


def cmd_publish(a) -> None:
    d = Path(a.input)
    result = read_json(d / "result.json")
    mode = (os.environ.get("PR_RISK_MODE") or "shadow").strip()
    if mode not in ("labels", "comment"):
        log(f"mode {mode}: not publishing")
        return
    if result.get("status", "classified") != "classified":  # belt and braces: the workflow already skips this
        log("classification unavailable: not publishing")
        return
    gh = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    log("labels: " + (" ".join(sync_labels(gh, result["number"], result["labels"])) or "unchanged"))
    if mode == "comment":
        log("comment: " + upsert_comment(gh, result["number"], (d / "comment.md").read_text()))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--base", required=True, help="base commit-ish, e.g. origin/main")
    c.add_argument("--head", help="PR head SHA (default: from the event)")
    c.add_argument("--event", required=True, help="pull_request event JSON ($GITHUB_EVENT_PATH)")
    c.add_argument("--out", required=True)
    c.add_argument("--konflate-url", default=os.environ.get("KONFLATE_URL", KONFLATE_URL_DEFAULT))
    c.add_argument("--konflate-wait", type=float, default=float(os.environ.get("KONFLATE_WAIT_SECONDS") or 480))
    c.add_argument("--checks-wait", type=float, default=float(os.environ.get("CHECKS_WAIT_SECONDS") or 240),
                   help="seconds to wait for the PR's own runs of the workflows it changes")  # fmt: skip
    k = sub.add_parser("classify")
    k.add_argument("--input", required=True)
    k.add_argument("--jev-fixture", help='canned Jev responses {"raw": {...}, "rendered": {...}}, or a result.json to replay; skips the API')
    k.add_argument("--dry-run", action="store_true", help="print the comment")
    u = sub.add_parser("publish")
    u.add_argument("--input", required=True)
    a = p.parse_args(argv)
    {"collect": cmd_collect, "classify": cmd_classify, "publish": cmd_publish}[a.cmd](a)


if __name__ == "__main__":
    main()
