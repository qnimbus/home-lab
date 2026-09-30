"""Deterministic rules: git facts, Konflate's structured signals, and what the diff and the render
say, turned into typed findings, evidence and context. No model is involved here.

Each rule is registered with the codes it can produce and the source it reads. A rule may only
emit its declared codes, which keeps the registry an honest index of what can fire and why.

Standard library only: YAML is read line by line, with each changed line's enclosing keys worked
out from indentation (`parse_diff`). That is approximate by design, and every rule built on it
reports what it saw so a reviewer can check it.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from surfaces import surface_id
from taxonomy import Assessment, Surface, matches, max_reach

# ── Diff model ───────────────────────────────────────────────────────────────────────────────

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@ ?(.*)$")
KEY = re.compile(r"""^(\s*)(-\s+)?("[^"]+"|'[^']+'|[^\s:#'"\-][^:#]*?|-[^\s:#][^:#]*?)\s*:(?:\s+(.*?))?\s*$""")
DASH = re.compile(r"^(\s*)-\s+(.*?)\s*$")
COMMENT = re.compile(r"(^|\s)#.*$")
TAG = re.compile(r"<[^>]+>")


@dataclass
class Line:
    sign: str  # "+", "-" or " "
    text: str
    keys: tuple[str, ...] = ()  # enclosing keys, outermost first
    key: str | None = None  # this line's own key
    value: str | None = None  # this line's value, or a list item's scalar

    @property
    def changed(self) -> bool:
        return self.sign in "+-"

    @property
    def blank(self) -> bool:
        s = self.text.strip()
        return not s or s.startswith("#")

    def within(self, *names: str) -> bool:
        return any(n in self.keys for n in names)


@dataclass
class Hunk:
    path: str  # a file path, or a rendered resource's title
    lines: list[Line] = field(default_factory=list)
    new_file: bool = False
    kind: str | None = None  # rendered resource kind
    status: str | None = None  # rendered resource status
    parent: str | None = None  # rendered resource's Flux parent

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = COMMENT.sub("", v).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def annotate(lines: list[Line], header: str = "") -> None:
    """Fill each line's enclosing keys, one stack per side of the diff."""
    base: list[tuple[int, str, bool]] = []
    m = KEY.match(header) if header else None
    if m and not m.group(2):
        base = [(len(m.group(1)), _clean(m.group(3)) or "", False)]
    stacks = {"+": list(base), "-": list(base)}
    for ln in lines:
        if ln.blank:
            continue
        indent = len(ln.text) - len(ln.text.lstrip())
        m, dash = KEY.match(ln.text), DASH.match(ln.text)
        is_dash = bool(dash)
        sides = ("+", "-") if ln.sign == " " else (ln.sign,)
        for side in sides:
            st = stacks[side]
            while st and (st[-1][0] > indent or (st[-1][0] == indent and (not is_dash or st[-1][2]))):
                st.pop()
        ln.keys = tuple(k for _, k, _ in stacks[sides[0]])
        if m:
            ln.key, ln.value = _clean(m.group(3)), _clean(m.group(4))
            own = indent + 2 if m.group(2) else indent
            for side in sides:
                stacks[side].append((own, ln.key, bool(m.group(2))))
        elif dash:
            ln.value = _clean(dash.group(2))


def parse_diff(diff: str) -> dict[str, list[Hunk]]:
    """A unified git diff, per file, with keys annotated."""
    out: dict[str, list[Hunk]] = {}
    for part in re.split(r"(?m)^(?=diff --git )", diff or ""):
        if not part.startswith("diff --git "):
            continue
        head = part.splitlines()[0]
        m = re.match(r"diff --git a/(.*?) b/(.*)", head)
        path = m.group(2) if m else "?"
        new_file = "\nnew file mode" in part.split("@@", 1)[0]
        hunks: list[Hunk] = []
        cur: Hunk | None = None
        header = ""
        for raw in part.splitlines()[1:]:
            hm = HUNK.match(raw)
            if hm:
                if cur:
                    annotate(cur.lines, header)
                header = hm.group(1)
                cur = Hunk(path, new_file=new_file)
                hunks.append(cur)
                continue
            if cur is None or raw.startswith("\\"):
                continue
            sign = raw[:1] if raw[:1] in "+- " else " "
            cur.lines.append(Line(sign, raw[1:]))
        if cur:
            annotate(cur.lines, header)
        out[path] = hunks
    return out


def row_text(u: dict) -> str:
    return html.unescape(TAG.sub("", u.get("html", "")))


def render_hunks(kdiff: dict | None) -> list[Hunk]:
    """Konflate's rendered resources as hunks; folded rows are kept as context."""
    out = []
    for r in ((kdiff or {}).get("diff") or {}).get("resources") or []:
        cur = Hunk(r.get("title") or r.get("kind") or "?", kind=r.get("kind"), status=r.get("status"), parent=r.get("parent"))
        for u in r.get("unified") or []:
            if u.get("hunk"):
                if cur.lines:
                    annotate(cur.lines)
                    out.append(cur)
                    cur = Hunk(cur.path, kind=cur.kind, status=cur.status, parent=cur.parent)
                continue
            cur.lines.append(Line({"add": "+", "del": "-"}.get(u.get("kind"), " "), row_text(u)))
        annotate(cur.lines)
        out.append(cur)
    return out


@dataclass
class Change:
    path: str
    keys: tuple[str, ...]
    key: str
    old: str | None
    new: str | None


def changes(hunk: Hunk) -> list[Change]:
    """Removed and added values of the same key at the same place, paired in order; an unpaired
    side has None."""
    removed: dict[tuple, list[str | None]] = {}
    added: dict[tuple, list[str | None]] = {}
    order: list[tuple] = []
    for ln in hunk.lines:
        if not ln.changed or ln.key is None:
            continue
        k = (ln.keys, ln.key)
        if k not in order:
            order.append(k)
        (removed if ln.sign == "-" else added).setdefault(k, []).append(ln.value)
    out = []
    for k in order:
        olds, news = removed.get(k, []), added.get(k, [])
        for i in range(max(len(olds), len(news))):
            old = olds[i] if i < len(olds) else None
            new = news[i] if i < len(news) else None
            if old != new:
                out.append(Change(hunk.path, k[0], k[1], old, new))
    return out


def moved(hunks: list[Hunk]) -> set[str]:
    """Lines removed and added unchanged somewhere in the same file: a move, not a change."""
    minus = {ln.text.strip() for h in hunks for ln in h.lines if ln.sign == "-"}
    plus = {ln.text.strip() for h in hunks for ln in h.lines if ln.sign == "+"}
    return minus & plus


YAMLISH = re.compile(r"\.(ya?ml|json5?)(\.j2|\.tpl)?$")
DEPLOYED_PREFIX = ("kubernetes/", "docker/", "bootstrap/", "truenas/", "talos/")

UNITS = {"": 1, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}


def qty(v: str | None) -> float | None:
    """A Kubernetes quantity (or a plain number, or a percentage), or None."""
    if v is None:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zA-Z]{0,2}|%)", v.strip().strip("\"'"))
    if not m or (m.group(2) not in UNITS and m.group(2) != "%"):
        return None
    return float(m.group(1)) * (1 if m.group(2) == "%" else UNITS[m.group(2)])


# ── Facts: the bundle, parsed once ───────────────────────────────────────────────────────────


