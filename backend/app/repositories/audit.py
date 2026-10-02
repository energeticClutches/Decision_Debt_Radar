from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog


def add_audit(session: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID | None, action: str, entity_type: str,
              entity_id: uuid.UUID | None, decision_id: uuid.UUID | None, before: dict | None, after: dict | None,
              is_synthetic: bool, actor_type: str = "user") -> AuditLog:
    """Insert one audit row. `decision_id` is recorded in `after` so a decision's whole trail can be listed."""
    payload = dict(after or {})
    if decision_id is not None:
        payload.setdefault("decision_id", str(decision_id))
    row = AuditLog(org_id=org_id, actor_type=actor_type, actor_id=actor_id, action=action, entity_type=entity_type,
                   entity_id=entity_id, before=before, after=payload or None, is_synthetic=is_synthetic,
                   ts=func.clock_timestamp())      # strictly ordered even inside one transaction
    session.add(row)
    session.flush()
    return row


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(or_(
        AuditLog.entity_id == decision_id, AuditLog.after["decision_id"].astext == str(decision_id)))
        .order_by(AuditLog.ts, AuditLog.id)))
