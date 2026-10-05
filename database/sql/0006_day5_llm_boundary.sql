-- Day-5 customer evidence, synthesis, review and brief (revision 0006). See docs/day-5-implementation-brief.md section 4.
-- Revisions 0001-0005 are never edited. FitConnect is a fictional company: every row stays SYNTHETIC (is_synthetic NOT NULL).
-- The LLM never writes SQL and never reads the database; these tables only store what the application validated.

-- ---------------------------------------------------------------- agent_runs: LLM call metadata (section 10)
ALTER TABLE agent_runs
  ADD COLUMN purpose text CONSTRAINT ck_agent_runs_purpose CHECK (purpose IN ('classify','synthesize','review')),
  ADD COLUMN model_fallback boolean NOT NULL DEFAULT false,
  ADD COLUMN prompt_id text,
  ADD COLUMN prompt_sha256 text,
  ADD COLUMN params jsonb,
  ADD COLUMN input_sha256 text,
  ADD COLUMN output_sha256 text,
  ADD COLUMN request_id text,
  ADD COLUMN error_class text;

-- ---------------------------------------------------------------- evidence: proposed / rejected and the human approval
ALTER TABLE evidence DROP CONSTRAINT ck_evidence_status;
ALTER TABLE evidence DROP CONSTRAINT ck_evidence_superseded_fields;
ALTER TABLE evidence
  ADD COLUMN approved_by uuid REFERENCES users(id),
  ADD COLUMN approved_at timestamptz,
  ADD COLUMN approval_note text,
  ADD CONSTRAINT ck_evidence_status CHECK (status IN ('proposed','active','superseded','rejected')),
  ADD CONSTRAINT ck_evidence_superseded_fields CHECK (status <> 'superseded' OR (superseded_by IS NOT NULL AND superseded_at IS NOT NULL)),
  -- a rejection is recorded by a human too (approved_by / approved_at name the person who actioned the item)
  ADD CONSTRAINT ck_evidence_rejected_actioned CHECK (status <> 'rejected' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL));
-- an active customer item created by an agent exists only because a human approved it (D5-02). NOT VALID: rows that already exist
-- (only possible when this revision is re-applied after a downgrade, which drops the approval columns) are not re-checked; every
-- insert and update is.
ALTER TABLE evidence ADD CONSTRAINT ck_evidence_agent_customer_approved CHECK (
  NOT (status = 'active' AND evidence_type = 'customer' AND created_by = 'agent')
  OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)) NOT VALID;
-- the identity slot is held by a proposed or an active item. A rejected item no longer holds it (the service refuses to
-- re-propose a rejected identity).
DROP INDEX ux_evidence_active_identity;
CREATE UNIQUE INDEX ux_evidence_active_identity ON evidence(decision_id, analysis_identity)
  WHERE status IN ('active','proposed') AND analysis_identity IS NOT NULL;
CREATE INDEX ix_evidence_decision_status ON evidence(decision_id, status);

-- ---------------------------------------------------------------- customer_insights: observed values (stored, not used by DDI v0.1)
ALTER TABLE customer_insights
  ADD COLUMN relevance_observed numeric CONSTRAINT ck_insights_relevance_observed CHECK (relevance_observed IS NULL OR relevance_observed BETWEEN 0 AND 1),
  ADD COLUMN source_types text[],
  ADD COLUMN first_mention_date date,
  ADD COLUMN last_mention_date date,
  ADD COLUMN taxonomy_version text,
  ADD COLUMN segment_counts jsonb;

-- ---------------------------------------------------------------- llm_classifications (insert-only)
CREATE TYPE customer_relevance AS ENUM ('direct','adjacent','not_relevant');

CREATE TABLE llm_classifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid NOT NULL REFERENCES decisions(id),
  feedback_id bigint NOT NULL,                       -- the fc_ id kept as a value: the core schema has no foreign key into fc_
  text_sha256 text NOT NULL,
  taxonomy_version text NOT NULL,
  theme text,
  relevance customer_relevance NOT NULL,
  prompt_version text NOT NULL,
  prompt_sha256 text NOT NULL,
  model text NOT NULL,
  agent_run_id uuid NOT NULL REFERENCES agent_runs(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  is_synthetic boolean NOT NULL,
  CONSTRAINT uq_llm_classifications_key UNIQUE (decision_id, feedback_id, taxonomy_version, prompt_version, model)
);
CREATE INDEX ix_llm_classifications_cache ON llm_classifications(text_sha256, taxonomy_version, prompt_version, model);
CREATE INDEX ix_llm_classifications_decision ON llm_classifications(decision_id, taxonomy_version, theme);
CREATE TRIGGER trg_llm_classifications_insert_only BEFORE UPDATE OR DELETE ON llm_classifications
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();
CREATE TRIGGER trg_llm_classifications_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON llm_classifications
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_decision_id();

