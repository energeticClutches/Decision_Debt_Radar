"""Machine-readable defect/pattern manifest (ground truth for the four FitConnect scenarios).

FitConnect is FICTIONAL and all data is SYNTHETIC. Each scenario lists the patterns the
generator deliberately seeded, the defects (with detection signals for later DQ checks) and
`checks`: SQL that returns one number, compared against bounds. These checks validate that the
LOADED data really contains the documented patterns. They are data-validation queries, not
product analytics.
"""

from __future__ import annotations

import datetime as dt

from . import config as C

RETAINED_CTE = """
WITH ret AS (
  SELECT u.user_id, u.prior_engagement_tier AS tier, u.engagement_style AS style,
         EXISTS (SELECT 1 FROM fc_.events e
                  WHERE e.user_id = u.user_id AND e.event_name = 'app_open'
                    AND e.event_ts >= u.signup_ts + interval '90 days') AS retained
  FROM fc_.users u
  WHERE u.signup_ts < timestamptz '2026-07-01 00:00:00+00'
)"""

AI_FLAG_CTE = """,
ai AS (
  SELECT DISTINCT user_id FROM fc_.events
   WHERE event_name = 'ai_coach_session'
     AND user_id NOT IN (SELECT user_id FROM fc_.experiment_assignments
                          WHERE experiment_key = 'ai_coach_holdout_2026q1')
)"""

COM_FLAG_CTE = """,
com AS (SELECT DISTINCT user_id FROM fc_.events WHERE event_name = 'challenge_joined')"""

ACT7 = """
WITH act AS (
  SELECT u.user_id, u.platform, u.signup_ts,
         EXISTS (SELECT 1 FROM fc_.events e WHERE e.user_id = u.user_id AND e.event_name = 'onboarding_completed'
                  AND e.event_ts < u.signup_ts + interval '7 days') AS activated
  FROM fc_.users u
)"""

D = C.DEFECT_START.isoformat()


def check(cid, description, sql, op, bound, scenario):
    return {"id": cid, "scenario": scenario, "description": description, "sql": " ".join(sql.split()),
            "op": op, "bound": bound}


