"""Scenario tests A1 to A4 and the Day-5 API (recorded client, hand-authored stub fixtures).

NO DDI band is asserted in advance (D4-24, brief section 11): every test asserts that the stored state, band and score equal what
the frozen engine returns for the very same facts, plus the structural properties of the brief. The numbers the engine produced
are reported in docs/day-5-implementation-notes.md."""

from __future__ import annotations

import pytest
from day4_support import TODAY
from day5_support import Scenario, customer_items, ctx5
from fastapi.testclient import TestClient
from flow import Flow
from replay import STUB_MODELS, ReplayClient
from sqlalchemy import select

from app.core import deps
from app.core.clock import FixedClock
from app.db import models as m
from app.domain.ddi import assess
from app.main import app
from app.repositories import syntheses as syn_repo
from app.repositories.evidence_facts import build_facts
from app.services import BriefService

H = lambda actor: {"X-Demo-User": actor.id}  # noqa: E731


def engine_result(sc: Scenario):
    """What the frozen DDI engine returns for the current facts (the assessment is compared against it, never against a literal)."""
    facts = build_facts(sc.session, sc.decision.id)
    return assess(facts, sc.ctx.ddi_params, TODAY), facts


def assert_matches_the_engine(sc: Scenario):
    result, facts = engine_result(sc)
    a = sc.assessment
    assert a.state == result.state and a.ddi_band == (result.band if result.scored else None)
    assert (float(a.ddi_score) if a.ddi_score is not None else None) == (result.ddi if result.scored else None)
    return result, facts


def synthesis_and_review(sc: Scenario):
    syn = syn_repo.latest_synthesis(sc.session, sc.assessment.id)
    reviews = syn_repo.agent_reviews(sc.session, sc.assessment.id)
    return syn, reviews[-1]


def assert_grounded(sc: Scenario, syn):
    """Every stored claim cites only ACTIVE evidence of this decision, and every cited item exists (traceability)."""
    active = {str(e.id) for e in sc.session.scalars(select(m.Evidence).where(m.Evidence.decision_id == sc.decision.id, m.Evidence.status == "active"))}
    pairs = syn_repo.claims_for_synthesis(sc.session, syn.id)
    assert pairs and all(ids and {str(i) for i in ids} <= active for _, ids in pairs)
    return pairs


# ================================================================ A1 AI Coach
def test_a1_ai_coach_gate_passes_after_approval_the_synthesis_is_grounded_and_the_reviewer_flags_the_causal_overclaim(session, seed):
    sc = Scenario(session, seed, "ai_coach").run()
    # before approval: three PROPOSED customer items, none in the facts of the first assessment
    assert len(sc.first.pending_approvals) == 3 and {p["stance"] for p in sc.first.pending_approvals} == {"supports", "contradicts", "neutral"}
    assert len(sc.approved) == 3 and all(c.status == "active" and c.approved_by for c in customer_items(session, sc.decision))
    # the first assessment did not see them: its fingerprint differs from the one of the assessment that includes them
    assert sc.first.assessment.evidence_fingerprint != sc.assessment.evidence_fingerprint
    # after approval: the gate passes and the assessment is scored, with whatever band the frozen engine produces
    assert sc.assessment.state == "scored" and sc.assessment.version == 2
    result, facts = assert_matches_the_engine(sc)
    assert sum(1 for i in facts.items if i.evidence_type == "customer") == 3 and result.band in ("low", "moderate", "high", "critical")
    # the synthesis is grounded; the injected causal claim was reclassified by code, nothing else was dropped
    syn, review = synthesis_and_review(sc)
    assert syn.status == "succeeded" and syn.claims_dropped == 0 and sc.second.synthesis["status"] == "succeeded"
    pairs = assert_grounded(sc, syn)
    assert [r["local_id"] for r in syn.validator_report["reclassified"]] == ["c7"]
    c7 = next(c for c, _ in pairs if c.local_id == "c7")
    assert c7.claim_type == "associative"
    # the reviewer flags it; the model wrote 'warning', code made it blocking, and the verdict follows
    f = next(x for x in review.challenges if x["category"] == "causal_from_observational")
    assert (f["severity_model"], f["severity"], f["target_local_id"], f["target_id"]) == ("warning", "blocking", "c7", str(c7.id))
    assert review.verdict == "needs_rework" and review.reviewer_type == "agent" and sc.decision.lifecycle_stage == "challenged"
    assert sc.second.review["verdict"] == "needs_rework" and sc.second.review["blocking"] == 1
    # a human may override with a reason (R12); the Decision Brief is then traceable end to end
    sc.session.refresh(sc.decision)
    flow = Flow(session, seed)
    with pytest.raises(Exception):
        flow.reviews.validate(seed.pm, sc.decision.id)                                  # needs_rework blocks validation
    flow.reviews.record_human_review(seed.pm, sc.assessment.id, "ready", "Reviewed by hand: the causal wording was reclassified to associative.")
    flow.reviews.validate(seed.pm, sc.decision.id)
    brief = BriefService(sc.ctx).create(seed.pm, sc.assessment.id, "decision_brief")
    c = brief.content
    assert c["ddi_panel"]["state"] == "scored" and c["ddi_panel"]["band"] == result.band and c["review"]["human_reviews"][0]["human_response"]
    assert c["review"]["agent_review"]["verdict"] == "needs_rework" and brief.synthesis_id == syn.id
    rows = [t for t in c["traceability"] if t["row_type"] == "claim_link"]
    assert {t["claim_id"] for t in rows} == {x["claim_id"] for x in c["claims"]} and all(t["source_name"] and t["evidence_id"] for t in rows)
    assert any(t["analysis_type"] in ("comparison", "experiment", "trend") for t in rows)
    assert {e["status"] for e in c["evidence_table"]} == {"active"} and len(c["evidence_table"]) == 6


