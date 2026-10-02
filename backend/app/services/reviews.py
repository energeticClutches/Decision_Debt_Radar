"""Human review (R12), validation and override.

Day 3 has no Reviewer agent (Day 5). A human review records a verdict and a reason. Rules:

- recording a review moves `assessed` -> `challenged` (later reviews keep the stage);
- a human `needs_rework` verdict needs a non-empty reason;
- OVERRIDE: after a `needs_rework` verdict on the same assessment, a later `ready` verdict is accepted only as a
  human review with a non-empty reason;
- validate (challenged -> validated) requires the latest review verdict `ready`. If any review of the assessment
  was `needs_rework`, the latest review must be a human review with a non-empty reason (the override), which is
  audit-logged as `assessment.override`.
"""

from __future__ import annotations

from app.db.models import DecisionAssessment, DecisionReview
from app.domain import permissions as perm
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.repositories import reviews as reviews_repo
from app.repositories.users import parse_uuid
from app.services.lifecycle import LifecycleHelpers, apply_transition


def _has_reason(review: DecisionReview) -> bool:
    return bool((review.human_response or "").strip())


class ReviewService(LifecycleHelpers):
    def list(self, actor: Actor, assessment_id) -> list[DecisionReview]:
        aid = parse_uuid(assessment_id)
        row = assessments_repo.get_assessment(self.session, aid) if aid else None
        if row is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, row.decision_id)
        return reviews_repo.list_reviews(self.session, row.id)

    # ---------------------------------------------------------------- human review
    def record_human_review(self, actor: Actor, assessment_id, verdict: str, human_response: str | None) -> DecisionReview:
        aid = parse_uuid(assessment_id)
        assessment = assessments_repo.get_assessment(self.session, aid) if aid else None
        decision_id = assessment.decision_id if assessment else None

        def op() -> DecisionReview:
            perm.authorize_role(actor, perm.HUMAN_REVIEW)
            if assessment is None:
                raise NotFound("Assessment not found.")
            decision = self.decision_or_404(actor, decision_id, lock=True)
            if verdict not in ("ready", "needs_rework"):
                raise InvalidInput("verdict must be 'ready' or 'needs_rework'.")
            if decision.lifecycle_stage not in ("assessed", "challenged"):
                raise StateConflict(f"A review can only be recorded at stage 'assessed' or 'challenged' "
                                    f"(the decision is '{decision.lifecycle_stage}').",
                                    detail={"lifecycle_stage": decision.lifecycle_stage})
            current = assessments_repo.current_assessment(self.session, decision.id)
            if current is None or current.id != assessment.id:
                raise StateConflict("Only the current assessment (the highest version) can be reviewed.",
                                    detail={"current_version": current.version if current else None})
            if current.state == "partial":
                raise StateConflict("A partial assessment cannot be reviewed.")
            existing = reviews_repo.list_reviews(self.session, assessment.id)
            reason = (human_response or "").strip()
            if verdict == "needs_rework" and not reason:
                raise InvalidInput("A needs_rework verdict requires a reason (human_response).")
            if verdict == "ready" and any(r.verdict == "needs_rework" for r in existing) and not reason:
                raise InvalidInput("Overriding a needs_rework verdict requires a non-empty reason (human_response, BR-13).")
            review = reviews_repo.add_review(
                self.session, assessment_id=assessment.id, reviewer_type="human", reviewer_id=parse_uuid(actor.id),
                verdict=verdict, challenges=[], human_response=reason or None, is_synthetic=decision.is_synthetic)
            before_stage = decision.lifecycle_stage
            if before_stage == "assessed":
                apply_transition(self.session, decision, "challenged")
            self.audit(actor, "review.completed", "review", review.id, decision,
                       before={"lifecycle_stage": before_stage},
                       after={"lifecycle_stage": decision.lifecycle_stage, "assessment_id": str(assessment.id),
                              "verdict": verdict, "reviewer_type": "human", "has_reason": bool(reason)})
            return review
        return self.guarded(actor, decision_id or aid, "record_review", op)

    # ---------------------------------------------------------------- validate (challenged -> validated)
    def validate(self, actor: Actor, decision_id) -> DecisionAssessment:
        def op() -> DecisionAssessment:
            decision = self.decision_or_404(actor, decision_id, lock=True)
            perm.authorize_on_decision(actor, perm.VALIDATE, decision_team_id=str(decision.team_id),
                                       decision_owner_id=str(decision.owner_id))
            if decision.lifecycle_stage != "challenged":
                raise StateConflict(f"Only a 'challenged' decision can be validated (the decision is "
                                    f"'{decision.lifecycle_stage}').", detail={"lifecycle_stage": decision.lifecycle_stage})
            current = assessments_repo.current_assessment(self.session, decision.id)
            if current is None or current.state == "partial":
                raise StateConflict("The current assessment is missing or partial and cannot be validated.")
            reviews = reviews_repo.list_reviews(self.session, current.id)
            if not reviews:
                raise StateConflict("The current assessment has no review.")
            latest = reviews[-1]
            had_rework = any(r.verdict == "needs_rework" for r in reviews)
            if latest.verdict != "ready":
                raise StateConflict("The latest review verdict is needs_rework. It blocks validation until a human "
                                    "overrides it with a non-empty reason (BR-13).", detail={"code": "needs_rework"})
            override = False
            if had_rework:
                if latest.reviewer_type != "human" or not _has_reason(latest):
                    raise StateConflict("A needs_rework verdict was recorded; validation requires an explicit human "
                                        "review with a non-empty reason (BR-13).", detail={"code": "needs_rework"})
                override = True
            before_stage = apply_transition(self.session, decision, "validated")
            self.audit(actor, "assessment.override" if override else "assessment.validated", "assessment", current.id,
                       decision, before={"lifecycle_stage": before_stage},
                       after={"lifecycle_stage": decision.lifecycle_stage, "assessment_id": str(current.id),
                              "version": current.version, "override": override})
            return current
        return self.guarded(actor, decision_id, "validate", op)
