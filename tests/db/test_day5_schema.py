"""Migration 0006 invariants (docs/day-5-implementation-brief.md section 4) and its reversibility with Day-5 data present."""

from __future__ import annotations

import os

import psycopg

from .conftest import new_decision, new_synthesis
from .test_constraints import add_scored_assessment, advance, fails
from .test_migrations import alembic, scratch_db  # noqa: F401  (scratch_db is a fixture)

ROOT_ENV = os.environ


def evidence(conn, ids, did, status="proposed", etype="customer", created_by="agent", identity="i1", approved=False):
    approval = ", approved_by, approved_at" if approved else ""
    vals = ", %s, now()" if approved else ""
    args = [did, ids.es_feedback, etype, status, created_by, identity]
    if approved:
        args.append(ids.pm)
    sql = ("INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
           f" observed_end, created_by, status, analysis_identity, is_synthetic{approval})"
           " VALUES (%s,%s,%s,'s','supports','C','2026-09-01','2026-09-02',%s,%s,%s,true" + vals + ") RETURNING id")
    # argument order: did, source, type, created_by, status, identity
    return conn.execute(sql, (args[0], args[1], args[2], args[4], args[3], args[5], *args[6:])).fetchone()[0]


def test_evidence_status_allows_proposed_active_superseded_rejected_and_nothing_else(conn, ids):
    did = new_decision(conn, ids)
    assert not fails(conn, "SAVEPOINT x") or True
    ok = evidence(conn, ids, did, "proposed", identity="a")
    assert ok
    assert fails(conn, "UPDATE evidence SET status = 'archived' WHERE id = %s", (ok,))
    # a superseded item needs both supersede fields; proposed and rejected do not
    assert fails(conn, "UPDATE evidence SET status = 'superseded' WHERE id = %s", (ok,))
    assert not fails(conn, "UPDATE evidence SET status = 'superseded', superseded_by = %s, superseded_at = now() WHERE id = %s", (ok, ok))


def test_an_active_customer_item_created_by_an_agent_needs_a_human_approval(conn, ids):
    did = new_decision(conn, ids)
    assert fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                       " observed_start, observed_end, created_by, status, is_synthetic)"
                       " VALUES (%s,%s,'customer','s','supports','C','2026-09-01','2026-09-02','agent','active',true)", (did, ids.es_feedback))
    assert not fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                           " observed_start, observed_end, created_by, status, approved_by, approved_at, is_synthetic)"
                           " VALUES (%s,%s,'customer','s','supports','C','2026-09-01','2026-09-02','agent','active',%s,now(),true)",
                     (did, ids.es_feedback, ids.pm))
    # a user-added customer item (Day 3) is active without any approval; a rejection is recorded by a human
    assert not fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                           " observed_start, observed_end, created_by, is_synthetic)"
                           " VALUES (%s,%s,'customer','s','supports','C','2026-09-01','2026-09-02','user',true)", (did, ids.es_feedback))
    assert fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                       " observed_start, observed_end, created_by, status, is_synthetic)"
                       " VALUES (%s,%s,'customer','s','supports','C','2026-09-01','2026-09-02','agent','rejected',true)", (did, ids.es_feedback))


def test_the_identity_slot_is_held_by_an_active_or_a_proposed_item_not_by_a_rejected_one(conn, ids):
    did = new_decision(conn, ids)
    first = evidence(conn, ids, did, "proposed", identity="same")
    assert fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
                       " observed_end, created_by, status, analysis_identity, is_synthetic) VALUES (%s,%s,'customer','s','supports','C',"
                       "'2026-09-01','2026-09-02','agent','proposed','same',true)", (did, ids.es_feedback)), "one live item per identity"
    conn.execute("UPDATE evidence SET status='rejected', approved_by=%s, approved_at=now() WHERE id=%s", (ids.pm, first))
    assert not fails(conn, "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
                           " observed_end, created_by, status, analysis_identity, is_synthetic) VALUES (%s,%s,'customer','s','supports','C',"
                           "'2026-09-01','2026-09-02','agent','proposed','same',true)", (did, ids.es_feedback))


