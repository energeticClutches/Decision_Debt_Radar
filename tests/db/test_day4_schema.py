"""Migration 0005 (Day 4) invariants. Every statement runs in a rolled-back transaction."""

import psycopg
import pytest

from .conftest import new_decision
from .test_constraints import ASSESSMENT_META, add_scored_assessment, advance, fails
from .test_day3_guards import decided


def ev_insert(identity="id-1", status_cols="", status_vals=""):
    return ("INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
            " observed_end, created_by, is_synthetic, analysis_identity" + status_cols + ") VALUES (%s,%s,'behavioral','s','supports','B',"
            "'2026-09-01','2026-09-02','agent',true,'" + identity + "'" + status_vals + ") RETURNING id")


def dq_insert(key="k1"):
    return ("INSERT INTO dq_checks (decision_id, data_source_id, check_type, severity, finding, check_key, target, is_synthetic)"
            " VALUES (%s,(SELECT id FROM data_sources LIMIT 1),'volume','warn','f','" + key + "','t',true) RETURNING id")


# ------------------------------------------------------------------ decisions.expected_direction (D4-20, O1)
def test_expected_direction_is_required_and_limited_to_the_three_values(conn, ids):
    for value in ("increase", "decrease", "no_material_decrease"):
        assert new_decision(conn, ids, expected_direction=value)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            new_decision(conn, ids, expected_direction="sideways")
    with pytest.raises(psycopg.errors.NotNullViolation):
        with conn.transaction():
            conn.execute("INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id, decision_due_date,"
                         " risk_level, change_my_mind_criteria, decision_type, canvas_completed_at, owner_id, is_synthetic)"
                         " VALUES (%s,%s,'t','d','h',%s,'2026-12-31','low','[\"a criterion long enough\"]','pricing_change',now(),%s,true)",
                         (ids.org, ids.team, ids.metric, ids.pm))


def test_the_seeded_decisions_carry_the_o1_values(conn, ids):
    rows = dict(conn.execute("SELECT scenario_key, expected_direction FROM decisions WHERE scenario_key IS NOT NULL").fetchall())
    assert rows == {"ai_coach": "increase", "onboarding": "increase", "community": "increase", "pricing": "no_material_decrease"}


# ------------------------------------------------------------------ dq_checks per decision (D4-01/02/03)
def test_dq_checks_belong_to_a_decision_the_assessment_link_is_optional_and_check_keys_are_unique_per_decision(conn, ids):
    d1, d2 = new_decision(conn, ids), new_decision(conn, ids)
    assert not fails(conn, dq_insert("k1"), (d1,))
    assert fails(conn, dq_insert("k1"), (d1,)), "UNIQUE(decision_id, check_key)"
    assert not fails(conn, dq_insert("k1"), (d2,)), "the same key is fine for another decision"
    assert fails(conn, "INSERT INTO dq_checks (decision_id, data_source_id, check_type, severity, finding, target, is_synthetic)"
                       " VALUES (%s,(SELECT id FROM data_sources LIMIT 1),'v','warn','f','t',true)", (d1,)), "check_key is required"
    assert fails(conn, "INSERT INTO dq_checks (decision_id, data_source_id, check_type, severity, finding, check_key, is_synthetic)"
                       " VALUES (%s,(SELECT id FROM data_sources LIMIT 1),'v','warn','f','k9',true)", (d1,)), "target is required"
    assert fails(conn, "INSERT INTO dq_checks (data_source_id, check_type, severity, finding, check_key, target, is_synthetic)"
                       " VALUES ((SELECT id FROM data_sources LIMIT 1),'v','warn','f','k9','t',true)"), "decision_id is required"
    row = conn.execute("SELECT assessment_id, affects_success_metric, observed_value, threshold, source_snapshot, last_run_at FROM dq_checks"
                       " WHERE decision_id=%s", (d1,)).fetchone()
    assert row == (None, False, None, None, None, None)