@dataclass
class Facts:
    meta: dict
    files: list[dict]
    overlap: list[str]
    conflict: dict
    konflate: dict
    kdiff: dict | None
    diff: str
    base_diff: str
    config: dict
    notes: dict
    components: list[dict]
    secrets: list[dict]
    surfaces: list[Surface]
    hunks: dict[str, list[Hunk]] = field(default_factory=dict)
    rendered: list[Hunk] = field(default_factory=list)
    presence: dict[str, set[str]] = field(default_factory=dict)  # what semantic questions are about

    def __post_init__(self):
        self.hunks = parse_diff(self.diff)
        self.rendered = render_hunks(self.kdiff) if self.konflate.get("state") == "fresh" else []
        self.by_id = {s.id: s for s in self.surfaces}

    def sid(self, path: str) -> str:
        return surface_id(path)

    def structural(self, h: "Hunk") -> bool:
        """Whether YAML-structure rules apply: a rendered resource, or a YAML/JSON file that
        deploys or configures something. Not Markdown, agent docs or scripts, whose YAML is an
        example (e45cdf0: `name: cluster-admin` in docs/ROADMAP.md)."""
        if h.kind is not None:
            return True
        s = self.by_id.get(self.sid(h.path))
        return bool(YAMLISH.search(h.path)) and s is not None and s.reach != "none" and s.id != "agents"

    def file_status(self, path: str) -> str:
        return next((f["status"] for f in self.files if f["path"] == path), "M")

    @property
    def rendered_surfaces(self) -> list[str]:
        return [s.id for s in self.surfaces if s.rendered]

    @property
    def model_surfaces(self) -> list[str]:
        return [s.id for s in self.surfaces if s.model_required]

    def resource_sid(self, ref: str | None) -> str | None:
        """The surface a rendered resource (`Kind ns/name`) belongs to, when it can be told."""
        rendered = self.rendered_surfaces
        m = re.match(r"^\S+ ([^/\s]+)/(\S+)$", ref or "")
        if m:
            ns, name = m.groups()
            if f"{ns}/{name}" in self.by_id:
                return f"{ns}/{name}"
            near = [s for s in rendered if s.startswith(ns + "/") and (name.startswith(s.split("/", 1)[1]) or s.split("/", 1)[1].startswith(name))]
            if near:
                return near[0]
            in_ns = [s for s in rendered if s.startswith(ns + "/") or s == f"namespace:{ns}"]
            if len(in_ns) == 1:
                return in_ns[0]
        return rendered[0] if len(rendered) == 1 else None

    def hunk_sid(self, h: Hunk) -> str | None:
        if h.kind is None:
            return self.sid(h.path)
        return self.resource_sid(h.parent) or self.resource_sid(h.path)

    def hunk_sid_of(self, name: str) -> str | None:
        """A file path's or a rendered resource title's surface."""
        if name in self.hunks or " " not in name:
            return self.sid(name)
        h = next((h for h in self.rendered if h.path == name), None)
        return self.hunk_sid(h) if h else self.resource_sid(name)

    def widest(self, sids) -> str | None:
        """The widest-reach surface among `sids`, to hang a PR-level finding on."""
        known = [s for s in sids if s in self.by_id]
        if not known:
            return None
        top = max_reach(self.by_id[s].reach for s in known)
        return next(s for s in known if self.by_id[s].reach == top)

    def raw(self):
        """(path, hunk) for every file, deleted ones included."""
        for path, hunks in self.hunks.items():
            for h in hunks:
                yield path, h

    def all_hunks(self):
        yield from (h for _, h in self.raw())
        yield from self.rendered


# ── Registry ─────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    name: str
    source: str  # git | konflate | release_notes | repo
    codes: tuple[str, ...]  # what it may emit (findings, gaps and context)
    applies: Callable[[Facts], bool]
    evaluate: Callable[[Facts, Assessment], None]


RULES: list[Rule] = []


def rule(name: str, source: str, codes, applies: Callable[[Facts], bool] = lambda f: True):
    def deco(fn):
        RULES.append(Rule(name, source, tuple(codes), applies, fn))
        return fn

    return deco


class Scoped:
    """An Assessment view that refuses codes its rule didn't declare."""

    def __init__(self, inner: Assessment, allowed: tuple[str, ...]):
        self._inner, self._allowed = inner, allowed

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def find(self, code, *args, **kw):
        assert code in self._allowed, f"{code} not declared by its rule"
        return self._inner.find(code, *args, **kw)

    def gap(self, code, *args, **kw):
        assert code in self._allowed, f"{code} not declared by its rule"
        return self._inner.gap(code, *args, **kw)

    def note(self, code, *args, **kw):
        assert code in self._allowed, f"{code} not declared by its rule"
        return self._inner.note(code, *args, **kw)


def evaluate(f: Facts, a: Assessment) -> list[str]:
    """Run every applicable rule; returns the names that ran."""
    ran = []
    for r in RULES:
        if r.applies(f):
            r.evaluate(f, Scoped(a, r.codes))
            ran.append(r.name)
    return ran


def short(items, n=5) -> str:
    items = list(items)
    return ", ".join(items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")


# ── Git ──────────────────────────────────────────────────────────────────────────────────────


@rule("git.merge", "git", ["integrity.merge_conflict", "ev.merge_result_unknown"])
def git_merge(f: Facts, a: Assessment) -> None:
    """A conflict is a known-bad state; failing to find out is an unknown one."""
    all_sids = [s.id for s in f.surfaces]
    state = f.conflict.get("conflict")
    if state is True:
        files = f.conflict.get("files") or []
        eid = a.record("git", "git merge-tree reports conflicts in " + (short(files) or "?"))
        for sid in all_sids:
            a.set_quality(sid, "git", "sufficient")
        a.find("integrity.merge_conflict", "established", f.widest([f.sid(p) for p in files]) or f.widest(all_sids), (eid,),
               "Conflicts with the base branch in " + (short(files) or "?") + ": it can't merge as-is.")  # fmt: skip
    elif state is None:
        a.gap("ev.merge_result_unknown", "git", all_sids, "insufficient", "The textual merge with the base branch couldn't be computed.")
    else:
        for sid in all_sids:
            a.record("git", "No textual conflict with the base branch.", sid)
            a.set_quality(sid, "git", "sufficient")


@rule("git.overlap", "git", ["ctx.base_overlap"], lambda f: bool(f.overlap))
def git_overlap(f: Facts, a: Assessment) -> None:
    detail = f"{len(f.overlap)} file(s) also changed on the base branch: {short(f.overlap)}"
    if f.meta.get("commits", 1) > 1:
        detail += f"; {f.meta['commits']} commits, so a rebase may need per-commit resolution"
    a.note("ctx.base_overlap", detail)


IMAGE_FILE = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico)$", re.I)


@rule("git.opaque", "git", ["ev.opaque_content"])
def git_opaque(f: Facts, a: Assessment) -> None:
    for x in f.files:
        if x.get("binary") and not IMAGE_FILE.search(x["path"]):
            a.gap("ev.opaque_content", "git", [f.sid(x["path"])], "insufficient",
                  f"`{x['path']}` is binary: nothing here can read what it changes.")  # fmt: skip


DEPLOYED = ["kubernetes/apps/**", "kubernetes/components/**", "docker/nas/**"]


@rule("git.removals", "git", ["lifecycle.resource_removed", "lifecycle.release_reinstalled", "data.volume_identity_changed"])
def git_removals(f: Facts, a: Assessment) -> None:
    for x in f.files:
        path = x["path"]
        if x["status"] == "D" and matches(path, DEPLOYED) and not path.endswith(".md"):
            eid = a.record("git", f"deletes {path}", f.sid(path))
            a.find("lifecycle.resource_removed", "possible", f.sid(path), (eid,), f"Deletes deployed file `{path}`.")
        old = x.get("old_path")
        if x["status"] == "R" and old:
            a_old, a_new = re.match(r"kubernetes/apps/[^/]+/[^/]+/", old), re.match(r"kubernetes/apps/[^/]+/[^/]+/", path)
            if a_old and a_new and a_old.group(0) != a_new.group(0):
                sid = f.sid(path)
                eid = a.record("git", f"moves {a_old.group(0)} to {a_new.group(0)}", sid)
                a.find("lifecycle.release_reinstalled", "probable", sid, (eid,),
                       f"Moves `{a_old.group(0)}` to `{a_new.group(0)}`: Flux deletes the old Kustomization/HelmRelease and installs "
                       "the new one, which uninstalls the release (and any templated CRDs without `keep`).")  # fmt: skip
                if "data" in f.by_id[sid].stakes:
                    a.find("data.volume_identity_changed", "possible", sid, (eid,),
                           "The app moves, and its volumes and database are named after it: check they follow (kopiur claim, CNPG cluster).")  # fmt: skip


@rule("git.size", "git", ["ctx.large_changeset"])
def git_size(f: Facts, a: Assessment) -> None:
    lines = sum(x.get("additions", 0) + x.get("deletions", 0) for x in f.files)
    if len(f.files) > 40 or lines > 2000:
        a.note("ctx.large_changeset", f"{len(f.files)} files, {lines} lines")


# ── Flux ─────────────────────────────────────────────────────────────────────────────────────

FLUX_KEYS = {
    "prune": "recon.prune_changed",
    "suspend": "recon.suspension_changed",
    "wait": "recon.health_gate_changed",
    "healthChecks": "recon.health_gate_changed",
    "healthCheckExprs": "recon.health_gate_changed",
    "deletionPolicy": "recon.deletion_policy_changed",
}


def _is_ks(path: str) -> bool:
    return path.endswith("/ks.yaml") and path.startswith("kubernetes/")


