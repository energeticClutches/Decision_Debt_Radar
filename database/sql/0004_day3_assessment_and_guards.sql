-- Day-3 invariants and assessment metadata (revision 0004). See docs/day-3-implementation-brief.md (R10, R13, 3.2, 3.7).
-- Only invariants live here. Workflow (who may do what, when) stays in the service layer.

-- ---------------------------------------------------------------- 3.2 assessment metadata (R4, R5, R11)
-- Existing rows (none in the seeded database) are backfilled with explicit markers before the defaults are dropped.
ALTER TABLE decision_assessments
  ADD COLUMN params_hash text NOT NULL DEFAULT 'legacy-unrecorded',
  ADD COLUMN nbe_params_version text,
  ADD COLUMN nbe_params_hash text,
  ADD COLUMN evidence_fingerprint text NOT NULL DEFAULT 'legacy-unrecorded',
  ADD COLUMN as_of_date date;
UPDATE decision_assessments SET as_of_date = created_at::date WHERE as_of_date IS NULL;
ALTER TABLE decision_assessments
  ALTER COLUMN as_of_date SET NOT NULL,
  ALTER COLUMN params_hash DROP DEFAULT,
  ALTER COLUMN evidence_fingerprint DROP DEFAULT;

-- ---------------------------------------------------------------- R10 blockers_resolved
-- Insufficient-evidence recommendations: expected_reduction = 0 and blockers_resolved holds the number of
-- gating blockers the action addresses. The two units are never mixed.
ALTER TABLE recommendations
  ADD COLUMN blockers_resolved integer NOT NULL DEFAULT 0 CONSTRAINT ck_blockers_resolved_nonneg CHECK (blockers_resolved >= 0);

-- ---------------------------------------------------------------- 3.4d assessment immutability
-- An assessment is a historical artifact. Only narrative and brief_md (filled by later days) may change.
CREATE FUNCTION ddr_assessment_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.decision_id IS DISTINCT FROM OLD.decision_id
     OR NEW.version IS DISTINCT FROM OLD.version
     OR NEW.state IS DISTINCT FROM OLD.state
     OR NEW.ddi_score IS DISTINCT FROM OLD.ddi_score
     OR NEW.ddi_band IS DISTINCT FROM OLD.ddi_band
     OR NEW.dimension_scores IS DISTINCT FROM OLD.dimension_scores
     OR NEW.penalty_scores IS DISTINCT FROM OLD.penalty_scores
     OR NEW.blocking_reasons IS DISTINCT FROM OLD.blocking_reasons
     OR NEW.sensitivity IS DISTINCT FROM OLD.sensitivity
     OR NEW.params_version IS DISTINCT FROM OLD.params_version
     OR NEW.params_hash IS DISTINCT FROM OLD.params_hash
     OR NEW.nbe_params_version IS DISTINCT FROM OLD.nbe_params_version
     OR NEW.nbe_params_hash IS DISTINCT FROM OLD.nbe_params_hash
     OR NEW.evidence_fingerprint IS DISTINCT FROM OLD.evidence_fingerprint
     OR NEW.as_of_date IS DISTINCT FROM OLD.as_of_date THEN
    RAISE EXCEPTION 'decision_assessments are immutable: only narrative and brief_md may change (assessment %)', OLD.id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_assessments_immutable BEFORE UPDATE ON decision_assessments
  FOR EACH ROW EXECUTE FUNCTION ddr_assessment_immutable();

-- Assessments can never be deleted, at any lifecycle stage (PO correction, Day-3 acceptance review).
CREATE FUNCTION ddr_assessment_no_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'decision_assessments cannot be deleted (assessment %)', OLD.id
    USING ERRCODE = 'integrity_constraint_violation';
END $$;
CREATE TRIGGER trg_assessments_no_delete BEFORE DELETE ON decision_assessments
  FOR EACH ROW EXECUTE FUNCTION ddr_assessment_no_delete();

