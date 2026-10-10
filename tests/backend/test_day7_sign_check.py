"""Day 7 (D7-06): the V-NUM sign check. A number in a claim that carries an explicit sign or direction word must match the sign of the signed
value (effect, confidence-interval bound) it matched. Unsigned candidates (counts, sample sizes, DDI) are unaffected. Pure unit tests."""

from __future__ import annotations

import pytest

from app.synthesis import validators as v


def ctx(**item) -> v.ValidationContext:
    base = {"id": "e1", "evidence_type": "behavioral", "stance": "supports", "grade": "B", "effect_size": 0.05, "ci_low": 0.03, "ci_high": 0.07,
            "n_sample": 5000, "summary": "Observational comparison."}
    base.update(item)
    return v.ValidationContext(evidence={"e1": base}, assessment={"ddi": 60.5, "band": "high"}, assessment_state="scored", criteria_count=1,
                               design_rank={"rct": 1.0, "holdout": 0.8})


def claim(text: str) -> dict:
    return {"local_id": "c1", "text": text, "claim_type": "descriptive", "stance": "neutral", "confidence": "low", "evidence_ids": ["e1"],
            "conclusion_ref": "D1"}


def test_decreased_5_percent_against_a_positive_5_percent_is_dropped():
    reason = v.check_numbers(claim("Retention decreased 5%."), ctx())
    assert reason is not None and "direction" in reason


def test_increased_23_percent_against_a_positive_effect_passes():
    assert v.check_numbers(claim("Retention increased 23.0%."), ctx(effect_size=0.230, ci_low=0.2, ci_high=0.26)) is None


@pytest.mark.parametrize("text", ["Retention fell by 5%.", "The outcome was 5% lower than before.", "Retention declined 5%.", "The change is -0.05."])
def test_a_downward_statement_against_a_positive_effect_is_dropped(text):
    assert v.check_numbers(claim(text), ctx()) is not None


@pytest.mark.parametrize("text", ["Retention rose by 5%.", "The outcome increased 5%.", "The effect is +0.05.", "The effect is 0.05."])
def test_an_upward_or_unsigned_statement_against_a_positive_effect_passes(text):
    assert v.check_numbers(claim(text), ctx()) is None


def test_a_negative_effect_and_negative_interval_bounds_pass_when_the_claim_agrees():
    c = ctx(effect_size=-0.0204, ci_low=-0.0752, ci_high=0.0343)
    assert v.check_numbers(claim("The effect is -0.0204 with an interval from -0.0752 to +0.0343."), c) is None
    assert v.check_numbers(claim("Conversion fell by 2.04%."), c) is None
    assert v.check_numbers(claim("Conversion rose by 2.04%."), c) is not None


def test_unsigned_candidates_are_unaffected_counts_sample_sizes_and_ddi():
    c = ctx()
    assert v.check_numbers(claim("The comparison covers 5000 users, fewer than planned and lower in power."), c) is None
    assert v.check_numbers(claim("The DDI decreased to 60.5 after the new evidence."), c) is None


def test_a_number_that_is_not_in_the_evidence_is_still_dropped_first():
    reason = v.check_numbers(claim("Retention decreased 42%."), ctx())
    assert reason is not None and "do not appear" in reason


def test_a_direction_word_far_from_the_number_is_not_read_as_its_direction():
    assert v.check_numbers(claim("Costs fell last quarter, and separately the effect is 5% in this comparison."), ctx()) is None


def test_the_whole_synthesis_drops_the_wrong_sign_claim_and_keeps_the_rest():
    out = {"claims": [dict(claim("Retention decreased 5%."), local_id="c1"),
                      dict(claim("The effect is 5%."), local_id="c2"), dict(claim("The effect is 5%."), local_id="c3")],
           "uncertainties": [], "gaps": [], "criteria_assessment": [],
           "sections": {"summary": "A [[c2]]. B [[c3]].", "supporting": "", "contradicting": "", "uncertainty": ""}}
    validated, report = v.validate_synthesis(out, ctx())
    assert [d["local_id"] for d in report.dropped] == ["c1"] and report.dropped[0]["rule"] == "V-NUM"
    assert [c["local_id"] for c in validated["claims"]] == ["c2", "c3"]
