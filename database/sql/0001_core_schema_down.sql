DROP TABLE IF EXISTS audit_logs, decision_reviews, recommendations, claim_evidence, claims, dq_checks,
  evidence, analysis_results, agent_runs, decision_records, decision_assessments, customer_insights,
  experiment_results, experiments, evidence_sources, decisions, metric_observations, metrics,
  data_sources, users, teams, organizations CASCADE;
DROP FUNCTION IF EXISTS ddr_claim_evidence_guard() CASCADE;
DROP FUNCTION IF EXISTS ddr_decision_record_guard() CASCADE;
DROP FUNCTION IF EXISTS ddr_decision_lifecycle_guard() CASCADE;
DROP FUNCTION IF EXISTS ddr_insert_only() CASCADE;
DROP FUNCTION IF EXISTS ddr_valid_criteria(jsonb) CASCADE;
DROP FUNCTION IF EXISTS ddr_set_updated_at() CASCADE;
DROP TYPE IF EXISTS pipeline_stage, decision_outcome, review_verdict, recommendation_status, dq_status,
  dq_severity, ddi_band, assessment_state, strength_grade, stance, evidence_type, risk_level,
  lifecycle_stage, user_role;