-- ---------------------------------------------------------------- R13 (a) and (c): lifecycle guard
-- Replaces the 0001 function in place (same trigger, no second BEFORE trigger, so no trigger-ordering issue).
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

  -- R13(a): a canvas edit after the lock marks the assessment stale and returns the decision to evidence_gathered.
  -- Canvas columns are the fields of docs/decision-canvas.md section 2.
  IF OLD.canvas_locked_at IS NOT NULL
     AND OLD.lifecycle_stage IN ('assessed','challenged','validated')
     AND NEW.lifecycle_stage = OLD.lifecycle_stage
     AND (NEW.title IS DISTINCT FROM OLD.title
          OR NEW.description IS DISTINCT FROM OLD.description
          OR NEW.hypothesis IS DISTINCT FROM OLD.hypothesis
          OR NEW.success_metric_id IS DISTINCT FROM OLD.success_metric_id
          OR NEW.decision_due_date IS DISTINCT FROM OLD.decision_due_date
          OR NEW.risk_level IS DISTINCT FROM OLD.risk_level
          OR NEW.current_evidence_notes IS DISTINCT FROM OLD.current_evidence_notes
          OR NEW.change_my_mind_criteria IS DISTINCT FROM OLD.change_my_mind_criteria
          OR NEW.decision_type IS DISTINCT FROM OLD.decision_type
          OR NEW.team_id IS DISTINCT FROM OLD.team_id
          OR NEW.owner_id IS DISTINCT FROM OLD.owner_id) THEN
    NEW.assessment_stale := true;
    NEW.lifecycle_stage := 'evidence_gathered';
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
    -- R13(c): assessed requires a completed (non-partial) assessment row.
    IF NOT EXISTS (SELECT 1 FROM decision_assessments a WHERE a.decision_id = NEW.id AND a.state <> 'partial') THEN
      RAISE EXCEPTION 'cannot enter assessed without a completed (non-partial) assessment row'
        USING ERRCODE = 'check_violation';
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

-- ---------------------------------------------------------------- R13 (b): a decided decision rejects every write
-- INSERT, UPDATE and DELETE on the tables below are rejected once the decision is decided.
-- audit_logs is intentionally NOT guarded (insert-only, still allowed).
-- FOR SHARE makes a concurrent transaction wait for an in-flight decision transition, then see its result.
CREATE FUNCTION ddr_reject_if_decided(d uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  s lifecycle_stage;
BEGIN
  IF d IS NULL THEN
    RETURN;
  END IF;
  SELECT lifecycle_stage INTO s FROM decisions WHERE id = d FOR SHARE;
  IF s = 'decided' THEN
    RAISE EXCEPTION 'decision % is decided: writes to its records are rejected', d
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
END $$;

CREATE FUNCTION ddr_decided_guard_decision_id() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    PERFORM ddr_reject_if_decided(OLD.decision_id);
    RETURN OLD;
  END IF;
  PERFORM ddr_reject_if_decided(NEW.decision_id);
  IF TG_OP = 'UPDATE' AND OLD.decision_id IS DISTINCT FROM NEW.decision_id THEN
    PERFORM ddr_reject_if_decided(OLD.decision_id);
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION ddr_decided_guard_assessment_id() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  d uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    SELECT decision_id INTO d FROM decision_assessments WHERE id = OLD.assessment_id;
    PERFORM ddr_reject_if_decided(d);
    RETURN OLD;
  END IF;
  SELECT decision_id INTO d FROM decision_assessments WHERE id = NEW.assessment_id;
  PERFORM ddr_reject_if_decided(d);
  RETURN NEW;
END $$;

CREATE FUNCTION ddr_decided_guard_agent_runs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  d uuid;
  r agent_runs;
BEGIN
  IF TG_OP = 'DELETE' THEN
    r := OLD;
  ELSE
    r := NEW;
  END IF;
  d := r.decision_id;
  IF d IS NULL AND r.assessment_id IS NOT NULL THEN
    SELECT decision_id INTO d FROM decision_assessments WHERE id = r.assessment_id;
  END IF;
  PERFORM ddr_reject_if_decided(d);
  RETURN r;
END $$;

CREATE FUNCTION ddr_decided_guard_claim_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  d uuid;
  cid uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    cid := OLD.claim_id;
  ELSE
    cid := NEW.claim_id;
  END IF;
  SELECT a.decision_id INTO d FROM claims c JOIN decision_assessments a ON a.id = c.assessment_id WHERE c.id = cid;
  PERFORM ddr_reject_if_decided(d);
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_evidence_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON evidence
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_decision_id();
CREATE TRIGGER trg_assessments_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON decision_assessments
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_decision_id();
CREATE TRIGGER trg_analysis_results_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON analysis_results
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_decision_id();
CREATE TRIGGER trg_agent_runs_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON agent_runs
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_agent_runs();
CREATE TRIGGER trg_recommendations_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON recommendations
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_assessment_id();
CREATE TRIGGER trg_reviews_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON decision_reviews
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_assessment_id();
CREATE TRIGGER trg_dq_checks_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON dq_checks
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_assessment_id();
CREATE TRIGGER trg_claims_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON claims
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_assessment_id();
CREATE TRIGGER trg_claim_evidence_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON claim_evidence
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_claim_evidence();