# ================================================================ A2 Community
def test_a2_community_is_scored_after_approval_the_heterogeneity_floor_applies_and_notifications_are_contradicting_evidence(session, seed):
    sc = Scenario(session, seed, "community").run()
    assert sc.first.assessment.state == "insufficient_evidence"                                  # two items, one type, before approval
    assert sc.assessment.state == "scored"
    result, facts = assert_matches_the_engine(sc)
    assert facts.heterogeneity_flag is True
    p1 = sc.assessment.penalty_scores["penalties"]["P1"]
    assert p1["score"] >= sc.ctx.ddi_params.segment_divergence_floor_p1 and p1["details"]["floor_applied"] in (True, False)
    assert any(i["name"] == "heterogeneity_flag" and i["source"] == "observed" for i in p1["inputs"])
    notif = [e for e in customer_items(session, sc.decision) if e.stance == "contradicts"]
    assert len(notif) == 1 and notif[0].status == "active" and "notifications_unwanted" in notif[0].summary
    syn, review = synthesis_and_review(sc)
    assert syn.status == "succeeded" and syn.claims_dropped == 0
    pairs = assert_grounded(sc, syn)
    texts = " ".join(c.claim_text for c, _ in pairs) + " " + " ".join(syn.output["sections"].values())
    assert "aggregate" in texts and "segment" in texts.lower()                                  # aggregate versus segments is discussed
    contradicting = [c for c, ids in pairs if c.stance == "contradicts" and str(notif[0].id) in {str(i) for i in ids}]
    assert contradicting and contradicting[0].conclusion_ref == "P1"
    assert review.verdict == "ready" and sc.decision.lifecycle_stage == "challenged"
    Flow(session, seed).reviews.validate(seed.pm, sc.decision.id)
    brief = BriefService(sc.ctx).create(seed.pm, sc.assessment.id, "decision_brief")
    assert brief.content["heterogeneity"]["flag"] is True and "No automated adversarial review" not in brief.markdown