@rule(
    "flux.kustomization",
    "git",
    ["recon.structural_dependency_removed", "recon.prune_changed", "recon.suspension_changed", "recon.health_gate_changed",
     "recon.deletion_policy_changed", "recon.substitution_unresolved", "data.recovery_path_changed"],
)  # fmt: skip
def flux_kustomization(f: Facts, a: Assessment) -> None:
    for path, hunks in f.hunks.items():
        if not path.startswith("kubernetes/") or not path.endswith((".yaml", ".yml")) or f.file_status(path) in "AD":
            continue
        sid, mv = f.sid(path), moved(hunks)
        dep_removed, seen = [], set()
        for h in hunks:
            for ln in h.lines:
                if not ln.changed or ln.blank or ln.text.strip() in mv:
                    continue
                if ln.sign == "-" and (ln.within("dependsOn") or ln.key == "dependsOn"):
                    dep_removed.append(ln.text.strip())
                if not _is_ks(path):
                    continue
                code = FLUX_KEYS.get(ln.key or "") or next((FLUX_KEYS[k] for k in ("healthChecks", "healthCheckExprs") if k in ln.keys), None)
                if code and code not in seen:
                    seen.add(code)
                    eid = a.record("git", f"{path}: {ln.sign}{ln.text.strip()}", sid)
                    what = ln.key if ln.key in FLUX_KEYS else next(k for k in ln.keys if k in FLUX_KEYS)
                    if code == "recon.deletion_policy_changed":
                        a.find(code, "possible", sid, (eid,), f"`{path}` changes `deletionPolicy`: what deleting this Kustomization does to its resources changes.")
                    else:
                        a.find(code, "established", sid, (eid,), f"`{path}` changes `{what}`.")
                if ln.sign == "-" and (ln.within("substituteFrom") or ln.key == "substituteFrom"):
                    eid = a.record("git", f"{path}: -{ln.text.strip()}", sid)
                    a.find("recon.substitution_unresolved", "possible", sid, (eid,),
                           f"`{path}` removes a `substituteFrom` source; any `${{VAR}}` it provided stops resolving.")  # fmt: skip
                if ln.sign == "+" and "substitution.flux.home.arpa/disabled" in ln.text:
                    eid = a.record("git", f"{path}: +{ln.text.strip()}", sid)
                    a.find("recon.substitution_unresolved", "possible", sid, (eid,),
                           f"`{path}` opts out of cluster-settings substitution; `${{DOMAIN_*}}`-style variables stop resolving.")  # fmt: skip
                if ln.sign == "+" and re.search(r"components\.postgres/cnpg:\s*[\"']?init", ln.text):
                    eid = a.record("git", f"{path}: +{ln.text.strip()}", sid)
                    a.find("data.recovery_path_changed", "possible", sid, (eid,),
                           f"`{path}` tags the Kustomization `components.postgres/cnpg=init`: its CNPG cluster bootstraps empty "
                           "(initdb) instead of recovering from its backup. Right only for a database with no backup yet.")  # fmt: skip
        if dep_removed:
            eid = a.record("git", f"{path}: " + "; ".join(dep_removed[:4]), sid)
            a.find("recon.structural_dependency_removed", "possible", sid, (eid,),
                   f"`{path}` removes `dependsOn` entries ({short(dep_removed, 3)}): the order it reconciles in on a fresh bootstrap changes.")  # fmt: skip


@rule("flux.cluster_defaults", "git", ["recon.cluster_defaults_changed", "lifecycle.namespace_removed"],
      lambda f: any(s.id in ("flux:cluster", "component:cluster-settings", "apps") for s in f.surfaces))  # fmt: skip
def flux_cluster_defaults(f: Facts, a: Assessment) -> None:
    """kubernetes/clusters patches every Kustomization and HelmRelease, and Konflate's per-app
    render doesn't show the effective change on each. A cluster-settings value that's changed
    or removed changes every app that substitutes it; a new one changes nothing. A namespace
    directory dropped from kubernetes/apps/kustomization.yaml is pruned with everything in it
    (deletionPolicy WaitForTermination deletes, PVCs included); a new one changes nothing."""
    for path, hunks in f.hunks.items():
        sid = f.sid(path)
        if sid == "apps":
            mv = moved(hunks)
            gone = [ln.value for h in hunks for ln in h.lines if ln.sign == "-" and ln.within("resources") and ln.value and ln.text.strip() not in mv]
            if gone:
                eid = a.record("git", f"{path}: removes {short(gone)}", sid)
                a.find("lifecycle.namespace_removed", "probable", sid, (eid,),
                       f"Drops {short(gone)} from cluster-apps: Flux prunes every Kustomization in it, and deletes what they manage.")  # fmt: skip
            continue
        if sid not in ("flux:cluster", "component:cluster-settings"):
            continue
        signs = "+-" if sid != "component:cluster-settings" else "-"
        hit = [ln.text.strip() for h in hunks for ln in h.lines if ln.sign in signs and not ln.blank]
        if hit:
            eid = a.record("git", f"{path}: {short(hit, 3)}", sid)
            a.find("recon.cluster_defaults_changed", "established", sid, (eid,),
                   f"`{path}` changes defaults that every Flux Kustomization/HelmRelease inherits; Konflate doesn't show the effect per app.")  # fmt: skip


@rule("flux.components", "git", ["recon.component_contract_broken"], lambda f: bool(f.components))
def flux_components(f: Facts, a: Assessment) -> None:
    """collect() worked out, for every Kustomization that uses a changed component (or changed
    which components it uses), the `${VAR}`s the component needs with no default, minus what
    the Kustomization substitutes and cluster-settings provides, at base and at head."""
    for c in f.components:
        if c.get("unknown"):
            continue
        new = sorted(set(c.get("missing_head") or []) - set(c.get("missing_base") or []))
        if not new:
            continue
        sid = f.sid(c["ks"])
        eid = a.record("git", f"{c['ks']} ({c.get('doc')}) uses {c['component']}, which needs {', '.join(new)}; nothing provides it", sid)
        a.find("recon.component_contract_broken", "established", sid, (eid,),
               f"`{c['ks']}` ({c.get('doc')}) uses `{c['component']}`, which needs `{', '.join(new)}`; neither the Kustomization's "
               "`postBuild.substitute` nor cluster-settings provides it any more.")  # fmt: skip


# ── Storage and data ─────────────────────────────────────────────────────────────────────────

CLAIM_KEYS = {"existingClaim", "claimName", "KOPIUR_CLAIM"}
SIZE_KEY = re.compile(r"^(size|storage|capacity|[A-Z_]*CAPACITY|POSTGRES_STORAGE)$")
RECOVERY_KEYS = {"serverName", "barmanObjectName", "destinationPath", "recovery", "bootstrap", "externalClusters",
                 "retentionPolicy", "objectStore", "barmanObjectStore", "KOPIUR_REPOSITORY"}  # fmt: skip
BACKUP_KINDS = {"ObjectStore", "ScheduledBackup", "Backup", "ReplicationSource", "ReplicationDestination", "SnapshotSchedule"}
BACKUP_KIND = re.compile(r"(?m)^kind:\s*(" + "|".join(sorted(BACKUP_KINDS)) + r")\s*$")
PG_IMAGE = re.compile(r"postgres|postgis|timescale|pgvecto|vectorchord", re.I)


def major(v: str | None) -> int | None:
    if not v:
        return None
    tag = v.split("@")[0].rsplit(":", 1)[-1] if ":" in v.split("@")[0] else v
    m = re.match(r"v?(\d+)", tag)
    return int(m.group(1)) if m else None


@rule("storage.identity", "git+konflate",
      ["data.volume_identity_changed", "integrity.apply_rejected", "data.recovery_path_changed", "data.engine_major_upgrade"])  # fmt: skip
