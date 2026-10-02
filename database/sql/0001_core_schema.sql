-- Decision Debt Radar: core schema (revision 0001).
-- Source of truth: docs/ERD.md and docs/PRD-v0.1.md section 14.
-- Industry-agnostic. FitConnect demo data lives only in schema fc_ (revision 0002).
-- Every table carries is_synthetic NOT NULL (explicit, no default).

-- ---------------------------------------------------------------- enums (ERD section 4)
CREATE TYPE user_role AS ENUM ('pm','ba','product_analyst','bizops','dept_leader','executive');
CREATE TYPE lifecycle_stage AS ENUM ('created','evidence_gathered','assessed','challenged','validated','decided');
CREATE TYPE risk_level AS ENUM ('low','medium','high');
CREATE TYPE evidence_type AS ENUM ('behavioral','experiment','customer','financial','market','anecdotal');
CREATE TYPE stance AS ENUM ('supports','contradicts','neutral');
CREATE TYPE strength_grade AS ENUM ('A','B','C','D');
CREATE TYPE assessment_state AS ENUM ('scored','insufficient_evidence','partial');
CREATE TYPE ddi_band AS ENUM ('low','moderate','high','critical');
CREATE TYPE dq_severity AS ENUM ('pass','warn','critical');
CREATE TYPE dq_status AS ENUM ('open','resolved','accepted');
CREATE TYPE recommendation_status AS ENUM ('proposed','accepted','rejected','deferred');
CREATE TYPE review_verdict AS ENUM ('ready','needs_rework');
CREATE TYPE decision_outcome AS ENUM ('approve','reject','defer','approve_conditional');
CREATE TYPE pipeline_stage AS ENUM ('dq','quant','customer','experiment','synthesis','review','brief');

-- ---------------------------------------------------------------- helpers
CREATE FUNCTION ddr_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END $$;

-- Canvas rule CV-5: 1-5 criteria, each 10-300 characters.
CREATE FUNCTION ddr_valid_criteria(c jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_typeof(c) = 'array'
     AND jsonb_array_length(c) BETWEEN 1 AND 5
     AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(c) AS e(v)
       WHERE jsonb_typeof(e.v) <> 'string'
          OR char_length(e.v #>> '{}') NOT BETWEEN 10 AND 300
     )
$$;

-- ---------------------------------------------------------------- core
CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  industry text NOT NULL,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE teams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);
CREATE INDEX ix_teams_org ON teams(org_id);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  team_id uuid REFERENCES teams(id),
  name text NOT NULL,
  email text NOT NULL,
  role user_role NOT NULL,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, email)
);
CREATE INDEX ix_users_org ON users(org_id);

CREATE TABLE data_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('csv','survey','ticketing','other')),
  owner_id uuid REFERENCES users(id),
  refresh_cadence text,
  last_loaded_at timestamptz,
  reliability_tier smallint NOT NULL CHECK (reliability_tier BETWEEN 1 AND 4),
  tier_rationale text NOT NULL,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);

CREATE TABLE metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  definition text NOT NULL,
  sql_logic text,
  unit text NOT NULL,
  grain text NOT NULL,
  data_source_id uuid REFERENCES data_sources(id),
  owner_id uuid REFERENCES users(id),
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);

CREATE TABLE metric_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_id uuid NOT NULL REFERENCES metrics(id),
  observed_at date NOT NULL,
  segment_key text,
  segment_value text,
  value numeric NOT NULL,
  n_sample integer CHECK (n_sample IS NULL OR n_sample >= 0),
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((segment_key IS NULL) = (segment_value IS NULL))
);
CREATE INDEX ix_metric_obs_metric_time ON metric_observations(metric_id, observed_at);
CREATE UNIQUE INDEX ux_metric_obs_point ON metric_observations
  (metric_id, observed_at, COALESCE(segment_key,''), COALESCE(segment_value,''));

