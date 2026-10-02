"""Test helpers that drive the real services end to end (database tests)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text

from app.core.clock import FixedClock
from app.core.params import get_ddi_params, get_nbe_params
from app.db import models as m
from app.services import (
    AssessmentService,
    AuditService,
    DecisionRecordService,
    DecisionService,
    DqService,
    EvidenceService,
    RecommendationService,
    ReviewService,
    ServiceContext,
)

TODAY = date(2026, 10, 1)


def canvas(seed, **over) -> dict:
    fields = dict(
        title="Flow test decision", description="Created by a test.", hypothesis="If we do X then retention will increase.",
        success_metric_id=seed.metric_d90, decision_due_date=date(2026, 12, 31), risk_level="medium",
        change_my_mind_criteria=["A properly powered test shows less than a 2 point effect"],
        decision_type="product_feature_investment", current_evidence_notes=None, team_id=None, owner_id=None)
    fields.update(over)
    return fields


def evidence_payload(seed, kind: str = "behavioral", **over) -> dict:
    base = dict(summary=f"{kind} evidence", stance="supports", strength_grade="B", observed_start=date(2026, 8, 1),
                observed_end=date(2026, 9, 25), n_sample=None, effect_size=None, ci_low=None, ci_high=None, metric_id=None,
                experiment_id=None, insight_id=None)
    if kind == "behavioral":
        base.update(evidence_type="behavioral", evidence_source_id=str(seed.es["fc_.events"].id), metric_id=seed.metric_d90,
                    n_sample=5000, effect_size=0.03, ci_low=0.02, ci_high=0.04)
    elif kind == "customer":
        base.update(evidence_type="customer", evidence_source_id=str(seed.es["fc_.feedback"].id), n_sample=120)
    elif kind == "financial":
        base.update(evidence_type="financial", evidence_source_id=str(seed.es["fc_.pricing_model_inputs"].id),
                    effect_size=1.2, ci_low=0.8, ci_high=1.6)
    elif kind == "experiment":
        base.update(evidence_type="experiment", evidence_source_id=str(seed.es["fc_.experiment_assignments"].id))
    base.update(over)
    return base


class Flow:
    def __init__(self, session, seed, *, checkpoint=None, clock=None):
        self.session, self.seed = session, seed
        self.ctx = ServiceContext(session, clock or FixedClock(TODAY), get_ddi_params(), get_nbe_params())
        self.decisions = DecisionService(self.ctx)
        self.evidence = EvidenceService(self.ctx)
        self.assessments = AssessmentService(self.ctx, checkpoint=checkpoint)
        self.reviews = ReviewService(self.ctx)
        self.records = DecisionRecordService(self.ctx)
        self.recs = RecommendationService(self.ctx)
        self.dq = DqService(self.ctx)
        self.audit = AuditService(self.ctx)

    # ---- building blocks
    def new_decision(self, **over) -> m.Decision:
        decision, _ = self.decisions.create(self.seed.pm, canvas(self.seed, **over))
        return decision

    def gathered(self, **over) -> m.Decision:
        d = self.new_decision(**over)
        return self.decisions.confirm_evidence(self.seed.pm, d.id)

    def add_evidence(self, decision, *kinds: str, actor=None, **over):
        out = []
        for k in kinds or ("behavioral", "customer", "financial"):
            out.append(self.evidence.add(actor or self.seed.analyst, decision.id, evidence_payload(self.seed, k, **over)))
        return out

    def scored(self) -> tuple[m.Decision, m.DecisionAssessment]:
        d = self.gathered()
        self.add_evidence(d)
        a = self.assessments.run(self.seed.analyst, d.id)
        return d, a

    def insufficient(self) -> tuple[m.Decision, m.DecisionAssessment]:
        d = self.gathered()
        a = self.assessments.run(self.seed.analyst, d.id)
        return d, a

    def to_challenged(self, decision, assessment, verdict="ready", reason=None):
        self.reviews.record_human_review(self.seed.pm, assessment.id, verdict, reason)

    def to_validated(self, decision=None, assessment=None):
        d, a = (decision, assessment) if decision is not None else self.scored()
        self.to_challenged(d, a)
        self.reviews.validate(self.seed.pm, d.id)
        return d, a

    def stage(self, decision) -> str:
        self.session.refresh(decision)
        return decision.lifecycle_stage

    def audit_actions(self, decision) -> list[str]:
        return [a.action for a in self.audit.list_for_decision(self.seed.pm, decision.id)]

    # ---- raw helpers (setup that the services deliberately do not offer)
    def insert_dq_check(self, assessment, data_source_id, severity="critical", status="open", metric_id=None) -> uuid.UUID:
        row = self.session.execute(text(
            "INSERT INTO dq_checks (assessment_id, data_source_id, check_type, severity, finding, affects_metric_id, status,"
            " resolved_by, is_synthetic) VALUES (:a,:ds,'tracking_gap',:sev,'synthetic finding',:mid,:st,:rb,true) RETURNING id"),
            {"a": assessment.id, "ds": data_source_id, "sev": severity, "mid": metric_id, "st": status,
             "rb": uuid.UUID(self.seed.analyst.id) if status == "resolved" else None}).one()
        return row[0]

    def insert_partial_assessment(self, decision, version: int, *, poison: bool = False) -> uuid.UUID:
        """A partial assessment row (Day 4 produces these on a failed stage). `poison` stores bogus numbers that
        no response may ever show."""
        scores = ('{"ddi_display": 61.0, "band": "high", "uncapped_ddi": 61.0, "support": 0.4, '
                  '"dimensions": {"D1": {"score": 0.5}}}') if poison else "{}"
        row = self.session.execute(text(
            "INSERT INTO decision_assessments (decision_id, version, state, dimension_scores, params_version, params_hash,"
            " evidence_fingerprint, as_of_date, is_synthetic) VALUES (:d,:v,'partial',CAST(:s AS jsonb),'ddi_params_v0.1','h','f',"
            "'2026-10-01',true) RETURNING id"), {"d": decision.id, "v": version, "s": scores}).one()
        return row[0]