def storage_identity(f: Facts, a: Assessment) -> None:
    for h in f.all_hunks():
        if not f.structural(h) or (h.kind is None and (h.new_file or not h.path.startswith(DEPLOYED_PREFIX))):
            continue
        sid = f.hunk_sid(h)
        src = "render" if h.kind else "git"
        where = f"`{h.path}`"
        for c in changes(h):
            ev = lambda c=c: a.record(src, f"{h.path}: {c.key} {c.old} → {c.new}", sid)  # noqa: E731,B023 - called in this iteration
            if c.key in CLAIM_KEYS and c.old and c.new:
                a.find("data.volume_identity_changed", "established", sid, (ev(),),
                       f"{where} points `{c.key}` at `{c.new}` instead of `{c.old}`: the app starts on a different volume.")  # fmt: skip
            elif c.key in CLAIM_KEYS and c.old and not c.new:
                a.find("data.volume_identity_changed", "possible", sid, (ev(),), f"{where} stops using claim `{c.old}`.")
            elif SIZE_KEY.match(c.key) and "limits" not in c.keys and qty(c.old) and qty(c.new) and qty(c.new) < qty(c.old):
                a.find("integrity.apply_rejected", "established", sid, (ev(),),
                       f"{where} shrinks `{c.key}` from {c.old} to {c.new}: a PVC can't shrink, so the apply fails.")  # fmt: skip
            elif c.key in ("storageClassName", "storageClass") and c.old and c.new:
                if "postgresql.cnpg.io" in f.config.get(h.path, "") + h.text:
                    # CNPG applies it to new instances only; the existing volumes stay put.
                    certainty, why = "possible", "CNPG only uses it for new instances, so the cluster ends up on two classes until they're replaced"
                else:
                    certainty = "established" if c.key == "storageClassName" else "probable"
                    why = "an existing PVC's storage class is immutable, so the apply fails until it's recreated"
                a.find("integrity.apply_rejected", certainty, sid, (ev(),), f"{where} changes `{c.key}` from `{c.old}` to `{c.new}`: {why}.",
                       kind="mechanism" if certainty == "possible" else None)  # fmt: skip
            elif c.key == "type" and "controllers" in c.keys and "statefulset" in (c.old, c.new) and c.old and c.new:
                a.find("data.volume_identity_changed", "possible", sid, (ev(),),
                       f"{where} switches a controller between `{c.old}` and `{c.new}`: volumeClaimTemplate PVCs and ordinary PVCs are named differently.")  # fmt: skip
            elif c.key in ("imageName", "image", "tag") and c.old and c.new and (PG_IMAGE.search(c.old + c.new) or (c.key == "tag" and PG_IMAGE.search(h.text))):
                mo, mn = major(c.old), major(c.new)
                if mo and mn and mn > mo:
                    a.find("data.engine_major_upgrade", "established", sid, (ev(),),
                           f"{where} upgrades PostgreSQL {mo} → {mn}: the data directory is upgraded in place and a revert can't read it.")  # fmt: skip
        # Backup objects and recovery settings. Additions count too: bf62c46 only added a region
        # to CNPG's ObjectStore, and backups to Backblaze stopped (reverted next day).
        backup_object = (h.kind or "") in BACKUP_KINDS or bool(BACKUP_KIND.search(f.config.get(h.path, "") + "\n" + h.text))
        for ln in h.lines:
            if ln.changed and not ln.blank and (backup_object or ln.key in RECOVERY_KEYS or ln.within(*RECOVERY_KEYS)):
                eid = a.record(src, f"{h.path}: {ln.sign}{ln.text.strip()}", sid)
                what = "a backup object" if backup_object else f"recovery settings (`{ln.key or ln.keys[-1]}`)"
                a.find("data.recovery_path_changed", "possible", sid, (eid,),
                       f"{where} changes {what}: check backups still run and a restore still reads the right data.")  # fmt: skip
                f.presence.setdefault("backup_lines", set()).add(sid or "")
                break


# ── Availability ─────────────────────────────────────────────────────────────────────────────

RESOURCE_KEYS = {"cpu", "memory", "ephemeral-storage"}
COUNT_KEYS = {"replicas", "replicaCount", "minReplicas", "maxReplicas", "minReplicaCount", "maxReplicaCount", "instances", "POSTGRES_INSTANCES"}


@rule("availability.envelope", "git+konflate", ["avail.resource_envelope_changed", "avail.capacity_reduced", "avail.drain_blocked", "ctx.resource_envelope"])
def availability_envelope(f: Facts, a: Assessment) -> None:
    """Requests, limits, replica counts and disruption budgets. Every change is context and
    scopes Jev's `resource_envelope_risk` question; a reduction, a new limit, or a request or
    limit that at least doubles is a possible degradation on its own (paperless-ngx, cf4bee2:
    a memory limit tripled to 12Gi, reverted the next day)."""
    seen = []
    for h in f.all_hunks():
        if not f.structural(h):
            continue
        if h.kind is None and h.new_file:
            continue
        if h.kind is not None and h.status == "added":
            continue
        sid, src = f.hunk_sid(h), ("render" if h.kind else "git")
        for c in changes(h):
            resource = c.key in RESOURCE_KEYS and ("limits" in c.keys or "requests" in c.keys)
            if not (resource or c.key in COUNT_KEYS or c.key in ("minAvailable", "maxUnavailable")):
                continue
            old, new = qty(c.old), qty(c.new)
            what = f"`{h.path}` {'.'.join(c.keys[-2:] + (c.key,))}: {c.old or '∅'} → {c.new or '∅'}"
            seen.append(what)
            f.presence.setdefault("envelope_rendered" if h.kind else "envelope_raw", set()).add(sid or "")
            finding = None
            if resource:
                limit = "limits" in c.keys
                if old and new and new < old and limit:
                    finding = ("avail.resource_envelope_changed", "possible", f"{what}: a lower {c.key} limit can OOM-kill or throttle it.")
                elif old and new and new >= 2 * old:
                    finding = ("avail.resource_envelope_changed", "possible",
                               f"{what}: at least double, which can stop it scheduling or overcommit the node.")  # fmt: skip
                elif c.old is None and new and limit:
                    finding = ("avail.resource_envelope_changed", "possible", f"{what}: a new {c.key} limit where there was none.")
            elif c.key in COUNT_KEYS and old is not None and new is not None and new < old:
                finding = ("avail.capacity_reduced", "established", f"{what}: scaled to zero.") if new == 0 else (
                    "avail.capacity_reduced", "possible", f"{what}: fewer replicas.")  # fmt: skip
            elif old is not None and new is not None and ((c.key == "minAvailable" and new > old) or (c.key == "maxUnavailable" and new < old)):
                finding = ("avail.drain_blocked", "possible", f"{what}: a tighter disruption budget can block node drains.")
            if finding:
                code, certainty, desc = finding
                eid = a.record(src, what, sid)
                a.find(code, certainty, sid, (eid,), desc,
                       consequence="availability_loss" if code == "avail.capacity_reduced" and certainty == "established" else None)  # fmt: skip
    if seen:
        a.note("ctx.resource_envelope", short(seen, 4))


NETPOL_KINDS = {"NetworkPolicy", "CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy"}


@rule("availability.netpol", "git+konflate", ["avail.traffic_newly_restricted", "ctx.networkpolicy_removed"])
def availability_netpol(f: Facts, a: Assessment) -> None:
    """The cluster runs without network policies (CLAUDE.md): the first one that selects a pod
    drops all its other traffic in that direction, silently. Adding one is a possible
    restriction for a human to check, and Jev is asked whether it blocks something needed;
    removing one is context, since nothing here relies on policies for isolation."""
    for h in f.all_hunks():
        if not f.structural(h):
            continue
        sid, src = f.hunk_sid(h), ("render" if h.kind else "git")
        if h.kind in NETPOL_KINDS:
            if h.status == "removed":
                a.note("ctx.networkpolicy_removed", h.path, sid)
            elif any(ln.changed for ln in h.lines):
                f.presence.setdefault("netpol_rendered", set()).add(sid or "")
                eid = a.record(src, f"{h.status} {h.path}", sid)
                a.find("avail.traffic_newly_restricted", "possible", sid, (eid,), f"{h.status.capitalize() if h.status else 'Changes'} `{h.path}`.")
            continue
        for ln in h.lines:
            netpol_kind = ln.key == "kind" and ln.value in NETPOL_KINDS
            enabled = ln.sign == "+" and ln.key in ("enabled", "create") and ln.value == "true" and any(re.search("(?i)networkpolic", k) for k in ln.keys)
            if ln.sign == "-" and netpol_kind:
                a.note("ctx.networkpolicy_removed", h.path, sid)
            elif ln.sign == "+" and (netpol_kind or enabled):
                f.presence.setdefault("netpol_raw", set()).add(sid)
                eid = a.record(src, f"{h.path}: +{ln.text.strip()}", sid)
                a.find("avail.traffic_newly_restricted", "possible", sid, (eid,),
                       f"`{h.path}` adds a network policy: every other connection to the pods it selects is dropped.")  # fmt: skip


# ── CRDs and lifecycle ───────────────────────────────────────────────────────────────────────


def crd_versions(h_lines: list[Line]) -> tuple[bool, bool]:
    """(a served version is dropped, the storage version moves)."""
    t = [(ln.sign, ln.text.strip()) for ln in h_lines]
    served_del = sum(1 for s, x in t if s == "-" and x == "served: true")
    served_add = sum(1 for s, x in t if s == "+" and x == "served: true")
    dropped = served_del > served_add or any(s == "+" and x == "served: false" for s, x in t)
    moved_ = any(s == "-" and x == "storage: true" for s, x in t)
    return dropped, moved_


HOOK_RECREATED = re.compile(r"helm\.sh/hook-delete-policy:.*\b(before-hook-creation|hook-succeeded)\b")


def recreated_hook(kdiff: dict | None, title: str) -> bool:
    """A Helm hook that Helm deletes before creating it again, or after it succeeds, is never
    patched in place, so an immutable-field change can't fail it. Without a delete policy Helm
    applies `before-hook-creation` by default: Envoy Gateway's certgen Job has none (#184).
    kube-prometheus-stack's admission Jobs spell it out (#172). Konflate's rows hold the whole
    manifest, folded context included."""
    for r in ((kdiff or {}).get("diff") or {}).get("resources") or []:
        if r.get("title") == title:
            text = "\n".join(row_text(u) for u in r.get("unified") or [])
            if "helm.sh/hook:" not in text:
                return False
            return "helm.sh/hook-delete-policy:" not in text or bool(HOOK_RECREATED.search(text))
    return False


