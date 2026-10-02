-- Reporting views, analytical views and the read-only role (revision 0003).
-- No DDI or NBE calculation lives here. Factor lookups mirror docs/DDI-spec.md section 3.1
-- (ddi_params_v0.1) and a Day-2 test asserts parity with backend/config/ddi/ddi_params_v0.1.yaml.

-- ---------------------------------------------------------------- shared lookups
-- Deterministic "as of" date: set 'ddr.as_of' for reproducible reporting, else current_date.
CREATE FUNCTION ddr_as_of() RETURNS date LANGUAGE sql STABLE AS $$
  SELECT COALESCE(NULLIF(current_setting('ddr.as_of', true), '')::date, current_date)
$$;

CREATE FUNCTION ddr_half_life_days(t evidence_type) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE t WHEN 'behavioral' THEN 90 WHEN 'experiment' THEN 180 WHEN 'customer' THEN 180
                WHEN 'financial' THEN 120 WHEN 'market' THEN 365 WHEN 'anecdotal' THEN 90 END
$$;

CREATE FUNCTION ddr_tier_factor(tier integer) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE tier WHEN 1 THEN 1.00 WHEN 2 THEN 0.75 WHEN 3 THEN 0.50 WHEN 4 THEN 0.25 END
$$;

CREATE FUNCTION ddr_grade_factor(g strength_grade) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE g WHEN 'A' THEN 1.00 WHEN 'B' THEN 0.75 WHEN 'C' THEN 0.50 WHEN 'D' THEN 0.25 END
$$;

-- Required evidence types per decision type (docs/DDI-spec.md section 5).
CREATE VIEW v_coverage_checklist AS
SELECT * FROM (VALUES
  ('product_feature_investment','behavioral',  ARRAY['behavioral']::evidence_type[]),
  ('product_feature_investment','customer',    ARRAY['customer']::evidence_type[]),
  ('product_feature_investment','experiment',  ARRAY['experiment']::evidence_type[]),
  ('product_feature_investment','financial',   ARRAY['financial']::evidence_type[]),
  ('pricing_change','behavioral',              ARRAY['behavioral']::evidence_type[]),
  ('pricing_change','customer',                ARRAY['customer']::evidence_type[]),
  ('pricing_change','experiment',              ARRAY['experiment']::evidence_type[]),
  ('pricing_change','financial',               ARRAY['financial']::evidence_type[]),
  ('process_or_ux_change','behavioral',        ARRAY['behavioral']::evidence_type[]),
  ('process_or_ux_change','customer',          ARRAY['customer']::evidence_type[]),
  ('process_or_ux_change','experiment',        ARRAY['experiment']::evidence_type[]),
  ('strategy_or_market_entry','market',        ARRAY['market']::evidence_type[]),
  ('strategy_or_market_entry','customer',      ARRAY['customer']::evidence_type[]),
  ('strategy_or_market_entry','financial',     ARRAY['financial']::evidence_type[]),
  ('policy_or_operations','behavioral',        ARRAY['behavioral']::evidence_type[]),
  ('policy_or_operations','anecdotal_or_customer', ARRAY['anecdotal','customer']::evidence_type[]),
  ('policy_or_operations','financial',         ARRAY['financial']::evidence_type[])
) AS t(decision_type, required_label, accepted_types);

-- ---------------------------------------------------------------- v_evidence_freshness
CREATE VIEW v_evidence_freshness AS
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
LEFT JOIN data_sources ds ON ds.id = es.data_source_id;

