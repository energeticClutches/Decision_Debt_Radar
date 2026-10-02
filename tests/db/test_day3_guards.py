"""Migration 0004 invariants (R10, R13, brief 3.2, 3.4d). All statements run in a rolled-back transaction."""

import psycopg
import pytest

from .conftest import new_decision
from .test_constraints import ASSESSMENT_META, add_scored_assessment, advance, fails


def assessed(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    add_scored_assessment(conn, did)
    advance(conn, did, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    return did


def stage(conn, did):
    return conn.execute("SELECT lifecycle_stage::text, assessment_stale FROM decisions WHERE id=%s", (did,)).fetchone()


# ------------------------------------------------------------------ 3.2 / R10 columns
def test_assessment_metadata_columns_are_required_and_blockers_resolved_is_non_negative(conn, ids):
    did = new_decision(conn, ids)
    base = ("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, {cols}"
            " is_synthetic) VALUES (%s,1,'insufficient_evidence','[\"x\"]'::jsonb,'v', {vals} true)")
    assert fails(conn, base.format(cols="", vals=""), (did,)), "params_hash, evidence_fingerprint, as_of_date are NOT NULL"
    full = base.format(cols=ASSESSMENT_META + ",", vals="'h','f','2026-10-01',")
    aid = conn.execute(full + " RETURNING id", (did,)).fetchone()[0]
    ok = ("INSERT INTO recommendations (assessment_id, action_type, description, effort_days, expected_reduction, relevance,"
          " priority_score, blockers_resolved, is_synthetic) VALUES (%s,'a','d',3,0,1,0.3333,%s,true)")
    assert not fails(conn, ok, (aid, 2))
    assert fails(conn, ok, (aid, -1)), "blockers_resolved >= 0"
    assert conn.execute("SELECT blockers_resolved FROM recommendations WHERE assessment_id=%s", (aid,)).fetchone()[0] == 2


# ------------------------------------------------------------------ R13 (a) canvas edit after the lock
@pytest.mark.parametrize("target", ["assessed", "challenged", "validated"])
def test_canvas_edit_after_the_lock_marks_stale_and_returns_to_evidence_gathered(conn, ids, target):
    did = assessed(conn, ids)
    if target in ("challenged", "validated"):
        advance(conn, did, "challenged")
    if target == "validated":
        advance(conn, did, "validated")
    assert stage(conn, did) == (target, False)
    conn.execute("UPDATE decisions SET hypothesis = 'If we do Z then retention increases.' WHERE id = %s", (did,))
    assert stage(conn, did) == ("evidence_gathered", True)


@pytest.mark.parametrize("column,value", [
    ("title", "'A changed title'"), ("description", "'changed'"), ("risk_level", "'high'"),
    ("current_evidence_notes", "'new notes'"), ("decision_due_date", "'2027-01-01'"), ("decision_type", "'pricing_change'"),
    ("change_my_mind_criteria", "'[\"A different criterion that is long enough\"]'::jsonb"),
])
def test_every_canvas_column_triggers_the_stale_rule(conn, ids, column, value):
    did = assessed(conn, ids)
    conn.execute(f"UPDATE decisions SET {column} = {value} WHERE id = %s", (did,))
    assert stage(conn, did) == ("evidence_gathered", True)


def test_non_canvas_updates_and_pre_lock_edits_do_not_mark_stale(conn, ids):
    did = assessed(conn, ids)
    conn.execute("UPDATE decisions SET scenario_key = 'tag' WHERE id = %s", (did,))
    assert stage(conn, did) == ("assessed", False)
    unlocked = new_decision(conn, ids)
    conn.execute("UPDATE decisions SET title = 'edited before any lock' WHERE id = %s", (unlocked,))
    assert stage(conn, unlocked) == ("created", False)
    advance(conn, unlocked, "evidence_gathered")
    conn.execute("UPDATE decisions SET title = 'edited again before any lock' WHERE id = %s", (unlocked,))
    assert stage(conn, unlocked) == ("evidence_gathered", False)


# ------------------------------------------------------------------ R13 (c) assessed requires an assessment row
def test_assessed_requires_a_non_partial_assessment_row(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    to_assessed = "UPDATE decisions SET lifecycle_stage='assessed', canvas_locked_at='2026-10-01T09:00:00Z' WHERE id=%s"
    assert fails(conn, to_assessed, (did,)), "no assessment row at all"
    conn.execute("INSERT INTO decision_assessments (decision_id, version, state, params_version, " + ASSESSMENT_META + ", is_synthetic)"
                 " VALUES (%s,1,'partial','v','h','f','2026-10-01',true)", (did,))
    assert fails(conn, to_assessed, (did,)), "a partial assessment does not count"
    add_scored_assessment(conn, did, version=2)
    assert not fails(conn, to_assessed, (did,))


# ------------------------------------------------------------------ R13 (b) decided decisions reject every write
def decided(conn, ids):
    did = assessed(conn, ids)
    advance(conn, did, "challenged")
    advance(conn, did, "validated")
    conn.execute("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic)"
                 " VALUES (%s,%s,'approve','fine',true)", (did, ids.executive))
    advance(conn, did, "decided")
    return did


def test_every_guarded_table_rejects_writes_once_the_decision_is_decided(conn, ids):
    live = new_decision(conn, ids, title="Live decision")
    advance(conn, live, "evidence_gathered")
    live_a = add_scored_assessment(conn, live)
    did = decided(conn, ids)
    aid = conn.execute("SELECT id FROM decision_assessments WHERE decision_id=%s", (did,)).fetchone()[0]
    # every guarded table refuses an INSERT for the decided decision
    inserts = {
        "evidence": ("INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                     " observed_start, observed_end, created_by, is_synthetic) VALUES (%s,%s,'behavioral','s','supports','B',"
                     "'2026-09-01','2026-09-02','user',true)", (did, ids.es_events)),
        "decision_assessments": ("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, "
                                 + ASSESSMENT_META + ", is_synthetic) VALUES (%s,9,'insufficient_evidence','[1]','v','h','f','2026-10-01',true)", (did,)),
        "recommendations": ("INSERT INTO recommendations (assessment_id, action_type, description, effort_days, expected_reduction,"
                            " relevance, priority_score, is_synthetic) VALUES (%s,'a','d',1,0,1,0,true)", (aid,)),
        "decision_reviews": ("INSERT INTO decision_reviews (assessment_id, reviewer_type, reviewer_id, verdict, is_synthetic)"
                             " VALUES (%s,'human',%s,'ready',true)", (aid, ids.executive)),
        "dq_checks": ("INSERT INTO dq_checks (assessment_id, data_source_id, check_type, severity, finding, is_synthetic)"
                      " VALUES (%s,(SELECT id FROM data_sources LIMIT 1),'t','warn','f',true)", (aid,)),
        "analysis_results": ("INSERT INTO analysis_results (decision_id, analysis_type, is_synthetic) VALUES (%s,'trend',true)", (did,)),
        "claims": ("INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic)"
                   " VALUES (%s,'c','descriptive','supports','low',true)", (aid,)),
        "agent_runs": ("INSERT INTO agent_runs (decision_id, agent_name, status, is_synthetic) VALUES (%s,'orchestrator','succeeded',true)", (did,)),
    }
    for table, (sql, params) in inserts.items():
        assert fails(conn, sql, params), f"{table} accepted an insert for a decided decision"
    # the same inserts are fine for a decision that is not decided
    assert not fails(conn, inserts["evidence"][0], (live, ids.es_events))
    assert not fails(conn, inserts["decision_reviews"][0], (live_a, ids.executive))
    assert not fails(conn, inserts["agent_runs"][0], (live,))
    # updates and deletes of existing rows are rejected too
    assert fails(conn, "UPDATE decision_assessments SET narrative='x' WHERE id=%s", (aid,))
    assert fails(conn, "DELETE FROM decision_assessments WHERE id=%s", (aid,))
    # audit_logs stays insert-only and is still allowed
    assert not fails(conn, "INSERT INTO audit_logs (org_id, actor_type, action, entity_type, entity_id, is_synthetic)"
                           " VALUES (%s,'system','probe','decision',%s,true)", (ids.org, did))


# ------------------------------------------------------------------ assessments can never be deleted (PO correction)
@pytest.mark.parametrize("target", ["evidence_gathered", "assessed", "challenged", "validated"])
def test_assessment_delete_is_rejected_at_every_lifecycle_stage(conn, ids, target):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    aid = add_scored_assessment(conn, did)
    if target != "evidence_gathered":
        advance(conn, did, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    if target in ("challenged", "validated"):
        advance(conn, did, "challenged")
    if target == "validated":
        advance(conn, did, "validated")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="cannot be deleted"):
        with conn.transaction():
            conn.execute("DELETE FROM decision_assessments WHERE id = %s", (aid,))
    assert conn.execute("SELECT count(*) FROM decision_assessments WHERE id=%s", (aid,)).fetchone()[0] == 1


# ------------------------------------------------------------------ 40. assessment immutability (PO rule 3.4d)
PROTECTED = [
    ("version", "99"), ("state", "'partial'"), ("ddi_score", "11.5"), ("ddi_band", "'critical'"),
    ("dimension_scores", "'{\"changed\": true}'::jsonb"), ("penalty_scores", "'{\"changed\": true}'::jsonb"),
    ("blocking_reasons", "'[\"changed\"]'::jsonb"), ("sensitivity", "'{\"band_stable\": false}'::jsonb"),
    ("params_version", "'other_version'"), ("params_hash", "'other_hash'"), ("nbe_params_version", "'nbe_other'"),
    ("nbe_params_hash", "'nbe_other_hash'"), ("evidence_fingerprint", "'other_fingerprint'"), ("as_of_date", "'2027-01-01'"),
    ("decision_id", "(SELECT id FROM decisions WHERE id <> %(own)s LIMIT 1)"),
]


@pytest.mark.parametrize("column,value", PROTECTED)
def test_40_protected_assessment_columns_cannot_be_updated(conn, ids, column, value):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    aid = add_scored_assessment(conn, did)
    sql = f"UPDATE decision_assessments SET {column} = {value} WHERE id = %(id)s"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="immutable"):
        with conn.transaction():
            conn.execute(sql, {"id": aid, "own": did})
    row = conn.execute("SELECT version, state::text, ddi_score FROM decision_assessments WHERE id=%s", (aid,)).fetchone()
    assert (row[0], row[1], float(row[2])) == (1, "scored", 10.0)


def test_40_narrative_and_brief_md_may_change_and_a_no_op_update_is_allowed(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    aid = add_scored_assessment(conn, did)
    conn.execute("UPDATE decision_assessments SET narrative = 'later narrative', brief_md = '# brief' WHERE id = %s", (aid,))
    assert conn.execute("SELECT narrative, brief_md FROM decision_assessments WHERE id=%s", (aid,)).fetchone() == ("later narrative", "# brief")
    conn.execute("UPDATE decision_assessments SET version = version, ddi_score = ddi_score WHERE id = %s", (aid,))