def in_kdiff(kdiff: dict | None, title: str) -> bool:
    return any(r.get("title") == title for r in ((kdiff or {}).get("diff") or {}).get("resources") or [])


@rule("crd.lifecycle", "konflate",
      ["compat.crd_version_dropped", "compat.crd_storage_version_moved", "compat.crd_conversion_changed", "lifecycle.crd_unprotected",
       "lifecycle.crd_second_owner",
       "lifecycle.release_reinstalled", "ctx.crd_touched", "ctx.crd_added"],
      lambda f: f.konflate.get("state") == "fresh")  # fmt: skip
def crd_lifecycle(f: Facts, a: Assessment) -> None:
    d = (f.konflate.get("summary") or {}).get("diff") or {}
    crds = (d.get("impact") or {}).get("crds", 0)
    if crds:
        a.note("ctx.crd_touched", f"{crds} CRD(s)")
    by_title: dict[str, list[Hunk]] = {}
    for h in f.rendered:
        by_title.setdefault(h.path, []).append(h)
    for title, hs in by_title.items():
        if hs[0].kind != "CustomResourceDefinition":
            continue
        sid = f.hunk_sid(hs[0])
        lines = [ln for h in hs for ln in h.lines]
        if hs[0].status == "added":
            a.note("ctx.crd_added", title, sid)
            eid = a.record("render", f"adds {title}", sid)
            a.find("lifecycle.crd_second_owner", "possible", sid, (eid,),
                   f"Adds `{title}`: check no other release already owns it (`kubectl get crd`), or two releases will take turns overwriting it.")  # fmt: skip
            continue
        dropped, moved_ = crd_versions(lines)
        if dropped:
            eid = a.record("render", f"{title}: a served version is removed", sid)
            a.find("compat.crd_version_dropped", "probable", sid, (eid,),
                   f"`{title}` stops serving a version: objects stored in it become unreadable until migrated.")  # fmt: skip
        elif moved_:
            eid = a.record("render", f"{title}: the storage version moves", sid)
            a.find("compat.crd_storage_version_moved", "established", sid, (eid,),
                   f"`{title}` moves its storage version: stored objects need migrating before the old version can be dropped.")  # fmt: skip
        conversion = [ln for ln in lines if ln.changed and not ln.blank and (ln.key == "conversion" or ln.within("conversion"))]
        if conversion:
            removed = all(ln.sign == "-" for ln in conversion)
            eid = a.record("render", f"{title}: conversion " + ("removed" if removed else "changed"), sid)
            a.find("compat.crd_conversion_changed", "established", sid, (eid,),
                   f"`{title}` {'drops its conversion webhook' if removed else 'changes how versions are converted'}: objects stored "
                   "in another served version are no longer converted. Harmless if no objects of this kind exist.")  # fmt: skip
        if any(ln.sign == "-" and "helm.sh/resource-policy: keep" in ln.text for ln in lines) and not any(
            ln.sign == "+" and "helm.sh/resource-policy: keep" in ln.text for ln in lines
        ):
            eid = a.record("render", f"{title}: helm.sh/resource-policy: keep removed", sid)
            a.find("lifecycle.crd_unprotected", "possible", sid, (eid,),
                   f"`{title}` loses `helm.sh/resource-policy: keep`: uninstalling its release would delete every object of that kind.")  # fmt: skip
    removed = [h for h in f.rendered if h.kind == "HelmRelease" and h.status == "removed"]
    added = [h for h in f.rendered if h.kind == "HelmRelease" and h.status == "added"]
    if removed and added:
        for h in removed:
            sid = f.hunk_sid(h)
            eid = a.record("render", f"removes {h.path} while adding {short(x.path for x in added)}", sid)
            a.find("lifecycle.release_reinstalled", "probable", sid, (eid,),
                   f"`{h.path}` is removed while {short(x.path for x in added)} is added: a rename or move uninstalls the old release.")  # fmt: skip


# ── Security ─────────────────────────────────────────────────────────────────────────────────

GRAVE_VERBS = {"escalate", "bind", "impersonate", "*"}
PRIVILEGE = [
    (("privileged",), "true"),
    (("hostNetwork", "hostPID", "hostIPC"), "true"),
    (("allowPrivilegeEscalation",), "true"),
    (("runAsNonRoot",), "false"),
    (("runAsUser",), "0"),
    (("network_mode", "pid", "ipc"), "host"),  # docker compose
]


@rule("security.rbac", "git+konflate", ["sec.rbac_widened"])
def security_rbac(f: Facts, a: Assessment) -> None:
    """Grants that amount to escalation (wildcards, escalate/bind/impersonate, cluster-admin,
    anonymous subjects) are established; new access to Secrets is possible and needs a look."""
    for h in f.all_hunks():
        if not f.structural(h):
            continue
        text = h.text
        if h.kind is None and not re.search(r"kind:\s*(Cluster)?Role(Binding)?\b|\brules:|roleRef", text):
            continue
        if h.kind is not None and h.kind not in ("ClusterRole", "Role", "ClusterRoleBinding", "RoleBinding"):
            continue
        sid, src = f.hunk_sid(h), ("render" if h.kind else "git")
        mv = {ln.text.strip() for ln in h.lines if ln.sign == "-"}
        for ln in h.lines:
            if ln.sign != "+" or ln.blank or ln.text.strip() in mv:
                continue
            val = ln.value or ""
            items = set(re.findall(r"[\w*]+", val)) if val.startswith("[") else {val}
            grave, why = None, None
            if (ln.within("verbs") or ln.key == "verbs") and items & GRAVE_VERBS:
                grave, why = True, f"grants verb(s) {', '.join(sorted(items & GRAVE_VERBS))}"
            elif (ln.within("resources") or ln.key == "resources") and "*" in items and ln.within("rules"):
                grave, why = True, "grants every resource (`*`)"
            elif (ln.within("nonResourceURLs") or ln.key == "nonResourceURLs") and "*" in items:
                grave, why = True, "grants every non-resource URL"
            elif ln.key == "name" and ln.value == "cluster-admin" and ln.within("roleRef"):
                grave, why = True, "binds to cluster-admin"
            elif ln.key == "name" and ln.value in ("system:anonymous", "system:unauthenticated") and ln.within("subjects"):
                grave, why = True, f"binds {ln.value}"
            elif (ln.within("resources") or ln.key == "resources") and "secrets" in items and ln.within("rules"):
                grave, why = False, "grants access to Secrets"
            if grave is None:
                continue
            eid = a.record(src, f"{h.path}: +{ln.text.strip()}", sid)
            a.find("sec.rbac_widened", "established" if grave else "possible", sid, (eid,), f"`{h.path}` {why}.",
                   kind="mechanism" if grave else "obligation")  # fmt: skip
            f.presence.setdefault("rbac_rendered" if h.kind else "rbac_raw", set()).add(sid or "")


@rule("security.privileges", "git+konflate", ["sec.privilege_added"])
def security_privileges(f: Facts, a: Assessment) -> None:
    for h in f.all_hunks():
        if not f.structural(h):
            continue
        if h.kind is not None and h.kind in ("CustomResourceDefinition",):
            continue
        if h.kind is None and not h.path.endswith((".yaml", ".yml")):
            continue
        sid, src = f.hunk_sid(h), ("render" if h.kind else "git")
        mv = {ln.text.strip() for ln in h.lines if ln.sign == "-"}
        for ln in h.lines:
            if ln.sign != "+" or ln.blank or ln.text.strip() in mv:
                continue
            what = None
            for keys, bad in PRIVILEGE:
                if ln.key in keys and ln.value == bad:
                    what = f"{ln.key}: {bad}"
            if ln.key == "hostPath" or (ln.key == "type" and ln.value == "hostPath"):
                what = "a hostPath volume"
            if ln.key is None and ln.value and (ln.within("capabilities") and ln.keys[-1:] == ("add",) or ln.keys[-1:] == ("cap_add",)):
                what = f"capability {ln.value}"
            if ln.value and "/var/run/docker.sock" in ln.value:
                what = "the Docker socket"
            if what:
                eid = a.record(src, f"{h.path}: +{ln.text.strip()}", sid)
                a.find("sec.privilege_added", "established", sid, (eid,), f"`{h.path}` adds {what}.")
                f.presence.setdefault("privileges_rendered" if h.kind else "privileges_raw", set()).add(sid or "")


