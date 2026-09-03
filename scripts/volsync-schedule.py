#!/usr/bin/env python3
"""Deterministically stagger VolSync's hourly backup schedule across apps.

VolSync's hourly ReplicationSource sync (kubernetes/components/volsync,
VOLSYNC_SCHEDULE:=0 * * * *) has no template-function support in Flux's
postBuild.substitute — every app's schedule has to be a literal string in its
ks.yaml. This script makes that literal deterministic (picking one is a
single command, not hand-guessing an unused number) and non-disruptive:
already-committed schedules are pinned and never reassigned, so deploying a
new app can only ever choose a free slot for *itself* — it never bumps an
already-running app's backup timing. See docs/ROADMAP.md's e1000e
packet-drops entry for why unstaggered hourly backups across every
ceph-block-backed app are a real synchronized-burst risk on the Ceph
public_network.

Usage:
  scripts/volsync-schedule.py compute <app-name>   # print the cron schedule for one app,
                                                    # resolved around every other app's
                                                    # already-committed schedule
  scripts/volsync-schedule.py check                # audit all volsync-component apps, exit 1 on issues

Algorithm: each app name hashes (CRC32, stable across runs/interpreters —
unlike Python's built-in hash()) to a candidate minute in [1-29, 31-59]
(0 and 30 excluded — the exact minutes any *unstaggered* job would also try
to use, so skipping them is part of avoiding clustering, not just avoiding
this component's own default). Apps that already have a committed
VOLSYNC_SCHEDULE are pinned at that value, full stop - never recomputed.
Apps without one (a brand-new app, or an explicit `compute` target) resolve
in a fixed order (sorted by name) against every pinned slot, linear-probing
forward on collision. `check` flags real collisions (two apps sharing a
literal schedule) and apps with no schedule at all; it never reports drift
for an app that already has one, since pinned values are authoritative by
definition.
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


def parse_minute(schedule):
    """Extract the leading minute field from a committed 'M * * * *' string, or None."""
    if not schedule:
        return None
    try:
        return int(schedule.split()[0])
    except (ValueError, IndexError):
        return None


def resolve_all(app_names, pinned=None):
    """Assign every name a distinct minute. Names already in `pinned` keep that
    exact value, untouched. Names without one resolve in a fixed order (sorted,
    so the result depends only on which names are unpinned, never on discovery
    order), hashing to a candidate minute and linear-probing forward past
    anything already taken - pinned or freshly assigned.

    Raises RuntimeError once all SAFE_RANGE (58) minutes are taken, rather than
    spinning forever - next_valid_minute only ever cycles through those same 58
    values, so an unbounded `while minute in taken` loop has no way to notice
    there's nothing left and just hangs."""
    pinned = pinned or {}
    taken = set(pinned.values())
    assignments = dict(pinned)
    for name in sorted(n for n in app_names if n not in pinned):
        if len(taken) >= SAFE_RANGE:
            raise RuntimeError(
                f"cannot assign {name!r} a schedule - all {SAFE_RANGE} staggered minutes "
                f"(1-29, 31-59) are already taken by other apps. Options: accept a same-minute "
                f"collision by hand, widen the scheme to sub-minute/multi-field staggering, or "
                f"split some apps onto a different sync interval."
            )
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
    apps = find_volsync_apps()
    # Resolve against every OTHER app's already-committed value, pinned as-is - this app's own
    # current value (if any) is deliberately excluded so it gets freshly resolved, same as a
    # brand-new app would.
    pinned = {
        name: m
        for name, (_, current) in apps.items()
        if name != app_name and (m := parse_minute(current)) is not None
    }
    minute = resolve_all({app_name} | apps.keys(), pinned)[app_name]
    print(f"{minute} * * * *")
    return 0


def cmd_check():
    apps = find_volsync_apps()
    if not apps:
        print("No apps found using the volsync component.")
        return 0

    pinned = {
        name: m
        for name, (_, current) in apps.items()
        if (m := parse_minute(current)) is not None
    }
    problems = []
    current_minutes = {}

    for name, (path, current) in sorted(apps.items()):
        if current is None:
            # Suggest a slot resolved around every OTHER app's pinned value - never touches them.
            suggested = resolve_all({name}, pinned)[name]
            status = "MISSING"
            print(f"{status:8} {name:16} {path:55} current=(unset)        suggested={f'{suggested} * * * *'!r}")
            problems.append(f"{name}: no VOLSYNC_SCHEDULE override — defaults to the "
                             f"0 * * * * clustering point ({path}); suggested {suggested} * * * *")
        else:
            print(f"{'OK':8} {name:16} {path:55} current={current}")
        current_minutes.setdefault(current or "0 * * * *", []).append(name)

    for schedule, names in sorted(current_minutes.items()):
        if len(names) > 1:
            problems.append(f"schedule {schedule!r}: currently shared by {', '.join(sorted(names))} "
                             f"— direct collision")

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
