#!/usr/bin/env python3
"""Parse Flux Kustomization dependsOn edges and report graph health.

Usage:
  scripts/depgraph.py              # print findings + update docs/CLUSTER.md
  scripts/depgraph.py --check      # print findings only, exit 1 on cycles/dangling refs
"""
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "CLUSTER.md"
BEGIN_MARKER = "<!-- BEGIN: DEPENDENCY-GRAPH-AUTO -->"
END_MARKER = "<!-- END: DEPENDENCY-GRAPH-AUTO -->"


def load_nodes():
    files = sorted(REPO_ROOT.glob("kubernetes/flux/**/ks.yaml")) + sorted(
        REPO_ROOT.glob("kubernetes/apps/**/ks.yaml")
    )
    nodes = {}
    for f in files:
        rel = f.relative_to(REPO_ROOT)
        for doc in yaml.safe_load_all(f.read_text()):
            if not doc or doc.get("kind") != "Kustomization":
                continue
            ns = doc.get("metadata", {}).get("namespace", "flux-system")
            name = doc["metadata"]["name"]
            key = f"{ns}/{name}"
            spec = doc.get("spec", {})
            deps_raw = spec.get("dependsOn", []) or []
            deps = [f"{d.get('namespace', ns)}/{d['name']}" for d in deps_raw]
            nodes[key] = {"deps": deps, "path": spec.get("path", ""), "file": str(rel)}
    return nodes


def find_dangling(nodes):
    out = []
    for key, info in nodes.items():
        for dep in info["deps"]:
            if dep not in nodes:
                out.append((key, dep))
    return out


def find_duplicates(nodes):
    out = []
    for key, info in nodes.items():
        deps = info["deps"]
        seen = set()
        for dep in deps:
            if dep in seen:
                out.append((key, dep))
            seen.add(dep)
    return out


def find_cycles(nodes):
    color = {}
    cycles = []

    def dfs(n, path):
        color[n] = 1
        path.append(n)
        for d in nodes.get(n, {}).get("deps", []):
            if d not in nodes:
                continue
            if color.get(d, 0) == 1:
                i = path.index(d)
                cycles.append(path[i:] + [d])
            elif color.get(d, 0) == 0:
                dfs(d, path)
        path.pop()
        color[n] = 2

    for n in nodes:
        if color.get(n, 0) == 0:
            dfs(n, [])
    return cycles


def find_redundant(nodes):
    """Edges A->B where B is also reachable from A via some other dependency
    of A. Not necessarily wrong (explicit deps aid clarity/health-gating) —
    flagged for human review, not auto-removed."""
    redundant = []
    for key, info in nodes.items():
        deps = info["deps"]
        for dep in deps:
            if dep not in nodes:
                continue
            others = [d for d in deps if d != dep]
            seen = set()
            stack = list(others)
            found = False
            while stack:
                n = stack.pop()
                if n == dep:
                    found = True
                    break
                if n in seen or n not in nodes:
                    continue
                seen.add(n)
                stack.extend(nodes[n]["deps"])
            if found:
                redundant.append((key, dep))
    return redundant


def group_for(file_rel):
    parts = Path(file_rel).parts
    if parts[:2] == ("kubernetes", "apps"):
        return parts[2]
    return "flux-bootstrap"


def sanitize(key):
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def build_groups(nodes):
    groups = {}
    for key, info in nodes.items():
        groups.setdefault(group_for(info["file"]), []).append(key)
    group_of = {key: group_for(info["file"]) for key, info in nodes.items()}
    return groups, group_of


def render_overview(nodes):
    """Collapsed graph: one node per app-directory group, edges deduplicated
    and self-loops dropped. This is the readable "what depends on what at a
    system level" view — individual Kustomizations are in the per-group
    detail diagrams instead."""
    groups, group_of = build_groups(nodes)
    edges = set()
    for key, info in nodes.items():
        for dep in info["deps"]:
            if dep not in nodes:
                continue
            sg, dg = group_of[key], group_of[dep]
            if sg != dg:
                edges.add((sg, dg))

    lines = ["```mermaid", "flowchart TD"]
    for g in sorted(groups):
        lines.append(f'  {sanitize(g)}["{g} ({len(groups[g])})"]')
    for sg, dg in sorted(edges):
        lines.append(f"  {sanitize(sg)} --> {sanitize(dg)}")
    lines.append("```")
    return "\n".join(lines)