@rule("security.exposure", "git+konflate", ["sec.exposure_widened"])
def security_exposure(f: Facts, a: Assessment) -> None:
    """`envoy-external` is on the internet through the Cloudflare tunnel; a LoadBalancer
    Service is on the LAN. Whether what gets exposed has authentication in front is Jev's
    question (`unauthenticated_external_exposure`)."""
    for h in f.all_hunks():
        if not f.structural(h):
            continue
        sid, src = f.hunk_sid(h), ("render" if h.kind else "git")
        mv = {ln.text.strip() for ln in h.lines if ln.sign == "-"}
        for ln in h.lines:
            if ln.sign != "+" or ln.blank or ln.text.strip() in mv:
                continue
            what, external = None, False
            if ln.key == "name" and ln.value == "envoy-external" and ln.within("parentRefs"):
                what, external = "a route on `envoy-external` (the internet, through Cloudflare)", True
            elif ln.key == "type" and ln.value == "LoadBalancer":
                what = "a LoadBalancer Service (the LAN)"
            elif ln.key == "hostname" and "cloudflare-tunnel" in h.path:
                what, external = f"Cloudflare tunnel hostname `{ln.value}`", True
            if not what:
                continue
            eid = a.record(src, f"{h.path}: +{ln.text.strip()}", sid)
            a.find("sec.exposure_widened", "established", sid, (eid,), f"`{h.path}` adds {what}.")
            f.presence.setdefault(("exposure_rendered" if h.kind else "exposure_raw"), set()).add(sid or "")
            if external:
                f.presence.setdefault("exposure_external", set()).add(sid or "")


SECRET_PATTERNS = {
    "private_key": r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----",
    "base64_private_key": r"LS0tLS1CRUdJTiB(?:QUklWQVRF|SU0EgUFJJVkFURS|FQyBQUklWQVRF|PUEVOU1NIIFBSSVZBVEU)[A-Za-z0-9+/=]*",
    "age_key": r"AGE-SECRET-KEY-1[0-9A-Z]{50,}",
    "github_token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "slack_token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "onepassword_token": r"\bops_[A-Za-z0-9+/=_-]{40,}",
    "api_key": r"\bsk-[A-Za-z0-9_-]{32,}",
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
}
SECRET_RE = re.compile("|".join(f"(?P<{k}>{v})" for k, v in SECRET_PATTERNS.items()))
REDACTED = re.compile(r"\[REDACTED:(\w+)\]")


KEY_MATERIAL = re.compile(r"^\+?\s*[\"']?[A-Za-z0-9+/=]{40,}")


def scan_secrets(diff: str) -> list[dict]:
    """Secret-shaped strings on added lines, by file and kind; never the values. A PEM header
    only counts with key material after it: docs mention `-----BEGIN PRIVATE KEY-----` as an
    example (eeab9c7, 1823ad3)."""
    out, path = [], None
    raws = (diff or "").splitlines()
    for i, raw in enumerate(raws):
        if raw.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*?) b/(.*)", raw)
            path = m.group(2) if m else "?"
            continue
        if not raw.startswith("+") or raw.startswith("+++") or not path:
            continue
        if path.endswith(".sops.yaml") or "ENC[" in raw:
            continue
        for m in SECRET_RE.finditer(raw):
            if m.lastgroup == "private_key":
                rest = raw[m.end() :].strip().strip("\\n\"'")
                following = raws[i + 1] if i + 1 < len(raws) else ""
                if not (KEY_MATERIAL.match(rest) or (following.startswith("+") and KEY_MATERIAL.match(following))):
                    continue
            out.append({"path": path, "kind": m.lastgroup})
        for m in REDACTED.finditer(raw):
            out.append({"path": path, "kind": m.group(1)})
    return [dict(t) for t in dict.fromkeys(tuple(sorted(x.items())) for x in out)]


NOT_A_SECRET = re.compile(r"ENC\[|\$\{|\{\{|op://|<[\w-]+>|PUBLIC KEY|CERTIFICATE|^[|>][-+]?$|^(true|false|\"\"|'')$")


def literal_secret(value: str | None) -> bool:
    """A Secret value that is the secret itself: not a SOPS ciphertext, a `${VAR}`, a template,
    a 1Password reference (op inject fills those at bootstrap), a placeholder, a public key or
    certificate, or a block scalar whose content is on the next lines."""
    return bool(value) and not NOT_A_SECRET.search(value)


def redact(text: str) -> str:
    return SECRET_RE.sub(lambda m: f"[REDACTED:{m.lastgroup}]", text or "")


@rule("security.secrets", "git", ["sec.secret_material_in_git"])
def security_secrets(f: Facts, a: Assessment) -> None:
    """In a public repository, anything committed is published for good, even after a revert.
    The collector redacts the values from the bundle, and from what Jev sees."""
    public = f.meta.get("repo_visibility", "public") != "private"
    found = {(x["path"], x["kind"]) for x in f.secrets + scan_secrets(f.diff)}
    for path, kind in sorted(found):
        sid = f.sid(path)
        eid = a.record("git", f"{path}: a {kind.replace('_', ' ')} on an added line (redacted)", sid)
        a.find("sec.secret_material_in_git", "established" if public else "possible", sid, (eid,),
               f"`{path}` adds what looks like a {kind.replace('_', ' ')}" + (": the repository is public, so rotate it." if public else "."),
               kind="integrity" if public else "obligation")  # fmt: skip
    for path, hunks in f.hunks.items():
        if not path.startswith(("kubernetes/", "bootstrap/", "docker/")) or path.endswith(".sops.yaml"):
            continue
        plus = [ln for h in hunks for ln in h.lines if ln.sign == "+"]
        if any(ln.key == "kind" and ln.value == "Secret" for ln in plus):
            values = [ln for ln in plus if ln.within("data", "stringData") and ln.key and literal_secret(ln.value)]
            if values:
                sid = f.sid(path)
                eid = a.record("git", f"{path}: a Secret with {len(values)} literal value(s) (not shown)", sid)
                a.find("sec.secret_material_in_git", "probable" if public else "possible", sid, (eid,),
                       f"`{path}` commits a Secret with literal values; secrets here come from ExternalSecrets.",
                       kind="integrity" if public else "obligation")  # fmt: skip


# ── Execution surfaces ───────────────────────────────────────────────────────────────────────

USES = re.compile(r"^\s*(-\s+)?uses:\s*\S+@[0-9a-f]{40}\b|^\s*(-\s+)?uses:\s*\S+@v?[\d.]+\b")
TOOL_PIN = re.compile(r"""^\s*"?[\w:@/.\-]+"?\s*=\s*("[^"]*"|'[^']*'|\[[^\]]*\]|\{[^}]*\bversion\b[^}]*\})\s*(#.*)?$""")
HOOK_WORDS = re.compile(r"(?i)\b(run|hook|postinstall|preinstall|exec|command|script|task|enter|leave|cd|env)\b")


def changed_lines(hunks: list[Hunk]) -> list[Line]:
    mv = moved(hunks)
    return [ln for h in hunks for ln in h.lines if ln.changed and not ln.blank and ln.text.strip() not in mv]


@rule("exec.surfaces", "git",
      ["exec.pre_merge_privileged", "exec.workflow_privilege_widened", "exec.review_bypass_widened", "exec.workstation_hook_changed",
       "ev.self_evaluation", "ctx.runner_privileged"])  # fmt: skip
def exec_surfaces(f: Facts, a: Assessment) -> None:
    """What runs before merge, with secrets, or on the owner's machine. A pinned action moving
    to a new release is a dependency bump like any other; a changed step, trigger or
    permission is code a human should read."""
    for path, hunks in f.hunks.items():
        sid = f.sid(path)
        lines = changed_lines(hunks)
        if not lines:
            continue
        ev = lambda path=path, lines=lines, sid=sid: a.record("git", f"{path}: " + "; ".join(ln.sign + ln.text.strip() for ln in lines[:3]), sid)  # noqa: E731
        if sid == "pr-risk":
            a.gap("ev.self_evaluation", "invariants", [sid], "limited",
                  "Changes this classifier; this run used the version on the base branch, so a human judges the change itself.")  # fmt: skip
        elif sid == "ci:workflows":
            text = "\n".join(h.text for h in hunks)
            if re.search(r"runs-on:.*(home-lab|RUNNER)", text):
                a.note("ctx.runner_privileged", f"{path} runs on the in-cluster runner, which is cluster-admin", sid)
            plus = [ln for ln in lines if ln.sign == "+"]
            if any(re.search(r"\b(pull_request_target|workflow_run)\b", ln.text) for ln in plus):
                a.find("exec.workflow_privilege_widened", "probable", sid, (ev(),),
                       f"`{path}` adds a `pull_request_target`/`workflow_run` trigger: code from a PR can run with this repo's secrets.")  # fmt: skip
            if any((ln.within("permissions") or ln.key == "permissions") and ln.value in ("write", "write-all") for ln in plus) or any(
                re.search(r"secrets:\s*inherit|persist-credentials:\s*true", ln.text) for ln in plus
            ):
                a.find("exec.workflow_privilege_widened", "possible", sid, (ev(),), f"`{path}` gives a job more privileges.")
            if not all(USES.match(ln.text) for ln in lines):
                a.find("exec.pre_merge_privileged", "established", sid, (ev(),),
                       f"`{path}` changes workflow steps or triggers, which run before merge with secrets.")  # fmt: skip
        elif sid == "ci:scripts":
            a.find("exec.pre_merge_privileged", "established", sid, (ev(),), f"`{path}` changes code CI runs with secrets.")
        elif sid == "renovate":
            if any(ln.sign == "+" and re.search(r"(?i)automerge|ignoreTests|platformAutomerge", ln.text) for ln in lines):
                a.find("exec.review_bypass_widened", "established", sid, (ev(),), f"`{path}` changes what Renovate merges without review.")
        elif sid == "workstation:hooks":
            if path.startswith(".mise/") or path == ".mise.toml":
                if path.endswith(".lock"):
                    continue
                code_lines = [ln for ln in lines if not TOOL_PIN.match(ln.text) or HOOK_WORDS.search(ln.text.split("=")[0])]
                if not code_lines:
                    continue
            a.find("exec.workstation_hook_changed", "established", sid, (ev(),),
                   f"`{path}` changes what runs on a workstation (git hooks, mise hooks and tasks, agent hooks or MCP servers).")  # fmt: skip


