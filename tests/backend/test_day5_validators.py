"""Deterministic validators (V1) and the deterministic half of the mutation suite (E2). Pure: no database, no LLM."""

from __future__ import annotations

import pytest

from app.synthesis import validators as V
from app.synthesis.validators import ValidationContext

RANK = {"rct": 3, "holdout": 2, "pre_post": 1, "other": 0}


def item(eid, etype, stance="supports", **over):
    base = {"id": eid, "evidence_type": etype, "stance": stance, "effect_size": None, "summary": f"{etype} item", "n_sample": 1000}
    base.update(over)
    return base


EVIDENCE = {
    "beh": item("beh", "behavioral", effect_size=0.2304, summary="46.0% vs 22.9%; difference +23.0% (95% CI +21.7% to +24.4%)", n_sample=40730),
    "beh0": item("beh0", "behavioral", stance="neutral", summary="trend, descriptive"),
    "exp_ok": item("exp_ok", "experiment", stance="neutral", effect_size=0.05,
                   experiment={"design": "rct", "srm_flag": False, "design_power": 0.82, "mde": 0.02}),
    "exp_bad": item("exp_bad", "experiment", stance="neutral", experiment={"design": "holdout", "srm_flag": True}),
    "exp_pre": item("exp_pre", "experiment", stance="neutral", experiment={"design": "pre_post", "srm_flag": False}),
    "cust": item("cust", "customer", n_sample=706, summary="706 relevant mentions"),
    "cust_con": item("cust_con", "customer", stance="contradicts", n_sample=113),
    "fin": item("fin", "financial", effect_size=1.2),
}
SCORED = {"state": "scored", "ddi": 60.5, "band": "high", "dimensions": [{"id": "D1", "score": 0.375, "display_contribution": 8.9}]}
CTX = ValidationContext(evidence=EVIDENCE, assessment=SCORED, assessment_state="scored", criteria_count=3, design_rank=RANK)
GATED = ValidationContext(evidence=EVIDENCE, assessment={"state": "insufficient_evidence"}, assessment_state="insufficient_evidence",
                          criteria_count=3, design_rank=RANK)


def claim(lid="c1", text="A plain statement.", ctype="descriptive", stance="neutral", ids=("beh",), ref="D1", conf="low"):
    return {"local_id": lid, "text": text, "claim_type": ctype, "stance": stance, "confidence": conf, "evidence_ids": list(ids),
            "conclusion_ref": ref}


def output(claims, sections=None, **extra):
    first = claims[0]["local_id"] if claims else "c1"
    return {"claims": claims, "uncertainties": extra.get("uncertainties", []), "gaps": extra.get("gaps", []),
            "criteria_assessment": extra.get("criteria", []),
            "sections": sections or {"summary": f"A sentence [[{first}]].", "supporting": "", "contradicting": "", "uncertainty": ""}}


def run(claims, ctx=CTX, **kw):
    return V.validate_synthesis(output(claims, **kw), ctx)


# ================================================================ V-ID
def test_v_id_pass_and_fail():
    out, rep = run([claim(ids=("beh",))])
    assert rep.status == "passed" and rep.surviving == ["c1"]
    out, rep = run([claim("c1", ids=("beh",)), claim("c2", ids=("fabricated-id",)), claim("c3", ids=())])
    assert rep.surviving == ["c1"] and [d["rule"] for d in rep.dropped] == ["V-ID", "V-ID"] and rep.status == "rejected_by_validators"
    assert "fabricated-id" in rep.dropped[0]["reason"]


def test_v_id_a_proposed_or_rejected_item_is_not_in_the_supplied_set():
    """The input contains active items only, so a cited id of a proposed item fails V-ID."""
    _, rep = run([claim("c1", ids=("beh",)), claim("c2", ids=("proposed-item",)), claim("c3", ids=("beh0",))])
    assert rep.surviving == ["c1", "c3"] and rep.dropped[0]["local_id"] == "c2"


