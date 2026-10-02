"""Pure NBE engine tests (brief section 4, tests 14-18). No database."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest
from ddi_factories import AS_OF, METRIC, METRIC_DS, NBE, PARAMS, facts, good_experiment, item, random_facts

from app.domain.ddi import assess, components_from_scores, score_components
from app.domain.facts import DqIssue, InsightFact
from app.domain.nbe import Recommendation, rank_recommendations, recommend

DIMS = dict(D1=0.55, D2=0.714, D3=0.60, D4=0.10, D5=0.65, D6=0.45, D7=0.30)
ALL_TYPES = frozenset({"behavioral", "customer", "experiment", "financial"})


def example_result(**over):
    kw = dict(d6_raw=0.45, types_present=ALL_TYPES, details={"D4": {"best_design": "holdout", "best_power_factor": 0.5}})
    kw.update(over)
    comps = components_from_scores("product_feature_investment", DIMS, 0.20, 0.30, PARAMS, **kw)
    return score_components(comps, PARAMS, AS_OF)


def by_id(recs):
    return {r.action_id: r for r in recs}


# ------------------------------------------------------------------ 14. worked example (updated per R9)
def test_14_nbe_spec_worked_example():
    r = example_result()
    assert r.ddi == 61.0
    recs = by_id(recommend(r, None, PARAMS, NBE))
    fin, hold, interview = recs["financial_model_with_sensitivity"], recs["powered_holdout_test"], recs["customer_interview_sprint"]
    assert (round(fin.potential_ddi_reduction, 1), fin.effort_days) == (8.4, 3.0)
    assert (round(hold.potential_ddi_reduction, 1), hold.effort_days) == (11.7, 8.0)
    assert (round(interview.potential_ddi_reduction, 1), interview.effort_days) == (3.4, 3.0)
    # relevance recomputed under the Day-3 rules: holdout targets the success metric, the others do not supply a missing type
    assert (hold.relevance, fin.relevance, interview.relevance) == (1.0, 0.4, 0.4)
    assert hold.priority_rounded == pytest.approx(1.4687, abs=1e-4)
    assert fin.priority_rounded == pytest.approx(0.4 * fin.potential_ddi_reduction / 3, abs=1e-4)
    assert interview.priority_rounded == pytest.approx(0.4476, abs=1e-3)
    # expected reduction equals the DDI engine's difference for a hand-computed fixture (NBE-AC-1)
    assumed = score_components(components_from_scores(
        "product_feature_investment", {**DIMS, "D7": 0.8}, 0.20, 0.30, PARAMS, d6_raw=0.45), PARAMS, AS_OF)
    assert fin.potential_ddi_reduction == pytest.approx(61.0285 - assumed.uncapped_ddi, abs=0.06)
    assert all(x.blockers_resolved == 0 and x.group == "reduce_debt" for x in recs.values())


def test_14b_supplying_a_missing_checklist_type_improves_d2_and_raises_relevance():
    # financial evidence is missing from the checklist: the financial model raises D2 as well as D7
    r = example_result(types_present=frozenset({"behavioral", "customer", "experiment"}),
                       details={"D4": {"best_design": "holdout", "best_power_factor": 0.5}})
    fin = by_id(recommend(r, None, PARAMS, NBE))["financial_model_with_sensitivity"]
    assert fin.relevance == 0.7
    assumed = score_components(components_from_scores(
        "product_feature_investment", {**DIMS, "D7": 0.8, "D2": 1.0}, 0.20, 0.30, PARAMS, d6_raw=0.45), PARAMS, AS_OF)
    assert fin.potential_ddi_reduction == pytest.approx(r.components and 61.0285 - assumed.uncapped_ddi, abs=0.06)
    assert fin.potential_ddi_reduction > 8.4
    assert "supplies a missing checklist evidence type" in fin.why_this


def test_14c_holdout_lifts_the_d6_observational_cap():
    # raw D6 is 0.9 but capped at 0.6 because D4 is low; the holdout lifts the cap
    r = example_result(d6_raw=0.9, details={"D4": {"best_design": "holdout", "best_power_factor": 0.5}})
    r = score_components(components_from_scores(
        "product_feature_investment", {**DIMS, "D6": 0.6}, 0.20, 0.30, PARAMS, d6_raw=0.9,
        types_present=ALL_TYPES, details={"D4": {"best_design": "holdout", "best_power_factor": 0.5}}), PARAMS, AS_OF)
    hold = by_id(recommend(r, None, PARAMS, NBE))["powered_holdout_test"]
    both = score_components(components_from_scores(
        "product_feature_investment", {**DIMS, "D6": 0.9, "D4": 0.8}, 0.20, 0.30, PARAMS), PARAMS, AS_OF)
    only_d4 = score_components(components_from_scores(
        "product_feature_investment", {**DIMS, "D6": 0.6, "D4": 0.8}, 0.20, 0.30, PARAMS), PARAMS, AS_OF)
    assert hold.potential_ddi_reduction == pytest.approx(r.ddi - both.ddi, abs=0.06)
    assert hold.potential_ddi_reduction > r.ddi - only_d4.ddi + 1.0


# ------------------------------------------------------------------ 15. ceilings and non-negative reduction
def test_15_actions_at_or_above_their_ceiling_are_excluded():
    strong = dict(D1=0.9, D2=1.0, D3=0.95, D4=0.85, D5=0.9, D6=0.7, D7=0.85)
    comps = components_from_scores("product_feature_investment", strong, 0.0, 0.0, PARAMS, d6_raw=0.7,
                                   types_present=ALL_TYPES, p2_parts=None,
                                   details={"D4": {"best_design": "rct", "best_power_factor": 0.9}})
    r = score_components(comps, PARAMS, AS_OF)
    assert recommend(r, None, PARAMS, NBE) == []


def test_15_each_action_is_excluded_when_its_own_dimension_is_at_ceiling():
    base = dict(DIMS)
    cases = {"powered_holdout_test": ("D4", 0.8), "segment_level_analysis": ("D6", 0.6), "customer_interview_sprint": ("D5", 0.85),
             "targeted_survey": ("D5", 0.80), "financial_model_with_sensitivity": ("D7", 0.80)}
    for action, (dim, level) in cases.items():
        comps = components_from_scores("product_feature_investment", {**base, dim: level}, 0.2, 0.3, PARAMS, d6_raw=0.45,
                                       types_present=ALL_TYPES)
        r = score_components(comps, PARAMS, AS_OF)
        assert action not in by_id(recommend(r, None, PARAMS, NBE)), action


def test_15_reduction_is_never_negative_property():
    rng = random.Random(3)
    seen = 0
    for _ in range(200):
        f = random_facts(rng)
        r = assess(f, PARAMS, AS_OF)
        if not r.scored:
            continue
        for rec in recommend(r, f, PARAMS, NBE):
            assert rec.potential_ddi_reduction >= 0.0 and rec.priority >= 0.0
            seen += 1
    assert seen > 100


# ------------------------------------------------------------------ 16. ranking
def _rec(action_id, priority, effort, ds=None):
    return Recommendation(action_id, "d", "S", effort, 1.0, 0, 1.0, priority, ("D1",), "w", "reduce_debt", ds)


def test_16_ranking_is_priority_then_effort_then_action_id():
    recs = [_rec("b_action", 1.0, 3.0), _rec("a_action", 1.0, 3.0), _rec("cheap", 1.0, 1.0), _rec("top", 2.0, 8.0),
            _rec("low", 0.5, 1.0)]
    ranked = rank_recommendations(recs)
    assert [r.action_id for r in ranked] == ["top", "cheap", "a_action", "b_action", "low"]
    assert [r.rank for r in ranked] == [1, 2, 3, 4, 5]
    # unrounded priority decides, not the rounded display value
    near = rank_recommendations([_rec("x", 1.00004, 1.0), _rec("y", 1.00001, 1.0)])
    assert near[0].priority_rounded == near[1].priority_rounded == 1.0
    assert [r.action_id for r in near] == ["x", "y"]


def test_16_recommendations_are_stable_across_runs_and_input_order():
    rng = random.Random(9)
    f = random_facts(rng, decision_type="product_feature_investment")
    while assess(f, PARAMS, AS_OF).state != "scored":
        f = random_facts(rng, decision_type="product_feature_investment")
    first = [(r.action_id, r.priority) for r in recommend(assess(f, PARAMS, AS_OF), f, PARAMS, NBE)]
    for _ in range(3):
        g = replace(f, items=tuple(random.Random(rng.random()).sample(f.items, len(f.items))))
        assert [(r.action_id, r.priority) for r in recommend(assess(g, PARAMS, AS_OF), g, PARAMS, NBE)] == first


# ------------------------------------------------------------------ 17. insufficient state
def test_17_onboarding_like_case_ranks_fix_dq_first_with_zero_reduction():
    # Evidence exists and links to the success metric, but an open critical DQ issue blocks scoring.
    items = [item("a", type="behavioral", metric_id=METRIC, ds=METRIC_DS), item("b", type="customer"), item("c", type="behavioral")]
    dq = [DqIssue("q1", METRIC_DS, "critical", "open", affects_metric_id=METRIC)]
    f = facts(items, decision_type="process_or_ux_change", dq=dq)
    r = assess(f, PARAMS, AS_OF)
    assert r.state == "insufficient_evidence" and [x.code for x in r.blocking_reasons] == ["open_critical_dq"]
    recs = recommend(r, f, PARAMS, NBE)
    assert [x.action_id for x in recs] == ["fix_dq_or_instrumentation"]
    top = recs[0]
    assert top.rank == 1 and top.potential_ddi_reduction == 0.0 and top.blockers_resolved == 1
    assert top.relevance == 1.0 and top.group == "unblock_scoring" and top.data_source_id == METRIC_DS
    assert top.priority == pytest.approx(1.0 * 1 / 3.0)


def test_17_blockers_resolved_counts_and_unblocking_actions_come_first():
    # nothing registered: min_items, min_types and success_metric_evidence all block
    f = facts([])
    r = assess(f, PARAMS, AS_OF)
    assert [x.code for x in r.blocking_reasons] == ["min_items", "min_types", "success_metric_evidence"]
    recs = by_id(recommend(r, f, PARAMS, NBE))
    assert recs["powered_holdout_test"].blockers_resolved == 3
    assert recs["extend_observation_or_refresh_data"].blockers_resolved == 3
    assert recs["segment_level_analysis"].blockers_resolved == 1
    assert recs["customer_interview_sprint"].blockers_resolved == 2
    assert recs["financial_model_with_sensitivity"].blockers_resolved == 2
    assert "replicate_independent_source" not in recs and "fix_dq_or_instrumentation" not in recs
    assert all(x.potential_ddi_reduction == 0.0 and x.group == "unblock_scoring" for x in recs.values())
    ranked = recommend(r, f, PARAMS, NBE)
    assert all(x.blockers_resolved >= 1 for x in ranked)
    pr = [x.priority for x in ranked]
    assert pr == sorted(pr, reverse=True)
    # priority = relevance x blockers_resolved / effort_days (never mixed with DDI points)
    h = recs["powered_holdout_test"]
    assert h.priority == pytest.approx(h.relevance * 3 / 8.0)


def test_17_min_types_only_counts_actions_that_supply_a_new_type():
    items = [item(f"b{i}", type="behavioral", metric_id=METRIC) for i in range(3)]
    f = facts(items)
    r = assess(f, PARAMS, AS_OF)
    assert [x.code for x in r.blocking_reasons] == ["min_types"]
    recs = by_id(recommend(r, f, PARAMS, NBE))
    assert "extend_observation_or_refresh_data" not in recs             # behavioral is already present
    assert recs["targeted_survey"].blockers_resolved == 1


# ------------------------------------------------------------------ 18. applicability and per-source DQ actions
def run(scores=None, p1=0.2, p2=0.3, types=ALL_TYPES, p2_parts=None, d6_raw=0.45, hetero=False, details=None, target=True):
    sc = {**DIMS, **(scores or {})}
    comps = components_from_scores("product_feature_investment", sc, p1, p2, PARAMS, d6_raw=d6_raw, types_present=types,
                                   p2_parts=p2_parts, heterogeneity_flag=hetero, success_metric_is_target=target,
                                   details=details or {"D4": {"best_design": "holdout", "best_power_factor": 0.5}})
    return by_id(recommend(score_components(comps, PARAMS, AS_OF), None, PARAMS, NBE))


def test_18_holdout_applicability():
    assert "powered_holdout_test" in run({"D4": 0.79})
    assert "powered_holdout_test" not in run({"D4": 0.8})
    rct = {"D4": {"best_design": "rct", "best_power_factor": 0.8}}
    assert "powered_holdout_test" not in run({"D4": 0.5}, details=rct)             # RCT with power factor >= 0.8
    assert "powered_holdout_test" in run({"D4": 0.5}, details={"D4": {"best_design": "rct", "best_power_factor": 0.5}})
    # D4 not applicable for the decision type
    comps = components_from_scores("policy_or_operations", {d: 0.3 for d in DIMS}, 0.2, 0.3, PARAMS)
    assert "powered_holdout_test" not in by_id(recommend(score_components(comps, PARAMS, AS_OF), None, PARAMS, NBE))


def test_18_segment_analysis_applicability():
    assert "segment_level_analysis" in run({"D6": 0.59})
    assert "segment_level_analysis" not in run({"D6": 0.6})
    # a heterogeneity flag makes it applicable, but at the D6 ceiling the action is excluded (R9: no floor clearing)
    assert "segment_level_analysis" not in run({"D6": 0.7}, hetero=True)


def test_18_customer_actions_applicability():
    r = run({"D5": 0.79})
    assert "customer_interview_sprint" in r and "targeted_survey" in r
    r = run({"D5": 0.84})
    assert "customer_interview_sprint" in r and "targeted_survey" not in r        # survey needs D5 < 0.80
    r = run({"D5": 0.85})
    assert "customer_interview_sprint" not in r and "targeted_survey" not in r


def test_18_extend_observation_and_financial_and_replicate_applicability():
    assert "extend_observation_or_refresh_data" not in run({"D3": 0.5})
    assert "extend_observation_or_refresh_data" in run({"D3": 0.49})
    # P2 CI component above 0.5 makes it applicable even when D3 is fine
    assert "extend_observation_or_refresh_data" in run({"D3": 0.6}, p2_parts=PARTS(ci=0.6))
    assert "extend_observation_or_refresh_data" not in run({"D3": 0.6}, p2_parts=PARTS(ci=0.5))
    assert "financial_model_with_sensitivity" in run({"D7": 0.79}) and "financial_model_with_sensitivity" not in run({"D7": 0.8})
    assert "replicate_independent_source" in run(p2_parts=PARTS(hhi=0.51))
    assert "replicate_independent_source" not in run(p2_parts=PARTS(hhi=0.5))


def PARTS(**kw):  # noqa: N802
    from app.domain.ddi.scoring import P2Parts
    return P2Parts(**kw)


def test_18_one_dq_recommendation_per_affected_data_source():
    items = [item("a", type="behavioral", metric_id=METRIC, ds="ds-a", tier=2), item("b", type="customer", ds="ds-b"),
             item("c", type="financial", ds="ds-b"), item("d", type="experiment", experiment_id="x1", ds="ds-c")]
    dq = [DqIssue("q1", "ds-a", "warn", "open"), DqIssue("q2", "ds-b", "critical", "open"),
          DqIssue("q3", "ds-b", "warn", "open"), DqIssue("q4", "ds-c", "warn", "resolved")]
    f = facts(items, experiments=[good_experiment()], insights=[InsightFact("ins", 10)], dq=dq, metric_ds=METRIC_DS)
    r = assess(f, PARAMS, AS_OF)
    assert r.state == "scored"                    # ds-b is not the success metric's data source
    dq_recs = [x for x in recommend(r, f, PARAMS, NBE) if x.action_id == "fix_dq_or_instrumentation"]
    assert sorted(x.data_source_id for x in dq_recs) == ["ds-a", "ds-b"]       # ds-c is resolved: no recommendation
    assert all(x.potential_ddi_reduction > 0 and x.blockers_resolved == 0 for x in dq_recs)
    # a data source that is not feeding this decision gets no recommendation
    f2 = facts(items, experiments=[good_experiment()], dq=[DqIssue("q9", "ds-zzz", "critical", "open")])
    assert all(x.action_id != "fix_dq_or_instrumentation" for x in recommend(assess(f2, PARAMS, AS_OF), f2, PARAMS, NBE))
    assert METRIC  # keep import used


def test_14d_the_updated_worked_example_table_in_nbe_spec_matches_the_engine():
    recs = {r.action_id: r for r in recommend(example_result(), None, PARAMS, NBE)}
    table = {
        "segment_level_analysis": (1.0, 2.5, 1, 2.52),
        "powered_holdout_test": (1.0, 11.7, 8, 1.47),
        "financial_model_with_sensitivity": (0.4, 8.4, 3, 1.12),
        "targeted_survey": (0.4, 2.5, 1, 1.01),
        "customer_interview_sprint": (0.4, 3.4, 3, 0.45),
    }
    assert set(recs) == set(table)
    for action, (relevance, reduction, effort, priority) in table.items():
        r = recs[action]
        assert (r.relevance, round(r.potential_ddi_reduction, 1), r.effort_days, round(r.priority, 2)) == (
            relevance, reduction, float(effort), priority), action
    assert [r.action_id for r in recommend(example_result(), None, PARAMS, NBE)] == list(table)      # the documented order