def test_dq_checks_decided_guard_is_repointed_to_decision_id(conn, ids):
    did = decided(conn, ids)
    live = new_decision(conn, ids)
    assert fails(conn, dq_insert("blocked"), (did,)), "a check without an assessment link is still guarded through decision_id"
    assert not fails(conn, dq_insert("allowed"), (live,))
    # an existing check of a decision that is then decided can no longer change or be deleted
    d = new_decision(conn, ids)
    advance(conn, d, "evidence_gathered")
    add_scored_assessment(conn, d)
    cid = conn.execute(dq_insert("will-freeze"), (d,)).fetchone()[0]
    advance(conn, d, "assessed", canvas_locked_at="2026-10-01T09:00:00Z")
    advance(conn, d, "challenged")
    advance(conn, d, "validated")
    conn.execute("INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic) VALUES (%s,%s,'approve','ok',true)",
                 (d, ids.executive))
    advance(conn, d, "decided")
    assert fails(conn, "UPDATE dq_checks SET status='accepted' WHERE id=%s", (cid,))
    assert fails(conn, "DELETE FROM dq_checks WHERE id=%s", (cid,))


# ------------------------------------------------------------------ experiments and results (D4-12, D4-14)
def test_experiment_inputs_and_the_results_upsert_target(conn, ids):
    did = new_decision(conn, ids)
    base = ("INSERT INTO experiments (org_id, decision_id, name, hypothesis, design, start_date, status, planned_treatment_share,"
            " control_variant, outcome_key, is_synthetic) VALUES (%s,%s,'e','h','rct','2026-05-01','completed',%s,'control','conv',true)"
            " RETURNING id")
    assert not fails(conn, base, (ids.org, did, 0.5))
    assert not fails(conn, base, (ids.org, did, None)), "no planned share is allowed (the SRM flag is then NULL)"
    for bad in (0, 1, 1.5, -0.2):
        assert fails(conn, base, (ids.org, did, bad)), f"planned_treatment_share {bad}"
    eid = conn.execute(base, (ids.org, did, 0.5)).fetchone()[0]
    ins = "INSERT INTO experiment_results (experiment_id, variant, n, is_synthetic) VALUES (%s,%s,10,true)"
    assert not fails(conn, ins, (eid, "control"))
    assert fails(conn, ins, (eid, "control")), "UNIQUE(experiment_id, variant)"
    assert not fails(conn, ins, (eid, "treatment"))


# ------------------------------------------------------------------ evidence status (D4-16/19)
def test_evidence_status_supersede_fields_and_the_active_identity_index(conn, ids):
    did = new_decision(conn, ids)
    e1 = conn.execute(ev_insert("same"), (did, ids.es_events)).fetchone()[0]
    assert conn.execute("SELECT status, superseded_by, superseded_at FROM evidence WHERE id=%s", (e1,)).fetchone() == ("active", None, None)
    assert fails(conn, ev_insert("same"), (did, ids.es_events)), "one ACTIVE item per (decision, analysis_identity)"
    assert not fails(conn, ev_insert("other"), (did, ids.es_events))
    assert not fails(conn, ev_insert("x"), (did, ids.es_events))
    other = new_decision(conn, ids)
    assert not fails(conn, ev_insert("same"), (other, ids.es_events)), "the same identity is fine for another decision"
    # items without an identity (manual evidence) are never constrained
    manual = "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start, observed_end, created_by, is_synthetic) VALUES (%s,%s,'customer','s','supports','B','2026-09-01','2026-09-02','user',true)"
    assert not fails(conn, manual, (did, ids.es_feedback)) and not fails(conn, manual, (did, ids.es_feedback))
    # superseding frees the identity, needs both fields, and the status is limited to two values
    e2 = conn.execute(ev_insert("new-id"), (did, ids.es_events)).fetchone()[0]
    assert fails(conn, "UPDATE evidence SET status='superseded' WHERE id=%s", (e1,)), "superseded_by and superseded_at are required"
    assert fails(conn, "UPDATE evidence SET status='superseded', superseded_by=%s WHERE id=%s", (e2, e1))
    assert fails(conn, "UPDATE evidence SET status='archived' WHERE id=%s", (e1,))
    assert not fails(conn, "UPDATE evidence SET status='superseded', superseded_by=%s, superseded_at=now() WHERE id=%s", (e2, e1))
    assert not fails(conn, ev_insert("same"), (did, ids.es_events)), "after superseding, the identity can be active again"
    assert conn.execute("SELECT count(*) FROM evidence WHERE id=%s", (e1,)).fetchone()[0] == 1       # never deleted


