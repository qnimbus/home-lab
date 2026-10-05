"""The v2 vocabulary: context dimensions, findings, evidence, and the reason-code registry.

Reach, stakes and activation describe a change. Findings describe what can go wrong. Evidence
describes how well we know. Policy (policy.py) turns those into a verdict. None of these is a
number, and none of them is a severity on its own. See README.md next to this file.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SCHEMA = "pr-risk/v2"
POLICY_VERSION = "2.5"

# ── Context dimensions ───────────────────────────────────────────────────────────────────────

REACH = ["none", "workstation", "ci", "app", "shared", "cluster", "host"]  # ordered: how far it propagates
STAKES = ["data", "credentials", "trust_boundary", "control_plane", "availability"]
ACTIVATION = ["pre_merge", "reconcile", "operation", "manual", "latent"]
REVERSIBILITY = ["revert", "revert_with_toil", "non_reversible"]  # ordered


def reach_at_least(reach: str, floor: str) -> bool:
    return REACH.index(reach) >= REACH.index(floor)


def max_reach(reaches) -> str:
    return max(reaches, key=REACH.index, default="none")


def worst_reversibility(values) -> str:
    return max(values, key=REVERSIBILITY.index, default="revert")


# ── Assessment ───────────────────────────────────────────────────────────────────────────────

KINDS = ["mechanism", "obligation", "evidence", "integrity", "intent"]
CERTAINTY = ["established", "probable", "possible", "ruled_out"]
CONSEQUENCE = [
    "none",
    "degradation",
    "availability_loss",
    "reconciliation_failure",
    "data_loss",
    "security_exposure",
    "privilege_escalation",
    "irreversible_state_change",
]
SUFFICIENCY = ["sufficient", "limited", "insufficient"]  # ordered
EVIDENCE_SOURCES = ["git", "render", "release_notes", "model", "invariants", "checks"]


def worst_sufficiency(values) -> str:
    return max(values, key=SUFFICIENCY.index, default="sufficient")


# ── Reason codes ─────────────────────────────────────────────────────────────────────────────
# Stable machine-readable identifiers. The prose lives in each finding's description, so it can
# change without breaking backtests that group by code. `kind` and `consequence` are defaults: a
# rule can report the same code with a different certainty.


@dataclass(frozen=True)
class Code:
    code: str
    kind: str
    consequence: str
    summary: str


def _codes(*rows: tuple[str, str, str, str]) -> dict[str, Code]:
    return {c: Code(c, k, q, s) for c, k, q, s in rows}


CODES = _codes(
    # Integrity: the PR is already in a known-bad state.
    ("integrity.merge_conflict", "integrity", "none", "Textual conflict with the base branch"),
    ("integrity.render_failed", "integrity", "reconciliation_failure", "The PR's manifests don't render"),
    ("integrity.image_unresolvable", "integrity", "availability_loss", "An image the PR deploys doesn't exist upstream"),
    ("integrity.apply_rejected", "integrity", "reconciliation_failure", "The API server will reject the apply (immutable field)"),
    ("integrity.dependency_unsatisfiable", "integrity", "reconciliation_failure", "A dependency the PR leaves in place can no longer be met"),
    ("integrity.semantic_merge_hazard", "integrity", "reconciliation_failure", "The PR and the base branch change the same setting"),
    # Data
    ("data.volume_removed", "mechanism", "data_loss", "A volume with data is removed"),
    ("data.volume_identity_changed", "mechanism", "data_loss", "A volume's or database's identity changes"),
    ("data.path_changed", "mechanism", "data_loss", "Where an app finds its data changes"),
    ("data.recovery_path_changed", "mechanism", "data_loss", "How data would be restored changes"),
    ("data.forward_only_migration", "mechanism", "irreversible_state_change", "A migration that a revert can't undo"),
    ("data.engine_major_upgrade", "obligation", "irreversible_state_change", "A database engine major upgrade"),
    # Availability
    ("avail.capacity_reduced", "mechanism", "availability_loss", "Fewer replicas or instances"),
    ("avail.drain_blocked", "mechanism", "degradation", "Node drains can block"),
    ("avail.writes_blocked", "mechanism", "availability_loss", "Writes can block"),
    ("avail.resource_envelope_changed", "mechanism", "degradation", "CPU, memory or storage requests/limits change"),
    ("avail.traffic_newly_restricted", "mechanism", "availability_loss", "A network policy restricts traffic"),
    ("avail.startup_dependency_changed", "mechanism", "availability_loss", "Something a workload needs at startup changes"),
    # Compatibility
    ("compat.breaking_change_applies", "integrity", "reconciliation_failure", "A breaking change touches this repo's configuration"),
    ("compat.breaking_change_elsewhere", "obligation", "none", "A breaking change that doesn't seem to touch this repo's configuration"),
    ("compat.setting_conflict", "mechanism", "reconciliation_failure", "A setting contradicts a repository rule"),
    ("compat.version_pair_split", "mechanism", "reconciliation_failure", "Components that must match versions are split"),
    ("compat.crd_version_dropped", "mechanism", "data_loss", "A CRD stops serving a version"),
    ("compat.crd_storage_version_moved", "obligation", "none", "A CRD's storage version moves"),
    ("compat.crd_schema_narrowed", "mechanism", "reconciliation_failure", "A CRD schema removes or narrows a field"),
    ("compat.crd_conversion_changed", "obligation", "reconciliation_failure", "A CRD's version conversion (webhook) changes"),
    # Kubernetes lifecycle
    ("lifecycle.resource_removed", "mechanism", "availability_loss", "A deployed resource is removed"),
    ("lifecycle.release_reinstalled", "mechanism", "availability_loss", "A HelmRelease is uninstalled and installed again"),
    ("lifecycle.crd_removed", "mechanism", "data_loss", "A CRD, and every object of its kind, is removed"),
    ("lifecycle.crd_unprotected", "mechanism", "data_loss", "A templated CRD loses helm.sh/resource-policy: keep"),
    ("lifecycle.crd_second_owner", "obligation", "reconciliation_failure", "A CRD may get a second owning release"),
    ("lifecycle.namespace_removed", "mechanism", "data_loss", "A namespace, and everything in it, is removed"),
    # Reconciliation
    ("recon.structural_dependency_removed", "mechanism", "reconciliation_failure", "An ordering dependency is removed"),
    ("recon.prune_changed", "obligation", "none", "Flux pruning changes"),
    ("recon.suspension_changed", "obligation", "none", "Flux suspension changes"),
    ("recon.health_gate_changed", "obligation", "none", "What Flux waits for changes"),
    ("recon.deletion_policy_changed", "mechanism", "data_loss", "What deleting a Kustomization does changes"),
    ("recon.substitution_unresolved", "mechanism", "reconciliation_failure", "A substitution source is removed"),
    ("recon.component_contract_broken", "integrity", "reconciliation_failure", "A component no longer gets what it needs"),
    ("recon.cluster_defaults_changed", "obligation", "reconciliation_failure", "Defaults patched onto every Kustomization/HelmRelease change"),
    # Security
    ("sec.rbac_widened", "mechanism", "privilege_escalation", "RBAC grants widen"),
    ("sec.privilege_added", "obligation", "privilege_escalation", "Container or host privileges are added"),
    ("sec.exposure_widened", "obligation", "security_exposure", "A service becomes reachable from more places"),
    ("sec.secret_material_in_git", "integrity", "security_exposure", "Secret material in a public repository"),
    # Execution / CI
    ("exec.pre_merge_privileged", "obligation", "privilege_escalation", "Code that runs before merge, with secrets, changes"),
    ("exec.workflow_privilege_widened", "mechanism", "privilege_escalation", "A workflow gets more privileges"),
    ("exec.review_bypass_widened", "obligation", "none", "More changes can merge without review"),
    ("exec.workstation_hook_changed", "obligation", "privilege_escalation", "A hook that runs on a workstation changes"),
    # Intent
    ("intent.unexplained_change", "intent", "none", "Changes the title and description don't explain"),
    ("intent.bot_diff_out_of_shape", "intent", "none", "A bot PR changes more than a bot would"),
    # Evidence: these set a surface's sufficiency, they don't count as findings themselves.
    ("ev.render_missing", "evidence", "none", "No fresh render of the PR's head"),
    ("ev.render_incomplete", "evidence", "none", "The render is incomplete"),
    ("ev.unrendered_surface", "evidence", "none", "Nothing renders this surface"),
    ("ev.release_notes_missing", "evidence", "none", "No usable release notes across a version boundary"),
    ("ev.release_notes_partial", "evidence", "none", "Release notes cover part of the version range, or the chart and not an image it deploys"),
    ("ev.model_unavailable", "evidence", "none", "Jev didn't answer"),
    ("ev.model_indecisive", "evidence", "none", "Jev's answer is on the fence"),
    ("ev.model_input_truncated", "evidence", "none", "Jev saw only part of the input"),
    ("ev.opaque_content", "evidence", "none", "Binary or opaque content"),
    ("ev.merge_result_unknown", "evidence", "none", "The merge result couldn't be computed"),
    ("ev.stale_base", "evidence", "none", "The base moved in a way that matters"),
    ("ev.manipulation_attempt", "evidence", "none", "The input tries to steer the classifier"),
    ("ev.self_evaluation", "evidence", "none", "The PR changes this classifier"),
    ("ev.unknown_signal", "evidence", "none", "A signal this classifier doesn't know"),
)  # fmt: skip

# Context codes: informational, never escalate. They can decide which checks run.
CONTEXT_CODES = {
    "ctx.version_boundary": "Crosses a major or 0.x minor version boundary",
    "ctx.release_notes_unlisted": "A package named like a GitHub repo that REPO_PACKAGES doesn't list, so its releases weren't looked up",
    "ctx.crd_touched": "Touches CustomResourceDefinitions",
    "ctx.base_overlap": "Files also changed on the base branch",
    "ctx.large_changeset": "Large changeset",
    "ctx.helm_hook_recreated": "Immutable change on a Helm hook that Helm recreates",
    "ctx.networkpolicy_removed": "Removes a network policy",
    "ctx.unrendered_surface": "A surface nothing renders",
    "ctx.runner_privileged": "Runs on the cluster-admin in-cluster runner",
    "ctx.resource_envelope": "Resource requests/limits or replica counts change",
    "ctx.crd_added": "Adds a CustomResourceDefinition",
    "ctx.operand_restart": "An operator's image changes, and rolling it out restarts what the operator manages",
    "ctx.change_exercised": "The PR's own run of a changed workflow passed on this head, with nothing skipped",
}


# ── Records ──────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Surface:
    id: str
    paths: tuple[str, ...]
    reach: str
    stakes: frozenset[str]
    activation: frozenset[str]
    reversibility: str
    rendered: bool  # Konflate renders it
    render_required: bool  # a render (or a stand-in) is needed to know what merging does
    model_required: bool
    operands: str = ""  # what its operator restarts when the operator's own image changes

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "paths": list(self.paths),
            "reach": self.reach,
            "stakes": sorted(self.stakes),
            "activation": sorted(self.activation, key=ACTIVATION.index),
            "reversibility": self.reversibility,
            "rendered": self.rendered,
        }


@dataclass(frozen=True)
class Evidence:
    id: str
    source: str
    fact: str
    surface: str | None
    quality: str  # sufficient | limited | insufficient


@dataclass(frozen=True)
class Finding:
    id: str
    code: str
    kind: str
    certainty: str
    consequence: str
    surface: str | None
    evidence: tuple[str, ...]
    description: str


@dataclass
class SurfaceAssessment:
    surface: Surface
    evidence: dict[str, str] = field(default_factory=dict)  # source -> sufficiency; absent = not applicable
    findings: list[Finding] = field(default_factory=list)
    reversibility: str = "revert"

    @property
    def sufficiency(self) -> str:
        return worst_sufficiency(self.evidence.values())

    def to_json(self) -> dict:
        return {
            **self.surface.to_json(),
            "reversibility": self.reversibility,
            "evidence": dict(self.evidence),
            "sufficiency": self.sufficiency,
        }


class Assessment:
    """The ledger rules write into: surfaces, evidence records, findings and context."""

    def __init__(self, surfaces: list[Surface]):
        self.surfaces = {s.id: SurfaceAssessment(s, reversibility=s.reversibility) for s in surfaces}
        self.evidence: list[Evidence] = []
        self.findings: list[Finding] = []
        self.context: list[dict] = []
        self._ev_index: dict[tuple, str] = {}

    # Evidence ----------------------------------------------------------------------------------

    def record(self, source: str, fact: str, surface: str | None = None, quality: str = "sufficient") -> str:
        """An evidence record; returns its id. Identical records are shared."""
        key = (source, fact, surface, quality)
        if key not in self._ev_index:
            eid = f"e-{len(self.evidence) + 1:03d}"
            self.evidence.append(Evidence(eid, source, fact, surface, quality))
            self._ev_index[key] = eid
        return self._ev_index[key]

    def set_quality(self, surface: str, source: str, quality: str) -> None:
        """Lower a surface's evidence for one source; it never goes back up."""
        sa = self.surfaces.get(surface)
        if sa is None:
            return
        have = sa.evidence.get(source)
        sa.evidence[source] = quality if have is None else worst_sufficiency([have, quality])

    def gap(self, code: str, source: str, surfaces, quality: str, description: str, fact: str | None = None) -> None:
        """An evidence gap: an `ev.*` finding plus a lowered ledger entry on each surface."""
        for sid in surfaces:
            eid = self.record(source, fact or description, sid, quality)
            self.set_quality(sid, source, quality)
            self.find(code, "established", sid, (eid,), description)

    # Findings ----------------------------------------------------------------------------------

    def find(
        self,
        code: str,
        certainty: str,
        surface: str | None,
        evidence: tuple[str, ...] | list[str],
        description: str,
        *,
        consequence: str | None = None,
        kind: str | None = None,
    ) -> Finding | None:
        spec = CODES[code]
        assert certainty in CERTAINTY, certainty
        kind, consequence = kind or spec.kind, consequence or spec.consequence
        if surface in self.surfaces and certainty in ("established", "probable"):
            if consequence == "irreversible_state_change" or code in NON_REVERSIBLE_CODES:
                self.surfaces[surface].reversibility = "non_reversible"
        # One finding per code, surface and kind: keep the most certain, merge the evidence. The
        # kind stays apart: "exposed" (an obligation, established) and "exposed without
        # authentication" (a mechanism, probable) are two claims, and the second can be risky.
        for i, f in enumerate(self.findings):
            if f.code == code and f.surface == surface and f.kind == kind:
                merged = tuple(dict.fromkeys((*f.evidence, *evidence)))
                if strength(certainty, kind) < strength(f.certainty, f.kind):
                    self.findings[i] = Finding(f.id, code, kind, certainty, consequence, surface, merged, description)
                else:
                    self.findings[i] = Finding(f.id, f.code, f.kind, f.certainty, f.consequence, surface, merged, f.description)
                if surface in self.surfaces:
                    sf = self.surfaces[surface].findings
                    sf[:] = [self.findings[i] if x.id == f.id else x for x in sf]
                return self.findings[i]
        f = Finding(f"f-{len(self.findings) + 1:03d}", code, kind, certainty, consequence, surface, tuple(evidence), description)
        self.findings.append(f)
        if surface in self.surfaces:
            self.surfaces[surface].findings.append(f)
        return f

    def note(self, code: str, detail: str, surface: str | None = None) -> None:
        assert code in CONTEXT_CODES, code
        entry = {"code": code, "detail": detail, "surface": surface}
        if entry not in self.context:
            self.context.append(entry)

    def reach_of(self, surface: str | None) -> str:
        """A finding without a surface is judged at the widest reach among the PR's surfaces."""
        if surface in self.surfaces:
            return self.surfaces[surface].surface.reach
        return max_reach(s.surface.reach for s in self.surfaces.values())

    def stakes_of(self, surface: str | None) -> frozenset[str]:
        if surface in self.surfaces:
            return self.surfaces[surface].surface.stakes
        return frozenset().union(*(s.surface.stakes for s in self.surfaces.values()))


