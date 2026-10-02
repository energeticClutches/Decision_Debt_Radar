"""Seed the core (industry-agnostic) tables with the SYNTHETIC FitConnect demo organization.

Deterministic: ids are uuid5 values and every timestamp is a fixed value, so the seeded core
rows are reproducible. FitConnect is a FICTIONAL company. Everything seeded is synthetic.

Not seeded on purpose: evidence, analysis results, assessments, claims, DQ checks,
recommendations, reviews, customer insights, experiment results. Those are produced by later
pipeline stages (Day 3+).
"""

from __future__ import annotations

import json
import uuid

NS = uuid.UUID("6f1c0a5e-9d34-4c1b-8a57-0d3f6b2e7a10")
AS_OF_TS = "2026-10-01T00:00:00+00:00"
CANVAS_TS = "2026-10-01T08:00:00+00:00"


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


ORG = uid("org:fitconnect")

TEAMS = ["Product", "Growth", "Strategy and Business Operations"]
USERS = [  # (key, name, role, team)
    ("pm1", "Priya Raman (synthetic)", "pm", "Product"),
    ("pm2", "Marcus Webb (synthetic)", "pm", "Growth"),
    ("ba1", "Elena Duarte (synthetic)", "ba", "Product"),
    ("pa1", "Tom Okafor (synthetic)", "product_analyst", "Growth"),
    ("biz1", "Sana Iqbal (synthetic)", "bizops", "Strategy and Business Operations"),
    ("lead1", "Hannah Lindqvist (synthetic)", "dept_leader", "Product"),
    ("exec1", "Rafael Ortiz (synthetic)", "executive", "Strategy and Business Operations"),
]

# (key, name, source_type, cadence, tier, rationale, fc_ref)
DATA_SOURCES = [
    ("events", "FitConnect product events (fc_.events)", "csv", "daily", 2,
     "Client-side event tracking. Subject to SDK and release-version tracking risks.", "fc_.events"),
    ("subs", "FitConnect subscriptions (fc_.subscriptions)", "csv", "daily", 1,
     "Billing-system export. High reliability for subscription state and price.", "fc_.subscriptions"),
    ("feedback", "FitConnect customer feedback (fc_.feedback)", "survey", "weekly", 3,
     "Reviews, surveys and support tickets. Self-selected respondents.", "fc_.feedback"),
    ("experiments", "FitConnect experiment export (fc_.experiment_*)", "csv", "per experiment", 2,
     "Experimentation platform export. Assignment integrity not independently verified.", "fc_.experiment_assignments"),
    ("ai_costs", "FitConnect AI inference costs (fc_.ai_inference_costs)", "csv", "monthly", 1,
     "Cloud billing export of inference cost.", "fc_.ai_inference_costs"),
    ("pricing_inputs", "FitConnect pricing model inputs (fc_.pricing_model_inputs)", "csv", "ad hoc", 3,
     "Finance planning assumptions. Not measured data.", "fc_.pricing_model_inputs"),
]

RETAINED_SQL = ("User is retained at D90 if they have an app_open event at least 90 days after signup. "
                "Cohort: signups before 2026-07-01 (so D90 has matured).")
METRICS = [  # (key, name, definition, sql_logic, unit, grain, source)
    ("d90", "d90_retention", "Share of a signup cohort with an app_open event 90 or more days after signup.",
     "SELECT avg(EXISTS (SELECT 1 FROM fc_.events e WHERE e.user_id=u.user_id AND e.event_name='app_open' "
     "AND e.event_ts >= u.signup_ts + interval '90 days')::int) FROM fc_.users u WHERE u.signup_ts < '2026-07-01'",
     "ratio", "signup cohort", "events"),
    ("act7", "activation_rate_7d", "Share of new users with an onboarding_completed event within 7 days of signup.",
     "SELECT avg(EXISTS (SELECT 1 FROM fc_.events e WHERE e.user_id=u.user_id AND e.event_name='onboarding_completed' "
     "AND e.event_ts < u.signup_ts + interval '7 days')::int) FROM fc_.users u",
     "ratio", "signup week", "events"),
    ("conv", "paid_conversion_rate", "Share of free-trial starters whose trial converted to a paid premium subscription.",
     "SELECT avg((status='trial_converted')::int) FROM fc_.subscriptions WHERE plan='free_trial'",
     "ratio", "signup week", "subs"),
    ("newusers", "weekly_new_users", "Number of signups per week.",
     "SELECT date_trunc('week', signup_ts), count(*) FROM fc_.users GROUP BY 1", "count", "week", "events"),
    ("aicost", "ai_inference_cost_per_active_user", "Average monthly AI inference cost (USD) per user with AI Coach sessions.",
     "SELECT cost_month, sum(cost_usd)/count(DISTINCT user_id) FROM fc_.ai_inference_costs GROUP BY 1",
     "USD", "month", "ai_costs"),
    ("churn", "monthly_premium_churn", "Share of active premium subscriptions cancelled per month.",
     "Defined for later analysis (subscription-month exposure model).", "ratio", "month", "subs"),
]

