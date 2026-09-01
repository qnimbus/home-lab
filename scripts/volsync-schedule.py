#!/usr/bin/env python3
"""Deterministically stagger VolSync's hourly backup schedule across apps.

VolSync's hourly ReplicationSource sync (kubernetes/components/volsync,
VOLSYNC_SCHEDULE:=0 * * * *) has no template-function support in Flux's
postBuild.substitute — every app's schedule has to be a literal string in its
ks.yaml. This script makes that literal deterministic (the same set of app
names always resolves to the same assignment, with collisions resolved
automatically) and scalable (adding an app is one command, not picking an
unused number by hand), rather than hand-assigned. See docs/ROADMAP.md's
e1000e packet-drops entry for why unstaggered hourly backups across every
ceph-block-backed app are a real synchronized-burst risk on the Ceph
public_network.

Usage:
  scripts/volsync-schedule.py compute <app-name>   # print the cron schedule for one app
                                                    # (existing apps + this one, resolved together)
  scripts/volsync-schedule.py check                # audit all volsync-component apps, exit 1 on issues

Algorithm: each app name hashes (CRC32, stable across runs/interpreters —
unlike Python's built-in hash()) to a candidate minute in [1-29, 31-59]
(0 and 30 excluded — the exact minutes any *unstaggered* job would also try
to use, so skipping them is part of avoiding clustering, not just avoiding
this component's own default). Apps are then resolved in a fixed order
(sorted by name, so the outcome never depends on filesystem iteration order)
and any collision is pushed to the next free valid minute. The same set of
app names always produces the same assignment; adding a new name can only
ever affect apps that sort after it, and `check` will flag any that shift.
"""
import sys
import zlib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_REF = "components/volsync"
SAFE_RANGE = 58  # minutes 1-29, 31-59 (0 and 30 excluded)


def minute_for(app_name):
    """Naive deterministic minute-of-hour for a name, before collision resolution."""
    raw = zlib.crc32(app_name.encode()) % SAFE_RANGE
    return raw + 1 if raw < 29 else raw + 2


def next_valid_minute(m):
    m += 1
    if m > 59:
        m = 1
    if m == 30:
        m = 31
    return m


def resolve_all(app_names):
    """Deterministically assign every name a distinct minute, resolving
    collisions by linear probing. Fixed (sorted) processing order means the
    result depends only on the *set* of names, never on discovery order."""
    taken = set()
    assignments = {}
    for name in sorted(app_names):
        minute = minute_for(name)
        while minute in taken:
            minute = next_valid_minute(minute)
        taken.add(minute)
        assignments[name] = minute
    return assignments


def find_volsync_apps():
    """Return {app_name: (ks_yaml_path, current_VOLSYNC_SCHEDULE_or_None)}."""
    apps = {}
    for f in sorted(REPO_ROOT.glob("kubernetes/apps/**/ks.yaml")):
        rel = f.relative_to(REPO_ROOT)
        for doc in yaml.safe_load_all(f.read_text()):
            if not doc or doc.get("kind") != "Kustomization":
                continue
            spec = doc.get("spec", {})
            components = spec.get("components", []) or []
            if not any(c.endswith(COMPONENT_REF) for c in components):
                continue
            name = doc["metadata"]["name"]
            substitute = spec.get("postBuild", {}).get("substitute", {}) or {}
            apps[name] = (str(rel), substitute.get("VOLSYNC_SCHEDULE"))
    return apps


def cmd_compute(app_name):
    existing = set(find_volsync_apps().keys())
    existing.add(app_name)
    minute = resolve_all(existing)[app_name]
    print(f"{minute} * * * *")
    return 0


def cmd_check():
    apps = find_volsync_apps()
    if not apps:
        print("No apps found using the volsync component.")
        return 0

    resolved = resolve_all(apps.keys())
    problems = []
    current_minutes = {}

    for name, (path, current) in sorted(apps.items()):
        expected = f"{resolved[name]} * * * *"
        if current is None:
            status = "MISSING"
        elif current == expected:
            status = "OK"
        else:
            status = "DIVERGED"
        print(f"{status:8} {name:16} {path:55} current={current or '(unset)':<14} expected={expected!r}")
        if status == "MISSING":
            problems.append(f"{name}: no VOLSYNC_SCHEDULE override — defaults to the "
                             f"0 * * * * clustering point ({path})")
        elif status == "DIVERGED":
            problems.append(f"{name}: current schedule {current!r} != resolved {expected!r} "
                             f"({path}) — either update it or, if intentional, ignore")
        current_minutes.setdefault(current or "0 * * * *", []).append(name)

    for schedule, names in sorted(current_minutes.items()):
        if len(names) > 1:
            problems.append(f"schedule {schedule!r}: currently shared by {', '.join(sorted(names))} "
                             f"— direct collision, independent of the diverged check above")

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("All volsync-component apps have distinct, deterministic schedules.")
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "compute":
        return cmd_compute(sys.argv[2])
    if len(sys.argv) == 2 and sys.argv[1] == "check":
        return cmd_check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
