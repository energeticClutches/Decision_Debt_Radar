"""Evidence materialisation: T-EVD-1 (idempotent), T-EVD-3 (parameter change supersedes), T-EVD-5 (expected_direction),
T-EVD-6 (traceability). T-EVD-4 and T-EVD-7 are pure and live in test_day4_stats.py, T-EVD-2 (changed source data) in
test_day4_scratch_data.py."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from day4_support import TODAY, clone_decision, no_run, pipeline
from flow import Flow, canvas
from sqlalchemy import select, text

from app.analytics.sql_guard import ALLOWED_TABLES, validate_select
from app.core.params import get_analytics_params, get_tenant_config
from app.db import models as m
from app.domain.errors import InvalidInput
from app.repositories import analysis as analysis_repo
from app.repositories.evidence_facts import build_facts

PARAMS, TENANT = get_analytics_params(), get_tenant_config()


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def evidence_of(session, d, *, status=None):
    q = select(m.Evidence).where(m.Evidence.decision_id == d.id)
    if status:
        q = q.where(m.Evidence.status == status)
    return list(session.scalars(q.order_by(m.Evidence.evidence_type, m.Evidence.created_at, m.Evidence.id).execution_options(populate_existing=True)))


def analytics_and_materialize(session, d, svc):
    """Stages 2, 4 and 5 for a decision at any stage (the pipeline entry point needs evidence_gathered)."""
    ids: list = []
    svc.stage_dq(d, no_run())
    svc.stage_quant(d, no_run(), ids)
    svc.stage_experiment(d, no_run(), ids)
    return svc.materializer.apply(d, ids), ids


# ---------------------------------------------------------------- T-EVD-1
def test_evd_1_run_creates_n_items_and_an_unchanged_rerun_keeps_n_without_marking_the_decision_stale(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    result = pipeline(session).run(seed.analyst, d.id)
    assert result.assessment.state == "scored"
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("assessed", False)
    first = evidence_of(session, d)
    assert len(first) == 3 and {e.status for e in first} == {"active"} and all(e.created_by == "agent" for e in first)
    assert sorted(e.evidence_type for e in first) == ["behavioral", "behavioral", "experiment"]
    analyses_before = len(analysis_repo.list_for_decision(session, d.id))
    stamps = {e.id: (e.updated_at, e.summary, e.stance, e.strength_grade, e.analysis_id) for e in first}

    summary, ids = analytics_and_materialize(session, d, pipeline(session))
    assert (summary.created, summary.updated, summary.unchanged, summary.superseded) == (0, 0, 3, 0) and summary.stale is False
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("assessed", False)               # a no-op must not mark the decision stale
    second = evidence_of(session, d)
    assert len(second) == 3 and {e.id: (e.updated_at, e.summary, e.stance, e.strength_grade, e.analysis_id) for e in second} == stamps
    assert len(analysis_repo.list_for_decision(session, d.id)) == analyses_before         # identical analyses are reused, not duplicated
    actions = [a.action for a in flow.audit.list_for_decision(seed.pm, d.id)]
    assert "assessment.stale" not in actions and actions.count("evidence.generated") == 3


def test_evd_1_the_four_evidence_producing_analyses_and_the_one_that_is_not(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    summary, ids = analytics_and_materialize(session, d, pipeline(session))
    assert summary.created == 3 and summary.skipped == 1                                  # segmentation creates no evidence
    by_type = {a.analysis_type: a for a in analysis_repo.list_for_decision(session, d.id)}
    assert set(by_type) == {"comparison", "segmentation", "trend", "experiment"}
    evidence = {e.analysis_id: e for e in evidence_of(session, d)}
    assert by_type["segmentation"].id not in evidence
    cmp_ev, trend_ev, exp_ev = (evidence[by_type[t].id] for t in ("comparison", "trend", "experiment"))
    assert (cmp_ev.evidence_type, cmp_ev.metric_id, cmp_ev.experiment_id) == ("behavioral", d.success_metric_id, None)
    assert cmp_ev.stance == "supports" and cmp_ev.strength_grade == "B"
    assert (trend_ev.evidence_type, trend_ev.stance, trend_ev.effect_size, trend_ev.metric_id) == ("behavioral", "neutral", None, None)   # Day 4.1: descriptive, NULL metric
    assert (exp_ev.evidence_type, exp_ev.experiment_id, exp_ev.strength_grade) == ("experiment", by_type["experiment"].result["experiment_id"] and exp_ev.experiment_id, "C")
    assert str(exp_ev.experiment_id) == by_type["experiment"].result["experiment_id"]
    for e in evidence.values():                                                           # the common fields of generated items
        assert e.created_by == "agent" and e.analysis_id and e.analysis_identity and e.source_fingerprint and e.status == "active"
        assert e.observed_end <= TODAY and e.observed_start <= e.observed_end and e.n_sample and e.summary
    source = {e.id: session.get(m.EvidenceSource, e.evidence_source_id) for e in evidence.values()}
    assert source[cmp_ev.id].ref == "fc_.events" and source[exp_ev.id].ref == "fc_.experiment_assignments"
    assert source[cmp_ev.id].reliability_tier == 2 and source[exp_ev.id].reliability_tier == 2           # the tier comes from the source


def test_evd_1_a_generated_summary_is_deterministic_text_with_numbers_from_the_analysis(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    analytics_and_materialize(session, d, pipeline(session))
    for e in evidence_of(session, d):
        a = session.get(m.AnalysisResult, e.analysis_id)
        if e.evidence_type == "experiment":
            assert f"{a.result['effect']:+.3g}" in e.summary and "SRM passed" in e.summary and "design power at the pre-registered MDE" in e.summary
        elif a.analysis_type == "comparison":
            assert f"{a.result['effect']:+.1%}" in e.summary and "Observational comparison, not randomised" in e.summary
        else:
            assert "Descriptive, no test" in e.summary


# ---------------------------------------------------------------- T-EVD-3
def altered_tenant(**changes):
    data = copy.deepcopy(dict(TENANT.data))
    for metric, value in changes.items():
        data["metrics"][metric]["materiality"] = value
    return replace(TENANT, data=data, content_hash="f" * 64)


def test_evd_3_a_parameter_change_gives_new_identities_and_supersedes_the_old_items_without_deleting_them(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    assert pipeline(session).run(seed.analyst, d.id).assessment.state == "scored"
    old = evidence_of(session, d)
    old_ids = {e.id for e in old}
    old_identity = {e.id: e.analysis_identity for e in old}
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("assessed", False)

    new_svc = pipeline(session, tenant=altered_tenant(paid_conversion_rate=0.05))          # materiality 0.02 -> 0.05
    summary, ids = analytics_and_materialize(session, d, new_svc)
    assert (summary.created, summary.superseded, summary.updated, summary.unchanged) == (3, 3, 0, 0)
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", True)           # a change after the assessment: stale

    all_rows = evidence_of(session, d)
    assert len(all_rows) == 6 and {e.id for e in all_rows} >= old_ids                       # never deleted
    active, superseded = evidence_of(session, d, status="active"), evidence_of(session, d, status="superseded")
    assert len(active) == 3 and {e.id for e in superseded} == old_ids
    assert not {e.analysis_identity for e in active} & set(old_identity.values())           # genuinely new identities
    by_slot = {session.get(m.AnalysisResult, e.analysis_id).params["slot"]: e for e in active}
    for e in superseded:
        slot = session.get(m.AnalysisResult, e.analysis_id).params["slot"]
        assert e.superseded_by == by_slot[slot].id and e.superseded_at is not None
        assert e.analysis_identity == old_identity[e.id]                                   # the old item keeps its own identity
    # each active item points at an analysis row that carries the NEW parameter hash (the old rows keep the old one)
    new_hashes = {session.get(m.AnalysisResult, e.analysis_id).params["config"]["tenant_config_hash"] for e in active}
    old_hashes = {session.get(m.AnalysisResult, e.analysis_id).params["config"]["tenant_config_hash"] for e in superseded}
    assert new_hashes == {"f" * 64} and old_hashes == {TENANT.content_hash}
    # the facts see only the active items
    facts = build_facts(session, d.id)
    assert {i.id for i in facts.items} == {str(e.id) for e in active}
    # ... and the database refuses a second active item with the same identity
    clash = active[0]
    with pytest.raises(Exception, match="ux_evidence_active_identity|duplicate key"):
        session.execute(text(
            "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start, observed_end,"
            " created_by, is_synthetic, analysis_identity) SELECT decision_id, evidence_source_id, evidence_type, 'dup', stance, strength_grade,"
            " observed_start, observed_end, 'agent', true, analysis_identity FROM evidence WHERE id = :i"), {"i": clash.id})


def test_evd_3_historical_traceability_still_resolves_for_superseded_evidence(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    pipeline(session).run(seed.analyst, d.id)
    assessment = session.scalars(select(m.DecisionAssessment).where(m.DecisionAssessment.decision_id == d.id)).one()
    old = next(e for e in evidence_of(session, d) if e.evidence_type == "experiment")
    claim = session.execute(text(
        "INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, conclusion_ref, is_synthetic)"
        " VALUES (:a,'The price test is inconclusive','descriptive','neutral','medium','D4 Experimental Strength',true) RETURNING id"),
        {"a": assessment.id}).scalar()
    session.execute(text("INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (:c,:e,true)"), {"c": claim, "e": old.id})
    analytics_and_materialize(session, d, pipeline(session, tenant=altered_tenant(paid_conversion_rate=0.05)))
    session.refresh(old)
    assert old.status == "superseded"
    row = session.execute(text("SELECT evidence_id, evidence_status, analysis_id, analysis_type, query_ref, dq_status, row_type"
                               " FROM v_traceability_matrix WHERE claim_id = :c"), {"c": claim}).one()
    assert row.evidence_id == old.id and row.evidence_status == "superseded" and row.analysis_id == old.analysis_id
    assert row.analysis_type == "experiment" and row.query_ref == f"analysis_results:{old.analysis_id}"
    assert row.dq_status in ("pass", "warn", "critical") and row.row_type == "claim_link"
    analysis = analysis_repo.get_analysis(session, old.analysis_id)
    assert analysis.query_text and analysis.params["config"]["tenant_config_hash"] == TENANT.content_hash     # the OLD parameters
    # the freshness and health views count active evidence only
    n_fresh = session.execute(text("SELECT count(*) FROM v_evidence_freshness WHERE decision_id=:d"), {"d": d.id}).scalar()
    assert n_fresh == 3
    # the claim of the historical assessment keeps resolving even though the item is superseded; gap rows count active items only
    gaps = session.execute(text("SELECT count(*) FROM v_traceability_matrix WHERE decision_id=:d AND row_type='gap'"), {"d": d.id}).scalar()
    assert gaps == 2                                                                      # customer and financial are missing (checklist)


def test_evd_3_a_source_data_only_change_keeps_the_identity_while_parameters_define_it(session, seed, flow):
    """The identity covers the parameters, never the data: the same parameters give the same identity on every run."""
    d1, d2 = clone_decision(flow, seed, "pricing"), clone_decision(flow, seed, "pricing")
    analytics_and_materialize(session, d1, pipeline(session))
    analytics_and_materialize(session, d2, pipeline(session))
    ids1 = {session.get(m.AnalysisResult, e.analysis_id).params_hash for e in evidence_of(session, d1)}
    ids2 = {session.get(m.AnalysisResult, e.analysis_id).params_hash for e in evidence_of(session, d2)}
    assert ids1 == ids2                                                                   # the parameter hash does not depend on the decision
    assert {e.analysis_identity for e in evidence_of(session, d1)}.isdisjoint({e.analysis_identity for e in evidence_of(session, d2)})   # the identity does


# ---------------------------------------------------------------- T-EVD-5
def test_evd_5_expected_direction_is_required_by_the_canvas_and_validated(session, seed, flow):
    fields = canvas(seed)
    del fields["expected_direction"]
    with pytest.raises(InvalidInput) as exc:
        flow.decisions.create(seed.pm, fields)
    assert "expected_direction" in exc.value.detail["fields"]
    with pytest.raises(InvalidInput):
        flow.decisions.create(seed.pm, canvas(seed, expected_direction="sideways"))
    for direction in ("increase", "decrease", "no_material_decrease"):
        d, _ = flow.decisions.create(seed.pm, canvas(seed, expected_direction=direction))
        assert d.expected_direction == direction
    d = flow.gathered()
    changed = flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "decrease"})
    assert changed.expected_direction == "decrease"
    with pytest.raises(InvalidInput):
        flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "up"})
    # the seeded decisions carry the O1 values
    assert {k: v.expected_direction for k, v in seed.decisions.items()} == {
        "ai_coach": "increase", "onboarding": "increase", "community": "increase", "pricing": "no_material_decrease"}


def test_evd_5_expected_direction_is_in_the_canvas_stale_column_list(session, seed, flow):
    d, a = flow.scored()
    assert flow.stage(d) == "assessed"
    flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "decrease"})
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", True)
    assert flow.audit_actions(d)[-2:] == ["canvas.edited", "assessment.stale"]


def test_evd_5_a_changed_expected_direction_changes_the_stance_in_place(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    analytics_and_materialize(session, d, pipeline(session))
    cmp_ev = next(e for e in evidence_of(session, d) if session.get(m.AnalysisResult, e.analysis_id).analysis_type == "comparison")
    assert cmp_ev.stance == "supports"
    flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "decrease"})          # the same data now contradicts the hypothesis
    summary, _ = analytics_and_materialize(session, d, pipeline(session))
    assert summary.updated >= 1 and summary.created == 0 and summary.superseded == 0       # same identity: updated in place
    session.refresh(cmp_ev)
    assert cmp_ev.stance == "contradicts" and cmp_ev.status == "active"


# ---------------------------------------------------------------- T-EVD-6
def test_evd_6_every_generated_item_resolves_through_its_analysis_to_the_query_the_view_and_the_dq_checks(session, seed, flow):
    for scenario in ("pricing", "ai_coach"):
        d = clone_decision(flow, seed, scenario)
        analytics_and_materialize(session, d, pipeline(session))
        dq_sources = {c.data_source_id for c in session.scalars(select(m.DqCheck).where(m.DqCheck.decision_id == d.id))}
        items = evidence_of(session, d)
        assert len(items) == 3
        for e in items:
            assert e.analysis_id is not None, "every generated item has analysis_id"
            a = session.get(m.AnalysisResult, e.analysis_id)
            assert a.decision_id == d.id and a.analysis_identity == e.analysis_identity and a.source_fingerprint == e.source_fingerprint
            # the analysis: query, params, n, result, limitations, dq_status
            assert a.query_text and validate_select(a.query_text).tables                       # the stored query passes the SQL guard
            assert a.params["query"]["name"] and a.params["config"]["analytics_params_hash"] == PARAMS.content_hash
            assert a.n and a.result and a.limitations and a.dq_status in ("pass", "warn", "critical")
            assert a.params["slot"].startswith(str(d.id)) and a.params_hash
            # ... the view: every view it read is allow-listed and belongs to a registered data source with DQ checks for this decision
            views = a.params["source_views"]
            assert views and all(v in ALLOWED_TABLES for v in views)
            assert a.params["primary_source_view"] in views
            for v in views:
                ref = TENANT.data_source_ref(v)
                es = session.scalars(select(m.EvidenceSource).where(m.EvidenceSource.ref == ref)).first()
                assert es is not None and es.data_source_id in dq_sources, (v, ref)
            # the evidence source is the data source of the primary view
            src = session.get(m.EvidenceSource, e.evidence_source_id)
            assert src.ref == TENANT.data_source_ref(a.params["primary_source_view"])
    # the traceability view resolves a claim on a generated item down to the analysis and query reference
    d = clone_decision(flow, seed, "pricing")
    pipeline(session).run(seed.analyst, d.id)
    assessment = session.scalars(select(m.DecisionAssessment).where(m.DecisionAssessment.decision_id == d.id)).one()
    for e in evidence_of(session, d):
        claim = session.execute(text(
            "INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic)"
            " VALUES (:a,'c','descriptive','neutral','low',true) RETURNING id"), {"a": assessment.id}).scalar()
        session.execute(text("INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (:c,:e,true)"), {"c": claim, "e": e.id})
    rows = session.execute(text("SELECT analysis_id, analysis_type, query_ref, evidence_status, dq_status FROM v_traceability_matrix"
                                " WHERE decision_id=:d AND row_type='claim_link'"), {"d": d.id}).all()
    assert len(rows) == 3 and all(r.analysis_id and r.query_ref.startswith("analysis_results:") and r.evidence_status == "active" for r in rows)
    assert {r.analysis_type for r in rows} == {"comparison", "trend", "experiment"}


def test_evd_6_analysis_rows_are_insert_only_except_agent_run_id(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    analytics_and_materialize(session, d, pipeline(session))
    a = analysis_repo.list_for_decision(session, d.id)[0]
    with pytest.raises(Exception, match="historical"):
        session.execute(text("UPDATE analysis_results SET n = 1 WHERE id = :i"), {"i": a.id})
