"""Audit trail reads. Writes happen inside the service transaction that changes the state (BR-14)."""

from __future__ import annotations

from app.db.models import AuditLog
from app.domain.permissions import Actor
from app.repositories import audit as audit_repo
from app.services.base import BaseService


class AuditService(BaseService):
    def list_for_decision(self, actor: Actor, decision_id) -> list[AuditLog]:
        decision = self.decision_or_404(actor, decision_id)
        return audit_repo.list_for_decision(self.session, decision.id)
