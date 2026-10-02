"""EvidenceFacts builder and evidence fingerprint (R4, R6).

Flow: Database -> this repository -> EvidenceFacts -> DDI engine. Decimal values become float and UUIDs
become str here. The fingerprint is a SHA-256 over everything the facts are built from, so a change made
by another transaction while an assessment runs is detected.
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


def _f(x) -> float | None:
    return None if x is None else float(x)


def _s(x) -> str | None:
    return None if x is None else str(x)


def _decision_core(session: Session, decision_id: uuid.UUID):
    d = session.get(m.Decision, decision_id, populate_existing=True)
    metric = session.get(m.Metric, d.success_metric_id, populate_existing=True)
    return d, metric


def build_facts(session: Session, decision_id: uuid.UUID) -> EvidenceFacts:
    d, metric = _decision_core(session, decision_id)
    rows = session.execute(
        select(m.Evidence, m.EvidenceSource).join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
        .where(m.Evidence.decision_id == decision_id).order_by(m.Evidence.id)
        .execution_options(populate_existing=True)).all()

    checks = session.execute(
        select(m.DqCheck).join(m.DecisionAssessment, m.DecisionAssessment.id == m.DqCheck.assessment_id)
        .where(m.DecisionAssessment.decision_id == decision_id).order_by(m.DqCheck.id)
        .execution_options(populate_existing=True)).scalars().all()
    dq_issues = tuple(DqIssue(id=str(c.id), data_source_id=str(c.data_source_id), severity=c.severity, status=c.status,
                              affects_metric_id=_s(c.affects_metric_id), check_type=c.check_type, finding=c.finding)
                      for c in checks)

    experiment_ids = sorted({ev.experiment_id for ev, _ in rows if ev.experiment_id is not None}, key=str)
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
            achieved_power=None))     # achieved power is not stored on Day 3 (documented default applies)

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
    return EvidenceFacts(
        decision_id=str(d.id), decision_type=d.decision_type, success_metric_id=str(d.success_metric_id),
        success_metric_data_source_id=_s(metric.data_source_id), items=tuple(items), experiments=tuple(experiments),
        insights=insights, dq_issues=dq_issues, heterogeneity_flag=None, data_source_names=names)


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
               m.EvidenceSource.data_source_id)
        .join(m.EvidenceSource, m.EvidenceSource.id == m.Evidence.evidence_source_id)
        .where(m.Evidence.decision_id == decision_id).order_by(m.Evidence.id)).all()
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
        .join(m.DecisionAssessment, m.DecisionAssessment.id == m.DqCheck.assessment_id)
        .where(m.DecisionAssessment.decision_id == decision_id).order_by(m.DqCheck.id)).all()
    payload = {
        "decision": [str(d.id), d.decision_type, str(d.success_metric_id), _s(metric.data_source_id)],
        "evidence": [list(r) for r in ev], "experiments": [list(r) for r in exps], "results": [list(r) for r in res],
        "insights": [list(r) for r in ins], "dq": [list(r) for r in dq],
    }
    blob = json.dumps(payload, default=_jsonable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
