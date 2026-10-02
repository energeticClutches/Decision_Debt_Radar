from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DecisionRecord, DecisionReview


def add_review(session: Session, **fields) -> DecisionReview:
    r = DecisionReview(created_at=func.clock_timestamp(), **fields)     # ordered even inside one transaction
    session.add(r)
    session.flush()
    session.refresh(r)
    return r


def list_reviews(session: Session, assessment_id: uuid.UUID) -> list[DecisionReview]:
    """Oldest first (created_at, then id)."""
    return list(session.scalars(select(DecisionReview).where(DecisionReview.assessment_id == assessment_id)
                                .order_by(DecisionReview.created_at, DecisionReview.id)))


def add_decision_record(session: Session, **fields) -> DecisionRecord:
    r = DecisionRecord(decided_at=func.clock_timestamp(), **fields)       # ordered even inside one transaction
    session.add(r)
    session.flush()
    session.refresh(r)
    return r


def list_decision_records(session: Session, decision_id: uuid.UUID) -> list[DecisionRecord]:
    return list(session.scalars(select(DecisionRecord).where(DecisionRecord.decision_id == decision_id)
                                .order_by(DecisionRecord.decided_at, DecisionRecord.id)))
