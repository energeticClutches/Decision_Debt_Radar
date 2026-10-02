"""Response models and presenters. A numeric DDI is only ever present for a SCORED assessment (BR-4, AC-35)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain import lifecycle as lifecycle_rules
from app.domain.ddi.engine import POSITIONING
from app.domain.nbe import NOTE as NBE_NOTE

SYNTHETIC_NOTICE = "Synthetic data: FitConnect is a fictional company."


def _f(x) -> float | None:
    return None if x is None else float(x)


def _s(x) -> str | None:
    return None if x is None else str(x)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    team_id: str | None
    team_name: str | None = None
    notice: str = "Demo identity only: this role switcher is not authentication."


class AssessmentSummary(BaseModel):
    id: str
    version: int
    state: str
    is_current: bool
    historical: bool = False
    ddi: float | None
    band: str | None
    evidence_direction: str | None
    created_at: datetime


class DecisionOut(BaseModel):
    id: str
    org_id: str
    team_id: str
    owner_id: str
    title: str
    description: str
    hypothesis: str
    success_metric_id: str
    decision_due_date: date
    risk_level: str
    current_evidence_notes: str | None
    change_my_mind_criteria: list[str]
    decision_type: str
    lifecycle_stage: str
    lifecycle_label: str
    assessment_stale: bool
    canvas_completed_at: datetime
    canvas_locked_at: datetime | None
    is_synthetic: bool
    synthetic_notice: str | None
    created_at: datetime
    updated_at: datetime
    warnings: list[dict] = []
    current_assessment: AssessmentSummary | None = None
    previous_scored_assessment: AssessmentSummary | None = None


class EvidenceOut(BaseModel):
    id: str
    decision_id: str
    evidence_source_id: str
    evidence_type: str
    summary: str
    stance: str
    strength_grade: str
    observed_start: date
    observed_end: date
    n_sample: int | None
    effect_size: float | None
    ci_low: float | None
    ci_high: float | None
    metric_id: str | None
    experiment_id: str | None
    insight_id: str | None
    created_by: str
    is_synthetic: bool
    created_at: datetime
    updated_at: datetime


class AssessmentOut(BaseModel):
    id: str
    decision_id: str
    version: int
    state: str
    is_current: bool
    is_superseded: bool
    historical: bool = False
    ddi: float | None
    band: str | None
    uncapped_ddi: float | None
    cap_applied: bool | None
    support: float | None
    penalty_multiplier: float | None
    dimensions: list[dict[str, Any]]
    penalties: list[dict[str, Any]]
    sensitivity: dict[str, Any] | None
    blocking_reasons: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    what_drove_this_result: str | None
    evidence_direction: dict[str, Any] | None
    params: dict[str, Any]
    as_of_date: date
    narrative: str | None
    positioning: str
    insufficient_evidence_label: str | None
    is_synthetic: bool
    synthetic_notice: str | None
    created_at: datetime
    previous_scored_assessment: AssessmentSummary | None = None


class RecommendationOut(BaseModel):
    id: str
    assessment_id: str
    rank: int
    action_type: str
    description: str
    why_this: str | None
    group: str
    effort_days: float
    expected_reduction: float
    potential_ddi_reduction: float
    blockers_resolved: int
    impact: float
    impact_unit: str
    relevance: float
    priority_score: float
    dimensions_addressed: list[str]
    status: str
    human_note: str | None
    note: str


class ReviewOut(BaseModel):
    id: str
    assessment_id: str
    reviewer_type: str
    reviewer_id: str | None
    verdict: str
    human_response: str | None
    created_at: datetime


class DecisionRecordOut(BaseModel):
    id: str
    decision_id: str
    decided_by: str
    outcome: str
    rationale: str
    acknowledged_risk: bool
    decided_at: datetime
    lifecycle_stage: str
    lifecycle_label: str


class DqCheckOut(BaseModel):
    id: str
    assessment_id: str
    data_source_id: str
    check_type: str
    severity: str
    finding: str
    status: str
    resolved_by: str | None
    resolved_at: datetime | None


class AuditOut(BaseModel):
    id: str
    ts: datetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


# ---------------------------------------------------------------- presenters


def user_out(u, team_name: str | None = None) -> dict:
    return {"id": str(u.id), "name": u.name, "email": u.email, "role": u.role,
            "team_id": _s(u.team_id), "team_name": team_name}


def assessment_summary(a, *, is_current: bool, historical: bool = False) -> dict:
    scored = a.state == "scored"
    direction = (a.dimension_scores or {}).get("evidence_direction") or {}
    return {"id": str(a.id), "version": a.version, "state": a.state, "is_current": is_current, "historical": historical,
            "ddi": _f(a.ddi_score) if scored else None, "band": a.ddi_band if scored else None,
            "evidence_direction": direction.get("label"), "created_at": a.created_at}


def decision_out(d, *, warnings: list[dict] | None = None, current=None, previous=None) -> dict:
    return {
        "id": str(d.id), "org_id": str(d.org_id), "team_id": str(d.team_id), "owner_id": str(d.owner_id),
        "title": d.title, "description": d.description, "hypothesis": d.hypothesis,
        "success_metric_id": str(d.success_metric_id), "decision_due_date": d.decision_due_date,
        "risk_level": d.risk_level, "current_evidence_notes": d.current_evidence_notes,
        "change_my_mind_criteria": list(d.change_my_mind_criteria), "decision_type": d.decision_type,
        "lifecycle_stage": d.lifecycle_stage, "lifecycle_label": lifecycle_rules.label(d.lifecycle_stage),
        "assessment_stale": d.assessment_stale, "canvas_completed_at": d.canvas_completed_at,
        "canvas_locked_at": d.canvas_locked_at, "is_synthetic": d.is_synthetic,
        "synthetic_notice": SYNTHETIC_NOTICE if d.is_synthetic else None,
        "created_at": d.created_at, "updated_at": d.updated_at, "warnings": warnings or [],
        "current_assessment": assessment_summary(current, is_current=True) if current is not None else None,
        "previous_scored_assessment": (assessment_summary(previous, is_current=False, historical=True)
                                       if previous is not None else None),
    }


def evidence_out(e) -> dict:
    return {"id": str(e.id), "decision_id": str(e.decision_id), "evidence_source_id": str(e.evidence_source_id),
            "evidence_type": e.evidence_type, "summary": e.summary, "stance": e.stance, "strength_grade": e.strength_grade,
            "observed_start": e.observed_start, "observed_end": e.observed_end, "n_sample": e.n_sample,
            "effect_size": _f(e.effect_size), "ci_low": _f(e.ci_low), "ci_high": _f(e.ci_high),
            "metric_id": _s(e.metric_id), "experiment_id": _s(e.experiment_id), "insight_id": _s(e.insight_id),
            "created_by": e.created_by, "is_synthetic": e.is_synthetic, "created_at": e.created_at,
            "updated_at": e.updated_at}


def assessment_panel(a, *, is_current: bool, is_superseded: bool, historical: bool = False, previous=None) -> dict:
    """The full DDI panel payload. Everything numeric comes from the stored row. Non-scored states carry no number."""
    scored = a.state == "scored"
    ds = a.dimension_scores or {}
    ps = a.penalty_scores or {}
    sens = a.sensitivity or {}
    dims = list((ds.get("dimensions") or {}).values()) if scored else []
    pens = list((ps.get("penalties") or {}).values()) if scored else []
    return {
        "id": str(a.id), "decision_id": str(a.decision_id), "version": a.version, "state": a.state,
        "is_current": is_current, "is_superseded": is_superseded, "historical": historical,
        "ddi": _f(a.ddi_score) if scored else None, "band": a.ddi_band if scored else None,
        "uncapped_ddi": ds.get("uncapped_ddi") if scored else None, "cap_applied": ds.get("cap_applied") if scored else None,
        "support": ds.get("support") if scored else None,
        "penalty_multiplier": ds.get("penalty_multiplier") if scored else None,
        "dimensions": dims, "penalties": pens, "sensitivity": sens if (scored and sens) else None,
        "blocking_reasons": list(a.blocking_reasons or []), "warnings": list(ds.get("warnings") or []),
        "what_drove_this_result": ds.get("what_drove_this_result") if scored else None,
        "evidence_direction": ds.get("evidence_direction"),
        "params": {"ddi_params_version": a.params_version, "ddi_params_hash": a.params_hash,
                   "nbe_params_version": a.nbe_params_version, "nbe_params_hash": a.nbe_params_hash},
        "as_of_date": a.as_of_date, "narrative": a.narrative if a.state != "partial" else None,
        "positioning": POSITIONING,
        "insufficient_evidence_label": ("INSUFFICIENT EVIDENCE" if a.state == "insufficient_evidence"
                                        else "PARTIAL ASSESSMENT" if a.state == "partial" else None),
        "is_synthetic": a.is_synthetic, "synthetic_notice": SYNTHETIC_NOTICE if a.is_synthetic else None,
        "created_at": a.created_at,
        "previous_scored_assessment": (assessment_summary(previous, is_current=False, historical=True)
                                       if previous is not None else None),
    }


def recommendation_out(r, rank: int) -> dict:
    parts = (r.description or "").split("\n", 1)
    why = parts[1].removeprefix("Why this: ") if len(parts) > 1 else None
    unblock = r.blockers_resolved > 0
    return {"id": str(r.id), "assessment_id": str(r.assessment_id), "rank": rank, "action_type": r.action_type,
            "description": parts[0], "why_this": why, "group": "unblock_scoring" if unblock else "reduce_debt",
            "effort_days": float(r.effort_days), "expected_reduction": float(r.expected_reduction),
            "potential_ddi_reduction": float(r.expected_reduction), "blockers_resolved": r.blockers_resolved,
            "impact": float(r.blockers_resolved) if unblock else float(r.expected_reduction),
            "impact_unit": "blockers_resolved" if unblock else "ddi_points", "relevance": float(r.relevance),
            "priority_score": float(r.priority_score), "dimensions_addressed": list(r.dimensions_addressed),
            "status": r.status, "human_note": r.human_note, "note": NBE_NOTE}


def review_out(r) -> dict:
    return {"id": str(r.id), "assessment_id": str(r.assessment_id), "reviewer_type": r.reviewer_type,
            "reviewer_id": _s(r.reviewer_id), "verdict": r.verdict, "human_response": r.human_response,
            "created_at": r.created_at}


def record_out(rec, decision) -> dict:
    return {"id": str(rec.id), "decision_id": str(rec.decision_id), "decided_by": str(rec.decided_by),
            "outcome": rec.outcome, "rationale": rec.rationale, "acknowledged_risk": rec.acknowledged_risk,
            "decided_at": rec.decided_at, "lifecycle_stage": decision.lifecycle_stage,
            "lifecycle_label": lifecycle_rules.label(decision.lifecycle_stage)}


def dq_out(c) -> dict:
    return {"id": str(c.id), "assessment_id": str(c.assessment_id), "data_source_id": str(c.data_source_id),
            "check_type": c.check_type, "severity": c.severity, "finding": c.finding, "status": c.status,
            "resolved_by": _s(c.resolved_by), "resolved_at": c.resolved_at}


def audit_out(a) -> dict:
    return {"id": str(a.id), "ts": a.ts, "actor_type": a.actor_type, "actor_id": _s(a.actor_id), "action": a.action,
            "entity_type": a.entity_type, "entity_id": _s(a.entity_id), "before": a.before, "after": a.after}
