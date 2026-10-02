"""Pure DDI engine tests (brief section 4, tests 1-12 and 33-35). No database."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta

import pytest
from ddi_factories import AS_OF, METRIC, METRIC_DS, PARAMS, facts, good_experiment, item, random_facts, strategy_facts

from app.domain.ddi import (
    Run,
    aggregate,
    assess,
    band_for,
    components_from_scores,
    compute_components,
    round_half_up,
    score_components,
    summarize,
)
from app.domain.ddi.scoring import P2Parts
from app.domain.facts import DqIssue, InsightFact

DIMS = dict(D1=0.55, D2=0.714, D3=0.60, D4=0.10, D5=0.65, D6=0.45, D7=0.30)


def worked_example():
    comps = components_from_scores("product_feature_investment", DIMS, 0.20, 0.30, PARAMS)
    return score_components(comps, PARAMS, AS_OF)


def raw_ddi(f) -> float:
    c = compute_components(f, PARAMS, AS_OF)
    return aggregate(c.scores(), c.applicable, c.p1.score, c.p2.score, PARAMS).capped


# ------------------------------------------------------------------ 1. worked example
def test_01_ddi_spec_worked_example():
    r = worked_example()
    assert (r.ddi, r.band) == (61.0, "high")
    dim_sum = round(sum(d.display_contribution for d in r.dimensions), 1)
    assert dim_sum == 51.9
    assert [p.display_contribution for p in r.penalties] == [5.2, 3.9]
    assert round(dim_sum + 5.2 + 3.9, 1) == r.ddi
    runs = {run.label: run.ddi for run in r.sensitivity.runs}
    assert runs["weight D4 x0.5"] == 57.6
    assert runs["weight D4 x1.5"] == 64.0
    assert runs["penalty coefficients x0.5"] == 56.5
    assert runs["penalty coefficients x1.5"] == 65.6
    assert r.sensitivity.band_stable and r.sensitivity.label == "robust"
    assert (r.sensitivity.min, r.sensitivity.max) == (56.5, 65.6)


# ------------------------------------------------------------------ 2. determinism
def test_02_identical_inputs_give_identical_output_regardless_of_item_order():
    rng = random.Random(7)
    f = random_facts(rng, decision_type="product_feature_investment")
    a = assess(f, PARAMS, AS_OF)
    b = assess(f, PARAMS, AS_OF)
    shuffled = replace(f, items=tuple(reversed(f.items)))
    c = assess(shuffled, PARAMS, AS_OF)
    for other in (b, c):
        assert a.state == other.state
        assert a.dimension_scores_payload() == other.dimension_scores_payload()
        assert a.penalty_scores_payload() == other.penalty_scores_payload()
        assert a.sensitivity_payload() == other.sensitivity_payload()


# ------------------------------------------------------------------ 3 / 4. gating
def _base_items():
    return [item("a", type="behavioral", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")]


def _assert_blocked(r, *codes):
    assert r.state == "insufficient_evidence"
    assert r.ddi is None and r.band is None and r.sensitivity is None and r.uncapped_ddi is None
    assert [x.code for x in r.blocking_reasons] == list(codes)
    p = r.dimension_scores_payload()
    assert p["ddi_display"] is None and p["band"] is None and p["dimensions"] == {}
    assert r.sensitivity_payload() == {} and r.penalty_scores_payload() == {}


def test_03_each_gate_alone_blocks_scoring():
    base = _base_items()
    # min_items only (2 items, 2 types, linked)
    _assert_blocked(assess(facts(base[:2]), PARAMS, AS_OF), "min_items")
    # min_types only (3 items, 1 type, linked)
    one_type = [item(f"t{i}", type="behavioral", metric_id=METRIC) for i in range(3)]
    _assert_blocked(assess(facts(one_type), PARAMS, AS_OF), "min_types")
    # success_metric_evidence only (3 items, 2 types, none linked to the success metric)
    unlinked = [item("u1", type="behavioral", metric_id="other"), item("u2", type="customer"), item("u3", type="financial")]
    _assert_blocked(assess(facts(unlinked), PARAMS, AS_OF), "success_metric_evidence")
    # open_critical_dq only
    dq = [DqIssue("q1", METRIC_DS, "critical", "open")]
    r = assess(facts(base, dq=dq), PARAMS, AS_OF)
    _assert_blocked(r, "open_critical_dq")
    assert r.blocking_reasons[0].detail["dq_check_ids"] == ["q1"]


def test_03_experiment_primary_metric_counts_as_success_metric_evidence():
    items = [item("a", type="experiment", experiment_id="x1"), item("b", type="customer"), item("c", type="financial")]
    r = assess(facts(items, experiments=[good_experiment()]), PARAMS, AS_OF)
    assert r.state == "scored"


def test_03_accepted_and_resolved_dq_do_not_block_accepted_is_a_warning():
    for status in ("accepted", "resolved"):
        dq = [DqIssue("q1", METRIC_DS, "critical", status)]
        r = assess(facts(_base_items(), dq=dq), PARAMS, AS_OF)
        assert r.state == "scored", status
        codes = [w["code"] for w in r.warnings]
        assert codes == (["accepted_critical_dq"] if status == "accepted" else [])
    # an open WARN does not block either
    r = assess(facts(_base_items(), dq=[DqIssue("q1", METRIC_DS, "warn", "open")]), PARAMS, AS_OF)
    assert r.state == "scored"


def test_04_all_four_gates_together_in_fixed_order():
    dq = [DqIssue("q1", METRIC_DS, "critical", "open")]
    r = assess(facts([item("a", type="behavioral", metric_id="other")], dq=dq), PARAMS, AS_OF)
    _assert_blocked(r, "min_items", "min_types", "success_metric_evidence", "open_critical_dq")


# ------------------------------------------------------------------ 5. bands and rounding
@pytest.mark.parametrize("raw,display,band", [
    (0.0, 0.0, "low"), (24.9, 24.9, "low"), (24.96, 25.0, "moderate"), (25.0, 25.0, "moderate"),
    (49.95, 50.0, "high"), (74.96, 75.0, "critical"), (75.0, 75.0, "critical"),
    (99.99, 100.0, "critical"), (100.0, 100.0, "critical"),
])
def test_05_round_first_then_band(raw, display, band):
    d = round_half_up(raw, 1)
    assert d == display
    assert band_for(d, PARAMS) == band


def test_05_exactly_100_is_critical_through_the_engine():
    comps = components_from_scores("product_feature_investment", {d: 0.0 for d in DIMS}, 0.0, 0.0, PARAMS)
    r = score_components(comps, PARAMS, AS_OF)
    assert (r.ddi, r.band, r.cap_applied) == (100.0, "critical", False)


# ------------------------------------------------------------------ 6. S = 1 and S = 0
def test_06_support_one_gives_zero_for_any_penalty():
    comps = components_from_scores("product_feature_investment", {d: 1.0 for d in DIMS}, 1.0, 1.0, PARAMS)
    r = score_components(comps, PARAMS, AS_OF)
    assert r.ddi == 0.0 and r.band == "low" and r.cap_applied is False
    assert all(d.display_contribution == 0.0 for d in r.dimensions) and all(p.display_contribution == 0.0 for p in r.penalties)


def test_06_support_zero_is_capped_at_100_with_reconciled_contributions():
    comps = components_from_scores("product_feature_investment", {d: 0.0 for d in DIMS}, 0.5, 0.5, PARAMS)
    r = score_components(comps, PARAMS, AS_OF)
    assert r.ddi == 100.0 and r.band == "critical"
    assert r.cap_applied is True and r.uncapped_ddi == 137.5
    total = sum(d.display_contribution for d in r.dimensions) + sum(p.display_contribution for p in r.penalties)
    assert round(total, 1) == 100.0
    # raw contributions are scaled by 100 / uncapped
    raw_total = sum(d.raw_contribution for d in r.dimensions) + sum(p.raw_contribution for p in r.penalties)
    assert raw_total == pytest.approx(100.0)


# ------------------------------------------------------------------ 7. contributions sum to the displayed DDI
def _check_sum(r):
    total = round(sum(d.display_contribution for d in r.dimensions) + sum(p.display_contribution for p in r.penalties), 1)
    assert total == r.ddi, (total, r.ddi)
    assert all(abs(x * 10 - round(x * 10)) < 1e-9 for x in
               [d.display_contribution for d in r.dimensions] + [p.display_contribution for p in r.penalties])


def test_07_contributions_equal_displayed_ddi_property_scores():
    rng = random.Random(11)
    capped = uncapped = 0
    for _ in range(400):
        dtype = rng.choice(["product_feature_investment", "process_or_ux_change", "strategy_or_market_entry"])
        scores = {d: rng.choice([0.0, rng.random(), rng.random() * 0.3, 1.0]) for d in DIMS}
        comps = components_from_scores(dtype, scores, rng.random(), rng.random(), PARAMS)
        r = score_components(comps, PARAMS, AS_OF)
        _check_sum(r)
        capped += r.cap_applied
        uncapped += not r.cap_applied
    assert capped > 20 and uncapped > 20            # both regimes were exercised


def test_07_contributions_equal_displayed_ddi_property_facts():
    rng = random.Random(5)
    for _ in range(150):
        r = assess(random_facts(rng), PARAMS, AS_OF)
        if r.scored:
            _check_sum(r)


# ------------------------------------------------------------------ 8. applicability and renormalization
def test_08_not_applicable_dimensions_are_excluded_and_weights_renormalized():
    r = assess(facts([item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")],
                     decision_type="process_or_ux_change"), PARAMS, AS_OF)
    d7 = next(d for d in r.dimensions if d.id == "D7")
    assert d7.applicable is False and d7.score is None and d7.weight == 0.0
    assert d7.to_dict()["status"] == "Not applicable"
    weights = [d.weight for d in r.dimensions if d.applicable]
    assert len(weights) == 6 and all(w == pytest.approx(1 / 6) for w in weights)
    assert sum(weights) == pytest.approx(1.0)
    assert r.sensitivity.count == 2 * 6 + 6
    # policy_or_operations: D4 not applicable
    r2 = assess(facts([item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")],
                      decision_type="policy_or_operations"), PARAMS, AS_OF)
    assert [d.id for d in r2.dimensions if not d.applicable] == ["D4"]


# ------------------------------------------------------------------ 9. monotonicity (improving an existing attribute)
def _improve(it, attr, rng):
    if attr == "tier":
        return replace(it, reliability_tier=max(1, it.reliability_tier - 1)) if it.reliability_tier > 1 else None
    if attr == "grade":
        order = "ABCD"
        return replace(it, strength_grade=order[order.index(it.strength_grade) - 1]) if it.strength_grade != "A" else None
    if attr == "dq":
        better = {"critical": "warn", "warn": "pass"}
        return replace(it, dq_status=better[it.dq_status]) if it.dq_status in better else None
    if attr == "recency":
        return replace(it, observed_end=min(AS_OF, it.observed_end + timedelta(days=rng.randint(1, 200)))) \
            if it.observed_end < AS_OF else None
    if attr == "n":
        return replace(it, n_sample=max(it.n_sample * 3, it.n_sample + 1)) if it.n_sample is not None else None
    raise AssertionError(attr)


def test_09_improving_an_attribute_of_an_existing_item_never_increases_ddi():
    """Holds for supporting and neutral items (all attributes) and for every item's n_sample.

    For a CONTRADICTING item, a higher tier/grade/recency/DQ raises its weight and therefore P1 by design
    (stronger contradicting evidence is more contradiction), so reliability attributes are not monotone for
    those items. See test_09b and docs/day-3-implementation-notes.md.
    """
    rng = random.Random(21)
    checked = 0
    for _ in range(250):
        f = random_facts(rng)
        if assess(f, PARAMS, AS_OF).state != "scored":
            continue
        base = raw_ddi(f)
        for idx, it in enumerate(f.items):
            for attr in ("tier", "grade", "dq", "recency", "n"):
                if it.stance == "contradicts" and attr != "n":
                    continue
                better = _improve(it, attr, rng)
                if better is None:
                    continue
                items = list(f.items)
                items[idx] = better
                new = raw_ddi(replace(f, items=tuple(items)))
                assert new <= base + 1e-9, (attr, it, base, new)
                checked += 1
    assert checked > 500


def test_09b_improving_a_contradicting_items_reliability_can_raise_ddi_by_design():
    items = [item("s1", type="behavioral", metric_id=METRIC, source="a"), item("s2", type="customer", source="b"),
             item("s3", type="market", source="c"),
             item("c1", type="anecdotal", stance="contradicts", tier=4, grade="D", source="d")]
    weak = facts(items, decision_type="strategy_or_market_entry")
    strong = replace(weak, items=(*items[:3], replace(items[3], reliability_tier=1, strength_grade="A")))
    assert raw_ddi(strong) > raw_ddi(weak)           # evidence-debt model: reliable contradiction is more contradiction


# ------------------------------------------------------------------ 10. P1
def test_10_p1_zero_without_contradiction_and_one_when_all_non_neutral_contradicts():
    sup = facts([item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")])
    assert compute_components(sup, PARAMS, AS_OF).p1.score == 0.0
    con = facts([item("a", stance="contradicts", metric_id=METRIC), item("b", type="customer", stance="contradicts"),
                 item("c", type="financial", stance="neutral")])
    assert compute_components(con, PARAMS, AS_OF).p1.score == 1.0          # neutral items do not dilute contradiction


def test_10_p1_is_zero_with_only_neutral_items_and_floor_needs_the_heterogeneity_flag():
    neutral = [item("a", stance="neutral", metric_id=METRIC), item("b", type="customer", stance="neutral"),
               item("c", type="financial", stance="neutral")]
    assert compute_components(facts(neutral), PARAMS, AS_OF).p1.score == 0.0
    sup = [item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")]
    for flag, expected in ((None, 0.0), (False, 0.0), (True, PARAMS.segment_divergence_floor_p1)):
        c = compute_components(facts(sup, hetero=flag), PARAMS, AS_OF)
        assert c.p1.score == expected
    assert compute_components(facts(sup, hetero=None), PARAMS, AS_OF).p1.defaulted_inputs      # unknown is flagged as defaulted


# ------------------------------------------------------------------ 11. P2
def test_11_p2_edge_cases_stay_in_unit_interval():
    # effect = 0 uses the documented component value, missing CI means the component is unavailable
    zero_effect = item("a", metric_id=METRIC, effect_size=0.0, ci_low=-0.1, ci_high=0.1, n_sample=500)
    no_ci = item("b", type="customer", n_sample=500)
    other = item("c", type="financial", n_sample=500)
    c = compute_components(facts([zero_effect, no_ci, other]), PARAMS, AS_OF)
    assert c.p2_parts.ci == PARAMS.ci_component_when_effect_zero
    assert 0.0 <= c.p2.score <= 1.0
    c2 = compute_components(facts([no_ci, other, replace(item("d", metric_id=METRIC))]), PARAMS, AS_OF)
    assert c2.p2_parts.ci is None and 0.0 <= c2.p2.score <= 1.0
    assert "ci_width" not in c2.p2.details["available_components"]
    # a single item (and a single source) stays in [0, 1]
    single = compute_components(facts([item("z", metric_id=METRIC)]), PARAMS, AS_OF)
    assert single.p2_parts.hhi == 1.0 and 0.0 <= single.p2.score <= 1.0


def test_11_normalized_hhi_is_zero_when_spread_evenly_and_one_for_a_single_source():
    spread = [item(f"i{k}", source=f"s{k % 3}", metric_id=METRIC) for k in range(6)]     # 3 sources x 2 items
    assert compute_components(facts(spread), PARAMS, AS_OF).p2_parts.hhi == pytest.approx(0.0)
    one = [item(f"i{k}", source="only", metric_id=METRIC) for k in range(4)]
    assert compute_components(facts(one), PARAMS, AS_OF).p2_parts.hhi == 1.0
    skewed = [item(f"i{k}", source="a" if k < 5 else "b", metric_id=METRIC) for k in range(6)]
    assert 0.0 < compute_components(facts(skewed), PARAMS, AS_OF).p2_parts.hhi < 1.0


# ------------------------------------------------------------------ 12. sensitivity
@pytest.mark.parametrize("dtype,k", [("product_feature_investment", 7), ("process_or_ux_change", 6),
                                     ("strategy_or_market_entry", 5)])
def test_12_sensitivity_count_is_2k_plus_6_and_range_contains_base(dtype, k):
    rng = random.Random(k)
    scores = {d: rng.random() for d in DIMS}
    r = score_components(components_from_scores(dtype, scores, 0.3, 0.2, PARAMS), PARAMS, AS_OF)
    s = r.sensitivity
    assert s.count == 2 * k + 6 == len(s.runs)
    assert s.min <= r.ddi <= s.max
    stored = r.sensitivity_payload()
    assert isinstance(stored["band_stable"], bool) and stored["count"] == 2 * k + 6
    assert stored["label"] in ("robust", "sensitive") and stored["range"] == [s.min, s.max]


@pytest.mark.parametrize("unchanged,total,stable", [(9, 10, True), (8, 10, False), (18, 20, True), (17, 20, False),
                                                    (20, 20, True)])
def test_12_robust_threshold_is_inclusive_at_exactly_90_percent(unchanged, total, stable):
    runs = [Run(f"r{i}", 50.0, "high" if i < unchanged else "moderate") for i in range(total)]
    s = summarize(55.0, "high", runs, PARAMS.robust_share)
    assert s.band_stable is stable
    assert s.label == ("robust" if stable else "sensitive")
    assert s.unchanged_band_share == pytest.approx(unchanged / total)


# ------------------------------------------------------------------ dimension details
def test_dimension_defaults_are_flagged_and_explained():
    items = [item("a", metric_id=METRIC, n_sample=2000, effect_size=0.03), item("b", type="customer", insight_id="ins1"),
             item("c", type="financial", tier=2, effect_size=1.0), item("d", type="experiment", experiment_id="x1")]
    f = facts(items, experiments=[good_experiment()], insights=[InsightFact("ins1", 100)])
    c = compute_components(f, PARAMS, AS_OF)
    assert [i.name for i in c.dims["D4"].defaulted_inputs] == ["power_factor"]
    assert [i.name for i in c.dims["D5"].defaulted_inputs] == ["segment_coverage", "relevance"]
    assert c.dims["D5"].score == pytest.approx(0.5 * 1.0 + 0.3 * 0.5 + 0.2 * 0.5)
    assert c.dims["D7"].score == pytest.approx(0.5 + 0.3)
    assert c.dims["D6"].score == pytest.approx(0.6)                  # observational cap
    assert [i.name for i in c.p1.defaulted_inputs] == ["heterogeneity_flag"]       # heterogeneity unknown


def test_d6_cap_lifted_when_d4_is_high():
    exp = replace(good_experiment(), achieved_power=0.9)
    items = [item("a", metric_id=METRIC, n_sample=5000, effect_size=0.05), item("x", type="experiment", experiment_id="x1")]
    f = facts(items + [item("f", type="financial")], experiments=[exp])
    c = compute_components(f, PARAMS, AS_OF)
    assert c.dims["D4"].score >= 0.6
    assert c.dims["D6"].score == pytest.approx(1.0)


# ------------------------------------------------------------------ 33-35 evidence direction is not DDI
def test_33_strong_supporting_evidence_gives_low_ddi_and_supporting():
    r = assess(strategy_facts("supports"), PARAMS, AS_OF)
    assert r.state == "scored" and r.band == "low"
    assert r.direction.label == "supporting"
    assert r.dimension_scores_payload()["evidence_direction"]["label"] == "supporting"


def test_34_strong_contradicting_evidence_gives_low_ddi_and_contradicting_same_band():
    sup = assess(strategy_facts("supports"), PARAMS, AS_OF)
    con = assess(strategy_facts("contradicts"), PARAMS, AS_OF)
    assert con.state == "scored" and con.band == "low" == sup.band
    assert con.direction.label == "contradicting"
    # DDI measures evidence debt, not correctness: the contradiction only adds the P1 penalty
    assert con.ddi >= sup.ddi


def test_35_weak_or_incomplete_evidence_is_high_debt_or_insufficient_and_uncertain():
    old = date(2023, 1, 1)
    weak = [item(f"w{k}", type=t, stance="supports", grade="D", tier=4, end=old, metric_id=METRIC if k == 0 else None)
            for k, t in enumerate(["behavioral", "customer", "behavioral", "customer"])]
    r = assess(facts(weak), PARAMS, AS_OF)
    assert r.state == "scored" and r.band in ("high", "critical")
    assert r.direction.label == "supporting"       # direction is not DDI: weak but one-sided evidence still points one way
    # ... unless the direction-bearing evidence is too thin to classify (neutral items do not bear a direction)
    thin_dir = [item("t0", type="behavioral", grade="D", tier=4, end=old, metric_id=METRIC)] + [
        item(f"t{k}", type=t, stance="neutral", grade="D", tier=4, end=old) for k, t in enumerate(["customer", "behavioral", "customer"], 1)]
    r = assess(facts(thin_dir), PARAMS, AS_OF)
    assert r.state == "scored" and r.band in ("high", "critical")
    assert r.direction.label == "uncertain" and r.direction.direction_bearing_items == 1
    thin = assess(facts(weak[:2]), PARAMS, AS_OF)
    assert thin.state == "insufficient_evidence" and thin.direction.label == "uncertain" and thin.ddi is None


def test_direction_mixed():
    items = [item("a", metric_id=METRIC), item("b", type="customer", stance="contradicts"),
             item("c", type="financial", stance="supports", tier=4)]
    r = assess(facts(items), PARAMS, AS_OF)
    assert r.direction.label == "mixed"
    assert r.direction.supporting_share + r.direction.contradicting_share == pytest.approx(1.0)
    assert r.direction.neutral_share == 0.0 and r.direction.direction_basis_weight == pytest.approx(1.0)


def test_stored_payload_carries_versions_hash_and_as_of():
    r = assess(strategy_facts(), PARAMS, AS_OF)
    p = r.dimension_scores_payload()
    assert p["params_version"] == PARAMS.version and p["params_hash"] == PARAMS.content_hash
    assert p["as_of_date"] == AS_OF.isoformat() and p["ddi_display"] == r.ddi
    assert p["cap_applied"] is False and p["band"] == "low"
    assert p["what_drove_this_result"]
    assert set(p["dimensions"]) == {f"D{i}" for i in range(1, 8)}
    assert InsightFact  # keep import used
