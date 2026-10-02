"""Decision Canvas and evidence input validation (docs/decision-canvas.md section 3). Pure, no I/O."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date

from app.domain.errors import InvalidInput

RISK_LEVELS = ("low", "medium", "high")
EVIDENCE_TYPES = ("behavioral", "experiment", "customer", "financial", "market", "anecdotal")
STANCES = ("supports", "contradicts", "neutral")
GRADES = ("A", "B", "C", "D")
DIRECTION_WORDS = ("increase", "decrease", "reduce", "improve")


def validate_canvas(fields: Mapping, *, decision_types: Collection[str], today: date, check_due_date: bool = True) -> None:
    """Block-level rules CV-1, CV-4, CV-5, CV-6 for the fields present in `fields` (all fields on creation)."""
    errors: dict[str, str] = {}
    if "title" in fields:
        t = (fields["title"] or "").strip()
        if not 1 <= len(t) <= 120:
            errors["title"] = "title must be 1-120 characters"
    if "description" in fields and not (fields["description"] or "").strip():
        errors["description"] = "description is required"
    if "hypothesis" in fields:
        h = (fields["hypothesis"] or "").strip()
        if not 1 <= len(h) <= 500:
            errors["hypothesis"] = "hypothesis must be 1-500 characters"
    if "risk_level" in fields and fields["risk_level"] not in RISK_LEVELS:
        errors["risk_level"] = f"risk_level must be one of {RISK_LEVELS}"
    if "decision_type" in fields and fields["decision_type"] not in decision_types:
        errors["decision_type"] = f"decision_type must be one of {sorted(decision_types)}"
    if "change_my_mind_criteria" in fields:
        c = fields["change_my_mind_criteria"]
        if not isinstance(c, list) or not 1 <= len(c) <= 5 or any(
                not isinstance(x, str) or not 10 <= len(x) <= 300 for x in c):
            errors["change_my_mind_criteria"] = "1-5 criteria, each 10-300 characters"
    if check_due_date and "decision_due_date" in fields:
        due = fields["decision_due_date"]
        if not isinstance(due, date) or due < today:
            errors["decision_due_date"] = f"decision_due_date must be on or after {today.isoformat()}"
    if errors:
        raise InvalidInput("The decision canvas is invalid.", detail={"fields": errors})


def canvas_warnings(hypothesis: str, metric_name: str, metric_has_data_source: bool) -> list[dict]:
    """Warn-level rules CV-2 and CV-3 (never block)."""
    out = []
    low = hypothesis.lower()
    if metric_name.lower() not in low and not any(w in low for w in DIRECTION_WORDS):
        out.append({"code": "CV-2", "message": "The hypothesis does not name a measurable outcome (the success metric or "
                                                "a direction word such as increase, decrease, reduce, improve)."})
    if not metric_has_data_source:
        out.append({"code": "CV-3", "message": "Quantitative evidence will depend on manually linked evidence "
                                                "(the success metric has no linked data source)."})
    return out


def validate_evidence(fields: Mapping) -> None:
    errors: dict[str, str] = {}
    if "evidence_type" in fields and fields["evidence_type"] not in EVIDENCE_TYPES:
        errors["evidence_type"] = f"evidence_type must be one of {EVIDENCE_TYPES}"
    if "stance" in fields and fields["stance"] not in STANCES:
        errors["stance"] = f"stance must be one of {STANCES}"
    if "strength_grade" in fields and fields["strength_grade"] not in GRADES:
        errors["strength_grade"] = f"strength_grade must be one of {GRADES}"
    if "summary" in fields and not (fields["summary"] or "").strip():
        errors["summary"] = "summary is required"
    s, e = fields.get("observed_start"), fields.get("observed_end")
    if s is not None and e is not None and e < s:
        errors["observed_end"] = "observed_end must not be before observed_start"
    lo, hi = fields.get("ci_low"), fields.get("ci_high")
    if lo is not None and hi is not None and lo > hi:
        errors["ci_low"] = "ci_low must not exceed ci_high"
    n = fields.get("n_sample")
    if n is not None and n < 0:
        errors["n_sample"] = "n_sample must be >= 0"
    if errors:
        raise InvalidInput("The evidence item is invalid.", detail={"fields": errors})
