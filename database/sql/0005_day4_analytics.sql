-- Day-4 data and analytics foundation (revision 0005). See docs/day-4-implementation-brief.md section 3.
-- Decisions D4-01 to D4-03, D4-12, D4-14, D4-15, D4-16, D4-19, D4-20 and the approved open point O1.
-- Revisions 0001-0004 are never edited. This revision replaces the 0004 lifecycle guard (same pattern as 0004) and
-- re-creates three views.

-- ---------------------------------------------------------------- D4-20 / O1: decisions.expected_direction
-- Existing rows are backfilled (Pricing: no_material_decrease, every other decision: increase), then the default is
-- dropped so that the canvas must supply the value. The backfill disables the lifecycle guard for this one statement
-- (a schema change, not a canvas edit by a person, so it must not mark any assessment stale).
ALTER TABLE decisions
  ADD COLUMN expected_direction text NOT NULL DEFAULT 'increase'
  CONSTRAINT ck_decisions_expected_direction CHECK (expected_direction IN ('increase','decrease','no_material_decrease'));
ALTER TABLE decisions DISABLE TRIGGER trg_decisions_lifecycle;
UPDATE decisions SET expected_direction = 'no_material_decrease' WHERE scenario_key = 'pricing';
ALTER TABLE decisions ENABLE TRIGGER trg_decisions_lifecycle;
ALTER TABLE decisions ALTER COLUMN expected_direction DROP DEFAULT;

-- The lifecycle guard replaces the 0004 function in place: expected_direction joins the canvas-stale column list.
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
  -- Canvas columns are the fields of docs/decision-canvas.md section 2 (Day 4: plus expected_direction).
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
          OR NEW.expected_direction IS DISTINCT FROM OLD.expected_direction
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

-- ---------------------------------------------------------------- D4-01/02/03: dq_checks per decision
-- A DQ check belongs to a decision (UNIQUE(decision_id, check_key), updated in place on every re-run). The assessment
-- link becomes optional. Existing rows (none in the seeded database) are backfilled from their assessment.
ALTER TABLE dq_checks DISABLE TRIGGER trg_dq_checks_decided_guard;
ALTER TABLE dq_checks
  ADD COLUMN decision_id uuid REFERENCES decisions(id),
  ADD COLUMN check_key text,
  ADD COLUMN target text,
  ADD COLUMN observed_value numeric,
  ADD COLUMN threshold numeric,
  ADD COLUMN affects_success_metric boolean NOT NULL DEFAULT false,
  ADD COLUMN source_snapshot text,
  ADD COLUMN last_run_at timestamptz;
UPDATE dq_checks q SET decision_id = a.decision_id, check_key = q.data_source_id::text || '|' || q.check_type || '|' || q.id::text,
                       target = q.check_type
  FROM decision_assessments a WHERE a.id = q.assessment_id;
ALTER TABLE dq_checks
  ALTER COLUMN assessment_id DROP NOT NULL,
  ALTER COLUMN decision_id SET NOT NULL,
  ALTER COLUMN check_key SET NOT NULL,
  ALTER COLUMN target SET NOT NULL,
  ADD CONSTRAINT uq_dq_checks_decision_check_key UNIQUE (decision_id, check_key);
CREATE INDEX ix_dq_checks_decision ON dq_checks(decision_id);
DROP TRIGGER trg_dq_checks_decided_guard ON dq_checks;
-- The decided-guard is re-pointed to decision_id (the assessment link can now be NULL).
CREATE TRIGGER trg_dq_checks_decided_guard BEFORE INSERT OR UPDATE OR DELETE ON dq_checks
  FOR EACH ROW EXECUTE FUNCTION ddr_decided_guard_decision_id();

-- ---------------------------------------------------------------- D4-12: experiments
ALTER TABLE experiments
  ADD COLUMN planned_treatment_share numeric CONSTRAINT ck_experiments_planned_share CHECK (planned_treatment_share > 0 AND planned_treatment_share < 1),
  ADD COLUMN control_variant text,
  ADD COLUMN outcome_key text;     -- the outcome metric_name in the source data (fc_.experiment_outcomes)

-- ---------------------------------------------------------------- D4-14: experiment_results upsert target
ALTER TABLE experiment_results ADD CONSTRAINT uq_experiment_results_variant UNIQUE (experiment_id, variant);

-- ---------------------------------------------------------------- D4-16/19: evidence status, identity and fingerprint
ALTER TABLE evidence
  ADD COLUMN status text NOT NULL DEFAULT 'active' CONSTRAINT ck_evidence_status CHECK (status IN ('active','superseded')),
  ADD COLUMN superseded_by uuid REFERENCES evidence(id),
  ADD COLUMN superseded_at timestamptz,
  ADD COLUMN analysis_identity text,
  ADD COLUMN source_fingerprint text,
  ADD CONSTRAINT ck_evidence_superseded_fields CHECK (status = 'active' OR (superseded_by IS NOT NULL AND superseded_at IS NOT NULL));
