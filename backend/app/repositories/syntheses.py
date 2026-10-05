"""Syntheses, claims and briefs (Day 5). Rows are inserted once and never changed (database triggers enforce it)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, Claim, ClaimEvidence, DecisionBrief, DecisionReview, Synthesis


# ---------------------------------------------------------------- syntheses
def max_version(session: Session, assessment_id: uuid.UUID) -> int:
    return session.execute(select(func.coalesce(func.max(Synthesis.version), 0)).where(Synthesis.assessment_id == assessment_id)).scalar_one()


def add_synthesis(session: Session, **fields) -> Synthesis:
    row = Synthesis(created_at=func.clock_timestamp(), **fields)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_synthesis(session: Session, synthesis_id: uuid.UUID) -> Synthesis | None:
    return session.get(Synthesis, synthesis_id)


def list_syntheses(session: Session, assessment_id: uuid.UUID) -> list[Synthesis]:
    """Oldest version first."""
    return list(session.scalars(select(Synthesis).where(Synthesis.assessment_id == assessment_id).order_by(Synthesis.version)))


def latest_synthesis(session: Session, assessment_id: uuid.UUID, *, status: str | None = None) -> Synthesis | None:
    stmt = select(Synthesis).where(Synthesis.assessment_id == assessment_id)
    if status is not None:
        stmt = stmt.where(Synthesis.status == status)
    return session.scalars(stmt.order_by(Synthesis.version.desc()).limit(1)).first()


# ---------------------------------------------------------------- claims
def add_claim(session: Session, *, assessment_id: uuid.UUID, synthesis_id: uuid.UUID, local_id: str, text: str, claim_type: str,
              stance: str, confidence: str, conclusion_ref: str | None, evidence_ids: Sequence[uuid.UUID], is_synthetic: bool) -> Claim:
    claim = Claim(assessment_id=assessment_id, synthesis_id=synthesis_id, local_id=local_id, claim_text=text, claim_type=claim_type,
                  stance=stance, confidence=confidence, conclusion_ref=conclusion_ref, is_synthetic=is_synthetic)
    session.add(claim)
    session.flush()
    for eid in evidence_ids:
        session.add(ClaimEvidence(claim_id=claim.id, evidence_id=eid, is_synthetic=is_synthetic))
    session.flush()
    session.refresh(claim)
    return claim


def claims_for_synthesis(session: Session, synthesis_id: uuid.UUID) -> list[tuple[Claim, list[uuid.UUID]]]:
    claims = list(session.scalars(select(Claim).where(Claim.synthesis_id == synthesis_id).order_by(Claim.created_at, Claim.local_id)))
    out = []
    for c in claims:
        ids = list(session.scalars(select(ClaimEvidence.evidence_id).where(ClaimEvidence.claim_id == c.id).order_by(ClaimEvidence.evidence_id)))
        out.append((c, ids))
    return out


# ---------------------------------------------------------------- reviews and runs of an assessment
def agent_reviews(session: Session, assessment_id: uuid.UUID) -> list[DecisionReview]:
    return list(session.scalars(select(DecisionReview).where(DecisionReview.assessment_id == assessment_id,
                                                              DecisionReview.reviewer_type == "agent")
                                .order_by(DecisionReview.created_at, DecisionReview.id)))


def agent_review_for_synthesis(session: Session, synthesis_id: uuid.UUID) -> DecisionReview | None:
    return session.scalars(select(DecisionReview).where(DecisionReview.synthesis_id == synthesis_id, DecisionReview.reviewer_type == "agent")
                           .order_by(DecisionReview.created_at.desc(), DecisionReview.id).limit(1)).first()


def llm_failures(session: Session, assessment_id: uuid.UUID, purposes: Sequence[str] = ("synthesize", "review")) -> list[AgentRun]:
    """Failed LLM runs recorded for the assessment (a synthesis or review that did not complete)."""
    return list(session.scalars(select(AgentRun).where(AgentRun.assessment_id == assessment_id, AgentRun.status == "failed",
                                                       AgentRun.purpose.in_(tuple(purposes))).order_by(AgentRun.created_at, AgentRun.id)))


def review_runs(session: Session, assessment_id: uuid.UUID, status: str | None = None) -> list[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.assessment_id == assessment_id, AgentRun.purpose == "review")
    if status is not None:
        stmt = stmt.where(AgentRun.status == status)
    return list(session.scalars(stmt.order_by(AgentRun.created_at, AgentRun.id)))


# ---------------------------------------------------------------- briefs
def max_brief_version(session: Session, assessment_id: uuid.UUID, kind: str) -> int:
    return session.execute(select(func.coalesce(func.max(DecisionBrief.version), 0))
                           .where(DecisionBrief.assessment_id == assessment_id, DecisionBrief.kind == kind)).scalar_one()


def add_brief(session: Session, **fields) -> DecisionBrief:
    row = DecisionBrief(created_at=func.clock_timestamp(), **fields)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_brief(session: Session, brief_id: uuid.UUID) -> DecisionBrief | None:
    return session.get(DecisionBrief, brief_id)


def list_briefs(session: Session, assessment_id: uuid.UUID) -> list[DecisionBrief]:
    return list(session.scalars(select(DecisionBrief).where(DecisionBrief.assessment_id == assessment_id)
                                .order_by(DecisionBrief.kind, DecisionBrief.version)))
