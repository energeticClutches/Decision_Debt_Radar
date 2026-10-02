"""Alembic migration from an empty PostgreSQL database (and back), on a throwaway database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]


def alembic(env, *args):
    return subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", *args], cwd=ROOT / "database",
                          env=env, capture_output=True, text=True, timeout=300)


@pytest.fixture()
def scratch_db(dsn):
    name = f"ddr_migtest_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(f"CREATE DATABASE {name}")
    base = dsn.rsplit("/", 1)[0]
    url = f"{base}/{name}"
    try:
        yield url
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


def test_upgrade_from_empty_database_then_downgrade_to_base(scratch_db):
    env = {**os.environ, "DATABASE_URL": scratch_db.replace("postgresql://", "postgresql+psycopg://", 1),
           "PYTHONPATH": str(ROOT / "backend")}
    up = alembic(env, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005"
        assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' "
                         "AND table_name <> 'alembic_version'").fetchone()[0] == 22
        assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='fc_' AND table_type='BASE TABLE'").fetchone()[0] == 9
        assert c.execute("SELECT count(*) FROM information_schema.views WHERE table_schema IN ('public','fc_')").fetchone()[0] == 15
    down = alembic(env, "downgrade", "base")
    assert down.returncode == 0, down.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','fc_') "
                         "AND table_name <> 'alembic_version'").fetchone()[0]
        assert left == 0
    again = alembic(env, "upgrade", "head")
    assert again.returncode == 0, again.stderr[-2000:]


def test_t_reg_3_downgrade_0005_to_0004_works_with_day_4_data_and_upgrades_again(scratch_db):
    """Revision 0005 is reversible even when Day-4 data exists: dq_checks without an assessment link are dropped, superseded
    evidence is kept as plain rows, the 0004 guard, views and columns are restored."""
    env = {**os.environ, "DATABASE_URL": scratch_db.replace("postgresql://", "postgresql+psycopg://", 1),
           "PYTHONPATH": str(ROOT / "backend")}
    assert alembic(env, "upgrade", "head").returncode == 0
    with psycopg.connect(scratch_db, autocommit=True) as c:
        org = c.execute("INSERT INTO organizations (name, industry, is_synthetic) VALUES ('o','t',true) RETURNING id").fetchone()[0]
        team = c.execute("INSERT INTO teams (org_id, name, is_synthetic) VALUES (%s,'t',true) RETURNING id", (org,)).fetchone()[0]
        user = c.execute("INSERT INTO users (org_id, team_id, name, email, role, is_synthetic) VALUES (%s,%s,'u','u@x.example','pm',true)"
                         " RETURNING id", (org, team)).fetchone()[0]
        ds = c.execute("INSERT INTO data_sources (org_id, name, source_type, reliability_tier, tier_rationale, is_synthetic)"
                       " VALUES (%s,'d','csv',1,'t',true) RETURNING id", (org,)).fetchone()[0]
        metric = c.execute("INSERT INTO metrics (org_id, name, definition, unit, grain, data_source_id, is_synthetic)"
                           " VALUES (%s,'m','d','ratio','day',%s,true) RETURNING id", (org, ds)).fetchone()[0]
        es = c.execute("INSERT INTO evidence_sources (org_id, data_source_id, title, ref, source_type, reliability_tier, is_synthetic)"
                       " VALUES (%s,%s,'e','r','csv',1,true) RETURNING id", (org, ds)).fetchone()[0]
        did = c.execute(
            "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id, decision_due_date, risk_level,"
            " change_my_mind_criteria, decision_type, expected_direction, canvas_completed_at, owner_id, is_synthetic)"
            " VALUES (%s,%s,'t','d','h',%s,'2026-12-31','low','[\"a criterion long enough\"]','pricing_change','increase',now(),%s,true)"
            " RETURNING id", (org, team, metric, user)).fetchone()[0]
        c.execute("INSERT INTO dq_checks (decision_id, data_source_id, check_type, severity, finding, check_key, target, is_synthetic)"
                  " VALUES (%s,%s,'volume','warn','f','k','t',true)", (did, ds))
        ev1 = c.execute("INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
                        " observed_end, created_by, is_synthetic, analysis_identity) VALUES (%s,%s,'behavioral','s','supports','B',"
                        "'2026-09-01','2026-09-02','agent',true,'id1') RETURNING id", (did, es)).fetchone()[0]
        ev2 = c.execute("INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
                        " observed_end, created_by, is_synthetic, analysis_identity) VALUES (%s,%s,'behavioral','s','supports','B',"
                        "'2026-09-01','2026-09-02','agent',true,'id2') RETURNING id", (did, es)).fetchone()[0]
        c.execute("UPDATE evidence SET status='superseded', superseded_by=%s, superseded_at=now() WHERE id=%s", (ev2, ev1))
    down = alembic(env, "downgrade", "0004")
    assert down.returncode == 0, down.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004"
        cols = lambda t: {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,)).fetchall()}  # noqa: E731
        assert not ({"expected_direction"} & cols("decisions"))
        assert not ({"decision_id", "check_key", "target", "observed_value", "threshold", "affects_success_metric", "source_snapshot",
                     "last_run_at"} & cols("dq_checks"))
        assert not ({"planned_treatment_share", "control_variant", "outcome_key"} & cols("experiments"))
        assert not ({"status", "superseded_by", "superseded_at", "analysis_identity", "source_fingerprint"} & cols("evidence"))
        assert not ({"analysis_identity", "params_hash", "source_fingerprint"} & cols("analysis_results"))
        assert "evidence_status" not in cols("v_traceability_matrix")
        assert c.execute("SELECT count(*) FROM dq_checks").fetchone()[0] == 0           # the unlinked Day-4 row could not be kept
        assert c.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2            # evidence is never deleted
        assert c.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name='dq_checks' AND column_name='assessment_id'"
                         ).fetchone()[0] == "NO"
        # the 0004 lifecycle guard is back (no expected_direction column to compare) and the views answer
        c.execute("SELECT count(*) FROM v_evidence_freshness")
        c.execute("SELECT count(*) FROM v_evidence_health")
        c.execute("SELECT count(*) FROM v_traceability_matrix")
        assert c.execute("SELECT has_table_privilege('ddr_readonly', 'public.metric_observations', 'SELECT')").fetchone()[0] is False
    assert alembic(env, "upgrade", "head").returncode == 0
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005"
        assert c.execute("SELECT has_table_privilege('ddr_readonly', 'public.metric_observations', 'SELECT')").fetchone()[0] is True
        assert c.execute("SELECT expected_direction FROM decisions").fetchone()[0] == "increase"      # backfilled by the migration