# ================================================================ A3 Onboarding
def test_a3_onboarding_complaints_become_active_evidence_but_the_gate_still_blocks_and_only_a_gated_summary_exists(session, seed):
    sc = Scenario(session, seed, "onboarding").run()
    items = customer_items(session, sc.decision)
    assert [(e.status, e.stance) for e in items] == [("active", "supports")] and items[0].approved_by is not None
    a = sc.assessment
    codes = [r["code"] for r in a.blocking_reasons]
    assert a.state == "insufficient_evidence" and "open_critical_dq" in codes
    assert a.ddi_score is None and a.ddi_band is None and a.penalty_scores == {} and a.sensitivity == {}
    assert a.dimension_scores["dimensions"] == {} and a.dimension_scores["ddi_display"] is None
    assert_matches_the_engine(sc)
    syn, review = synthesis_and_review(sc)
    assert syn.status == "succeeded" and review.verdict == "ready"
    out_text = " ".join(c["text"] for c in syn.output["claims"]) + " ".join(syn.output["sections"].values())
    assert "DDI" not in out_text.replace("no DDI is shown", "")                                    # no number or band, only the honest wording
    assert sc.decision.lifecycle_stage == "challenged"
    svc = BriefService(sc.ctx)
    with pytest.raises(Exception, match="only after the assessment is validated"):
        svc.create(seed.pm, a.id, "decision_brief")                                                # a Decision Brief is refused
    gated = svc.create(seed.pm, a.id, "gated_evidence_summary")
    assert gated.content["label"] == "Gated Evidence Summary: not a validated decision artifact" and gated.synthesis_id == syn.id
    assert gated.markdown.startswith("**Gated Evidence Summary: not a validated decision artifact**")
    assert "open_critical_dq" in gated.markdown and gated.content["ddi_panel"]["ddi"] is None and gated.content["unblocking_actions"]
    assert [x["description"] for x in gated.content["unblocking_actions"]] == ["Fix or add instrumentation, or resolve a data-quality issue"]
    section = gated.markdown.split("## DDI panel")[1].split("## Gate reasons")[0]
    assert not any(ch.isdigit() for ch in section)
    assert gated.content["llm_sections"]["summary"] and "insufficient evidence" in gated.markdown.lower()


# ================================================================ A4 Pricing
def test_a4_pricing_d4_is_unchanged_the_experiment_stays_inconclusive_and_the_reviewer_flags_the_no_harm_claim(session, seed):
    sc = Scenario(session, seed, "pricing").run()
    assert sc.first.assessment.state == sc.assessment.state == "scored"
    keys = ("score", "inputs", "explanation", "details")
    assert {k: sc.first.assessment.dimension_scores["dimensions"]["D4"][k] for k in keys} == \
           {k: sc.assessment.dimension_scores["dimensions"]["D4"][k] for k in keys}
    assert_matches_the_engine(sc)
    exp = next(e for e in session.scalars(select(m.Evidence).where(m.Evidence.decision_id == sc.decision.id)) if e.evidence_type == "experiment")
    assert exp.stance == "neutral" and exp.ci_low < 0 < exp.ci_high                                    # inconclusive: the interval spans zero
    syn, review = synthesis_and_review(sc)
    assert syn.status == "succeeded"
    pairs = assert_grounded(sc, syn)
    inconclusive = [c for c, _ in pairs if c.local_id == "c2"]
    assert inconclusive and "inconclusive" in inconclusive[0].claim_text and inconclusive[0].stance == "neutral"
    no_harm = next(c for c, _ in pairs if c.local_id == "c6")
    f = next(x for x in review.challenges if x["target_local_id"] == "c6")
    assert f["category"] == "statistical_misinterpretation" and f["severity"] == "blocking" and f["target_id"] == str(no_harm.id)
    assert review.verdict == "needs_rework" and sc.decision.lifecycle_stage == "challenged"


# ================================================================ API
@pytest.fixture()
def client(session):
    client_llm = ReplayClient()
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    app.dependency_overrides[deps.get_llm] = lambda: client_llm
    app.dependency_overrides[deps.get_llm_models] = lambda: STUB_MODELS
    yield TestClient(app, raise_server_exceptions=False), client_llm
    app.dependency_overrides.clear()


