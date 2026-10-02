"""Lifecycle transitions (docs/decision-lifecycle.md). The database trigger is the backstop for these rules."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.models import Decision
from app.domain import lifecycle as rules
from app.domain.permissions import Actor
from app.repositories import audit as audit_repo
from app.services.base import BaseService


def apply_transition(session: Session, decision: Decision, to_stage: str, *, clock: Clock | None = None,
                     lock_canvas: bool = False) -> str:
    """Move a decision to `to_stage` if the transition is legal. Returns the previous stage.

    - returning to evidence_gathered from a later stage sets assessment_stale (the DB requires it)
    - entering assessed clears assessment_stale and (optionally) locks the canvas at the first assessment
    The caller is responsible for authorization and audit.
    """
    from_stage = decision.lifecycle_stage
    rules.require_legal(from_stage, to_stage)
    if to_stage == "evidence_gathered" and from_stage != "created":
        decision.assessment_stale = True
    if to_stage == "assessed":
        decision.assessment_stale = False
        if lock_canvas and decision.canvas_locked_at is None:
            decision.canvas_locked_at = (clock or _default_clock()).now()
    decision.lifecycle_stage = to_stage
    session.flush()
    session.refresh(decision)
    return from_stage


def _default_clock() -> Clock:
    from app.core.clock import SystemClock
    return SystemClock()


class LifecycleHelpers(BaseService):
    def mark_stale_if_needed(self, actor: Actor, decision: Decision, reason: str) -> bool:
        """Evidence added/changed or a DQ status change after assessment: stale and back to evidence_gathered."""
        if decision.lifecycle_stage not in rules.STALE_RETURN_FROM:
            return False
        before = decision.lifecycle_stage
        apply_transition(self.session, decision, "evidence_gathered")
        self.audit(actor, "assessment.stale", "decision", decision.id, decision,
                   before={"lifecycle_stage": before, "assessment_stale": False},
                   after={"lifecycle_stage": decision.lifecycle_stage, "assessment_stale": True, "reason": reason})
        return True

    def mark_stale_system(self, decision: Decision, reason: str) -> bool:
        """Same rule as mark_stale_if_needed for a change made by deterministic code (automatic DQ status change, generated
        evidence): the audit row has actor_type 'system'."""
        if decision.lifecycle_stage not in rules.STALE_RETURN_FROM:
            return False
        before = decision.lifecycle_stage
        apply_transition(self.session, decision, "evidence_gathered")
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="assessment.stale",
                             entity_type="decision", entity_id=decision.id, decision_id=decision.id,
                             before={"lifecycle_stage": before, "assessment_stale": False},
                             after={"lifecycle_stage": decision.lifecycle_stage, "assessment_stale": True, "reason": reason},
                             is_synthetic=decision.is_synthetic)
        return True

    def note_db_stale_return(self, actor: Actor, decision: Decision, before_stage: str, reason: str) -> bool:
        """The database trigger already returned the decision (canvas edit after the lock). Record the transition."""
        if before_stage in rules.STALE_RETURN_FROM and decision.lifecycle_stage == "evidence_gathered":
            self.audit(actor, "assessment.stale", "decision", decision.id, decision,
                       before={"lifecycle_stage": before_stage, "assessment_stale": False},
                       after={"lifecycle_stage": "evidence_gathered", "assessment_stale": True, "reason": reason})
            return True
        return False
