"""FitConnect synthetic data configuration.

FitConnect is a FICTIONAL company. Everything generated here is SYNTHETIC.
Scenario semantics (the patterns below) are fixed. Only the scale (`users`) and `seed` are
configurable. A fixed seed always reproduces identical output.
"""

import datetime as dt
from dataclasses import dataclass

GENERATOR_VERSION = "fc-gen-0.1"
DEFAULT_SEED = 20260401


@dataclass(frozen=True)
class GenConfig:
    seed: int = DEFAULT_SEED
    users: int = 50_000
    window_start: dt.date = dt.date(2025, 10, 1)       # 12 months of data
    window_end: dt.date = dt.date(2026, 9, 30)
    signup_end: dt.date = dt.date(2026, 8, 31)         # leaves time for D90 retention to mature
    as_of: dt.date = dt.date(2026, 10, 1)


# ---- shared population model (latent, documented in the manifest) ----
TIER_NAMES = ["high", "medium", "low"]
TIER_P = [0.15, 0.45, 0.40]
TIER_LIFETIME_MULT = [3.0, 1.2, 0.5]
TIER_ACTIVE_DAYS_PER_WEEK = [3.0, 1.6, 0.7]
TIER_LABEL_NOISE = 0.10                                  # observed tier differs from latent tier
BASE_LIFETIME_SCALE_DAYS = 55.0
LIFETIME_WEIBULL_SHAPE = 0.8

PLATFORMS = ["android", "ios", "web"]
PLATFORM_P = [0.45, 0.40, 0.15]
COUNTRIES = ["US", "UK", "CA", "AU", "DE"]
COUNTRY_P = [0.40, 0.15, 0.17, 0.13, 0.15]
CHANNELS = ["organic", "paid_social", "referral", "search"]
CHANNEL_P = [0.35, 0.25, 0.15, 0.25]

# ---- Scenario 1: AI Coach ----
AI_ADOPT_P_BY_TIER = [0.55, 0.18, 0.04]                  # power-user selection effect
AI_ADOPTION_DAY_RANGE = (3, 12)                          # adopters must survive to adoption day
AI_TRUE_REMAINING_LIFE_EFFECT = 0.05                     # small true causal effect
AI_COST_PER_SESSION_USD = 1.35
AI_FIXED_COST_PER_ACTIVE_MONTH_USD = 0.40
AI_EXPERIMENT = dict(
    key="ai_coach_holdout_2026q1", start=dt.date(2026, 3, 16), end=dt.date(2026, 3, 29),
    sample_share_of_users=0.03, planned_share_of_users=0.08,
    treatment_share_actual=0.30, treatment_share_planned=0.50,
    prior_activity_window=(dt.date(2026, 3, 2), dt.date(2026, 3, 15)),
    tier_selection_weights=[3.0, 1.5, 1.0], extra_workouts_mean=0.3, extra_sessions_mean=2.0,
    control_contamination_share=0.12, contamination_sessions_mean=1.5,
)

# ---- Scenario 2: Onboarding ----
DEFECT_START = dt.date(2026, 8, 3)
ONB_P_STEP1, ONB_P_STEP2_PRE, ONB_P_STEP2_POST, ONB_P_STEP3, ONB_P_COMPLETE = 0.88, 0.78, 0.74, 0.85, 0.92
ONB_LATE_COMPLETION_SHARE = 0.10                         # completions after day 7 (not counted as activated_7d)
DEFECT_ANDROID_COMPLETED_EVENT_KEEP = 0.40               # only 40% of true completions are tracked
ONB_COMPLAINT_P_PRE, ONB_COMPLAINT_P_POST, ONB_COMPLAINT_P_POST_ANDROID = 0.012, 0.028, 0.036
APP_VERSIONS_PRE = {"android": "5.1.2", "ios": "5.1.3", "web": "5.1.4"}
APP_VERSIONS_POST = {"android": "5.2.0", "ios": "5.2.0", "web": "5.1.4"}

# ---- Scenario 3: Premium pricing ----
PRICE_STANDARD, PRICE_PILOT = 9.99, 11.99
PILOT_START = dt.date(2026, 4, 1)
PILOT_COUNTRIES = ["CA", "AU"]
TRIAL_P, TRIAL_START_DAY_MAX, TRIAL_LENGTH_DAYS = 0.40, 10, 14
CONVERSION_BASE = 0.38
CONVERSION_MULT = {"CA_pilot": 0.78, "AU_pilot": 0.98, "exp_treatment": 0.93}
MONTHLY_CHURN = {"standard": 0.065, "CA_pilot": 0.12, "AU_pilot": 0.067, "exp_treatment": 0.07}
PRICE_EXPERIMENT = dict(
    key="premium_price_test_2026q2", start=dt.date(2026, 5, 1), end=dt.date(2026, 5, 28),
    sample_share_of_users=0.028, planned_per_arm_share_of_users=0.08,
)
PRICING_INPUTS = [
    ("current_price_monthly", 9.99, "USD", False, "Observed list price (synthetic)"),
    ("proposed_price_monthly", 11.99, "USD", False, "Proposed premium price (synthetic)"),
    ("assumed_price_elasticity", -0.40, "ratio", True,
     "Finance planning assumption (synthetic). Not measured. No sensitivity range provided."),
    ("assumed_incremental_monthly_churn_pp", 0.5, "percentage_points", True,
     "Finance planning assumption (synthetic). Not measured."),
    ("variable_cost_per_subscriber_monthly", 1.10, "USD", False, "Payment and support cost estimate (synthetic)"),
    ("planning_horizon_months", 12, "months", True, "Planning convention (synthetic)"),
]

# ---- Scenario 4: Community / challenges ----
STYLE_NAMES = ["social_exerciser", "solo_athlete", "time_pressed"]
STYLE_P = [0.30, 0.50, 0.20]
STYLE_LIFETIME_MULT = [1.25, 1.0, 0.85]
JOIN_P_BY_STYLE = [0.45, 0.10, 0.08]
JOIN_P_HIGH_TIER_BONUS = 0.08
JOIN_DAY_RANGE = (0, 6)                                  # early, so no immortal-time bias
COMMUNITY_REMAINING_LIFE_MULT = [2.00, 0.85, 0.45]       # true effect: positive, slightly negative, negative

# ---- activity model ----
P_WORKOUT_STARTED, P_WORKOUT_COMPLETED = 0.70, 0.85
P_AI_SESSION_PER_ACTIVE_DAY, P_CHECKIN_PER_ACTIVE_DAY = 0.50, 0.40

# ---- customer feedback volumes (shares of users) ----
FEEDBACK_GENERIC_SHARE = 0.03
FEEDBACK_AI_ADOPTER_SHARE = 0.12                          # of adopters