def test_the_views_count_only_active_evidence_and_the_matrix_keeps_every_row(conn, ids):
    did = new_decision(conn, ids, title="Active evidence view fixture")
    old = conn.execute(ev_insert("a"), (did, ids.es_events)).fetchone()[0]
    new = conn.execute(ev_insert("b"), (did, ids.es_events)).fetchone()[0]
    conn.execute("UPDATE evidence SET status='superseded', superseded_by=%s, superseded_at=now() WHERE id=%s", (new, old))
    assert conn.execute("SELECT count(*) FROM v_evidence_freshness WHERE decision_id=%s", (did,)).fetchone()[0] == 1
    assert conn.execute("SELECT evidence_id FROM v_evidence_freshness WHERE decision_id=%s", (did,)).fetchone()[0] == new
    a = conn.execute("INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version, " + ASSESSMENT_META +
                     ", is_synthetic) VALUES (%s,1,'scored',10,'low','v','h','f','2026-10-01',true) RETURNING id", (did,)).fetchone()[0]
    claim = conn.execute("INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic)"
                         " VALUES (%s,'c','descriptive','neutral','low',true) RETURNING id", (a,)).fetchone()[0]
    for e in (old, new):
        conn.execute("INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (%s,%s,true)", (claim, e))
    rows = dict(conn.execute("SELECT evidence_id, evidence_status FROM v_traceability_matrix WHERE claim_id=%s", (claim,)).fetchall())
    assert rows == {old: "superseded", new: "active"}                                  # historical claims still resolve
    # evidence health counts the active item only: one item within its half-life
    share = conn.execute("SELECT value FROM v_evidence_health WHERE metric_name='share_items_within_half_life' AND decision_type="
                         "'product_feature_investment' AND team_id IS NOT NULL").fetchone()
    assert share is not None


# ------------------------------------------------------------------ analysis_results (D4-15)
def test_analysis_results_are_historical_only_agent_run_id_may_change(conn, ids):
    did = new_decision(conn, ids)
    aid = conn.execute("INSERT INTO analysis_results (decision_id, analysis_type, params, n, analysis_identity, params_hash, source_fingerprint,"
                       " is_synthetic) VALUES (%s,'trend','{}'::jsonb,5,'i','p','s',true) RETURNING id", (did,)).fetchone()[0]
    for col, val in (("n", "6"), ("analysis_identity", "'x'"), ("params_hash", "'x'"), ("source_fingerprint", "'x'"),
                     ("result", "'{\"a\": 1}'::jsonb"), ("params", "'{\"a\": 1}'::jsonb"), ("limitations", "'x'"), ("dq_status", "'warn'"),
                     ("query_text", "'select 1'"), ("analysis_type", "'funnel'")):
        assert fails(conn, f"UPDATE analysis_results SET {col} = {val} WHERE id = %s", (aid,)), col
    run = conn.execute("INSERT INTO agent_runs (decision_id, agent_name, status, is_synthetic) VALUES (%s,'data_analytics','succeeded',true)"
                       " RETURNING id", (did,)).fetchone()[0]
    assert not fails(conn, "UPDATE analysis_results SET agent_run_id = %s WHERE id = %s", (run, aid))
    assert not fails(conn, "UPDATE analysis_results SET n = n WHERE id = %s", (aid,))                 # a no-op update is allowed


# ------------------------------------------------------------------ the read-only role
def test_the_readonly_role_reads_metric_observations_and_nothing_else_new(conn, ids):
    assert conn.execute("SELECT has_table_privilege('ddr_readonly', 'public.metric_observations', 'SELECT')").fetchone()[0] is True
    assert conn.execute("SELECT has_table_privilege('ddr_readonly', 'public.metric_observations', 'INSERT')").fetchone()[0] is False
    for table in ("decisions", "evidence", "dq_checks", "analysis_results", "decision_assessments", "audit_logs", "users"):
        assert conn.execute("SELECT has_table_privilege('ddr_readonly', %s, 'SELECT')", (f"public.{table}",)).fetchone()[0] is False, table
    assert conn.execute("SELECT has_table_privilege('ddr_readonly', 'fc_.feedback_ground_truth', 'SELECT')").fetchone()[0] is False
    assert conn.execute("SELECT has_table_privilege('ddr_readonly', 'fc_.users', 'SELECT')").fetchone()[0] is False