CREATE TABLE decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  team_id uuid NOT NULL REFERENCES teams(id),
  -- Decision Canvas (docs/decision-canvas.md). Required fields are NOT NULL: a decision
  -- cannot exist without a completed canvas (AC-37).
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
  description text NOT NULL,
  hypothesis text NOT NULL CHECK (char_length(hypothesis) BETWEEN 1 AND 500),
  success_metric_id uuid NOT NULL REFERENCES metrics(id),
  decision_due_date date NOT NULL,
  risk_level risk_level NOT NULL,
  current_evidence_notes text,
  change_my_mind_criteria jsonb NOT NULL CHECK (ddr_valid_criteria(change_my_mind_criteria)),
  decision_type text NOT NULL CHECK (decision_type IN (
    'product_feature_investment','pricing_change','process_or_ux_change',
    'strategy_or_market_entry','policy_or_operations')),
  canvas_completed_at timestamptz NOT NULL,
  canvas_locked_at timestamptz,
  -- Lifecycle (docs/decision-lifecycle.md). MVP stops at 'decided'.
  lifecycle_stage lifecycle_stage NOT NULL DEFAULT 'created',
  assessment_stale boolean NOT NULL DEFAULT false,
  owner_id uuid NOT NULL REFERENCES users(id),
  scenario_key text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- the canvas locks at first assessment, so any stage past evidence_gathered has a lock time
  CHECK (lifecycle_stage IN ('created','evidence_gathered') OR canvas_locked_at IS NOT NULL)
);
CREATE INDEX ix_decisions_org_stage ON decisions(org_id, lifecycle_stage);
CREATE INDEX ix_decisions_team ON decisions(team_id);

CREATE TABLE evidence_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  data_source_id uuid REFERENCES data_sources(id),
  title text NOT NULL,
  ref text,
  source_type text NOT NULL,
  collected_at timestamptz,
  reliability_tier smallint NOT NULL CHECK (reliability_tier BETWEEN 1 AND 4),
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_evidence_sources_org ON evidence_sources(org_id);

CREATE TABLE experiments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  decision_id uuid REFERENCES decisions(id),
  name text NOT NULL,
  hypothesis text NOT NULL,
  design text NOT NULL CHECK (design IN ('rct','holdout','pre_post','other')),
  start_date date NOT NULL,
  end_date date,
  status text NOT NULL CHECK (status IN ('planned','running','completed','abandoned')),
  primary_metric_id uuid REFERENCES metrics(id),
  planned_sample integer CHECK (planned_sample IS NULL OR planned_sample > 0),
  mde numeric,
  source_ref text,               -- reference to the raw experiment data in its data source (for example an experiment key)
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_experiments_decision ON experiments(decision_id);

CREATE TABLE experiment_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id),
  variant text NOT NULL,
  n integer NOT NULL CHECK (n >= 0),
  metric_value numeric,
  effect_size numeric,
  ci_low numeric,
  ci_high numeric,
  p_value numeric CHECK (p_value IS NULL OR p_value BETWEEN 0 AND 1),
  srm_flag boolean,
  notes text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high)
);
CREATE INDEX ix_experiment_results_experiment ON experiment_results(experiment_id);

CREATE TABLE customer_insights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  data_source_id uuid REFERENCES data_sources(id),
  decision_id uuid REFERENCES decisions(id),
  theme text NOT NULL,
  sentiment text NOT NULL CHECK (sentiment IN ('positive','negative','mixed','neutral')),
  segment text,
  quote_count integer NOT NULL CHECK (quote_count >= 0),
  sample_quotes jsonb NOT NULL DEFAULT '[]'::jsonb,
  collected_at timestamptz,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_customer_insights_decision ON customer_insights(decision_id);

-- ---------------------------------------------------------------- assessment layer
CREATE TABLE decision_assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid NOT NULL REFERENCES decisions(id),
  version integer NOT NULL CHECK (version >= 1),
  state assessment_state NOT NULL,
  ddi_score numeric CHECK (ddi_score IS NULL OR ddi_score BETWEEN 0 AND 100),
  ddi_band ddi_band,
  dimension_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  penalty_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  sensitivity jsonb NOT NULL DEFAULT '{}'::jsonb,
  params_version text NOT NULL,
  narrative text,
  brief_md text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (decision_id, version),
  -- ADR-004 / BR-4: a score exists if and only if the state is 'scored'
  CONSTRAINT ck_score_iff_scored CHECK ((state = 'scored') = (ddi_score IS NOT NULL)),
  CONSTRAINT ck_band_iff_scored CHECK ((state = 'scored') = (ddi_band IS NOT NULL)),
  CONSTRAINT ck_insufficient_has_reasons CHECK (
    state <> 'insufficient_evidence'
    OR (jsonb_typeof(blocking_reasons) = 'array' AND jsonb_array_length(blocking_reasons) >= 1))
);
CREATE INDEX ix_assessments_decision ON decision_assessments(decision_id, created_at);