def render_group_detail(nodes, group, group_of):
    """Per-group diagram: full detail for this group's own Kustomizations,
    plus rounded "external" stub nodes for any dependency outside the group
    (not that dependency's own neighbors) so the diagram stays self-contained
    and small."""
    members = sorted(k for k, info in nodes.items() if group_of[k] == group)
    member_set = set(members)
    external = {}
    edges = []
    for key in members:
        for dep in nodes[key]["deps"]:
            if dep not in nodes:
                continue
            edges.append((key, dep))
            if dep not in member_set:
                external[dep] = group_of[dep]

    lines = ["```mermaid", "flowchart TD"]
    for key in members:
        label = key.split("/", 1)[1]
        lines.append(f'  {sanitize(key)}["{label}"]')
    for dep, dep_group in sorted(external.items()):
        label = dep.split("/", 1)[1]
        lines.append(f'  {sanitize(dep)}(("{label} · {dep_group}")):::external')
    for key, dep in sorted(edges):
        lines.append(f"  {sanitize(key)} --> {sanitize(dep)}")
    if external:
        lines.append("  classDef external fill:#eee,stroke:#999,stroke-dasharray: 3 3")
    lines.append("```")
    return "\n".join(lines)


def render_graph_doc(nodes):
    groups, group_of = build_groups(nodes)
    parts = [
        "**Overview** — collapsed to one node per app directory; arrow means "
        "\"depends on\". Expand a group below for the individual Kustomizations "
        "and their external dependencies.\n",
        render_overview(nodes),
        "",
    ]
    for group in sorted(groups):
        parts.append(f"<details>\n<summary>{group} ({len(groups[group])})</summary>\n")
        parts.append(render_group_detail(nodes, group, group_of))
        parts.append("\n</details>\n")
    return "\n".join(parts)


def update_doc(mermaid):
    text = DOC_PATH.read_text()
    if BEGIN_MARKER not in text or END_MARKER not in text:
        print(f"WARNING: markers not found in {DOC_PATH}, skipping doc update", file=sys.stderr)
        return False
    pre, rest = text.split(BEGIN_MARKER, 1)
    _, post = rest.split(END_MARKER, 1)
    new_text = f"{pre}{BEGIN_MARKER}\n{mermaid}\n{END_MARKER}{post}"
    if new_text == text:
        return False
    DOC_PATH.write_text(new_text)
    return True


def main():
    check_only = "--check" in sys.argv
    nodes = load_nodes()

    dangling = find_dangling(nodes)
    duplicates = find_duplicates(nodes)
    cycles = find_cycles(nodes)
    redundant = find_redundant(nodes)

    print(f"Kustomizations parsed: {len(nodes)}")
    for key, dep in dangling:
        print(f"DANGLING: {key} -> {dep} (target not found)")
    for key, dep in duplicates:
        print(f"DUPLICATE: {key} -> {dep} (listed more than once)")
    for cycle in cycles:
        print("CYCLE: " + " -> ".join(cycle))
    for key, dep in redundant:
        print(f"REDUNDANT?: {key} -> {dep} (also reachable via another path — review, not auto-fixed)")

    print(
        f"\nSummary: {len(dangling)} dangling, {len(duplicates)} duplicate, "
        f"{len(cycles)} cycle(s), {len(redundant)} possibly-redundant edge(s)"
    )

    if not check_only:
        mermaid = render_graph_doc(nodes)
        if update_doc(mermaid):
            print(f"\nUpdated {DOC_PATH.relative_to(REPO_ROOT)}")
        else:
            print(f"\n{DOC_PATH.relative_to(REPO_ROOT)} already up to date")

    if dangling or cycles:
        sys.exit(1)


if __name__ == "__main__":
    main()
