-- Revert revision 0004. Restores the 0001 lifecycle guard and removes the Day-3 columns and triggers.
DROP TRIGGER IF EXISTS trg_assessments_no_delete ON decision_assessments;
DROP FUNCTION IF EXISTS ddr_assessment_no_delete();
DROP TRIGGER IF EXISTS trg_assessments_immutable ON decision_assessments;
DROP FUNCTION IF EXISTS ddr_assessment_immutable();
DROP TRIGGER IF EXISTS trg_claim_evidence_decided_guard ON claim_evidence;
DROP TRIGGER IF EXISTS trg_claims_decided_guard ON claims;
DROP TRIGGER IF EXISTS trg_dq_checks_decided_guard ON dq_checks;
DROP TRIGGER IF EXISTS trg_reviews_decided_guard ON decision_reviews;
DROP TRIGGER IF EXISTS trg_recommendations_decided_guard ON recommendations;
DROP TRIGGER IF EXISTS trg_agent_runs_decided_guard ON agent_runs;
DROP TRIGGER IF EXISTS trg_analysis_results_decided_guard ON analysis_results;
DROP TRIGGER IF EXISTS trg_assessments_decided_guard ON decision_assessments;
DROP TRIGGER IF EXISTS trg_evidence_decided_guard ON evidence;
DROP FUNCTION IF EXISTS ddr_decided_guard_claim_evidence();
DROP FUNCTION IF EXISTS ddr_decided_guard_agent_runs();
DROP FUNCTION IF EXISTS ddr_decided_guard_assessment_id();
DROP FUNCTION IF EXISTS ddr_decided_guard_decision_id();
DROP FUNCTION IF EXISTS ddr_reject_if_decided(uuid);

CREATE OR REPLACE FUNCTION ddr_decision_lifecycle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  has_basis boolean;
  ok boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.lifecycle_stage <> 'created' THEN
      RAISE EXCEPTION 'a new decision must start at lifecycle_stage created (got %)', NEW.lifecycle_stage
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;

  IF OLD.lifecycle_stage = 'decided' THEN
    RAISE EXCEPTION 'decision % is decided and immutable in the MVP', OLD.id USING ERRCODE = 'integrity_constraint_violation';
  END IF;

  -- Canvas lock is set once and never cleared.
  IF OLD.canvas_locked_at IS NOT NULL AND NEW.canvas_locked_at IS DISTINCT FROM OLD.canvas_locked_at THEN
    RAISE EXCEPTION 'canvas_locked_at cannot be changed once set' USING ERRCODE = 'integrity_constraint_violation';
  END IF;

  IF NEW.lifecycle_stage = OLD.lifecycle_stage THEN
    RETURN NEW;
  END IF;

  ok := (OLD.lifecycle_stage, NEW.lifecycle_stage) IN (
    ('created','evidence_gathered'),
    ('evidence_gathered','assessed'),
    ('assessed','challenged'),
    ('challenged','validated'),
    ('validated','decided'),
    ('assessed','evidence_gathered'),
    ('challenged','evidence_gathered'),
    ('validated','evidence_gathered'));
  IF NOT ok THEN
    RAISE EXCEPTION 'illegal lifecycle transition % -> %', OLD.lifecycle_stage, NEW.lifecycle_stage
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.lifecycle_stage = 'evidence_gathered' AND OLD.lifecycle_stage = 'created' THEN
    SELECT (EXISTS (SELECT 1 FROM metrics m WHERE m.id = NEW.success_metric_id AND m.data_source_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM evidence e WHERE e.decision_id = NEW.id)) INTO has_basis;
    IF NOT has_basis THEN
      RAISE EXCEPTION 'cannot leave created: success metric has no data source and no evidence is linked'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  IF NEW.lifecycle_stage = 'assessed' THEN
    IF NEW.canvas_locked_at IS NULL THEN
      RAISE EXCEPTION 'canvas must be locked when the decision is assessed' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.assessment_stale THEN
      RAISE EXCEPTION 'assessment_stale must be false when entering assessed' USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  -- Going back to evidence_gathered from a later stage means the assessment is stale.
  IF NEW.lifecycle_stage = 'evidence_gathered' AND OLD.lifecycle_stage <> 'created' AND NOT NEW.assessment_stale THEN
    RAISE EXCEPTION 'returning to evidence_gathered must set assessment_stale' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.lifecycle_stage = 'decided' THEN
    IF NOT EXISTS (SELECT 1 FROM decision_records r WHERE r.decision_id = NEW.id AND r.outcome <> 'defer') THEN
      RAISE EXCEPTION 'cannot mark decided without a final human decision record' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

ALTER TABLE recommendations DROP COLUMN IF EXISTS blockers_resolved;
ALTER TABLE decision_assessments
  DROP COLUMN IF EXISTS as_of_date,
  DROP COLUMN IF EXISTS evidence_fingerprint,
  DROP COLUMN IF EXISTS nbe_params_hash,
  DROP COLUMN IF EXISTS nbe_params_version,
  DROP COLUMN IF EXISTS params_hash;