CREATE UNIQUE INDEX ux_evidence_active_identity ON evidence(decision_id, analysis_identity)
  WHERE status = 'active' AND analysis_identity IS NOT NULL;
CREATE INDEX ix_evidence_analysis ON evidence(analysis_id);

-- ---------------------------------------------------------------- D4-15: analysis_results identity and hashes
-- Rows are historical: never updated after insert, except agent_run_id (enforced below).
ALTER TABLE analysis_results
  ADD COLUMN analysis_identity text,
  ADD COLUMN params_hash text,
  ADD COLUMN source_fingerprint text;
CREATE INDEX ix_analysis_results_identity ON analysis_results(decision_id, analysis_identity);

CREATE FUNCTION ddr_analysis_results_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.decision_id IS DISTINCT FROM OLD.decision_id
     OR NEW.analysis_type IS DISTINCT FROM OLD.analysis_type
     OR NEW.params IS DISTINCT FROM OLD.params
     OR NEW.query_text IS DISTINCT FROM OLD.query_text
     OR NEW.result IS DISTINCT FROM OLD.result
     OR NEW.n IS DISTINCT FROM OLD.n
     OR NEW.limitations IS DISTINCT FROM OLD.limitations
     OR NEW.dq_status IS DISTINCT FROM OLD.dq_status
     OR NEW.analysis_identity IS DISTINCT FROM OLD.analysis_identity
     OR NEW.params_hash IS DISTINCT FROM OLD.params_hash
     OR NEW.source_fingerprint IS DISTINCT FROM OLD.source_fingerprint
     OR NEW.is_synthetic IS DISTINCT FROM OLD.is_synthetic
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'analysis_results are historical: only agent_run_id may change (analysis %)', OLD.id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_analysis_results_immutable BEFORE UPDATE ON analysis_results
  FOR EACH ROW EXECUTE FUNCTION ddr_analysis_results_immutable();

-- ---------------------------------------------------------------- read-only role needs metric_observations (brief section 9)
GRANT SELECT ON public.metric_observations TO ddr_readonly;

-- ---------------------------------------------------------------- D4-19: views count only active evidence
CREATE OR REPLACE VIEW v_evidence_freshness AS
SELECT e.id AS evidence_id,
       e.decision_id,
       d.org_id,
       d.team_id,
       d.decision_type,
       e.evidence_type,
       e.observed_end,
       (ddr_as_of() - e.observed_end) AS age_days,
       ddr_half_life_days(e.evidence_type) AS half_life_days,
       ((ddr_as_of() - e.observed_end) <= ddr_half_life_days(e.evidence_type)) AS within_half_life,
       es.id AS evidence_source_id,
       es.reliability_tier,
       ds.last_loaded_at,
       (ddr_as_of() - ds.last_loaded_at::date) AS days_since_source_load,
       e.is_synthetic
FROM evidence e
JOIN decisions d ON d.id = e.decision_id
JOIN evidence_sources es ON es.id = e.evidence_source_id
LEFT JOIN data_sources ds ON ds.id = es.data_source_id
WHERE e.status = 'active';

-- v_traceability_matrix keeps every evidence row (claims of historical assessments must still resolve) and adds
-- evidence_status. DQ is now per decision. Gap rows count only active evidence.
CREATE OR REPLACE VIEW v_traceability_matrix AS
SELECT d.id AS decision_id,
       d.title AS decision_title,
       a.id AS assessment_id,
       a.version AS assessment_version,
       c.id AS claim_id,
       c.claim_text,
       c.claim_type,
       c.stance::text AS stance,
       c.confidence AS claim_confidence,
       e.id AS evidence_id,
       e.summary AS evidence_summary,
       e.evidence_type::text AS evidence_type,
       e.strength_grade::text AS strength_grade,
       es.id AS source_id,
       es.title AS source_name,
       es.reliability_tier::int AS reliability_tier,
       ar.id AS analysis_id,
       ar.analysis_type,
       CASE WHEN ar.id IS NOT NULL THEN 'analysis_results:' || ar.id::text END AS query_ref,
       (SELECT max(q.severity)::text FROM dq_checks q
         WHERE q.decision_id = a.decision_id AND q.data_source_id = es.data_source_id) AS dq_status,
       c.conclusion_ref,
       (SELECT array_agg(r.id::text || '#' || ch.ord)
          FROM decision_reviews r
          CROSS JOIN LATERAL jsonb_array_elements(r.challenges) WITH ORDINALITY AS ch(v, ord)
         WHERE r.assessment_id = a.id AND ch.v ->> 'target_id' IN (c.id::text, e.id::text)) AS reviewer_challenge_ids,
       'claim_link'::text AS row_type,
       (c.is_synthetic AND e.is_synthetic) AS is_synthetic,
       e.status AS evidence_status