# ================================================================ V-SEM-TYPE (T3: an in-input but semantically wrong citation)
def test_v_sem_type_customer_and_financial_claims_need_matching_evidence():
    _, rep = run([claim("c1", ctype="customer", ids=("cust",), ref="D5", stance="supports"),
                  claim("c2", ctype="customer", ids=("beh",), ref="D5"),                       # in the input, but not customer evidence
                  claim("c3", ctype="financial", ids=("fin",), ref="D7", stance="supports"),
                  claim("c4", ctype="financial", ids=("cust",), ref="D7")])
    assert rep.surviving == ["c1", "c3"]
    assert {d["local_id"]: d["rule"] for d in rep.dropped} == {"c2": "V-SEM-TYPE", "c4": "V-SEM-TYPE"}


def test_v_sem_type_causal_needs_a_qualifying_experiment_else_it_becomes_associative():
    out, rep = run([claim("c1", ctype="causal", ids=("exp_ok",), ref="D4"),                     # rct, SRM passed: stays causal
                    claim("c2", ctype="causal", ids=("beh",), stance="supports", ref="D6"),     # observational: reclassified
                    claim("c3", ctype="causal", ids=("exp_bad",), ref="D4"),                    # SRM failed: reclassified
                    claim("c4", ctype="causal", ids=("exp_pre",), ref="D4"),                    # design below holdout: reclassified
                    claim("c5", ctype="causal", ids=("cust",), ref="D5", stance="supports")])   # cannot be associative either: dropped
    types = {c["local_id"]: c["claim_type"] for c in out["claims"]}
    assert types == {"c1": "causal", "c2": "associative", "c3": "associative", "c4": "associative"}
    assert [r["local_id"] for r in rep.reclassified] == ["c2", "c3", "c4"] and rep.dropped[0]["local_id"] == "c5"


def test_v_sem_type_associative_needs_behavioral_or_experiment():
    _, rep = run([claim("c1", ctype="associative", ids=("beh",), ref="D6", stance="supports"),
                  claim("c2", ctype="associative", ids=("cust",), ref="D5", stance="supports")])
    assert rep.surviving == ["c1"] and rep.dropped[0]["rule"] == "V-SEM-TYPE"


# ================================================================ V-SEM-STANCE
def test_v_sem_stance_supports_and_contradicts_need_a_matching_item():
    _, rep = run([claim("c1", stance="supports", ids=("beh",)),
                  claim("c2", stance="supports", ids=("cust_con",), ctype="customer", ref="D5"),     # cites only a contradicting item
                  claim("c3", stance="contradicts", ids=("cust_con",), ctype="customer", ref="P1"),
                  claim("c4", stance="contradicts", ids=("beh",), ref="D6"),
                  claim("c5", stance="neutral", ids=("cust_con",), ctype="customer", ref="D5")])
    assert rep.surviving == ["c1", "c3", "c5"] and {d["local_id"]: d["rule"] for d in rep.dropped} == {"c2": "V-SEM-STANCE", "c4": "V-SEM-STANCE"}


# ================================================================ V-SEM-SCOPE
@pytest.mark.parametrize("ref,ids,ok", [
    ("D4", ("exp_ok",), True), ("D4", ("beh",), False), ("D5", ("cust",), True), ("D5", ("beh",), False),
    ("D6", ("beh",), True), ("D6", ("beh0",), False), ("D6", ("cust",), False), ("D7", ("fin",), True), ("D7", ("beh",), False),
    ("P1", ("cust_con",), True), ("P1", ("beh",), False), ("D1", ("beh",), True), ("D2", ("cust",), True), ("D3", ("beh0",), True),
    ("P2", ("exp_bad",), True), ("gate", ("beh",), True), ("D9", ("beh",), False), (None, ("beh",), False)])
def test_v_sem_scope(ref, ids, ok):
    stance = "contradicts" if (ref == "P1" and ok) else "neutral"
    ctype = "customer" if ids == ("cust",) or ids == ("cust_con",) else "descriptive"
    _, rep = run([claim("c1", ids=ids, ref=ref, stance=stance, ctype=ctype), claim("c2", ids=("beh",), ref="D1")])
    assert ("c1" in rep.surviving) is ok
    if not ok:
        assert rep.dropped[0]["rule"] == "V-SEM-SCOPE"