# decision key, scenario, team, owner, metric, risk, type, due, title, description, hypothesis, notes, criteria
DECISIONS = [
    ("ai_coach", "ai_coach", "Product", "pm1", "d90", "high", "product_feature_investment", "2026-10-31",
     "Invest in expanding the AI Coach",
     "Fund a dedicated team and inference budget to expand the AI Coach across the product.",
     "If we expand the AI Coach, then 90-day retention increases, because users get personalised guidance that keeps them training.",
     "Retention appears higher among AI Coach users. Feedback from adopters is positive. Inference cost per active user is high. One short holdout experiment exists.",
     ["A properly powered holdout test shows less than a 2 percentage point effect on D90 retention",
      "The retention difference disappears after controlling for prior engagement level",
      "Inference cost per retained user exceeds the planned cost threshold"]),
    ("onboarding", "onboarding", "Growth", "pm2", "act7", "medium", "process_or_ux_change", "2026-10-15",
     "Fund a full onboarding redesign",
     "Commission a full redesign of the onboarding flow.",
     "If we redesign onboarding, then 7-day activation increases, because users are abandoning during setup.",
     "Activation appears to have declined in recent weeks and onboarding complaints have risen.",
     ["Activation decline is confirmed on every platform using trustworthy tracking",
      "Step-level conversion is shown to fall for real users, not only in event data",
      "A controlled test shows the redesign improves 7-day activation by at least 3 percentage points"]),
    ("pricing", "pricing", "Growth", "pm2", "conv", "high", "pricing_change", "2026-11-15",
     "Raise the premium subscription price",
     "Raise the premium monthly price from 9.99 to 11.99.",
     "If we raise the premium price from 9.99 to 11.99, then revenue per user increases without unacceptable churn, because demand is relatively price-inelastic.",
     "A simple revenue model shows upside. Some customers say the price is too high. A price experiment was run but was small.",
     ["A price test shows trial-to-paid conversion falling by more than 3 percentage points",
      "Monthly churn increases by more than 1 percentage point in any major cohort",
      "A revenue model under pessimistic elasticity shows no net revenue gain"]),
    ("community", "community", "Product", "pm1", "d90", "medium", "product_feature_investment", "2026-11-30",
     "Invest in community challenges",
     "Invest in community and challenge features across the product.",
     "If we invest in community challenges, then 90-day retention increases, because social accountability keeps users training.",
     "Users who join challenges show much higher retention overall. Feedback is mixed.",
     ["Retention benefit holds within each major user segment, not just in the aggregate",
      "Any user segment shows a negative retention effect from challenge participation",
      "A segment-level test shows the effect is concentrated in specific users"]),
]


