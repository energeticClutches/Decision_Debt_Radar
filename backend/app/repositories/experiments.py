from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Experiment, ExperimentResult


def list_for_decision(session: Session, decision_id: uuid.UUID) -> list[Experiment]:
    """Experiments are discovered through experiments.decision_id (D4-11)."""
    return list(session.scalars(select(Experiment).where(Experiment.decision_id == decision_id)
                                .order_by(Experiment.start_date, Experiment.id)))


def upsert_results(session: Session, experiment: Experiment, rows: Sequence[Mapping[str, Any]]) -> None:
    """experiment_results: one row per (experiment, variant), updated in place on every re-run (D4-14)."""
    for row in rows:
        values = {"experiment_id": experiment.id, "is_synthetic": experiment.is_synthetic, **row}
        stmt = insert(ExperimentResult).values(**values)
        update = {k: stmt.excluded[k] for k in ("n", "metric_value", "effect_size", "ci_low", "ci_high", "p_value", "srm_flag", "notes")}
        session.execute(stmt.on_conflict_do_update(constraint="uq_experiment_results_variant", set_=update))
    session.flush()


def list_results(session: Session, experiment_id: uuid.UUID) -> list[ExperimentResult]:
    return list(session.scalars(select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
                                .order_by(ExperimentResult.variant).execution_options(populate_existing=True)))
