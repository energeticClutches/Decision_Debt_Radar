"""Day-6 read models N1 to N6 (docs/day-6-implementation-brief.md section 3): happy path, 404s, permissions, provenance and the N5 stale
reason for every stale trigger. Served by the product replay client; nothing here reaches a network."""

from __future__ import annotations

import uuid

import pytest
import copy
from dataclasses import replace

from day4_support import clone_decision, no_run, pipeline
from day6_support import H, ok, replay_http, run_to_challenged  # noqa: F401
from flow import Flow
from sqlalchemy import text

from app.core.params import get_tenant_config

ROLES = ("pm", "ba", "analyst", "leader", "executive", "bizops")
MISSING = "00000000-0000-0000-0000-000000000000"


def actors(seed):
    return [seed.pm, seed.ba, seed.analyst, seed.leader, seed.executive, seed.bizops]


# ================================================================ N1, N3, N6 and provenance on a full AI Coach path
def test_n1_n3_n6_and_provenance_on_the_ai_coach_path(session, seed, replay_http):
    http, _ = replay_http
    run = run_to_challenged(http, seed, "ai_coach", session)
    aid, did = run["assessment_id"], run["decision_id"]

    # N1: the reviews, with findings and the provenance of the agent run
    reviews = ok(http.get(f"/assessments/{aid}/reviews", headers=H(seed.bizops)))
    assert [r["reviewer_type"] for r in reviews] == ["agent"]
    agent = reviews[0]
    assert agent["verdict"] == "needs_rework" and agent["provenance"] == "stub_not_model_output"
    assert agent["model"] == "stub:handauthored_review_v1" and agent["model_fallback"] is False and agent["synthesis_id"] and agent["agent_run_id"]
    assert set(agent["findings"][0]) == {"category", "severity", "severity_model", "source", "target_type", "target_id", "target_local_id",
                                         "rationale", "evidence_ids", "notes"}
    c7 = next(f for f in agent["findings"] if f["category"] == "causal_from_observational")
    assert (c7["severity"], c7["severity_model"], c7["source"], c7["target_local_id"]) == ("blocking", "warning", "model", "c7")
    assert {f["source"] for f in agent["findings"]} <= {"model", "code"}

    # a human review joins the list, ordered by created_at, without findings and without provenance
    ok(http.post(f"/assessments/{aid}/reviews", headers=H(seed.pm), json={"verdict": "ready", "human_response": "Reviewed by hand."}), 201)
    reviews = ok(http.get(f"/assessments/{aid}/reviews", headers=H(seed.pm)))
    assert [r["reviewer_type"] for r in reviews] == ["agent", "human"]
    assert reviews[1]["findings"] == [] and reviews[1]["provenance"] is None and reviews[1]["human_response"] == "Reviewed by hand."
    assert reviews[0]["created_at"] <= reviews[1]["created_at"]

    # provenance on the synthesis and on the customer-evidence classification summary
    syn = ok(http.get(f"/assessments/{aid}/syntheses", headers=H(seed.pm)))[0]
    assert syn["provenance"] == "stub_not_model_output" and syn["model"] == "stub:handauthored_synthesis_v1"
    counts = ok(http.get(f"/decisions/{did}/customer-evidence", headers=H(seed.pm)))
    assert {c["provenance"] for c in counts["classification_counts"]} == {"stub_not_model_output"}
    assert {c["model"] for c in counts["classification_counts"]} == {"stub:keyword_rules_v1"}
    assert all(i["classification_counts"]["provenance"] == "stub_not_model_output" for i in counts["items"])

    # N3: briefs (none, then one)
    assert ok(http.get(f"/assessments/{aid}/briefs", headers=H(seed.pm))) == []
    ok(http.post(f"/decisions/{did}/validate", headers=H(seed.pm)))
    brief = ok(http.post(f"/assessments/{aid}/briefs", headers=H(seed.pm), json={"kind": "decision_brief"}), 201)
    listed = ok(http.get(f"/assessments/{aid}/briefs", headers=H(seed.executive)))
    assert listed == [{"id": brief["id"], "kind": "decision_brief", "version": 1, "label": "Validated Decision Brief",
                       "synthesis_id": brief["synthesis_id"], "created_at": listed[0]["created_at"]}]
    assert "content" not in listed[0]

    # N6: the evidence register carries the source, the reliability tier and the freshness of the view
    ev = ok(http.get(f"/decisions/{did}/evidence", headers=H(seed.pm)))
    active = [e for e in ev if e["status"] == "active"]
    assert active and all(e["source_name"] and e["reliability_tier"] in (1, 2, 3, 4) for e in ev)
    fresh = active[0]["freshness"]
    assert set(fresh) == {"age_days", "half_life_days", "within_half_life", "as_of"} and fresh["as_of"] == "2026-10-01"
    row = session.execute(text("SELECT age_days, half_life_days FROM v_evidence_freshness WHERE evidence_id = :e"), {"e": active[0]["id"]}).one()
    session.execute(text("SELECT set_config('ddr.as_of', '2026-10-01', true)"))
    row = session.execute(text("SELECT age_days, half_life_days, within_half_life FROM v_evidence_freshness WHERE evidence_id = :e"),
                          {"e": active[0]["id"]}).one()
    assert (fresh["age_days"], fresh["half_life_days"], fresh["within_half_life"]) == tuple(row)
    session.execute(text("SELECT set_config('ddr.as_of', '', true)"))

    # N2: no record yet (404), then the latest record
    assert http.get(f"/decisions/{did}/decision-record", headers=H(seed.executive)).status_code == 404
    rec = ok(http.post(f"/decisions/{did}/decision-record", headers=H(seed.executive),
                       json={"outcome": "approve_conditional", "rationale": "Reviewed.", "acknowledged_risk": True}), 201)
    got = ok(http.get(f"/decisions/{did}/decision-record", headers=H(seed.bizops)))
    assert got == {**rec} and got["lifecycle_stage"] == "decided"


