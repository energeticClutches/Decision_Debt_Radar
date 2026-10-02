from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult


def add_analysis(session: Session, **fields) -> AnalysisResult:
    """analysis_results rows are historical: inserted once, never updated (except agent_run_id). `created_at` is the
    statement clock so that rows inserted in one transaction are still strictly ordered."""
    row = AnalysisResult(created_at=func.clock_timestamp(), **fields)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_analysis(session: Session, analysis_id: uuid.UUID) -> AnalysisResult | None:
    return session.get(AnalysisResult, analysis_id)


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[AnalysisResult]:
    return list(session.scalars(select(AnalysisResult).where(AnalysisResult.decision_id == decision_id)
                                .order_by(AnalysisResult.created_at, AnalysisResult.id)))


def latest_for_identity(session: Session, decision_id: uuid.UUID, identity: str) -> AnalysisResult | None:
    return session.scalars(select(AnalysisResult).where(AnalysisResult.decision_id == decision_id,
                                                       AnalysisResult.analysis_identity == identity)
                           .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc()).limit(1)
                           .execution_options(populate_existing=True)).first()


def latest_segmentation(session: Session, decision_id: uuid.UUID, metric_id: uuid.UUID) -> AnalysisResult | None:
    """The latest segmentation analysis for the decision's success metric (it feeds heterogeneity_flag)."""
    return session.scalars(select(AnalysisResult).where(AnalysisResult.decision_id == decision_id,
                                                       AnalysisResult.analysis_type == "segmentation",
                                                       AnalysisResult.params["metric_id"].astext == str(metric_id))
                           .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc()).limit(1)
                           .execution_options(populate_existing=True)).first()
