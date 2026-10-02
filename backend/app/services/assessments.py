"""Assessment execution (R5, R6, R7).

One transaction: BEGIN -> SELECT decision FOR UPDATE -> capture evidence fingerprint -> build EvidenceFacts ->
calculate DDI + NBE -> verify the fingerprint -> insert the completed assessment once -> update the lifecycle ->
audit -> COMMIT. If the fingerprint changed, the run is rejected with 409 and must be repeated.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError

from app.db.models import DecisionAssessment
from app.domain import permissions as perm
from app.domain.ddi import INSUFFICIENT, assess
from app.domain.errors import NotFound, StateConflict
from app.domain.nbe import recommend
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.repositories import recommendations as recs_repo
from app.repositories.evidence_facts import build_facts, evidence_fingerprint
from app.repositories.users import parse_uuid
from app.services.base import ServiceContext
from app.services.lifecycle import LifecycleHelpers, apply_transition


ASSESSMENT_ISOLATION_LEVEL = "READ COMMITTED"   # explicit pin, not the database default


def _narrative(result) -> str:
    if result.scored:
        return result.what_drove or ""
    reasons = "; ".join(r.message for r in result.blocking_reasons)
    return f"INSUFFICIENT EVIDENCE: no DDI is shown. Blocking reasons: {reasons}"


class AssessmentService(LifecycleHelpers):
    def __init__(self, ctx: ServiceContext, *, checkpoint: Callable[[], None] | None = None):
        super().__init__(ctx)
        # Test seam: called after the facts are built and the results calculated, before the fingerprint is verified.
        self._checkpoint = checkpoint

    # ---------------------------------------------------------------- run
    def run(self, actor: Actor, decision_id) -> DecisionAssessment:
        def op() -> DecisionAssessment:
            # Pin the isolation level explicitly (the fingerprint re-check relies on READ COMMITTED seeing
            # concurrent commits). Must be the first use of the connection in this transaction.
            # SQLAlchemy cannot change the level once a transaction has begun (for example after the demo-user lookup);
            # in that case the engine-level pin (app.db.session) applies and the check below verifies it.
            if not self.session.in_transaction():
                try:
                    self.session.connection(execution_options={"isolation_level": ASSESSMENT_ISOLATION_LEVEL})
                except InvalidRequestError:
                    pass      # the bound connection already has an outer transaction (tests); verified below
            actual = self.session.execute(text("SHOW transaction_isolation")).scalar()
            if actual != ASSESSMENT_ISOLATION_LEVEL.lower():
                raise StateConflict(f"Assessment transaction isolation is '{actual}', expected "
                                    f"'{ASSESSMENT_ISOLATION_LEVEL.lower()}'.", detail={"reason": "isolation_level"})
            perm.authorize_role(actor, perm.RUN_ASSESSMENT)
            decision = self.decision_or_404(actor, decision_id, lock=True)          # SELECT ... FOR UPDATE
            if decision.lifecycle_stage != "evidence_gathered":
                raise StateConflict(
                    f"An assessment can only run from stage 'evidence_gathered' (the decision is "
                    f"'{decision.lifecycle_stage}'). Confirm the evidence base, or add/change evidence after a "
                    f"previous assessment, first.", detail={"lifecycle_stage": decision.lifecycle_stage})
            fingerprint = evidence_fingerprint(self.session, decision.id)
            facts = build_facts(self.session, decision.id)
            as_of = self.clock.today()
            result = assess(facts, self.ctx.ddi_params, as_of)
            recs = recommend(result, facts, self.ctx.ddi_params, self.ctx.nbe_params)
            if self._checkpoint:
                self._checkpoint()
            if evidence_fingerprint(self.session, decision.id) != fingerprint:
                raise StateConflict("The evidence changed while the assessment was running. No assessment was stored: "
                                    "please run it again.", detail={"reason": "evidence_changed"})
            version = assessments_repo.max_version(self.session, decision.id) + 1
            row = assessments_repo.add_assessment(
                self.session, decision_id=decision.id, version=version, state=result.state,
                ddi_score=result.ddi if result.scored else None, ddi_band=result.band if result.scored else None,
                dimension_scores=result.dimension_scores_payload(), penalty_scores=result.penalty_scores_payload(),
                blocking_reasons=result.blocking_payload(), sensitivity=result.sensitivity_payload(),
                params_version=self.ctx.ddi_params.version, params_hash=self.ctx.ddi_params.content_hash,
                nbe_params_version=self.ctx.nbe_params.version, nbe_params_hash=self.ctx.nbe_params.content_hash,
                evidence_fingerprint=fingerprint, as_of_date=as_of, narrative=_narrative(result),
                is_synthetic=decision.is_synthetic)
            recs_repo.add_recommendations(self.session, row.id, recs, decision.is_synthetic)
            before_stage = apply_transition(self.session, decision, "assessed", clock=self.clock, lock_canvas=True)
            self.audit(actor, "assessment.completed", "assessment", row.id, decision,
                       before={"lifecycle_stage": before_stage},
                       after={"lifecycle_stage": decision.lifecycle_stage, "assessment_id": str(row.id),
                              "version": version, "state": result.state, "band": result.band,
                              "params_version": row.params_version, "recommendations": len(recs)})
            return row
        return self.guarded(actor, decision_id, "run_assessment", op)

    # ---------------------------------------------------------------- read
    def get(self, actor: Actor, assessment_id) -> DecisionAssessment:
        aid = parse_uuid(assessment_id)
        row = assessments_repo.get_assessment(self.session, aid) if aid else None
        if row is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, row.decision_id)               # org scoping
        return row

    def list(self, actor: Actor, decision_id) -> list[DecisionAssessment]:
        decision = self.decision_or_404(actor, decision_id)
        return assessments_repo.list_assessments(self.session, decision.id)

    def current_and_previous(self, actor: Actor, decision_id):
        """(current, previous_scored). The highest version is current, including partial. If the current one is
        partial, the previous scored version is returned separately as historical (R7). No silent fallback."""
        decision = self.decision_or_404(actor, decision_id)
        current = assessments_repo.current_assessment(self.session, decision.id)
        previous = None
        if current is not None and current.state == "partial":
            previous = assessments_repo.previous_scored(self.session, decision.id, current.version)
        return current, previous


__all__ = ["AssessmentService", "INSUFFICIENT"]
