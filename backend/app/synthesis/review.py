"""Reviewer / Critic rules enforced in code (docs/day-5-implementation-brief.md section 7, tests R1, R2, E3).

The model produces findings. Code decides what they mean:
  * minimum severities: the categories in MIN_BLOCKING are ALWAYS blocking, whatever severity the model wrote. The model can raise a
    severity (warning -> blocking) but never lower it
  * the verdict is derived by code: any blocking finding gives `needs_rework`, otherwise `ready`. The model never states a verdict,
    and a finding can never be dropped because its ids are wrong: invalid evidence ids are removed from the finding and noted
  * every id in the output is checked against the input; a target that does not resolve is kept and marked unresolved
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from app.synthesis.schema import SECTION_KEYS

MIN_BLOCKING = frozenset({
    "unsupported_claim", "incorrect_citation", "causal_from_observational", "dq_issue_ignored", "recommendation_as_fact",
    "narrative_inconsistent_with_facts", "contradiction_ignored"})
SEVERITY_ORDER = {"info": 0, "warning": 1, "blocking": 2}


def enforce_findings(findings: Sequence[Mapping[str, Any]], *, evidence_ids: Collection[str], claim_ids: Collection[str],
                     criteria_count: int) -> list[dict[str, Any]]:
    """The findings with enforced severities, validated ids and the model's original severity kept for the audit trail."""
    out = []
    for f in findings:
        model_severity = f["severity"]
        severity = "blocking" if f["category"] in MIN_BLOCKING else model_severity
        valid_ids = [e for e in f["evidence_ids"] if e in evidence_ids]
        removed = [e for e in f["evidence_ids"] if e not in evidence_ids]
        ttype, target = f["target_type"], f["target_id"]
        resolved = (target in claim_ids if ttype == "claim" else target in SECTION_KEYS if ttype == "section"
                    else target.isdigit() and int(target) < criteria_count if ttype == "criterion" else target == "synthesis")
        notes = []
        if severity != model_severity:
            notes.append(f"severity raised from {model_severity} to {severity} by the minimum-severity rule")
        if removed:
            notes.append(f"{len(removed)} evidence id(s) not in the input were removed")
        if not resolved:
            notes.append("the target does not resolve to a claim, section, criterion or the synthesis")
        out.append({"category": f["category"], "severity": severity, "severity_model": model_severity, "target_type": ttype,
                    "target_id": target, "rationale": f["rationale"], "evidence_ids": valid_ids, "target_resolved": resolved,
                    "notes": notes})
    return out


def derive_verdict(findings: Sequence[Mapping[str, Any]]) -> str:
    """needs_rework if any finding is blocking, otherwise ready. Derived by code, never by the model (D5-09)."""
    return "needs_rework" if any(f["severity"] == "blocking" for f in findings) else "ready"


__all__ = ["MIN_BLOCKING", "SEVERITY_ORDER", "derive_verdict", "enforce_findings"]
