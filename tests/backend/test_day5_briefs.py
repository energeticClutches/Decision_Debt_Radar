"""Briefs (B1 to B4): the Validated Decision Brief and the Gated Evidence Summary."""

from __future__ import annotations

import json

import pytest
from day5_support import ctx5, review_output, synthesis_output_for
from flow import Flow
from replay import RoutedClient, ScriptedClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.domain.errors import Forbidden, InvalidInput, StateConflict
from app.services import BriefService, ReviewerService, SynthesisService
from app.synthesis import payload as payload_mod
from app.synthesis.briefs import GATED_LABEL, render_markdown
from app.synthesis.validators import recommendation_hits


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def validated_decision(session, seed, flow):
    """A scored decision whose synthesis was reviewed (ready) and validated."""
    d, a = flow.scored()
    payload, _ = payload_mod.build_input(session, d, a)
    client = RoutedClient({"synthesize": ScriptedClient([synthesis_output_for(payload)]),
                           "review": ScriptedClient([review_output()])})
    ctx = ctx5(session, client)
    syn = SynthesisService(ctx).synthesize(seed.pm, a.id)
    rev = ReviewerService(ctx).review(seed.pm, syn.synthesis.id)
    assert rev.review.verdict == "ready"
    flow.reviews.validate(seed.pm, d.id)
    return d, a, ctx, syn.synthesis


# ================================================================ B1
def test_b1_a_decision_brief_is_refused_before_validated_and_the_database_agrees(session, seed, flow):
    d, a = flow.scored()
    payload, _ = payload_mod.build_input(session, d, a)
    client = RoutedClient({"synthesize": ScriptedClient([synthesis_output_for(payload)]), "review": ScriptedClient([review_output()])})
    ctx = ctx5(session, client)
    syn = SynthesisService(ctx).synthesize(seed.pm, a.id)
    svc = BriefService(ctx)
    for stage_setup in ("assessed", "challenged"):
        if stage_setup == "challenged":
            ReviewerService(ctx).review(seed.pm, syn.synthesis.id)
        assert flow.stage(d) == stage_setup
        with pytest.raises(StateConflict, match="only after the assessment is validated"):
            svc.create(seed.pm, a.id, "decision_brief")
    with pytest.raises(DBAPIError):                                                      # the trigger repeats the rule
        with session.begin_nested():
            session.execute(text("INSERT INTO decision_briefs (assessment_id, synthesis_id, kind, version, content, markdown, is_synthetic)"
                                 " VALUES (:a,:s,'decision_brief',1,'{}'::jsonb,'x',true)"), {"a": a.id, "s": syn.synthesis.id})
    flow.reviews.validate(seed.pm, d.id)
    brief = svc.create(seed.pm, a.id, "decision_brief")
    assert brief.kind == "decision_brief" and brief.version == 1 and brief.content["label"] == "Validated Decision Brief"


def test_b1_a_decision_brief_needs_a_succeeded_synthesis_permission_and_a_known_kind(session, seed, flow):
    d, a = flow.scored()
    flow.reviews.record_human_review(seed.pm, a.id, "ready", None)
    flow.reviews.validate(seed.pm, d.id)
    svc = BriefService(ctx5(session, None))
    with pytest.raises(StateConflict, match="succeeded synthesis"):
        svc.create(seed.pm, a.id, "decision_brief")
    for actor in (seed.analyst, seed.leader, seed.bizops, seed.executive):
        with pytest.raises(Forbidden):
            svc.create(actor, a.id, "decision_brief")
    with pytest.raises(InvalidInput):
        svc.create(seed.pm, a.id, "recommendation")


# ================================================================ B2
def test_b2_a_gated_summary_exists_only_for_an_insufficient_assessment_and_carries_the_label_everywhere(session, seed, flow):
    d, a = flow.insufficient()
    svc = BriefService(ctx5(session, None))
    b = svc.create(seed.pm, a.id, "gated_evidence_summary")
    assert b.kind == "gated_evidence_summary" and b.synthesis_id is None and b.version == 1
    assert b.content["label"] == "Gated Evidence Summary: not a validated decision artifact" == GATED_LABEL
    assert b.content["banners"][0] == GATED_LABEL and b.markdown.startswith(f"**{GATED_LABEL}**") and b.markdown.rstrip().endswith(f"**{GATED_LABEL}**")
    assert b.content["ddi_panel"]["state"] == "insufficient_evidence" and b.content["ddi_panel"]["ddi"] is None
    assert b.content["ddi_panel"]["band"] is None and b.content["blocking_reasons_explained"] and b.content["unblocking_actions"] is not None
    assert "no DDI, band, dimension or penalty" in b.markdown and "Why this assessment is gated" in b.markdown
    assert not any(ch in b.markdown.split("## DDI panel")[1].split("## Gate reasons")[0] for ch in "0123456789"), "a number appears in the DDI panel"
    with pytest.raises(StateConflict):                                                   # never usable as a Decision Brief
        svc.create(seed.pm, a.id, "decision_brief")
    assert b.version == 1 and svc.create(seed.pm, a.id, "gated_evidence_summary").version == 2


def test_b2_a_scored_assessment_cannot_have_a_gated_summary(session, seed, flow):
    d, a = flow.scored()
    with pytest.raises(StateConflict, match="insufficient_evidence"):
        BriefService(ctx5(session, None)).create(seed.pm, a.id, "gated_evidence_summary")
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.execute(text("INSERT INTO decision_briefs (assessment_id, kind, version, content, markdown, is_synthetic)"
                                 " VALUES (:a,'gated_evidence_summary',1,'{}'::jsonb,'x',true)"), {"a": a.id})


