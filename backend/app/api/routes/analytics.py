"""Day-4 endpoints: the deterministic pipeline, DQ checks and analyses (docs/day-4-implementation-brief.md section 10).

POST /decisions/{id}/pipeline-runs requires the "run assessment" permission. The three GET endpoints are read-only and,
like every other read in the API, are open to every demo persona (an interpretation noted in day-4-implementation-notes.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import analysis_service, get_actor, get_session, pipeline_service, readmodel_service
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.schemas.responses import (
    AnalysisOut,
    AnalysisSummaryOut,
    DqCheckOut,
    PipelineRunOut,
    analysis_out,
    analysis_summary,
    assessment_panel,
    dq_out,
)
from app.services import AnalysisService, PipelineService, ReadModelService

router = APIRouter(tags=["analytics"])


@router.post("/decisions/{decision_id}/pipeline-runs", response_model=PipelineRunOut, status_code=status.HTTP_201_CREATED)
def run_pipeline(decision_id: str, actor: Actor = Depends(get_actor), svc: PipelineService = Depends(pipeline_service),
                 session: Session = Depends(get_session), rm: ReadModelService = Depends(readmodel_service)):
    result = svc.run(actor, decision_id)
    decision = svc.decision_or_404(actor, decision_id)
    panel = None
    if result.assessment is not None:
        current = assessments_repo.current_assessment(session, decision.id)
        previous = (assessments_repo.previous_scored(session, decision.id, result.assessment.version)
                    if result.assessment.state == "partial" else None)
        panel = assessment_panel(result.assessment, is_current=current is not None and current.id == result.assessment.id,
                                 is_superseded=False, previous=previous)
    return {"decision_id": str(decision.id), "lifecycle_stage": decision.lifecycle_stage, "partial": result.partial,
            "failed_stage": result.failed_stage, "error": result.error, "stages": result.stages,
            "analysis_ids": [str(a) for a in result.analysis_ids], "assessment": panel,
            "pending_approvals": result.pending_approvals,
            "synthesis": rm.annotate_llm_summary(result.synthesis, synthesis=True), "review": rm.annotate_llm_summary(result.review, synthesis=False)}


@router.get("/decisions/{decision_id}/dq-checks", response_model=list[DqCheckOut])
def list_dq_checks(decision_id: str, actor: Actor = Depends(get_actor), svc: AnalysisService = Depends(analysis_service)):
    return [dq_out(c) for c in svc.list_dq_checks(actor, decision_id)]


@router.get("/decisions/{decision_id}/analyses", response_model=list[AnalysisSummaryOut])
def list_analyses(decision_id: str, actor: Actor = Depends(get_actor), svc: AnalysisService = Depends(analysis_service)):
    return [analysis_summary(a) for a in svc.list_analyses(actor, decision_id)]


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: str, actor: Actor = Depends(get_actor), svc: AnalysisService = Depends(analysis_service)):
    row, evidence_ids = svc.get(actor, analysis_id)
    return analysis_out(row, evidence_ids)
