"""PO clarification tests 36-39 (evidence direction, P1 quality adjustment, defaulted inputs) and NBE naming."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from ddi_factories import AS_OF, METRIC, METRIC_DS, NBE, PARAMS, facts, good_experiment, item, strategy_facts

from app.domain.ddi import assess, compute_components, evidence_direction
from app.domain.facts import DqIssue, InsightFact
from app.domain.nbe import recommend
from app.repositories.recommendations import to_row


def direction(items, insufficient=False, **kw):
    return evidence_direction(facts(items, **kw), PARAMS, AS_OF, insufficient=insufficient)


def supports(n_a=0, n_c=0, n_d=0, stance="supports", prefix="s"):
    """Fresh tier-1 behavioral items with weights 1.0 (A), 0.5 (C) and 0.25 (D)."""
    out = [item(f"{prefix}A{k}", stance=stance, grade="A") for k in range(n_a)]
    out += [item(f"{prefix}C{k}", stance=stance, grade="C") for k in range(n_c)]
    out += [item(f"{prefix}D{k}", stance=stance, grade="D") for k in range(n_d)]
    return out


# ------------------------------------------------------------------ 36. thresholds and output contract
@pytest.mark.parametrize("sup,con,label,share", [
    (dict(n_a=4), dict(n_a=1), "supporting", 0.8),               # 80/20
    (dict(n_a=1), dict(n_a=4), "contradicting", 0.2),            # 20/80
    (dict(n_a=1, n_c=1), dict(n_a=1), "supporting", 0.6),        # 60/40, exactly the threshold
    (dict(n_a=1), dict(n_a=1, n_c=1), "contradicting", 0.4),     # 40/60, exactly the threshold
    (dict(n_a=1, n_d=1), dict(n_a=1), "mixed", 1.25 / 2.25),     # about 55/45: neither side reaches 0.6
])
def test_36_direction_thresholds(sup, con, label, share):
    d = direction(supports(**sup) + supports(**con, stance="contradicts", prefix="c"))
    assert d.label == label
    assert d.supporting_share == pytest.approx(share)
    assert d.contradicting_share == pytest.approx(1 - share)
    assert d.supporting_share + d.contradicting_share == pytest.approx(1.0)


def test_36_fewer_than_two_direction_bearing_items_is_uncertain():
    assert direction(supports(n_a=1)).label == "uncertain"
    assert direction(supports(n_a=1) + [item("n1", stance="neutral"), item("n2", stance="neutral")]).label == "uncertain"
    # an item with weight 0 (critical data-quality issue) does not bear a direction
    dq = [DqIssue("q", "ds-x", "critical", "open")]
    zero_weight = [item("a", ds="ds-x", grade="A"), item("b", ds="ds-x", grade="A")]
    d = direction(zero_weight + supports(n_a=1, prefix="ok"), dq=dq)
    assert d.label == "uncertain" and d.direction_bearing_items == 1
    assert direction(supports(n_a=2)).label == "supporting"                         # two are enough
    only_zero = direction(zero_weight, dq=dq)
    assert only_zero.label == "uncertain" and only_zero.direction_basis_weight == 0.0 and only_zero.supporting_share == 0.0


def test_36_a_gated_assessment_is_uncertain_and_the_output_contract_is_complete():
    r = assess(facts(supports(n_a=1)), PARAMS, AS_OF)
    assert r.state == "insufficient_evidence" and r.direction.label == "uncertain"
    d = direction(supports(n_a=1) + supports(n_a=1, stance="contradicts", prefix="c") + supports(n_c=1, stance="neutral", prefix="n"))
    out = d.to_dict()
    for key in ("label", "supporting_share", "contradicting_share", "neutral_share", "direction_basis_weight", "threshold",
                "direction_bearing_items"):
        assert key in out, key
    assert out["threshold"] == 0.6 and out["direction_bearing_items"] == 2
    assert out["supporting_share"] == 0.5 and out["contradicting_share"] == 0.5
    assert out["neutral_share"] == pytest.approx(0.5 / 2.5) and out["direction_basis_weight"] == pytest.approx(2.0 / 2.5)
    stored = assess(strategy_facts(), PARAMS, AS_OF).dimension_scores_payload()["evidence_direction"]
    assert stored["label"] == "supporting" and set(out) <= set(stored) | {"explanation"}


# ------------------------------------------------------------------ 37. direction never modifies the DDI
def test_37_flipping_every_stance_moves_only_p1_and_direction():
    """Decision type strategy_or_market_entry has no stance-dependent dimension (D6 is not applicable)."""
    a, b = strategy_facts("supports"), strategy_facts("contradicts")
    ca, cb = compute_components(a, PARAMS, AS_OF), compute_components(b, PARAMS, AS_OF)
    assert ca.applicable == cb.applicable == ("D1", "D2", "D3", "D5", "D7")
    for dim in ca.applicable:
        assert ca.score(dim) == cb.score(dim), dim
    assert ca.p2.score == cb.p2.score
    assert (ca.p1.score, cb.p1.score) == (0.0, 1.0)
    ra, rb = assess(a, PARAMS, AS_OF), assess(b, PARAMS, AS_OF)
    assert (ra.direction.label, rb.direction.label) == ("supporting", "contradicting")
    # the DDI differs only through the P1 penalty (higher P1 => higher DDI), never through the direction itself
    assert [d.score for d in ra.dimensions] == [d.score for d in rb.dimensions]
    assert rb.ddi >= ra.ddi


def test_37_changing_the_direction_parameters_leaves_the_ddi_untouched():
    f = strategy_facts("contradicts")
    base = assess(f, PARAMS, AS_OF)
    strict = replace(PARAMS, direction_majority_share=0.99, direction_min_bearing_items=50)
    other = assess(f, strict, AS_OF)
    assert base.direction.label == "contradicting" and other.direction.label == "uncertain"
    assert (base.ddi, base.band, base.uncapped_ddi) == (other.ddi, other.band, other.uncapped_ddi)
    assert base.penalty_scores_payload() == other.penalty_scores_payload()
    assert base.sensitivity_payload() == other.sensitivity_payload()
    assert [d.to_dict() for d in base.dimensions] == [d.to_dict() for d in other.dimensions]


def _d6_facts(stance, **beh):
    """product_feature_investment (D6 applies): one behavioral item on the success metric plus other evidence; every\n    item carries the given stance, so flipping it flips all the evidence (the same evidence, opposite direction)."""
    return facts([item("a", stance=stance, metric_id=METRIC, **beh), item("b", type="customer", stance=stance), item("c", type="financial", stance=stance)])


def test_d6_same_behavioral_evidence_has_identical_d6_whatever_the_stance():
    scores = {st: compute_components(_d6_facts(st, n_sample=2000, effect_size=0.03), PARAMS, AS_OF)
              for st in ("supports", "contradicts", "neutral")}
    assert len({c.score("D6") for c in scores.values()}) == 1 and scores["supports"].score("D6") > 0
    # a contradicting item with a NEGATIVE effect of the same magnitude is just as strong
    neg = compute_components(_d6_facts("contradicts", n_sample=2000, effect_size=-0.03), PARAMS, AS_OF)
    assert neg.score("D6") == scores["supports"].score("D6")


def test_d6_stance_flip_may_change_p1_and_direction_but_no_dimension_or_p2():
    sup = _d6_facts("supports", n_sample=2000, effect_size=0.03)
    con = _d6_facts("contradicts", n_sample=2000, effect_size=0.03)
    ca, cb = compute_components(sup, PARAMS, AS_OF), compute_components(con, PARAMS, AS_OF)
    for dim in ca.applicable:
        assert ca.score(dim) == cb.score(dim), dim
    assert ca.p2.score == cb.p2.score and ca.p1.score != cb.p1.score
    assert assess(sup, PARAMS, AS_OF).direction.label != assess(con, PARAMS, AS_OF).direction.label


def test_d6_ddi_difference_from_a_stance_flip_is_attributable_to_p1_only():
    sup = assess(_d6_facts("supports", n_sample=2000, effect_size=0.03), PARAMS, AS_OF)
    con = assess(_d6_facts("contradicts", n_sample=2000, effect_size=0.03), PARAMS, AS_OF)
    assert [d.score for d in sup.dimensions] == [d.score for d in con.dimensions]
    p1a, p1b = sup.components.p1.score, con.components.p1.score
    p2 = sup.components.p2.score
    penalty = lambda p1: 1 + PARAMS.contradiction_coefficient * p1 + PARAMS.uncertainty_coefficient * p2  # noqa: E731
    assert con.uncapped_ddi == pytest.approx(sup.uncapped_ddi * penalty(p1b) / penalty(p1a), abs=0.15)   # uncapped_ddi is rounded to 1 dp
    assert con.uncapped_ddi > sup.uncapped_ddi


def test_d6_existing_edge_cases_still_behave():
    none = compute_components(facts([item("a", type="customer"), item("b", type="financial"), item("c", type="market")]), PARAMS, AS_OF)
    assert none.score("D6") == 0.0                                           # no behavioral evidence on the success metric
    other_metric = compute_components(facts([item("a", metric_id="other", n_sample=2000, effect_size=0.03), item("b", type="customer"),
                                             item("c", type="financial")]), PARAMS, AS_OF)
    assert other_metric.score("D6") == 0.0                                   # evidence on another metric does not count
    unknown = compute_components(_d6_facts("supports"), PARAMS, AS_OF)       # no n_sample, no effect: defaulted, not observed
    assert unknown.score("D6") == 0.0 and unknown.dims["D6"].defaulted_inputs
    capped = compute_components(_d6_facts("supports", n_sample=2000, effect_size=0.03), PARAMS, AS_OF)
    assert capped.score("D6") == PARAMS.observational_cap                    # observational cap
    from app.domain.ddi.scoring import d6_from_raw
    assert d6_from_raw(1.0, 0.7, PARAMS) == (1.0, None)                        # cap lifted once D4 is high enough
    assert d6_from_raw(1.0, 0.5, PARAMS) == (PARAMS.observational_cap, PARAMS.observational_cap)
    assert compute_components(_d6_facts("supports", n_sample=2000, effect_size=0.01), PARAMS, AS_OF).score("D6") == pytest.approx(0.5)

# ------------------------------------------------------------------ 38. P1 golden tests
def test_38_a_contradicting_item_with_an_open_critical_dq_issue_adds_less_contradiction_weight():
    items = [item("s1", metric_id=METRIC, ds="ds-ok"), item("s2", type="customer", ds="ds-ok"),
             item("c1", type="financial", stance="contradicts", ds="ds-x")]
    clean = compute_components(facts(items), PARAMS, AS_OF)
    warn = compute_components(facts(items, dq=[DqIssue("q", "ds-x", "warn", "open")]), PARAMS, AS_OF)
    crit = compute_components(facts(items, dq=[DqIssue("q", "ds-x", "critical", "open")]), PARAMS, AS_OF)
    cw = [c.p1.details["contradicting_weight"] for c in (clean, warn, crit)]
    assert cw[0] == 1.0 and cw[1] == pytest.approx(0.7) and cw[2] == 0.0
    assert crit.p1.score < warn.p1.score < clean.p1.score
    assert crit.p1.details["direction_bearing_weight"] < clean.p1.details["direction_bearing_weight"]
    # the critical item still counts as evidence for the gate (its dq_factor is 0 in D1) and does not block scoring
    r = assess(facts(items, dq=[DqIssue("q", "ds-x", "critical", "open")]), PARAMS, AS_OF)
    assert r.state == "scored" and "adjusted for evidence quality" in r.penalties[0].explanation


def test_38_neutral_items_do_not_dilute_p1():
    base = [item("s1", metric_id=METRIC), item("c1", type="customer", stance="contradicts"), item("s2", type="financial")]
    with_neutral = base + [item(f"n{k}", stance="neutral") for k in range(5)]
    assert compute_components(facts(base), PARAMS, AS_OF).p1.score == compute_components(facts(with_neutral), PARAMS, AS_OF).p1.score == pytest.approx(1 / 3)


# ------------------------------------------------------------------ 39. defaulted inputs are never presented as observed
def all_entries(result):
    payload = result.dimension_scores_payload()["dimensions"]
    pens = result.penalty_scores_payload()["penalties"]
    return {**payload, **pens}


def test_39_defaulted_inputs_carry_source_default_and_a_reason():
    items = [item("a", metric_id=METRIC, n_sample=2000, effect_size=0.03, ci_low=0.02, ci_high=0.04),
             item("b", type="customer", insight_id="ins1"), item("c", type="experiment", experiment_id="x1"),
             item("d", type="financial", tier=2, effect_size=1.0, ci_low=0.5, ci_high=1.5)]
    r = assess(facts(items, experiments=[replace(good_experiment(), srm_flag=None, mde=None)],
                     insights=[InsightFact("ins1", 100)]), PARAMS, AS_OF)
    entries = all_entries(r)
    seen_defaults = []
    for key, entry in entries.items():
        if not entry.get("applicable", True):
            continue
        for d in entry["defaulted_inputs"]:
            assert d["source"] == "default" and d["default_reason"] and "value" in d, (key, d)
            seen_defaults.append((key, d["name"]))
        defaulted_names = {d["name"] for d in entry["defaulted_inputs"]}
        for i in entry["inputs"]:
            if i["source"] == "observed":
                assert i["default_reason"] is None and i["name"] not in defaulted_names, (key, i)
            else:
                assert i["source"] == "default" and i["default_reason"]
    assert {("D4", "power_factor"), ("D4", "integrity_factor"), ("D4", "informativeness_factor"), ("D5", "segment_coverage"),
            ("D5", "relevance"), ("P1", "heterogeneity_flag")} <= set(seen_defaults)
    d5 = entries["D5"]
    assert next(i for i in d5["defaulted_inputs"] if i["name"] == "relevance")["value"] == 0.5
    assert "no explicit customer relevance value was supplied" in next(
        i for i in d5["defaulted_inputs"] if i["name"] == "relevance")["default_reason"]


def test_39_observed_values_are_reported_as_observed_not_defaulted():
    items = [item("a", metric_id=METRIC, n_sample=2000, effect_size=0.03), item("b", type="customer"),
             item("c", type="experiment", experiment_id="x1")]
    exp = replace(good_experiment(), achieved_power=0.9, srm_flag=False)
    r = assess(facts(items, experiments=[exp], hetero=False), PARAMS, AS_OF)
    d4 = all_entries(r)["D4"]
    assert d4["defaulted_inputs"] == [] and {i["source"] for i in d4["inputs"]} == {"observed"}
    p1 = all_entries(r)["P1"]
    assert p1["defaulted_inputs"] == [] and p1["inputs"][0]["source"] == "observed"
    # D6 items without n_sample / effect size are defaulted (scored 0) and say so
    thin = assess(facts([item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")]), PARAMS, AS_OF)
    names = {d["name"].split("[")[0] for d in all_entries(thin)["D6"]["defaulted_inputs"]}
    assert names == {"adequacy", "materiality"}
    assert METRIC_DS  # keep import used


# ------------------------------------------------------------------ NBE naming (PO rule 3.4c)
def test_nbe_uses_explicit_names_and_the_repository_maps_the_column():
    src = (Path(__file__).resolve().parents[2] / "backend" / "app" / "domain" / "nbe" / "engine.py").read_text(encoding="utf-8")
    assert "priority = relevance * potential_ddi_reduction / effort_days" in src
    assert not re.search(r"\b(V|R|E)\(a\)", src) and "expected_reduction =" not in src
    items = [item("a", metric_id=METRIC), item("b", type="customer"), item("c", type="financial")]
    f = facts(items)
    recs = recommend(assess(f, PARAMS, AS_OF), f, PARAMS, NBE)
    assert recs and all(hasattr(r, "potential_ddi_reduction") and not hasattr(r, "expected_reduction") for r in recs)
    row = to_row(recs[0])
    assert row["expected_reduction"] == round(recs[0].potential_ddi_reduction, 4)
    assert row["priority_score"] == recs[0].priority_rounded and "potential_ddi_reduction" not in row
