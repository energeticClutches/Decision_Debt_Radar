"""SQL guard and read-only execution: T-SQL-1 (the parser rejects) and T-SQL-2 (the database role is the real boundary)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
import sqlalchemy.exc as sa_exc

from app.analytics import queries as Q
from app.analytics.executor import READONLY_ROLE, ReadOnlyExecutor
from app.analytics.sql_guard import ALLOWED_TABLES, DEFAULT_MAX_ROWS, SqlRejected, validate_select

GOOD = [
    "SELECT count(*) AS n FROM fc_.v_users LIMIT 1",
    "WITH b AS (SELECT user_id FROM fc_.v_users WHERE signup_ts < :t) SELECT count(*) FROM b LIMIT 10",
    "SELECT u.user_id FROM fc_.v_users u JOIN fc_.v_events e ON e.user_id = u.user_id WHERE e.event_name = ANY(CAST(:n AS text[])) LIMIT 5",
    "SELECT metric_id, value FROM public.metric_observations LIMIT 100000",
    "SELECT count(*) FROM fc_.v_subscriptions UNION ALL SELECT count(*) FROM fc_.v_feedback LIMIT 5",
]

REJECTED = {
    "multiple statements": ["SELECT 1 LIMIT 1; SELECT 2 LIMIT 1", "SELECT 1 LIMIT 1; DROP TABLE decisions"],
    "DML": ["INSERT INTO fc_.v_users (user_id) VALUES (1)", "UPDATE fc_.v_users SET platform = 'web'", "DELETE FROM fc_.v_users",
            "WITH x AS (DELETE FROM decisions RETURNING id) SELECT * FROM x LIMIT 1", "MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE"],
    "DDL": ["DROP TABLE fc_.users", "CREATE TABLE x (a int)", "ALTER TABLE decisions ADD COLUMN x int", "TRUNCATE decisions",
            "GRANT ALL ON decisions TO PUBLIC"],
    "other commands": ["COPY (SELECT 1) TO STDOUT", "SET ROLE postgres", "BEGIN", "COMMIT", "EXPLAIN ANALYZE SELECT 1 LIMIT 1"],
    "SELECT INTO": ["SELECT * INTO scratch FROM fc_.v_users LIMIT 5"],
    "locking clauses": ["SELECT * FROM fc_.v_users LIMIT 1 FOR UPDATE", "SELECT * FROM fc_.v_users LIMIT 1 FOR SHARE"],
    "non-allow-listed tables": [
        "SELECT * FROM fc_.users LIMIT 1", "SELECT * FROM fc_.feedback_ground_truth LIMIT 1", "SELECT * FROM fc_.events LIMIT 1",
        "SELECT * FROM decisions LIMIT 1", "SELECT * FROM public.decisions LIMIT 1", "SELECT * FROM evidence LIMIT 1",
        "SELECT * FROM audit_logs LIMIT 1", "SELECT * FROM pg_catalog.pg_user LIMIT 1",
        "SELECT * FROM information_schema.tables LIMIT 1", "SELECT * FROM metric_observations LIMIT 1",
        "SELECT * FROM fc_.v_users u JOIN fc_.users x ON x.user_id = u.user_id LIMIT 1",
        "SELECT (SELECT count(*) FROM fc_.feedback_ground_truth) AS n LIMIT 1",
        "SELECT * FROM (SELECT * FROM fc_.users) s LIMIT 1", "SELECT * FROM fc_.v_users WHERE user_id IN (SELECT user_id FROM decisions) LIMIT 1",
        "SELECT * FROM mydb.fc_.v_users LIMIT 1", "SELECT * FROM generate_series(1, 10) LIMIT 5",
    ],
    "denied functions": [
        "SELECT pg_sleep(5) LIMIT 1", "SELECT pg_catalog.pg_sleep(5) LIMIT 1", "SELECT dblink('host=x', 'select 1') LIMIT 1",
        "SELECT dblink_exec('host=x', 'drop table y') LIMIT 1", "SELECT lo_import('/etc/passwd') LIMIT 1", "SELECT lo_export(1, '/tmp/x') LIMIT 1",
        "SELECT pg_read_file('/etc/passwd') LIMIT 1", "SELECT pg_read_binary_file('/etc/passwd') LIMIT 1", "SELECT pg_ls_dir('/') LIMIT 1",
        "SELECT set_config('role', 'postgres', false) LIMIT 1", "SELECT pg_terminate_backend(1) LIMIT 1", "SELECT nextval('s') LIMIT 1",
        "SELECT repeat('x', 1000000000) LIMIT 1",
    ],
    "missing or invalid LIMIT": ["SELECT * FROM fc_.v_users", "SELECT * FROM fc_.v_users LIMIT 100001", "SELECT * FROM fc_.v_users LIMIT :n",
                                 "WITH b AS (SELECT 1 FROM fc_.v_users) SELECT * FROM b", "SELECT * FROM fc_.v_users LIMIT ALL"],
    "recursive CTE": ["WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) SELECT * FROM r LIMIT 5"],
    "unparseable": ["SELEC * FORM x", "", "   "],
}


@pytest.mark.parametrize("sql", GOOD)
def test_sql_1_allowed_statements_pass(sql):
    g = validate_select(sql)
    assert g.limit <= DEFAULT_MAX_ROWS and set(g.tables) <= ALLOWED_TABLES


@pytest.mark.parametrize("category,sql", [(c, s) for c, items in REJECTED.items() for s in items])
def test_sql_1_the_guard_rejects(category, sql):
    with pytest.raises(SqlRejected):
        validate_select(sql)


def test_sql_1_the_allow_list_is_the_eight_views_plus_metric_observations():
    assert ALLOWED_TABLES == frozenset({
        "fc_.v_users", "fc_.v_events", "fc_.v_subscriptions", "fc_.v_feedback", "fc_.v_experiment_assignments",
        "fc_.v_experiment_outcomes", "fc_.v_ai_inference_costs", "fc_.v_pricing_model_inputs", "public.metric_observations"})


def test_sql_1_max_rows_is_configurable_and_aggregations_are_fine():
    assert validate_select("SELECT count(*) FROM fc_.v_events LIMIT 1").limit == 1
    with pytest.raises(SqlRejected):
        validate_select("SELECT * FROM fc_.v_users LIMIT 51", max_rows=50)
    assert validate_select("SELECT * FROM fc_.v_users LIMIT 50", max_rows=50).limit == 50


def test_sql_1_rejections_are_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="app.analytics.sql_guard"):
        with pytest.raises(SqlRejected):
            validate_select("SELECT * FROM fc_.feedback_ground_truth LIMIT 1")
    assert any("sql rejected" in r.message and "feedback_ground_truth" in r.getMessage() for r in caplog.records)


def test_sql_1_the_executor_runs_the_guard_before_the_database(monkeypatch, engine):
    ex = ReadOnlyExecutor(engine)
    bad = Q.QueryTemplate.build("bad", "SELECT * FROM fc_.users LIMIT 1")
    called = []
    monkeypatch.setattr(ex, "_execute", lambda *a, **k: called.append(a))
    with pytest.raises(SqlRejected):
        ex.run(bad, {})
    assert called == []
    with pytest.raises(ValueError):                      # parameters must match the template exactly
        ex.run(Q.anchor_query(), {})
    with pytest.raises(ValueError):
        ex.run(Q.anchor_query(), {"as_of_ts": datetime(2026, 10, 1, tzinfo=UTC), "extra": 1})


# ---------------------------------------------------------------- T-SQL-2
@pytest.fixture()
def ex(engine):
    return ReadOnlyExecutor(engine)


def test_sql_2_execution_runs_as_the_readonly_role_in_a_read_only_transaction_with_a_timeout(ex):
    (row,) = ex._execute("SELECT current_user AS u, current_setting('transaction_read_only') AS ro, "
                         "current_setting('statement_timeout') AS t, current_setting('TimeZone') AS tz LIMIT 1", {}, 1)
    assert row["u"] == READONLY_ROLE and row["ro"] == "on" and row["t"] == "30s" and row["tz"] == "UTC"


def test_sql_2_parameters_are_bound_never_interpolated(ex):
    template = Q.QueryTemplate.build("probe", "SELECT CAST(:x AS text) AS x LIMIT 1")
    hostile = "'; DROP TABLE decisions; --"
    assert ex.run(template, {"x": hostile}) == [{"x": hostile}]
    assert "DROP" not in template.sql


def test_sql_2_a_mutation_that_slips_past_the_parser_is_still_rejected_by_the_database(ex):
    # the parser is bypassed on purpose: _execute is what run() calls AFTER validation
    for sql, message in [
        ("INSERT INTO fc_.users (user_id) VALUES (1)", "read-only"),
        ("UPDATE fc_.users SET platform = 'web'", "read-only"),
        ("DELETE FROM fc_.events", "read-only"),
        ("CREATE TABLE public.hijack (a int)", "read-only"),
    ]:
        with pytest.raises(sa_exc.DBAPIError, match=message):
            ex._execute(sql, {}, 10)


def test_sql_2_the_role_cannot_read_anything_that_is_not_allow_listed(ex):
    for sql in ("SELECT * FROM fc_.users LIMIT 1", "SELECT * FROM fc_.events LIMIT 1", "SELECT * FROM fc_.feedback_ground_truth LIMIT 1",
                "SELECT * FROM decisions LIMIT 1", "SELECT * FROM evidence LIMIT 1", "SELECT * FROM audit_logs LIMIT 1",
                "SELECT * FROM users LIMIT 1"):
        with pytest.raises(sa_exc.DBAPIError, match="permission denied"):
            ex._execute(sql, {}, 10)
    # ... and can read the allow-listed ones, including metric_observations (granted in 0005)
    for view in sorted(ALLOWED_TABLES):
        ex._execute(f"SELECT count(*) AS n FROM {view} LIMIT 1", {}, 1)


def test_sql_2_the_statement_timeout_cancels_a_slow_query(engine):
    slow = ReadOnlyExecutor(engine, statement_timeout="200ms")
    with pytest.raises(sa_exc.DBAPIError, match="statement timeout"):
        slow._execute("SELECT pg_sleep(3)", {}, 1)


def test_sql_2_even_a_role_reset_cannot_write_because_the_transaction_is_read_only(ex):
    """The application user in the local stack is the database owner, so a statement that escaped the parser could RESET ROLE.
    The READ ONLY transaction is the second layer: it still rejects every write. (The parser also refuses any ';' separator.)"""
    with pytest.raises(sa_exc.DBAPIError, match="read-only"):
        ex._execute("RESET ROLE; INSERT INTO fc_.users (user_id) VALUES (1)", {}, 1)
    with pytest.raises(sa_exc.DBAPIError, match="read-only"):
        ex._execute("RESET ROLE; DELETE FROM decisions", {}, 1)
    with pytest.raises(SqlRejected):
        validate_select("SELECT 1 LIMIT 1; RESET ROLE")
    with pytest.raises(SqlRejected):
        validate_select("SELECT 'a;b' AS x LIMIT 1")


def test_sql_2_the_executor_uses_its_own_transaction_and_leaves_the_callers_session_alone(session, ex):
    from sqlalchemy import text
    session.execute(text("CREATE TEMP TABLE probe_txn (a int)"))
    ex.run(Q.anchor_query(), {"as_of_ts": datetime(2026, 10, 1, tzinfo=UTC)})
    assert session.execute(text("SELECT count(*) FROM probe_txn")).scalar() == 0          # the caller's transaction is intact
    assert session.execute(text("SELECT current_user")).scalar() != READONLY_ROLE          # and was never switched to the role
