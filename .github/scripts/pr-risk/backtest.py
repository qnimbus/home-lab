#!/usr/bin/env python3
"""Backtest pr_risk.py over history, to calibrate the policy before labels are switched on.

Runs locally (needs `gh` and git history; Jev needs TYPESAFE_API_KEY, else --no-jev):

    git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'   # merged PR heads
    python3 .github/scripts/pr-risk/backtest.py prs --konflate-url https://konflate.cluster.vwn.io
    python3 .github/scripts/pr-risk/backtest.py commits --since 2026-06-01
    python3 .github/scripts/pr-risk/backtest.py commits --no-jev --baseline pr-risk-backtest-v1.csv

Ground truth comes from git: an item is a strong positive when one of its commits was later
reverted (`This reverts commit <sha>`, or a `revert(...)` / `fix(...): revert` commit touching the
same files within 14 days), and a weak positive when a non-Renovate `fix(...)` commit touched the
same files within 48 hours. Commits mode has no Konflate renders, so it judges without them.
Everything else counts as negative. What matters most is false-safe: a positive labelled `safe`.
Read every one of them; don't tune the policy to recall alone.

--no-jev answers every Jev question with a clear "no". What comes out is the verdict from
deterministic rules alone, which Jev could only raise: a false safe there is one only Jev can
catch.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_risk as p  # noqa: E402

REVERT_SHA = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True, errors="replace").stdout


def history(ref: str) -> list[dict]:
    """Non-merge commits on `ref`, oldest first, with files."""
    out = sh("git", "log", "--reverse", "--no-merges", "--format=%x1e%H%x1f%aI%x1f%an%x1f%s%x1f%b%x1f", "--name-only", ref)
    commits = []
    for rec in out.split("\x1e")[1:]:
        sha, date, author, subject, body, files = rec.split("\x1f", 5)
        commits.append({
            "sha": sha, "date": datetime.fromisoformat(date), "author": author, "subject": subject,
            "body": body, "files": set(filter(None, files.split("\n"))),
        })  # fmt: skip
    return commits


def ground_truth(commits: list[dict]) -> tuple[dict, list[dict]]:
    """sha -> reason for strong positives, plus the follow-up fix commits for weak ones."""
    strong: dict[str, str] = {}
    for c in commits:
        text = c["subject"] + "\n" + c["body"]
        for m in REVERT_SHA.finditer(text):
            target = next((x for x in commits if x["sha"].startswith(m.group(1))), None)
            if target:
                strong[target["sha"]] = f"reverted by {c['sha'][:7]}"
        if re.match(r"(?i)^revert(\(|:)|^fix(\([^)]*\))?: revert\b", c["subject"]):
            window = [x for x in commits if c["date"] - timedelta(days=14) <= x["date"] < c["date"] and x["files"] & c["files"]]
            for target in window[-1:]:  # the nearest earlier commit touching the same files
                strong.setdefault(target["sha"], f"reverted by {c['sha'][:7]}")
    fixes = [c for c in commits if re.match(r"^fix(\(|:)", c["subject"]) and "renovate" not in c["author"].lower() and not BUMP.search(c["subject"])]
    return strong, fixes


# A follow-up that is itself a version bump isn't a fix of the item (f93ed16, ff18e2f: the
# next Renovate update, committed under a human name).
BUMP = re.compile(r"(?i)\bupdate (image|chart|tool|release|dependency|action|module)\b|[➔→]")
# Files many unrelated changes touch: overlap through these alone says nothing. 2439395 (a
# bootstrap secret fix) labelled six chart bumps through the bootstrap helmfile that pins them.
SHARED = ["**/*.md", "docs/**", "bootstrap/**", "kubernetes/bootstrap/**", ".renovaterc.json5", ".renovate/**", "renovate.json5",
          ".mise.toml", ".mise/**", "**/*.lock", ".github/labels.yaml"]  # fmt: skip


def label_item(shas, when, files, strong, fixes) -> str:
    for s in shas:
        if s in strong:
            return "strong: " + strong[s]
    files = {f for f in files if f and not p.matches(f, SHARED)}
    for f in fixes:
        if when < f["date"] <= when + timedelta(hours=48) and files & f["files"] and f["sha"] not in shas:
            return f"weak: fix {f['sha'][:7]}"
    return ""


def clean_jev(name, state, questions):
    """--no-jev: every question answered with a clear no (and the description matching)."""
    return {"model": "none (--no-jev)", "usage": {}, "answers": {q: {"type": "noul", "noul": 0.95 if q == "description_matches" else 0.0} for q in questions}}


def run_item(event, base, head, konflate_url, key, model, no_jev=False, keep: Path | None = None) -> dict:
    """Collect and classify one item. With `keep`, the bundle stays there with result.json and
    comment.md, like a workflow artifact: readable, and replayable offline with
    `pr_risk.py classify --input <dir> --jev-fixture <dir>/result.json`."""
    with tempfile.TemporaryDirectory() as tmp:
        out = keep or Path(tmp)
        out.mkdir(parents=True, exist_ok=True)
        p.collect(event, base, head, out, konflate_url, 0)
        # No render exists for older history (commits, or PRs from before Konflate): judge the
        # rest on its own rather than flag every item uncertain.
        state = json.loads((out / "konflate.json").read_text())["state"]
        if not konflate_url or state == "not_rendered":
            (out / "konflate.json").write_text(json.dumps({"state": "ignored", "summary": {"reason": "backtest"}}))
        r = p.classify(out, key=key, model=model, answer=clean_jev if no_jev else None)
        if keep:
            (out / "result.json").write_text(json.dumps(r, indent=2))
            (out / "comment.md").write_text(p.render_comment(r))
        return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["prs", "commits", "replay"],
                    help="replay: re-classify a --keep directory with its recorded Jev answers (no API calls)")  # fmt: skip
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--since", help="commits mode: only commits after this date (YYYY-MM-DD)")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--konflate-url", help="prs mode: reuse Konflate renders that still match the merged head")
    ap.add_argument("--no-jev", action="store_true", help="deterministic rules only (every Jev question answered no)")
    ap.add_argument("--baseline", help="an earlier run's CSV (v1 or v2) to compare verdicts with")
    ap.add_argument("--out", default="pr-risk-backtest.csv")
    ap.add_argument("--keep", type=Path, help="keep each item's bundle, result.json and comment.md in <dir>/pr-<n> or <dir>/<sha>")
    a = ap.parse_args()

    if a.mode == "replay":
        if not a.keep:
            sys.exit("replay needs --keep <dir> from an earlier run")
        return replay(a)
    key = None if a.no_jev else os.environ.get("TYPESAFE_API_KEY")
    if not a.no_jev and not key:
        sys.exit("TYPESAFE_API_KEY not set (or pass --no-jev)")
    model = os.environ.get("JEV_MODEL") or p.JEV_MODEL_DEFAULT
    commits = history(a.ref)
    strong, fixes = ground_truth(commits)
    rows = []

    if a.mode == "prs":
        prs = json.loads(sh(
            "gh", "pr", "list", "--state", "merged", "--limit", str(a.limit), "--json",
            "number,title,body,author,labels,baseRefOid,headRefOid,mergedAt",
        ))  # fmt: skip
        for pr in prs:
            login = pr["author"]["login"].removeprefix("app/") + ("[bot]" if pr["author"]["login"].startswith("app/") else "")
            event = {"pull_request": {
                "number": pr["number"], "title": pr["title"], "body": pr["body"], "user": {"login": login},
                "labels": [{"name": lbl["name"]} for lbl in pr["labels"]], "head": {"sha": pr["headRefOid"]},
            }}  # fmt: skip
            try:
                r = run_item(event, pr["baseRefOid"], pr["headRefOid"], a.konflate_url, key, model, a.no_jev,
                             keep=a.keep / f"pr-{pr['number']}" if a.keep else None)
            except subprocess.CalledProcessError as e:
                print(f"#{pr['number']}: skipped ({e.stderr.strip()[:100]}); fetch refs/pull/*/head first", file=sys.stderr)
                continue
            shas = sh("git", "rev-list", f"{pr['baseRefOid']}..{pr['headRefOid']}").split()
            files = sh("git", "diff", "--name-only", pr["baseRefOid"], pr["headRefOid"]).split("\n")
            when = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
            rows.append(row(f"#{pr['number']}", pr["title"], r, label_item(set(shas), when, files, strong, fixes)))
            print(f"#{pr['number']}: {tag(r)}  {pr['title'][:70]}", file=sys.stderr)
    else:
        since = datetime.fromisoformat(a.since).astimezone() if a.since else None
        todo = [c for c in commits if not since or c["date"] >= since][-a.limit :]
        for c in todo:
            login = "renovate[bot]" if "renovate" in c["author"].lower() else os.environ.get("GITHUB_REPOSITORY_OWNER", "qnimbus")
            event = {"pull_request": {
                "number": 0, "title": c["subject"], "body": c["body"], "user": {"login": login},
                "labels": [], "head": {"sha": c["sha"]},
            }}  # fmt: skip
            try:
                r = run_item(event, c["sha"] + "^", c["sha"], None, key, model, a.no_jev, keep=a.keep / c["sha"][:7] if a.keep else None)
            except subprocess.CalledProcessError:
                continue  # root commit
            rows.append(row(c["sha"][:7], c["subject"], r, label_item({c["sha"]}, c["date"], c["files"], strong, fixes)))
            print(f"{c['sha'][:7]}: {tag(r)}  {c['subject'][:70]}", file=sys.stderr)

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    report(rows, baseline(a.baseline) if a.baseline else None)
    print(f"\nwrote {a.out}")


def replay(a) -> None:
    """Re-classify every kept item with the Jev answers its run recorded, and compare with what
    that run said. Questions the current policy asks that the run didn't are unanswered, so they
    show up as uncertain rather than being guessed."""
    commits = history(a.ref)
    strong, fixes = ground_truth(commits)
    merged = {}
    if any(d.name.startswith("pr-") for d in a.keep.iterdir()):
        prs = json.loads(sh("gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json", "number,mergedAt"))
        merged = {f"pr-{x['number']}": datetime.fromisoformat(x["mergedAt"].replace("Z", "+00:00")) for x in prs}
    by_sha = {c["sha"][:7]: c for c in commits}
    rows, before = [], {}
    for d in sorted(a.keep.iterdir(), key=lambda d: (len(d.name), d.name), reverse=True):
        old_path = d / "result.json"
        if not old_path.exists():
            continue
        old = json.loads(old_path.read_text())
        fixture = {n: {"answers": ans, "model": old["jev"].get("model")} for n, ans in old["jev"].get("answers", {}).items()}
        r = p.classify(d, key=None, model=old["jev"].get("model") or p.JEV_MODEL_DEFAULT, fixture=fixture)
        meta = json.loads((d / "meta.json").read_text())
        files = [f["path"] for f in json.loads((d / "files.json").read_text())]
        ident = f"#{meta['number']}" if d.name.startswith("pr-") else d.name
        if d.name in merged:
            shas = set(sh("git", "rev-list", f"{meta['merge_base']}..{meta['head_sha']}").split())
            truth = label_item(shas, merged[d.name], files, strong, fixes)
        elif d.name in by_sha:
            c = by_sha[d.name]
            truth = label_item({c["sha"]}, c["date"], c["files"], strong, fixes)
        else:
            truth = ""
        before[ident] = old.get("classification", old.get("verdict"))
        rows.append(row(ident, meta.get("title", ""), r, truth))
        print(f"{ident}: {before[ident]} → {tag(r)}  {meta.get('title', '')[:60]}", file=sys.stderr)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    report(rows, baseline(a.baseline) if a.baseline else before)
    print(f"\nwrote {a.out}")


def tag(r: dict) -> str:
    return f"{r['classification']}{' ?' if r['uncertain'] else ''} {r['rule']}"


def row(ident, title, r, truth) -> dict:
    """One CSV row. Findings are listed as code@certainty; `sources` is where the material
    findings' evidence came from (git, render, model, release_notes, invariants)."""
    evidence = {e["id"]: e for e in r["evidence"]}
    material = [f for f in r["findings"] if f["kind"] != "evidence" and f["certainty"] != "ruled_out"]
    gaps = [f for f in r["findings"] if f["kind"] == "evidence"]
    sources = sorted({evidence[e]["source"] for f in material for e in f["evidence"] if e in evidence})
    return {
        "id": ident,
        "title": title,
        "schema": r.get("schema", "pr-risk/v1"),
        "verdict": r["classification"],
        "uncertain": r["uncertain"],
        "rule": r["rule"],
        "status": r["status"],
        "truth": truth,
        "reach": r["dimensions"]["reach"],
        "stakes": " ".join(r["dimensions"]["stakes"]),
        "reversibility": r["dimensions"]["reversibility"],
        "findings": " ".join(sorted({f"{f['code']}@{f['certainty']}" for f in material})),
        "gaps": " ".join(sorted({f["code"] for f in gaps})),
        "context": " ".join(sorted({c["code"] for c in r["context"]})),
        "sources": " ".join(sources),
        "uncertain_surfaces": " ".join(s["id"] for s in r["surfaces"] if s["sufficiency"] == "insufficient"),
        "limited_surfaces": " ".join(s["id"] for s in r["surfaces"] if s["sufficiency"] == "limited"),
        "konflate": r["konflate"].get("state"),
        "input_tokens": sum((u or {}).get("input_tokens", 0) for u in r["jev"]["usage"].values()),
    }


