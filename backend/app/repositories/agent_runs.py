from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun


def add_run(session: Session, **fields) -> AgentRun:
    """`created_at` is the statement clock, so runs inserted in one transaction keep their order."""
    row = AgentRun(created_at=func.clock_timestamp(), **fields)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[AgentRun]:
    return list(session.scalars(select(AgentRun).where(AgentRun.decision_id == decision_id)
                                .order_by(AgentRun.created_at, AgentRun.id)))