# ================================================================ B3
def test_b3_briefs_are_immutable_versioned_and_contain_no_recommendation(session, seed, flow):
    d, a, ctx, syn = validated_decision(session, seed, flow)
    svc = BriefService(ctx)
    b1 = svc.create(seed.pm, a.id, "decision_brief")
    b2 = svc.create(seed.ba, a.id, "decision_brief")
    assert (b1.version, b2.version, b1.id != b2.id) == (1, 2, True) and b1.synthesis_id == syn.id
    for sql in ("UPDATE decision_briefs SET markdown = 'x' WHERE id = :i", "DELETE FROM decision_briefs WHERE id = :i",
                "UPDATE decision_briefs SET content = '{}'::jsonb WHERE id = :i"):
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text(sql), {"i": b1.id})
    with pytest.raises(DBAPIError):                                                      # a duplicate version is refused
        with session.begin_nested():
            session.execute(text("INSERT INTO decision_briefs (assessment_id, synthesis_id, kind, version, content, markdown, is_synthetic)"
                                 " VALUES (:a,:s,'decision_brief',1,'{}'::jsonb,'x',true)"), {"a": a.id, "s": syn.id})
    for b in (b1, b2):
        md = b.markdown
        heads = [ln.lower() for ln in md.splitlines() if ln.startswith("#")]
        assert not any("recommend" in h for h in heads), heads
        assert "recommend" not in md.lower()
        offenders = {ln: recommendation_hits(ln) for ln in md.splitlines() if recommendation_hits(ln)}
        assert offenders == {}, offenders
        assert "not a statement that the decision is correct" in md and "Assessment validated by review" in md
        blob = json.dumps(b.content)
        assert "recommendation" not in blob.lower()
    assert b1.content["header"]["decision"]["lifecycle_label"] == "Assessment validated by review"
    versions = b1.content["header"]["versions"]
    for key in ("ddi_params", "nbe_params", "analytics_params", "tenant_config", "synthesis_prompt", "synthesis_model", "review_prompt", "review_model",
                "synthesis"):
        assert key in versions, key
    assert "ddi_params_v0.1" in versions["ddi_params"] and "stub:" in versions["synthesis_model"]
    assert b1.content["synthesis"]["provenance"] == "stub_not_model_output"
    md = render_markdown(b1.content)
    assert md == b1.markdown                                                              # rendering is a pure function of the content


# ================================================================ B4
def test_b4_every_llm_sentence_resolves_to_claims_and_evidence(session, seed, flow):
    d, a, ctx, syn = validated_decision(session, seed, flow)
    b = BriefService(ctx).create(seed.pm, a.id, "decision_brief")
    c = b.content
    evidence_ids = {e["id"] for e in c["evidence_table"]}
    claim_by_local = {x["local_id"]: x for x in c["claims"]}
    assert c["claims"] and all(x["evidence_ids"] and set(x["evidence_ids"]) <= evidence_ids for x in c["claims"])
    sentences = [s for key in ("summary", "supporting", "contradicting", "uncertainty") for s in c["llm_sections"][key]]
    assert sentences
    for s in sentences:
        assert s["claim_refs"], s
        for ref in s["claim_refs"]:
            assert ref["local_id"] in claim_by_local and ref["evidence_ids"] and set(ref["evidence_ids"]) <= evidence_ids
            assert ref["claim_id"] == claim_by_local[ref["local_id"]]["claim_id"]
        assert "[[" not in s["text"]
    # the traceability appendix is the database view: every claim resolves to an evidence row, a source and a conclusion
    rows = [t for t in c["traceability"] if t["row_type"] == "claim_link"]
    assert {t["claim_id"] for t in rows} == {x["claim_id"] for x in c["claims"]}
    assert all(t["evidence_id"] in evidence_ids and t["source_name"] and t["conclusion_ref"] for t in rows)
    assert {e["status"] for e in c["evidence_table"]} == {"active"} and b.synthesis_id == syn.id
    # the decision brief shows the agent review and its findings and the human responses
    assert c["review"]["agent_review"]["verdict"] == "ready" and c["review"]["agent_review"]["model"].startswith("stub:")
    assert "No automated adversarial review" not in c["banners"]


def test_b4_the_brief_uses_the_synthesis_the_validating_review_covered(session, seed, flow):
    d, a, ctx, syn = validated_decision(session, seed, flow)
    payload, _ = payload_mod.build_input(session, d, a)
    # a newer synthesis exists but was not reviewed: the stage rule blocks a new synthesis, so insert one directly (service-level proof)
    from app.repositories import syntheses as syn_repo
    run_id = syn.agent_run_id
    newer = syn_repo.add_synthesis(session, assessment_id=a.id, version=2, agent_run_id=run_id, status="succeeded", input_sha256="n",
                                   output_sha256="n", output=syn.output, validator_report={}, claims_dropped=0, is_synthetic=True)
    with pytest.raises(StateConflict, match="not covered"):
        BriefService(ctx).create(seed.pm, a.id, "decision_brief") if False else BriefService(ctx5(session, None)).create(seed.pm, a.id, "decision_brief")
    assert newer.version == 2 and payload
