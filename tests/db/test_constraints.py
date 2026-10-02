"""Canvas, lifecycle, assessment, insert-only and role constraints (all rolled back)."""

import json

import psycopg
import pytest

from .conftest import new_decision


def fails(conn, sql, params=None):
    """True if the statement raises a database error (rolled back to a savepoint)."""
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error:
        return True
    return False


# ------------------------------------------------------------------ Decision Canvas
@pytest.mark.parametrize("criteria", [
    "[]",                                              # CV-5: at least one criterion
    '["short"]',                                       # below 10 characters
    json.dumps(["x" * 301]),                           # above 300 characters
    json.dumps([f"criterion number {i} is long enough" for i in range(6)]),   # more than 5
    '"not an array"',
    '[123456789012]',                                  # not strings
])
def test_canvas_rejects_invalid_change_my_mind_criteria(conn, ids, criteria):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            new_decision(conn, ids, criteria=criteria)


def test_canvas_accepts_valid_criteria_and_requires_fields(conn, ids):
    did = new_decision(conn, ids, criteria=json.dumps(["x" * 10, "y" * 300]))
    assert did
    assert fails(conn, "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id,"
                       " decision_due_date, risk_level, change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at,"
                       " owner_id, is_synthetic)"
                       " VALUES (%s,%s,'t','d','h',%s,NULL,'low','[\"criterion long enough\"]','pricing_change','increase',now(),%s,true)",
                 (ids.org, ids.team, ids.metric, ids.pm)), "decision_due_date is required"
    assert fails(conn, "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id,"
                       " decision_due_date, risk_level, change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at,"
                       " owner_id, is_synthetic)"
                       " VALUES (%s,%s,'t','d','h',NULL,'2026-12-01','low','[\"criterion long enough\"]','pricing_change','increase',now(),%s,true)",
                 (ids.org, ids.team, ids.pm)), "success_metric_id is required"
    assert fails(conn, "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id,"
                       " decision_due_date, risk_level, change_my_mind_criteria, decision_type, canvas_completed_at, owner_id, is_synthetic)"
                       " VALUES (%s,%s,'t','d','h',%s,'2026-12-01','low','[\"criterion long enough\"]','pricing_change',now(),%s,true)",
                 (ids.org, ids.team, ids.metric, ids.pm)), "0005: expected_direction is required (no default)"
    assert fails(conn, "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id,"
                       " decision_due_date, risk_level, change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at,"
                       " owner_id, is_synthetic)"
                       " VALUES (%s,%s,'t','d','h',%s,'2026-12-01','low','[\"criterion long enough\"]','pricing_change','sideways',now(),%s,true)",
                 (ids.org, ids.team, ids.metric, ids.pm)), "0005: expected_direction must be one of the three values"


def test_title_hypothesis_and_type_limits(conn, ids):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            new_decision(conn, ids, title="t" * 121)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            new_decision(conn, ids, hypothesis="h" * 501)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            new_decision(conn, ids, decision_type="not_a_type")


# ------------------------------------------------------------------ Lifecycle
ASSESSMENT_META = "params_hash, evidence_fingerprint, as_of_date"      # NOT NULL since migration 0004


def add_scored_assessment(conn, did, version=1, score=10, band="low"):
    """Migration 0004 (R13c): the decision needs a non-partial assessment row before it can be 'assessed'."""
    return conn.execute(
        f"INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version, {ASSESSMENT_META}, is_synthetic)"
        " VALUES (%s,%s,'scored',%s,%s,'ddi_params_v0.1','h','f','2026-10-01',true) RETURNING id",
        (did, version, score, band)).fetchone()[0]


def advance(conn, did, stage, **extra):
    sets = ["lifecycle_stage = %s"] + [f"{k} = %s" for k in extra]
    conn.execute(f"UPDATE decisions SET {', '.join(sets)} WHERE id = %s", (stage, *extra.values(), did))


def test_new_decisions_must_start_created(conn, ids):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id, decision_due_date,"
                " risk_level, change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at, owner_id,"
                " lifecycle_stage, is_synthetic)"
                " VALUES (%s,%s,'t','d','h',%s,'2026-12-01','low','[\"criterion long enough\"]','pricing_change','increase',now(),%s,'assessed',true)",
                (ids.org, ids.team, ids.metric, ids.pm))


