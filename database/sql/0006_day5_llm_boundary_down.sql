-- Revert revision 0006. Day-5 tables are dropped (their content is derived and regenerable). Claims, reviews and agent_runs
-- keep their rows and lose the Day-5 columns. Evidence is never deleted: a proposed or rejected item (which the 0005 schema
-- cannot represent) is kept as a superseded row that points to itself, so it is excluded from every view and from the facts.

DROP TRIGGER IF EXISTS trg_decision_briefs_insert_only ON decision_briefs;
DROP TRIGGER IF EXISTS trg_decision_briefs_guard ON decision_briefs;
DROP TABLE decision_briefs;
DROP FUNCTION ddr_decision_briefs_guard();

DROP TRIGGER IF EXISTS trg_decision_reviews_insert_only ON decision_reviews;
ALTER TABLE decision_reviews
  DROP COLUMN IF EXISTS agent_run_id,
  DROP COLUMN IF EXISTS synthesis_id;

DROP INDEX IF EXISTS ix_claims_synthesis;
ALTER TABLE claims DROP CONSTRAINT IF EXISTS ck_claims_synthesis_required;
ALTER TABLE claims
  DROP COLUMN IF EXISTS local_id,
  DROP COLUMN IF EXISTS synthesis_id;

DROP TRIGGER IF EXISTS trg_syntheses_decided_guard ON syntheses;
DROP TRIGGER IF EXISTS trg_syntheses_insert_only ON syntheses;
DROP TABLE syntheses;

DROP TRIGGER IF EXISTS trg_llm_classifications_decided_guard ON llm_classifications;
DROP TRIGGER IF EXISTS trg_llm_classifications_insert_only ON llm_classifications;
DROP TABLE llm_classifications;
DROP TYPE customer_relevance;

ALTER TABLE customer_insights
  DROP COLUMN IF EXISTS segment_counts,
  DROP COLUMN IF EXISTS taxonomy_version,
  DROP COLUMN IF EXISTS last_mention_date,
  DROP COLUMN IF EXISTS first_mention_date,
  DROP COLUMN IF EXISTS source_types,
  DROP COLUMN IF EXISTS relevance_observed;

-- evidence: back to the 0005 status model
ALTER TABLE evidence DISABLE TRIGGER trg_evidence_decided_guard;
DROP INDEX IF EXISTS ix_evidence_decision_status;
DROP INDEX ux_evidence_active_identity;
UPDATE evidence SET status = 'superseded', superseded_by = id, superseded_at = COALESCE(superseded_at, now())
  WHERE status IN ('proposed','rejected');
ALTER TABLE evidence
  DROP CONSTRAINT ck_evidence_rejected_actioned,
  DROP CONSTRAINT ck_evidence_agent_customer_approved,
  DROP CONSTRAINT ck_evidence_superseded_fields,
  DROP CONSTRAINT ck_evidence_status,
  DROP COLUMN approval_note,
  DROP COLUMN approved_at,
  DROP COLUMN approved_by;
ALTER TABLE evidence
  ADD CONSTRAINT ck_evidence_status CHECK (status IN ('active','superseded')),
  ADD CONSTRAINT ck_evidence_superseded_fields CHECK (status = 'active' OR (superseded_by IS NOT NULL AND superseded_at IS NOT NULL));
CREATE UNIQUE INDEX ux_evidence_active_identity ON evidence(decision_id, analysis_identity)
  WHERE status = 'active' AND analysis_identity IS NOT NULL;
ALTER TABLE evidence ENABLE TRIGGER trg_evidence_decided_guard;

ALTER TABLE agent_runs
  DROP COLUMN IF EXISTS error_class,
  DROP COLUMN IF EXISTS request_id,
  DROP COLUMN IF EXISTS output_sha256,
  DROP COLUMN IF EXISTS input_sha256,
  DROP COLUMN IF EXISTS params,
  DROP COLUMN IF EXISTS prompt_sha256,
  DROP COLUMN IF EXISTS prompt_id,
  DROP COLUMN IF EXISTS model_fallback,
  DROP COLUMN IF EXISTS purpose;

COMMENT ON COLUMN decision_assessments.brief_md IS NULL;
