from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DataSource, Decision, Metric, Team


def get_decision(session: Session, decision_id: uuid.UUID) -> Decision | None:
    return session.get(Decision, decision_id)


def lock_decision(session: Session, decision_id: uuid.UUID) -> Decision | None:
    """SELECT ... FOR UPDATE. Concurrent assessment requests for the same decision serialize on this row lock (R6)."""
    return session.execute(select(Decision).where(Decision.id == decision_id).with_for_update()
                           .execution_options(populate_existing=True)).scalar_one_or_none()


def list_decisions(session: Session, org_id: uuid.UUID) -> list[Decision]:
    return list(session.scalars(select(Decision).where(Decision.org_id == org_id)
                                .order_by(Decision.created_at, Decision.title)))


def add_decision(session: Session, **fields) -> Decision:
    d = Decision(**fields)
    session.add(d)
    session.flush()
    session.refresh(d)
    return d


def get_metric(session: Session, metric_id: uuid.UUID) -> Metric | None:
    return session.get(Metric, metric_id)


def get_team(session: Session, team_id: uuid.UUID) -> Team | None:
    return session.get(Team, team_id)


def get_data_source(session: Session, ds_id: uuid.UUID) -> DataSource | None:
    return session.get(DataSource, ds_id)
