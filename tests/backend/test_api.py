"""API tests (brief section 4, tests 26-30) through FastAPI's TestClient on the real database (rolled back)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flow import TODAY, Flow, canvas, evidence_payload
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import deps
from app.core.clock import FixedClock
from app.core.errors import install_error_handlers, translate_db_error
from app.domain.errors import InvalidInput, StateConflict
from app.main import app


@pytest.fixture()
def client(session):
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def H(actor):
    return {"X-Demo-User": actor.id}


def jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}


def api_workflow(client, seed, *, ack=True):
    """create -> confirm -> 3 evidence -> assess -> review -> validate, entirely over HTTP. Returns (decision id, assessment)."""
    body = jsonable(canvas(seed, team_id=None, owner_id=None))
    r = client.post("/decisions", headers=H(seed.pm), json=body)
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert client.post(f"/decisions/{did}/confirm-evidence", headers=H(seed.pm)).status_code == 200
    for kind in ("behavioral", "customer", "financial"):
        r = client.post(f"/decisions/{did}/evidence", headers=H(seed.analyst), json=jsonable(evidence_payload(seed, kind)))
        assert r.status_code == 201, r.text
    r = client.post(f"/decisions/{did}/assessments", headers=H(seed.analyst))
    assert r.status_code == 201, r.text
    return did, r.json()


# ------------------------------------------------------------------ 26. decided decisions cannot be mutated
def test_26_a_decided_decision_cannot_be_mutated_through_any_endpoint(client, seed, flow, session):
    did, assessment = api_workflow(client, seed)
    aid = assessment["id"]
    rec_id = client.get(f"/assessments/{aid}/recommendations", headers=H(seed.pm)).json()[0]["id"]
    check = flow.insert_dq_check(session.get(__import__("app.db.models", fromlist=["x"]).DecisionAssessment, uuid.UUID(aid)),
                                 seed.metrics["d90_retention"].data_source_id, "warn")
    assert client.post(f"/assessments/{aid}/reviews", headers=H(seed.leader), json={"verdict": "ready"}).status_code == 201
    assert client.post(f"/decisions/{did}/validate", headers=H(seed.executive)).status_code == 200
    ack = assessment["state"] != "scored" or assessment["band"] in ("high", "critical")
    r = client.post(f"/decisions/{did}/decision-record", headers=H(seed.executive),
                    json={"outcome": "approve", "rationale": "Decided with eyes open.", "acknowledged_risk": ack})
    assert r.status_code == 201, r.text
    assert client.get(f"/decisions/{did}", headers=H(seed.pm)).json()["lifecycle_stage"] == "decided"

    mutations = [
        ("PATCH", f"/decisions/{did}/canvas", seed.pm, {"title": "changed"}),
        ("POST", f"/decisions/{did}/confirm-evidence", seed.pm, None),
        ("POST", f"/decisions/{did}/evidence", seed.analyst, jsonable(evidence_payload(seed, "behavioral"))),
        ("POST", f"/decisions/{did}/assessments", seed.analyst, None),
        ("POST", f"/assessments/{aid}/reviews", seed.pm, {"verdict": "ready"}),
        ("POST", f"/decisions/{did}/validate", seed.executive, None),
        ("POST", f"/decisions/{did}/decision-record", seed.executive,
         {"outcome": "reject", "rationale": "second record", "acknowledged_risk": True}),
        ("PATCH", f"/recommendations/{rec_id}", seed.pm, {"status": "accepted", "note": "late"}),
        ("PATCH", f"/dq-checks/{check}", seed.analyst, {"status": "resolved"}),
    ]
    for method, url, actor, body in mutations:
        r = client.request(method, url, headers=H(actor), json=body)
        assert r.status_code == 409, (method, url, r.status_code, r.text)
        assert r.json()["error"]["code"] == "state_conflict"
    # reads still work and the stored data was not touched
    assert client.get(f"/decisions/{did}/evidence", headers=H(seed.pm)).status_code == 200
    assert client.get(f"/decisions/{did}", headers=H(seed.pm)).json()["title"] == canvas(seed)["title"]


# ------------------------------------------------------------------ 27. DB errors map to 409 / 422, never 500
def captured(session, sql, **params) -> DBAPIError:
    try:
        with session.begin_nested():
            session.execute(text(sql), params)
    except DBAPIError as exc:
        return exc
    raise AssertionError(f"expected the database to reject: {sql}")


def test_27_database_constraint_and_trigger_errors_translate_to_409_or_422(session, seed, flow):
    d = flow.new_decision()
    mapped = {
        "illegal transition (trigger, check_violation)": (409, captured(session, "UPDATE decisions SET lifecycle_stage='decided' WHERE id=:d", d=d.id)),
        "canvas CHECK constraint": (422, captured(session, "UPDATE decisions SET change_my_mind_criteria='[]'::jsonb WHERE id=:d", d=d.id)),
        "NOT NULL": (422, captured(session, "UPDATE decisions SET title=NULL WHERE id=:d", d=d.id)),
        "foreign key": (422, captured(session, "UPDATE decisions SET success_metric_id=gen_random_uuid() WHERE id=:d", d=d.id)),
        "insert-only audit (integrity_constraint_violation)": (409, captured(session, "DELETE FROM audit_logs")),
    }
    flow.insert_partial_assessment(d, 1)
    mapped["unique (decision_id, version)"] = (409, captured(
        session, "INSERT INTO decision_assessments (decision_id, version, state, params_version, params_hash,"
                 " evidence_fingerprint, as_of_date, is_synthetic) VALUES (:d,1,'partial','v','h','f','2026-10-01',true)", d=d.id))
    for label, (expected, exc) in mapped.items():
        err = translate_db_error(exc)
        assert err is not None, label
        assert (409 if isinstance(err, StateConflict) else 422 if isinstance(err, InvalidInput) else 500) == expected, \
            (label, type(err).__name__, str(exc.orig)[:100])


def test_27_the_http_error_handler_never_returns_500_for_database_errors(session, seed, flow):
    d = flow.new_decision()
    mini = FastAPI()
    install_error_handlers(mini)

    @mini.get("/trigger")
    def trigger():
        session.execute(text("UPDATE decisions SET lifecycle_stage='decided' WHERE id=:d"), {"d": d.id})

    @mini.get("/check")
    def check():
        session.execute(text("UPDATE decisions SET change_my_mind_criteria='[]'::jsonb WHERE id=:d"), {"d": d.id})

    c = TestClient(mini, raise_server_exceptions=False)
    r1 = c.get("/trigger")
    session.rollback()                      # the failed statement left the test transaction in an aborted state
    r2 = c.get("/check")
    session.rollback()
    assert r1.status_code == 409 and r2.status_code == 422
    assert "error" in r1.json() and "error" in r2.json()


def test_27_service_validation_errors_over_http_are_422_and_state_errors_409(client, seed, flow):
    h = H(seed.pm)
    assert client.post("/decisions", headers=h, json=jsonable(canvas(seed, decision_due_date=date(2026, 1, 1)))).status_code == 422
    assert client.post("/decisions", headers=h, json={"title": "missing everything"}).status_code == 422
    d = flow.new_decision()
    assert client.post(f"/decisions/{d.id}/assessments", headers=H(seed.analyst)).status_code == 409        # created
    assert client.post(f"/decisions/{d.id}/evidence", headers=H(seed.analyst),
                       json=jsonable(evidence_payload(seed, "behavioral", observed_end=date(2020, 1, 1)))).status_code == 422
    assert client.get(f"/decisions/{uuid.uuid4()}", headers=h).status_code == 404
    assert client.get("/decisions/not-a-uuid", headers=h).status_code == 404


# ------------------------------------------------------------------ 28. role permission matrix (one test per persona)
PERSONAS = ["pm", "ba", "product_analyst", "bizops", "dept_leader", "executive"]
ACTOR_KEY = {"pm": "pm1", "ba": "ba1", "product_analyst": "pa1", "bizops": "biz1", "dept_leader": "lead1", "executive": "exec1"}

ALLOWED = {   # action -> roles (decision-based rules are covered separately below)
    "create_decision": {"pm", "ba"},
    "edit_canvas": {"pm", "ba"},
    "confirm_evidence": {"pm", "ba", "product_analyst"},
    "add_evidence": {"pm", "ba", "product_analyst"},
    "run_assessment": {"pm", "ba", "product_analyst"},
    "human_review": {"pm", "ba", "dept_leader", "executive"},
    "validate": {"pm", "ba", "dept_leader", "executive"},         # dept_leader: own team (Product) in this world
    "record_decision": {"pm", "dept_leader", "executive"},        # pm owns the decision; ba does not; leader: own team
    "update_dq": {"product_analyst", "ba"},
    "update_recommendation": {"pm", "ba", "product_analyst"},
    "read": set(PERSONAS),
}


@pytest.mark.parametrize("persona", PERSONAS)
def test_28_role_permission_matrix(client, seed, flow, session, persona):
    owner_world = flow.gathered()                                  # owned by pm1, Product team
    flow.add_evidence(owner_world)
    a = flow.assessments.run(seed.analyst, owner_world.id)
    rec_id = flow.recs.list_for_assessment(seed.pm, a.id)[0].id
    check = flow.insert_dq_check(a, seed.metrics["d90_retention"].data_source_id, "warn")
    did, aid = str(owner_world.id), str(a.id)
    actor = seed.actors[ACTOR_KEY[persona]]
    h = H(actor)
    calls = {
        "create_decision": ("POST", "/decisions", jsonable(canvas(seed, team_id=None, owner_id=None))),
        "edit_canvas": ("PATCH", f"/decisions/{did}/canvas", {"title": "A new title"}),
        "confirm_evidence": ("POST", f"/decisions/{did}/confirm-evidence", None),
        "add_evidence": ("POST", f"/decisions/{did}/evidence", jsonable(evidence_payload(seed, "customer"))),
        "run_assessment": ("POST", f"/decisions/{did}/assessments", None),
        "human_review": ("POST", f"/assessments/{aid}/reviews", {"verdict": "ready"}),
        "validate": ("POST", f"/decisions/{did}/validate", None),
        "record_decision": ("POST", f"/decisions/{did}/decision-record",
                            {"outcome": "approve", "rationale": "r", "acknowledged_risk": False}),
        "update_dq": ("PATCH", f"/dq-checks/{check}", {"status": "accepted"}),
        "update_recommendation": ("PATCH", f"/recommendations/{rec_id}", {"status": "accepted", "note": "ok"}),
        "read": ("GET", f"/decisions/{did}", None),
    }
    for action, (method, url, body) in calls.items():
        r = client.request(method, url, headers=h, json=body)
        if persona in ALLOWED[action]:
            assert r.status_code not in (401, 403, 500), (persona, action, r.status_code, r.text)
        else:
            assert r.status_code == 403, (persona, action, r.status_code, r.text)
            assert r.json()["error"]["code"] == "forbidden"
    assert client.get("/me", headers=h).json()["role"] == persona


def test_28_department_leader_acts_only_on_own_team_and_owner_may_record(client, seed, flow):
    growth = flow.gathered(title="Growth decision", team_id=seed.team_growth, owner_id=seed.actors["pm2"].id)
    a = flow.assessments.run(seed.analyst, growth.id)
    gid = str(growth.id)
    assert a.state == "insufficient_evidence"
    # lead1 is on the Product team: not allowed on a Growth decision, an executive is
    assert client.post(f"/decisions/{gid}/validate", headers=H(seed.leader)).status_code == 403
    assert client.post(f"/decisions/{gid}/decision-record", headers=H(seed.leader),
                       json={"outcome": "approve", "rationale": "r", "acknowledged_risk": True}).status_code == 403
    assert client.post(f"/decisions/{gid}/validate", headers=H(seed.executive)).status_code != 403
    # the owner of a decision may record it whatever their role: here a product analyst owns it
    mine = flow.gathered(title="Analyst owned", owner_id=seed.analyst.id)
    r = client.post(f"/decisions/{mine.id}/decision-record", headers=H(seed.analyst),
                    json={"outcome": "approve", "rationale": "r", "acknowledged_risk": True})
    assert r.status_code == 409                                    # permitted, but the decision is not validated yet
    r = client.post(f"/decisions/{mine.id}/decision-record", headers=H(seed.bizops),
                    json={"outcome": "approve", "rationale": "r", "acknowledged_risk": True})
    assert r.status_code == 403


def test_28_missing_or_unknown_demo_user_is_401(client, seed):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"X-Demo-User": "not-a-uuid"}).status_code == 401
    assert client.get("/me", headers={"X-Demo-User": str(uuid.uuid4())}).status_code == 401
    assert client.get("/decisions").status_code == 401
    assert client.post("/decisions", json=jsonable(canvas(seed))).status_code == 401
    assert client.get("/me").json()["error"]["code"] == "demo_identity_missing"
    # the role-switcher list itself is public (it is how a demo identity is chosen) and says it is not authentication
    users = client.get("/users").json()
    assert len(users) == 7 and {u["role"] for u in users} == set(PERSONAS)
    assert "not authentication" in users[0]["notice"]
    assert client.get("/health").json()["status"] == "ok"


# ------------------------------------------------------------------ 29. validated label
def test_29_validated_stage_label_is_exactly_assessment_validated_by_review(client, seed):
    did, assessment = api_workflow(client, seed)
    assert client.post(f"/assessments/{assessment['id']}/reviews", headers=H(seed.leader), json={"verdict": "ready"}).status_code == 201
    r = client.post(f"/decisions/{did}/validate", headers=H(seed.executive))
    assert r.status_code == 200
    assert r.json()["lifecycle_stage"] == "validated"
    assert r.json()["lifecycle_label"] == "Assessment validated by review"
    assert client.get(f"/decisions/{did}", headers=H(seed.pm)).json()["lifecycle_label"] == "Assessment validated by review"
    labels = {d["lifecycle_stage"]: d["lifecycle_label"] for d in client.get("/decisions", headers=H(seed.pm)).json()}
    assert labels["evidence_gathered"] == "Evidence gathered"


# ------------------------------------------------------------------ 30. no numeric DDI for insufficient / partial
NUMERIC_DDI_KEYS = {"ddi", "ddi_display", "ddi_score", "uncapped_ddi", "support", "penalty_multiplier"}


def assert_no_number(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in NUMERIC_DDI_KEYS:
                assert v is None, f"{path}.{k} = {v!r}"
            if k in ("dimensions", "penalties"):
                assert v == [], f"{path}.{k} must be empty"
            if k == "sensitivity":
                assert v is None, f"{path}.sensitivity must be null"
            if k != "previous_scored_assessment":
                assert_no_number(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            assert_no_number(v, f"{path}[{i}]")


def test_30_insufficient_assessments_expose_no_ddi_anywhere(client, seed, flow):
    d, a = flow.insufficient()
    r = client.get(f"/assessments/{a.id}", headers=H(seed.pm))
    body = r.json()
    assert body["state"] == "insufficient_evidence" and body["insufficient_evidence_label"] == "INSUFFICIENT EVIDENCE"
    assert_no_number(body)
    assert [b["code"] for b in body["blocking_reasons"]] == ["min_items", "min_types", "success_metric_evidence"]
    assert body["evidence_direction"]["label"] == "uncertain"
    detail = client.get(f"/decisions/{d.id}", headers=H(seed.pm)).json()
    assert_no_number(detail)
    assert detail["current_assessment"]["ddi"] is None and detail["current_assessment"]["band"] is None
    assert_no_number(client.get(f"/decisions/{d.id}/assessments", headers=H(seed.pm)).json())
    assert_no_number(client.get("/decisions", headers=H(seed.pm)).json())
    recs = client.get(f"/assessments/{a.id}/recommendations", headers=H(seed.pm)).json()
    assert recs and all(x["expected_reduction"] == 0.0 and x["impact_unit"] == "blockers_resolved" for x in recs)
    assert all(x["group"] == "unblock_scoring" and x["blockers_resolved"] >= 1 for x in recs)
    audit = client.get(f"/decisions/{d.id}/audit", headers=H(seed.pm)).json()
    assert all("ddi" not in str(x["after"]).lower() or x["after"].get("band") is None for x in audit)


def test_30_partial_assessments_expose_no_ddi_even_if_the_row_holds_numbers(client, seed, flow):
    d, a1 = flow.scored()
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral", summary="newer"))
    partial_id = flow.insert_partial_assessment(d, 2, poison=True)
    r = client.get(f"/assessments/{partial_id}", headers=H(seed.pm))
    body = r.json()
    assert body["state"] == "partial" and body["is_current"] is True and body["insufficient_evidence_label"] == "PARTIAL ASSESSMENT"
    assert_no_number(body)
    # the previous scored version is exposed separately and flagged historical (never a silent fallback)
    assert body["previous_scored_assessment"]["version"] == 1 and body["previous_scored_assessment"]["historical"] is True
    detail = client.get(f"/decisions/{d.id}", headers=H(seed.pm)).json()
    assert detail["current_assessment"]["state"] == "partial" and detail["current_assessment"]["ddi"] is None
    assert detail["previous_scored_assessment"]["version"] == 1 and detail["previous_scored_assessment"]["historical"] is True
    listing = client.get(f"/decisions/{d.id}/assessments", headers=H(seed.pm)).json()
    assert [x["version"] for x in listing] == [2, 1] and listing[0]["is_current"] and listing[1]["is_superseded"]
    assert_no_number(listing[0])
    assert listing[1]["ddi"] is not None                          # the older scored version keeps its own number


def test_scored_assessment_panel_has_everything_the_ddi_panel_needs(client, seed):
    did, a = api_workflow(client, seed)
    body = client.get(f"/assessments/{a['id']}", headers=H(seed.pm)).json()
    assert body["state"] == "scored" and body["ddi"] is not None and body["band"] in ("low", "moderate", "high", "critical")
    assert len(body["dimensions"]) == 7 and len(body["penalties"]) == 2
    assert round(sum(x["display_contribution"] for x in body["dimensions"] + body["penalties"]), 1) == body["ddi"]
    assert body["sensitivity"]["count"] == 20 and isinstance(body["sensitivity"]["band_stable"], bool)
    assert body["params"]["ddi_params_version"] == "ddi_params_v0.1" and len(body["params"]["ddi_params_hash"]) == 64
    assert body["evidence_direction"]["label"] in ("supporting", "contradicting", "mixed", "uncertain")
    assert "not a measure of decision quality" in body["positioning"]
    assert body["what_drove_this_result"]
    recs = client.get(f"/assessments/{a['id']}/recommendations", headers=H(seed.pm)).json()
    assert recs and recs[0]["rank"] == 1 and "does not predict" in recs[0]["note"]
    pr = [x["priority_score"] for x in recs]
    assert pr == sorted(pr, reverse=True)
    r = client.patch(f"/recommendations/{recs[0]['id']}", headers=H(seed.analyst), json={"status": "deferred", "note": "later"})
    assert r.status_code == 200 and r.json()["status"] == "deferred" and r.json()["human_note"] == "later"
    audit = client.get(f"/decisions/{did}/audit", headers=H(seed.pm)).json()
    assert [x["action"] for x in audit].count("recommendation.status_changed") == 1
    assert client.get(f"/decisions/{did}/evidence", headers=H(seed.pm)).json()[0]["created_by"] == "user"
