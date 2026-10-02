"""Data-quality check status (resolve / accept). DQ is not computed on Day 3: checks arrive with Day-4 analytics.

A status change alters the evidence snapshot (the DQ gate and every item's dq_factor depend on it), so after an
assessment it is handled like an evidence change: the assessment becomes stale and the decision returns to
`evidence_gathered` so the assessment can be re-run (PRD journey J5).
"""

from __future__ import annotations

from app.db.models import DqCheck
from app.domain import permissions as perm
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import dq as dq_repo
from app.repositories.users import parse_uuid
from app.services.base import unit_of_work
from app.services.lifecycle import LifecycleHelpers

STATUSES = ("resolved", "accepted")


class DqService(LifecycleHelpers):
    def get(self, actor: Actor, check_id) -> DqCheck:
        cid = parse_uuid(check_id)
        check = dq_repo.get_dq_check(self.session, cid) if cid else None
        if check is None:
            raise NotFound("Data-quality check not found.")
        self.decision_or_404(actor, dq_repo.decision_id_of(self.session, check))
        return check

    def set_status(self, actor: Actor, check_id, status: str, note: str | None = None) -> DqCheck:
        perm.authorize_role(actor, perm.UPDATE_DQ)
        if status not in STATUSES:
            raise InvalidInput(f"status must be one of {STATUSES}.")
        with unit_of_work(self.session):
            cid = parse_uuid(check_id)
            check = dq_repo.get_dq_check(self.session, cid) if cid else None
            if check is None:
                raise NotFound("Data-quality check not found.")
            decision = self.decision_or_404(actor, dq_repo.decision_id_of(self.session, check), lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided: data-quality checks can no longer change.")
            if check.status != "open":
                raise StateConflict(f"The check is already '{check.status}'.", detail={"status": check.status})
            before = {"status": check.status}
            check.status = status
            check.resolved_by = parse_uuid(actor.id)
            check.resolved_at = self.clock.now()
            self.session.flush()
            self.session.refresh(check)
            self.audit(actor, "dq_check.status_changed", "dq_check", check.id, decision, before=before,
                       after={"status": status, "severity": check.severity, "data_source_id": str(check.data_source_id),
                              "note": (note or "").strip() or None})
            self.mark_stale_if_needed(actor, decision, f"data-quality check {status}")
            return check
