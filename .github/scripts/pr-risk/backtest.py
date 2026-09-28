#!/usr/bin/env python3
"""Backtest pr_risk.py over history, to tune THRESHOLDS before labels are switched on.

Runs locally (needs `gh` and git history; Jev needs TYPESAFE_API_KEY, else --no-jev):

    git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'   # merged PR heads
    python3 .github/scripts/pr-risk/backtest.py prs --konflate-url https://konflate.cluster.vwn.io
    python3 .github/scripts/pr-risk/backtest.py commits --since 2026-06-01

Ground truth comes from git: an item is a strong positive when one of its commits was later
reverted (`This reverts commit <sha>`, or a `revert(...)` / `fix(...): revert` commit touching the
same files within 14 days), and a weak positive when a non-Renovate `fix(...)` commit touched the
same files within 48 hours. Commits mode has no Konflate renders, so it judges without them. Everything else counts as negative. What matters most is false-safe: a positive
labelled `safe`.
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
from collections import Counter
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


def app_dirs(files) -> set[str]:
    return {"/".join(f.split("/")[:4]) for f in files if f.startswith("kubernetes/apps/") and f.count("/") >= 4}


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
    fixes = [c for c in commits if re.match(r"^fix(\(|:)", c["subject"]) and "renovate" not in c["author"].lower()]
    return strong, fixes


def label_item(shas, when, files, strong, fixes) -> str:
    for s in shas:
        if s in strong:
            return "strong: " + strong[s]
    files = set(files)
    for f in fixes:
        if when < f["date"] <= when + timedelta(hours=48) and files & f["files"] and f["sha"] not in shas:
            return f"weak: fix {f['sha'][:7]}"
    return ""


def run_item(event, base, head, konflate_url, key, model) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        p.collect(event, base, head, out, konflate_url, 0)
        if not konflate_url:  # no render exists for history: judge the rest on its own
            (out / "konflate.json").write_text(json.dumps({"state": "ignored", "summary": {"reason": "backtest"}}))
        return p.classify(out, key=key, model=model)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["prs", "commits"])
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--since", help="commits mode: only commits after this date (YYYY-MM-DD)")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--konflate-url", help="prs mode: reuse Konflate renders that still match the merged head")
    ap.add_argument("--no-jev", action="store_true", help="deterministic signals only")
    ap.add_argument("--out", default="pr-risk-backtest.csv")
    a = ap.parse_args()

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
                r = run_item(event, pr["baseRefOid"], pr["headRefOid"], a.konflate_url, key, model)
            except subprocess.CalledProcessError as e:
                print(f"#{pr['number']}: skipped ({e.stderr.strip()[:100]}); fetch refs/pull/*/head first", file=sys.stderr)
                continue
            shas = sh("git", "rev-list", f"{pr['baseRefOid']}..{pr['headRefOid']}").split()
            files = sh("git", "diff", "--name-only", pr["baseRefOid"], pr["headRefOid"]).split("\n")
            when = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
            rows.append(row(f"#{pr['number']}", pr["title"], r, label_item(set(shas), when, files, strong, fixes)))
            print(f"#{pr['number']}: {r['verdict']}{' ?' if r['uncertain'] else ''}  {pr['title'][:70]}", file=sys.stderr)
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
                r = run_item(event, c["sha"] + "^", c["sha"], None, key, model)
            except subprocess.CalledProcessError:
                continue  # root commit
            rows.append(row(c["sha"][:7], c["subject"], r, label_item({c["sha"]}, c["date"], c["files"], strong, fixes)))
            print(f"{c['sha'][:7]}: {r['verdict']}{' ?' if r['uncertain'] else ''}  {c['subject'][:70]}", file=sys.stderr)

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    report(rows)
    print(f"\nwrote {a.out}")


def row(ident, title, r, truth) -> dict:
    return {
        "id": ident,
        "title": title,
        "verdict": r["verdict"],
        "uncertain": r["uncertain"],
        "truth": truth,
        "change_kind": r.get("change_kind"),
        "blast_radius": r.get("blast_radius"),
        "konflate": r["konflate"].get("state"),
        "signals": " | ".join(f"{s['source']}:{s['level']}:{s['reason']}" for s in r["signals"] if s["level"] or s["uncertain"]),
        "input_tokens": sum((u or {}).get("input_tokens", 0) for u in r["jev"]["usage"].values()),
    }


def report(rows) -> None:
    n = len(rows)
    if not n:
        print("no items")
        return
    grid = Counter((r["verdict"], r["truth"].split(":")[0] or "negative") for r in rows)
    print(f"\n{n} items · uncertain {sum(r['uncertain'] for r in rows)} · tokens {sum(r['input_tokens'] for r in rows)}")
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
    for r in false_safe:
        print(f"FALSE SAFE {r['id']}: {r['title'][:70]} ({r['truth']})")


if __name__ == "__main__":
    main()
