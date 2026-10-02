"""Day 4.1, Remediation 2 on the real pipeline: descriptive evidence is materialised with a NULL metric link, stays active
evidence with its analysis link, and no longer dilutes D6 (B2). Pure D6 rules are in test_d6_descriptive.py."""

from __future__ import annotations

from dataclasses import replace

import pytest
from day4_support import TODAY, clone_decision, pipeline
from fastapi.testclient import TestClient
from flow import Flow
from sqlalchemy import select, text

from app.core import deps
from app.core.clock import FixedClock
from app.db import models as m
from app.domain.ddi.scoring import compute_components
from app.core.params import get_ddi_params
from app.main import app
from app.repositories import analysis as analysis_repo
from app.repositories.evidence_facts import build_facts

DDI = get_ddi_params()


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


@pytest.fixture()
def client(session):
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def active(session, d):
    return list(session.scalars(select(m.Evidence).where(m.Evidence.decision_id == d.id, m.Evidence.status == "active")
                                .order_by(m.Evidence.id).execution_options(populate_existing=True)))


def analysis_type(session, e) -> str:
    return session.get(m.AnalysisResult, e.analysis_id).analysis_type


def d6_of(facts_):
    c = compute_components(facts_, DDI, TODAY)
    return c.dims["D6"].score, c.d6_raw, c.dims["D6"].details.get("items", 0)


@pytest.mark.parametrize("scenario", ["ai_coach", "community", "pricing"])
def test_trend_and_funnel_evidence_has_a_null_metric_link_and_the_comparison_keeps_it(session, seed, flow, scenario):
    d = clone_decision(flow, seed, scenario)
    pipeline(session).run(seed.analyst, d.id)
    session.refresh(d)
    rows = active(session, d)
    by_type = {analysis_type(session, e): e for e in rows}
    assert "trend" in by_type
    for kind in ("trend", "funnel"):
        if kind in by_type:
            e = by_type[kind]
            assert (e.evidence_type, e.stance, e.effect_size, e.ci_low, e.ci_high, e.metric_id) == ("behavioral", "neutral", None, None, None, None)
            a = session.get(m.AnalysisResult, e.analysis_id)
            # the metric stays traceable through the analysis row and the summary
            assert a.params["metric_id"] == str(d.success_metric_id) and a.params["metric_name"] in e.summary
            assert e.analysis_identity == a.analysis_identity
    if "comparison" in by_type:
        assert by_type["comparison"].metric_id == d.success_metric_id
    if "experiment" in by_type:
        assert by_type["experiment"].metric_id is None and by_type["experiment"].experiment_id is not None


@pytest.mark.parametrize("scenario", ["ai_coach", "community"])
def test_d6_in_the_pipeline_counts_only_quantified_evidence_and_the_old_linkage_would_have_diluted_it(session, seed, flow, scenario):
    d = clone_decision(flow, seed, scenario)
    pipeline(session).run(seed.analyst, d.id)
    f = build_facts(session, d.id)
    descriptive_ids = {str(e.id) for e in active(session, d) if e.effect_size is None and e.evidence_type == "behavioral"}
    assert descriptive_ids, "the scenario produces descriptive evidence"
    actual = d6_of(f)
    quantified_only = replace(f, items=tuple(i for i in f.items if i.id not in descriptive_ids))
    assert actual == d6_of(quantified_only)                                       # descriptive items do not enter D6
    # counterfactual (the Day-4 linkage): re-link the descriptive items to the success metric and D6 is lower
    relinked = replace(f, items=tuple(replace(i, metric_id=f.success_metric_id) if i.id in descriptive_ids else i for i in f.items))
    old = d6_of(relinked)
    assert old[2] == actual[2] + len(descriptive_ids)
    if actual[1] > 0:
        assert old[1] < actual[1]


def test_descriptive_evidence_stays_active_evidence_with_its_analysis_link_in_every_downstream_input(session, seed, flow, client):
    d = clone_decision(flow, seed, "ai_coach")
    pipeline(session).run(seed.analyst, d.id)
    descriptive = [e for e in active(session, d) if e.effect_size is None and e.evidence_type == "behavioral"]
    assert len(descriptive) == 1 and analysis_type(session, descriptive[0]) == "trend"
    e = descriptive[0]
    assert e.status == "active" and e.analysis_id is not None and e.analysis_identity
    # the evidence set the next stages read: the facts items ...
    assert str(e.id) in {i.id for i in build_facts(session, d.id).items}
    # ... and the evidence list endpoint (with its analysis link)
    r = client.get(f"/decisions/{d.id}/evidence", headers={"X-Demo-User": seed.analyst.id})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["id"] == str(e.id))
    assert row["status"] == "active" and row["analysis_id"] == str(e.analysis_id) and row["metric_id"] is None
    # ... and the traceability matrix, down to the analysis and its query
    assessment = session.scalars(select(m.DecisionAssessment).where(m.DecisionAssessment.decision_id == d.id)).one()
    claim = session.execute(text(
        "INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic)"
        " VALUES (:a,'c','descriptive','neutral','low',true) RETURNING id"), {"a": assessment.id}).scalar()
    session.execute(text("INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (:c,:e,true)"), {"c": claim, "e": e.id})
    rows = session.execute(text("SELECT analysis_id, analysis_type, query_ref, evidence_status FROM v_traceability_matrix"
                                " WHERE claim_id = :c"), {"c": claim}).all()
    assert len(rows) == 1 and rows[0].analysis_type == "trend" and rows[0].evidence_status == "active"
    assert str(rows[0].analysis_id) == str(e.analysis_id) and rows[0].query_ref.startswith("analysis_results:")


def test_the_evidence_identity_is_unchanged_by_the_null_metric_link(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    pipeline(session).run(seed.analyst, d.id)
    before = {e.id: (e.analysis_identity, e.updated_at) for e in active(session, d)}
    for a in analysis_repo.list_for_decision(session, d.id):
        ev = [e for e in active(session, d) if e.analysis_id == a.id]
        assert all(e.analysis_identity == a.analysis_identity for e in ev)
    session.execute(text("UPDATE decisions SET lifecycle_stage='evidence_gathered', assessment_stale=true WHERE id=:d"), {"d": d.id})
    session.refresh(d)
    pipeline(session).run(seed.analyst, d.id)                                        # nothing changed: nothing is superseded or updated
    after = {e.id: (e.analysis_identity, e.updated_at) for e in active(session, d)}
    assert after == before
