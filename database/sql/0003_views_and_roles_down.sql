DROP VIEW IF EXISTS fc_.v_users, fc_.v_events, fc_.v_subscriptions, fc_.v_feedback,
  fc_.v_experiment_assignments, fc_.v_experiment_outcomes, fc_.v_ai_inference_costs,
  fc_.v_pricing_model_inputs;
DROP VIEW IF EXISTS v_evidence_health, v_traceability_matrix, v_agent_quality, v_nbe_ranking,
  v_debt_radar, v_evidence_freshness, v_coverage_checklist;
DROP FUNCTION IF EXISTS ddr_grade_factor(strength_grade);
DROP FUNCTION IF EXISTS ddr_tier_factor(integer);
DROP FUNCTION IF EXISTS ddr_half_life_days(evidence_type);
DROP FUNCTION IF EXISTS ddr_as_of();
DROP OWNED BY ddr_readonly;
-- Roles are cluster-wide. Keep the role if another database still uses it.
DO $$ BEGIN
  DROP ROLE IF EXISTS ddr_readonly;
EXCEPTION WHEN dependent_objects_still_exist THEN
  RAISE NOTICE 'ddr_readonly is still used by another database; role kept';
END $$;

