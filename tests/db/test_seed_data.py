"""Seeded-data validation: manifest patterns, synthetic labelling, core demo records, no premature outputs."""

import json
from pathlib import Path

import pytest

from database.seed.validate import run_checks

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "generated" / "manifest.json"


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST.exists():
        pytest.skip("manifest not generated")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_marked_synthetic_and_covers_four_scenarios(manifest):
    assert manifest["synthetic"] is True and "FICTIONAL" in manifest["synthetic_notice"]
    assert set(manifest["scenarios"]) == {"ai_coach", "onboarding", "pricing", "community"}
    ids = [c["id"] for c in manifest["checks"]]
    assert len(ids) == len(set(ids))
    assert {c["scenario"] for c in manifest["checks"]} == {"global", "ai_coach", "onboarding", "pricing", "community"}
    community = manifest["scenarios"]["community"]
    text = json.dumps(community).lower()
    assert "aggregate masking" in text and "heterogeneity" in text
    assert "not a textbook simpson" in community["terminology_note"].lower()
    defects = manifest["scenarios"]["onboarding"]["defects"]
    assert {d["id"] for d in defects} == {"DEF-ONB-001", "DEF-ONB-002"}
    assert all(d["detection_signals"] for d in defects)


def test_every_manifest_pattern_check_holds_in_the_loaded_data(conn, seeded, manifest):
    if seeded < manifest["min_users_for_pattern_checks"]:
        pytest.skip("pattern thresholds are calibrated for the default scale")
    if conn.execute("SELECT count(*) FROM fc_.users").fetchone()[0] != manifest["scale"]["users"]:
        pytest.skip("loaded data does not match the manifest on disk")
    failed = [r for r in run_checks(conn, manifest) if not r["passed"]]
    assert failed == [], failed


def test_all_loaded_rows_are_labelled_synthetic(conn, seeded):
    tables = conn.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' "
                          "AND table_schema IN ('public','fc_') AND table_name <> 'alembic_version'").fetchall()
    for schema, table in tables:
        n = conn.execute(f"SELECT count(*) FROM {schema}.{table} WHERE NOT is_synthetic").fetchone()[0]
        assert n == 0, f"{schema}.{table} contains non-synthetic rows"
    assert conn.execute("SELECT is_synthetic, name FROM organizations").fetchone() == (True, "FitConnect (fictional, synthetic demo)")


def test_four_scenario_decisions_are_seeded_with_complete_canvases(conn, seeded):
    rows = conn.execute("SELECT scenario_key, lifecycle_stage::text, assessment_stale, canvas_locked_at, "
                        "jsonb_array_length(change_my_mind_criteria), canvas_completed_at IS NOT NULL, decision_type "
                        "FROM decisions ORDER BY scenario_key").fetchall()
    assert [r[0] for r in rows] == ["ai_coach", "community", "onboarding", "pricing"]
    for r in rows:
        assert r[1] == "evidence_gathered" and r[2] is False and r[3] is None and r[4] == 3 and r[5]
    assert {r[0]: r[6] for r in rows} == {"ai_coach": "product_feature_investment", "community": "product_feature_investment",
                                          "onboarding": "process_or_ux_change", "pricing": "pricing_change"}


def test_lifecycle_transitions_for_seeded_decisions_were_audited(conn, seeded):
    n = conn.execute("SELECT count(*) FROM audit_logs WHERE action IN ('decision.created','decision.evidence_gathered')").fetchone()[0]
    assert n == 8


def test_registered_sources_metrics_and_experiments(conn, seeded):
    assert conn.execute("SELECT count(*) FROM data_sources").fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM evidence_sources").fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM metrics WHERE data_source_id IS NOT NULL").fetchone()[0] >= 5
    assert conn.execute("SELECT count(*) FROM metric_observations").fetchone()[0] > 100
    exps = {r[0]: r[1:] for r in conn.execute("SELECT source_ref, design, status, planned_sample FROM experiments").fetchall()}
    assert exps["ai_coach_holdout_2026q1"][0] == "holdout" and exps["premium_price_test_2026q2"][0] == "rct"


def test_later_stage_tables_are_empty_in_day_2(conn, seeded):
    for t in ("evidence", "analysis_results", "decision_assessments", "claims", "claim_evidence", "dq_checks",
              "recommendations", "decision_reviews", "customer_insights", "experiment_results", "agent_runs", "decision_records"):
        assert conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0, t


def test_tracking_defect_is_visible_in_the_raw_events(conn, seeded):
    """DQ-detectability: android step 2 volume collapses to zero at the release date while step 3 continues."""
    rows = conn.execute(
        "SELECT event_ts >= timestamptz '2026-08-03 00:00:00+00' AS post, "
        "count(*) FILTER (WHERE event_name='onboarding_step_2_completed'), count(*) FILTER (WHERE event_name='onboarding_step_3_completed') "
        "FROM fc_.events WHERE platform='android' GROUP BY 1 ORDER BY 1").fetchall()
    pre, post = rows
    assert pre[1] > 1000 and pre[2] > 1000
    assert post[1] == 0 and post[2] > 100
    ios_post = conn.execute("SELECT count(*) FROM fc_.events WHERE platform='ios' AND event_name='onboarding_step_2_completed' "
                            "AND event_ts >= timestamptz '2026-08-03 00:00:00+00'").fetchone()[0]
    assert ios_post > 100