# ================================================================ V-NUM
def test_v_num_numbers_must_appear_in_the_cited_items_or_the_ddi_payload():
    ok = claim("c1", text="Retention is 46.0% against 22.9%, a difference of +23.0% (95% CI +21.7% to +24.4%) among 40,730 users.", ids=("beh",))
    rounded = claim("c2", text="The effect is about 0.23 with a rate of 46% and 0.2304 exactly.", ids=("beh",))
    ddi = claim("c3", text="The DDI is 60.5 with D1 at 0.375 on 2026-08-31.", ids=("beh",))
    bad = claim("c4", text="Retention is 51.3% for these users.", ids=("beh",))
    other_item = claim("c5", text="There are 706 mentions.", ids=("beh",))                        # exists, but not in the CITED item
    _, rep = run([ok, rounded, ddi, bad, other_item])
    assert rep.surviving == ["c1", "c2", "c3"] and {d["local_id"] for d in rep.dropped} == {"c4", "c5"}
    assert all(d["rule"] == "V-NUM" for d in rep.dropped) and "51.3%" in rep.dropped[0]["reason"]


def test_v_num_ignores_ids_dates_and_code_tokens():
    assert [n.raw for n in V.numbers_in("D4 and P1 on 2026-08-31 in 2026, see [[c12]] and ai_coach_session, D90 retention")] == []
    assert [n.raw for n in V.numbers_in("n=1,050 and +0.293 and 12%")] == ["1,050", "+0.293", "12%"]


# ================================================================ V-REC
@pytest.mark.parametrize("text", [
    "The team should approve the investment.", "We recommend expanding the coach.", "Go ahead with the launch.", "Proceed with the redesign.",
    "I suggest delaying.", "This must be rejected.", "Approve the proposal now.", "The recommendation is to wait.", "Do not proceed.",
    "It would be advisable to cancel the test."])
def test_v_rec_rejects_recommendation_phrasing_in_any_field(text):
    for place in ("claim", "section", "uncertainty", "gap"):
        claims = [claim(text=text if place == "claim" else "A plain statement.")]
        out = output(claims, sections={"summary": (text if place == "section" else "A plain sentence") + " [[c1]].", "supporting": "",
                                       "contradicting": "", "uncertainty": ""},
                     uncertainties=[{"text": text, "evidence_ids": ["beh"]}] if place == "uncertainty" else [],
                     gaps=[{"text": text, "gap_type": "other"}] if place == "gap" else [])
        _, rep = V.validate_synthesis(out, CTX)
        assert rep.status == "rejected_by_validators" and any(r["rule"] == "V-REC" for r in rep.rejections), (place, text)


def test_v_rec_passes_neutral_evidence_language():
    _, rep = run([claim(text="The comparison is observational, so the difference may reflect who adopts the feature.")],
                 sections={"summary": "The evidence is mixed [[c1]].", "supporting": "", "contradicting": "", "uncertainty": ""})
    assert rep.status == "passed" and not rep.rejections


# ================================================================ V-GATE
@pytest.mark.parametrize("text", ["There is sufficient evidence to score this.", "The evidence is strong.", "DDI 61.2 shows high risk.",
                                  "The decision debt index is 61 out of 100.", "The result is well supported.", "A strong evidence base exists."])
def test_v_gate_an_insufficient_assessment_never_reads_as_sufficient_or_shows_a_ddi_number(text):
    _, rep = V.validate_synthesis(output([claim(text=text)]), GATED)
    assert rep.status == "rejected_by_validators" and any(r["rule"] == "V-GATE" for r in rep.rejections)


def test_v_gate_passes_the_honest_wording_and_does_not_apply_to_a_scored_assessment():
    honest = "The assessment has insufficient evidence and no DDI is shown [[c1]]. There is no strong evidence yet."
    _, rep = V.validate_synthesis(output([claim(text="Evidence is insufficient.")], sections={"summary": honest, "supporting": "",
                                                                                               "contradicting": "", "uncertainty": ""}), GATED)
    assert rep.status == "passed", rep.rejections
    _, rep = V.validate_synthesis(output([claim(text="The evidence is strong here.")]), CTX)
    assert rep.status == "passed"


