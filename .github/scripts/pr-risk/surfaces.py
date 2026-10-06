"""The surface registry: which part of the repo a path belongs to, and that part's context.

A surface's reach, stakes and activation are deterministic facts about where a change lands. They
decide which checks apply and how grave a real finding is. They are never a finding themselves:
a clean Cilium patch bump is a cluster-reach change with nothing wrong with it.

First match wins. `{ns}` and `{app}` in an id are filled from the path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from taxonomy import Surface, matches

A = frozenset  # short for the tables below


@dataclass(frozen=True)
class SurfaceDef:
    id: str
    patterns: tuple[str, ...]
    reach: str
    stakes: frozenset[str] = A()
    activation: frozenset[str] = A({"reconcile"})
    reversibility: str = "revert"
    rendered: bool = False  # Konflate renders it (its filter keys on area/kubernetes, set from these paths)
    render_required: bool = False  # without a render, a human has to picture what merging does
    model_required: bool = True
    operands: str = ""  # what restarts when this operator's image changes; a context line, never a finding


def d(id, patterns, reach, stakes=(), activation=("reconcile",), **kw) -> SurfaceDef:
    return SurfaceDef(id, tuple(patterns), reach, A(stakes), A(activation), **kw)


def app(id, patterns, reach, stakes=("availability",), **kw) -> SurfaceDef:
    """A Flux-deployed surface: rendered by Konflate, which has to have rendered it."""
    return d(id, patterns, reach, stakes, rendered=True, render_required=True, **kw)


AGENT_DOCS = [".agents/**", ".claude/**"]

REGISTRY: list[SurfaceDef] = [
    # ── The classifier itself: this run used the version on the base branch.
    d("pr-risk", [".github/workflows/pr-risk.yaml", ".github/scripts/pr-risk/**"], "ci", ("credentials", "trust_boundary"), ("manual",)),
    # ── Executable surfaces that run before merge or on a workstation. Not inert, even when
    # nothing deploys from them.
    d("ci:workflows", [".github/workflows/**", ".github/actions/**"], "ci", ("credentials", "trust_boundary"), ("pre_merge",)),
    d("ci:scripts", [".github/scripts/**"], "ci", ("credentials", "trust_boundary"), ("pre_merge",)),
    d("ci:config", [".github/labeler.yaml", ".github/actionlint.yaml", ".github/validate.env", ".yamllint.yaml",
                    ".oxfmtrc.json", ".yamlfmt.yaml"], "ci", (), ("pre_merge",)),  # fmt: skip
    d("renovate", [".renovaterc.json5", ".renovate/**", "renovate.json5"], "ci", ("trust_boundary",), ("latent",)),
    d("workstation:hooks", [".lefthook.yaml", ".mise/**", ".mise.toml", ".claude/settings*.json", ".mcp.json", ".gitattributes",
                            ".devcontainer/**"], "workstation", ("credentials",), ("pre_merge",)),  # fmt: skip
    # ── Documentation. Agent instructions are docs for agents that act with the owner's
    # credentials, so they aren't `none`.
    d("agents", AGENT_DOCS, "workstation", (), ("manual",)),
    d("docs", ["**/*.md", "docs/**", "LICENSE", ".github/labels.yaml", ".github/release.yaml", ".github/ISSUE_TEMPLATE/**",
               ".github/CODEOWNERS", ".editorconfig", ".vscode/**", ".worktreeinclude"], "none", (), (),
      model_required=False),  # fmt: skip
    d("workstation:tooling", [".justfile", "**/mod.just", ".minijinja.toml", ".sopsrc.yaml", ".gitignore", "Taskfile.yaml",
                              ".taskfiles/**", "scripts/**"], "workstation", ("credentials",), ("manual",)),  # fmt: skip
    # ── Host and bring-up: nothing renders these. (talos/, ops/, truenas/ and kubernetes/flux
    # are where these lived before; kept so a backtest over history lands them right.)
    d("talos", ["kubernetes/talos/**", "talos/**"], "host", ("control_plane", "availability"), ("operation",),
      reversibility="revert_with_toil", render_required=True),  # fmt: skip
    d("bootstrap", ["bootstrap/**", "kubernetes/bootstrap/**", "ops/bootstrap/**"], "cluster", ("control_plane", "credentials"),
      ("manual",), render_required=True),  # fmt: skip
    d("ansible", ["ansible/**"], "host", ("control_plane", "credentials"), ("manual",), render_required=True),
    d("doco-cd", ["docker/nas/.doco-cd/**"], "host", ("credentials",), ("manual",)),  # needs `just bootstrap nas`
    d("doco-cd:config", ["docker/nas/.doco-cd.yaml"], "host", ("credentials",)),
    # A compose file is the whole truth (no templating), so the git diff is its render.
    d("nas:{stack}", ["docker/nas/{stack}/**", "truenas/docker/{stack}/**"], "app", ("availability",)),
    # ── Flux: cluster-wide entry point and defaults.
    app("flux:cluster", ["kubernetes/clusters/**"], "cluster", ("control_plane",)),
    app("flux:meta", ["kubernetes/flux/**"], "cluster", ("availability",)),  # chart sources, now per-app ocirepository.yaml
    app("component:cluster-settings", ["kubernetes/components/cluster-settings/**"], "cluster", ("control_plane",)),
    app("component:postgres", ["kubernetes/components/postgres/**"], "shared", ("data", "availability", "credentials")),
    app("component:dragonfly", ["kubernetes/components/dragonfly/**"], "shared", ("availability", "credentials")),
    app("component:kopiur", ["kubernetes/components/kopiur/**"], "shared", ("data",)),
    app("component:nfs", ["kubernetes/components/nfs/**"], "shared", ("data",)),
    app("component:{component}", ["kubernetes/components/{component}/**"], "shared"),
    app("apps", ["kubernetes/apps/kustomization.yaml"], "cluster", ("control_plane",)),
    app("namespace:{ns}", ["kubernetes/apps/{ns}/kustomization.yaml", "kubernetes/apps/{ns}/namespace.yaml"], "shared", ("trust_boundary",)),
    # ── Cluster foundation: wide reach, which only matters when something is actually wrong.
    app("{ns}/{app}", ["kubernetes/apps/kube-system/{cilium,coredns}/**"], "cluster", ("control_plane", "availability")),
    app("{ns}/{app}", ["kubernetes/apps/rook-ceph/{app}/**"], "cluster", ("data", "availability", "control_plane")),
    app("{ns}/{app}", ["kubernetes/apps/system/{openebs,csi-driver-nfs,csi-driver-smb,snapshot-controller,kopiur}/**",
                       "kubernetes/apps/longhorn-system/{app}/**"], "cluster", ("data", "availability", "control_plane")),  # fmt: skip
    app("{ns}/{app}", ["kubernetes/apps/system-upgrade/{app}/**"], "host", ("control_plane", "availability"),
        activation=("reconcile", "operation"), reversibility="revert_with_toil"),  # fmt: skip
    app("{ns}/{app}", ["kubernetes/apps/network/{envoy-gateway,cloudflare-tunnel}/**"], "cluster", ("trust_boundary", "availability")),
    app("{ns}/{app}", ["kubernetes/apps/network/certificates/**", "kubernetes/apps/cert-manager/{app}/**"], "cluster", ("credentials", "availability")),
    app("{ns}/{app}", ["kubernetes/apps/external-secrets/{app}/**"], "cluster", ("credentials",)),
    app("{ns}/{app}", ["kubernetes/apps/flux-system/{flux-instance,flux-operator}/**"], "cluster", ("control_plane",)),
    app("{ns}/{app}", ["kubernetes/apps/actions-runner-system/{app}/**"], "cluster", ("credentials", "trust_boundary")),  # runners are cluster-admin
    # ── Shared platform services.
    # In-place instance-manager updates are off, so a new operator image rolls every instance.
    # Drop `operands` if ENABLE_INSTANCE_MANAGER_INPLACE_UPDATES is ever set.
    app("{ns}/{app}", ["kubernetes/apps/database/cloudnative-pg/**"], "shared", ("data", "availability", "control_plane"),
        operands="every Postgres cluster it manages (one instance each, so each is briefly down; avoid the backup windows)"),  # fmt: skip
    app("{ns}/{app}", ["kubernetes/apps/database/dragonfly/**"], "shared", ("data", "availability", "control_plane")),
    app("{ns}/{app}", ["kubernetes/apps/observability/kube-prometheus-stack/**"], "shared", ("availability",)),
    app("{ns}/{app}", ["kubernetes/apps/system/{keda,reloader,intel-gpu-resource-driver}/**", "kubernetes/apps/kube-system/{app}/**"],
        "shared", ("availability",)),  # fmt: skip
    app("{ns}/{app}", ["kubernetes/apps/network/{tailscale-operator,external-services}/**"], "shared", ("trust_boundary",)),
    app("{ns}/{app}", ["kubernetes/apps/network/{app}/**", "kubernetes/apps/flux-system/{app}/**"], "shared", ("availability",)),
    # ── One application.
    app("{ns}/{app}", ["kubernetes/apps/{ns}/{app}/**"], "app"),
    d("repo", ["**"], "workstation", (), ("manual",)),  # anything else: not inert until someone says so
]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Like taxonomy.glob_re, but `{name}` (no comma) captures one path segment."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "{":
            j = pattern.index("}", i)
            inner = pattern[i + 1 : j]
            out += "(?:" + "|".join(map(re.escape, inner.split(","))) + ")" if "," in inner else f"(?P<{inner.replace('-', '_')}>[^/]+)"
            i = j + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


_COMPILED = [(sd, [_pattern_to_regex(p) for p in sd.patterns]) for sd in REGISTRY]
APP_PATH = re.compile(r"^kubernetes/apps/(?P<ns>[^/]+)/(?P<app>[^/]+)/")


def classify_path(path: str) -> tuple[SurfaceDef, str]:
    """(definition, surface id) for one path. Markdown anywhere is docs, except agent docs."""
    if matches(path, ["**/*.md"]) and not matches(path, AGENT_DOCS):
        sd = next(s for s in REGISTRY if s.id == "docs")
        return sd, "docs"
    for sd, regexes in _COMPILED:
        for rx in regexes:
            m = rx.match(path)
            if not m:
                continue
            groups = {k: v for k, v in m.groupdict().items() if v}
            a = APP_PATH.match(path)
            if a:
                groups.setdefault("ns", a.group("ns"))
                groups.setdefault("app", a.group("app"))
            sid = sd.id
            for k, v in groups.items():
                sid = sid.replace("{" + k + "}", v)
            return sd, sid
    raise AssertionError("the registry ends with a catch-all")


# Content that adds a stake a path alone doesn't show: an app with a volume holds data.
STAKE_HINTS = {
    "data": re.compile(r"persistence:|PersistentVolumeClaim|existingClaim|volumeClaimTemplates|components/(postgres|kopiur)|"
                       r"storageClass|postgresql\.cnpg\.io|KOPIUR_"),  # fmt: skip
    "credentials": re.compile(r"ExternalSecret|secretKeyRef|existingSecret|op://|kind: Secret\b"),
    "trust_boundary": re.compile(r"envoy-external|HTTPRoute|type: LoadBalancer|ClusterRole|RoleBinding"),
}


def build_surfaces(files: list[dict], texts: dict[str, str] | None = None) -> list[Surface]:
    """Group changed paths into surfaces. `texts` (surface id -> diff and config text) adds the
    stakes that content shows."""
    groups: dict[str, tuple[SurfaceDef, list[str]]] = {}
    for f in files:
        for path in dict.fromkeys(p for p in (f.get("old_path"), f["path"]) if p):
            sd, sid = classify_path(path)
            groups.setdefault(sid, (sd, []))[1].append(path)
    out = []
    for sid, (sd, paths) in groups.items():
        stakes = set(sd.stakes)
        text = (texts or {}).get(sid, "")
        if sd.reach not in ("none",):
            stakes |= {s for s, rx in STAKE_HINTS.items() if rx.search(text)}
        out.append(Surface(sid, tuple(paths), sd.reach, frozenset(stakes), sd.activation, sd.reversibility,
                           sd.rendered, sd.render_required, sd.model_required, sd.operands))  # fmt: skip
    return out


def surface_id(path: str) -> str:
    return classify_path(path)[1]
