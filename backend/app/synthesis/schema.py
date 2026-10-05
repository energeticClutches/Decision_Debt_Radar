"""Output schemas of the Evidence Synthesis and the Reviewer (docs/day-5-implementation-brief.md sections 6.1 and 7).

Strict structural validation of the parsed model output. A violation raises OutputSchemaError (the synthesis then gets its one
repair attempt, the Reviewer fails). Semantic rules (citations, types, stance, scope, numbers, recommendation language) are in
app.synthesis.validators and are applied to claims one by one.
"""

from __future__ import annotations

import json
import re
from typing import Any

CLAIM_TYPES = ("descriptive", "associative", "causal", "financial", "customer", "risk")
STANCES = ("supports", "contradicts", "neutral")
CONFIDENCE = ("low", "medium", "high")
CRITERIA_STATUS = ("met", "not_met", "not_testable")
CONCLUSION_REFS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "P1", "P2", "gate")
SECTION_KEYS = ("summary", "supporting", "contradicting", "uncertainty")

REVIEW_CATEGORIES = (
    "unsupported_claim", "missing_evidence", "incorrect_citation", "contradiction_ignored", "uncertainty_understated",
    "evidence_overstated", "causal_from_observational", "statistical_misinterpretation", "dq_issue_ignored",
    "customer_overgeneralization", "stale_evidence", "conflicting_evidence", "scope_mismatch", "criterion_mismatch",
    "recommendation_as_fact", "narrative_inconsistent_with_facts")
SEVERITIES = ("blocking", "warning", "info")
TARGET_TYPES = ("claim", "section", "criterion", "synthesis")

_LOCAL_ID = re.compile(r"^[A-Za-z0-9_\-]{1,20}$")
_CLAIM_KEYS = {"local_id", "text", "claim_type", "stance", "confidence", "evidence_ids", "conclusion_ref"}
MAX_TEXT = 1200


class OutputSchemaError(ValueError):
    """The model output is not valid JSON or does not match the schema."""


def _loads(raw_text: str) -> Any:
    try:
        return json.loads(raw_text)
    except (ValueError, TypeError) as exc:
        raise OutputSchemaError(f"the output is not valid JSON: {exc}") from exc


