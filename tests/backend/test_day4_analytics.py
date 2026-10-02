"""Heterogeneity and experiment statistics against the seeded FitConnect data (T-HET-1, T-HET-2, T-EXP-1 to T-EXP-5).
The analyses read the committed synthetic data through the read-only executor; results are stored in the rolled-back
transaction. Pure-maths cases are in test_day4_stats.py."""

from __future__ import annotations

import pytest
from day4_support import clone_decision, no_run, pipeline
from flow import Flow
from sqlalchemy import select, text

from app.analytics import analyses as analyses_mod
from app.analytics import experiments as exp_mod
from app.analytics.executor import ReadOnlyExecutor
from app.core.params import get_analytics_params, get_ddi_params, get_tenant_config
from app.db import models as m
from app.domain.ddi import compute_components
from app.repositories import analysis as analysis_repo
from app.repositories import experiments as experiments_repo
from app.repositories.evidence_facts import build_facts

PARAMS, TENANT = get_analytics_params(), get_tenant_config()


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def quant(session, d):
    """Run the quantitative stage for a decision and return (output, analysis ids)."""
    ids: list = []
    out, status = pipeline(session).stage_quant(d, no_run(), ids)
    assert status == "succeeded", out
    return out, ids


def experiments_stage(session, d, svc=None):
    ids: list = []
    out, status = (svc or pipeline(session)).stage_experiment(d, no_run(), ids)
    return out, ids


def stored(session, analysis_type, d):
    return [a for a in analysis_repo.list_for_decision(session, d.id) if a.analysis_type == analysis_type]


# ---------------------------------------------------------------- T-HET-1
def test_het_1_community_is_true_and_the_stored_result_has_every_field(session, seed, flow):
    d = clone_decision(flow, seed, "community")
    out, ids = quant(session, d)
    (seg,) = stored(session, "segmentation", d)
    r = seg.result
    # every field listed in brief section 6
    for key in ("segment_key", "segments_scanned", "segments_eligible", "min_segment_n", "materiality_threshold",
                "multiple_comparison_method", "pairs_tested", "alpha_adjusted", "segments", "triggering_pairs", "flag"):
        assert key in r, key
    assert r["flag"] is True and r["segment_key"] == "engagement_style"
    assert (r["segments_scanned"], r["segments_eligible"], r["min_segment_n"]) == (3, 3, 500)
    assert r["materiality_threshold"] == 0.02 and r["multiple_comparison_method"] == "bonferroni"
    assert r["pairs_tested"] == 3 and r["alpha_adjusted"] == pytest.approx(0.05 / 3)
    effects = {s["segment"]: s for s in r["segments"]}
    assert effects["social_exerciser"]["effect"] == pytest.approx(0.196, abs=1e-3)      # the brief's +0.196
    assert effects["time_pressed"]["effect"] == pytest.approx(-0.080, abs=1e-3)          # the brief's -0.080
    assert effects["solo_athlete"]["effect"] == pytest.approx(0.0, abs=1e-3)
    for s in effects.values():                                                           # per-segment effects and n
        assert s["n_treatment"] >= 500 and s["n_comparison"] >= 500 and s["eligible"]
    pairs = {(p["segment_a"], p["segment_b"]) for p in r["triggering_pairs"]}
    assert ("social_exerciser", "time_pressed") in pairs
    opposite = next(p for p in r["triggering_pairs"] if (p["segment_a"], p["segment_b"]) == ("social_exerciser", "time_pressed"))
    assert opposite["rule_a_opposite_signs"] is True
    # stored with its identity, parameter hash, source fingerprint, query and parameters
    assert seg.analysis_identity and seg.params_hash and seg.source_fingerprint and seg.query_text and seg.n == 40730
    assert seg.params["config"]["tenant_config_hash"] == TENANT.content_hash
    assert seg.params["config"]["analytics_params_hash"] == PARAMS.content_hash
    # the flag reaches the facts builder
    assert build_facts(session, d.id).heterogeneity_flag is True
    # segmentation produces no evidence item
    assert session.execute(text("SELECT count(*) FROM evidence WHERE analysis_id = :a"), {"a": seg.id}).scalar() == 0
    assert out["analyses"][1]["heterogeneity_flag"] is True and out["analyses"][1]["creates_evidence"] is False