# ================================================================ V-REF
def test_v_ref_dropped_and_unknown_references_are_removed_and_uncited_sentences_go():
    claims = [claim("c1", ids=("beh",)), claim("c2", ids=("fabricated",)), claim("c3", ids=("beh0",))]
    sections = {"summary": "Kept sentence [[c1]]. Mixed sentence [[c1]] [[c2]]. Only dropped [[c2]]. No reference at all. Unknown [[zz]].",
                "supporting": "", "contradicting": "Another [[c3]].", "uncertainty": ""}
    out, rep = V.validate_synthesis(output(claims, sections=sections), CTX)
    assert out["sections"]["summary"] == "Kept sentence [[c1]]. Mixed sentence [[c1]]."
    removed = [r for r in rep.repaired if "removed_ref" in r]
    assert {r["removed_ref"] for r in removed} == {"c2", "zz"}
    assert sum(1 for r in rep.repaired if "removed_sentence" in r) == 3
    assert out["sections"]["contradicting"] == "Another [[c3]]." and rep.status == "passed"


# ================================================================ drop threshold, uncertainties and criteria
def test_more_than_half_the_claims_dropped_rejects_the_synthesis_exactly_half_does_not():
    _, rep = run([claim("c1", ids=("beh",)), claim("c2", ids=("nope",))])
    assert rep.claims_dropped == 1 and rep.status == "passed"
    _, rep = run([claim("c1", ids=("beh",)), claim("c2", ids=("nope",)), claim("c3", ids=("nope",))])
    assert rep.status == "rejected_by_validators" and any(r["rule"] == "V-DROP" for r in rep.rejections)
    _, rep = run([claim("c1", ids=("nope",))])
    assert rep.status == "rejected_by_validators"


def test_uncertainties_and_criteria_with_unknown_ids_or_indices_are_dropped():
    out, rep = run([claim()], uncertainties=[{"text": "ok", "evidence_ids": ["beh"]}, {"text": "bad", "evidence_ids": ["ghost"]}],
                   criteria=[{"criterion_index": 0, "status": "met", "evidence_ids": ["beh"]},
                             {"criterion_index": 7, "status": "met", "evidence_ids": []},
                             {"criterion_index": 1, "status": "not_met", "evidence_ids": ["ghost"]}])
    assert len(out["uncertainties"]) == 1 and [c["criterion_index"] for c in out["criteria_assessment"]] == [0]
    assert len(rep.other_dropped) == 3


# ================================================================ E2 (deterministic half): injected faults are caught by code
def test_e2_injected_unsupported_overstated_and_contradiction_omitted_claims_are_caught_by_validators():
    injected = [
        claim("m1", text="Retention rose to 88.8% for coach users.", ids=("beh",)),                     # fabricated number (unsupported)
        claim("m2", text="Customers love the feature.", ctype="customer", ids=("beh",), ref="D5", stance="supports"),   # wrong evidence type
        claim("m3", text="The feature causes retention.", ctype="causal", ids=("beh",), ref="D6", stance="supports"),   # overstated
        claim("m4", text="Customers are unhappy.", ctype="customer", stance="contradicts", ids=("cust",), ref="P1"),    # wrong stance citation
    ]
    out, rep = run([claim("ok1", ids=("beh",)), claim("ok2", ids=("beh0",)), claim("ok3", ids=("cust",), ctype="customer", ref="D5",
                                                                                  stance="supports")] + injected)
    assert {d["local_id"]: d["rule"] for d in rep.dropped} == {"m1": "V-NUM", "m2": "V-SEM-TYPE", "m4": "V-SEM-STANCE"}
    assert [r["local_id"] for r in rep.reclassified] == ["m3"]
    # the overstated causal claim is typed associative but its wording is the reviewer's job (live, opt-in): see test_day5_evals
    assert next(c for c in out["claims"] if c["local_id"] == "m3")["claim_type"] == "associative"


def test_e2_a_dq_ignored_or_recommendation_mutation_rejects_or_is_left_to_the_reviewer():
    """Recommendation language is rejected by code. Ignoring a data-quality finding is a narrative fault: code cannot see it, the
    Reviewer (minimum severity blocking) must, so the deterministic part passes it through."""
    _, rep = V.validate_synthesis(output([claim(text="The team should approve this.")]), CTX)
    assert rep.status == "rejected_by_validators"
    _, rep = V.validate_synthesis(output([claim(text="Data quality is fine and nothing blocks the analysis.")]), CTX)
    assert rep.status == "passed"
