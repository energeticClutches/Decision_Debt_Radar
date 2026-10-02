"""Schema structure checks against docs/ERD.md (tables, enums, views, isolation, synthetic labelling)."""

CORE_TABLES = {
    "organizations", "teams", "users", "data_sources", "metrics", "metric_observations", "decisions",
    "decision_records", "evidence_sources", "evidence", "experiments", "experiment_results",
    "customer_insights", "dq_checks", "analysis_results", "claims", "claim_evidence",
    "decision_assessments", "recommendations", "decision_reviews", "agent_runs", "audit_logs",
}
FC_TABLES = {
    "users", "events", "subscriptions", "feedback", "feedback_ground_truth", "experiment_assignments",
    "experiment_outcomes", "ai_inference_costs", "pricing_model_inputs",
}
ENUMS = {
    "user_role", "lifecycle_stage", "risk_level", "evidence_type", "stance", "strength_grade",
    "assessment_state", "ddi_band", "dq_severity", "dq_status", "recommendation_status", "review_verdict",
    "decision_outcome", "pipeline_stage",
}
REPORTING_VIEWS = {
    "v_traceability_matrix", "v_debt_radar", "v_evidence_freshness", "v_nbe_ranking", "v_agent_quality",
    "v_evidence_health",
}
FC_VIEWS = {
    "v_users", "v_events", "v_subscriptions", "v_feedback", "v_experiment_assignments",
    "v_experiment_outcomes", "v_ai_inference_costs", "v_pricing_model_inputs",
}


def names(conn, sql, *params):
    return {r[0] for r in conn.execute(sql, params).fetchall()}


def test_core_tables_match_the_canonical_erd(conn, dsn):
    got = names(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
                      "AND table_type='BASE TABLE' AND table_name <> 'alembic_version'")
    assert got == CORE_TABLES and len(got) == 22


def test_fc_schema_tables(conn, dsn):
    got = names(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema='fc_' AND table_type='BASE TABLE'")
    assert got == FC_TABLES


def test_enums_exist(conn, dsn):
    got = names(conn, "SELECT typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                      "WHERE n.nspname='public' AND t.typtype='e'")
    assert ENUMS <= got


def test_reporting_and_analytical_views_exist(conn, dsn):
    pub = names(conn, "SELECT table_name FROM information_schema.views WHERE table_schema='public'")
    assert REPORTING_VIEWS <= pub
    fc = names(conn, "SELECT table_name FROM information_schema.views WHERE table_schema='fc_'")
    assert fc == FC_VIEWS


def test_every_table_has_non_null_is_synthetic(conn, dsn):
    rows = conn.execute(
        "SELECT table_schema, table_name FROM information_schema.tables t WHERE table_type='BASE TABLE' "
        "AND table_schema IN ('public','fc_') AND table_name <> 'alembic_version' "
        "AND NOT EXISTS (SELECT 1 FROM information_schema.columns c WHERE c.table_schema=t.table_schema "
        "AND c.table_name=t.table_name AND c.column_name='is_synthetic' AND c.is_nullable='NO')").fetchall()
    assert rows == [], f"tables without a NOT NULL is_synthetic column: {rows}"


def test_core_schema_never_references_fc_tables(conn, dsn):
    n = conn.execute(
        "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace rn ON rn.oid=r.relnamespace "
        "JOIN pg_class f ON f.oid=c.confrelid JOIN pg_namespace fn ON fn.oid=f.relnamespace "
        "WHERE c.contype='f' AND rn.nspname='public' AND fn.nspname='fc_'").fetchone()[0]
    assert n == 0


def test_expected_indexes_exist(conn, dsn):
    idx = names(conn, "SELECT indexname FROM pg_indexes WHERE schemaname='public'")
    expected = {"ix_metric_obs_metric_time", "ix_decisions_org_stage", "ix_evidence_decision", "ix_experiment_results_experiment",
                "ix_dq_checks_assessment", "ix_analysis_results_decision", "ix_agent_runs_assessment_stage",
                "ix_audit_entity", "ix_audit_org_ts"}
    assert expected <= idx
    uniq = conn.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'decision_assessments_decision_id_version_key'").fetchone()[0]
    assert uniq == 1


def test_reconciled_schema_additions_match_the_documentation(conn, dsn):
    cols = lambda t: names(conn, "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", t)  # noqa: E731
    assert "conclusion_ref" in cols("claims")              # PRD 14.1, ERD 5, traceability-spec 3
    assert "source_ref" in cols("experiments")             # PRD 14.1, ERD 5
    assert "is_superseded" not in cols("decision_assessments")   # superseded is derived from version
    idx = conn.execute("SELECT indexdef FROM pg_indexes WHERE indexname='ux_decision_records_final'").fetchone()[0]
    assert "UNIQUE" in idx and "<> 'defer'" in idx


def test_fc_check_constraints_force_synthetic(conn, dsn):
    n = conn.execute(
        "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace "
        "WHERE n.nspname='fc_' AND c.contype='c' AND pg_get_constraintdef(c.oid) LIKE '%is_synthetic%'").fetchone()[0]
    assert n >= len(FC_TABLES)
