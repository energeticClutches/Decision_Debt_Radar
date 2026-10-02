"""Read access to the analyses and DQ checks of a decision (Day 4). Writes happen in the pipeline."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import AnalysisResult, DqCheck, Evidence
from app.domain.errors import NotFound
from app.domain.permissions import Actor
from app.repositories import analysis as analysis_repo
from app.repositories import dq as dq_repo
from app.repositories.users import parse_uuid
from app.services.base import BaseService


class AnalysisService(BaseService):
    def list_dq_checks(self, actor: Actor, decision_id) -> list[DqCheck]:
        decision = self.decision_or_404(actor, decision_id)
        return dq_repo.list_for_decision(self.session, decision.id)

    def list_analyses(self, actor: Actor, decision_id) -> list[AnalysisResult]:
        decision = self.decision_or_404(actor, decision_id)
        return analysis_repo.list_for_decision(self.session, decision.id)

    def get(self, actor: Actor, analysis_id) -> tuple[AnalysisResult, list[str]]:
        aid = parse_uuid(analysis_id)
        row = analysis_repo.get_analysis(self.session, aid) if aid else None
        if row is None:
            raise NotFound("Analysis not found.")
        self.decision_or_404(actor, row.decision_id)
        evidence_ids = [str(e) for e in self.session.scalars(select(Evidence.id).where(Evidence.analysis_id == row.id)
                                                              .order_by(Evidence.created_at, Evidence.id))]
        return row, evidence_ids