# ── Konflate ─────────────────────────────────────────────────────────────────────────────────
# Konflate's structured fields only; its free text (details, failure messages) is matched for
# infrastructure errors but never reaches the model.

KONFLATE_RULES: dict[str, tuple[str, str] | None] = {
    "removed-pvc": ("data.volume_removed", "established"),
    "pvc-shrink": ("integrity.apply_rejected", "established"),
    "removed-statefulset": ("lifecycle.resource_removed", "probable"),  # its volumes outlive it, under names a successor won't use
    "removed-namespace": ("lifecycle.namespace_removed", "established"),
    "removed-crd": ("lifecycle.crd_removed", "established"),
    "immutable-field": None,  # special-cased: Helm hooks and Jobs
    "dangling-dependson": ("integrity.dependency_unsatisfiable", "established"),
    "image-not-found": ("integrity.image_unresolvable", "established"),
    "rbac-widened": ("sec.rbac_widened", "possible"),
    "privileged": ("sec.privilege_added", "established"),
    "replicas-zero": ("avail.capacity_reduced", "established"),
    "suspends": ("recon.suspension_changed", "established"),
    "resumes": ("recon.suspension_changed", "established"),
    "suspended-parent": ("recon.suspension_changed", "established"),
    "not-pruned": ("recon.prune_changed", "established"),
    "removed-networkpolicy": None,  # context
    "large-changeset": None,  # context
    "major-chart-bump": None,  # context
    "major-source-bump": None,
    "major-image-bump": None,
}
KONFLATE_CONTEXT = {
    "removed-networkpolicy": "ctx.networkpolicy_removed",
    "large-changeset": "ctx.large_changeset",
    "major-chart-bump": "ctx.version_boundary",
    "major-source-bump": "ctx.version_boundary",
    "major-image-bump": "ctx.version_boundary",
}
CONSEQUENCE_OVERRIDE = {"removed-statefulset": "data_loss"}
# A failure with one of these is Konflate's environment (chart pull, network), not the PR.
INFRA_FAILURE = re.compile(
    r"dial tcp|network is unreachable|i/o timeout|connection refused|no such host|"
    r"TLS handshake timeout|context deadline exceeded|Too Many Requests|oras copy",
    re.IGNORECASE,
)

KONFLATE_CODES = sorted(
    {c for v in KONFLATE_RULES.values() if v for c in [v[0]]}
    | set(KONFLATE_CONTEXT.values())
    | {"integrity.render_failed", "integrity.apply_rejected", "ev.render_missing", "ev.render_incomplete", "ev.unknown_signal",
       "ctx.helm_hook_recreated", "ctx.crd_touched"}
)  # fmt: skip


@rule("konflate.render", "konflate", KONFLATE_CODES, lambda f: any(s.rendered for s in f.surfaces))
def konflate_render(f: Facts, a: Assessment) -> None:
    rendered = f.rendered_surfaces
    state, summary = f.konflate.get("state"), f.konflate.get("summary") or {}
    if state == "ignored":  # backtest over history: no render exists, judge the rest on its own
        return
    if state != "fresh":
        why = {"unavailable": "Konflate is unavailable", "stale": "Konflate hasn't rendered the current head",
               "not_rendered": "Konflate hasn't rendered this PR"}.get(state, f"Konflate: {state}")  # fmt: skip
        a.gap("ev.render_missing", "render", rendered, "insufficient", f"{why} ({summary.get('reason', state)}): nothing shows what merging renders.")
        return
    d = summary.get("diff") or {}
    head = (d.get("headSha") or "")[:7]
    for sid in rendered:
        a.record("render", f"Fresh Konflate render of {head}", sid)
        a.set_quality(sid, "render", "sufficient")

    if summary.get("status") == "error" or summary.get("error"):
        if INFRA_FAILURE.search(str(summary.get("error") or "")):
            a.gap("ev.render_incomplete", "render", rendered, "insufficient", "Konflate couldn't fetch the PR's sources, so the render is incomplete.")
        else:
            eid = a.record("render", "Konflate's render ended in an error")
            a.find("integrity.render_failed", "established", f.widest(rendered), (eid,), "The PR's manifests fail to render.")
    failed_infra: set[str] = set()
    for fl in d.get("failures") or []:
        parent = fl.get("parent", "?")
        sid = f.resource_sid(parent)
        if INFRA_FAILURE.search(fl.get("message", "")):
            failed_infra.add(parent)
            a.gap("ev.render_incomplete", "render", [sid] if sid else rendered, "insufficient",
                  f"Konflate couldn't fetch sources for `{parent}`, so its render is missing.")  # fmt: skip
        else:
            eid = a.record("render", f"render failure in {parent}", sid)
            a.find("integrity.render_failed", "established", sid, (eid,), f"`{parent}` fails to render.")

    for w in d.get("warnings") or []:
        name, res = w.get("rule", "?"), w.get("resource", "")
        sid = f.resource_sid(res)
        eid = a.record("render", f"Konflate `{name}`: {res}", sid)
        if name in KONFLATE_CONTEXT:
            a.note(KONFLATE_CONTEXT[name], res, sid)
            continue
        if name == "immutable-field":
            if res.startswith("Job "):
                if recreated_hook(f.kdiff, res):
                    a.note("ctx.helm_hook_recreated", res, sid)
                elif in_kdiff(f.kdiff, res):
                    a.find("integrity.apply_rejected", "probable", sid, (eid,),
                           f"`{res}` changes an immutable field and isn't a Helm hook Helm recreates: the apply fails until it's deleted.",
                           kind="mechanism")  # fmt: skip
                else:
                    a.find("integrity.apply_rejected", "possible", sid, (eid,),
                           f"`{res}` changes an immutable field; without its rendered diff, whether Helm recreates it can't be told.",
                           kind="mechanism")  # fmt: skip
            else:
                a.find("integrity.apply_rejected", "established", sid, (eid,), f"`{res}` changes an immutable field: the apply fails.")
            continue
        if name == "dangling-dependson" and res in failed_infra:
            # The resource only looks removed because its render failed for Konflate's reasons.
            a.gap("ev.render_incomplete", "render", [sid] if sid else rendered, "insufficient",
                  f"`{res}` looks removed only because its render failed; can't tell whether dependents lose it.")  # fmt: skip
            continue
        mapped = KONFLATE_RULES.get(name)
        if mapped is None:
            quality = "insufficient" if w.get("level") == "blocking" else "limited"
            a.gap("ev.unknown_signal", "render", [sid] if sid else rendered, quality,
                  f"Konflate rule `{name}` on `{res}` isn't one this classifier knows: read Konflate's comment.")  # fmt: skip
            continue
        code, certainty = mapped
        a.find(code, certainty, sid, (eid,), f"Konflate `{name}`: `{res}`." + (f" {w.get('detail')}" if name == "dangling-dependson" and w.get("detail") else ""),
               consequence=CONSEQUENCE_OVERRIDE.get(name))  # fmt: skip

    for img in d.get("images") or []:
        if img.get("upstream") == "missing":
            sid = next((f.resource_sid(r) for r in img.get("refs") or []), None)
            eid = a.record("render", f"image {img.get('name')} {img.get('to')} not found upstream", sid)
            a.find("integrity.image_unresolvable", "established", sid, (eid,), f"Image `{img.get('name')}:{img.get('to')}` doesn't exist upstream.")
    if d.get("truncated"):
        a.gap("ev.render_incomplete", "render", rendered, "insufficient", "Konflate truncated the rendered diff.")


# ── Evidence the PR needs but nothing renders ────────────────────────────────────────────────


DEFAULTS_SURFACES = {"flux:cluster", "component:cluster-settings", "apps"}  # flux.cluster_defaults covers these


