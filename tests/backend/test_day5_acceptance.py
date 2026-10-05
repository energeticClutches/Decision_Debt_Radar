"""Independent Day-5 acceptance probes (Opus verification, added after the implementation).

Adversarial checks on the real seeded scenarios, separate from the implementer's tests:
  * grounding: a wrong number, and citations that exist in the input but do not support the claim (T3)
  * the LLM boundary: the classifier cannot set stance or anything beyond theme and relevance; injected customer text
    cannot reach stance, grade or the DDI
  * lifecycle: approval only for proposed items, active agent customer evidence needs an approver (database CHECK),
    a Decision Brief is refused before validated
No DDI band is asserted: only that stored results equal the frozen engine's output.
"""

from __future__ import annotations

import json

import pytest
from day4_support import TODAY
from day5_support import Scenario, customer_items
from sqlalchemy import text

from app.domain.ddi import assess
from app.repositories.evidence_facts import build_facts
from app.synthesis import validators as v


def _ctx(sc: Scenario):
    payload, _ = sc.evidence_input()
    ctx = v.ValidationContext(evidence={e["id"]: e for e in payload["evidence"]}, assessment=payload["assessment"],
                              assessment_state=sc.assessment.state, criteria_count=len(payload["decision"]["criteria"]),
                              design_rank=dict(sc.ctx.ddi_params.design_rank))
    return payload, ctx


def _first(payload, **match):
    return next(e for e in payload["evidence"] if all(e.get(k) == val for k, val in match.items()))


def _claim(text, ctype, stance, ids, ref, local_id="x1"):
    return {"local_id": local_id, "text": text, "claim_type": ctype, "stance": stance, "confidence": "low",
            "evidence_ids": list(ids), "conclusion_ref": ref}


@pytest.fixture()
def ai_coach(session, seed):
    return Scenario(session, seed, "ai_coach").run()


# ---------------------------------------------------------------- grounding
def test_a_wrong_number_is_dropped_even_though_the_citation_is_valid(ai_coach):
    payload, ctx = _ctx(ai_coach)
    beh = _first(payload, evidence_type="behavioral", stance="supports")
    claim = _claim("Retention increased 42% for AI Coach users.", "associative", "supports", [beh["id"]], "D6"
                   if beh.get("effect_size") is not None else "D1")
    reason = v.check_numbers(claim, ctx)
    assert reason is not None and "42%" in reason


def test_a_valid_but_irrelevant_citation_is_dropped(ai_coach):
    """Right decision, right id, wrong evidence for the claim: a customer claim citing a behavioral item, and a D4 claim citing
    a customer item."""
    payload, ctx = _ctx(ai_coach)
    beh = _first(payload, evidence_type="behavioral")
    cust = _first(payload, evidence_type="customer")
    out1 = {"claims": [_claim("Customers say the coach helps.", "customer", beh["stance"], [beh["id"]], "D5")],
            "uncertainties": [], "gaps": [], "criteria_assessment": [], "sections": {k: "" for k in ("summary", "supporting", "contradicting", "uncertainty")}}
    _, rep1 = v.validate_synthesis(out1, ctx)
    assert rep1.dropped and rep1.dropped[0]["rule"] == "V-SEM-TYPE"
    assert v.check_scope(_claim("The experiment shows it.", "descriptive", "neutral", [cust["id"]], "D4"), ctx) is not None


def test_a_supports_claim_may_not_cite_contradicting_evidence(ai_coach):
    payload, ctx = _ctx(ai_coach)
    sup = _first(payload, evidence_type="customer", stance="supports")
    con = _first(payload, evidence_type="customer", stance="contradicts")
    claim = _claim("Customers find the coach helpful.", "customer", "supports", [sup["id"], con["id"]], "D5")
    assert v.check_stance(claim, ctx) is not None
    claim = _claim("Customers find the coach unhelpful.", "customer", "contradicts", [con["id"], sup["id"]], "D5")
    assert v.check_stance(claim, ctx) is not None


def test_a_recommendation_rejects_the_synthesis(ai_coach):
    assert v.recommendation_hits("Given this, the decision should be approved.")
    assert v.recommendation_hits("The team should launch the AI Coach.")


# ---------------------------------------------------------------- LLM boundary
def test_the_classifier_cannot_set_stance_or_any_other_field():
    from app.customer.schema import ClassificationSchemaError, parse_classifications
    bad = json.dumps({"classifications": [{"text_ref": "t1", "theme": "coach_helpful", "relevance": "direct", "stance": "supports"}]})
    with pytest.raises(ClassificationSchemaError):
        parse_classifications(bad, themes={"coach_helpful"}, text_refs={"t1"})


def test_customer_stance_and_grade_come_from_config_and_counts_not_from_text(ai_coach, session):
    """Every customer item's stance equals the tenant stance map and its grade is C or D (never A or B)."""
    stance_map = {t["theme"]: t["stance"]
                  for t in ai_coach.ctx.tenant.data["customer_taxonomy"]["ai_coach"]["themes"]}
    from app.db import models as m
    for ev in customer_items(session, ai_coach.decision):
        insight = session.get(m.CustomerInsight, ev.insight_id)
        assert ev.stance == stance_map[insight.theme]
        assert ev.strength_grade in ("C", "D")


def test_the_stored_assessment_equals_the_frozen_engine(ai_coach):
    facts = build_facts(ai_coach.session, ai_coach.decision.id)
    result = assess(facts, ai_coach.ctx.ddi_params, TODAY)
    a = ai_coach.assessment
    assert a.state == result.state and a.ddi_band == (result.band if result.scored else None)


# ---------------------------------------------------------------- lifecycle and approval
def test_approval_bypass_is_refused_by_the_database(ai_coach, session):
    ev = customer_items(session, ai_coach.decision)[0]
    with pytest.raises(Exception):
        with session.begin_nested():
            session.execute(text("UPDATE evidence SET approved_by = NULL, approved_at = NULL WHERE id = :i"), {"i": ev.id})
            session.flush()


def test_a_validated_insufficient_assessment_never_gets_a_decision_brief(session, seed):
    """T2: an insufficient assessment has a Gated Evidence Summary only, even after a human validates it."""
    from flow import Flow

    from app.domain.errors import StateConflict
    from app.services import BriefService
    from day5_support import ctx5
    flow = Flow(session, seed)
    d, a = flow.insufficient()
    flow.reviews.record_human_review(seed.pm, a.id, "ready", "Reviewed by hand: the gate reasons are understood.")
    flow.reviews.validate(seed.pm, d.id)
    session.refresh(d)
    assert d.lifecycle_stage == "validated"
    svc = BriefService(ctx5(session, None))
    with pytest.raises(StateConflict, match="scored assessment"):
        svc.create(seed.pm, a.id, "decision_brief")
    with pytest.raises(Exception, match="scored assessment"):
        with session.begin_nested():
            session.execute(text("INSERT INTO decision_briefs (assessment_id, kind, version, content, markdown, is_synthetic) "
                                 "VALUES (:a, 'decision_brief', 1, '{}'::jsonb, '', true)"), {"a": a.id})
    assert svc.create(seed.pm, a.id, "gated_evidence_summary").kind == "gated_evidence_summary"


def test_only_proposed_items_can_be_approved(ai_coach, session, seed):
    from app.services import CustomerEvidenceService
    ev = customer_items(session, ai_coach.decision)[0]
    assert ev.status == "active"
    with pytest.raises(Exception):
        CustomerEvidenceService(ai_coach.ctx).set_approval(seed.ba, ev.id, "reject", "late rejection")
