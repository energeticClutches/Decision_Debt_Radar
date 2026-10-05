"""The structured input of the Evidence Synthesis and of the Reviewer (docs/day-5-implementation-brief.md section 6.1).

Built only from stored data: the stored assessment (a numeric DDI only if it was scored), the ACTIVE evidence of the decision, the
non-pass data-quality findings, the heterogeneity result, the customer insights (sample quotes wrapped in
<untrusted_customer_text> and escaped) and the next-evidence actions. The model receives no database access, no tool and no SQL. A
non-scored assessment carries no number anywhere.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain import lifecycle as lifecycle_rules  # noqa: F401  (documented dependency: stage names)
from app.domain.ddi.engine import POSITIONING
from app.llm import sanitize
from app.repositories import analysis as analysis_repo
from app.repositories import dq as dq_repo
from app.repositories import recommendations as recs_repo
from app.repositories.evidence_facts import build_facts
from app.synthesis.schema import CONCLUSION_REFS

SYNTHETIC_NOTICE = "All data is synthetic: FitConnect is a fictional company."


def _j(x: Any) -> Any:
    """JSON-safe copy: Decimal -> float, date -> ISO, UUID -> str."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, uuid.UUID):
        return str(x)
    if isinstance(x, dict):
        return {str(k): _j(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_j(v) for v in x]
    return x


def assessment_block(a: m.DecisionAssessment) -> dict[str, Any]:
    scored = a.state == "scored"
    ds, ps = a.dimension_scores or {}, a.penalty_scores or {}
    block: dict[str, Any] = {
        "assessment_id": str(a.id), "version": a.version, "state": a.state, "as_of_date": a.as_of_date.isoformat(),
        "positioning": POSITIONING, "blocking_reasons": _j(a.blocking_reasons or []),
        "evidence_direction": _j(ds.get("evidence_direction")), "warnings": _j(ds.get("warnings") or []),
        "params": {"ddi_params_version": a.params_version, "nbe_params_version": a.nbe_params_version},
    }
    if scored:
        block.update({
            "ddi": float(a.ddi_score), "band": a.ddi_band, "support": ds.get("support"), "penalty_multiplier": ds.get("penalty_multiplier"),
            "cap_applied": ds.get("cap_applied"),
            "dimensions": [{"id": d.get("id"), "name": d.get("name"), "applicable": d.get("applicable"), "score": d.get("score"),
                            "display_contribution": d.get("display_contribution"),
                            "defaulted_inputs": [i.get("name") for i in d.get("defaulted_inputs", [])]}
                           for d in (ds.get("dimensions") or {}).values()],
            "penalties": [{"id": p.get("id"), "name": p.get("name"), "score": p.get("score"),
                           "display_contribution": p.get("display_contribution"),
                           "defaulted_inputs": [i.get("name") for i in p.get("defaulted_inputs", [])]}
                          for p in (ps.get("penalties") or {}).values()],
            "sensitivity": _j(a.sensitivity or {}), "what_drove_this_result": ds.get("what_drove_this_result")})
    else:
        block["note"] = "INSUFFICIENT EVIDENCE: no DDI, band, dimension or penalty exists for this assessment."
    return _j(block)


def heterogeneity_block(session: Session, decision: m.Decision) -> dict[str, Any]:
    row = analysis_repo.latest_segmentation(session, decision.id, decision.success_metric_id)
    if row is None:
        return {"flag": None, "note": "no segmentation analysis exists"}
    res = row.result or {}
    return _j({"flag": res.get("flag") if isinstance(res.get("flag"), bool) else None, "analysis_id": str(row.id),
               "segment_key": res.get("segment_key"), "segments_eligible": res.get("segments_eligible"),
               "segments": res.get("segments"), "triggering_pairs": res.get("triggering_pairs")})


def build_input(session: Session, decision: m.Decision, assessment: m.DecisionAssessment, *, task: str = "synthesize"
                ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(the structured input, the evidence index used by RecordedClient to resolve fixture selectors)."""
    facts = build_facts(session, decision.id)
    facts_items = {i.id: i for i in facts.items}
    exp_facts = {e.id: e for e in facts.experiments}
    rows = session.execute(select(m.Evidence, m.EvidenceSource).join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
                           .where(m.Evidence.decision_id == decision.id, m.Evidence.status == "active").order_by(m.Evidence.id)
                           .execution_options(populate_existing=True)).all()
    insights = {i.id: i for i in session.scalars(select(m.CustomerInsight).where(m.CustomerInsight.decision_id == decision.id)
                                                .execution_options(populate_existing=True))}
    evidence, index, insight_blocks = [], [], []
    for ev, src in rows:
        analysis_type = None
        if ev.analysis_id is not None:
            an = analysis_repo.get_analysis(session, ev.analysis_id)
            analysis_type = None if an is None else an.analysis_type
        item: dict[str, Any] = {
            "id": str(ev.id), "evidence_type": ev.evidence_type, "stance": ev.stance, "grade": ev.strength_grade,
            "tier": int(src.reliability_tier), "summary": ev.summary, "effect_size": ev.effect_size, "ci_low": ev.ci_low,
            "ci_high": ev.ci_high, "n_sample": ev.n_sample, "observed_start": ev.observed_start, "observed_end": ev.observed_end,
            "analysis_id": ev.analysis_id, "analysis_type": analysis_type, "created_by": ev.created_by,
            "dq_status": facts_items[str(ev.id)].dq_status if str(ev.id) in facts_items else "pass"}
        if ev.experiment_id is not None and str(ev.experiment_id) in exp_facts:
            e = exp_facts[str(ev.experiment_id)]
            item["experiment"] = {"design": e.design, "mde": e.mde, "srm_flag": e.srm_flag, "design_power": e.achieved_power,
                                  "p_value": e.p_value, "n": e.result_n}
        theme = None
        if ev.insight_id is not None and ev.insight_id in insights:
            ins = insights[ev.insight_id]
            theme = ins.theme
            item["theme"] = theme
            item["customer_insight"] = {
                "mentions": ins.quote_count, "sentiment": ins.sentiment, "relevance_observed": ins.relevance_observed,
                "relevance_note": "observed, not used by DDI v0.1", "source_types": ins.source_types,
                "first_mention_date": ins.first_mention_date, "last_mention_date": ins.last_mention_date,
                "segment_counts": ins.segment_counts, "taxonomy_version": ins.taxonomy_version}
            insight_blocks.append({"insight_id": str(ins.id), "theme": theme, "stance": ev.stance, "mentions": ins.quote_count,
                                   "sample_quotes": [{"text": sanitize.wrap(str(q.get("text", ""))), "mentions": q.get("mentions")}
                                                     for q in (ins.sample_quotes or [])]})
        evidence.append(_j(item))
        index.append({"id": str(ev.id), "evidence_type": ev.evidence_type, "analysis_type": analysis_type, "theme": theme})

    dq = [{"check_key": c.check_key, "check_type": c.check_type, "target": c.target, "severity": c.severity, "status": c.status,
           "finding": c.finding, "affects_success_metric": c.affects_success_metric, "observed_value": c.observed_value,
           "threshold": c.threshold}
          for c in dq_repo.list_for_decision(session, decision.id) if c.severity != "pass"]
    metric = session.get(m.Metric, decision.success_metric_id)
    recs = recs_repo.list_for_assessment(session, assessment.id)
    payload = {
        "task": task, "synthetic_data_notice": SYNTHETIC_NOTICE,
        "decision": {"title": decision.title, "hypothesis": decision.hypothesis, "decision_type": decision.decision_type,
                     "expected_direction": decision.expected_direction,
                     "success_metric": {"name": metric.name if metric else None, "definition": metric.definition if metric else None},
                     "criteria": [{"index": i, "text": c} for i, c in enumerate(decision.change_my_mind_criteria)]},
        "assessment": assessment_block(assessment), "evidence": evidence, "dq_findings": _j(dq),
        "heterogeneity": heterogeneity_block(session, decision), "customer_insights": _j(insight_blocks),
        "next_evidence_actions": [{"rank": i + 1, "action_type": r.action_type, "description": (r.description or "").split("\n", 1)[0],
                                   "blockers_resolved": r.blockers_resolved} for i, r in enumerate(recs)],
        "conclusion_refs": list(CONCLUSION_REFS)}
    return _j(payload), index


__all__ = ["SYNTHETIC_NOTICE", "assessment_block", "build_input", "heterogeneity_block"]
