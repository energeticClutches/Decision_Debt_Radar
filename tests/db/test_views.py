"""Reporting-view validation. Fixture rows are inserted in a transaction that is rolled back."""

from pathlib import Path

import yaml

from .conftest import new_decision, new_synthesis

CONFIG = Path(__file__).resolve().parents[2] / "backend" / "config" / "ddi" / "ddi_params_v0.1.yaml"


def build_assessed_decision(conn, ids):
    """A decision with 3 evidence items (behavioral, customer, experiment), a scored assessment, claims, NBE, review."""
    did = new_decision(conn, ids, title="View fixture decision")
    ev = {}
    for key, etype, es, stance, grade, end in [
        ("beh", "behavioral", ids.es_events, "supports", "B", "2026-09-15"),
        ("cus", "customer", ids.es_feedback, "supports", "C", "2026-03-01"),
        ("exp", "experiment", ids.es_events, "contradicts", "C", "2026-09-20"),
    ]:
        ev[key] = conn.execute(
            "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade, observed_start,"
            " observed_end, created_by, is_synthetic) VALUES (%s,%s,%s,%s,%s,%s,'2026-01-01',%s,'user',true) RETURNING id",
            (did, es, etype, f"{key} evidence", stance, grade, end)).fetchone()[0]
    a = conn.execute(
        "INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, sensitivity, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
        " VALUES (%s,1,'scored',61.0,'high','{\"band_stable\": true, \"range\": [56.5, 65.6]}'::jsonb,'ddi_params_v0.1','h','f','2026-10-01',true) RETURNING id",
        (did,)).fetchone()[0]
    claim = conn.execute("INSERT INTO claims (assessment_id, synthesis_id, claim_text, claim_type, stance, confidence, conclusion_ref, is_synthetic)"
                         " VALUES (%s,%s,'Users with the feature retain more','associative','supports','medium','D6 Behavioral',true) RETURNING id",
                         (a, new_synthesis(conn, a))).fetchone()[0]
    for e in (ev["beh"], ev["exp"]):
        conn.execute("INSERT INTO claim_evidence (claim_id, evidence_id, is_synthetic) VALUES (%s,%s,true)", (claim, e))
    for action, red, eff, rel in [("financial_model_with_sensitivity", 8.4, 3, 0.7), ("powered_holdout_test", 11.7, 8, 1.0),
                                  ("customer_interview_sprint", 3.4, 3, 0.4)]:
        conn.execute("INSERT INTO recommendations (assessment_id, action_type, description, effort_days, expected_reduction,"
                     " relevance, priority_score, dimensions_addressed, is_synthetic) VALUES (%s,%s,'d',%s,%s,%s,%s,'{D4}',true)",
                     (a, action, eff, red, rel, round(rel * red / eff, 4)))
    conn.execute("INSERT INTO decision_reviews (assessment_id, reviewer_type, verdict, challenges, is_synthetic)"
                 " VALUES (%s,'agent','needs_rework', %s::jsonb, true)",
                 (a, '[{"type": "causation", "severity": "high", "target_type": "claim", "target_id": "%s", "text": "x"}]' % claim))
    conn.execute("INSERT INTO agent_runs (decision_id, assessment_id, stage, agent_name, status, model, prompt_version, latency_ms,"
                 " tokens_in, tokens_out, output, is_synthetic) VALUES (%s,%s,'synthesis','evidence_synthesis','succeeded','m','v0.1',1200,10,20,"
                 " '{\"claims_dropped\": 2}'::jsonb, true)", (did, a))
    return did, a, claim, ev


def test_v_debt_radar_shows_score_band_and_robustness(conn, ids):
    did, *_ = build_assessed_decision(conn, ids)
    r = conn.execute("SELECT ddi_score, ddi_band::text, assessment_state::text, band_stable, robustness_label, is_synthetic "
                     "FROM v_debt_radar WHERE decision_id=%s", (did,)).fetchone()
    assert r == (61.0, "high", "scored", True, "robust", True)


def test_v_debt_radar_never_shows_a_number_without_a_score(conn, ids):
    did = new_decision(conn, ids, title="Insufficient")
    conn.execute("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
                 " VALUES (%s,1,'insufficient_evidence','[\"x\"]'::jsonb,'ddi_params_v0.1','h','f','2026-10-01',true)", (did,))
    r = conn.execute("SELECT assessment_state::text, ddi_score, ddi_band, band_stable, robustness_label FROM v_debt_radar WHERE decision_id=%s", (did,)).fetchone()
    assert r == ("insufficient_evidence", None, None, None, None)
    assert conn.execute("SELECT count(*) FROM v_debt_radar WHERE assessment_state <> 'scored' AND ddi_score IS NOT NULL").fetchone()[0] == 0