def test_n1_n2_n3_n4_n6_404s_and_401s(session, seed, replay_http):
    http, _ = replay_http
    d = seed.decisions["ai_coach"]
    session.refresh(d)
    for path in (f"/assessments/{MISSING}/reviews", f"/assessments/{MISSING}/briefs", f"/assessments/{MISSING}/traceability",
                 "/assessments/not-a-uuid/reviews", "/assessments/not-a-uuid/briefs", "/assessments/not-a-uuid/traceability",
                 f"/decisions/{MISSING}/decision-record", "/decisions/not-a-uuid/decision-record", f"/decisions/{d.id}/decision-record"):
        assert http.get(path, headers=H(seed.pm)).status_code == 404, path
    for path in (f"/assessments/{MISSING}/reviews", f"/assessments/{MISSING}/briefs", f"/assessments/{MISSING}/traceability",
                 f"/decisions/{d.id}/decision-record", "/metrics", f"/decisions/{d.id}/evidence", f"/decisions/{d.id}"):
        assert http.get(path).status_code == 401, path
        assert http.get(path, headers={"X-Demo-User": MISSING}).status_code == 401, path


def test_n1_n2_n3_n4_n6_are_open_to_every_demo_persona_like_the_other_reads(session, seed, replay_http):
    http, _ = replay_http
    run = run_to_challenged(http, seed, "community", session)
    aid, did = run["assessment_id"], run["decision_id"]
    ok(http.post(f"/assessments/{aid}/reviews", headers=H(seed.pm), json={"verdict": "ready", "human_response": "ok"}), 201)
    for actor in actors(seed):
        for path in (f"/assessments/{aid}/reviews", f"/assessments/{aid}/briefs", f"/assessments/{aid}/traceability", "/metrics",
                     f"/decisions/{did}", f"/decisions/{did}/evidence", "/decisions"):
            assert http.get(path, headers=H(actor)).status_code == 200, (actor.role, path)


