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


# ---------------------------------------------------------------- Day 4: generated evidence (identity, status, supersede)
def get_active_by_identity(session: Session, decision_id: uuid.UUID, identity: str) -> Evidence | None:
    return session.scalars(select(Evidence).where(Evidence.decision_id == decision_id, Evidence.analysis_identity == identity,
                                                  Evidence.status == "active")
                           .execution_options(populate_existing=True)).first()


def active_in_slot(session: Session, decision_id: uuid.UUID, slot: str, *, except_identity: str) -> list[Evidence]:
    """Active evidence generated from an analysis with the same slot (decision, type, metric, key) but another identity,
    i.e. produced under different analysis parameters."""
    from app.db.models import AnalysisResult
    return list(session.scalars(
        select(Evidence).join(AnalysisResult, AnalysisResult.id == Evidence.analysis_id)
        .where(Evidence.decision_id == decision_id, Evidence.status == "active", Evidence.analysis_identity.is_not(None),
               Evidence.analysis_identity != except_identity, AnalysisResult.params["slot"].astext == slot)
        .order_by(Evidence.id).execution_options(populate_existing=True)))


def evidence_source_by_ref(session: Session, org_id: uuid.UUID, ref: str) -> EvidenceSource | None:
    return session.scalars(select(EvidenceSource).where(EvidenceSource.org_id == org_id, EvidenceSource.ref == ref)
                           .order_by(EvidenceSource.id).limit(1)).first()
