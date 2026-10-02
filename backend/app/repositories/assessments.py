from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DecisionAssessment


def max_version(session: Session, decision_id: uuid.UUID) -> int:
    return session.execute(select(func.coalesce(func.max(DecisionAssessment.version), 0))
                           .where(DecisionAssessment.decision_id == decision_id)).scalar_one()


def add_assessment(session: Session, **fields) -> DecisionAssessment:
    a = DecisionAssessment(**fields)
    session.add(a)
    session.flush()
    session.refresh(a)
    return a


def get_assessment(session: Session, assessment_id: uuid.UUID) -> DecisionAssessment | None:
    return session.get(DecisionAssessment, assessment_id)


def list_assessments(session: Session, decision_id: uuid.UUID) -> list[DecisionAssessment]:
    """Newest version first."""
    return list(session.scalars(select(DecisionAssessment).where(DecisionAssessment.decision_id == decision_id)
                                .order_by(DecisionAssessment.version.desc())))


def current_assessment(session: Session, decision_id: uuid.UUID) -> DecisionAssessment | None:
    """The highest version is current, including a partial one (R7). There is no silent fallback."""
    return session.scalars(select(DecisionAssessment).where(DecisionAssessment.decision_id == decision_id)
                           .order_by(DecisionAssessment.version.desc()).limit(1)).first()


def previous_scored(session: Session, decision_id: uuid.UUID, below_version: int) -> DecisionAssessment | None:
    """The latest scored version below `below_version`, exposed only as historical (R7)."""
    return session.scalars(select(DecisionAssessment).where(
        DecisionAssessment.decision_id == decision_id, DecisionAssessment.version < below_version,
        DecisionAssessment.state == "scored").order_by(DecisionAssessment.version.desc()).limit(1)).first()