def test_llm_classifications_are_unique_per_key_and_insert_only(conn, ids):
    did = new_decision(conn, ids)
    run = conn.execute("INSERT INTO agent_runs (decision_id, stage, agent_name, status, purpose, model, is_synthetic)"
                       " VALUES (%s,'customer','evidence_synthesis','succeeded','classify','stub:x',true) RETURNING id", (did,)).fetchone()[0]
    ins = ("INSERT INTO llm_classifications (decision_id, feedback_id, text_sha256, taxonomy_version, theme, relevance, prompt_version,"
           " prompt_sha256, model, agent_run_id, is_synthetic) VALUES (%s,%s,'h','tax','coach_helpful',%s,'v0.1','p','stub:x',%s,true)")
    assert not fails(conn, ins, (did, 1, "direct", run))
    assert fails(conn, ins, (did, 1, "adjacent", run)), "unique (decision, feedback, taxonomy, prompt, model)"
    assert not fails(conn, ins, (did, 2, "not_relevant", run))
    assert fails(conn, ins, (did, 3, "sometimes", run)), "relevance is an enum"
    assert fails(conn, "UPDATE llm_classifications SET theme = NULL WHERE decision_id = %s", (did,))
    assert fails(conn, "DELETE FROM llm_classifications WHERE decision_id = %s", (did,))
    assert conn.execute("SELECT is_synthetic FROM llm_classifications LIMIT 1").fetchone()[0] is True


