"""AC-29 (PRD section 24.6): changing a data source's last load date, or marking a data-quality check resolved, changes the relevant
Evidence Health indicator with no code change. Raw fixture rows in a transaction that is rolled back."""

from .conftest import new_decision


def _org_value(conn, metric):
    return conn.execute("SELECT value, indicator FROM v_evidence_health WHERE metric_name=%s AND decision_type IS NULL", (metric,)).fetchone()


def test_ac29_the_last_load_date_moves_the_recency_indicator(conn, ids):
    before = _org_value(conn, "avg_days_since_source_load")
    conn.execute("UPDATE data_sources SET last_loaded_at = timestamptz '2026-04-01 00:00:00+00'")
    after = _org_value(conn, "avg_days_since_source_load")
    assert float(after[0]) > float(before[0]) and after[1] != before[1]      # older load: more days, and the indicator leaves green


def test_ac29_a_resolved_dq_check_changes_the_data_quality_indicator(conn, ids):
    did = new_decision(conn, ids, title="AC-29 fixture")
    ds = conn.execute("SELECT id FROM data_sources ds WHERE NOT EXISTS (SELECT 1 FROM dq_checks q WHERE q.data_source_id = ds.id AND q.status = 'open') ORDER BY name LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO dq_checks (decision_id, data_source_id, check_type, severity, finding, status, check_key, target, is_synthetic)"
                 " VALUES (%s,%s,'tracking_gap','critical','fixture','open','ac29|key','fixture target',true)", (did, ds))
    open_value = _org_value(conn, "share_sources_with_open_dq_issues")
    conn.execute("UPDATE dq_checks SET status='resolved', resolved_at=now(), resolved_by=%s WHERE check_key='ac29|key'", (ids.pm,))
    resolved_value = _org_value(conn, "share_sources_with_open_dq_issues")
    assert float(open_value[0]) > float(resolved_value[0])      # one more source with an open issue, then back to the baseline
    assert open_value[1] != resolved_value[1]