def test_v_debt_radar_lists_all_seeded_decisions(conn, ids):
    rows = conn.execute("SELECT scenario FROM (SELECT d.scenario_key AS scenario FROM v_debt_radar r JOIN decisions d "
                        "ON d.id = r.decision_id WHERE d.scenario_key IS NOT NULL) x ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == ["ai_coach", "community", "onboarding", "pricing"]


def test_v_nbe_ranking_orders_by_priority_with_effort_tiebreak(conn, ids):
    did, a, *_ = build_assessed_decision(conn, ids)
    rows = conn.execute("SELECT action_type, rank_in_assessment, priority_score FROM v_nbe_ranking WHERE assessment_id=%s ORDER BY rank_in_assessment", (a,)).fetchall()
    assert [r[0] for r in rows] == ["financial_model_with_sensitivity", "powered_holdout_test", "customer_interview_sprint"]
    assert [r[1] for r in rows] == [1, 2, 3]
    assert float(rows[0][2]) == 1.9600


def test_superseded_is_derived_from_the_latest_version(conn, ids):
    did, a1, *_ = build_assessed_decision(conn, ids)
    a2 = conn.execute("INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, params_hash, evidence_fingerprint, as_of_date, is_synthetic)"
                      " VALUES (%s,2,'insufficient_evidence','[\"x\"]'::jsonb,'ddi_params_v0.1','h','f','2026-10-01',true) RETURNING id", (did,)).fetchone()[0]
    # v_debt_radar shows the latest version (no recommendations on it)
    assert conn.execute("SELECT assessment_id, assessment_version FROM v_debt_radar WHERE decision_id=%s", (did,)).fetchone() == (a2, 2)
    # v_nbe_ranking marks the version-1 recommendations as superseded even though version 2 has none
    flags = {r[0] for r in conn.execute("SELECT is_superseded FROM v_nbe_ranking WHERE assessment_id=%s", (a1,)).fetchall()}
    assert flags == {True}


def test_v_traceability_matrix_links_claims_and_adds_gap_rows(conn, ids):
    did, a, claim, ev = build_assessed_decision(conn, ids)
    links = conn.execute("SELECT evidence_type, source_name, reliability_tier, conclusion_ref, array_length(reviewer_challenge_ids,1), is_synthetic "
                         "FROM v_traceability_matrix WHERE decision_id=%s AND row_type='claim_link' ORDER BY evidence_type", (did,)).fetchall()
    assert [l[0] for l in links] == ["behavioral", "experiment"]
    assert all(l[3] == "D6 Behavioral" and l[4] == 1 and l[5] for l in links)
    gaps = conn.execute("SELECT claim_text, evidence_id FROM v_traceability_matrix WHERE decision_id=%s AND row_type='gap'", (did,)).fetchall()
    assert gaps == [("GAP: no financial evidence for this decision", None)]    # checklist: behavioral, customer, experiment, financial


def test_v_evidence_freshness_ages_items_against_the_as_of_date(conn, ids):
    did, *_ = build_assessed_decision(conn, ids)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT evidence_type::text, age_days, half_life_days, within_half_life FROM v_evidence_freshness WHERE decision_id=%s", (did,)).fetchall()}
    assert rows["behavioral"] == (16, 90, True)          # 2026-09-15 to 2026-10-01
    assert rows["customer"] == (214, 180, False)         # 2026-03-01 to 2026-10-01
    assert rows["experiment"] == (11, 180, True)


def test_v_agent_quality_aggregates_runs(conn, ids):
    build_assessed_decision(conn, ids)
    r = conn.execute("SELECT runs, succeeded, claims_dropped, is_synthetic FROM v_agent_quality WHERE agent_name='evidence_synthesis'").fetchone()
    assert r == (1, 1, 2, True)


def test_v_evidence_health_is_descriptive_with_no_composite_score(conn, ids):
    build_assessed_decision(conn, ids)
    cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='v_evidence_health'").fetchall()]
    assert not any("score" in c or "composite" in c for c in cols)
    rows = {(r[0], r[1]): r[2:] for r in conn.execute(
        "SELECT dimension, metric_name, value, indicator FROM v_evidence_health WHERE decision_type='product_feature_investment' AND team_id IS NOT NULL").fetchall()}
    # The only decisions with evidence in this transaction have 2 of 3 items within half-life (customer is stale).
    assert float(rows[("freshness", "share_items_within_half_life")][0]) == round(2 / 3, 4)
    # Coverage: checklist has 4 types, fixture covers behavioral, customer and experiment for one decision, none for the 3 others.
    cov = float(rows[("coverage", "avg_checklist_coverage")][0])
    assert 0 < cov < 1
    # Organization-level data-source metrics are present, and every dimension of PRD section 24 appears.
    dims = {r[0] for r in conn.execute("SELECT DISTINCT dimension FROM v_evidence_health").fetchall()}
    assert dims == {"freshness", "recency", "reliability", "coverage", "data_quality_status", "source_diversity", "contradiction"}


def test_v_evidence_health_has_no_data_rows_for_decisions_without_evidence(conn, ids):
    rows = conn.execute("SELECT indicator FROM v_evidence_health WHERE metric_name='share_items_within_half_life'").fetchall()
    assert rows and all(r[0] == "no_data" for r in rows)


def test_sql_factor_lookups_match_the_versioned_ddi_params(conn, ids):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for etype, days in cfg["half_life_days"].items():
        assert conn.execute("SELECT ddr_half_life_days(%s::evidence_type)", (etype,)).fetchone()[0] == days
    for tier, f in cfg["tier_factor"].items():
        assert float(conn.execute("SELECT ddr_tier_factor(%s)", (tier,)).fetchone()[0]) == f
    for grade, f in cfg["grade_factor"].items():
        assert float(conn.execute("SELECT ddr_grade_factor(%s::strength_grade)", (grade,)).fetchone()[0]) == f


def test_sql_coverage_checklist_matches_the_versioned_ddi_params(conn, ids):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    sql = {}
    for dtype, label, accepted in conn.execute("SELECT decision_type, required_label, accepted_types::text[] FROM v_coverage_checklist").fetchall():
        sql.setdefault(dtype, set()).add(label)
    for dtype, required in cfg["coverage_checklists"].items():
        expected = {r if isinstance(r, str) else "_or_".join(r["any_of"]) for r in required}
        assert sql[dtype] == {e.replace("anecdotal_or_customer", "anecdotal_or_customer") for e in expected}