CREATE TABLE decision_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid NOT NULL REFERENCES decisions(id),
  decided_by uuid NOT NULL REFERENCES users(id),
  outcome decision_outcome NOT NULL,
  rationale text NOT NULL CHECK (char_length(btrim(rationale)) > 0),
  acknowledged_risk boolean NOT NULL DEFAULT false,
  decided_at timestamptz NOT NULL DEFAULT now(),
  is_synthetic boolean NOT NULL
);
-- 1:0..1 final record per decision (ERD section 5). 'defer' records are historical and do not count,
-- so a deferral never blocks the later final decision.
CREATE UNIQUE INDEX ux_decision_records_final ON decision_records(decision_id) WHERE outcome <> 'defer';
CREATE INDEX ix_decision_records_decision ON decision_records(decision_id);

CREATE TABLE agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid REFERENCES decisions(id),
  assessment_id uuid REFERENCES decision_assessments(id),
  stage pipeline_stage,
  agent_name text NOT NULL CHECK (agent_name IN
    ('orchestrator','data_analytics','evidence_synthesis','reviewer')),
  status text NOT NULL CHECK (status IN ('running','succeeded','failed','partial')),
  input jsonb,
  output jsonb,
  model text,
  prompt_version text,
  tokens_in integer CHECK (tokens_in IS NULL OR tokens_in >= 0),
  tokens_out integer CHECK (tokens_out IS NULL OR tokens_out >= 0),
  latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
  error text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_agent_runs_assessment_stage ON agent_runs(assessment_id, stage);
CREATE INDEX ix_agent_runs_decision ON agent_runs(decision_id);

CREATE TABLE analysis_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid NOT NULL REFERENCES decisions(id),
  agent_run_id uuid REFERENCES agent_runs(id),
  analysis_type text NOT NULL CHECK (analysis_type IN
    ('trend','segmentation','funnel','retention','experiment','comparison','data_quality')),
  params jsonb NOT NULL DEFAULT '{}'::jsonb,
  query_text text,
  result jsonb,
  n integer CHECK (n IS NULL OR n >= 0),
  limitations text,
  dq_status dq_severity,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_analysis_results_decision ON analysis_results(decision_id);

CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id uuid NOT NULL REFERENCES decisions(id),
  evidence_source_id uuid NOT NULL REFERENCES evidence_sources(id),
  analysis_id uuid REFERENCES analysis_results(id),
  evidence_type evidence_type NOT NULL,
  summary text NOT NULL,
  stance stance NOT NULL,
  strength_grade strength_grade NOT NULL,
  observed_start date NOT NULL,
  observed_end date NOT NULL,
  n_sample integer CHECK (n_sample IS NULL OR n_sample >= 0),
  effect_size numeric,
  ci_low numeric,
  ci_high numeric,
  metric_id uuid REFERENCES metrics(id),
  experiment_id uuid REFERENCES experiments(id),
  insight_id uuid REFERENCES customer_insights(id),
  created_by text NOT NULL CHECK (created_by IN ('user','agent')),
  agent_run_id uuid REFERENCES agent_runs(id),
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (observed_end >= observed_start),
  CHECK (ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high)
);
CREATE INDEX ix_evidence_decision ON evidence(decision_id);
CREATE INDEX ix_evidence_source ON evidence(evidence_source_id);

CREATE TABLE dq_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  data_source_id uuid NOT NULL REFERENCES data_sources(id),
  check_type text NOT NULL,
  severity dq_severity NOT NULL,
  finding text NOT NULL,
  affects_metric_id uuid REFERENCES metrics(id),
  status dq_status NOT NULL DEFAULT 'open',
  resolved_by uuid REFERENCES users(id),
  resolved_at timestamptz,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status = 'open' OR resolved_by IS NOT NULL OR status = 'accepted')
);
CREATE INDEX ix_dq_checks_assessment ON dq_checks(assessment_id);
CREATE INDEX ix_dq_checks_source_status ON dq_checks(data_source_id, status);

CREATE TABLE claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  claim_text text NOT NULL,
  claim_type text NOT NULL CHECK (claim_type IN
    ('descriptive','associative','causal','financial','customer','risk')),
  stance stance NOT NULL,
  confidence text NOT NULL CHECK (confidence IN ('low','medium','high')),
  conclusion_ref text,           -- the dimension or finding this claim feeds (traceability spec)
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_claims_assessment ON claims(assessment_id);

