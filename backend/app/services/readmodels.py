"""Day-6 read models (docs/day-6-implementation-brief.md section 3, N1 to N6). Reads only: nothing here writes, scores or decides.

    reviews          N1  the reviews of an assessment with their findings and provenance
    decision_record  N2  the latest decision record of a decision
    briefs           N3  the briefs of an assessment (no content)
    traceability     N4  the rows of v_traceability_matrix for an assessment, gap rows included
    stale_info       N5  why and when the assessment became stale (the latest stale audit row) and the proposed-item count
    metrics          N6  the metric definitions
    evidence_extras  N6  source name, reliability tier and freshness (v_evidence_freshness) of evidence rows
    run_info             provenance and model of the agent run behind a synthesis, a review or a classification

Provenance (D6-01): `live_model_output` for a real model call, `stub_not_model_output` for a replayed or stubbed fixture,
`recorded_model_output` for a fixture recorded from a live call. It is read from the stored agent run, never inferred by the UI.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain.errors import NotFound
from app.domain.permissions import Actor
from app.repositories import assessments as assessments_repo
from app.repositories import reviews as reviews_repo
from app.repositories import syntheses as syn_repo
from app.repositories.users import parse_uuid
from app.services.base import BaseService

PROVENANCE_LIVE = "live_model_output"
PROVENANCE_STUB = "stub_not_model_output"
PROVENANCE_RECORDED = "recorded_model_output"
_PROVENANCE_RANK = {PROVENANCE_STUB: 0, PROVENANCE_RECORDED: 1, PROVENANCE_LIVE: 2}     # the least live value wins when runs differ

# The audit actions that make a decision stale. `assessment.stale` is written by every evidence, DQ, canvas, approval and
# rematerialisation trigger; a deferral returns the decision to evidence gathering and is audited as `decision.deferred`.
STALE_ACTIONS = ("assessment.stale", "decision.deferred")
DEFER_REASON = "the decision was deferred by a human record: it returned to evidence gathering"


def provenance_of(run: m.AgentRun | None) -> str | None:
    """The provenance recorded on an agent run. A run that stored a response without a provenance was a live model call; a run that
    stored no response at all (the call failed) has no provenance. A `stub:` model name always means stub output, whatever the
    stored field says, so a stub can never be presented as live."""
    if run is None or not isinstance(run.output, dict):
        return None
    if str(run.model or "").startswith("stub:"):
        return PROVENANCE_STUB
    return run.output.get("provenance") or PROVENANCE_LIVE


def jsonable(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, date, datetime)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


class ReadModelService(BaseService):
    # ------------------------------------------------------------------ provenance
    def run_info(self, run_id) -> dict[str, Any]:
        run = self.session.get(m.AgentRun, run_id) if run_id is not None else None
        return {"provenance": provenance_of(run), "model": None if run is None else run.model,
                "model_fallback": bool(run.model_fallback) if run is not None else False}

    def runs_info(self, run_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        ids = {r for r in run_ids if r is not None}
        if not ids:
            return {}
        runs = self.session.scalars(select(m.AgentRun).where(m.AgentRun.id.in_(ids)))
        return {r.id: {"provenance": provenance_of(r), "model": r.model, "model_fallback": bool(r.model_fallback)} for r in runs}

    def classification_provenance(self, decision_id: uuid.UUID, taxonomy_id: str) -> dict[str, Any]:
        """Provenance and model of the runs behind the stored classifications of one taxonomy (the least live provenance wins)."""
        run_ids = set(self.session.scalars(select(m.LlmClassification.agent_run_id).where(
            m.LlmClassification.decision_id == decision_id, m.LlmClassification.taxonomy_version == taxonomy_id).distinct()))
        infos = list(self.runs_info(run_ids).values())
        if not infos:
            return {"provenance": None, "model": None}
        provenance = min((i["provenance"] for i in infos), key=lambda p: _PROVENANCE_RANK.get(p, 0))
        models = sorted({i["model"] for i in infos if i["model"]})
        return {"provenance": provenance, "model": ", ".join(models) or None}

    def annotate_llm_summary(self, summary: dict[str, Any] | None, *, synthesis: bool) -> dict[str, Any] | None:
        """A pipeline or re-synthesis summary (synthesis or review) plus the provenance and model of the agent run behind it (D6-01)."""
        if not summary:
            return summary
        ref = parse_uuid(summary.get("synthesis_id" if synthesis else "review_id"))
        row = self.session.get(m.Synthesis if synthesis else m.DecisionReview, ref) if ref else None
        info = self.run_info(row.agent_run_id) if row is not None and row.agent_run_id is not None else {"provenance": None, "model": None}
        return {**summary, "provenance": info["provenance"], "model": info["model"]}

    # ------------------------------------------------------------------ N1 reviews
    def _assessment(self, actor: Actor, assessment_id) -> m.DecisionAssessment:
        aid = parse_uuid(assessment_id)
        row = assessments_repo.get_assessment(self.session, aid) if aid else None
        if row is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, row.decision_id)
        return row

    def reviews(self, actor: Actor, assessment_id) -> list[dict[str, Any]]:
        assessment = self._assessment(actor, assessment_id)
        rows = reviews_repo.list_reviews(self.session, assessment.id)
        infos = self.runs_info(r.agent_run_id for r in rows)
        out = []
        for r in rows:
            info = infos.get(r.agent_run_id, {}) if r.agent_run_id is not None else {}
            out.append({"id": str(r.id), "assessment_id": str(r.assessment_id), "synthesis_id": None if r.synthesis_id is None else str(r.synthesis_id),
                        "agent_run_id": None if r.agent_run_id is None else str(r.agent_run_id), "reviewer_type": r.reviewer_type,
                        "reviewer_id": None if r.reviewer_id is None else str(r.reviewer_id), "verdict": r.verdict,
                        "human_response": r.human_response, "created_at": r.created_at,
                        "provenance": info.get("provenance"), "model": info.get("model"),
                        "model_fallback": bool(info.get("model_fallback", False)),
                        "findings": [finding_out(f) for f in (r.challenges or [])]})
        return out

    # ------------------------------------------------------------------ N2 decision record
    def decision_record(self, actor: Actor, decision_id) -> tuple[m.DecisionRecord, m.Decision]:
        decision = self.decision_or_404(actor, decision_id)
        records = reviews_repo.list_decision_records(self.session, decision.id)
        if not records:
            raise NotFound("This decision has no decision record yet.", detail={"decision_id": str(decision.id)})
        return records[-1], decision

    # ------------------------------------------------------------------ N3 briefs
    def briefs(self, actor: Actor, assessment_id) -> list[dict[str, Any]]:
        assessment = self._assessment(actor, assessment_id)
        return [{"id": str(b.id), "kind": b.kind, "version": b.version, "label": (b.content or {}).get("label", ""),
                 "synthesis_id": None if b.synthesis_id is None else str(b.synthesis_id), "created_at": b.created_at}
                for b in syn_repo.list_briefs(self.session, assessment.id)]

    # ------------------------------------------------------------------ N4 traceability
    def traceability(self, actor: Actor, assessment_id) -> list[dict[str, Any]]:
        """The rows of v_traceability_matrix for the assessment (claim links and gap rows) with the view's columns. Two plain lookups are
        added to the claim rows (the claim's id inside its synthesis and the synthesis id) so that the page can show the claim ids a
        reader sees in the text and keep one synthesis. No scoring happens here."""
        assessment = self._assessment(actor, assessment_id)
        rows = self.session.execute(text("SELECT * FROM v_traceability_matrix WHERE assessment_id = :a "
                                         "ORDER BY row_type DESC, claim_text, evidence_id"), {"a": assessment.id}).mappings().all()
        claims = {c.id: c for c in self.session.scalars(select(m.Claim).where(m.Claim.assessment_id == assessment.id))}
        out = []
        for r in rows:
            d = {k: jsonable(v) for k, v in dict(r).items()}
            claim = claims.get(r["claim_id"]) if r["claim_id"] is not None else None
            d["claim_local_id"] = None if claim is None else claim.local_id
            d["synthesis_id"] = None if claim is None or claim.synthesis_id is None else str(claim.synthesis_id)
            out.append(d)
        return out

    # ------------------------------------------------------------------ N5 stale reason and pending approvals
    def stale_info(self, decisions: Sequence[m.Decision]) -> dict[uuid.UUID, dict[str, Any]]:
        return stale_info(self.session, decisions)

    # ------------------------------------------------------------------ N6 metrics and evidence extras
    def metrics(self, actor: Actor) -> list[m.Metric]:
        return list(self.session.scalars(select(m.Metric).where(m.Metric.org_id == uuid.UUID(actor.org_id)).order_by(m.Metric.name)))

    def evidence_extras(self, evidence: Sequence[m.Evidence]) -> dict[uuid.UUID, dict[str, Any]]:
        """evidence id -> {source_name, reliability_tier, freshness}. Freshness is a row of the existing v_evidence_freshness view, read
        for the as-of date of the clock (the Day-3 freshness factor is not redefined here). The view holds active evidence only, so
        a proposed, rejected or superseded item has freshness null."""
        if not evidence:
            return {}
        sources = {s.id: s for s in self.session.scalars(select(m.EvidenceSource).where(
            m.EvidenceSource.id.in_({e.evidence_source_id for e in evidence})))}
        as_of = self.clock.today()
        self.session.execute(text("SELECT set_config('ddr.as_of', :d, true)"), {"d": as_of.isoformat()})
        try:
            fresh = {r["evidence_id"]: r for r in self.session.execute(
                text("SELECT evidence_id, age_days, half_life_days, within_half_life FROM v_evidence_freshness "
                     "WHERE evidence_id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(e.id) for e in evidence]}).mappings().all()}
        finally:
            self.session.execute(text("SELECT set_config('ddr.as_of', '', true)"))
        out = {}
        for e in evidence:
            src = sources.get(e.evidence_source_id)
            f = fresh.get(e.id)
            out[e.id] = {"source_name": None if src is None else src.title,
                         "reliability_tier": None if src is None else int(src.reliability_tier),
                         "freshness": None if f is None else {"age_days": int(f["age_days"]), "half_life_days": int(f["half_life_days"]),
                                                              "within_half_life": bool(f["within_half_life"]), "as_of": as_of.isoformat()}}
        return out


def stale_info(session: Session, decisions: Sequence[m.Decision]) -> dict[uuid.UUID, dict[str, Any]]:
    """decision id -> {stale_reason, stale_at} for the decisions whose assessment is stale (the latest stale audit row of each),
    and pending_approvals (proposed customer evidence items) for every decision."""
    ids = [d.id for d in decisions]
    if not ids:
        return {}
    out: dict[uuid.UUID, dict[str, Any]] = {d.id: {"stale_reason": None, "stale_at": None, "pending_approvals": 0} for d in decisions}
    for did, n in session.execute(select(m.Evidence.decision_id, func.count()).where(
            m.Evidence.decision_id.in_(ids), m.Evidence.evidence_type == "customer", m.Evidence.status == "proposed")
            .group_by(m.Evidence.decision_id)).all():
        out[did]["pending_approvals"] = int(n)
    for d in decisions:
        if not d.assessment_stale:
            continue
        row = session.scalars(select(m.AuditLog).where(
            m.AuditLog.action.in_(STALE_ACTIONS),
            (m.AuditLog.after["decision_id"].astext == str(d.id)) | (m.AuditLog.entity_id == d.id))
            .order_by(m.AuditLog.ts.desc(), m.AuditLog.id.desc()).limit(1)).first()
        if row is None:
            continue
        reason = DEFER_REASON if row.action == "decision.deferred" else str((row.after or {}).get("reason") or "")
        out[d.id].update({"stale_reason": reason or None, "stale_at": row.ts})
    return out


def finding_out(f: dict[str, Any]) -> dict[str, Any]:
    """One stored review finding with every field the API promises (older rows may lack some)."""
    ttype = f.get("target_type")
    return {"category": f.get("category"), "severity": f.get("severity"), "severity_model": f.get("severity_model", f.get("severity")),
            "source": f.get("source", "model"), "target_type": ttype, "target_id": f.get("target_id"),
            "target_local_id": f.get("target_local_id"), "rationale": f.get("rationale"),
            "evidence_ids": [str(e) for e in (f.get("evidence_ids") or [])], "notes": list(f.get("notes") or [])}