-- ---------------------------------------------------------------- v_debt_radar
CREATE VIEW v_debt_radar AS
SELECT d.id AS decision_id,
       d.org_id,
       d.team_id,
       t.name AS team_name,
       d.title,
       d.decision_type,
       d.risk_level,
       d.lifecycle_stage,
       d.assessment_stale,
       d.decision_due_date,
       a.id AS assessment_id,
       a.version AS assessment_version,
       a.state AS assessment_state,
       a.ddi_score,          -- NULL unless state = scored (enforced by ck_score_iff_scored)
       a.ddi_band,
       CASE WHEN a.state = 'scored' THEN (a.sensitivity ->> 'band_stable')::boolean END AS band_stable,
       CASE WHEN a.state <> 'scored' THEN NULL
            WHEN (a.sensitivity ->> 'band_stable')::boolean IS TRUE THEN 'robust'
            WHEN (a.sensitivity ->> 'band_stable')::boolean IS FALSE THEN 'sensitive' END AS robustness_label,
       a.params_version,
       a.created_at AS last_assessed_at,
       (ddr_as_of() - a.created_at::date) AS days_since_assessed,
       d.is_synthetic
FROM decisions d
JOIN teams t ON t.id = d.team_id
LEFT JOIN LATERAL (
  SELECT x.* FROM decision_assessments x
  WHERE x.decision_id = d.id
  ORDER BY x.version DESC LIMIT 1      -- the latest version is current; lower versions are superseded
) a ON true;

-- ---------------------------------------------------------------- v_nbe_ranking
CREATE VIEW v_nbe_ranking AS
SELECT r.id AS recommendation_id,
       r.assessment_id,
       a.decision_id,
       d.title AS decision_title,
       a.version AS assessment_version,
       (a.version < (SELECT max(x.version) FROM decision_assessments x WHERE x.decision_id = a.decision_id)) AS is_superseded,   -- derived, not stored
       r.action_type,
       r.description,
       r.effort_days,
       r.expected_reduction,
       r.relevance,
       r.priority_score,
       rank() OVER (PARTITION BY r.assessment_id ORDER BY r.priority_score DESC, r.effort_days ASC) AS rank_in_assessment,
       r.dimensions_addressed,
       r.status,
       r.human_note,
       r.is_synthetic
FROM recommendations r
JOIN decision_assessments a ON a.id = r.assessment_id
JOIN decisions d ON d.id = a.decision_id;

-- ---------------------------------------------------------------- v_agent_quality
CREATE VIEW v_agent_quality AS
SELECT agent_name,
       stage,
       model,
       prompt_version,
       count(*) AS runs,
       count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
       count(*) FILTER (WHERE status = 'failed') AS failed,
       count(*) FILTER (WHERE status = 'partial') AS partial,
       count(*) FILTER (WHERE error IS NOT NULL) AS runs_with_error,
       round(avg(latency_ms)) AS avg_latency_ms,
       sum(tokens_in) AS tokens_in,
       sum(tokens_out) AS tokens_out,
       sum(CASE WHEN output ->> 'claims_dropped' ~ '^[0-9]+$' THEN (output ->> 'claims_dropped')::int END) AS claims_dropped,
       bool_and(is_synthetic) AS is_synthetic
FROM agent_runs
GROUP BY agent_name, stage, model, prompt_version;

-- ---------------------------------------------------------------- v_traceability_matrix
CREATE VIEW v_traceability_matrix AS
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
         WHERE q.assessment_id = a.id AND q.data_source_id = es.data_source_id) AS dq_status,
       c.conclusion_ref,
       (SELECT array_agg(r.id::text || '#' || ch.ord)
          FROM decision_reviews r
          CROSS JOIN LATERAL jsonb_array_elements(r.challenges) WITH ORDINALITY AS ch(v, ord)
         WHERE r.assessment_id = a.id AND ch.v ->> 'target_id' IN (c.id::text, e.id::text)) AS reviewer_challenge_ids,
       'claim_link'::text AS row_type,
       (c.is_synthetic AND e.is_synthetic) AS is_synthetic
