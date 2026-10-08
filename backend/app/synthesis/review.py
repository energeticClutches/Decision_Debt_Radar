"""Reviewer / Critic rules enforced in code (docs/day-5-implementation-brief.md section 7, tests R1, R2, E3).

The model produces findings. Code decides what they mean:
  * minimum severities: the categories in MIN_BLOCKING are ALWAYS blocking, whatever severity the model wrote. The model can raise a
    severity (warning -> blocking) but never lower it
  * the verdict is derived by code: any blocking finding gives `needs_rework`, otherwise `ready`. The model never states a verdict,
    and a finding can never be dropped because its ids are wrong: invalid evidence ids are removed from the finding and noted
  * every id in the output is checked against the input; a target that does not resolve is kept and marked unresolved
  * deterministic critic checks (code_findings) are added to every review, so an omitted contradiction or an ignored critical DQ
    issue is flagged even if the model misses it. Each finding records its `source` (model or code)
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


_DQ_WORDS = ("data quality", "data-quality", "dq ", "dq)", "dq,", "dq.", "instrumentation", "tracking issue")


def code_findings(output: Mapping[str, Any], facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Deterministic critic checks that run on every review, whatever the model returns (source `code`). They catch what can be
    decided from structure alone:
      * contradiction_ignored  an active contradicting evidence item is cited by no claim and no uncertainty
      * dq_issue_ignored       an open critical data-quality finding exists and no synthesis text mentions data quality
      * evidence_overstated    a claim of confidence `high` cites only grade C or D evidence (warning)"""
    claims = list(output.get("claims") or [])
    cited = {e for c in claims for e in c.get("evidence_ids", [])}
    cited |= {e for u in (output.get("uncertainties") or []) for e in u.get("evidence_ids", [])}
    found: list[dict[str, Any]] = []
    for item in facts.get("evidence", []):
        if item.get("stance") == "contradicts" and item["id"] not in cited:
            found.append({"category": "contradiction_ignored", "severity": "blocking", "target_type": "synthesis", "target_id": "synthesis",
                          "rationale": f"The contradicting {item.get('evidence_type')} evidence item is not discussed by any claim or uncertainty.",
                          "evidence_ids": [item["id"]]})
    open_critical = [d for d in facts.get("dq_findings", []) if d.get("severity") == "critical" and d.get("status") == "open"]
    if open_critical:
        texts = [c.get("text", "") for c in claims] + [u.get("text", "") for u in (output.get("uncertainties") or [])]
        texts += [g.get("text", "") for g in (output.get("gaps") or [])] + list((output.get("sections") or {}).values())
        blob = " " + " ".join(texts).lower() + " "
        if not any(w in blob for w in _DQ_WORDS):
            found.append({"category": "dq_issue_ignored", "severity": "blocking", "target_type": "synthesis", "target_id": "synthesis",
                          "rationale": f"{len(open_critical)} open critical data-quality finding(s) are not mentioned anywhere in the synthesis.",
                          "evidence_ids": []})
    grades = {i["id"]: i.get("grade") for i in facts.get("evidence", [])}
    for c in claims:
        if c.get("confidence") == "high" and c.get("evidence_ids") and all(grades.get(e) in ("C", "D") for e in c["evidence_ids"]):
            found.append({"category": "evidence_overstated", "severity": "warning", "target_type": "claim", "target_id": c["local_id"],
                          "rationale": "High confidence is stated on grade C or D evidence only.", "evidence_ids": list(c["evidence_ids"])})
    return found


def derive_verdict(findings: Sequence[Mapping[str, Any]]) -> str:
    """needs_rework if any finding is blocking, otherwise ready. Derived by code, never by the model (D5-09)."""
    return "needs_rework" if any(f["severity"] == "blocking" for f in findings) else "ready"


__all__ = ["MIN_BLOCKING", "SEVERITY_ORDER", "code_findings", "derive_verdict", "enforce_findings"]