def build_manifest(cfg: C.GenConfig, meta: dict) -> dict:
    pe, ae = C.PRICE_EXPERIMENT, C.AI_EXPERIMENT
    checks = []

    # ---------------------------------------------------------------- global
    fc_tables = ["users", "events", "subscriptions", "feedback", "feedback_ground_truth",
                 "experiment_assignments", "experiment_outcomes", "ai_inference_costs", "pricing_model_inputs"]
    nonsyn = " + ".join(f"(SELECT count(*) FROM fc_.{t} WHERE NOT is_synthetic)" for t in fc_tables)
    checks += [
        check("GLB-001", "No fc_ row is flagged non-synthetic", f"SELECT {nonsyn}", "==", 0, "global"),
        check("GLB-002", "User count equals the configured scale", "SELECT count(*) FROM fc_.users", "==", cfg.users, "global"),
        check("GLB-003", "All events fall inside the 12-month window",
              f"SELECT count(*) FROM fc_.events WHERE event_ts < timestamptz '{cfg.window_start} 00:00:00+00' "
              f"OR event_ts >= timestamptz '{cfg.window_end + dt.timedelta(days=1)} 00:00:00+00'", "==", 0, "global"),
        check("GLB-004", "Average events per user is in the intended range",
              "SELECT (SELECT count(*) FROM fc_.events)::numeric / (SELECT count(*) FROM fc_.users)",
              "between", [25, 60], "global"),
    ]

    # ---------------------------------------------------------------- scenario 1: AI Coach
    gap_sql = RETAINED_CTE + AI_FLAG_CTE + """
      SELECT (SELECT avg(retained::int) FROM ret WHERE user_id IN (SELECT user_id FROM ai))
           - (SELECT avg(retained::int) FROM ret WHERE user_id NOT IN (SELECT user_id FROM ai))"""
    within_sql = RETAINED_CTE + AI_FLAG_CTE + """,
      t AS (SELECT tier, (user_id IN (SELECT user_id FROM ai)) AS adopter, avg(retained::int) AS r, count(*) AS n
              FROM ret GROUP BY 1, 2),
      g AS (SELECT a.tier, a.n AS n_adopt, a.r - b.r AS gap FROM t a JOIN t b ON a.tier = b.tier AND a.adopter AND NOT b.adopter)
      SELECT (SELECT sum(n_adopt * gap) / sum(n_adopt) FROM g)"""
    within_ratio = RETAINED_CTE + AI_FLAG_CTE + """,
      t AS (SELECT tier, (user_id IN (SELECT user_id FROM ai)) AS adopter, avg(retained::int) AS r, count(*) AS n
              FROM ret GROUP BY 1, 2),
      g AS (SELECT a.n AS n_adopt, a.r - b.r AS gap FROM t a JOIN t b ON a.tier = b.tier AND a.adopter AND NOT b.adopter),
      raw AS (SELECT (SELECT avg(retained::int) FROM ret WHERE user_id IN (SELECT user_id FROM ai))
                   - (SELECT avg(retained::int) FROM ret WHERE user_id NOT IN (SELECT user_id FROM ai)) AS gap)
      SELECT (SELECT sum(n_adopt * gap) / sum(n_adopt) FROM g) / (SELECT gap FROM raw)"""
    checks += [
        check("AI-001", "Observational: adopters retain much better than non-adopters at D90 (raw gap)", gap_sql, ">=", 0.15, "ai_coach"),
        check("AI-002", "Power-user selection: adopters are over-represented in the high engagement tier (ratio vs population)",
              """WITH ai AS (SELECT DISTINCT user_id FROM fc_.events WHERE event_name='ai_coach_session'
                 AND user_id NOT IN (SELECT user_id FROM fc_.experiment_assignments WHERE experiment_key='ai_coach_holdout_2026q1'))
                 SELECT (SELECT avg((prior_engagement_tier='high')::int) FROM fc_.users WHERE user_id IN (SELECT user_id FROM ai))
                      / (SELECT avg((prior_engagement_tier='high')::int) FROM fc_.users)""", ">=", 2.0, "ai_coach"),
        check("AI-003", "Within engagement tiers the adopter gap is a small fraction of the raw gap (selection explains most of it)",
              within_ratio, "<=", 0.45, "ai_coach"),
        check("AI-004", "High inference cost: median monthly cost per adopter-month (USD)",
              "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY cost_usd) FROM fc_.ai_inference_costs", ">=", 4.0, "ai_coach"),
        check("AI-005", "Positive customer evidence: share of positive AI Coach feedback",
              "SELECT avg((sentiment='positive')::int) FROM fc_.feedback_ground_truth WHERE scenario_key='ai_coach'", ">=", 0.65, "ai_coach"),
        check("AI-006", "Imbalanced experiment: treatment share far from the planned 50%",
              f"SELECT avg((variant='ai_coach')::int) FROM fc_.experiment_assignments WHERE experiment_key='{ae['key']}'",
              "between", [0.25, 0.35], "ai_coach"),
        check("AI-007", "Short experiment: duration in days",
              f"SELECT (DATE '{ae['end']}' - DATE '{ae['start']}' + 1)", "<=", 14, "ai_coach"),
        check("AI-008", "Weak experiment: enrolled users as a share of the planned sample",
              f"SELECT count(*)::numeric / {meta['ai_experiment_planned_total']} FROM fc_.experiment_assignments "
              f"WHERE experiment_key='{ae['key']}'", "<=", 0.5, "ai_coach"),
    ]

    # ---------------------------------------------------------------- scenario 2: Onboarding
    def act_expr(where_pre, where_post, extra=""):
        return (f"(SELECT avg(activated::int) FROM act WHERE {where_pre} {extra}) "
                f"- (SELECT avg(activated::int) FROM act WHERE {where_post} {extra})")

    def act_diff(where_pre, where_post, extra=""):
        return ACT7 + " SELECT " + act_expr(where_pre, where_post, extra)
    pre = "signup_ts >= timestamptz '2026-06-01 00:00:00+00' AND signup_ts < timestamptz '" + D + " 00:00:00+00'"
    post = "signup_ts >= timestamptz '" + D + " 00:00:00+00'"
    checks += [
        check("ONB-001", "Apparent activation decline (measured activation_7d, pre minus post defect date)", act_diff(pre, post), ">=", 0.10, "onboarding"),
        check("ONB-002", "Apparent decline is concentrated on android", act_diff(pre, post, "AND platform='android'"), ">=", 0.25, "onboarding"),
        check("ONB-003", "ios barely moves (absolute change)", ACT7 + " SELECT abs(" + act_expr(pre, post, "AND platform='ios'") + ")", "<=", 0.05, "onboarding"),
        check("ONB-004", "DEFECT: android step 2 event never fires after the release date",
              f"SELECT count(*) FROM fc_.events WHERE event_name='onboarding_step_2_completed' AND platform='android' "
              f"AND event_ts >= timestamptz '{D} 00:00:00+00'", "==", 0, "onboarding"),
        check("ONB-005", "DEFECT signal: android step 3 events still fire after the release date (sequence violation)",
              f"SELECT count(*) FROM fc_.events WHERE event_name='onboarding_step_3_completed' AND platform='android' "
              f"AND event_ts >= timestamptz '{D} 00:00:00+00'", ">=", 100, "onboarding"),
        check("ONB-006", "Increased complaints: onboarding tickets per 1,000 signups, post vs pre (ratio)",
              f"""WITH c AS (SELECT f.created_at, f.user_id FROM fc_.feedback f JOIN fc_.feedback_ground_truth g USING (feedback_id)
                          WHERE g.theme='onboarding_complaint'),
                  pre AS (SELECT count(*)::numeric / NULLIF((SELECT count(*) FROM fc_.users WHERE {pre}),0) AS r
                            FROM c JOIN fc_.users u USING (user_id) WHERE u.{pre}),
                  post AS (SELECT count(*)::numeric / NULLIF((SELECT count(*) FROM fc_.users WHERE {post}),0) AS r
                            FROM c JOIN fc_.users u USING (user_id) WHERE u.{post})
                  SELECT (SELECT r FROM post) / (SELECT r FROM pre)""", ">=", 1.8, "onboarding"),
        check("ONB-007", "Ground truth: TRUE onboarding completion changed far less than measured (generator truth, pre minus post, below 6 points)",
              f"SELECT {meta['true_onboarding_completion_pre']} - {meta['true_onboarding_completion_post']}",
              "between", [-0.03, 0.06], "onboarding"),
    ]

    # ---------------------------------------------------------------- scenario 3: Pricing
    def conv(cohort_where):
        return f"""SELECT avg((s.status='trial_converted')::int) FROM fc_.subscriptions s JOIN fc_.users u USING (user_id)
                    WHERE s.plan='free_trial' AND {cohort_where}"""
    ca_pre = "u.country='CA' AND u.signup_ts < timestamptz '2026-04-01 00:00:00+00'"
    ca_post = "u.country='CA' AND u.signup_ts >= timestamptz '2026-04-01 00:00:00+00'"
    au_pre = ca_pre.replace("'CA'", "'AU'")
    au_post = ca_post.replace("'CA'", "'AU'")

    def churn(where):
        # share of premium subscriptions cancelled within 90 days (subscriptions started by 2026-06-30 so 90 days is observable)
        return f"""SELECT avg((s.status='cancelled' AND s.end_date <= s.start_date + 90)::int)
                     FROM fc_.subscriptions s JOIN fc_.users u USING (user_id)
                    WHERE s.plan='premium' AND s.start_date <= DATE '2026-06-30' AND {where}"""
    std = ("u.user_id NOT IN (SELECT user_id FROM fc_.experiment_assignments WHERE experiment_key='" + pe["key"] + "') "
           "AND NOT (u.country IN ('CA','AU') AND u.signup_ts >= timestamptz '2026-04-01 00:00:00+00')")
    ca_churn_where = "u.country='CA' AND u.signup_ts >= timestamptz '2026-04-01 00:00:00+00'"
    checks += [
        check("PRC-001", "Financial upside model inputs present", "SELECT count(*) FROM fc_.pricing_model_inputs", ">=", 6, "pricing"),
        check("PRC-002", "Financial inputs contain NO sensitivity range (deliberate gap)",
              "SELECT count(*) FROM fc_.pricing_model_inputs WHERE input_key ILIKE '%sensitivity%' OR input_key ILIKE '%range%'", "==", 0, "pricing"),
        check("PRC-003", "Conversion effect in some cohorts: CA pilot trial-to-paid change vs pre-pilot",
              f"SELECT ({conv(ca_post)}) - ({conv(ca_pre)})", "<=", -0.05, "pricing"),
        check("PRC-004", "No material conversion effect in the AU pilot cohort (absolute change)",
              f"SELECT abs(({conv(au_post)}) - ({conv(au_pre)}))", "<=", 0.04, "pricing"),
        check("PRC-005", "Churn effect: CA pilot 90-day churn relative to standard (ratio)",
              f"SELECT ({churn(ca_churn_where)}) / ({churn(std)})",
              ">=", 1.25, "pricing"),
        check("PRC-006", "Pricing-sensitive customer feedback dominates pricing feedback (share negative)",
              "SELECT avg((sentiment='negative')::int) FROM fc_.feedback_ground_truth WHERE scenario_key='pricing'", ">=", 0.5, "pricing"),
        check("PRC-007", "Experiment is inconclusive: |conversion difference| is within 1.96 standard errors",
              f"""WITH x AS (SELECT a.variant, count(*) AS n, avg(o.value) AS p FROM fc_.experiment_outcomes o
                    JOIN fc_.experiment_assignments a USING (experiment_key, user_id)
                   WHERE o.experiment_key='{pe['key']}' GROUP BY 1),
                   c AS (SELECT * FROM x WHERE variant LIKE 'control%'), t AS (SELECT * FROM x WHERE variant LIKE 'treatment%')
                   SELECT abs(t.p - c.p) / (1.96 * sqrt(c.p*(1-c.p)/c.n + t.p*(1-t.p)/t.n)) FROM c, t""", "<", 1.0, "pricing"),
        check("PRC-008", "Underpowered experiment: enrolled users per arm as a share of the planned per-arm sample",
              f"SELECT (count(*)::numeric / 2) / {meta['pricing_experiment_per_arm_planned']} FROM fc_.experiment_assignments "
              f"WHERE experiment_key='{pe['key']}'", "<=", 0.25, "pricing"),
    ]

    # ---------------------------------------------------------------- scenario 4: Community
    def com_gap(style=None):
        flt = f"WHERE style = '{style}'" if style else ""
        return (RETAINED_CTE + COM_FLAG_CTE +
                f""" SELECT (SELECT avg(retained::int) FROM ret {flt + (' AND' if flt else 'WHERE')} user_id IN (SELECT user_id FROM com))
                          - (SELECT avg(retained::int) FROM ret {flt + (' AND' if flt else 'WHERE')} user_id NOT IN (SELECT user_id FROM com))""")
    checks += [
        check("COM-001", "Strong aggregate retention relationship that masks segment differences (joiners minus non-joiners)", com_gap(), ">=", 0.12, "community"),
        check("COM-002", "Segment A (social_exerciser): strongly positive", com_gap("social_exerciser"), ">=", 0.15, "community"),
        check("COM-003", "Segment B (solo_athlete): near zero or negative", com_gap("solo_athlete"), "<=", 0.02, "community"),
        check("COM-004", "Segment C (time_pressed): negative", com_gap("time_pressed"), "<=", -0.05, "community"),
        check("COM-005", "Composition drives the aggregate: share of joiners in segment A",
              "SELECT avg((u.engagement_style='social_exerciser')::int) FROM fc_.users u WHERE u.user_id IN "
              "(SELECT user_id FROM fc_.events WHERE event_name='challenge_joined')", ">=", 0.55, "community"),
        check("COM-006", "Notification complaints come from the time_pressed segment (share)",
              "SELECT avg((u.engagement_style='time_pressed')::int) FROM fc_.feedback_ground_truth g JOIN fc_.feedback f USING (feedback_id) "
              "JOIN fc_.users u ON u.user_id=f.user_id WHERE g.theme='community_negative_notifications'", ">=", 0.9, "community"),
    ]

    return {
        "manifest_version": "1.0",
        "generator_version": C.GENERATOR_VERSION,
        "synthetic": True,
        "synthetic_notice": "FitConnect is a FICTIONAL company. All data described here is SYNTHETIC.",
        "seed": cfg.seed,
        "scale": {"users": cfg.users, "window_start": str(cfg.window_start), "window_end": str(cfg.window_end),
                  "signup_end": str(cfg.signup_end)},
        "min_users_for_pattern_checks": 20000,
        "generator_truth": meta,
        "scenarios": {
            "ai_coach": {
                "decision": "Invest in expanding the AI Coach",
                "patterns": [
                    "positive observational engagement/retention relationship",
                    "power-user selection effect (adoption concentrated in the high engagement tier)",
                    "positive customer feedback among adopters",
                    "high inference cost per active adopter-month",
                    "weak, imbalanced (30/70 vs planned 50/50), short (14 day) experiment with contamination",
                ],
                "generator_parameters": {
                    "adopt_p_by_latent_tier": C.AI_ADOPT_P_BY_TIER,
                    "true_remaining_life_effect": C.AI_TRUE_REMAINING_LIFE_EFFECT,
                    "adoption_day_range": list(C.AI_ADOPTION_DAY_RANGE),
                    "cost_per_session_usd": C.AI_COST_PER_SESSION_USD,
                },
                "expected_downstream": {"assessment_state": "scored", "ddi_band": ["moderate", "high"],
                                        "reviewer_flags": ["correlation_vs_causation", "selection_bias", "weak_experiment", "cost_not_weighed"],
                                        "next_best_evidence": ["powered_holdout_test"]},
            },
            "onboarding": {
                "decision": "Fund a full onboarding redesign",
                "patterns": [
                    "apparent activation decline (measured)", "apparent onboarding abandonment increase (measured)",
                    "increased onboarding complaints", "true completion barely changed",
                ],
                "defects": [
                    {"id": "DEF-ONB-001", "table": "fc_.events", "event_name": "onboarding_step_2_completed",
                     "platform": "android", "app_version": "5.2.0", "starts": str(C.DEFECT_START), "loss_rate": 1.0,
                     "effect": "step 2 never fires, creating a spurious step 2 to 3 abandonment on android",
                     "detection_signals": ["platform x event volume discontinuity at the release date",
                                           "event-sequence violation: step 3 without step 2"]},
                    {"id": "DEF-ONB-002", "table": "fc_.events", "event_name": "onboarding_completed",
                     "platform": "android", "app_version": "5.2.0", "starts": str(C.DEFECT_START),
                     "loss_rate": round(1 - C.DEFECT_ANDROID_COMPLETED_EVENT_KEEP, 2),
                     "effect": "60% of true completions are not tracked, so measured activation_7d falls sharply on android",
                     "detection_signals": ["completion-to-step-3 ratio collapses on android after the release date",
                                           "android versus ios divergence in the success metric"]},
                ],
                "affects_success_metric": "activation_rate_7d",
                "expected_downstream": {"assessment_state": "insufficient_evidence", "ddi_band": None,
                                        "blocking_reason": "open critical DQ failure on the success metric data",
                                        "next_best_evidence": ["fix_dq_or_instrumentation"]},
            },
            "pricing": {
                "decision": "Raise the premium subscription price",
                "patterns": [
                    "financial upside model inputs (assumed elasticity, no sensitivity range)",
                    "pricing-sensitive customer feedback (heavier in the CA pilot cohort)",
                    "conversion decline in the CA pilot cohort, no material decline in AU, churn uplift in CA",
                    "inconclusive, underpowered price experiment",
                ],
                "generator_parameters": {"price_standard": C.PRICE_STANDARD, "price_pilot": C.PRICE_PILOT,
                                         "pilot_start": str(C.PILOT_START), "conversion_multipliers": C.CONVERSION_MULT,
                                         "monthly_churn": C.MONTHLY_CHURN},
                "expected_downstream": {"assessment_state": "scored", "ddi_band": ["high"],
                                        "reviewer_flags": ["inconclusive_experiment", "assumed_elasticity"],
                                        "next_best_evidence": ["financial_model_with_sensitivity", "powered_holdout_test"]},
            },
            "community": {
                "decision": "Invest in community challenges",
                "patterns": [
                    "strong aggregate retention relationship", "materially different segment effects",
                    "composition-driven aggregate: joiners are mostly the high-baseline segment",
                    "aggregate-vs-segment heterogeneity / aggregate masking: the positive aggregate conceals "
                    "an about-zero effect in segment B and a negative effect in segment C (together about 70% of users)",
                ],
                "terminology_note": ("Related to Simpson-type aggregation risks, but this is not a textbook Simpson's "
                                     "paradox: the aggregate is positive and segment effects are mixed, not all reversed."),
                "generator_parameters": {"join_p_by_style": C.JOIN_P_BY_STYLE,
                                         "remaining_life_multiplier_by_style": C.COMMUNITY_REMAINING_LIFE_MULT,
                                         "style_lifetime_multiplier": C.STYLE_LIFETIME_MULT},
                "expected_downstream": {"assessment_state": "scored", "ddi_band": ["moderate"],
                                        "reviewer_flags": ["aggregate_masking"],
                                        "heterogeneity_flag": True,
                                        "next_best_evidence": ["segment_level_analysis", "powered_holdout_test"],
                                        "recommendation": "segment-aware validation"},
            },
        },
        "checks": checks,
    }



