"""Day 4.1, Remediation 2: descriptive evidence (trend, funnel; no effect size) must not dilute D6.

Option (a), implemented outside the frozen DDI engine (B2): descriptive evidence is materialised with metric_id = NULL, so the
unchanged D6 selection (behavioral evidence whose metric_id is the success metric) excludes it. The first group of tests runs
the unchanged DDI engine on fact sets shaped like the materialised rows (pure, no database); the second group runs the real
pipeline on the seeded scenarios."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest
from ddi_factories import AS_OF, METRIC, PARAMS, facts, item

from app.domain.ddi.scoring import compute_components, evaluate_gate


def quantified(i: str, *, stance="supports", n=2000, effect=0.05):
    return item(i, type="behavioral", metric_id=METRIC, stance=stance, n_sample=n, effect_size=effect, ci_low=effect - 0.01,
                ci_high=effect + 0.01)


def descriptive(i: str):
    """What a trend or a funnel becomes after Day 4.1: behavioral, neutral, no effect size, no metric link."""
    return item(i, type="behavioral", metric_id=None, stance="neutral", n_sample=5000, effect_size=None)


def d6(*items):
    comps = compute_components(facts(list(items)), PARAMS, AS_OF)
    return comps.dims["D6"].score, comps.d6_raw, comps.dims["D6"].details.get("items", 0)


BASE = [quantified("q1"), quantified("q2", effect=0.01, n=500), item("c1", type="customer"), item("f1", type="financial")]


# ---------------------------------------------------------------- 1, 2. a descriptive item contributes nothing
@pytest.mark.parametrize("kind", ["trend", "funnel"])
def test_a_descriptive_item_with_no_effect_does_not_contribute_to_d6(kind):
    alone = d6(*BASE)
    with_item = d6(*BASE, descriptive(kind))
    assert with_item == alone and with_item[2] == 2                       # same score, same raw value, same item count
    # on its own it is "no behavioral evidence on the success metric", not a diluted mean
    only = compute_components(facts([descriptive(kind), item("c1", type="customer"), item("f1", type="financial")]), PARAMS, AS_OF)
    assert only.dims["D6"].score == 0.0 and only.d6_raw == 0.0 and only.dims["D6"].explanation.startswith("No behavioral evidence")
    assert only.dims["D6"].inputs == ()


# ---------------------------------------------------------------- 3. removing a descriptive item changes nothing
def test_removing_a_descriptive_item_does_not_change_d6():
    both = [*BASE, descriptive("trend"), descriptive("funnel")]
    assert d6(*both) == d6(*BASE) == d6(*BASE, descriptive("trend")) == d6(*BASE, descriptive("funnel"))
    # D6 inside a full assessment too (other dimensions, such as freshness, legitimately still see every active item)
    from app.domain.ddi import assess
    with_items, without = assess(facts(both), PARAMS, AS_OF), assess(facts(BASE), PARAMS, AS_OF)
    assert with_items.state == without.state == "scored"
    assert with_items.components.dims["D6"] == without.components.dims["D6"] and with_items.components.d6_raw == without.components.d6_raw


# ---------------------------------------------------------------- 4. adding descriptive evidence can never reduce D6
def test_adding_descriptive_evidence_cannot_reduce_d6_property():
    rng = random.Random(77)
    for _ in range(150):
        n_q = rng.randint(1, 4)
        base = [quantified(f"q{k}", effect=rng.choice([0.0, 0.004, 0.01, 0.05, 0.3]), n=rng.choice([30, 400, 1000, 6000]),
                           stance=rng.choice(["supports", "contradicts", "neutral"])) for k in range(n_q)]
        base += [item("c1", type="customer"), item("f1", type="financial")]
        before = d6(*base)
        extra = [descriptive(f"d{k}") for k in range(rng.randint(1, 4))]
        after = d6(*base, *extra)
        assert after[0] >= before[0] and after[1] == before[1] and after == before


# ---------------------------------------------------------------- 5. quantified evidence works exactly as before
def test_quantified_behavioral_evidence_affects_d6_exactly_as_before():
    one = d6(quantified("q1"), item("c", type="customer"))
    assert one[2] == 1 and one[1] == pytest.approx(1.0 * 1.0)                         # n 2000 >= 1000, |0.05| >= 0.02 -> 1.0
    mixed = d6(quantified("q1"), quantified("q2", effect=0.01, n=500), item("c", type="customer"))
    assert mixed[1] == pytest.approx((1.0 * 1.0 + 0.5 * 0.5) / 2)                     # the Day-3 mean of adequacy x materiality
    assert mixed[2] == 2
    # a quantified item with a missing effect size on the success metric still counts (the Day-3 rule is untouched)
    nan_effect = d6(quantified("q1"), item("q3", type="behavioral", metric_id=METRIC, n_sample=2000, effect_size=None),
                    item("c", type="customer"))
    assert nan_effect[2] == 2 and nan_effect[1] == pytest.approx(0.5)


# ---------------------------------------------------------------- 6. stance never enters D6
def test_flipping_a_quantified_items_stance_leaves_d6_unchanged():
    ref = d6(quantified("q1", stance="supports"), quantified("q2", stance="supports", effect=0.01), item("c", type="customer"))
    for flipped in ("contradicts", "neutral"):
        assert d6(quantified("q1", stance=flipped), quantified("q2", stance="supports", effect=0.01), item("c", type="customer")) == ref
    assert d6(descriptive("trend"), quantified("q1", stance="contradicts")) == d6(quantified("q1", stance="supports"))


# ---------------------------------------------------------------- B2 known consequence: the gate
def test_the_gate_no_longer_counts_descriptive_evidence_as_linked_to_the_success_metric():
    only_descriptive = facts([descriptive("trend"), descriptive("funnel"), item("c", type="customer")])
    codes = [r.code for r in evaluate_gate(only_descriptive, PARAMS).reasons]
    assert "success_metric_evidence" in codes
    assert "success_metric_evidence" not in [r.code for r in evaluate_gate(facts(BASE), PARAMS).reasons]
    # a single quantified or experiment item restores the link (the Day-3 gate is untouched)
    assert "success_metric_evidence" not in [r.code for r in evaluate_gate(
        replace(only_descriptive, items=(*only_descriptive.items, quantified("q1"))), PARAMS).reasons]