def test_api_the_day5_path_end_to_end_with_permissions(session, seed, client):
    http, llm = client
    d = seed.decisions["community"]
    session.refresh(d)
    r = http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["lifecycle_stage"] == "assessed" and len(body["pending_approvals"]) == 3 and body["synthesis"]["status"] == "failed"
    assert body["assessment"]["state"] == "insufficient_evidence" and [s["stage"] for s in body["stages"]][-2:] == ["assessment", "synthesis"]
    listing = http.get(f"/decisions/{d.id}/customer-evidence", headers=H(seed.bizops)).json()
    assert listing["pending_approvals"] == 3 and len(listing["items"]) == 3 and listing["classification_counts"][0]["total"] == 6083
    item = listing["items"][0]
    assert item["evidence"]["status"] == "proposed" and item["insight"]["relevance_note"] == "observed, not used by DDI v0.1"
    assert item["classification_counts"]["by_relevance"]["direct"] > 0
    ev_id = item["evidence"]["id"]
    for actor in (seed.pm, seed.leader, seed.executive, seed.bizops):
        assert http.patch(f"/evidence/{ev_id}/approval", headers=H(actor), json={"action": "approve"}).status_code == 403
    assert http.patch(f"/evidence/{ev_id}/approval", headers=H(seed.ba), json={"action": "bogus"}).status_code == 422
    assert http.patch(f"/evidence/{ev_id}/approval").status_code == 401
    for it in listing["items"]:
        r = http.patch(f"/evidence/{it['evidence']['id']}/approval", headers=H(seed.ba), json={"action": "approve", "note": "ok"})
        assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["approved_by"] == seed.ba.id
    assert http.patch(f"/evidence/{ev_id}/approval", headers=H(seed.ba), json={"action": "reject"}).status_code == 409      # not proposed any more
    assert http.get(f"/decisions/{d.id}", headers=H(seed.pm)).json()["lifecycle_stage"] == "evidence_gathered"
    r = http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
    body = r.json()
    assert r.status_code == 201 and body["assessment"]["state"] == "scored" and body["synthesis"]["status"] == "succeeded"
    assert body["review"]["status"] == "reviewed" and body["review"]["verdict"] == "ready" and body["pending_approvals"] == []
    aid = body["assessment"]["id"]
    assert http.get(f"/decisions/{d.id}", headers=H(seed.pm)).json()["lifecycle_stage"] == "challenged"
    # syntheses: list, idempotent re-run, forced new version with a new review
    assert len(http.get(f"/assessments/{aid}/syntheses", headers=H(seed.executive)).json()) == 1
    again = http.post(f"/assessments/{aid}/syntheses", headers=H(seed.pm), json={})
    assert again.status_code == 200 and again.json()["reused"] is True and again.json()["synthesis"]["version"] == 1
    forced = http.post(f"/assessments/{aid}/syntheses", headers=H(seed.ba), json={"force": True})
    assert forced.status_code == 201 and forced.json()["synthesis"]["version"] == 2 and forced.json()["review"]["verdict"] == "ready"
    assert http.post(f"/assessments/{aid}/syntheses", headers=H(seed.analyst), json={}).status_code == 403
    assert http.post(f"/assessments/{aid}/syntheses", headers=H(seed.pm), json={"unknown": 1}).status_code == 422
    # briefs
    assert http.post(f"/assessments/{aid}/briefs", headers=H(seed.pm), json={"kind": "decision_brief"}).status_code == 409      # not validated
    assert http.post(f"/assessments/{aid}/briefs", headers=H(seed.pm), json={"kind": "gated_evidence_summary"}).status_code == 409
    assert http.post(f"/decisions/{d.id}/validate", headers=H(seed.pm)).status_code == 200
    assert http.post(f"/assessments/{aid}/briefs", headers=H(seed.analyst), json={"kind": "decision_brief"}).status_code == 403
    assert http.post(f"/assessments/{aid}/briefs", headers=H(seed.pm), json={"kind": "other"}).status_code == 422
    r = http.post(f"/assessments/{aid}/briefs", headers=H(seed.pm), json={"kind": "decision_brief"})
    assert r.status_code == 201 and r.json()["label"] == "Validated Decision Brief" and r.json()["version"] == 1
    got = http.get(f"/briefs/{r.json()['id']}", headers=H(seed.bizops))
    assert got.status_code == 200 and got.json()["markdown"].startswith("**Validated Decision Brief**") and got.json()["is_synthetic"] is True
    assert http.get("/briefs/not-a-uuid", headers=H(seed.pm)).status_code == 404
    assert http.get(f"/briefs/{r.json()['id']}").status_code == 401
    assert len(llm.calls_for("review")) == 2 and len(llm.calls_for("synthesize")) >= 3


def test_api_without_an_llm_client_the_pipeline_records_the_llm_stages_as_not_run_and_resynthesis_is_refused(session, seed):
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    app.dependency_overrides[deps.get_llm] = lambda: None
    try:
        http = TestClient(app, raise_server_exceptions=False)
        d = seed.decisions["pricing"]
        session.refresh(d)
        r = http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
        body = r.json()
        assert r.status_code == 201 and body["synthesis"]["status"] == "not_run" and body["review"]["status"] == "not_run"
        assert [s["stage"] for s in body["stages"]] == ["dq", "quant", "customer", "experiment", "materialize", "assessment"]
        assert next(s for s in body["stages"] if s["stage"] == "customer")["output"]["outcome"] == "skipped_no_llm_client"
        assert http.post(f"/assessments/{body['assessment']['id']}/syntheses", headers=H(seed.pm), json={}).status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert ctx5 is not None