-- ---------------------------------------------------------------- syntheses (immutable, no delete)
CREATE TABLE syntheses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  version integer NOT NULL CHECK (version >= 1),
  agent_run_id uuid NOT NULL REFERENCES agent_runs(id),
  status text NOT NULL CHECK (status IN ('succeeded','failed','rejected_by_validators')),
  input_sha256 text NOT NULL,
  output_sha256 text,
  output jsonb,
  validator_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  claims_dropped integer NOT NULL DEFAULT 0 CHECK (claims_dropped >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  is_synthetic boolean NOT NULL,
  CONSTRAINT uq_syntheses_assessment_version UNIQUE (assessment_id, version),
  CONSTRAINT ck_syntheses_succeeded_has_output CHECK (status <> 'succeeded' OR (output IS NOT NULL AND output_sha256 IS NOT NULL))
);
CREATE INDEX ix_syntheses_assessment ON syntheses(assessment_id, version);
CREATE INDEX ix_syntheses_input ON syntheses(assessment_id, input_sha256);
-- insert-only: a synthesis is never changed or deleted (same intent as the assessment immutability trigger)
CREATE TRIGGER trg_syntheses_insert_only BEFORE UPDATE OR DELETE ON syntheses
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();
CREATE TRIGGER trg_syntheses_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON syntheses
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_assessment_id();

-- ---------------------------------------------------------------- claims: the synthesis they come from
ALTER TABLE claims
  ADD COLUMN synthesis_id uuid REFERENCES syntheses(id),
  ADD COLUMN local_id text;
-- NOT VALID: Day-3 and Day-4 rows (none are produced by the seed) are not re-checked, every new row must name its synthesis.
ALTER TABLE claims ADD CONSTRAINT ck_claims_synthesis_required CHECK (synthesis_id IS NOT NULL) NOT VALID;
CREATE INDEX ix_claims_synthesis ON claims(synthesis_id);

-- ---------------------------------------------------------------- decision_reviews: the synthesis and the agent run, insert-only
ALTER TABLE decision_reviews
  ADD COLUMN synthesis_id uuid REFERENCES syntheses(id),
  ADD COLUMN agent_run_id uuid REFERENCES agent_runs(id);
CREATE TRIGGER trg_decision_reviews_insert_only BEFORE UPDATE OR DELETE ON decision_reviews
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();

-- ---------------------------------------------------------------- decision_briefs (immutable, versioned, no delete)
CREATE TABLE decision_briefs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  synthesis_id uuid REFERENCES syntheses(id),
  kind text NOT NULL CHECK (kind IN ('decision_brief','gated_evidence_summary')),
  version integer NOT NULL CHECK (version >= 1),
  content jsonb NOT NULL,
  markdown text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  is_synthetic boolean NOT NULL,
  CONSTRAINT uq_decision_briefs_version UNIQUE (assessment_id, kind, version),
  -- a validated Decision Brief always rests on a synthesis. Only a gated summary may exist without one
  CONSTRAINT ck_decision_briefs_synthesis CHECK (kind = 'gated_evidence_summary' OR synthesis_id IS NOT NULL)
);
CREATE INDEX ix_decision_briefs_assessment ON decision_briefs(assessment_id, kind, version);

-- decision_brief needs decision stage validated or decided AND a scored assessment (T2); gated_evidence_summary needs an insufficient_evidence assessment.
-- (Briefs are derived documents: they are NOT under the decided-guard, because a Decision Brief may be produced after the
-- decision was recorded.)
CREATE FUNCTION ddr_decision_briefs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  s lifecycle_stage;
  st assessment_state;
  syn_assessment uuid;
BEGIN
  SELECT d.lifecycle_stage, a.state INTO s, st
    FROM decision_assessments a JOIN decisions d ON d.id = a.decision_id WHERE a.id = NEW.assessment_id;
  IF NEW.kind = 'decision_brief' AND s NOT IN ('validated','decided') THEN
    RAISE EXCEPTION 'a decision_brief requires the decision to be validated or decided (it is %)', s
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.kind = 'decision_brief' AND st <> 'scored' THEN
    RAISE EXCEPTION 'a decision_brief requires a scored assessment (it is %); an insufficient one gets a gated_evidence_summary', st
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.kind = 'gated_evidence_summary' AND st <> 'insufficient_evidence' THEN
    RAISE EXCEPTION 'a gated_evidence_summary exists only for an insufficient_evidence assessment (it is %)', st
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.synthesis_id IS NOT NULL THEN
    SELECT assessment_id INTO syn_assessment FROM syntheses WHERE id = NEW.synthesis_id;
    IF syn_assessment IS DISTINCT FROM NEW.assessment_id THEN
      RAISE EXCEPTION 'the synthesis belongs to a different assessment' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decision_briefs_guard BEFORE INSERT ON decision_briefs
  FOR EACH ROW EXECUTE FUNCTION ddr_decision_briefs_guard();
CREATE TRIGGER trg_decision_briefs_insert_only BEFORE UPDATE OR DELETE ON decision_briefs
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();

-- ---------------------------------------------------------------- decision_assessments.brief_md is deprecated
COMMENT ON COLUMN decision_assessments.brief_md IS 'DEPRECATED since revision 0006: left in place and unused. Briefs live in decision_briefs.';
