from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import (
    assessment_service,
    dq_service,
    get_actor,
    get_session,
    recommendation_service,
    review_service,
)
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.schemas import requests as rq
from app.schemas.responses import (
    AssessmentOut,
    DqCheckOut,
    RecommendationOut,
    ReviewOut,
    assessment_panel,
    dq_out,
    recommendation_out,
    review_out,
)
from app.services import AssessmentService, DqService, RecommendationService, ReviewService

router = APIRouter(tags=["assessments"])


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: str, actor: Actor = Depends(get_actor),
                   svc: AssessmentService = Depends(assessment_service), session: Session = Depends(get_session)):
    row = svc.get(actor, assessment_id)
    current = assessments_repo.current_assessment(session, row.decision_id)
    is_current = current is not None and current.id == row.id
    previous = None
    if is_current and row.state == "partial":
        previous = assessments_repo.previous_scored(session, row.decision_id, row.version)
    historical = (current is not None and current.state == "partial" and row.state == "scored" and not is_current)
    return assessment_panel(row, is_current=is_current, is_superseded=not is_current, historical=historical,
                            previous=previous)


@router.get("/assessments/{assessment_id}/recommendations", response_model=list[RecommendationOut])
def list_recommendations(assessment_id: str, actor: Actor = Depends(get_actor),
                         svc: RecommendationService = Depends(recommendation_service)):
    return [recommendation_out(r, i + 1) for i, r in enumerate(svc.list_for_assessment(actor, assessment_id))]


@router.post("/assessments/{assessment_id}/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def post_review(assessment_id: str, body: rq.ReviewCreate, actor: Actor = Depends(get_actor),
                svc: ReviewService = Depends(review_service)):
    return review_out(svc.record_human_review(actor, assessment_id, body.verdict, body.human_response))


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationOut)
def patch_recommendation(recommendation_id: str, body: rq.RecommendationPatch, actor: Actor = Depends(get_actor),
                         svc: RecommendationService = Depends(recommendation_service)):
    rec = svc.set_status(actor, recommendation_id, body.status, body.note)
    rows = svc.list_for_assessment(actor, rec.assessment_id)
    rank = next((i + 1 for i, r in enumerate(rows) if r.id == rec.id), 0)
    return recommendation_out(rec, rank)


@router.patch("/dq-checks/{check_id}", response_model=DqCheckOut)
def patch_dq_check(check_id: str, body: rq.DqPatch, actor: Actor = Depends(get_actor),
                   svc: DqService = Depends(dq_service)):
    return dq_out(svc.set_status(actor, check_id, body.status, body.note))