FROM claims c
JOIN decision_assessments a ON a.id = c.assessment_id
JOIN decisions d ON d.id = a.decision_id
JOIN claim_evidence ce ON ce.claim_id = c.id
JOIN evidence e ON e.id = ce.evidence_id
JOIN evidence_sources es ON es.id = e.evidence_source_id
LEFT JOIN analysis_results ar ON ar.id = e.analysis_id
UNION ALL
-- Gap rows (TM-4): required evidence types with no active evidence for the decision.
SELECT d.id, d.title, a.id, a.version,
       NULL::uuid, 'GAP: no ' || g.required_label || ' evidence for this decision', NULL::text,
       NULL::text, NULL::text,
       NULL::uuid, NULL::text, NULL::text, NULL::text,
       NULL::uuid, NULL::text, NULL::int,
       NULL::uuid, NULL::text, NULL::text,
       NULL::text,
       'D2 Evidence Coverage'::text,
       NULL::text[],
       'gap'::text,
       d.is_synthetic,
       NULL::text
FROM decisions d
JOIN LATERAL (
  SELECT x.id, x.version FROM decision_assessments x     -- explicit columns: a view must not depend on later-added columns
  WHERE x.decision_id = d.id ORDER BY x.version DESC LIMIT 1
) a ON true
JOIN LATERAL (
  SELECT cl.required_label FROM v_coverage_checklist cl
  WHERE cl.decision_type = d.decision_type
    AND NOT EXISTS (SELECT 1 FROM evidence e
                    WHERE e.decision_id = d.id AND e.status = 'active' AND e.evidence_type = ANY (cl.accepted_types))
) g ON true;

CREATE OR REPLACE VIEW v_evidence_health AS
WITH asof AS (SELECT ddr_as_of() AS d),
dec AS (SELECT id, org_id, team_id, decision_type, is_synthetic FROM decisions),
ev AS (
  SELECT e.id, e.decision_id, dc.org_id, dc.team_id, dc.decision_type, e.evidence_type,
         e.strength_grade, e.stance, e.evidence_source_id, es.reliability_tier,
         (a.d - e.observed_end) AS age_days,
         ddr_half_life_days(e.evidence_type) AS hl,
         ddr_tier_factor(es.reliability_tier) * ddr_grade_factor(e.strength_grade)
           * power(0.5, (a.d - e.observed_end)::numeric / ddr_half_life_days(e.evidence_type)) AS w
  FROM evidence e
  JOIN dec dc ON dc.id = e.decision_id
  JOIN evidence_sources es ON es.id = e.evidence_source_id
  CROSS JOIN asof a
  WHERE e.status = 'active'
),
freshness AS (
  SELECT org_id, team_id, decision_type, avg((age_days <= hl)::int)::numeric AS v FROM ev GROUP BY 1,2,3),
reliability AS (
  SELECT org_id, team_id, decision_type,
         avg(((reliability_tier <= 2) AND strength_grade IN ('A','B'))::int)::numeric AS v
  FROM ev GROUP BY 1,2,3),
dec_newest AS (
  SELECT decision_id, org_id, team_id, decision_type, min(age_days) AS newest FROM ev GROUP BY 1,2,3,4),
recency AS (
  SELECT org_id, team_id, decision_type, avg(newest)::numeric AS v FROM dec_newest GROUP BY 1,2,3),
dec_cov AS (
  SELECT dc.id, dc.org_id, dc.team_id, dc.decision_type,
         avg(CASE WHEN EXISTS (SELECT 1 FROM evidence e WHERE e.decision_id = dc.id AND e.status = 'active'
                               AND e.evidence_type = ANY (cl.accepted_types)) THEN 1 ELSE 0 END)::numeric AS cov
  FROM dec dc JOIN v_coverage_checklist cl ON cl.decision_type = dc.decision_type
  GROUP BY 1,2,3,4),
coverage AS (
  SELECT org_id, team_id, decision_type, avg(cov) AS v FROM dec_cov GROUP BY 1,2,3),
dec_contra AS (
  SELECT decision_id, org_id, team_id, decision_type,
         COALESCE(sum(w) FILTER (WHERE stance = 'contradicts'), 0) / NULLIF(sum(w), 0) AS share
  FROM ev GROUP BY 1,2,3,4),
contradiction AS (
  SELECT org_id, team_id, decision_type, avg((COALESCE(share, 0) > 0.3)::int)::numeric AS v
  FROM dec_contra GROUP BY 1,2,3),
