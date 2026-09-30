"""Policy: findings and evidence in, a verdict out. Nothing else goes in: no path tier, no reach
on its own, no model score. Reach only decides how grave a real finding's consequence is.

  R1 risky      a concrete defect is established or probable (kind `integrity`), or a mechanism
                with a grave consequence is.
  R2 uncertain  otherwise, some surface's required evidence is insufficient: review + uncertain.
  R3 review     otherwise, any remaining finding (possible or non-grave), obligation, bounded
                evidence gap (`limited`), or non-reversible change.
  R4 safe       none of the above: every surface identified, its evidence sufficient, and
                nothing left to look at.

A risky PR can also be uncertain: what is known is bad, and something else is unknown.
"""

from __future__ import annotations

from dataclasses import dataclass

from taxonomy import Assessment, Finding, reach_at_least

GRAVE_ALWAYS = {"data_loss", "security_exposure", "privilege_escalation"}
GRAVE_WHEN_WIDE = {"availability_loss", "reconciliation_failure"}  # an app going down is review; a platform, risky
CERTAIN = ("established", "probable")


def grave(f: Finding, a: Assessment) -> bool:
    if f.consequence in GRAVE_ALWAYS:
        return True
    if f.consequence in GRAVE_WHEN_WIDE:
        return reach_at_least(a.reach_of(f.surface), "shared")
    if f.consequence == "irreversible_state_change":
        return "data" in a.stakes_of(f.surface)  # materially harmful when there is data to lose
    return False


def material(f: Finding) -> bool:
    return f.kind != "evidence" and f.certainty != "ruled_out"


def risky_because(f: Finding, a: Assessment) -> str | None:
    if not material(f) or f.certainty not in CERTAIN:
        return None
    if f.kind == "integrity":
        return "defect"
    if f.kind == "mechanism" and grave(f, a):
        return "grave"
    return None


@dataclass
class Verdict:
    classification: str  # safe | review | risky
    uncertain: bool
    rule: str  # R1 | R2 | R3 | R4
    why: str
    risky: list[Finding]
    review: list[Finding]
    insufficient: list[str]  # surface ids
    limited: list[str]
    non_reversible: list[str]


def decide(a: Assessment) -> Verdict:
    findings = [f for f in a.findings if material(f)]
    risky = [f for f in findings if risky_because(f, a)]
    review = [f for f in findings if f not in risky]
    sas = list(a.surfaces.values())
    insufficient = [s.surface.id for s in sas if s.sufficiency == "insufficient"]
    limited = [s.surface.id for s in sas if s.sufficiency == "limited"]
    non_reversible = [s.surface.id for s in sas if s.reversibility == "non_reversible"]
    uncertain = bool(insufficient) or not sas

    def v(classification, rule, why):
        return Verdict(classification, uncertain, rule, why, risky, review, insufficient, limited, non_reversible)

    if risky:
        kinds = {risky_because(f, a) for f in risky}
        why = "a concrete defect" if kinds == {"defect"} else "a grave mechanism" if kinds == {"grave"} else "a concrete defect and a grave mechanism"
        return v("risky", "R1", f"{why}: " + ", ".join(dict.fromkeys(f"`{f.code}`" for f in risky)))
    if not sas:
        return v("review", "R2", "no changed files were identified")
    if insufficient:
        return v("review", "R2", "required evidence is missing for " + ", ".join(f"`{s}`" for s in insufficient))
    reasons = []
    if review:
        reasons.append("findings to check: " + ", ".join(dict.fromkeys(f"`{f.code}`" for f in review)))
    if limited:
        reasons.append("a bounded evidence gap on " + ", ".join(f"`{s}`" for s in limited))
    if non_reversible:
        reasons.append("a revert won't undo " + ", ".join(f"`{s}`" for s in non_reversible))
    if reasons:
        return v("review", "R3", "; ".join(reasons))
    return v("safe", "R4", "evidence is sufficient and nothing needs a look")