def seed_core(conn, meta: dict, experiments_meta: dict) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT set_config('ddr.as_of', '2026-10-01', false)")
    cur.execute("INSERT INTO organizations (id, name, industry, is_synthetic) VALUES (%s,%s,%s,true)",
                (ORG, "FitConnect (fictional, synthetic demo)", "fitness_wellness_technology"))
    team_id = {t: uid(f"team:{t}") for t in TEAMS}
    for t, i in team_id.items():
        cur.execute("INSERT INTO teams (id, org_id, name, is_synthetic) VALUES (%s,%s,%s,true)", (i, ORG, t))
    user_id = {}
    for key, name, role, team in USERS:
        user_id[key] = uid(f"user:{key}")
        cur.execute("INSERT INTO users (id, org_id, team_id, name, email, role, is_synthetic) VALUES (%s,%s,%s,%s,%s,%s,true)",
                    (user_id[key], ORG, team_id[team], name, f"{key}@fitconnect.example", role))
    ds_id, es_id = {}, {}
    for key, name, stype, cadence, tier, why, ref in DATA_SOURCES:
        ds_id[key] = uid(f"ds:{key}")
        es_id[key] = uid(f"es:{key}")
        cur.execute("INSERT INTO data_sources (id, org_id, name, source_type, owner_id, refresh_cadence, last_loaded_at,"
                    " reliability_tier, tier_rationale, is_synthetic) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",
                    (ds_id[key], ORG, name, stype, user_id["pa1"], cadence, AS_OF_TS, tier, why))
        cur.execute("INSERT INTO evidence_sources (id, org_id, data_source_id, title, ref, source_type, collected_at,"
                    " reliability_tier, is_synthetic) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true)",
                    (es_id[key], ORG, ds_id[key], name, ref, stype, AS_OF_TS, tier))
    metric_id = {}
    for key, name, definition, sql_logic, unit, grain, src in METRICS:
        metric_id[key] = uid(f"metric:{key}")
        cur.execute("INSERT INTO metrics (id, org_id, name, definition, sql_logic, unit, grain, data_source_id, owner_id,"
                    " is_synthetic) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",
                    (metric_id[key], ORG, name, definition, sql_logic, unit, grain, ds_id[src], user_id["pa1"]))

    decision_id = {}
    for (key, scen, team, owner, metric, risk, dtype, due, title, desc, hyp, notes, crit) in DECISIONS:
        decision_id[key] = uid(f"decision:{key}")
        cur.execute(
            "INSERT INTO decisions (id, org_id, team_id, title, description, hypothesis, success_metric_id,"
            " decision_due_date, risk_level, current_evidence_notes, change_my_mind_criteria, decision_type,"
            " canvas_completed_at, owner_id, scenario_key, is_synthetic)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,true)",
            (decision_id[key], ORG, team_id[team], title, desc, hyp, metric_id[metric], due, risk, notes,
             json.dumps(crit), dtype, CANVAS_TS, user_id[owner], scen))
        cur.execute("INSERT INTO audit_logs (id, org_id, actor_type, actor_id, action, entity_type, entity_id, after, ts,"
                    " is_synthetic) VALUES (%s,%s,'user',%s,'decision.created','decision',%s,%s::jsonb,%s,true)",
                    (uid(f"audit:{key}:created"), ORG, user_id[owner], decision_id[key],
                     json.dumps({"lifecycle_stage": "created"}), CANVAS_TS))
        # Lifecycle: created -> evidence_gathered (guarded by the DB trigger).
        cur.execute("UPDATE decisions SET lifecycle_stage = 'evidence_gathered' WHERE id = %s", (decision_id[key],))
        cur.execute("INSERT INTO audit_logs (id, org_id, actor_type, actor_id, action, entity_type, entity_id, before, after,"
                    " ts, is_synthetic) VALUES (%s,%s,'user',%s,'decision.evidence_gathered','decision',%s,%s::jsonb,%s::jsonb,%s,true)",
                    (uid(f"audit:{key}:gathered"), ORG, user_id[owner], decision_id[key],
                     json.dumps({"lifecycle_stage": "created"}), json.dumps({"lifecycle_stage": "evidence_gathered"}),
                     AS_OF_TS))

    ae, pe = experiments_meta["ai"], experiments_meta["pricing"]
    exps = [
        ("ai_holdout", "ai_coach", "AI Coach holdout (short, imbalanced)",
         "AI Coach availability increases workouts over 14 days.", "holdout", ae["start"], ae["end"],
         None, meta["ai_experiment_planned_total"], 0.5, ae["key"]),
        ("price_test", "pricing", "Premium price test 9.99 vs 11.99",
         "A higher premium price does not reduce trial-to-paid conversion materially.", "rct", pe["start"], pe["end"],
         "conv", 2 * meta["pricing_experiment_per_arm_planned"], 0.02, pe["key"]),
    ]
    for key, dec, name, hyp, design, start, end, metric, planned, mde, ref in exps:
        cur.execute("INSERT INTO experiments (id, org_id, decision_id, name, hypothesis, design, start_date, end_date, status,"
                    " primary_metric_id, planned_sample, mde, source_ref, is_synthetic)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'completed',%s,%s,%s,%s,true)",
                    (uid(f"exp:{key}"), ORG, decision_id[dec], name, hyp, design, start, end,
                     metric_id[metric] if metric else None, planned, mde, ref))

    # Observations: plain counts and rates by week/month (data preparation, no analysis).
    obs = [
        ("newusers", """SELECT date_trunc('week', signup_ts)::date, NULL::text, NULL::text, count(*)::numeric, count(*)::int
                          FROM fc_.users GROUP BY 1"""),
        ("act7", """WITH a AS (SELECT u.user_id, u.platform, u.signup_ts, EXISTS (SELECT 1 FROM fc_.events e
                       WHERE e.user_id=u.user_id AND e.event_name='onboarding_completed'
                         AND e.event_ts < u.signup_ts + interval '7 days') AS act
                      FROM fc_.users u WHERE u.signup_ts < timestamptz '2026-09-24 00:00:00+00')
                    SELECT date_trunc('week', signup_ts)::date, NULL::text, NULL::text, round(avg(act::int), 4), count(*)::int
                      FROM a GROUP BY 1
                    UNION ALL
                    SELECT date_trunc('week', signup_ts)::date, 'platform', platform, round(avg(act::int), 4), count(*)::int
                      FROM a GROUP BY 1, 3"""),
        ("conv", """SELECT date_trunc('week', u.signup_ts)::date, NULL::text, NULL::text,
                           round(avg((s.status='trial_converted')::int), 4), count(*)::int
                      FROM fc_.subscriptions s JOIN fc_.users u USING (user_id) WHERE s.plan='free_trial' GROUP BY 1"""),
        ("aicost", """SELECT cost_month, NULL::text, NULL::text, round(sum(cost_usd)/count(DISTINCT user_id), 4),
                             count(DISTINCT user_id)::int FROM fc_.ai_inference_costs GROUP BY 1"""),
    ]
    for key, sel in obs:
        cur.execute(
            f"INSERT INTO metric_observations (id, metric_id, observed_at, segment_key, segment_value, value, n_sample, is_synthetic)"
            f" SELECT md5(%s || o.d::text || COALESCE(o.k,'') || COALESCE(o.v,''))::uuid, %s, o.d, o.k, o.v, o.val, o.n, true"
            f" FROM ({sel}) AS o(d, k, v, val, n)", (key, metric_id[key]))
    conn.commit()
    return {"decisions": decision_id, "metrics": metric_id}