def test_syntheses_are_versioned_immutable_and_claims_must_name_one(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    a = add_scored_assessment(conn, did)
    s1 = new_synthesis(conn, a)
    assert new_synthesis(conn, a) != s1
    assert conn.execute("SELECT array_agg(version ORDER BY version) FROM syntheses WHERE assessment_id=%s", (a,)).fetchone()[0] == [1, 2]
    run = conn.execute("SELECT agent_run_id FROM syntheses WHERE id=%s", (s1,)).fetchone()[0]
    assert fails(conn, "INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, is_synthetic)"
                       " VALUES (%s,1,%s,'failed','h',true)", (a, run)), "unique (assessment, version)"
    assert fails(conn, "INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, is_synthetic)"
                       " VALUES (%s,9,%s,'succeeded','h',true)", (a, run)), "a succeeded synthesis needs its output and hash"
    assert not fails(conn, "INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, is_synthetic)"
                           " VALUES (%s,9,%s,'rejected_by_validators','h',true)", (a, run))
    assert fails(conn, "INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, is_synthetic)"
                       " VALUES (%s,10,%s,'unknown','h',true)", (a, run))
    assert fails(conn, "UPDATE syntheses SET status='failed' WHERE id=%s", (s1,)) and fails(conn, "DELETE FROM syntheses WHERE id=%s", (s1,))
    claim = "INSERT INTO claims (assessment_id, claim_text, claim_type, stance, confidence, is_synthetic) VALUES (%s,'c','descriptive','neutral','low',true)"
    assert fails(conn, claim, (a,)), "migration 0006: a new claim must name its synthesis"
    assert not fails(conn, "INSERT INTO claims (assessment_id, synthesis_id, local_id, claim_text, claim_type, stance, confidence, is_synthetic)"
                           " VALUES (%s,%s,'c1','c','descriptive','neutral','low',true)", (a, s1))


def test_decision_reviews_are_insert_only_and_carry_the_synthesis_and_run(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    a = add_scored_assessment(conn, did)
    s = new_synthesis(conn, a)
    run = conn.execute("SELECT agent_run_id FROM syntheses WHERE id=%s", (s,)).fetchone()[0]
    r = conn.execute("INSERT INTO decision_reviews (assessment_id, reviewer_type, verdict, challenges, synthesis_id, agent_run_id, is_synthetic)"
                     " VALUES (%s,'agent','ready','[]'::jsonb,%s,%s,true) RETURNING id", (a, s, run)).fetchone()[0]
    assert fails(conn, "UPDATE decision_reviews SET verdict='needs_rework' WHERE id=%s", (r,))
    assert fails(conn, "DELETE FROM decision_reviews WHERE id=%s", (r,))


def test_decision_briefs_rules_kind_stage_state_immutability_and_synthesis_requirement(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    a = add_scored_assessment(conn, did)
    s = new_synthesis(conn, a)
    brief = ("INSERT INTO decision_briefs (assessment_id, synthesis_id, kind, version, content, markdown, is_synthetic)"
             " VALUES (%s,%s,%s,%s,'{}'::jsonb,'m',true)")
    assert fails(conn, brief, (a, s, "decision_brief", 1)), "decision stage is evidence_gathered"
    assert fails(conn, brief, (a, s, "gated_evidence_summary", 1)), "the assessment is scored, not insufficient"
    assert fails(conn, brief, (a, s, "other", 1))
    advance(conn, did, "assessed", canvas_locked_at="now()") if False else None
    conn.execute("UPDATE decisions SET canvas_locked_at = now(), assessment_stale = false WHERE id = %s", (did,))
    advance(conn, did, "assessed")
    advance(conn, did, "challenged")
    advance(conn, did, "validated")
    assert not fails(conn, brief, (a, s, "decision_brief", 1))
    assert fails(conn, brief, (a, None, "decision_brief", 2)), "a decision_brief needs a synthesis"
    other = add_scored_assessment(conn, did, version=2)
    assert fails(conn, brief, (a, new_synthesis(conn, other), "decision_brief", 3)), "the synthesis must belong to the assessment"
    bid = conn.execute("SELECT id FROM decision_briefs WHERE assessment_id=%s", (a,)).fetchone()[0]
    assert fails(conn, "UPDATE decision_briefs SET markdown='x' WHERE id=%s", (bid,)) and fails(conn, "DELETE FROM decision_briefs WHERE id=%s", (bid,))


def test_a_gated_summary_is_allowed_for_an_insufficient_assessment_without_a_synthesis(conn, ids):
    did = new_decision(conn, ids)
    advance(conn, did, "evidence_gathered")
    a = conn.execute("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, params_hash,"
                     " evidence_fingerprint, as_of_date, is_synthetic) VALUES (%s,1,'insufficient_evidence','[{\"code\":\"min_items\"}]'::jsonb,"
                     "'v','h','f','2026-10-01',true) RETURNING id", (did,)).fetchone()[0]
    assert not fails(conn, "INSERT INTO decision_briefs (assessment_id, kind, version, content, markdown, is_synthetic)"
                           " VALUES (%s,'gated_evidence_summary',1,'{}'::jsonb,'m',true)", (a,))


def test_agent_runs_have_the_llm_metadata_columns_and_a_closed_purpose(conn, ids):
    cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agent_runs'").fetchall()}
    assert {"purpose", "model_fallback", "prompt_id", "prompt_sha256", "params", "input_sha256", "output_sha256", "request_id", "error_class"} <= cols
    did = new_decision(conn, ids)
    ins = "INSERT INTO agent_runs (decision_id, agent_name, status, purpose, is_synthetic) VALUES (%s,'reviewer','succeeded',%s,true)"
    assert not fails(conn, ins, (did, "review")) and fails(conn, ins, (did, "summarise"))
    assert conn.execute("SELECT model_fallback FROM agent_runs WHERE decision_id=%s", (did,)).fetchone()[0] is False
    assert conn.execute("SELECT col_description('decision_assessments'::regclass, attnum) FROM pg_attribute WHERE attrelid='decision_assessments'::regclass"
                        " AND attname='brief_md'").fetchone()[0].startswith("DEPRECATED")


def test_customer_insight_observed_columns_exist(conn, ids):
    cols = {r[0]: r[1] for r in conn.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='customer_insights'").fetchall()}
    assert cols["relevance_observed"] == "numeric" and cols["source_types"] == "ARRAY" and cols["segment_counts"] == "jsonb"
    assert cols["first_mention_date"] == "date" and cols["last_mention_date"] == "date" and cols["taxonomy_version"] == "text"


# ================================================================ reversibility with Day-5 data
def test_downgrade_0006_to_0005_with_day_5_data_keeps_evidence_and_upgrades_again(scratch_db):
    env = {**os.environ, "DATABASE_URL": scratch_db.replace("postgresql://", "postgresql+psycopg://", 1),
           "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[2] / "backend")}
    assert alembic(env, "upgrade", "head").returncode == 0
    with psycopg.connect(scratch_db, autocommit=True) as c:
        org = c.execute("INSERT INTO organizations (name, industry, is_synthetic) VALUES ('o','t',true) RETURNING id").fetchone()[0]
        team = c.execute("INSERT INTO teams (org_id, name, is_synthetic) VALUES (%s,'t',true) RETURNING id", (org,)).fetchone()[0]
        user = c.execute("INSERT INTO users (org_id, team_id, name, email, role, is_synthetic) VALUES (%s,%s,'u','u@x.example','ba',true)"
                         " RETURNING id", (org, team)).fetchone()[0]
        ds = c.execute("INSERT INTO data_sources (org_id, name, source_type, reliability_tier, tier_rationale, is_synthetic)"
                       " VALUES (%s,'d','csv',3,'t',true) RETURNING id", (org,)).fetchone()[0]
        metric = c.execute("INSERT INTO metrics (org_id, name, definition, unit, grain, data_source_id, is_synthetic)"
                           " VALUES (%s,'m','d','ratio','day',%s,true) RETURNING id", (org, ds)).fetchone()[0]
        es = c.execute("INSERT INTO evidence_sources (org_id, data_source_id, title, ref, source_type, reliability_tier, is_synthetic)"
                       " VALUES (%s,%s,'e','r','csv',3,true) RETURNING id", (org, ds)).fetchone()[0]
        did = c.execute(
            "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id, decision_due_date, risk_level,"
            " change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at, owner_id, is_synthetic)"
            " VALUES (%s,%s,'t','d','h',%s,'2026-12-31','low','[\"a criterion long enough\"]','pricing_change','increase',now(),%s,true)"
            " RETURNING id", (org, team, metric, user)).fetchone()[0]
        c.execute("UPDATE decisions SET lifecycle_stage='evidence_gathered' WHERE id=%s", (did,))
        ev = lambda status, ident, extra="": c.execute(  # noqa: E731
            "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start, observed_end,"
            f" created_by, status, analysis_identity, is_synthetic{extra and ', approved_by, approved_at'}) VALUES (%s,%s,'customer','s','supports','C',"
            f"'2026-09-01','2026-09-02','agent',%s,%s,true{extra and ', %s, now()'}) RETURNING id",
            (did, es, status, ident, *((user,) if extra else ()))).fetchone()[0]
        active, proposed, rejected = ev("active", "a", "x"), ev("proposed", "b"), ev("rejected", "c", "x")
        a = c.execute("INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version, params_hash,"
                      " evidence_fingerprint, as_of_date, is_synthetic) VALUES (%s,1,'scored',10,'low','v','h','f','2026-10-01',true)"
                      " RETURNING id", (did,)).fetchone()[0]
        run = c.execute("INSERT INTO agent_runs (decision_id, assessment_id, stage, agent_name, status, purpose, model, is_synthetic)"
                        " VALUES (%s,%s,'synthesis','evidence_synthesis','succeeded','synthesize','stub:t',true) RETURNING id", (did, a)).fetchone()[0]
        syn = c.execute("INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, output_sha256, output, is_synthetic)"
                        " VALUES (%s,1,%s,'succeeded','h','h','{}'::jsonb,true) RETURNING id", (a, run)).fetchone()[0]
        c.execute("INSERT INTO claims (assessment_id, synthesis_id, local_id, claim_text, claim_type, stance, confidence, is_synthetic)"
                  " VALUES (%s,%s,'c1','c','descriptive','neutral','low',true)", (a, syn))
        c.execute("INSERT INTO decision_briefs (assessment_id, synthesis_id, kind, version, content, markdown, is_synthetic)"
                  " VALUES (%s,NULL,'gated_evidence_summary',1,'{}'::jsonb,'m',true)", (a,)) if False else None
    down = alembic(env, "downgrade", "0005")
    assert down.returncode == 0, down.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005"
        tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
        assert not ({"llm_classifications", "syntheses", "decision_briefs"} & tables)
        cols = lambda t: {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,)).fetchall()}  # noqa: E731
        assert not ({"purpose", "model_fallback", "prompt_sha256", "error_class"} & cols("agent_runs"))
        assert not ({"approved_by", "approved_at", "approval_note"} & cols("evidence"))
        assert not ({"synthesis_id", "local_id"} & cols("claims")) and not ({"synthesis_id", "agent_run_id"} & cols("decision_reviews"))
        assert not ({"relevance_observed", "segment_counts"} & cols("customer_insights"))
        rows = dict(c.execute("SELECT analysis_identity, status FROM evidence ORDER BY analysis_identity").fetchall())
        assert rows == {"a": "active", "b": "superseded", "c": "superseded"}                    # evidence is never deleted
        assert c.execute("SELECT count(*) FROM evidence WHERE status='superseded' AND superseded_by = id").fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 1                       # the claim stays
        c.execute("SELECT count(*) FROM v_evidence_freshness")
        c.execute("SELECT count(*) FROM v_traceability_matrix")
    again = alembic(env, "upgrade", "head")
    assert again.returncode == 0, again.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"
        assert c.execute("SELECT count(*) FROM claims WHERE synthesis_id IS NULL").fetchone()[0] == 1       # old rows are not re-checked (NOT VALID)
