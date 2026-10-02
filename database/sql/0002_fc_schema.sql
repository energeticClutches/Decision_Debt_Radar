-- FitConnect synthetic demo schema (revision 0002).
-- FitConnect is a FICTIONAL company. EVERY row in this schema is SYNTHETIC.
-- The core platform never references these tables directly. They are reached only through
-- registered data_sources/metrics and the read-only analytical views fc_.v_* (revision 0003).

CREATE SCHEMA fc_;
COMMENT ON SCHEMA fc_ IS 'SYNTHETIC FitConnect demo data (fictional company). Not real-world data.';

CREATE TABLE fc_.users (
  user_id bigint PRIMARY KEY,
  signup_ts timestamptz NOT NULL,
  platform text NOT NULL CHECK (platform IN ('android','ios','web')),
  country text NOT NULL,
  acquisition_channel text NOT NULL,
  engagement_style text NOT NULL CHECK (engagement_style IN ('social_exerciser','solo_athlete','time_pressed')),
  prior_engagement_tier text NOT NULL CHECK (prior_engagement_tier IN ('high','medium','low')),
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)
);
CREATE INDEX ix_fc_users_signup ON fc_.users(signup_ts);

CREATE TABLE fc_.events (
  event_id bigint PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  event_ts timestamptz NOT NULL,
  event_name text NOT NULL,
  platform text NOT NULL CHECK (platform IN ('android','ios','web')),
  app_version text NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)
);
CREATE INDEX ix_fc_events_user_ts ON fc_.events(user_id, event_ts);
CREATE INDEX ix_fc_events_name_ts ON fc_.events(event_name, event_ts);

CREATE TABLE fc_.subscriptions (
  subscription_id bigint PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  plan text NOT NULL CHECK (plan IN ('free_trial','premium')),
  price_monthly numeric(8,2) NOT NULL CHECK (price_monthly >= 0),
  start_date date NOT NULL,
  end_date date,
  status text NOT NULL CHECK (status IN ('trial_converted','trial_expired','active','cancelled')),
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
  CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_fc_subscriptions_user ON fc_.subscriptions(user_id);

CREATE TABLE fc_.feedback (
  feedback_id bigint PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  created_at timestamptz NOT NULL,
  source text NOT NULL CHECK (source IN ('app_review','survey','support_ticket')),
  rating smallint CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
  body text NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)
);
CREATE INDEX ix_fc_feedback_created ON fc_.feedback(created_at);

-- Ground-truth labels for later evaluation of customer-theme extraction.
-- NOT exposed through the analytical views and not allow-listed for the SQL guard.
CREATE TABLE fc_.feedback_ground_truth (
  feedback_id bigint PRIMARY KEY REFERENCES fc_.feedback(feedback_id),
  scenario_key text NOT NULL,
  theme text NOT NULL,
  sentiment text NOT NULL CHECK (sentiment IN ('positive','negative','neutral')),
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)
);

CREATE TABLE fc_.experiment_assignments (
  experiment_key text NOT NULL,
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  variant text NOT NULL,
  assigned_at timestamptz NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
  PRIMARY KEY (experiment_key, user_id)
);

CREATE TABLE fc_.experiment_outcomes (
  experiment_key text NOT NULL,
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  metric_name text NOT NULL,
  value numeric NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
  PRIMARY KEY (experiment_key, user_id, metric_name)
);

CREATE TABLE fc_.ai_inference_costs (
  user_id bigint NOT NULL REFERENCES fc_.users(user_id),
  cost_month date NOT NULL,
  sessions integer NOT NULL CHECK (sessions >= 0),
  cost_usd numeric(10,2) NOT NULL CHECK (cost_usd >= 0),
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
  PRIMARY KEY (user_id, cost_month)
);

CREATE TABLE fc_.pricing_model_inputs (
  input_key text PRIMARY KEY,
  value numeric NOT NULL,
  unit text NOT NULL,
  is_assumption boolean NOT NULL,
  source_note text NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)
);
