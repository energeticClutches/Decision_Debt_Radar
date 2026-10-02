from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DecisionAssessment, DqCheck


def get_dq_check(session: Session, check_id: uuid.UUID) -> DqCheck | None:
    return session.get(DqCheck, check_id)


def decision_id_of(session: Session, check: DqCheck) -> uuid.UUID:
    return session.get(DecisionAssessment, check.assessment_id).decision_id


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[DqCheck]:
    """DQ checks of every assessment version of the decision (earlier versions remain relevant, R5)."""
    return list(session.scalars(select(DqCheck).join(DecisionAssessment, DecisionAssessment.id == DqCheck.assessment_id)
                                .where(DecisionAssessment.decision_id == decision_id)
                                .order_by(DqCheck.created_at, DqCheck.id)))
