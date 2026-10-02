"""Next Best Evidence recommendations: list and status changes (accept / reject / defer + note)."""

from __future__ import annotations

from app.db.models import Recommendation
from app.domain import permissions as perm
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.repositories import recommendations as recs_repo
from app.repositories.users import parse_uuid
from app.services.base import unit_of_work
from app.services.lifecycle import LifecycleHelpers

STATUSES = ("accepted", "rejected", "deferred")


class RecommendationService(LifecycleHelpers):
    def list_for_assessment(self, actor: Actor, assessment_id) -> list[Recommendation]:
        aid = parse_uuid(assessment_id)
        row = assessments_repo.get_assessment(self.session, aid) if aid else None
        if row is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, row.decision_id)
        return recs_repo.list_for_assessment(self.session, row.id)

    def set_status(self, actor: Actor, recommendation_id, status: str, note: str | None) -> Recommendation:
        perm.authorize_role(actor, perm.UPDATE_RECOMMENDATION)
        if status not in STATUSES:
            raise InvalidInput(f"status must be one of {STATUSES}.")
        with unit_of_work(self.session):
            rid = parse_uuid(recommendation_id)
            rec = recs_repo.get_recommendation(self.session, rid) if rid else None
            if rec is None:
                raise NotFound("Recommendation not found.")
            assessment = assessments_repo.get_assessment(self.session, rec.assessment_id)
            decision = self.decision_or_404(actor, assessment.decision_id, lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided: recommendations can no longer change.")
            before = {"status": rec.status, "human_note": rec.human_note}
            rec.status = status
            rec.human_note = (note or "").strip() or None
            self.session.flush()
            self.session.refresh(rec)
            self.audit(actor, "recommendation.status_changed", "recommendation", rec.id, decision, before=before,
                       after={"status": rec.status, "human_note": rec.human_note, "action_type": rec.action_type,
                              "assessment_id": str(rec.assessment_id)})
            return rec
