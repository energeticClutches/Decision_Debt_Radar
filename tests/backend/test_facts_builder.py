"""EvidenceFacts builder and evidence fingerprint (repository layer) against the real database, rolled back."""

from __future__ import annotations

from datetime import date

import pytest
from flow import Flow, canvas, evidence_payload
from sqlalchemy import text

from app.domain.errors import StateConflict
from app.domain.facts import EvidenceFacts
from app.repositories.evidence_facts import build_facts, evidence_fingerprint


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def make_experiment(session, seed, decision, *, metric):
    exp = session.execute(text(
        "INSERT INTO experiments (org_id, decision_id, name, hypothesis, design, start_date, end_date, status, primary_metric_id,"
        " planned_sample, mde, is_synthetic) VALUES (:o,:d,'exp','h','rct','2026-08-01','2026-09-01','completed',:m,2000,0.02,true)"
        " RETURNING id"), {"o": decision.org_id, "d": decision.id, "m": metric}).scalar()
    for variant, n, effect, lo, hi in (("control", 1000, None, None, None), ("a", 900, 0.03, 0.01, 0.05), ("b", 1200, 0.01, 0.0, 0.02)):
        session.execute(text(
            "INSERT INTO experiment_results (experiment_id, variant, n, effect_size, ci_low, ci_high, srm_flag, is_synthetic)"
            " VALUES (:e,:v,:n,:ef,:lo,:hi,false,true)"), {"e": exp, "v": variant, "n": n, "ef": effect, "lo": lo, "hi": hi})
    return exp


def test_facts_builder_reads_experiments_insights_dq_and_converts_types(flow, session, seed):
    d = flow.gathered()
    insight = session.execute(text(
        "INSERT INTO customer_insights (org_id, decision_id, theme, sentiment, quote_count, is_synthetic)"
        " VALUES (:o,:d,'theme','positive',150,true) RETURNING id"), {"o": d.org_id, "d": d.id}).scalar()
    exp = make_experiment(session, seed, d, metric=seed.metric_d90)
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral"))
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "customer", insight_id=str(insight)))
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "experiment", experiment_id=str(exp), metric_id=None))
    a = flow.assessments.run(seed.analyst, d.id)
    events_ds = seed.ds["FitConnect product events (fc_.events)"].id
    flow.insert_dq_check(a, events_ds, "warn", "open")
    flow.insert_dq_check(a, seed.ds["FitConnect customer feedback (fc_.feedback)"].id, "critical", "resolved")

    facts = build_facts(session, d.id)
    assert isinstance(facts, EvidenceFacts) and facts.decision_type == "product_feature_investment"
    assert facts.success_metric_id == seed.metric_d90
    assert facts.success_metric_data_source_id == str(seed.metrics["d90_retention"].data_source_id)
    assert len(facts.items) == 3 and all(isinstance(i.id, str) for i in facts.items)
    by_type = {i.evidence_type: i for i in facts.items}
    assert by_type["behavioral"].dq_status == "warn"                       # open warn on the events data source
    assert by_type["customer"].dq_status == "pass"                         # its critical check was resolved
    assert isinstance(by_type["behavioral"].effect_size, float) and by_type["behavioral"].effect_size == 0.03
    assert by_type["behavioral"].reliability_tier == 2 and by_type["customer"].reliability_tier == 3
    # the non-control result with the largest n is used, and numbers are floats
    (e,) = facts.experiments
    assert e.id == str(exp) and e.design == "rct" and e.result_n == 1200 and e.effect_size == 0.01 and e.mde == 0.02
    assert e.srm_flag is False and e.achieved_power is None and isinstance(e.mde, float)
    assert [(i.id, i.quote_count) for i in facts.insights] == [(str(insight), 150)]
    assert {(q.severity, q.status) for q in facts.dq_issues} == {("warn", "open"), ("critical", "resolved")}
    assert facts.heterogeneity_flag is None
    assert dict(facts.data_source_names)[str(events_ds)].startswith("FitConnect product events")


def test_evidence_fingerprint_changes_when_any_input_changes_and_is_stable_otherwise(flow, session, seed):
    d, a = flow.scored()
    f1 = evidence_fingerprint(session, d.id)
    assert f1 == evidence_fingerprint(session, d.id) == a.evidence_fingerprint
    ev = flow.evidence.list(seed.pm, d.id)[0]
    session.execute(text("UPDATE evidence SET strength_grade='A' WHERE id=:i"), {"i": ev.id})
    f2 = evidence_fingerprint(session, d.id)
    assert f2 != f1
    session.execute(text("UPDATE evidence_sources SET reliability_tier = 4 WHERE id=:i"), {"i": ev.evidence_source_id})
    f3 = evidence_fingerprint(session, d.id)
    assert f3 not in (f1, f2)
    flow.insert_dq_check(a, seed.metrics["d90_retention"].data_source_id, "warn")
    assert evidence_fingerprint(session, d.id) not in (f1, f2, f3)


def test_facts_with_experiment_evidence_score_d4_from_observed_statistics(flow, session, seed):
    from app.core.params import get_ddi_params
    from app.domain.ddi import compute_components
    d = flow.gathered()
    exp = make_experiment(session, seed, d, metric=seed.metric_d90)
    flow.add_evidence(d, "behavioral", "customer")
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "experiment", experiment_id=str(exp)))
    c = compute_components(build_facts(session, d.id), get_ddi_params(), date(2026, 10, 1))
    d4 = c.dims["D4"]
    names = {i.name: i.source for i in d4.inputs}
    assert names == {"power_factor": "default", "integrity_factor": "observed", "informativeness_factor": "observed"}
    # rct 1.0 x power 0.5 (default) x integrity 1.0 x informativeness (CI width 0.02 <= 2 x MDE 0.02) 1.0
    assert d4.score == pytest.approx(0.5)


def test_confirming_the_evidence_base_needs_a_data_source_or_evidence(flow, session, seed):
    metric = session.execute(text(
        "INSERT INTO metrics (org_id, name, definition, unit, grain, is_synthetic) VALUES (:o,'orphan_metric','manual','ratio','day',true)"
        " RETURNING id"), {"o": seed.org}).scalar()
    d, warnings = flow.decisions.create(seed.pm, canvas(seed, success_metric_id=str(metric)))
    assert "CV-3" in [w["code"] for w in warnings]                      # warn: no linked data source
    with pytest.raises(StateConflict):
        flow.decisions.confirm_evidence(seed.pm, d.id)
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "customer"))
    assert flow.decisions.confirm_evidence(seed.pm, d.id).lifecycle_stage == "evidence_gathered"