# ================================================================ N6 metrics
def test_n6_metrics_list_is_read_only_and_complete(session, seed, replay_http):
    http, _ = replay_http
    metrics = ok(http.get("/metrics", headers=H(seed.pm)))
    names = {m["name"] for m in metrics}
    assert {"d90_retention", "paid_conversion_rate"} <= names
    d90 = next(m for m in metrics if m["name"] == "d90_retention")
    assert set(d90) == {"id", "name", "definition", "unit", "grain"} and d90["definition"] and d90["unit"]
    assert d90["id"] == seed.metric_d90
    assert http.post("/metrics", headers=H(seed.pm), json={}).status_code == 405


# ================================================================ N4 traceability equals the view
def test_n4_traceability_rows_equal_the_view_including_gap_rows(session, seed, replay_http):
    http, _ = replay_http
    run = run_to_challenged(http, seed, "onboarding", session)
    aid = run["assessment_id"]
    rows = ok(http.get(f"/assessments/{aid}/traceability", headers=H(seed.bizops)))
    view = session.execute(text("SELECT * FROM v_traceability_matrix WHERE assessment_id = :a"), {"a": aid}).mappings().all()
    assert len(rows) == len(view) and len(rows) > 0
    gaps = [r for r in rows if r["row_type"] == "gap"]
    assert gaps and len(gaps) == sum(1 for v in view if v["row_type"] == "gap")
    assert all(r["claim_id"] is None and r["claim_text"].startswith("GAP: no ") and r["conclusion_ref"] == "D2 Evidence Coverage" for r in gaps)
    columns = set(view[0].keys())
    assert columns <= set(rows[0]) and set(rows[0]) - columns == {"claim_local_id", "synthesis_id"}
    key = lambda r: (r["row_type"], str(r["claim_id"]), str(r["evidence_id"]), r["claim_text"])           # noqa: E731
    expected = sorted(({k: (None if v is None else (str(v) if hasattr(v, "hex") or hasattr(v, "isoformat") else v)) for k, v in dict(v).items()}
                       for v in view), key=key)
    got = sorted(({k: r[k] for k in columns} for r in rows), key=key)
    assert got == expected
    claim_rows = [r for r in rows if r["row_type"] == "claim_link"]
    assert claim_rows and all(r["claim_local_id"] and r["synthesis_id"] and r["evidence_status"] == "active" for r in claim_rows)


# ================================================================ N5
def stale_view(http, seed, did):
    return ok(http.get(f"/decisions/{did}", headers=H(seed.pm)))


def test_n5_a_current_decision_has_no_stale_fields_and_counts_pending_approvals(session, seed, replay_http):
    http, _ = replay_http
    d = seed.decisions["ai_coach"]
    session.refresh(d)
    ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    view = stale_view(http, seed, d.id)
    assert view["assessment_stale"] is False and view["stale_reason"] is None and view["stale_at"] is None
    assert view["pending_approvals"] == 3
    listed = {x["id"]: x for x in ok(http.get("/decisions", headers=H(seed.pm)))}
    assert listed[str(d.id)]["pending_approvals"] == 3 and listed[str(d.id)]["stale_reason"] is None
    others = [x for k, x in listed.items() if k != str(d.id)]
    assert all(x["pending_approvals"] == 0 and x["stale_reason"] is None for x in others)


def test_n5_stale_reason_after_a_customer_approval(session, seed, replay_http):
    http, _ = replay_http
    d = seed.decisions["community"]
    session.refresh(d)
    ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    items = ok(http.get(f"/decisions/{d.id}/customer-evidence", headers=H(seed.ba)))["items"]
    ok(http.patch(f"/evidence/{items[0]['evidence']['id']}/approval", headers=H(seed.ba), json={"action": "approve", "note": "ok"}))
    view = stale_view(http, seed, d.id)
    assert view["assessment_stale"] is True and view["lifecycle_stage"] == "evidence_gathered"
    assert view["stale_reason"] == "customer evidence approved after the assessment" and view["stale_at"]
    assert view["pending_approvals"] == 2
    # a rejection gives its own wording; the latest stale event wins after a re-run and a new staleness
    ok(http.patch(f"/evidence/{items[1]['evidence']['id']}/approval", headers=H(seed.ba), json={"action": "reject", "note": "no"}))
    assert stale_view(http, seed, d.id)["stale_reason"] == "customer evidence approved after the assessment"      # already stale: no second event
    ok(http.patch(f"/evidence/{items[2]['evidence']['id']}/approval", headers=H(seed.ba), json={"action": "approve", "note": "ok"}))
    ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    fresh = stale_view(http, seed, d.id)
    assert fresh["assessment_stale"] is False and fresh["stale_reason"] is None and fresh["stale_at"] is None


