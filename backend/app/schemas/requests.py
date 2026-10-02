"""Request bodies. Shape and types are checked here (FastAPI returns 422 for a malformed body). The business
validation rules (canvas CV-1..CV-6, evidence rules) live in the domain and are enforced by the services."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

RiskLevel = Literal["low", "medium", "high"]
EvidenceType = Literal["behavioral", "experiment", "customer", "financial", "market", "anecdotal"]
Stance = Literal["supports", "contradicts", "neutral"]
Grade = Literal["A", "B", "C", "D"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasCreate(_Body):
    title: str
    description: str
    hypothesis: str
    success_metric_id: str
    decision_due_date: date
    risk_level: RiskLevel
    change_my_mind_criteria: list[str]
    decision_type: str
    current_evidence_notes: str | None = None
    team_id: str | None = None          # defaults to the actor's team
    owner_id: str | None = None         # defaults to the actor


class CanvasPatch(_Body):
    title: str | None = None
    description: str | None = None
    hypothesis: str | None = None
    success_metric_id: str | None = None
    decision_due_date: date | None = None
    risk_level: RiskLevel | None = None
    change_my_mind_criteria: list[str] | None = None
    decision_type: str | None = None
    current_evidence_notes: str | None = None
    team_id: str | None = None
    owner_id: str | None = None


class EvidenceCreate(_Body):
    evidence_source_id: str
    evidence_type: EvidenceType
    summary: str
    stance: Stance
    strength_grade: Grade
    observed_start: date
    observed_end: date
    n_sample: int | None = None
    effect_size: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    metric_id: str | None = None
    experiment_id: str | None = None
    insight_id: str | None = None


class ReviewCreate(_Body):
    verdict: Literal["ready", "needs_rework"]
    human_response: str | None = None


class DecisionRecordCreate(_Body):
    outcome: Literal["approve", "reject", "defer", "approve_conditional"]
    rationale: str
    acknowledged_risk: bool = False


class RecommendationPatch(_Body):
    status: Literal["accepted", "rejected", "deferred"]
    note: str | None = None


class DqPatch(_Body):
    status: Literal["resolved", "accepted"]
    note: str | None = None