src_counts AS (
  SELECT decision_id, org_id, team_id, decision_type, evidence_source_id, count(*)::numeric AS n,
         sum(count(*)) OVER (PARTITION BY decision_id)::numeric AS total
  FROM ev GROUP BY 1,2,3,4,5),
dec_src AS (
  SELECT decision_id, org_id, team_id, decision_type,
         count(*)::numeric / max(total) AS distinct_per_item,
         sum(power(n / total, 2)) AS hhi
  FROM src_counts GROUP BY 1,2,3,4),
diversity AS (
  SELECT org_id, team_id, decision_type, avg(distinct_per_item) AS v_distinct, avg(hhi) AS v_hhi
  FROM dec_src GROUP BY 1,2,3),
base AS (
  SELECT org_id, team_id, decision_type, bool_and(is_synthetic) AS is_synthetic
  FROM dec GROUP BY 1,2,3),
catalog AS (
  SELECT * FROM (VALUES
    ('freshness',        'share_items_within_half_life',               true,  0.70, 0.40),
    ('recency',          'avg_days_since_newest_evidence',             false, 30,   90),
    ('reliability',      'share_reliable_items',                       true,  0.70, 0.40),
    ('coverage',         'avg_checklist_coverage',                     true,  0.80, 0.50),
    ('contradiction',    'share_decisions_contradiction_over_0_3',     false, 0.10, 0.30),
    ('source_diversity', 'avg_distinct_sources_per_item',              true,  0.60, 0.30),
    ('source_diversity', 'avg_source_concentration_hhi',               false, 0.35, 0.60)
  ) AS t(dimension, metric_name, higher_is_better, green_at, amber_at)),
vals AS (
  SELECT org_id, team_id, decision_type, 'share_items_within_half_life' AS metric_name, v FROM freshness
  UNION ALL SELECT org_id, team_id, decision_type, 'avg_days_since_newest_evidence', v FROM recency
  UNION ALL SELECT org_id, team_id, decision_type, 'share_reliable_items', v FROM reliability
  UNION ALL SELECT org_id, team_id, decision_type, 'avg_checklist_coverage', v FROM coverage
  UNION ALL SELECT org_id, team_id, decision_type, 'share_decisions_contradiction_over_0_3', v FROM contradiction
  UNION ALL SELECT org_id, team_id, decision_type, 'avg_distinct_sources_per_item', v_distinct FROM diversity
  UNION ALL SELECT org_id, team_id, decision_type, 'avg_source_concentration_hhi', v_hhi FROM diversity),
group_rows AS (
  SELECT b.org_id, b.team_id, b.decision_type, c.dimension, c.metric_name, vv.v AS value,
         c.higher_is_better, c.green_at, c.amber_at, b.is_synthetic
  FROM base b CROSS JOIN catalog c
  LEFT JOIN vals vv ON vv.org_id = b.org_id AND vv.team_id = b.team_id
                   AND vv.decision_type = b.decision_type AND vv.metric_name = c.metric_name),
org_rows AS (
  SELECT ds.org_id, NULL::uuid AS team_id, NULL::text AS decision_type,
         'data_quality_status'::text AS dimension, 'share_sources_with_open_dq_issues'::text AS metric_name,
         avg((EXISTS (SELECT 1 FROM dq_checks q WHERE q.data_source_id = ds.id AND q.status = 'open'
                       AND q.severity IN ('warn','critical')))::int)::numeric AS value,
         false AS higher_is_better, 0.10::numeric AS green_at, 0.30::numeric AS amber_at,
         bool_and(ds.is_synthetic) AS is_synthetic
  FROM data_sources ds GROUP BY ds.org_id
  UNION ALL
  SELECT ds.org_id, NULL, NULL, 'recency', 'avg_days_since_source_load',
         avg(ddr_as_of() - ds.last_loaded_at::date)::numeric, false, 30, 90, bool_and(ds.is_synthetic)
  FROM data_sources ds WHERE ds.last_loaded_at IS NOT NULL GROUP BY ds.org_id),
all_rows AS (SELECT * FROM group_rows UNION ALL SELECT * FROM org_rows)
SELECT org_id, team_id, decision_type, dimension, metric_name,
       round(value, 4) AS value,
       CASE WHEN value IS NULL THEN 'no_data'
            WHEN higher_is_better THEN CASE WHEN value >= green_at THEN 'green' WHEN value >= amber_at THEN 'amber' ELSE 'red' END
            ELSE CASE WHEN value <= green_at THEN 'green' WHEN value <= amber_at THEN 'amber' ELSE 'red' END
       END AS indicator,
       (SELECT d FROM asof) AS as_of_date,
       is_synthetic
FROM all_rows;