# ---------------------------------------------------------------- T-HET-2
def test_het_2_ai_coach_is_false_because_the_gap_is_positive_in_every_segment(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    quant(session, d)
    (seg,) = stored(session, "segmentation", d)
    r = seg.result
    assert r["flag"] is False and r["segment_key"] == "engagement_style"
    assert r["segments_eligible"] == 3 and r["triggering_pairs"] == [] and r["pairs_tested"] == 3
    gaps = {s["segment"]: s["effect"] for s in r["segments"]}
    assert all(g > 0.2 for g in gaps.values()), gaps                                   # positive in every segment
    assert max(gaps.values()) - min(gaps.values()) < r["materiality_threshold"]        # and the segments do not diverge materially
    assert not any(p["rule_a_opposite_signs"] or p["rule_b_difference_significant"] for p in r["pairs"])
    assert build_facts(session, d.id).heterogeneity_flag is False
    # the aggregate-vs-segment gap is not a criterion: the aggregate effect is reported but never tested
    assert r["aggregate_effect"] == pytest.approx(0.2304, abs=1e-3)


def test_het_unknown_for_pricing_and_absent_for_onboarding(session, seed, flow):
    pricing = clone_decision(flow, seed, "pricing")
    quant(session, pricing)
    (seg,) = stored(session, "segmentation", pricing)
    assert seg.result["flag"] is None and seg.result["segments_eligible"] == 1          # CA only: fewer than 2 eligible segments
    assert build_facts(session, pricing.id).heterogeneity_flag is None                  # unknown, not False
    onboarding = clone_decision(flow, seed, "onboarding")
    assert build_facts(session, onboarding.id).heterogeneity_flag is None               # no segmentation analysis at all


def test_het_the_facts_use_the_latest_segmentation_analysis(session, seed, flow):
    d = clone_decision(flow, seed, "community")
    quant(session, d)
    assert build_facts(session, d.id).heterogeneity_flag is True
    (old,) = stored(session, "segmentation", d)
    # a later segmentation (new parameters) with a different flag wins
    from app.repositories.analysis import add_analysis
    add_analysis(session, decision_id=d.id, analysis_type="segmentation", params={"metric_id": str(d.success_metric_id), "key": "x"},
                 result={"flag": False}, n=1, is_synthetic=True, analysis_identity="later", params_hash="h", source_fingerprint="f")
    assert build_facts(session, d.id).heterogeneity_flag is False
    add_analysis(session, decision_id=d.id, analysis_type="segmentation", params={"metric_id": str(d.success_metric_id), "key": "y"},
                 result={"flag": None}, n=1, is_synthetic=True, analysis_identity="latest", params_hash="h", source_fingerprint="f")
    assert build_facts(session, d.id).heterogeneity_flag is None
    assert old.result["flag"] is True                                                    # history is never rewritten


# ---------------------------------------------------------------- T-EXP-1
def raw_outcomes(session, key, outcome):
    rows = session.execute(text(
        "SELECT a.variant, count(*) n, avg(o.value) mean FROM fc_.experiment_assignments a JOIN fc_.experiment_outcomes o"
        " ON o.experiment_key = a.experiment_key AND o.user_id = a.user_id WHERE a.experiment_key=:k AND o.metric_name=:m GROUP BY 1"),
        {"k": key, "m": outcome}).all()
    return {r[0]: (r[1], float(r[2])) for r in rows}


def test_exp_1_effect_is_treatment_minus_control_on_the_natural_scale_and_the_ci_uses_it(session, seed, flow):
    for scenario, key, outcome, control, treatment, unit in (
            ("pricing", "premium_price_test_2026q2", "converted_to_paid", "control_9_99", "treatment_11_99", "proportion"),
            ("ai_coach", "ai_coach_holdout_2026q1", "workouts_14d", "holdout", "ai_coach", "count")):
        d = clone_decision(flow, seed, scenario)
        out, ids = experiments_stage(session, d)
        raw = raw_outcomes(session, key, outcome)
        expected = raw[treatment][1] - raw[control][1]
        (exp,) = experiments_repo.list_for_decision(session, d.id)
        rows = {r.variant: r for r in experiments_repo.list_results(session, exp.id)}
        assert set(rows) == {control, treatment}
        assert float(rows[treatment].effect_size) == pytest.approx(expected, abs=1e-9)      # treatment minus control, natural scale
        assert rows[control].effect_size is None and rows[control].ci_low is None and rows[control].p_value is None
        assert rows[control].srm_flag is None                                                # the control row leaves these NULL
        assert rows[treatment].ci_low < rows[treatment].effect_size < rows[treatment].ci_high
        assert (rows[control].n, rows[treatment].n) == (raw[control][0], raw[treatment][0])
        assert float(rows[control].metric_value) == pytest.approx(raw[control][1])
        assert float(rows[treatment].metric_value) == pytest.approx(raw[treatment][1])
        (a,) = stored(session, "experiment", d)
        assert a.result["effect"] == pytest.approx(expected, abs=1e-9)                       # the same scale in the analysis
        half = (a.result["ci_high"] - a.result["ci_low"]) / 2
        assert a.result["ci_low"] == pytest.approx(expected - half) and a.result["ci_high"] == pytest.approx(expected + half)
        assert a.result["outcome_kind"] == ("binary" if unit == "proportion" else "continuous")
        assert a.result["method"] == ("two_proportion_z" if unit == "proportion" else "welch_t")


# ---------------------------------------------------------------- T-EXP-2
def test_exp_2_srm_uses_planned_treatment_share_ai_coach_true_pricing_false_missing_null(session, seed, flow):
    ai = clone_decision(flow, seed, "ai_coach")
    out, _ = experiments_stage(session, ai)
    (e,) = out["experiments"]
    assert e["srm_flag"] is True and e["srm_chi2"] == pytest.approx(240.0) and e["srm_p_value"] < 1e-50
    (a,) = stored(session, "experiment", ai)
    assert a.result["srm"]["planned_allocation"] == {"ai_coach": 0.5, "holdout": 0.5}
    assert a.result["srm"]["observed_allocation"]["ai_coach"] == pytest.approx(0.30)
    assert a.result["srm"]["observed_counts"] == {"ai_coach": 450, "holdout": 1050}
    assert a.result["srm"]["expected_counts"] == {"ai_coach": 750.0, "holdout": 750.0}
    assert a.result["srm"]["alpha"] == 0.001 and a.result["srm"]["flag"] is True
    (exp,) = experiments_repo.list_for_decision(session, ai.id)
    assert next(r for r in experiments_repo.list_results(session, exp.id) if r.variant == "ai_coach").srm_flag is True
    # Pricing passes
    pr = clone_decision(flow, seed, "pricing")
    out, _ = experiments_stage(session, pr)
    assert out["experiments"][0]["srm_flag"] is False and out["experiments"][0]["srm_p_value"] == pytest.approx(1.0)
    # no planned share: the flag is NULL and the DDI treats the integrity input as defaulted
    no_share = clone_decision(flow, seed, "ai_coach")
    session.execute(text("UPDATE experiments SET planned_treatment_share = NULL WHERE decision_id = :d"), {"d": no_share.id})
    out, _ = experiments_stage(session, no_share)
    assert out["experiments"][0]["srm_flag"] is None
    (exp,) = experiments_repo.list_for_decision(session, no_share.id)
    assert all(r.srm_flag is None for r in experiments_repo.list_results(session, exp.id))
    (na,) = stored(session, "experiment", no_share)
    assert na.result["srm"] is None and "sample-ratio check was not run" in na.limitations
    # the share is what is tested against: a planned 30% treatment share makes the same 450/1050 split fine
    planned30 = clone_decision(flow, seed, "ai_coach")
    session.execute(text("UPDATE experiments SET planned_treatment_share = 0.3 WHERE decision_id = :d"), {"d": planned30.id})
    out, _ = experiments_stage(session, planned30)
    assert out["experiments"][0]["srm_flag"] is False


# ---------------------------------------------------------------- T-EXP-3
class Perturb:
    """Delegates to the real executor but rewrites the aggregated outcome rows (a stand-in for different outcome values)."""

    def __init__(self, inner: ReadOnlyExecutor, mutate):
        self.inner, self.mutate = inner, mutate

    def run(self, template, params=None):
        rows = self.inner.run(template, params)
        return self.mutate(rows) if template.name == "experiment.outcomes" else rows


def analyze(engine, spec, mutate=None):
    ex = ReadOnlyExecutor(engine)
    return exp_mod.analyze_experiment(Perturb(ex, mutate) if mutate else ex, PARAMS, spec)


def spec_from(session, d):
    (e,) = experiments_repo.list_for_decision(session, d.id)
    return exp_mod.ExperimentSpec(
        id=str(e.id), name=e.name, design=e.design, source_ref=e.source_ref, control_variant=e.control_variant, outcome_key=e.outcome_key,
        planned_treatment_share=float(e.planned_treatment_share) if e.planned_treatment_share is not None else None,
        mde=float(e.mde) if e.mde is not None else None, planned_sample=e.planned_sample, start_date=e.start_date, end_date=e.end_date,
        primary_metric_id=str(e.primary_metric_id) if e.primary_metric_id else None)


def test_exp_3_design_power_uses_the_mde_and_n_and_is_independent_of_the_observed_effect(session, seed, flow, engine):
    from dataclasses import replace
    for scenario, treatment_variant in (("pricing", "treatment_11_99"), ("ai_coach", "ai_coach")):
        d = clone_decision(flow, seed, scenario)
        spec = spec_from(session, d)
        base = analyze(engine, spec)

        def shift_treatment(rows, tv=treatment_variant, binary=scenario == "pricing"):
            out = []
            for r in rows:
                r = dict(r)
                if r["variant"] == tv:                                      # change the OUTCOME VALUES of the treatment arm only, not n
                    r["mean"] = (0.9 if binary else 9.0)
                out.append(r)
            return out
        changed = analyze(engine, spec, shift_treatment)
        assert changed.n == base.n and changed.variants[treatment_variant]["n"] == base.variants[treatment_variant]["n"]
        assert changed.difference.effect != pytest.approx(base.difference.effect)          # the observed effect changed a lot ...
        assert changed.design_power == base.design_power                                    # ... the design power did not
        assert 0 < base.design_power <= 1
        # a larger MDE or larger n changes it (it is a function of MDE and n)
        bigger_mde = analyze(engine, replace(spec, mde=spec.mde * 4))
        assert bigger_mde.design_power > base.design_power
        # a missing MDE: power is None
        assert analyze(engine, replace(spec, mde=None)).design_power is None
    # the seeded values: Pricing is far below 0.8, and the AI Coach holdout is NOT low at its MDE of 0.5 workouts (reported in the notes)
    pr = analyze(engine, spec_from(session, clone_decision(flow, seed, "pricing")))
    assert pr.design_power == pytest.approx(0.109, abs=0.005) and pr.design_power < 0.8
    ai = analyze(engine, spec_from(session, clone_decision(flow, seed, "ai_coach")))
    assert ai.design_power > 0.99
    assert ai.result_payload(PARAMS, 0.8)["design_power"]["label"] == "design power at the pre-registered MDE"


def test_exp_3_missing_mde_means_power_is_none_so_the_ddi_reports_it_as_defaulted(session, seed, flow):
    withmde = clone_decision(flow, seed, "pricing")
    nomde = clone_decision(flow, seed, "pricing")
    session.execute(text("UPDATE experiments SET mde = NULL WHERE decision_id = :d"), {"d": nomde.id})
    for d, observed in ((withmde, True), (nomde, False)):
        svc = pipeline(session)
        ids: list = []
        svc.stage_dq(d, no_run())
        svc.stage_quant(d, no_run(), ids)
        svc.stage_experiment(d, no_run(), ids)
        svc.materializer.apply(d, ids)
        facts = build_facts(session, d.id)
        (exp,) = facts.experiments
        assert (exp.achieved_power is not None) is observed
        assert (exp.srm_flag is not None)                                                  # SRM is observed in both cases
        inputs = {i.name: i.source for i in compute_components(facts, get_ddi_params(), flow.ctx.clock.today()).dims["D4"].inputs}
        assert inputs["power_factor"] == ("observed" if observed else "default")
        assert inputs["integrity_factor"] == "observed"
        if not observed:
            assert inputs["informativeness_factor"] == "default"                          # no MDE: informativeness cannot be read either


# ---------------------------------------------------------------- T-EXP-4
def test_exp_4_the_pricing_ci_spans_zero_so_the_stance_is_neutral_under_no_material_decrease(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    assert d.expected_direction == "no_material_decrease"
    out, _ = experiments_stage(session, d)
    (e,) = out["experiments"]
    assert e["ci_low"] < 0 < e["ci_high"]                                                   # inconclusive
    assert e["srm_flag"] is False and e["design_power"] < 0.8
    (a,) = stored(session, "experiment", d)
    assert a.result["materiality"] == 0.02
    assert a.result["ci_low"] <= -0.02 and a.result["ci_high"] >= -0.02                     # neither bound decides under -materiality
    pipeline(session).materializer.apply(d, [a.id])
    (ev,) = session.scalars(select(m.Evidence).where(m.Evidence.decision_id == d.id, m.Evidence.evidence_type == "experiment"))
    assert (ev.stance, ev.strength_grade) == ("neutral", "C")


# ---------------------------------------------------------------- T-EXP-5
def test_exp_5_experiment_results_are_upserted_one_row_per_variant(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    svc = pipeline(session)
    for _ in range(3):
        experiments_stage(session, d, svc)
        (exp,) = experiments_repo.list_for_decision(session, d.id)
        results = experiments_repo.list_results(session, exp.id)
        assert sorted(r.variant for r in results) == ["control_9_99", "treatment_11_99"]
    ids_first = {r.variant: r.id for r in results}
    experiments_stage(session, d, svc)
    assert {r.variant: r.id for r in experiments_repo.list_results(session, exp.id)} == ids_first       # updated in place
    # the upsert target is enforced by the database
    with pytest.raises(Exception, match="uq_experiment_results_variant|duplicate key"):
        session.execute(text("INSERT INTO experiment_results (experiment_id, variant, n, is_synthetic) VALUES (:e, 'control_9_99', 1, true)"),
                        {"e": exp.id})


def test_exp_5_the_upsert_replaces_the_values_when_the_statistics_change(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    (exp,) = experiments_repo.list_for_decision(session, d.id)
    experiments_repo.upsert_results(session, exp, [
        {"variant": "control_9_99", "n": 10, "metric_value": 0.5, "effect_size": None, "ci_low": None, "ci_high": None, "p_value": None,
         "srm_flag": None, "notes": "old"}])
    experiments_repo.upsert_results(session, exp, [
        {"variant": "control_9_99", "n": 20, "metric_value": 0.6, "effect_size": None, "ci_low": None, "ci_high": None, "p_value": None,
         "srm_flag": None, "notes": "new"}])
    (row,) = experiments_repo.list_results(session, exp.id)
    assert (row.n, float(row.metric_value), row.notes) == (20, 0.6, "new")


def test_experiment_and_comparison_drafts_are_deterministic(session, seed, flow, engine):
    d = clone_decision(flow, seed, "pricing")
    info = pipeline(session)._decision_info(d)
    ex = ReadOnlyExecutor(engine)
    a = analyses_mod.comparison_analyses(ex, PARAMS, TENANT, info, pipeline(session).clock.today())
    b = analyses_mod.comparison_analyses(ex, PARAMS, TENANT, info, pipeline(session).clock.today())
    assert [x.result for x in a] == [x.result for x in b] and [x.rows for x in a] == [x.rows for x in b]
