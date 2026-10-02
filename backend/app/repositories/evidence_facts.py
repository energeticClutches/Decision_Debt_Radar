"""EvidenceFacts builder and evidence fingerprint (R4, R6).

Flow: Database -> this repository -> EvidenceFacts -> DDI engine. Decimal values become float and UUIDs
become str here. The fingerprint is a SHA-256 over everything the facts are built from, so a change made
by another transaction while an assessment runs is detected.

Day 4 (docs/day-4-implementation-brief.md section 3, the only changes allowed here):
  * DQ checks are read by dq_checks.decision_id (a check without an assessment link still counts and gates)
  * evidence with status 'superseded' is excluded
  * heterogeneity_flag comes from the LATEST segmentation analysis for the decision's success metric (None if there is none)
  * ExperimentFact.achieved_power comes from the experiment analysis that the evidence item's analysis_id points to (None if none)
  * the evidence fingerprint covers the same inputs
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain.facts import (
    DqIssue,
    EvidenceFacts,
    EvidenceItem,
    ExperimentFact,
    InsightFact,
    derive_item_dq_status,
)
from app.repositories import analysis as analysis_repo


def _f(x) -> float | None:
    return None if x is None else float(x)


def _s(x) -> str | None:
    return None if x is None else str(x)


def _heterogeneity(session: Session, decision_id: uuid.UUID, metric_id: uuid.UUID) -> tuple[bool | None, str | None]:
    """(flag, analysis id) of the latest segmentation analysis for the success metric. (None, None) when there is none."""
    row = analysis_repo.latest_segmentation(session, decision_id, metric_id)
    if row is None:
        return None, None
    flag = (row.result or {}).get("flag")
    return (flag if isinstance(flag, bool) else None), str(row.id)


def _design_power(session: Session, analysis_id: uuid.UUID | None) -> float | None:
    """Design power at the pre-registered MDE, stored by the experiment analysis (None when absent)."""
    if analysis_id is None:
        return None
    row = analysis_repo.get_analysis(session, analysis_id)
    if row is None or row.analysis_type != "experiment":
        return None
    value = ((row.result or {}).get("design_power") or {}).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _experiment_analysis_ids(rows) -> dict[uuid.UUID, uuid.UUID]:
    """experiment id -> analysis id of its (active) evidence item. If several, the most recently created one."""
    best: dict[uuid.UUID, tuple] = {}
    for ev, _ in rows:
        if ev.experiment_id is None or ev.analysis_id is None:
            continue
        key = (ev.created_at, str(ev.id))
        if ev.experiment_id not in best or key > best[ev.experiment_id][0]:
            best[ev.experiment_id] = (key, ev.analysis_id)
    return {k: v[1] for k, v in best.items()}


def _decision_core(session: Session, decision_id: uuid.UUID):
    d = session.get(m.Decision, decision_id, populate_existing=True)
    metric = session.get(m.Metric, d.success_metric_id, populate_existing=True)
    return d, metric


def build_facts(session: Session, decision_id: uuid.UUID) -> EvidenceFacts:
    d, metric = _decision_core(session, decision_id)
    rows = session.execute(
        select(m.Evidence, m.EvidenceSource).join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
        .where(m.Evidence.decision_id == decision_id, m.Evidence.status != "superseded").order_by(m.Evidence.id)
        .execution_options(populate_existing=True)).all()

    # D4-05: DQ checks belong to the decision (a check without an assessment link still counts and gates).
    checks = session.execute(
        select(m.DqCheck).where(m.DqCheck.decision_id == decision_id).order_by(m.DqCheck.id)
        .execution_options(populate_existing=True)).scalars().all()
    dq_issues = tuple(DqIssue(id=str(c.id), data_source_id=str(c.data_source_id), severity=c.severity, status=c.status,
                              affects_metric_id=_s(c.affects_metric_id), check_type=c.check_type, finding=c.finding)
                      for c in checks)

    experiment_ids = sorted({ev.experiment_id for ev, _ in rows if ev.experiment_id is not None}, key=str)
    analysis_for_experiment = _experiment_analysis_ids(rows)
    experiments: list[ExperimentFact] = []
    for exp in session.scalars(select(m.Experiment).where(m.Experiment.id.in_(experiment_ids)).order_by(m.Experiment.id)
                               .execution_options(populate_existing=True)):
        # The non-control result row is the one with a stored effect size. If several, the largest n.
        result = session.scalars(
            select(m.ExperimentResult).where(m.ExperimentResult.experiment_id == exp.id,
                                             m.ExperimentResult.effect_size.is_not(None))
            .order_by(m.ExperimentResult.n.desc(), m.ExperimentResult.id).limit(1)
            .execution_options(populate_existing=True)).first()
        experiments.append(ExperimentFact(
            id=str(exp.id), design=exp.design, primary_metric_id=_s(exp.primary_metric_id), mde=_f(exp.mde),
            result_n=result.n if result else None, effect_size=_f(result.effect_size) if result else None,
            ci_low=_f(result.ci_low) if result else None, ci_high=_f(result.ci_high) if result else None,
            p_value=_f(result.p_value) if result else None, srm_flag=result.srm_flag if result else None,
            achieved_power=_design_power(session, analysis_for_experiment.get(exp.id))))   # None: the DDI default applies

    insight_ids = sorted({ev.insight_id for ev, _ in rows if ev.insight_id is not None}, key=str)
    insights = tuple(InsightFact(id=str(i.id), quote_count=i.quote_count, segment=i.segment)
                     for i in session.scalars(select(m.CustomerInsight).where(m.CustomerInsight.id.in_(insight_ids))
                                              .order_by(m.CustomerInsight.id).execution_options(populate_existing=True)))

    items = []
    ds_ids: set[uuid.UUID] = set()
    for ev, src in rows:
        ds = src.data_source_id
        if ds:
            ds_ids.add(ds)
        items.append(EvidenceItem(
            id=str(ev.id), evidence_type=ev.evidence_type, stance=ev.stance, strength_grade=ev.strength_grade,
            source_id=str(ev.evidence_source_id), reliability_tier=int(src.reliability_tier), observed_end=ev.observed_end,
            data_source_id=_s(ds), dq_status=derive_item_dq_status(_s(ds), dq_issues), n_sample=ev.n_sample,
            effect_size=_f(ev.effect_size), ci_low=_f(ev.ci_low), ci_high=_f(ev.ci_high), metric_id=_s(ev.metric_id),
            experiment_id=_s(ev.experiment_id), insight_id=_s(ev.insight_id)))
    if metric.data_source_id:
        ds_ids.add(metric.data_source_id)
    ds_ids.update(c.data_source_id for c in checks)
    names = tuple((str(x.id), x.name) for x in session.scalars(select(m.DataSource).where(m.DataSource.id.in_(ds_ids))
                                                                .order_by(m.DataSource.id))) if ds_ids else ()
    het_flag, _ = _heterogeneity(session, d.id, d.success_metric_id)
    return EvidenceFacts(
        decision_id=str(d.id), decision_type=d.decision_type, success_metric_id=str(d.success_metric_id),
        success_metric_data_source_id=_s(metric.data_source_id), items=tuple(items), experiments=tuple(experiments),
        insights=insights, dq_issues=dq_issues, heterogeneity_flag=het_flag, data_source_names=names)


def _jsonable(x):
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, (Decimal, uuid.UUID)):
        return str(x)
    return x


def evidence_fingerprint(session: Session, decision_id: uuid.UUID) -> str:
    """SHA-256 over every row the facts depend on (evidence incl. updated_at, sources, experiments + results,
    insights, DQ checks of all assessment versions, decision type and success metric)."""
    d, metric = _decision_core(session, decision_id)
    ev = session.execute(
        select(m.Evidence.id, m.Evidence.evidence_source_id, m.Evidence.evidence_type, m.Evidence.stance,
               m.Evidence.strength_grade, m.Evidence.observed_start, m.Evidence.observed_end, m.Evidence.n_sample,
               m.Evidence.effect_size, m.Evidence.ci_low, m.Evidence.ci_high, m.Evidence.metric_id,
               m.Evidence.experiment_id, m.Evidence.insight_id, m.Evidence.updated_at, m.EvidenceSource.reliability_tier,
               m.EvidenceSource.data_source_id, m.Evidence.analysis_id)
        .join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
        .where(m.Evidence.decision_id == decision_id, m.Evidence.status != "superseded").order_by(m.Evidence.id)).all()
    exp_ids = [r.experiment_id for r in ev if r.experiment_id is not None]
    ins_ids = [r.insight_id for r in ev if r.insight_id is not None]
    exps = session.execute(select(m.Experiment.id, m.Experiment.design, m.Experiment.primary_metric_id, m.Experiment.mde,
                                  m.Experiment.updated_at).where(m.Experiment.id.in_(exp_ids)).order_by(m.Experiment.id)).all()
    res = session.execute(select(m.ExperimentResult.id, m.ExperimentResult.experiment_id, m.ExperimentResult.variant,
                                 m.ExperimentResult.n, m.ExperimentResult.effect_size, m.ExperimentResult.ci_low,
                                 m.ExperimentResult.ci_high, m.ExperimentResult.p_value, m.ExperimentResult.srm_flag)
                          .where(m.ExperimentResult.experiment_id.in_(exp_ids)).order_by(m.ExperimentResult.id)).all()
    ins = session.execute(select(m.CustomerInsight.id, m.CustomerInsight.quote_count, m.CustomerInsight.segment)
                          .where(m.CustomerInsight.id.in_(ins_ids)).order_by(m.CustomerInsight.id)).all()
    dq = session.execute(
        select(m.DqCheck.id, m.DqCheck.data_source_id, m.DqCheck.severity, m.DqCheck.status, m.DqCheck.affects_metric_id)
        .where(m.DqCheck.decision_id == decision_id).order_by(m.DqCheck.id)).all()
    het_flag, het_analysis = _heterogeneity(session, d.id, d.success_metric_id)
    # achieved power per experiment, from the analysis the active evidence item points to (the same input as the facts)
    newest: dict = {}
    for r in ev:
        if r.experiment_id is not None and r.analysis_id is not None:
            key = (r.updated_at, str(r.id))
            if r.experiment_id not in newest or key > newest[r.experiment_id][0]:
                newest[r.experiment_id] = (key, r.analysis_id)
    power = [[str(e), str(a), _design_power(session, a)] for e, (_, a) in sorted(newest.items(), key=lambda kv: str(kv[0]))]
    payload = {
        "decision": [str(d.id), d.decision_type, str(d.success_metric_id), _s(metric.data_source_id)],
        "evidence": [list(r) for r in ev], "experiments": [list(r) for r in exps], "results": [list(r) for r in res],
        "insights": [list(r) for r in ins], "dq": [list(r) for r in dq],
        "heterogeneity": [het_flag, het_analysis], "achieved_power": power,
    }
    blob = json.dumps(payload, default=_jsonable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