def _text(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > MAX_TEXT * 4:
        raise OutputSchemaError(f"{where} must be a non-empty string")
    return value


def _ids(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise OutputSchemaError(f"{where} must be a list of non-empty strings")
    return list(dict.fromkeys(value))


def parse_synthesis(raw_text: str) -> dict[str, Any]:
    data = _loads(raw_text)
    keys = {"claims", "uncertainties", "gaps", "criteria_assessment", "sections"}
    if not isinstance(data, dict) or set(data) != keys:
        raise OutputSchemaError(f"the output must be an object with exactly the keys {sorted(keys)}")
    claims, seen = [], set()
    if not isinstance(data["claims"], list):
        raise OutputSchemaError("claims must be a list")
    for i, c in enumerate(data["claims"]):
        if not isinstance(c, dict) or set(c) != _CLAIM_KEYS:
            raise OutputSchemaError(f"claims[{i}] must have exactly the keys {sorted(_CLAIM_KEYS)}")
        lid = c["local_id"]
        if not isinstance(lid, str) or not _LOCAL_ID.match(lid) or lid in seen:
            raise OutputSchemaError(f"claims[{i}].local_id must be a unique short identifier")
        seen.add(lid)
        if c["claim_type"] not in CLAIM_TYPES or c["stance"] not in STANCES or c["confidence"] not in CONFIDENCE:
            raise OutputSchemaError(f"claims[{i}]: claim_type, stance or confidence has an invalid value")
        if c["conclusion_ref"] is not None and not isinstance(c["conclusion_ref"], str):
            raise OutputSchemaError(f"claims[{i}].conclusion_ref must be a string")
        claims.append({"local_id": lid, "text": _text(c["text"], f"claims[{i}].text"), "claim_type": c["claim_type"],
                       "stance": c["stance"], "confidence": c["confidence"], "evidence_ids": _ids(c["evidence_ids"], f"claims[{i}].evidence_ids"),
                       "conclusion_ref": c["conclusion_ref"]})
    uncertainties = []
    if not isinstance(data["uncertainties"], list):
        raise OutputSchemaError("uncertainties must be a list")
    for i, u in enumerate(data["uncertainties"]):
        if not isinstance(u, dict) or set(u) != {"text", "evidence_ids"}:
            raise OutputSchemaError(f"uncertainties[{i}] must have exactly the keys text and evidence_ids")
        uncertainties.append({"text": _text(u["text"], f"uncertainties[{i}].text"),
                              "evidence_ids": _ids(u["evidence_ids"], f"uncertainties[{i}].evidence_ids")})
    gaps = []
    if not isinstance(data["gaps"], list):
        raise OutputSchemaError("gaps must be a list")
    for i, g in enumerate(data["gaps"]):
        if not isinstance(g, dict) or set(g) != {"text", "gap_type"}:
            raise OutputSchemaError(f"gaps[{i}] must have exactly the keys text and gap_type")
        gaps.append({"text": _text(g["text"], f"gaps[{i}].text"), "gap_type": _text(g["gap_type"], f"gaps[{i}].gap_type")})
    criteria = []
    if not isinstance(data["criteria_assessment"], list):
        raise OutputSchemaError("criteria_assessment must be a list")
    for i, c in enumerate(data["criteria_assessment"]):
        if (not isinstance(c, dict) or set(c) != {"criterion_index", "status", "evidence_ids"}
                or isinstance(c["criterion_index"], bool) or not isinstance(c["criterion_index"], int)
                or c["status"] not in CRITERIA_STATUS):
            raise OutputSchemaError(f"criteria_assessment[{i}] must have criterion_index (integer), status and evidence_ids")
        criteria.append({"criterion_index": c["criterion_index"], "status": c["status"],
                         "evidence_ids": _ids(c["evidence_ids"], f"criteria_assessment[{i}].evidence_ids")})
    sections = data["sections"]
    if not isinstance(sections, dict) or set(sections) != set(SECTION_KEYS):
        raise OutputSchemaError(f"sections must have exactly the keys {list(SECTION_KEYS)}")
    return {"claims": claims, "uncertainties": uncertainties, "gaps": gaps, "criteria_assessment": criteria,
            "sections": {k: _text(sections[k], f"sections.{k}", allow_empty=True) for k in SECTION_KEYS}}


def parse_review(raw_text: str) -> list[dict[str, Any]]:
    """The findings of the Reviewer. Unknown categories or severities are a schema error (the review then fails, it is never
    guessed)."""
    data = _loads(raw_text)
    if not isinstance(data, dict) or set(data) != {"findings"} or not isinstance(data["findings"], list):
        raise OutputSchemaError('the output must be an object with exactly one key, "findings" (a list)')
    out = []
    keys = {"category", "severity", "target_type", "target_id", "rationale", "evidence_ids"}
    for i, f in enumerate(data["findings"]):
        if not isinstance(f, dict) or set(f) != keys:
            raise OutputSchemaError(f"findings[{i}] must have exactly the keys {sorted(keys)}")
        if f["category"] not in REVIEW_CATEGORIES or f["severity"] not in SEVERITIES or f["target_type"] not in TARGET_TYPES:
            raise OutputSchemaError(f"findings[{i}]: category, severity or target_type is not in the closed list")
        target = f["target_id"]
        if isinstance(target, bool) or not isinstance(target, (str, int)) or str(target) == "":
            raise OutputSchemaError(f"findings[{i}].target_id must be a non-empty string")
        out.append({"category": f["category"], "severity": f["severity"], "target_type": f["target_type"], "target_id": str(target),
                    "rationale": _text(f["rationale"], f"findings[{i}].rationale"), "evidence_ids": _ids(f["evidence_ids"], f"findings[{i}].evidence_ids")})
    return out


__all__ = ["CLAIM_TYPES", "CONCLUSION_REFS", "CONFIDENCE", "CRITERIA_STATUS", "OutputSchemaError", "REVIEW_CATEGORIES", "SECTION_KEYS",
           "SEVERITIES", "STANCES", "TARGET_TYPES", "parse_review", "parse_synthesis"]