def test_valid_lifecycle_path_and_illegal_transitions(conn, ids):
    did = new_decision(conn, ids)
    assert not fails(conn, "UPDATE decisions SET lifecycle_stage='evidence_gathered' WHERE id=%s", (did,))
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='decided' WHERE id=%s", (did,)), "skipping stages is rejected"
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='validated' WHERE id=%s", (did,))
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='assessed' WHERE id=%s", (did,)), "needs a locked canvas"
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='assessed', canvas_locked_at='2026-10-01T09:00:00Z' WHERE id=%s", (did,)),         "0004: assessed requires an assessment row"
    add_scored_assessment(conn, did)
    advance(conn, did, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='validated' WHERE id=%s", (did,)), "must pass challenged first"
    advance(conn, did, "challenged")
    advance(conn, did, "validated")
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='decided' WHERE id=%s", (did,)), "needs a human decision record"


def test_cannot_leave_created_without_metric_data_source_or_evidence(conn, ids):
    mid = conn.execute("INSERT INTO metrics (org_id, name, definition, unit, grain, is_synthetic)"
                       " VALUES (%s,'orphan_metric','no data source','ratio','day',true) RETURNING id", (ids.org,)).fetchone()[0]
    did = new_decision(conn, ids, metric=mid)
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='evidence_gathered' WHERE id=%s", (did,))


def test_returning_to_evidence_gathered_requires_stale_flag_and_locked_canvas_is_permanent(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    add_scored_assessment(conn, did)
    advance(conn, did, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='evidence_gathered' WHERE id=%s", (did,)), "stale flag required"
    assert not fails(conn, "UPDATE decisions SET lifecycle_stage='evidence_gathered', assessment_stale=true WHERE id=%s", (did,))
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='assessed' WHERE id=%s", (did,)), "stale must be cleared when re-assessed"
    assert fails(conn, "UPDATE decisions SET canvas_locked_at=NULL WHERE id=%s", (did,)), "canvas lock cannot be cleared"
    assert not fails(conn, "UPDATE decisions SET lifecycle_stage='assessed', assessment_stale=false WHERE id=%s", (did,))


def test_stage_past_evidence_gathered_requires_canvas_lock(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    assert fails(conn, "UPDATE decisions SET lifecycle_stage='assessed' WHERE id=%s", (did,))


def to_validated(conn, ids, did, state="scored", band="low"):
    advance(conn, did, "evidence_gathered")
    if state == "scored":
        conn.execute("INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
                     " VALUES (%s,1,'scored',%s,%s,'ddi_params_v0.1','h','f','2026-10-01',true)", (did, {"low": 10, "high": 60}[band], band))
    else:
        conn.execute("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
                     " VALUES (%s,1,'insufficient_evidence','[\"critical DQ failure\"]'::jsonb,'ddi_params_v0.1','h','f','2026-10-01',true)", (did,))
    advance(conn, did, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    advance(conn, did, "challenged")
    advance(conn, did, "validated")


def test_human_decision_record_rules(conn, ids):
    did = new_decision(conn, ids)
    rec = ("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, acknowledged_risk, is_synthetic)"
           " VALUES (%s,%s,%s,%s,%s,true)")
    assert fails(conn, rec, (did, ids.executive, "approve", "r", False)), "record requires a validated decision"
    to_validated(conn, ids, did, "scored", "high")
    assert fails(conn, rec, (did, ids.executive, "approve", "r", False)), "BR-11: high band needs acknowledgement"
    assert fails(conn, rec, (did, ids.executive, "approve", "   ", True)), "rationale must not be blank"
    assert not fails(conn, rec, (did, ids.executive, "approve", "Approved with eyes open.", True))
    assert fails(conn, rec, (did, ids.executive, "reject", "second final record", True)), "one final record"
    advance(conn, did, "decided")
    assert fails(conn, "UPDATE decisions SET title='changed' WHERE id=%s", (did,)), "decided is immutable"


def test_insufficient_evidence_decision_requires_acknowledgement(conn, ids):
    did = new_decision(conn, ids)
    to_validated(conn, ids, did, "insufficient")
    rec = ("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, acknowledged_risk, is_synthetic)"
           " VALUES (%s,%s,'approve_conditional',%s,%s,true)")
    assert fails(conn, rec, (did, ids.executive, "go", False))
    assert not fails(conn, rec, (did, ids.executive, "go", True))


def test_decision_records_and_audit_logs_are_insert_only(conn, ids):
    did = new_decision(conn, ids)
    to_validated(conn, ids, did, "scored", "low")
    conn.execute("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic)"
                 " VALUES (%s,%s,'approve','fine',true)", (did, ids.executive))
    assert fails(conn, "UPDATE decision_records SET rationale='edited' WHERE decision_id=%s", (did,))
    assert fails(conn, "DELETE FROM decision_records WHERE decision_id=%s", (did,))
    assert fails(conn, "UPDATE audit_logs SET action='edited'")
    assert fails(conn, "DELETE FROM audit_logs")


def test_defer_record_does_not_block_a_later_final_decision(conn, ids):
    did = new_decision(conn, ids)
    to_validated(conn, ids, did, "scored", "low")
    conn.execute("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic)"
                 " VALUES (%s,%s,'defer','need more evidence',true)", (did, ids.executive))
    advance(conn, did, "evidence_gathered", assessment_stale=True)
    assert conn.execute("SELECT lifecycle_stage::text FROM decisions WHERE id=%s", (did,)).fetchone()[0] == "evidence_gathered"
    assert conn.execute("SELECT count(*) FROM decision_records WHERE decision_id=%s", (did,)).fetchone()[0] == 1


# ------------------------------------------------------------------ assessments: no score unless scored
def test_ddi_score_exists_iff_state_is_scored(conn, ids):
    did = new_decision(conn, ids)
    ins = ("INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, blocking_reasons, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
           " VALUES (%s,%s,%s,%s,%s,%s::jsonb,'ddi_params_v0.1','h','f','2026-10-01',true)")
    assert fails(conn, ins, (did, 1, "insufficient_evidence", 55, None, '["x"]')), "no score for insufficient evidence"
    assert fails(conn, ins, (did, 1, "insufficient_evidence", None, "high", '["x"]')), "no band for insufficient evidence"
    assert fails(conn, ins, (did, 1, "partial", 40, "moderate", "[]")), "no score for partial"
    assert fails(conn, ins, (did, 1, "scored", None, None, "[]")), "scored requires a score"
    assert fails(conn, ins, (did, 1, "scored", 120, "critical", "[]")), "score must be 0..100"
    assert fails(conn, ins, (did, 1, "insufficient_evidence", None, None, "[]")), "insufficient requires blocking reasons"
    assert not fails(conn, ins, (did, 1, "insufficient_evidence", None, None, '["critical DQ failure"]'))
    assert not fails(conn, ins, (did, 2, "scored", 61.0, "high", "[]"))
    assert fails(conn, ins, (did, 2, "scored", 62.0, "high", "[]")), "unique (decision_id, version)"


# ------------------------------------------------------------------ traceability guard
def test_claim_can_only_cite_evidence_of_the_same_decision(conn, ids):
    d1, d2 = new_decision(conn, ids), new_decision(conn, ids, title="Other decision")
    a1 = conn.execute("INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
                      " VALUES (%s,1,'scored',50,'moderate','ddi_params_v0.1','h','f','2026-10-01',true) RETURNING id", (d1,)).fetchone()[0]
    claim = conn.execute("INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic)"
                         " VALUES (%s,'c','descriptive','supports','low',true) RETURNING id", (a1,)).fetchone()[0]
    ev = lambda d: conn.execute(  # noqa: E731
        "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
        " observed_end, created_by, is_synthetic) VALUES (%s,%s,'behavioral','s','supports','B','2026-09-01','2026-09-30','user',true)"
        " RETURNING id", (d, ids.es_events)).fetchone()[0]
    own, foreign = ev(d1), ev(d2)
    assert fails(conn, "INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (%s,%s,true)", (claim, foreign))
    assert not fails(conn, "INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (%s,%s,true)", (claim, own))


# ------------------------------------------------------------------ synthetic labelling and referential integrity
def test_fc_rows_must_be_synthetic_and_reference_existing_users(conn, ids):
    assert fails(conn, "INSERT INTO fc_.pricing_model_inputs (input_key, value, unit, is_assumption, source_note, is_synthetic)"
                       " VALUES ('x',1,'u',false,'n',false)")
    assert fails(conn, "INSERT INTO fc_.events (event_id, user_id, event_ts, event_name, platform, app_version)"
                       " VALUES (999999999, 999999999, now(), 'app_open', 'ios', '1')"), "FK to fc_.users"
    assert fails(conn, "INSERT INTO fc_.users (user_id, signup_ts, platform, country, acquisition_channel, engagement_style,"
                       " prior_engagement_tier) VALUES (900000001, now(), 'blackberry', 'US', 'x', 'solo_athlete', 'low')")


def test_core_rows_require_explicit_is_synthetic(conn, ids):
    assert fails(conn, "INSERT INTO teams (org_id, name) VALUES (%s, 'no flag')", (ids.org,)), "is_synthetic has no default"


# ------------------------------------------------------------------ read-only role
def test_read_only_role_sees_only_views(conn, seeded):
    conn.execute("SET LOCAL ROLE ddr_readonly")
    assert conn.execute("SELECT count(*) FROM fc_.v_users").fetchone()[0] > 0
    assert conn.execute("SELECT count(*) FROM v_debt_radar").fetchone()[0] >= 4
    for sql in ("SELECT 1 FROM fc_.users LIMIT 1", "SELECT 1 FROM fc_.events LIMIT 1",
                "SELECT 1 FROM fc_.feedback_ground_truth LIMIT 1", "SELECT 1 FROM decisions LIMIT 1"):
        assert fails(conn, sql), sql
    assert fails(conn, "INSERT INTO fc_.pricing_model_inputs VALUES ('a',1,'u',false,'n',true)")
    assert fails(conn, "DELETE FROM fc_.v_users")
