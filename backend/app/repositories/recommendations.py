from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Recommendation
from app.domain.nbe import Recommendation as RecommendationDraft


def to_row(draft: RecommendationDraft) -> dict:
    """Domain recommendation -> database columns. `potential_ddi_reduction` is stored in `expected_reduction`
    (the column keeps its schema name), priority is stored rounded to 4 decimals for display."""
    return {
        "action_type": draft.action_id,
        "description": f"{draft.description}\nWhy this: {draft.why_this}",
        "effort_days": draft.effort_days,
        "expected_reduction": round(draft.potential_ddi_reduction, 4),
        "relevance": draft.relevance,
        "priority_score": draft.priority_rounded,
        "dimensions_addressed": list(draft.dimensions_addressed),
        "blockers_resolved": draft.blockers_resolved,
    }


def add_recommendations(session: Session, assessment_id: uuid.UUID, drafts: list[RecommendationDraft],
                        is_synthetic: bool) -> list[Recommendation]:
    out = []
    for draft in drafts:
        rec = Recommendation(assessment_id=assessment_id, is_synthetic=is_synthetic, **to_row(draft))
        session.add(rec)
        out.append(rec)
    session.flush()
    for rec in out:
        session.refresh(rec)
    return out


def get_recommendation(session: Session, rec_id: uuid.UUID) -> Recommendation | None:
    return session.get(Recommendation, rec_id)


def list_for_assessment(session: Session, assessment_id: uuid.UUID) -> list[Recommendation]:
    """Display order: scoring blockers first, then priority desc, effort asc, action asc."""
    rows = list(session.scalars(select(Recommendation).where(Recommendation.assessment_id == assessment_id)))
    rows.sort(key=lambda r: (-(1 if r.blockers_resolved > 0 else 0), -float(r.priority_score), float(r.effort_days),
                             r.action_type, r.description))
    return rows