FROM claims c
JOIN decision_assessments a ON a.id = c.assessment_id
JOIN decisions d ON d.id = a.decision_id
JOIN claim_evidence ce ON ce.claim_id = c.id
JOIN evidence e ON e.id = ce.evidence_id
JOIN evidence_sources es ON es.id = e.evidence_source_id
LEFT JOIN analysis_results ar ON ar.id = e.analysis_id
UNION ALL
-- Gap rows (TM-4): required evidence types with no evidence for the decision.
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
       d.is_synthetic
FROM decisions d
JOIN LATERAL (
  SELECT x.* FROM decision_assessments x
  WHERE x.decision_id = d.id ORDER BY x.version DESC LIMIT 1
) a ON true
JOIN LATERAL (
  SELECT cl.required_label FROM v_coverage_checklist cl
  WHERE cl.decision_type = d.decision_type
    AND NOT EXISTS (SELECT 1 FROM evidence e
                    WHERE e.decision_id = d.id AND e.evidence_type = ANY (cl.accepted_types))
) g ON true;

-- ---------------------------------------------------------------- v_evidence_health
-- Descriptive monitoring view (PRD section 24). One row per org x team x decision_type x metric.
-- No composite score. The green/amber/red indicator is a per-metric display convention only.
-- Organization-level metrics (data sources) have NULL team_id and decision_type.
CREATE VIEW v_evidence_health AS
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
         avg(CASE WHEN EXISTS (SELECT 1 FROM evidence e WHERE e.decision_id = dc.id
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

-- ---------------------------------------------------------------- analytical views over fc_ (SQL guard allow-list, Day 4)
-- Only these views are exposed to the read-only role. fc_ base tables and the ground-truth
-- table fc_.feedback_ground_truth are NOT exposed.
CREATE VIEW fc_.v_users AS
  SELECT user_id, signup_ts, platform, country, acquisition_channel, engagement_style,
         prior_engagement_tier, is_synthetic FROM fc_.users;
CREATE VIEW fc_.v_events AS
  SELECT event_id, user_id, event_ts, event_name, platform, app_version, is_synthetic FROM fc_.events;
CREATE VIEW fc_.v_subscriptions AS
  SELECT subscription_id, user_id, plan, price_monthly, start_date, end_date, status, is_synthetic
  FROM fc_.subscriptions;
CREATE VIEW fc_.v_feedback AS
  SELECT feedback_id, user_id, created_at, source, rating, body, is_synthetic FROM fc_.feedback;
CREATE VIEW fc_.v_experiment_assignments AS
  SELECT experiment_key, user_id, variant, assigned_at, is_synthetic FROM fc_.experiment_assignments;
CREATE VIEW fc_.v_experiment_outcomes AS
  SELECT experiment_key, user_id, metric_name, value, is_synthetic FROM fc_.experiment_outcomes;
CREATE VIEW fc_.v_ai_inference_costs AS
  SELECT user_id, cost_month, sessions, cost_usd, is_synthetic FROM fc_.ai_inference_costs;
CREATE VIEW fc_.v_pricing_model_inputs AS
  SELECT input_key, value, unit, is_assumption, source_note, is_synthetic FROM fc_.pricing_model_inputs;

-- ---------------------------------------------------------------- read-only role
-- NOLOGIN: used with SET ROLE (or granted to a login role later). Sees only views.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ddr_readonly') THEN
    CREATE ROLE ddr_readonly NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO ddr_readonly;
GRANT USAGE ON SCHEMA fc_ TO ddr_readonly;
GRANT SELECT ON v_traceability_matrix, v_debt_radar, v_evidence_freshness, v_nbe_ranking,
                v_agent_quality, v_evidence_health, v_coverage_checklist TO ddr_readonly;
GRANT SELECT ON fc_.v_users, fc_.v_events, fc_.v_subscriptions, fc_.v_feedback,
                fc_.v_experiment_assignments, fc_.v_experiment_outcomes,
                fc_.v_ai_inference_costs, fc_.v_pricing_model_inputs TO ddr_readonly;
ALTER ROLE ddr_readonly SET statement_timeout = '30s';
