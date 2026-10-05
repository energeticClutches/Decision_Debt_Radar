"""Day-5 endpoints (docs/day-5-implementation-brief.md section 9): customer evidence and its approval, syntheses, briefs.

Permissions: PATCH /evidence/{id}/approval needs ba or product_analyst; POST syntheses and POST briefs need pm or ba; the GET endpoints
are read-only and open to every demo persona. There is no generic agent endpoint: the model is only ever called by the pipeline and by
POST /assessments/{id}/syntheses. The existing human review, validate and decision-record endpoints are unchanged."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.core.deps import (
    brief_service,
    customer_evidence_service,
    get_actor,
    reviewer_service,
    synthesis_service,
)
from app.domain.permissions import Actor
from app.schemas import requests as rq
from app.schemas.responses import (
    BriefOut,
    CustomerEvidenceOut,
    EvidenceOut,
    SynthesisOut,
    SynthesisRunOut,
    brief_out,
    customer_evidence_out,
    evidence_out,
    synthesis_out,
)
from app.services import BriefService, CustomerEvidenceService, ReviewerService, SynthesisService

router = APIRouter(tags=["customer evidence, synthesis and briefs"])


@router.get("/decisions/{decision_id}/customer-evidence", response_model=CustomerEvidenceOut)
def get_customer_evidence(decision_id: str, actor: Actor = Depends(get_actor),
                          svc: CustomerEvidenceService = Depends(customer_evidence_service)):
    return customer_evidence_out(svc.list(actor, decision_id))


@router.patch("/evidence/{evidence_id}/approval", response_model=EvidenceOut)
def patch_evidence_approval(evidence_id: str, body: rq.ApprovalPatch, actor: Actor = Depends(get_actor),
                            svc: CustomerEvidenceService = Depends(customer_evidence_service)):
    return evidence_out(svc.set_approval(actor, evidence_id, body.action, body.note))


@router.post("/assessments/{assessment_id}/syntheses", response_model=SynthesisRunOut)
def post_synthesis(assessment_id: str, response: Response, body: rq.SynthesisCreate | None = None, actor: Actor = Depends(get_actor),
                   svc: SynthesisService = Depends(synthesis_service), reviewer: ReviewerService = Depends(reviewer_service)):
    """Re-synthesis. Idempotent on input_sha256 unless force=true. A new version also gets a new agent review."""
    outcome = svc.synthesize(actor, assessment_id, force=bool(body and body.force))
    response.status_code = status.HTTP_200_OK if outcome.reused else status.HTTP_201_CREATED
    review = None
    if outcome.status == "succeeded" and outcome.synthesis is not None:
        review = reviewer.review(actor, outcome.synthesis.id).summary()
    elif outcome.synthesis is not None:
        review = {"status": "skipped", "reason": f"the synthesis is '{outcome.status}': there is nothing to review"}
    return {"reused": outcome.reused, "synthesis": None if outcome.synthesis is None else synthesis_out(outcome.synthesis),
            "synthesis_status": outcome.status, "review": review}


@router.get("/assessments/{assessment_id}/syntheses", response_model=list[SynthesisOut])
def list_syntheses(assessment_id: str, actor: Actor = Depends(get_actor), svc: SynthesisService = Depends(synthesis_service)):
    return [synthesis_out(s) for s in svc.list(actor, assessment_id)]


@router.post("/assessments/{assessment_id}/briefs", response_model=BriefOut, status_code=status.HTTP_201_CREATED)
def post_brief(assessment_id: str, body: rq.BriefCreate, actor: Actor = Depends(get_actor), svc: BriefService = Depends(brief_service)):
    return brief_out(svc.create(actor, assessment_id, body.kind))


@router.get("/briefs/{brief_id}", response_model=BriefOut)
def get_brief(brief_id: str, actor: Actor = Depends(get_actor), svc: BriefService = Depends(brief_service)):
    return brief_out(svc.get(actor, brief_id))