@rule("evidence.unrendered", "repo", ["ev.unrendered_surface", "ctx.unrendered_surface"])
def evidence_unrendered(f: Facts, a: Assessment) -> None:
    configured = config_changed(f)
    for s in f.surfaces:
        if s.render_required and not s.rendered and ("operation" in s.activation or surface_config_changed(f, s.id)):
            # A version string alone is fully shown by the diff (and its release notes are
            # checked on their own); the bootstrap helmfile's chart pins are just that.
            a.note("ctx.unrendered_surface", s.id, s.id)
            a.gap("ev.unrendered_surface", "render", [s.id], "limited",
                  f"Nothing renders `{s.id}` ({short(s.paths, 3)}): a human pictures what applying it does.")  # fmt: skip
        elif "operation" in s.activation and s.reach != "none":
            # tuppr: Konflate renders the TalosUpgrade/KubernetesUpgrade object, not the node
            # upgrades it starts (f3aa1ab, Talos 1.13 → 1.14 on every node, was one changed line).
            a.note("ctx.unrendered_surface", f"{s.id}: the render shows the request, not the operation it starts", s.id)
            a.gap("ev.unrendered_surface", "render", [s.id], "limited",
                  f"`{s.id}` starts an operation (node or Kubernetes upgrades) that no render shows: check the upstream notes and the rollout.")  # fmt: skip
        elif "control_plane" in s.stakes and s.id in configured and s.id not in DEFAULTS_SURFACES:
            # A controller's configuration (CNI, storage, DNS, operators) renders as YAML, but
            # what the controller does with it only shows at runtime: Cilium's toFQDNs grace
            # period (6b68e8e) and BGP layout (0cf712a), Longhorn's storageNetwork (five
            # attempts, each reverted) all rendered cleanly. A version bump alone isn't this.
            a.note("ctx.unrendered_surface", f"{s.id}: the render shows the configuration, not the controller's behaviour", s.id)
            a.gap("ev.unrendered_surface", "render", [s.id], "limited",
                  f"Changes how `{s.id}` is configured; the render shows the new settings, not what the controller does with them.")  # fmt: skip


MAJOR_TITLE = re.compile(r"^\w+(\([^)]*\))?!:")


def may_break(meta) -> str | None:
    """Why this update may be breaking by version alone, or None. Renovate's `!:` also marks 0.x
    minor bumps (0.16 → 0.17), which it labels type/minor, so for Renovate only the label counts
    as major."""
    labels, title = meta.get("labels", []), meta.get("title", "")
    if "type/major" in labels:
        return "Major update"
    if MAJOR_TITLE.match(title):
        return "0.x update that Renovate marks as breaking" if meta.get("author_kind") == "renovate" else "Title marks a breaking change (`!:`)"
    return None


@rule("evidence.release_notes", "release_notes", ["ev.release_notes_missing", "ev.release_notes_partial", "ctx.version_boundary"])
def evidence_release_notes(f: Facts, a: Assessment) -> None:
    """A version boundary isn't a finding: the release notes decide (Jev's breaking_notes and
    breaking_affects_config). Without notes that say anything, someone has to read the
    upstream changelog, which is a bounded gap, not an unknown."""
    notes = f.notes
    targets = [s.id for s in f.surfaces if s.reach != "none"]
    why = may_break(f.meta)
    versions = ", ".join(s["version"] for s in notes.get("sections", [])[:6])
    if why:
        a.note("ctx.version_boundary", why)
        if not notes.get("sections"):
            a.gap("ev.release_notes_missing", "release_notes", targets, "limited",
                  f"{why} and no usable release notes ({notes.get('reason')}): check the upstream changelog.")  # fmt: skip
            return
        if "only" in (notes.get("reason") or ""):
            a.gap("ev.release_notes_partial", "release_notes", targets, "limited",
                  f"{why}; the release notes cover part of the range ({notes.get('reason')}): check the rest of the changelog.")  # fmt: skip
            return
    if notes.get("sections"):
        where = "GitHub releases" if notes.get("source") == "github" else "the PR"
        for sid in targets:
            a.record("release_notes", f"Release notes from {where}: {versions}", sid)
            a.set_quality(sid, "release_notes", "sufficient")


@rule("evidence.invariants", "repo", [])
def evidence_invariants(f: Facts, a: Assessment) -> None:
    for s in f.surfaces:
        a.set_quality(s.id, "invariants", "sufficient")


# ── Presence: what the semantic questions are about ──────────────────────────────────────────

VERSIONISH = {"tag", "version", "image", "imageName", "digest", "appVersion", "ref", "chart", "uses", "rev"}
STARTUP = re.compile(r"initContainers|livenessProbe|readinessProbe|startupProbe|secretKeyRef|configMapKeyRef|envFrom|existingSecret|_HOST\b|\bhost:|\burl:|dependsOn")
AVAIL_TEXT = re.compile(r"replicas|PodDisruptionBudget|strategy|Recreate|minAvailable|maxUnavailable|HorizontalPodAutoscaler|ScaledObject|topologySpread|affinity|nodeSelector|tolerations")
DATA_TEXT = re.compile(r"volumes|volumeMounts|mountPath|persistentVolumeClaim|claimName|storageClass|volumeClaimTemplates|PersistentVolume")
PAIRED = {"flux-system/flux-operator", "flux-system/flux-instance", "database/cloudnative-pg", "rook-ceph/rook-ceph",
          "network/envoy-gateway", "observability/grafana-operator", "system/snapshot-controller", "kube-system/cilium"}  # fmt: skip


def versionish(ln: Line) -> bool:
    if ln.key in VERSIONISH or USES.match(ln.text) or TOOL_PIN.match(ln.text):
        return True
    v = ln.value or ""
    return bool(re.fullmatch(r"v?\d+(\.\d+)*([-+][\w.]+)?(@sha256:[0-9a-f]{64})?|sha256:[0-9a-f]{64}", v))


def deployed_files(f: Facts):
    """(path, surface id, changed lines) for YAML that deploys or configures something."""
    for path, hunks in f.hunks.items():
        sid = f.sid(path)
        if not hunks or not path.startswith(DEPLOYED_PREFIX) or not f.structural(hunks[0]):
            continue
        yield path, sid, changed_lines(hunks)


def surface_config_changed(f: Facts, sid: str) -> bool:
    """Whether any file of a surface changes beyond versions, tags and digests (any format)."""
    return any(not versionish(ln) for path, hunks in f.hunks.items() if f.sid(path) == sid for ln in changed_lines(hunks))


def config_changed(f: Facts) -> set[str]:
    """Surfaces whose deployed configuration changes, beyond versions, tags and digests."""
    return {sid for _, sid, lines in deployed_files(f) if any(not versionish(ln) for ln in lines)}


def compute_presence(f: Facts) -> None:
    """Deterministic facts that decide which of Jev's questions have a subject. Rules above
    add to f.presence as they go; this fills in the rest."""
    p = f.presence
    for path, sid, lines in deployed_files(f):
        if any(not versionish(ln) for ln in lines):
            p.setdefault("config_change", set()).add(sid)
        if any(versionish(ln) for ln in lines):
            p.setdefault("version_change", set()).add(sid)
        if any(STARTUP.search(ln.text) for ln in lines):
            p.setdefault("startup_raw", set()).add(sid)
        if any(ln.sign == "-" and (ln.within("dependsOn", "components") or (path.endswith("kustomization.yaml") and ln.within("resources")))
               for ln in lines):  # fmt: skip
            p.setdefault("dependency_removed_raw", set()).add(sid)
        if sid.startswith("component:") or (_is_ks(path) and any(ln.within("components", "substitute") or ln.key in ("components", "substitute") for ln in lines)):
            p.setdefault("components_changed", set()).add(sid)
        if sid in ("flux:cluster", "component:cluster-settings", "apps"):
            p.setdefault("cluster_defaults", set()).add(sid)
        if any(ln.key in RECOVERY_KEYS or ln.within(*RECOVERY_KEYS) or "cnpg: init" in ln.text for ln in lines):
            p.setdefault("backup_lines", set()).add(sid)
    for h in f.rendered:
        sid = f.hunk_sid(h) or ""
        lines = [ln for ln in h.lines if ln.changed]
        if not lines:
            continue
        if h.kind in ("PodDisruptionBudget", "HorizontalPodAutoscaler", "ScaledObject") or any(AVAIL_TEXT.search(ln.text) for ln in lines):
            p.setdefault("availability_rendered", set()).add(sid)
        if h.kind in ("PersistentVolumeClaim", "PersistentVolume", "StorageClass", "StatefulSet", "Cluster") or any(DATA_TEXT.search(ln.text) for ln in lines):
            p.setdefault("data_rendered", set()).add(sid)
    data = {s.id for s in f.surfaces if "data" in s.stakes}
    p["data_surfaces"] = data
    p["paired"] = {s for s in p.get("version_change", set()) if s in PAIRED}
    p["stateful_config"] = p.get("config_change", set()) & data
    p["stateful_version"] = p.get("version_change", set()) & data
