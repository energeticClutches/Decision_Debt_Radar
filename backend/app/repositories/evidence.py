from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CustomerInsight, Evidence, EvidenceSource, Experiment, Metric


def add_evidence(session: Session, **fields) -> Evidence:
    e = Evidence(**fields)
    session.add(e)
    session.flush()
    session.refresh(e)
    return e


def get_evidence(session: Session, evidence_id: uuid.UUID) -> Evidence | None:
    return session.get(Evidence, evidence_id)


def list_evidence(session: Session, decision_id: uuid.UUID) -> list[Evidence]:
    return list(session.scalars(select(Evidence).where(Evidence.decision_id == decision_id)
                                .order_by(Evidence.created_at, Evidence.id)))


def get_evidence_source(session: Session, source_id: uuid.UUID) -> EvidenceSource | None:
    return session.get(EvidenceSource, source_id)


def get_experiment(session: Session, experiment_id: uuid.UUID) -> Experiment | None:
    return session.get(Experiment, experiment_id)


def get_insight(session: Session, insight_id: uuid.UUID) -> CustomerInsight | None:
    return session.get(CustomerInsight, insight_id)


def get_metric(session: Session, metric_id: uuid.UUID) -> Metric | None:
    return session.get(Metric, metric_id)