KIND_RANK = {"integrity": 0, "mechanism": 1, "intent": 2, "obligation": 3, "evidence": 4}


def strength(certainty: str, kind: str) -> tuple[int, int]:
    """Lower is stronger: more certain first, then the kind that can make a PR risky."""
    return CERTAINTY.index(certainty), KIND_RANK[kind]


NON_REVERSIBLE_CODES = {"data.volume_identity_changed", "data.volume_removed", "lifecycle.crd_removed", "lifecycle.namespace_removed"}


def finding_json(f: Finding) -> dict:
    return asdict(f) | {"evidence": list(f.evidence)}


# ── Globs ────────────────────────────────────────────────────────────────────────────────────


def glob_re(pattern: str) -> re.Pattern:
    """`**` crosses directories, `*` doesn't, `{a,b}` alternates; anchored to the whole path."""
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "{":
            j = pattern.index("}", i)
            out, i = out + "(?:" + "|".join(map(re.escape, pattern[i + 1 : j].split(","))) + ")", j + 1
        else:
            out, i = out + re.escape(c), i + 1
    return re.compile(out + r"\Z")


_GLOBS: dict[str, re.Pattern] = {}


def matches(path: str, patterns) -> bool:
    for p in patterns:
        if p not in _GLOBS:
            _GLOBS[p] = glob_re(p)
        if _GLOBS[p].match(path):
            return True
    return False