def test_n5_stale_reason_after_evidence_dq_canvas_and_defer(session, seed, replay_http):
    http, _ = replay_http
    flow = Flow(session, seed)

    def stale_of(decision):
        v = stale_view(http, seed, decision.id)
        assert v["assessment_stale"] is True and v["stale_at"]
        return v["stale_reason"]

    # evidence added after the assessment
    d, _a = flow.scored()
    flow.add_evidence(d, "behavioral")
    assert stale_of(d) == "evidence added after the assessment"

    # evidence changed after the assessment
    d, _a = flow.scored()
    ev = flow.evidence.list(seed.pm, d.id)[0]
    flow.evidence.update(seed.analyst, d.id, ev.id, {"summary": "changed summary"})
    assert stale_of(d) == "evidence changed after the assessment"

    # a data-quality status change by a person
    d, a = flow.scored()
    check = flow.insert_dq_check(a, seed.ds["FitConnect product events (fc_.events)"].id, severity="warn", status="open")
    flow.dq.set_status(seed.analyst, check, "accepted")
    assert stale_of(d) == "data-quality check accepted"

    # a canvas edit after the first assessment
    d, _a = flow.scored()
    flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "decrease"})
    assert stale_of(d) == "canvas edited after the first assessment"

    # a defer decision record returns the validated decision to evidence gathering
    d, a = flow.scored()
    flow.to_validated(d, a)
    flow.records.record(seed.executive, d.id, "defer", "Wait for more evidence.", True)
    assert stale_view(http, seed, d.id)["lifecycle_stage"] == "evidence_gathered"
    assert stale_of(d) == "the decision was deferred by a human record: it returned to evidence gathering"


def test_n5_stale_reason_after_rematerialisation(session, seed, replay_http):
    """Generated evidence re-written by a changed analysis parameter marks an assessed decision stale (a system event)."""
    http, _ = replay_http
    flow = Flow(session, seed)
    d = clone_decision(flow, seed, "pricing")
    assert pipeline(session).run(seed.analyst, d.id).assessment.state == "scored"
    assert stale_view(http, seed, d.id)["assessment_stale"] is False
    tenant = get_tenant_config()
    data = copy.deepcopy(dict(tenant.data))
    data["metrics"]["paid_conversion_rate"]["materiality"] = 0.05                    # a changed analysis parameter: new identities
    svc, ids = pipeline(session, tenant=replace(tenant, data=data, content_hash="f" * 64)), []
    svc.stage_dq(d, no_run())
    svc.stage_quant(d, no_run(), ids)
    svc.stage_experiment(d, no_run(), ids)
    assert svc.materializer.apply(d, ids).superseded == 3
    v = stale_view(http, seed, d.id)
    assert v["assessment_stale"] is True and v["stale_reason"] == "evidence generated or changed after the assessment"


def test_n5_the_stale_reason_is_the_latest_stale_row_and_cleared_when_current(session, seed, replay_http):
    http, _ = replay_http
    flow = Flow(session, seed)
    d, a = flow.scored()
    flow.add_evidence(d, "behavioral")
    assert stale_view(http, seed, d.id)["stale_reason"] == "evidence added after the assessment"
    flow.assessments.run(seed.analyst, d.id)                                    # a new assessment clears the flag
    v = stale_view(http, seed, d.id)
    assert v["assessment_stale"] is False and v["stale_reason"] is None
    flow.decisions.edit_canvas(seed.pm, d.id, {"expected_direction": "decrease"})
    assert stale_view(http, seed, d.id)["stale_reason"] == "canvas edited after the first assessment"       # the newer event, not the old one
    assert uuid.UUID(v["id"]) == d.id
