"""The deterministic pipeline on the seeded decisions (T-PIPE-1, T-PIPE-2, T-PIPE-3) and the Day-4 API.
Assertions are about states and inputs, never about DDI bands (D4-24)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from day4_support import TODAY, assessment_payload, clone_decision, normalized, pipeline
from fastapi.testclient import TestClient
from flow import Flow, evidence_payload
from sqlalchemy import select, text

from app.analytics import store as analysis_store
from app.core import deps
from app.core.clock import FixedClock
from app.db import models as m
from app.domain.errors import Forbidden, StateConflict
from app.main import app
from app.repositories import agent_runs as runs_repo
from app.repositories import analysis as analysis_repo
from app.repositories import dq as dq_repo
from app.repositories.evidence_facts import build_facts
from app.services import AssessmentService, PipelineService


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


@pytest.fixture()
def client(session):
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def H(actor):
    return {"X-Demo-User": actor.id}


def run_seeded(session, seed, scenario):
    d = seed.decisions[scenario]
    session.refresh(d)
    result = pipeline(session).run(seed.analyst, d.id)
    return d, result


def codes(assessment):
    return [r["code"] for r in assessment.blocking_reasons]


def evidence(session, d):
    return list(session.scalars(select(m.Evidence).where(m.Evidence.decision_id == d.id).order_by(m.Evidence.evidence_type, m.Evidence.id)))


def stage_names(result):
    return [s["stage"] for s in result.stages]


# ================================================================ T-PIPE-1
def test_pipe_1_onboarding_is_insufficient_with_an_open_critical_dq_reason_and_no_number_anywhere(session, seed, flow):
    d, result = run_seeded(session, seed, "onboarding")
    a = result.assessment
    assert result.partial is False and a.state == "insufficient_evidence"
    assert codes(a) == ["min_items", "min_types", "success_metric_evidence", "open_critical_dq"]
    # no number anywhere: the row, its payloads and the API panel
    assert a.ddi_score is None and a.ddi_band is None and a.penalty_scores == {} and a.sensitivity == {}
    assert a.dimension_scores["dimensions"] == {} and a.dimension_scores["ddi_display"] is None
    assert a.dimension_scores["uncapped_ddi"] is None and a.dimension_scores["support"] is None
    assert "INSUFFICIENT EVIDENCE" in a.narrative and not any(ch.isdigit() for ch in a.narrative.split("Blocking reasons:")[0])
    # the quantitative analyses were skipped as blocked, recorded in agent_runs output
    quant = next(s for s in result.stages if s["stage"] == "quant")
    assert quant["status"] == "partial" and quant["output"]["outcome"] == "blocked"
    assert [x["analysis"] for x in quant["output"]["skipped"]] == ["trend", "funnel"]
    assert all(x["status"] == "skipped (blocked)" and x["reason"] == "open_critical_dq" for x in quant["output"]["skipped"])
    assert analysis_repo.list_for_decision(session, d.id) == [] and evidence(session, d) == []
    # DQ: the three findings, DEF-ONB-002 critical and open
    crit = [c for c in dq_repo.list_for_decision(session, d.id) if c.severity == "critical"]
    assert [(c.target, c.status, c.affects_success_metric) for c in crit] == [("onboarding_completed@android", "open", True)]
    assert a.blocking_reasons[3]["detail"]["dq_check_ids"] == [str(crit[0].id)]
    # the whole run: six stage rows, deterministic agent, no model
    assert stage_names(result) == ["dq", "quant", "customer", "experiment", "materialize", "assessment"]
    runs = runs_repo.list_for_decision(session, d.id)
    assert len(runs) == 6 and {r.model for r in runs} == {None} and {r.prompt_version for r in runs} == {None}
    assert {r.agent_name for r in runs} == {"data_analytics", "orchestrator"} and all(r.latency_ms is not None for r in runs)
    customer = next(s for s in result.stages if s["stage"] == "customer")
    assert customer["output"]["outcome"] == "skipped_day5"
    # the NBE offers the DQ fix as the unblocking action
    recs = {r.action_type: r for r in flow.recs.list_for_assessment(seed.pm, a.id)}
    assert "fix_dq_or_instrumentation" in recs and recs["fix_dq_or_instrumentation"].blockers_resolved >= 1
    # Day 4.1b (NBE v0.2): while the critical DQ issue is open nothing else can claim a blocker, so the fix is the only action
    assert list(recs) == ["fix_dq_or_instrumentation"]
    session.refresh(d)
    assert d.lifecycle_stage == "assessed"


def test_pipe_1_onboarding_after_accepting_def_onb_002_the_dq_reason_is_gone_and_only_type_count_and_metric_link_remain(session, seed, flow):
    d, first = run_seeded(session, seed, "onboarding")
    crit = next(c for c in dq_repo.list_for_decision(session, d.id) if c.severity == "critical")
    flow.dq.set_status(seed.analyst, crit.id, "accepted")
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", True)
    second = pipeline(session).run(seed.analyst, d.id)
    a = second.assessment
    assert a.state == "insufficient_evidence" and a.version == 2
    # Day 4.1 (B2): descriptive evidence is no longer linked to the success metric, so the gate gains success_metric_evidence
    assert codes(a) == ["min_items", "min_types", "success_metric_evidence"]
    assert any(w["code"] == "accepted_critical_dq" for w in a.dimension_scores["warnings"])      # accepted: a warning, not a block
    assert a.ddi_score is None and a.dimension_scores["dimensions"] == {}
    items = evidence(session, d)
    assert [(e.evidence_type, e.stance, e.metric_id) for e in items] == [("behavioral", "neutral", None)] * 2          # Day 4.1: descriptive evidence has NULL metric_id
    assert sorted(session.get(m.AnalysisResult, e.analysis_id).analysis_type for e in items) == ["funnel", "trend"]
    quant = next(s for s in second.stages if s["stage"] == "quant")
    assert quant["status"] == "succeeded" and quant["output"]["skipped"] == []
    # the accepted check stays accepted through the re-run
    assert next(c for c in dq_repo.list_for_decision(session, d.id) if c.id == crit.id).status == "accepted"
    # DQ status of the data is carried to the analysis, so the items are graded D (an accepted critical issue still lowers quality)
    assert {e.strength_grade for e in items} == {"D"}
    assert {session.get(m.AnalysisResult, e.analysis_id).dq_status for e in items} == {"critical"}


def test_pipe_1_onboarding_resolving_removes_the_dq_reason_until_the_defect_is_seen_again(session, seed, flow):
    d, first = run_seeded(session, seed, "onboarding")
    crit = next(c for c in dq_repo.list_for_decision(session, d.id) if c.severity == "critical")
    flow.dq.set_status(seed.analyst, crit.id, "resolved")
    # the Day-3 gate ignores a resolved check: an assessment run on the stored state has no open_critical_dq reason
    direct = AssessmentService(pipeline(session).ctx).run(seed.analyst, d.id)
    assert "open_critical_dq" not in codes(direct)
    assert codes(direct) == ["min_items", "min_types", "success_metric_evidence"]
    # but the data defect is still present, so the next pipeline run reopens the resolved check (D4-04) and blocks again
    session.execute(text("UPDATE decisions SET lifecycle_stage='evidence_gathered', assessment_stale=true WHERE id=:d"), {"d": d.id})
    session.refresh(d)
    again = pipeline(session).run(seed.analyst, d.id)
    assert "open_critical_dq" in codes(again.assessment)
    reopened = session.get(m.DqCheck, crit.id)
    session.refresh(reopened)
    assert (reopened.status, reopened.resolved_by) == ("open", None)
    assert [a.action for a in flow.audit.list_for_decision(seed.pm, d.id)].count("dq.reopened") == 1


@pytest.mark.parametrize("scenario,direction", [("ai_coach", "increase"), ("pricing", "no_material_decrease")])
def test_pipe_1_ai_coach_and_pricing_are_scored_with_observed_power_and_srm_inputs(session, seed, scenario, direction):
    d, result = run_seeded(session, seed, scenario)
    a = result.assessment
    assert d.expected_direction == direction and a.state == "scored" and result.partial is False
    assert a.blocking_reasons == [] and a.ddi_score is not None and a.ddi_band is not None            # (no band is asserted, D4-24)
    d4 = a.dimension_scores["dimensions"]["D4"]
    sources = {i["name"]: i["source"] for i in d4["inputs"]}
    assert sources == {"power_factor": "observed", "integrity_factor": "observed", "informativeness_factor": "observed"}
    assert d4["defaulted_inputs"] == []                                                              # power and SRM are NOT defaulted
    facts = build_facts(session, d.id)
    (exp,) = facts.experiments
    assert exp.achieved_power is not None and exp.srm_flag is not None and exp.mde is not None
    assert d4["details"]["power_factor"] == pytest.approx(min(1.0, exp.achieved_power / 0.8))
    assert d4["details"]["integrity_factor"] == (0.3 if exp.srm_flag else 1.0)
    items = evidence(session, d)
    assert sorted(e.evidence_type for e in items) == ["behavioral", "behavioral", "experiment"] and all(e.analysis_id for e in items)
    p1_inputs = {i["name"]: i["source"] for i in a.penalty_scores["penalties"]["P1"]["inputs"]}
    assert p1_inputs["heterogeneity_flag"] == ("observed" if scenario == "ai_coach" else "default")   # Pricing: unknown (one segment)


def test_pipe_1_community_flag_is_true_and_the_scored_path_needs_one_manual_customer_item(session, seed, flow):
    d, result = run_seeded(session, seed, "community")
    a = result.assessment
    assert build_facts(session, d.id).heterogeneity_flag is True
    assert a.state == "insufficient_evidence" and codes(a) == ["min_items", "min_types"]     # no customer evidence is generated (O2)
    assert a.ddi_score is None
    assert result.analysis_ids and len(evidence(session, d)) == 2
    # O2: one manually entered customer item through the existing Day-3 API, then the scored path
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "customer", stance="neutral", metric_id=None))
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", True)
    second = pipeline(session).run(seed.analyst, d.id)
    b = second.assessment
    assert b.state == "scored" and b.version == 2 and b.blocking_reasons == []
    p1 = b.penalty_scores["penalties"]["P1"]
    assert p1["score"] >= 0.3                                                                  # the segment-divergence floor
    p1_inputs = {i["name"]: (i["source"], i["value"]) for i in p1["inputs"]}
    assert p1_inputs["heterogeneity_flag"] == ("observed", True)
    # the generated items were not duplicated by the second run
    assert len([e for e in evidence(session, d) if e.created_by == "agent"]) == 2 and len(evidence(session, d)) == 3
    assert second.stages[3]["output"]["outcome"] == "completed"
    materialize = next(s for s in second.stages if s["stage"] == "materialize")
    assert (materialize["output"]["created"], materialize["output"]["updated"], materialize["output"]["unchanged"]) == (0, 0, 2)


def test_pipe_1_the_preconditions_and_permissions(session, seed, flow):
    d = seed.decisions["pricing"]
    with pytest.raises(Forbidden):
        pipeline(session).run(seed.bizops, d.id)
    with pytest.raises(Forbidden):
        pipeline(session).run(seed.leader, d.id)
    created = flow.new_decision()                                                                # stage 'created'
    with pytest.raises(StateConflict):
        pipeline(session).run(seed.analyst, created.id)
    done = clone_decision(flow, seed, "pricing")
    pipeline(session).run(seed.analyst, done.id)
    with pytest.raises(StateConflict):                                                           # now 'assessed': not evidence_gathered
        pipeline(session).run(seed.analyst, done.id)


# ================================================================ T-PIPE-2
FAIL_AT = ["dq", "quant", "customer", "experiment", "materialize"]


@pytest.mark.parametrize("stage", FAIL_AT)
def test_pipe_2_a_failing_stage_inserts_a_partial_assessment_and_leaves_the_stage_unchanged(session, seed, flow, monkeypatch, stage):
    d = clone_decision(flow, seed, "pricing")
    monkeypatch.setattr(PipelineService, f"stage_{stage}", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError(f"boom in {stage}")))
    result = pipeline(session).run(seed.analyst, d.id)
    assert result.partial is True and result.failed_stage == stage and "boom" in result.error
    a = result.assessment
    assert a.state == "partial" and a.ddi_score is None and a.ddi_band is None and a.version == 1
    assert a.blocking_reasons == [{"code": "stage_failed", "stage": stage, "message": f"boom in {stage}"}]
    # the assessment metadata is still recorded
    assert a.params_version and a.params_hash and a.nbe_params_version and a.nbe_params_hash and a.evidence_fingerprint
    assert a.as_of_date == TODAY and a.dimension_scores == {} and a.penalty_scores == {} and a.sensitivity == {}
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", False)              # the stage is unchanged
    runs = runs_repo.list_for_decision(session, d.id)
    failed = [r for r in runs if r.status == "failed"]
    assert len(failed) == 1 and failed[0].error == f"boom in {stage}" and failed[0].assessment_id == a.id
    assert failed[0].model is None and failed[0].output["pipeline_stage"] == stage
    assert result.stages[-1]["status"] == "failed" and result.stages[-1]["stage"] == stage
    # the pipeline stopped: no later stage ran
    done = [s["stage"] for s in result.stages if s["status"] != "failed"]
    assert done == ["dq", "quant", "customer", "experiment", "materialize"][:FAIL_AT.index(stage)]
    assert flow.audit_actions(d)[-1] == "pipeline.stage_failed"
    # R7: the partial assessment is current and never shows a number
    current, previous = AssessmentService(pipeline(session).ctx).current_and_previous(seed.pm, d.id)
    assert current.id == a.id and previous is None
    # and the decision can run again after the cause is fixed
    monkeypatch.undo()
    again = pipeline(session).run(seed.analyst, d.id)
    assert again.partial is False and again.assessment.state == "scored" and again.assessment.version == 2


def test_pipe_2_the_failing_stage_is_rolled_back_but_earlier_stages_stay_committed(session, seed, flow, monkeypatch):
    d = clone_decision(flow, seed, "pricing")
    real = analysis_store.persist
    calls = []

    def persist_then_fail(*args, **kwargs):
        stored = real(*args, **kwargs)
        calls.append(stored.row.id)
        if len(calls) == 2:
            raise RuntimeError("second analysis failed")
        return stored
    monkeypatch.setattr("app.services.pipeline.analysis_store.persist", persist_then_fail)
    result = pipeline(session).run(seed.analyst, d.id)
    assert result.failed_stage == "quant" and len(calls) == 2
    assert analysis_repo.list_for_decision(session, d.id) == []                                  # the stage's own writes are gone
    assert dq_repo.list_for_decision(session, d.id)                                              # stage 1 (DQ) was committed
    runs = runs_repo.list_for_decision(session, d.id)
    assert [(r.stage, r.status) for r in runs] == [("dq", "succeeded"), ("quant", "failed")]


def test_pipe_2_a_failing_assessment_stage_is_also_a_partial_assessment(session, seed, flow, monkeypatch):
    d = clone_decision(flow, seed, "pricing")
    monkeypatch.setattr(AssessmentService, "run", lambda self, actor, decision_id: (_ for _ in ()).throw(RuntimeError("engine blew up")))
    result = pipeline(session).run(seed.analyst, d.id)
    assert result.partial and result.failed_stage == "assessment"
    assert result.assessment.state == "partial" and result.assessment.blocking_reasons[0]["stage"] == "assessment"
    assert [s["stage"] for s in result.stages][:5] == ["dq", "quant", "customer", "experiment", "materialize"]
    session.refresh(d)
    assert d.lifecycle_stage == "evidence_gathered"
    assert len(evidence(session, d)) == 3                                                         # earlier stages stay committed


def test_pipe_2_through_the_api_a_stage_failure_is_a_201_with_a_partial_assessment(session, seed, flow, client, monkeypatch):
    d = clone_decision(flow, seed, "pricing")
    monkeypatch.setattr(PipelineService, "stage_experiment", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("api boom")))
    r = client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["partial"] is True and body["failed_stage"] == "experiment" and body["lifecycle_stage"] == "evidence_gathered"
    assert body["assessment"]["state"] == "partial" and body["assessment"]["ddi"] is None and body["assessment"]["dimensions"] == []
    assert body["assessment"]["blocking_reasons"][0] == {"code": "stage_failed", "stage": "experiment", "message": "api boom"}
    assert body["assessment"]["insufficient_evidence_label"] == "PARTIAL ASSESSMENT"


# ================================================================ T-PIPE-3
@pytest.mark.parametrize("scenario", ["pricing", "community", "onboarding"])
def test_pipe_3_two_runs_on_the_same_data_give_byte_identical_payloads(session, seed, scenario):
    d, first = run_seeded(session, seed, scenario)
    session.execute(text("UPDATE decisions SET lifecycle_stage='evidence_gathered', assessment_stale=true WHERE id=:d"), {"d": d.id})
    session.refresh(d)
    second = pipeline(session).run(seed.analyst, d.id)
    a, b = first.assessment, second.assessment
    assert (a.version, b.version) == (1, 2)
    pa, pb = assessment_payload(a, with_fingerprint=True), assessment_payload(b, with_fingerprint=True)
    assert json.dumps(pa, sort_keys=True, default=str) == json.dumps(pb, sort_keys=True, default=str)
    assert normalized(pa) == normalized(pb)
    # the recommendations are identical too
    ra = [(r.action_type, float(r.expected_reduction), float(r.priority_score), r.blockers_resolved) for r in
          sorted(session.scalars(select(m.Recommendation).where(m.Recommendation.assessment_id == a.id)), key=lambda r: r.action_type)]
    rb = [(r.action_type, float(r.expected_reduction), float(r.priority_score), r.blockers_resolved) for r in
          sorted(session.scalars(select(m.Recommendation).where(m.Recommendation.assessment_id == b.id)), key=lambda r: r.action_type)]
    assert ra == rb


def test_pipe_3_a_clone_with_other_ids_gives_the_same_numbers(session, seed, flow):
    """Same data, other ids: every computed number and every classification is identical. (The order of per-item input lists in
    the DDI breakdown follows the Day-3 sort by item id, so lists that carry ids are compared by value, not by position.)"""
    d, first = run_seeded(session, seed, "pricing")
    clone = clone_decision(flow, seed, "pricing")
    second = pipeline(session).run(seed.analyst, clone.id)
    a, b = first.assessment, second.assessment

    def numbers(x):
        dims = {k: (v["score"], v["raw_contribution"], v["display_contribution"]) for k, v in x.dimension_scores["dimensions"].items()}
        pens = {k: (v["score"], v["raw_contribution"], v["display_contribution"]) for k, v in x.penalty_scores["penalties"].items()}
        sens = {k: x.sensitivity[k] for k in ("base", "min", "max", "count", "band_stable", "label")}
        return {"state": x.state, "ddi": float(x.ddi_score), "band": x.ddi_band, "dims": dims, "pens": pens, "sens": sens,
                "direction": x.dimension_scores["evidence_direction"], "uncapped": x.dimension_scores["uncapped_ddi"]}
    assert numbers(a) == numbers(b)

    def evidence_view(dec):
        out = []
        for e in evidence(session, dec):
            an = session.get(m.AnalysisResult, e.analysis_id)
            out.append((an.analysis_type, e.evidence_type, e.stance, e.strength_grade, e.n_sample, e.effect_size, e.ci_low, e.ci_high,
                        e.summary, an.params_hash, an.source_fingerprint, an.dq_status))
        return sorted(out, key=str)
    assert evidence_view(d) == evidence_view(clone)                                                 # incl. parameter hash and data fingerprint


# ================================================================ API
def test_api_pipeline_run_dq_checks_analyses_and_analysis_detail(session, seed, flow, client):
    d = clone_decision(flow, seed, "pricing")
    r = client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["partial"] is False and body["lifecycle_stage"] == "assessed" and body["assessment"]["state"] == "scored"
    assert [s["stage"] for s in body["stages"]] == ["dq", "quant", "customer", "experiment", "materialize", "assessment"]
    assert len(body["analysis_ids"]) == 4

    checks = client.get(f"/decisions/{d.id}/dq-checks", headers=H(seed.bizops)).json()
    assert checks and all(c["decision_id"] == str(d.id) and c["assessment_id"] is None for c in checks)
    one = checks[0]
    assert {"check_key", "target", "observed_value", "threshold", "affects_success_metric", "source_snapshot", "last_run_at"} <= set(one)

    analyses = client.get(f"/decisions/{d.id}/analyses", headers=H(seed.pm)).json()
    assert sorted(a["analysis_type"] for a in analyses) == ["comparison", "experiment", "segmentation", "trend"]
    assert {a["creates_evidence"] for a in analyses if a["analysis_type"] == "segmentation"} == {False}
    detail = client.get(f"/analyses/{analyses[0]['id']}", headers=H(seed.executive)).json()
    assert detail["query_text"] and detail["params"]["config"]["tenant_config_hash"] and detail["result"] and "limitations" in detail
    exp = next(a for a in analyses if a["analysis_type"] == "experiment")
    exp_detail = client.get(f"/analyses/{exp['id']}", headers=H(seed.pm)).json()
    assert len(exp_detail["evidence_ids"]) == 1 and exp_detail["result"]["design_power"]["label"] == "design power at the pre-registered MDE"

    evidence_rows = client.get(f"/decisions/{d.id}/evidence", headers=H(seed.pm)).json()
    assert len(evidence_rows) == 3 and all(e["status"] == "active" and e["analysis_id"] and e["created_by"] == "agent" for e in evidence_rows)


def test_api_pipeline_run_permissions_state_and_errors(session, seed, flow, client):
    d = clone_decision(flow, seed, "pricing")
    assert client.post(f"/decisions/{d.id}/pipeline-runs").status_code == 401
    for actor in (seed.bizops, seed.leader, seed.executive):
        assert client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(actor)).status_code == 403
    assert client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.pm)).status_code == 201
    assert client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.pm)).status_code == 409                # now assessed
    assert client.post("/decisions/not-a-uuid/pipeline-runs", headers=H(seed.pm)).status_code == 404
    assert client.get("/analyses/not-a-uuid", headers=H(seed.pm)).status_code == 404
    assert client.get(f"/decisions/{d.id}/dq-checks").status_code == 401
    assert client.get("/decisions/not-a-uuid/analyses", headers=H(seed.pm)).status_code == 404


def test_api_the_canvas_requires_expected_direction(session, seed, flow, client):
    from flow import canvas
    body = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in canvas(seed, team_id=None, owner_id=None).items()}
    body_missing = {k: v for k, v in body.items() if k != "expected_direction"}
    assert client.post("/decisions", headers=H(seed.pm), json=body_missing).status_code == 422
    assert client.post("/decisions", headers=H(seed.pm), json={**body, "expected_direction": "sideways"}).status_code == 422
    for direction in ("increase", "decrease", "no_material_decrease"):
        r = client.post("/decisions", headers=H(seed.pm), json={**body, "expected_direction": direction})
        assert r.status_code == 201 and r.json()["expected_direction"] == direction
    did = r.json()["id"]
    patched = client.patch(f"/decisions/{did}/canvas", headers=H(seed.pm), json={"expected_direction": "increase"})
    assert patched.status_code == 200 and patched.json()["expected_direction"] == "increase"
    assert client.patch(f"/decisions/{did}/canvas", headers=H(seed.pm), json={"expected_direction": "up"}).status_code == 422
    seeded = client.get(f"/decisions/{seed.decisions['pricing'].id}", headers=H(seed.pm)).json()
    assert seeded["expected_direction"] == "no_material_decrease"


def test_api_dq_patch_keeps_its_day_3_semantics_on_a_pipeline_check(session, seed, flow, client):
    d = clone_decision(flow, seed, "onboarding")
    client.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst))
    checks = client.get(f"/decisions/{d.id}/dq-checks", headers=H(seed.pm)).json()
    crit = next(c for c in checks if c["severity"] == "critical")
    r = client.patch(f"/dq-checks/{crit['id']}", headers=H(seed.analyst), json={"status": "accepted", "note": "known tracking defect"})
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["target"] == "onboarding_completed@android"
    assert client.patch(f"/dq-checks/{crit['id']}", headers=H(seed.analyst), json={"status": "resolved"}).status_code == 409   # already decided by a human
    assert client.patch(f"/dq-checks/{crit['id']}", headers=H(seed.bizops), json={"status": "resolved"}).status_code == 403
    state = client.get(f"/decisions/{d.id}", headers=H(seed.pm)).json()
    assert state["lifecycle_stage"] == "evidence_gathered" and state["assessment_stale"] is True
