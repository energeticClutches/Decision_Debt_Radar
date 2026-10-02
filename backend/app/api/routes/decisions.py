from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import (
    assessment_service,
    audit_service,
    decision_service,
    evidence_service,
    get_actor,
    get_session,
    record_service,
    review_service,
)
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.schemas import requests as rq
from app.schemas.responses import (
    AssessmentOut,
    AuditOut,
    DecisionOut,
    DecisionRecordOut,
    EvidenceOut,
    assessment_panel,
    audit_out,
    decision_out,
    evidence_out,
    record_out,
)
from app.services import (
    AssessmentService,
    AuditService,
    DecisionRecordService,
    DecisionService,
    EvidenceService,
    ReviewService,
)

router = APIRouter(tags=["decisions"])


def _view(session: Session, decision, warnings=None) -> dict:
    current = assessments_repo.current_assessment(session, decision.id)
    previous = None
    if current is not None and current.state == "partial":       # R7: historical, exposed separately, never a fallback
        previous = assessments_repo.previous_scored(session, decision.id, current.version)
    return decision_out(decision, warnings=warnings, current=current, previous=previous)


@router.post("/decisions", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
def create_decision(body: rq.CanvasCreate, actor: Actor = Depends(get_actor), svc: DecisionService = Depends(decision_service),
                    session: Session = Depends(get_session)):
    decision, warnings = svc.create(actor, body.model_dump())
    return _view(session, decision, warnings)


@router.get("/decisions", response_model=list[DecisionOut])
def list_decisions(actor: Actor = Depends(get_actor), svc: DecisionService = Depends(decision_service),
                   session: Session = Depends(get_session)):
    return [_view(session, d) for d in svc.list(actor)]


@router.get("/decisions/{decision_id}", response_model=DecisionOut)
def get_decision(decision_id: str, actor: Actor = Depends(get_actor), svc: DecisionService = Depends(decision_service),
                 session: Session = Depends(get_session)):
    return _view(session, svc.get(actor, decision_id))


@router.patch("/decisions/{decision_id}/canvas", response_model=DecisionOut)
def patch_canvas(decision_id: str, body: rq.CanvasPatch, actor: Actor = Depends(get_actor),
                 svc: DecisionService = Depends(decision_service), session: Session = Depends(get_session)):
    return _view(session, svc.edit_canvas(actor, decision_id, body.model_dump(exclude_unset=True)))


@router.post("/decisions/{decision_id}/confirm-evidence", response_model=DecisionOut)
def confirm_evidence(decision_id: str, actor: Actor = Depends(get_actor), svc: DecisionService = Depends(decision_service),
                     session: Session = Depends(get_session)):
    return _view(session, svc.confirm_evidence(actor, decision_id))


@router.post("/decisions/{decision_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def add_evidence(decision_id: str, body: rq.EvidenceCreate, actor: Actor = Depends(get_actor),
                 svc: EvidenceService = Depends(evidence_service)):
    return evidence_out(svc.add(actor, decision_id, body.model_dump()))


@router.get("/decisions/{decision_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(decision_id: str, actor: Actor = Depends(get_actor), svc: EvidenceService = Depends(evidence_service)):
    return [evidence_out(e) for e in svc.list(actor, decision_id)]


@router.post("/decisions/{decision_id}/assessments", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED)
def run_assessment(decision_id: str, actor: Actor = Depends(get_actor),
                   svc: AssessmentService = Depends(assessment_service), session: Session = Depends(get_session)):
    row = svc.run(actor, decision_id)
    return assessment_panel(row, is_current=True, is_superseded=False)


@router.get("/decisions/{decision_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(decision_id: str, actor: Actor = Depends(get_actor),
                     svc: AssessmentService = Depends(assessment_service)):
    rows = svc.list(actor, decision_id)                       # newest first
    latest = rows[0].version if rows else 0
    return [assessment_panel(r, is_current=r.version == latest, is_superseded=r.version < latest,
                             historical=(rows[0].state == "partial" and r.state == "scored" and r.version < latest))
            for r in rows]


@router.post("/decisions/{decision_id}/validate", response_model=DecisionOut)
def validate_decision(decision_id: str, actor: Actor = Depends(get_actor), svc: ReviewService = Depends(review_service),
                      decisions: DecisionService = Depends(decision_service), session: Session = Depends(get_session)):
    svc.validate(actor, decision_id)
    return _view(session, decisions.get(actor, decision_id))


@router.post("/decisions/{decision_id}/decision-record", response_model=DecisionRecordOut,
             status_code=status.HTTP_201_CREATED)
def record_decision(decision_id: str, body: rq.DecisionRecordCreate, actor: Actor = Depends(get_actor),
                    svc: DecisionRecordService = Depends(record_service), decisions: DecisionService = Depends(decision_service)):
    rec = svc.record(actor, decision_id, body.outcome, body.rationale, body.acknowledged_risk)
    return record_out(rec, decisions.get(actor, decision_id))


@router.get("/decisions/{decision_id}/audit", response_model=list[AuditOut])
def decision_audit(decision_id: str, actor: Actor = Depends(get_actor), svc: AuditService = Depends(audit_service)):
    return [audit_out(a) for a in svc.list_for_decision(actor, decision_id)]
