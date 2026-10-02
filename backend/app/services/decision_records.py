"""Human decision record (BR-10, BR-11, LC-3, LC-AC-4).

Only a human can record a decision, and only on a `validated` decision. `defer` stores the record, returns the
decision to `evidence_gathered` (assessment_stale = true) in the same transaction and never sets `decided`.
Any other outcome stores the final record and moves the decision to `decided`, after which it is immutable.
"""

from __future__ import annotations

from app.db.models import DecisionRecord
from app.domain import permissions as perm
from app.domain.errors import InvalidInput, StateConflict
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.repositories import reviews as reviews_repo
from app.repositories.users import parse_uuid
from app.services.lifecycle import LifecycleHelpers, apply_transition

OUTCOMES = ("approve", "reject", "defer", "approve_conditional")


class DecisionRecordService(LifecycleHelpers):
    def list(self, actor: Actor, decision_id) -> list[DecisionRecord]:
        decision = self.decision_or_404(actor, decision_id)
        return reviews_repo.list_decision_records(self.session, decision.id)

    def record(self, actor: Actor, decision_id, outcome: str, rationale: str, acknowledged_risk: bool) -> DecisionRecord:
        def op() -> DecisionRecord:
            decision = self.decision_or_404(actor, decision_id, lock=True)
            perm.authorize_on_decision(actor, perm.RECORD_DECISION, decision_team_id=str(decision.team_id),
                                       decision_owner_id=str(decision.owner_id))
            if outcome not in OUTCOMES:
                raise InvalidInput(f"outcome must be one of {OUTCOMES}.")
            if decision.lifecycle_stage != "validated":
                raise StateConflict(f"A decision can only be recorded at stage 'validated' (the decision is "
                                    f"'{decision.lifecycle_stage}').", detail={"lifecycle_stage": decision.lifecycle_stage})
            if not (rationale or "").strip():
                raise InvalidInput("A rationale is required.")
            current = assessments_repo.current_assessment(self.session, decision.id)
            needs_ack = current is None or current.state != "scored" or current.ddi_band in ("high", "critical")
            if needs_ack and not acknowledged_risk:
                raise InvalidInput("BR-11: a High/Critical band or an insufficient-evidence assessment requires an "
                                   "explicit risk acknowledgement.", detail={"code": "acknowledgement_required"})
            record = reviews_repo.add_decision_record(
                self.session, decision_id=decision.id, decided_by=parse_uuid(actor.id), outcome=outcome,
                rationale=rationale.strip(), acknowledged_risk=bool(acknowledged_risk), is_synthetic=decision.is_synthetic)
            before_stage = decision.lifecycle_stage
            if outcome == "defer":
                apply_transition(self.session, decision, "evidence_gathered")
                action = "decision.deferred"
            else:
                apply_transition(self.session, decision, "decided")
                action = "decision.recorded"
            self.audit(actor, action, "decision_record", record.id, decision,
                       before={"lifecycle_stage": before_stage},
                       after={"lifecycle_stage": decision.lifecycle_stage, "outcome": outcome,
                              "acknowledged_risk": bool(acknowledged_risk), "assessment_stale": decision.assessment_stale,
                              "assessment_id": str(current.id) if current else None})
            return record
        return self.guarded(actor, decision_id, "record_decision", op)
