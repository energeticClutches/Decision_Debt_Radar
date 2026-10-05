"""Customer evidence, Stage 3 (tests C1 to C7). The LLM is the deterministic keyword-rule stub: it measures the pipeline, not a model."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date

import pytest
from day4_support import clone_decision
from day5_support import (
    Scenario,
    approve_pending,
    by_theme,
    ctx5,
    customer_items,
    run_stage3,
    with_customer_params,
)
from flow import Flow
from replay import ReplayClient
from sqlalchemy import select
from stub_classifier import StubClassifierClient

from app.analytics.config import TenantConfig
from app.core.params import get_tenant_config
from app.customer.aggregate import ClassifiedRow, aggregate, customer_grade, evidence_identity
from app.customer.schema import ClassificationSchemaError, parse_classifications
from app.db import models as m
from app.domain.errors import StateConflict
from app.repositories.evidence_facts import build_facts, evidence_fingerprint

TAX = get_tenant_config().customer_taxonomy("ai_coach")
THEMES = list(TAX.theme_names)


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


# ================================================================ C1
def good(refs=("t1", "t2")):
    return {"classifications": [{"text_ref": r, "theme": "coach_helpful", "relevance": "direct"} for r in refs]}


def test_c1_a_valid_classification_parses_and_null_themes_are_allowed():
    import json
    raw = json.dumps({"classifications": [{"text_ref": "t1", "theme": "coach_helpful", "relevance": "direct"},
                                           {"text_ref": "t2", "theme": None, "relevance": "not_relevant"}]})
    assert parse_classifications(raw, themes=THEMES, text_refs=["t1", "t2"]) == {"t1": ("coach_helpful", "direct"), "t2": (None, "not_relevant")}


@pytest.mark.parametrize("mutate", [
    lambda d: d["classifications"][0].update(theme="invented_theme"),               # out-of-taxonomy theme
    lambda d: d["classifications"][0].update(text_ref="t99"),                        # unknown ref
    lambda d: d["classifications"].pop(),                                            # missing ref
    lambda d: d["classifications"].append(dict(d["classifications"][0])),            # duplicate ref
    lambda d: d["classifications"][0].update(stance="supports"),                     # the model may not choose a stance
    lambda d: d["classifications"][0].update(relevance="very"),
    lambda d: d.update(summary="x"),
])
def test_c1_any_schema_violation_fails_the_whole_batch(mutate):
    import json
    data = good()
    mutate(data)
    with pytest.raises(ClassificationSchemaError):
        parse_classifications(json.dumps(data), themes=THEMES, text_refs=["t1", "t2"])


def test_c1_malformed_json_fails_and_a_failing_batch_creates_no_evidence(session, seed, flow):
    from replay import ScriptedClient
    d = clone_decision(flow, seed, "ai_coach")
    out, status = run_stage3(ctx5(session, ScriptedClient(["not json"])), seed.analyst, d)
    assert status == "partial" and out["outcome"] == "llm_failed" and out["error_class"] == "schema_error"
    assert customer_items(session, d) == []
    runs = session.scalars(select(m.AgentRun).where(m.AgentRun.decision_id == d.id, m.AgentRun.purpose == "classify")).all()
    assert len(runs) == 1 and runs[0].status == "failed" and runs[0].error_class == "schema_error" and runs[0].model == "stub:scripted"


def test_c1_an_out_of_taxonomy_theme_from_the_model_fails_the_stage(session, seed, flow):
    from replay import ScriptedClient
    d = clone_decision(flow, seed, "ai_coach")
    bad = {"classifications": [{"text_ref": f"t{i}", "theme": "price_too_high", "relevance": "direct"} for i in range(1, 51)]}
    out, status = run_stage3(ctx5(session, ScriptedClient([bad])), seed.analyst, d)
    assert status == "partial" and out["error_class"] == "schema_error" and customer_items(session, d) == []


# ================================================================ C2
def test_c2_the_cache_prevents_a_second_llm_call_within_and_across_decisions(session, seed, flow):
    stub = StubClassifierClient()
    ctx = ctx5(session, stub)
    d1 = clone_decision(flow, seed, "ai_coach")
    out1, _ = run_stage3(ctx, seed.analyst, d1)
    assert out1["distinct_texts"] == 195 and stub.call_count == 4 == out1["llm_calls"] and out1["cache_hits"] == 0
    assert sum(len(c.input_obj["texts"]) for c in stub.calls) == 195 and len(set(stub.texts_seen)) == 195
    out2, _ = run_stage3(ctx, seed.analyst, d1)                                        # same decision again
    assert stub.call_count == 4 and out2["llm_calls"] == 0 and out2["cache_hits"] == 195 and out2["classifications_inserted"] == 0
    d2 = clone_decision(flow, seed, "ai_coach")                                        # another decision, same taxonomy version
    out3, _ = run_stage3(ctx, seed.analyst, d2)
    assert stub.call_count == 4 and out3["llm_calls"] == 0 and out3["classifications_inserted"] == 6083
    d3 = clone_decision(flow, seed, "pricing")                                         # another taxonomy: the cache does not apply
    run_stage3(ctx, seed.analyst, d3)
    assert stub.call_count == 8
    rows = session.scalars(select(m.LlmClassification).where(m.LlmClassification.decision_id == d1.id)).all()
    assert len(rows) == 6083 and {r.model for r in rows} == {"stub:keyword_rules_v1"} and {r.prompt_version for r in rows} == {"v0.1"}
    assert len({r.prompt_sha256 for r in rows}) == 1 and all(r.is_synthetic for r in rows)


def test_c2_classification_rows_are_insert_only(session, seed, flow):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    d = clone_decision(flow, seed, "onboarding")
    run_stage3(ctx5(session, StubClassifierClient()), seed.analyst, d)
    for sql in ("UPDATE llm_classifications SET theme = NULL WHERE decision_id = :d", "DELETE FROM llm_classifications WHERE decision_id = :d"):
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text(sql), {"d": d.id})


# ================================================================ C3
def row(i, theme, relevance="direct", source="app_review", segment="a", day=1, text="t"):
    return ClassifiedRow(i, f"{text}{i % 7}", f"{text}{i % 7}", date(2026, 1, day), source, segment, theme, relevance)


def test_c3_one_item_per_theme_at_or_above_the_threshold_and_gaps_below_it():
    rows = [row(i, "coach_helpful") for i in range(30)] + [row(100 + i, "coach_generic_or_wrong") for i in range(29)]
    rows += [row(200 + i, "coach_indifferent", relevance="not_relevant") for i in range(80)]          # not relevant: not a mention
    agg = aggregate(rows, TAX, min_theme_mentions=30, grade_c_min_mentions=100, grade_c_min_source_types=2, sample_quotes_per_insight=5)
    assert [t.theme for t in agg.themes] == ["coach_helpful"]
    assert agg.themes[0].mentions == 30 and agg.themes[0].stance == "supports"
    assert {g.theme: g.mentions for g in agg.gaps} == {"coach_generic_or_wrong": 29, "coach_indifferent": 0}


def test_c3_aggregation_is_deterministic_and_computes_the_observed_values():
    rows = [row(i, "coach_helpful", relevance="direct" if i % 4 else "adjacent", source=("survey" if i % 2 else "app_review"),
                segment=("x" if i % 3 else None), day=1 + i % 5) for i in range(120)]
    kwargs = dict(min_theme_mentions=30, grade_c_min_mentions=100, grade_c_min_source_types=2, sample_quotes_per_insight=5)
    a = aggregate(rows, TAX, **kwargs)
    b = aggregate(list(reversed(rows)), TAX, **kwargs)
    assert a == b
    t = a.themes[0]
    assert t.mentions == 120 and t.direct == 90 and t.relevance_observed == 0.75 and t.source_types == ("app_review", "survey")
    assert t.first_mention == date(2026, 1, 1) and t.last_mention == date(2026, 1, 5) and t.segment_counts == {"unknown": 40, "x": 80}
    hashes = [q["text_sha256"] for q in t.sample_quotes]
    assert hashes == sorted(hashes) and len(hashes) == 5 and t.sentiment == "positive"            # lowest hash first, at most five


def test_c3_the_pipeline_makes_one_item_per_theme_and_reports_gaps_below_the_threshold(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    ctx = with_customer_params(ctx5(session, StubClassifierClient()), min_theme_mentions=200)
    out, status = run_stage3(ctx, seed.analyst, d)
    assert status == "succeeded" and [t["theme"] for t in out["themes"]] == ["coach_helpful"]
    assert {g["theme"]: g["relevant_mentions"] for g in out["gaps"]} == {"coach_generic_or_wrong": 113, "coach_indifferent": 128}
    assert all(g["min_theme_mentions"] == 200 for g in out["gaps"])
    assert len(customer_items(session, d)) == 1
    out2, _ = run_stage3(ctx, seed.analyst, d)                                                  # idempotent: same identity, no change
    assert [t["action"] for t in out2["themes"]] == ["unchanged"] and len(customer_items(session, d)) == 1


def test_c3_the_proposed_item_carries_the_observed_values_and_the_traceable_fields(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    out, _ = run_stage3(ctx5(session, StubClassifierClient()), seed.analyst, d)
    items = by_theme(session, d)
    assert set(items) == {"price_too_high", "worth_the_price"} and all(len(v) == 1 for v in items.values())
    ev = items["price_too_high"][0]
    ins = session.get(m.CustomerInsight, ev.insight_id)
    assert (ev.status, ev.evidence_type, ev.created_by, ev.metric_id, ev.analysis_id, ev.effect_size) == ("proposed", "customer", "agent", None, None, None)
    assert ev.n_sample == ins.quote_count == 1126 and ev.observed_end == ins.last_mention_date and ev.observed_end <= date(2026, 10, 1)
    assert float(ins.relevance_observed) == 1.0 and ins.source_types == ["app_review", "survey"] and ins.segment_counts
    assert len(ins.sample_quotes) == 5 and ins.taxonomy_version.startswith("fitconnect_pricing_taxonomy_v0.1#") and ins.sentiment == "negative"
    assert "not used by DDI v0.1" in ev.summary and ev.is_synthetic and ins.is_synthetic
    src = session.get(m.EvidenceSource, ev.evidence_source_id)
    assert src.ref == "fc_.feedback" and src.reliability_tier == 3                              # tier from the feedback data source
    prompt_sha = session.scalars(select(m.LlmClassification.prompt_sha256).where(m.LlmClassification.decision_id == d.id)).first()
    assert ev.analysis_identity == evidence_identity(str(d.id), "price_too_high", ins.taxonomy_version, "v0.1", "stub:keyword_rules_v1")
    assert prompt_sha


# ================================================================ C4
def test_c4_stance_comes_only_from_the_human_authored_map():
    for scenario, expected in {"pricing": {"price_too_high": "contradicts", "worth_the_price": "supports"}}.items():
        tax = get_tenant_config().customer_taxonomy(scenario)
        rows = [row(i, "price_too_high") for i in range(40)] + [row(100 + i, "worth_the_price") for i in range(40)]
        agg = aggregate(rows, tax, min_theme_mentions=30, grade_c_min_mentions=100, grade_c_min_source_types=2, sample_quotes_per_insight=5)
        assert {t.theme: t.stance for t in agg.themes} == expected


def altered_tenant(stance_for_helpful: str) -> TenantConfig:
    base = get_tenant_config()
    raw = copy.deepcopy(dict(base.data))
    for t in raw["customer_taxonomy"]["ai_coach"]["themes"]:
        if t["theme"] == "coach_helpful":
            t["stance"] = stance_for_helpful
    return TenantConfig.from_mapping(raw, "altered-" + stance_for_helpful)


def test_c4_a_changed_map_changes_the_identity_and_the_old_item_is_superseded(session, seed, flow):
    d = clone_decision(flow, seed, "ai_coach")
    ctx = ctx5(session, StubClassifierClient())
    run_stage3(ctx, seed.analyst, d)
    old = by_theme(session, d)["coach_helpful"][0]
    approve_pending(session, ctx, seed.ba, d)
    session.refresh(old)
    assert old.status == "active" and old.stance == "supports"
    ctx2 = replace(ctx, tenant=altered_tenant("neutral"))
    out, _ = run_stage3(ctx2, seed.analyst, d)
    rows = by_theme(session, d)["coach_helpful"]
    session.refresh(old)
    new = next(e for e in rows if e.id != old.id)
    assert old.status == "superseded" and old.superseded_by == new.id and old.superseded_at is not None
    assert new.status == "proposed" and new.stance == "neutral" and new.analysis_identity != old.analysis_identity
    assert any(t["theme"] == "coach_helpful" and t["action"] == "proposed" and t.get("superseded_active") for t in out["themes"])
    # the other themes keep their identity only if their map entry is unchanged: all themes share one taxonomy id, so all are new
    assert all(len(v) == 2 for v in by_theme(session, d).values())


def test_c4_the_taxonomy_id_changes_with_any_stance_or_description_change():
    a = get_tenant_config().customer_taxonomy("ai_coach")
    b = altered_tenant("contradicts").customer_taxonomy("ai_coach")
    assert a.taxonomy_version == b.taxonomy_version and a.taxonomy_id != b.taxonomy_id


# ================================================================ C5
@pytest.mark.parametrize("mentions,types,expected", [
    (99, 2, "D"), (100, 1, "D"), (100, 2, "C"), (100, 3, "C"), (30, 2, "D"), (5000, 1, "D"), (5000, 3, "C"), (0, 0, "D"), (101, 2, "C")])
def test_c5_grade_truth_table(mentions, types, expected):
    assert customer_grade(mentions, types, grade_c_min_mentions=100, grade_c_min_source_types=2) == expected


def test_c5_the_grade_is_never_a_or_b():
    grades = {customer_grade(n, k, grade_c_min_mentions=100, grade_c_min_source_types=2) for n in range(0, 2000, 7) for k in range(0, 6)}
    assert grades == {"C", "D"}


# ================================================================ C6
def test_c6_proposed_items_are_excluded_from_the_facts_and_the_fingerprint_then_approval_makes_them_active_and_stale(session, seed, flow):
    d = flow.gathered(scenario_key=None) if False else clone_decision(flow, seed, "pricing")
    ctx = ctx5(session, StubClassifierClient())
    before_fp, before_items = evidence_fingerprint(session, d.id), len(build_facts(session, d.id).items)
    run_stage3(ctx, seed.analyst, d)
    assert len(customer_items(session, d)) == 2 and all(e.status == "proposed" for e in customer_items(session, d))
    assert evidence_fingerprint(session, d.id) == before_fp and len(build_facts(session, d.id).items) == before_items
    assert not any(i.evidence_type == "customer" for i in build_facts(session, d.id).items)
    # assess (the pipeline has no customer item in the facts), then approve: stale and back to evidence_gathered
    flow.add_evidence(d, "behavioral", "financial")
    assessment = flow.assessments.run(seed.analyst, d.id)
    assert flow.stage(d) == "assessed" and assessment.state in ("scored", "insufficient_evidence")
    approved = customer_items(session, d)[0]
    from app.services import CustomerEvidenceService
    ev = CustomerEvidenceService(ctx).set_approval(seed.ba, approved.id, "approve", "ok")
    assert ev.status == "active" and ev.approved_by is not None and ev.approved_at is not None and ev.approval_note == "ok"
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    assert evidence_fingerprint(session, d.id) != before_fp
    assert [i.evidence_type for i in build_facts(session, d.id).items].count("customer") == 1
    actions = flow.audit_actions(d)
    assert "evidence.proposed" in actions and "evidence.approved" in actions and "assessment.stale" in actions


def test_c6_a_rejection_is_permanent_for_that_identity_and_the_item_stays_out_of_the_facts(session, seed, flow):
    from app.services import CustomerEvidenceService
    d = clone_decision(flow, seed, "pricing")
    ctx = ctx5(session, StubClassifierClient())
    run_stage3(ctx, seed.analyst, d)
    target = by_theme(session, d)["price_too_high"][0]
    svc = CustomerEvidenceService(ctx)
    ev = svc.set_approval(seed.analyst, target.id, "reject", "not representative")
    assert ev.status == "rejected" and ev.approved_by is not None
    out, _ = run_stage3(ctx, seed.analyst, d)
    action = {t["theme"]: t["action"] for t in out["themes"]}
    assert action["price_too_high"] == "rejected_not_reproposed" and action["worth_the_price"] == "unchanged"
    assert len(by_theme(session, d)["price_too_high"]) == 1
    assert not any(i.evidence_type == "customer" for i in build_facts(session, d.id).items)
    with pytest.raises(StateConflict):                                                        # only proposed items can be actioned
        svc.set_approval(seed.analyst, target.id, "approve", None)


def test_c6_approval_permissions_and_state_rules(session, seed, flow):
    from app.domain.errors import Forbidden, InvalidInput, NotFound
    from app.services import CustomerEvidenceService
    d = clone_decision(flow, seed, "pricing")
    ctx = ctx5(session, StubClassifierClient())
    run_stage3(ctx, seed.analyst, d)
    ev = customer_items(session, d)[0]
    svc = CustomerEvidenceService(ctx)
    for actor in (seed.pm, seed.leader, seed.executive, seed.bizops):
        with pytest.raises(Forbidden):
            svc.set_approval(actor, ev.id, "approve", None)
    with pytest.raises(InvalidInput):
        svc.set_approval(seed.ba, ev.id, "maybe", None)
    with pytest.raises(NotFound):
        svc.set_approval(seed.ba, "not-a-uuid", "approve", None)
    assert svc.set_approval(seed.ba, ev.id, "approve", None).status == "active"
    # the database refuses an active agent customer item without a human approval
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    other = customer_items(session, d)[1]
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.execute(text("UPDATE evidence SET status = 'active' WHERE id = :e"), {"e": other.id})


# ================================================================ C7
def test_c7_customer_evidence_never_changes_d4_or_the_experiment_fields_pricing(session, seed):
    sc = Scenario(session, seed, "pricing").run()
    first, second = sc.first.assessment, sc.second.assessment
    d4_1 = first.dimension_scores["dimensions"]["D4"]
    d4_2 = second.dimension_scores["dimensions"]["D4"]
    # the D4 SCORE and its inputs are a function of the experiment facts only. (Its weighted contribution is normalised over the other
    # dimensions by the frozen aggregate, so it may move when D5 and the penalties change: that is the engine, not D4.)
    keys = ("score", "inputs", "defaulted_inputs", "explanation", "details", "applicable", "weight")
    assert {k: d4_1[k] for k in keys} == {k: d4_2[k] for k in keys}, "D4 changed when customer evidence was approved"
    exp_rows = session.scalars(select(m.Evidence).where(m.Evidence.decision_id == sc.decision.id, m.Evidence.evidence_type == "experiment")).all()
    assert len(exp_rows) == 1 and exp_rows[0].status == "active"
    facts = build_facts(session, sc.decision.id)
    assert len(facts.experiments) == 1 and facts.experiments[0].design == "rct" and facts.experiments[0].srm_flag is False
    result_rows = session.scalars(select(m.ExperimentResult).join(m.Experiment, m.Experiment.id == m.ExperimentResult.experiment_id)
                                  .where(m.Experiment.decision_id == sc.decision.id)).all()
    assert result_rows and all(r.is_synthetic for r in result_rows)
    # the customer items are separate evidence and carry no experiment link
    assert all(e.experiment_id is None for e in customer_items(session, sc.decision))
    assert first.state == second.state == "scored"
    assert isinstance(sc.client, ReplayClient)
