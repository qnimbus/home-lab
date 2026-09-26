#!/usr/bin/env python3
"""List or strip comments in the YAML files under a directory.

Usage:
  comments.py list  <dir> [--include-app-config]   # print comments, grouped per file
  comments.py strip <dir> [--include-app-config]   # remove strippable comments in place

Kept (never stripped, not listed):
  - functional directives: `# yaml-language-server:`, `# renovate:`, `# yamllint ...`
  - `*.sops.yaml` files (the whole file is skipped: its MAC covers the content)
  - app config: files fed to a configMapGenerator/secretGenerator, except Helm
    values (`values.yaml`). They're the app's own format, not manifests; pass
    --include-app-config to take them in too.

Listed but never stripped, tagged [embedded]:
  - `#` lines inside block scalars (`key: |`, `patch: |-`, ...). These are part
    of a string: a config file, a script, or an inline kustomize patch. Decide
    per case and edit them by hand.
"""

import re
import signal
import subprocess
import sys
from pathlib import Path

KEEP = re.compile(r"#\s*(yaml-language-server:|renovate:|yamllint\s)")
BLOCK_HEADER = re.compile(r"[|>][-+]?[0-9]?[-+]?$")


def inline_comment_start(line: str) -> int:
    """Index of a comment `#` outside quotes, or -1."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'" and (i == 0 or line[i - 1] in " :-[{,"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return i
    return -1


def scan(path: Path):
    """Yield (lineno, kind, text) with kind in {full, inline, embedded, keep}."""
    block_indent = None
    for n, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if block_indent is not None:
            if not stripped or indent > block_indent:
                if stripped.startswith("#"):
                    yield n, "embedded", stripped
                continue
            block_indent = None
        pos = inline_comment_start(line)
        code = line[:pos].rstrip() if pos >= 0 else line.rstrip()
        if pos >= 0:
            text = line[pos:]
            if KEEP.match(text):
                yield n, "keep", text
            else:
                yield n, "full" if not code.strip() else "inline", text
        if BLOCK_HEADER.search(code) and (": " in code or code.lstrip().startswith("- ")):
            block_indent = indent


def app_config(root: Path) -> set[Path]:
    """Generator input files under root, minus Helm values files."""
    found = set()
    for ks in root.rglob("kustomization.yaml"):
        out = subprocess.run(
            ["yq", ".configMapGenerator[].files[], .secretGenerator[].files[]", str(ks)],
            capture_output=True, text=True, check=True,
        ).stdout
        for entry in out.split():
            path = (ks.parent / entry.split("=")[-1]).resolve()
            if path.name != "values.yaml":
                found.add(path)
    return found


def files(root: Path, include_app_config: bool):
    skip = set() if include_app_config else app_config(root)
    for p in sorted(root.rglob("*")):
        if p.suffix not in (".yaml", ".yml") or p.name.endswith(".sops.yaml"):
            continue
        if p.resolve() in skip:
            print(f"skipped (app config): {p}", file=sys.stderr)
            continue
        yield p


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    args = [a for a in sys.argv[1:] if a != "--include-app-config"]
    if len(args) != 2 or args[0] not in ("list", "strip"):
        sys.exit(__doc__)
    mode, root = args[0], Path(args[1])
    for path in files(root, "--include-app-config" in sys.argv):
        found = [c for c in scan(path) if c[1] != "keep"]
        if not found:
            continue
        if mode == "list":
            print(f"== {path}")
            for n, kind, text in found:
                print(f"{n:5}  [{kind}] {text}")
            continue
        drop = {n for n, kind, _ in found if kind == "full"}
        trim = {n for n, kind, _ in found if kind == "inline"}
        out = []
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if n in drop:
                continue
            if n in trim:
                line = line[: inline_comment_start(line)].rstrip()
            out.append(line)
        path.write_text("\n".join(out) + "\n")
        embedded = sum(1 for c in found if c[1] == "embedded")
        print(f"{path}: -{len(drop)} lines, {len(trim)} trimmed, {embedded} embedded left")


if __name__ == "__main__":
    main()
