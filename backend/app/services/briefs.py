"""Decision briefs and Gated Evidence Summaries (docs/day-5-implementation-brief.md section 8, T2).

    decision_brief            only when the decision is `validated` or `decided`, from the latest succeeded synthesis that the
                              validating review covered. Without an agent review it carries the banner
                              "No automated adversarial review"
    gated_evidence_summary    only for an `insufficient_evidence` assessment, labelled "Gated Evidence Summary: not a validated
                              decision artifact" on every rendering; never usable as a Decision Brief

Deterministic sections come from stored rows; the LLM sections are copied verbatim from the validated synthesis (sentence by
sentence, each resolved to its claims and evidence). Rows are immutable and versioned; regenerating creates a new version. The
database trigger repeats the stage and state rules (409 here, check_violation there).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.params import get_analytics_params, get_tenant_config
from app.db import models as m
from app.domain import lifecycle as lifecycle_rules
from app.domain import permissions as perm
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import analysis as analysis_repo
from app.repositories import assessments as assessments_repo
from app.repositories import recommendations as recs_repo
from app.repositories import reviews as reviews_repo
from app.repositories import syntheses as syn_repo
from app.repositories.users import parse_uuid
from app.schemas.responses import assessment_panel
from app.services.base import unit_of_work
from app.services.lifecycle import LifecycleHelpers
from app.synthesis import briefs as brief_mod
from app.synthesis import payload as payload_mod
from app.synthesis.briefs import KIND_DECISION_BRIEF, KIND_GATED_SUMMARY, KINDS, render_markdown

_REF = re.compile(r"\[\[([^\]]*)\]\]")


def _j(x):
    return payload_mod._j(x)


class BriefService(LifecycleHelpers):
    # ------------------------------------------------------------------ create
    def create(self, actor: Actor, assessment_id, kind: str) -> m.DecisionBrief:
        perm.authorize_role(actor, perm.CREATE_BRIEF)
        if kind not in KINDS:
            raise InvalidInput(f"kind must be one of {KINDS}.")
        aid = parse_uuid(assessment_id)
        assessment = assessments_repo.get_assessment(self.session, aid) if aid else None
        if assessment is None:
            raise NotFound("Assessment not found.")
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, assessment.decision_id, lock=True)
            if assessment.state == "partial":
                raise StateConflict("A partial assessment has no brief.")
            synthesis = syn_repo.latest_synthesis(self.session, assessment.id, status="succeeded")
            if kind == KIND_DECISION_BRIEF:
                if decision.lifecycle_stage not in ("validated", "decided"):
                    raise StateConflict(f"A Decision Brief exists only after the assessment is validated (the decision is "
                                        f"'{decision.lifecycle_stage}'). A Gated Evidence Summary may exist for an insufficient assessment.",
                                        detail={"lifecycle_stage": decision.lifecycle_stage})
                if assessment.state != "scored":
                    raise StateConflict("A Decision Brief exists only for a scored assessment. An insufficient assessment gets a "
                                        "Gated Evidence Summary, even after validation (T2).", detail={"state": assessment.state})
                current = assessments_repo.current_assessment(self.session, decision.id)
                if current is None or current.id != assessment.id:
                    raise StateConflict("A Decision Brief can only be made from the current assessment.")
                if synthesis is None:
                    raise StateConflict("A Decision Brief needs a succeeded synthesis, and none exists for this assessment.")
                agent_reviews = syn_repo.agent_reviews(self.session, assessment.id)
                if agent_reviews and agent_reviews[-1].synthesis_id != synthesis.id:
                    raise StateConflict("The latest succeeded synthesis was not covered by the validating review. Re-run the review.")
            else:
                if assessment.state != "insufficient_evidence":
                    raise StateConflict("A Gated Evidence Summary exists only for an assessment in insufficient_evidence state.",
                                        detail={"state": assessment.state})
            content = self._content(decision, assessment, synthesis, kind)
            version = syn_repo.max_brief_version(self.session, assessment.id, kind) + 1
            content["version"] = version
            row = syn_repo.add_brief(self.session, assessment_id=assessment.id, synthesis_id=None if synthesis is None else synthesis.id,
                                     kind=kind, version=version, content=content, markdown=render_markdown(content),
                                     is_synthetic=decision.is_synthetic)
            self.audit(actor, "brief.created", "brief", row.id, decision, before=None,
                       after={"kind": kind, "version": version, "assessment_id": str(assessment.id),
                              "synthesis_id": None if synthesis is None else str(synthesis.id)})
            return row

    # ------------------------------------------------------------------ read
    def get(self, actor: Actor, brief_id) -> m.DecisionBrief:
        bid = parse_uuid(brief_id)
        row = syn_repo.get_brief(self.session, bid) if bid else None
        if row is None:
            raise NotFound("Brief not found.")
        assessment = assessments_repo.get_assessment(self.session, row.assessment_id)
        self.decision_or_404(actor, assessment.decision_id)
        return row

    def list(self, actor: Actor, assessment_id) -> list[m.DecisionBrief]:
        aid = parse_uuid(assessment_id)
        assessment = assessments_repo.get_assessment(self.session, aid) if aid else None
        if assessment is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, assessment.decision_id)
        return syn_repo.list_briefs(self.session, assessment.id)

    # ------------------------------------------------------------------ content
    def _content(self, decision: m.Decision, assessment: m.DecisionAssessment, synthesis: m.Synthesis | None, kind: str) -> dict[str, Any]:
        session: Session = self.session
        scored = assessment.state == "scored"
        panel = assessment_panel(assessment, is_current=True, is_superseded=False)
        panel = _j({k: panel[k] for k in ("state", "ddi", "band", "dimensions", "penalties", "positioning", "insufficient_evidence_label",
                                          "what_drove_this_result", "sensitivity", "blocking_reasons", "warnings")})
        facts_input, _ = payload_mod.build_input(session, decision, assessment, task="brief")
        metric = session.get(m.Metric, decision.success_metric_id)
        analytics = self.ctx.analytics_params or get_analytics_params()
        tenant = self.ctx.tenant or get_tenant_config()
        review_block = self._review_block(assessment, synthesis)
        banners = [brief_mod.SYNTHETIC_BANNER]
        if kind == KIND_GATED_SUMMARY:
            banners.insert(0, brief_mod.GATED_LABEL)
        if kind == KIND_DECISION_BRIEF:
            banners.insert(0, "Assessment validated by review: this is not a statement that the decision is correct.")
            if review_block["agent_review"] is None:
                banners.append(brief_mod.NO_AUTOMATED_REVIEW_BANNER)
        runs = {}
        if synthesis is not None:
            run = session.get(m.AgentRun, synthesis.agent_run_id)
            runs["synthesis"] = run
        if review_block["agent_review"] is not None:
            runs["review"] = session.get(m.AgentRun, review_block["agent_review"]["agent_run_id"])
        versions: dict[str, Any] = {
            "ddi_params": f"{assessment.params_version} ({assessment.params_hash})",
            "nbe_params": f"{assessment.nbe_params_version} ({assessment.nbe_params_hash})",
            "analytics_params": f"{analytics.version} ({analytics.content_hash})",
            "tenant_config": f"{tenant.version} ({tenant.content_hash})"}
        for name, run in runs.items():
            if run is not None:
                versions[f"{name}_prompt"] = f"{run.prompt_id} {run.prompt_version} ({run.prompt_sha256})"
                versions[f"{name}_model"] = run.model + (" (fallback)" if run.model_fallback else "")
        if synthesis is not None:
            versions["synthesis"] = f"version {synthesis.version}, input {synthesis.input_sha256}, output {synthesis.output_sha256}"
        content: dict[str, Any] = {
            "kind": kind,
            "label": brief_mod.GATED_LABEL if kind == KIND_GATED_SUMMARY else brief_mod.DECISION_BRIEF_LABEL,
            "title": f"{'Gated Evidence Summary' if kind == KIND_GATED_SUMMARY else 'Decision Brief'}: {decision.title}",
            "banners": banners,
            "header": {
                "decision": {"id": str(decision.id), "title": decision.title, "hypothesis": decision.hypothesis,
                             "decision_type": decision.decision_type, "expected_direction": decision.expected_direction,
                             "success_metric": metric.name if metric else None,
                             "lifecycle_stage": decision.lifecycle_stage, "lifecycle_label": lifecycle_rules.label(decision.lifecycle_stage),
                             "criteria": list(decision.change_my_mind_criteria)},
                "assessment": {"id": str(assessment.id), "version": assessment.version, "state": assessment.state,
                               "as_of_date": assessment.as_of_date.isoformat(), "evidence_fingerprint": assessment.evidence_fingerprint},
                "versions": versions},
            "ddi_panel": panel,
            "direction": _j((assessment.dimension_scores or {}).get("evidence_direction") or {}),
            "gate_reasons": _j(assessment.blocking_reasons or []),
            "evidence_table": self._evidence_table(decision),
            "dq": facts_input["dq_findings"], "heterogeneity": facts_input["heterogeneity"],
            "nbe": [{"action_type": r["action_type"], "description": r["description"], "effort_days": float(row.effort_days),
                     "blockers_resolved": r["blockers_resolved"]}
                    for r, row in zip(facts_input["next_evidence_actions"], recs_repo.list_for_assessment(session, assessment.id))],
            "review": review_block, "decision_record": self._decision_record(decision),
            "synthesis": None, "llm_sections": {k: [] for k in ("summary", "supporting", "contradicting", "uncertainty")},
            "claims": [], "uncertainties": [], "gaps": [], "criteria_assessment": [], "traceability": []}
        if kind == KIND_GATED_SUMMARY:
            content["blocking_reasons_explained"] = [{"code": r.get("code"), "explanation": r.get("message") or r.get("code")}
                                                     for r in (assessment.blocking_reasons or [])]
            content["unblocking_actions"] = [{"action_type": r.action_type, "description": (r.description or "").split("\n", 1)[0],
                                              "blockers_resolved": r.blockers_resolved, "effort_days": float(r.effort_days)}
                                             for r in recs_repo.list_for_assessment(session, assessment.id) if r.blockers_resolved > 0]
        if synthesis is not None:
            self._add_synthesis(content, decision, assessment, synthesis, runs.get("synthesis"))
        content["traceability"] = self._traceability(assessment, synthesis)
        return _j(content)

    def _add_synthesis(self, content: dict, decision: m.Decision, assessment: m.DecisionAssessment, synthesis: m.Synthesis, run) -> None:
        out = synthesis.output or {}
        claims = syn_repo.claims_for_synthesis(self.session, synthesis.id)
        by_local = {c.local_id: (c, ids) for c, ids in claims}
        content["synthesis"] = {"id": str(synthesis.id), "version": synthesis.version, "model": run.model if run else None,
                                "provenance": "stub_not_model_output" if run is not None and (run.model or "").startswith("stub:")
                                else "model_output", "input_sha256": synthesis.input_sha256, "output_sha256": synthesis.output_sha256,
                                "claims_dropped": synthesis.claims_dropped}
        content["claims"] = [{"local_id": c.local_id, "claim_id": str(c.id), "text": c.claim_text, "claim_type": c.claim_type,
                              "stance": c.stance, "confidence": c.confidence, "conclusion_ref": c.conclusion_ref,
                              "evidence_ids": [str(i) for i in ids]} for c, ids in claims]
        for key in ("summary", "supporting", "contradicting", "uncertainty"):
            sentences = []
            for sent in [s for s in re.split(r"(?<=[.!?])\s+", (out.get("sections") or {}).get(key, "").strip()) if s.strip()]:
                refs = [r for r in _REF.findall(sent) if r in by_local]
                sentences.append({"text": _REF.sub("", sent).replace("  ", " ").strip(), "raw": sent,
                                  "claim_refs": [{"local_id": r, "claim_id": str(by_local[r][0].id),
                                                  "evidence_ids": [str(i) for i in by_local[r][1]]} for r in refs]})
            content["llm_sections"][key] = sentences
        content["uncertainties"] = list(out.get("uncertainties") or [])
        content["gaps"] = list(out.get("gaps") or [])
        criteria = decision.change_my_mind_criteria
        content["criteria_assessment"] = [{"criterion_index": c["criterion_index"], "text": criteria[c["criterion_index"]],
                                           "status": c["status"], "evidence_ids": c["evidence_ids"]}
                                          for c in (out.get("criteria_assessment") or [])]

    def _evidence_table(self, decision: m.Decision) -> list[dict]:
        rows = self.session.execute(select(m.Evidence, m.EvidenceSource).join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
                                    .where(m.Evidence.decision_id == decision.id).order_by(m.Evidence.created_at, m.Evidence.id)
                                    .execution_options(populate_existing=True)).all()
        out = []
        for ev, src in rows:
            analysis_type = None
            if ev.analysis_id is not None:
                an = analysis_repo.get_analysis(self.session, ev.analysis_id)
                analysis_type = None if an is None else an.analysis_type
            out.append({"id": str(ev.id), "evidence_type": ev.evidence_type, "stance": ev.stance, "grade": ev.strength_grade,
                        "tier": int(src.reliability_tier), "status": ev.status, "summary": ev.summary, "n_sample": ev.n_sample,
                        "effect_size": ev.effect_size, "ci_low": ev.ci_low, "ci_high": ev.ci_high, "analysis_id": ev.analysis_id,
                        "analysis_type": analysis_type, "created_by": ev.created_by, "source": src.title,
                        "approved_by": ev.approved_by, "approval_note": ev.approval_note})
        return out

    def _review_block(self, assessment: m.DecisionAssessment, synthesis: m.Synthesis | None) -> dict:
        reviews = reviews_repo.list_reviews(self.session, assessment.id)
        agent = None
        for r in reversed(reviews):
            if r.reviewer_type == "agent" and (synthesis is None or r.synthesis_id == synthesis.id):
                run = self.session.get(m.AgentRun, r.agent_run_id) if r.agent_run_id else None
                agent = {"review_id": str(r.id), "verdict": r.verdict, "findings": list(r.challenges or []),
                         "agent_run_id": r.agent_run_id, "model": run.model if run else None,
                         "model_fallback": bool(run.model_fallback) if run else False, "synthesis_id": _j(r.synthesis_id)}
                break
        humans = [{"review_id": str(r.id), "verdict": r.verdict, "human_response": r.human_response, "created_at": r.created_at}
                  for r in reviews if r.reviewer_type == "human"]
        return _j({"agent_review": agent, "human_reviews": humans})

    def _decision_record(self, decision: m.Decision) -> dict | None:
        records = [r for r in reviews_repo.list_decision_records(self.session, decision.id) if r.outcome != "defer"]
        if not records:
            return None
        r = records[-1]
        return _j({"outcome": r.outcome, "rationale": r.rationale, "acknowledged_risk": r.acknowledged_risk, "decided_at": r.decided_at})

    def _traceability(self, assessment: m.DecisionAssessment, synthesis: m.Synthesis | None) -> list[dict]:
        """The rows of v_traceability_matrix for the claims of this synthesis, plus the gap rows of the assessment (TM-3, TM-4)."""
        claim_ids = [] if synthesis is None else [str(c.id) for c, _ in syn_repo.claims_for_synthesis(self.session, synthesis.id)]
        local = {} if synthesis is None else {str(c.id): c.local_id for c, _ in syn_repo.claims_for_synthesis(self.session, synthesis.id)}
        rows = self.session.execute(text(
            "SELECT claim_id, claim_text, claim_type, stance, claim_confidence, evidence_id, evidence_summary, evidence_type, "
            "strength_grade, source_id, source_name, reliability_tier, analysis_id, analysis_type, dq_status, conclusion_ref, "
            "row_type, evidence_status FROM v_traceability_matrix WHERE assessment_id = :a "
            "AND (row_type = 'gap' OR claim_id = ANY(CAST(:claims AS uuid[]))) ORDER BY row_type DESC, claim_text, evidence_id"),
            {"a": assessment.id, "claims": claim_ids}).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["local_id"] = local.get(str(d["claim_id"])) if d.get("claim_id") else None
            out.append(d)
        return _j(out)

