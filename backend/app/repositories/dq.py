from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqCheck


def get_dq_check(session: Session, check_id: uuid.UUID) -> DqCheck | None:
    return session.get(DqCheck, check_id)


def decision_id_of(session: Session, check: DqCheck) -> uuid.UUID:
    """A DQ check belongs to a decision (migration 0005); the assessment link is optional."""
    return check.decision_id


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[DqCheck]:
    """All DQ checks of the decision (they are per decision since Day 4 and updated in place on every run)."""
    return list(session.scalars(select(DqCheck).where(DqCheck.decision_id == decision_id)
                                .order_by(DqCheck.check_key, DqCheck.id)))


def checks_by_key(session: Session, decision_id: uuid.UUID) -> dict[str, DqCheck]:
    return {c.check_key: c for c in session.scalars(
        select(DqCheck).where(DqCheck.decision_id == decision_id).execution_options(populate_existing=True))}


def add_check(session: Session, **fields) -> DqCheck:
    c = DqCheck(**fields)
    session.add(c)
    session.flush()
    session.refresh(c)
    return c