def baseline(path: str) -> dict[str, str]:
    with open(path, newline="") as f:
        return {r["id"]: r["verdict"] for r in csv.DictReader(f)}


def report(rows, base: dict[str, str] | None = None) -> None:
    n = len(rows)
    if not n:
        print("no items")
        return
    truth = lambda r: r["truth"].split(":")[0] or "negative"  # noqa: E731
    grid = Counter((r["verdict"], truth(r)) for r in rows)
    print(f"\n{n} items · uncertain {sum(r['uncertain'] in (True, 'True') for r in rows)} · tokens {sum(int(r['input_tokens']) for r in rows)}")
    print(f"{'':10}{'negative':>10}{'weak':>8}{'strong':>8}")
    for v in p.LEVELS:
        print(f"{v:10}" + "".join(f"{grid[(v, t)]:>{w}}" for t, w in (("negative", 10), ("weak", 8), ("strong", 8))))
    positives = [r for r in rows if r["truth"]]
    caught = [r for r in positives if r["verdict"] != "safe"]
    false_safe = [r for r in positives if r["verdict"] == "safe"]
    flagged = [r for r in rows if r["verdict"] != "safe"]
    print(f"\nrecall (review+ on positives): {len(caught)}/{len(positives)}")
    print(f"precision (positives among review+): {len(caught)}/{len(flagged)}")
    print(f"labelled safe: {sum(r['verdict'] == 'safe' for r in rows)}/{n}")

    def table(title, key_fn, items=rows):
        counts: dict[str, Counter] = defaultdict(Counter)
        for r in items:
            for k in key_fn(r):
                counts[k][r["verdict"]] += 1
        if not counts:
            return
        print(f"\n{title}")
        for k, c in sorted(counts.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"  {k:44} " + "  ".join(f"{v} {c[v]:>3}" for v in p.LEVELS))

    table("verdict by reach", lambda r: [r["reach"]])
    table("verdict by finding source", lambda r: r["sources"].split() or ["(no finding)"])
    table("findings by reason code (verdict of the items they appear in)", lambda r: [f.split("@")[0] for f in r["findings"].split()])
    table("evidence gaps by code", lambda r: r["gaps"].split())
    for what, col in (("uncertain", "uncertain_surfaces"), ("limited evidence", "limited_surfaces")):
        unc = Counter(s for r in rows for s in r.get(col, "").split())
        if unc:
            print(f"\n{what} by surface")
            for s, c in unc.most_common(20):
                print(f"  {s:44} {c}")
    pos_codes = Counter(f.split("@")[0] for r in positives for f in r["findings"].split())
    if pos_codes:
        print("\nreason codes on positives: " + ", ".join(f"{k} {v}" for k, v in pos_codes.most_common(12)))
    for r in false_safe:
        print(f"FALSE SAFE {r['id']}: {r['title'][:70]} ({r['truth']})")
        print(f"    reach {r['reach']} · context [{r['context'] or '-'}] · gaps [{r['gaps'] or '-'}] · rule {r['rule']}")
    if base:
        moves = Counter((base[r["id"]], r["verdict"]) for r in rows if r["id"] in base)
        if moves:
            print("\nbaseline → this run")
            print(f"{'':10}" + "".join(f"{v:>8}" for v in p.LEVELS))
            for old in p.LEVELS:
                print(f"{old:10}" + "".join(f"{moves[(old, new)]:>8}" for new in p.LEVELS))
            changed = [r for r in rows if r["id"] in base and base[r["id"]] != r["verdict"]]
            for r in changed[:40]:
                print(f"  {r['id']}: {base[r['id']]} → {r['verdict']}  [{r['findings'] or r['gaps'] or '-'}]  {r['title'][:50]}")


if __name__ == "__main__":
    main()