CREATE TABLE claim_evidence (
  claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id),
  is_synthetic boolean NOT NULL,
  PRIMARY KEY (claim_id, evidence_id)
);
CREATE INDEX ix_claim_evidence_evidence ON claim_evidence(evidence_id);

CREATE TABLE recommendations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  action_type text NOT NULL,
  description text NOT NULL,
  effort_days numeric NOT NULL CHECK (effort_days > 0),
  expected_reduction numeric NOT NULL CHECK (expected_reduction >= 0),
  relevance numeric NOT NULL CHECK (relevance BETWEEN 0 AND 1),
  priority_score numeric NOT NULL CHECK (priority_score >= 0),
  dimensions_addressed text[] NOT NULL DEFAULT '{}',
  status recommendation_status NOT NULL DEFAULT 'proposed',
  human_note text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_recommendations_assessment ON recommendations(assessment_id);

CREATE TABLE decision_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES decision_assessments(id),
  reviewer_type text NOT NULL CHECK (reviewer_type IN ('agent','human')),
  reviewer_id uuid REFERENCES users(id),
  verdict review_verdict NOT NULL,
  challenges jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(challenges) = 'array'),
  human_response text,
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (reviewer_type = 'agent' OR reviewer_id IS NOT NULL)
);
CREATE INDEX ix_decision_reviews_assessment ON decision_reviews(assessment_id);

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id),
  actor_type text NOT NULL CHECK (actor_type IN ('user','agent','system')),
  actor_id uuid,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  before jsonb,
  after jsonb,
  ts timestamptz NOT NULL DEFAULT now(),
  is_synthetic boolean NOT NULL
);
CREATE INDEX ix_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX ix_audit_org_ts ON audit_logs(org_id, ts);

-- updated_at maintenance
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['organizations','teams','users','data_sources','metrics','decisions',
    'evidence_sources','experiments','decision_assessments','evidence','recommendations']
  LOOP
    EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I
                    FOR EACH ROW EXECUTE FUNCTION ddr_set_updated_at()', t, t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- insert-only tables (ERD section 5)
CREATE FUNCTION ddr_insert_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is insert-only (% rejected)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END $$;
CREATE TRIGGER trg_audit_insert_only BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();
CREATE TRIGGER trg_decision_records_insert_only BEFORE UPDATE OR DELETE ON decision_records
  FOR EACH ROW EXECUTE FUNCTION ddr_insert_only();

-- ---------------------------------------------------------------- lifecycle guard (decision-lifecycle.md section 4)
CREATE FUNCTION ddr_decision_lifecycle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER trg_decisions_lifecycle BEFORE INSERT OR UPDATE ON decisions
  FOR EACH ROW EXECUTE FUNCTION ddr_decision_lifecycle_guard();

-- A human decision can only be recorded on a validated decision (BR-10, BR-11).
CREATE FUNCTION ddr_decision_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  stage lifecycle_stage;
  a record;
BEGIN
  SELECT lifecycle_stage INTO stage FROM decisions WHERE id = NEW.decision_id;
  IF stage IS DISTINCT FROM 'validated' THEN
    RAISE EXCEPTION 'a decision record requires lifecycle_stage validated (is %)', stage
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT state, ddi_band INTO a FROM decision_assessments
   WHERE decision_id = NEW.decision_id ORDER BY version DESC LIMIT 1;   -- latest version is current
  IF FOUND AND (a.state <> 'scored' OR a.ddi_band IN ('high','critical')) AND NOT NEW.acknowledged_risk THEN
    RAISE EXCEPTION 'High/Critical or insufficient-evidence decisions require acknowledged_risk (BR-11)'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decision_records_guard BEFORE INSERT ON decision_records
  FOR EACH ROW EXECUTE FUNCTION ddr_decision_record_guard();

-- A claim may only cite evidence belonging to the same decision (traceability rule).
CREATE FUNCTION ddr_claim_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  claim_decision uuid;
  evidence_decision uuid;
BEGIN
  SELECT a.decision_id INTO claim_decision FROM claims c JOIN decision_assessments a ON a.id = c.assessment_id WHERE c.id = NEW.claim_id;
  SELECT decision_id INTO evidence_decision FROM evidence WHERE id = NEW.evidence_id;
  IF claim_decision IS DISTINCT FROM evidence_decision THEN
    RAISE EXCEPTION 'claim and evidence belong to different decisions' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_claim_evidence_guard BEFORE INSERT ON claim_evidence
  FOR EACH ROW EXECUTE FUNCTION ddr_claim_evidence_guard();
