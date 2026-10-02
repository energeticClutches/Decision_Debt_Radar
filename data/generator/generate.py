"""FitConnect synthetic data generator (fixed seed, deterministic, scale-configurable).

FitConnect is FICTIONAL. All output is SYNTHETIC. Scenario semantics are defined in
config.py and documented in the manifest. This module only creates data. It does not
analyse it.
"""

from __future__ import annotations

import calendar
import datetime as dt

import numpy as np
import pandas as pd

from . import config as C
from .feedback import THEME_SENTIMENT, rating_for, render

DAY = 86_400
EVENT_NAMES = [
    "signup_completed", "onboarding_started", "onboarding_step_1_completed",
    "onboarding_step_2_completed", "onboarding_step_3_completed", "onboarding_completed",
    "app_open", "workout_started", "workout_completed", "ai_coach_session",
    "challenge_joined", "challenge_checkin", "paywall_viewed",
]
EV = {name: i for i, name in enumerate(EVENT_NAMES)}


def _epoch(d: dt.date) -> int:
    return calendar.timegm(d.timetuple())


def generate(cfg: C.GenConfig) -> tuple[dict[str, pd.DataFrame], dict]:
    n = cfg.users
    ss = np.random.SeedSequence(cfg.seed)
    (r_users, r_life, r_act, r_onb, r_ai, r_com, r_price, r_exp, r_fb, _spare) = [
        np.random.default_rng(s) for s in ss.spawn(10)
    ]
    T0 = _epoch(cfg.window_start)
    end_idx = (cfg.window_end - cfg.window_start).days
    end_sec = T0 + (end_idx + 1) * DAY            # exclusive end of the observation window
    day_idx = lambda d: (d - cfg.window_start).days  # noqa: E731
    sec_of = lambda d: T0 + day_idx(d) * DAY         # noqa: E731

    # ------------------------------------------------------------------ users
    n_signup_days = (cfg.signup_end - cfg.window_start).days + 1
    day_off = r_users.integers(0, n_signup_days, n)
    tod = r_users.integers(0, DAY, n)
    signup_sec_unsorted = T0 + day_off * DAY + tod
    order = np.argsort(signup_sec_unsorted, kind="stable")
    day_off = day_off[order]
    signup_sec = signup_sec_unsorted[order]
    max_off = end_idx - day_off

    platform = r_users.choice(3, n, p=C.PLATFORM_P)
    country = r_users.choice(len(C.COUNTRIES), n, p=C.COUNTRY_P)
    channel = r_users.choice(len(C.CHANNELS), n, p=C.CHANNEL_P)
    tier = r_users.choice(3, n, p=C.TIER_P)                       # latent tier: 0 high, 1 medium, 2 low
    u = r_users.random(n)
    shift = np.where(u < C.TIER_LABEL_NOISE / 2, -1, np.where(u < C.TIER_LABEL_NOISE, 1, 0))
    tier_obs = np.clip(tier + shift, 0, 2)
    style = r_users.choice(3, n, p=C.STYLE_P)

    # ------------------------------------------------------------------ latent lifetimes
    scale = (C.BASE_LIFETIME_SCALE_DAYS
             * np.array(C.TIER_LIFETIME_MULT)[tier] * np.array(C.STYLE_LIFETIME_MULT)[style])
    life0 = scale * r_life.weibull(C.LIFETIME_WEIBULL_SHAPE, n)

    # Scenario 4: community joiners (early join, so no survival conditioning)
    p_join = np.array(C.JOIN_P_BY_STYLE)[style] + C.JOIN_P_HIGH_TIER_BONUS * (tier == 0)
    joined = r_com.random(n) < p_join
    join_day = np.minimum(r_com.uniform(*C.JOIN_DAY_RANGE, n), life0)
    m_com = np.array(C.COMMUNITY_REMAINING_LIFE_MULT)[style]
    life1 = np.where(joined, life0 + (m_com - 1.0) * (life0 - join_day), life0)

    # Scenario 1: AI Coach adoption (selection on engagement tier; adopters must survive to adoption)
    wants = r_ai.random(n) < np.array(C.AI_ADOPT_P_BY_TIER)[tier]
    adopt_day = r_ai.uniform(*C.AI_ADOPTION_DAY_RANGE, n)
    adopter = wants & (life1 > adopt_day)
    life = np.where(adopter, life1 + C.AI_TRUE_REMAINING_LIFE_EFFECT * (life1 - adopt_day), life1)
    life_days = np.minimum(np.floor(life).astype(np.int64), max_off)

    # ------------------------------------------------------------------ active days
    lam = np.array(C.TIER_ACTIVE_DAYS_PER_WEEK)[tier] / 7.0
    k = r_act.poisson(lam * (life_days + 1))
    uid = np.repeat(np.arange(n), k)
    days = np.floor(r_act.random(uid.size) * (life_days[uid] + 1)).astype(np.int64)
    uid = np.concatenate([uid, np.arange(n), np.arange(n)])
    days = np.concatenate([days, np.zeros(n, np.int64), life_days])
    key = np.unique(uid.astype(np.int64) * 4096 + days)
    a_uid, a_day = key // 4096, key % 4096
    a_mid = T0 + day_off[a_uid] * DAY
    tod_a = r_act.integers(6 * 3600, 22 * 3600, a_uid.size)
    a_ts = np.where(a_day == 0, signup_sec[a_uid] + r_act.integers(60, 1800, a_uid.size),
                    a_mid + a_day * DAY + tod_a)

    ev_uid, ev_ts, ev_code = [], [], []

    def add(uids, ts, name):
        uids = np.asarray(uids)
        ts = np.asarray(ts, dtype=np.int64)
        keep = ts < end_sec
        ev_uid.append(uids[keep])
        ev_ts.append(ts[keep])
        ev_code.append(np.full(int(keep.sum()), EV[name], np.int8))

    add(a_uid, a_ts, "app_open")
    started = r_act.random(a_uid.size) < C.P_WORKOUT_STARTED
    s_ts = a_ts[started] + r_act.integers(60, 600, int(started.sum()))
    add(a_uid[started], s_ts, "workout_started")
    completed = r_act.random(int(started.sum())) < C.P_WORKOUT_COMPLETED
    add(a_uid[started][completed], s_ts[completed] + r_act.integers(1200, 3600, int(completed.sum())),
        "workout_completed")

    # signup
    all_u = np.arange(n)
    add(all_u, signup_sec, "signup_completed")

    # ------------------------------------------------------------------ Scenario 2: onboarding + tracking defect
    defect_sec = sec_of(C.DEFECT_START)
    is_android = platform == 0
    post_signup = day_off >= day_idx(C.DEFECT_START)
    p2 = np.where(post_signup, C.ONB_P_STEP2_POST, C.ONB_P_STEP2_PRE)
    s1 = r_onb.random(n) < C.ONB_P_STEP1
    s2 = s1 & (r_onb.random(n) < p2)
    s3 = s2 & (r_onb.random(n) < C.ONB_P_STEP3)
    comp = s3 & (r_onb.random(n) < C.ONB_P_COMPLETE)          # TRUE completion (ground truth)
    t_start = signup_sec + 20
    t1 = t_start + r_onb.integers(30, 300, n)
    t2 = t1 + r_onb.integers(30, 600, n)
    t3 = t2 + r_onb.integers(30, 600, n)
    late = r_onb.random(n) < C.ONB_LATE_COMPLETION_SHARE
    tc = t3 + np.where(late, r_onb.integers(8 * DAY, 14 * DAY, n), r_onb.integers(60, 2 * DAY, n))
    keep_comp_draw = r_onb.random(n)
    add(all_u, t_start, "onboarding_started")
    add(all_u[s1], t1[s1], "onboarding_step_1_completed")
    emit2 = s2 & ~(is_android & (t2 >= defect_sec))                           # DEF-ONB-001
    add(all_u[emit2], t2[emit2], "onboarding_step_2_completed")
    add(all_u[s3], t3[s3], "onboarding_step_3_completed")
    emitc = comp & ~(is_android & (tc >= defect_sec) & (keep_comp_draw >= C.DEFECT_ANDROID_COMPLETED_EVENT_KEEP))  # DEF-ONB-002
    add(all_u[emitc], tc[emitc], "onboarding_completed")

    # ------------------------------------------------------------------ Scenario 1 events
    ad_idx = np.where(adopter)[0]
    add(ad_idx, signup_sec[ad_idx] + (adopt_day[ad_idx] * DAY).astype(np.int64), "ai_coach_session")
    adopt_day_int = np.floor(adopt_day).astype(np.int64)
    m_ai = adopter[a_uid] & (a_day >= adopt_day_int[a_uid]) & (r_ai.random(a_uid.size) < C.P_AI_SESSION_PER_ACTIVE_DAY)
    add(a_uid[m_ai], a_ts[m_ai] + r_ai.integers(30, 240, int(m_ai.sum())), "ai_coach_session")

    # ------------------------------------------------------------------ Scenario 4 events
    jd_idx = np.where(joined)[0]
    add(jd_idx, signup_sec[jd_idx] + (join_day[jd_idx] * DAY).astype(np.int64), "challenge_joined")
    join_day_int = np.floor(join_day).astype(np.int64)
    m_ck = joined[a_uid] & (a_day >= join_day_int[a_uid]) & (r_com.random(a_uid.size) < C.P_CHECKIN_PER_ACTIVE_DAY)
    add(a_uid[m_ck], a_ts[m_ck] + r_com.integers(300, 900, int(m_ck.sum())), "challenge_checkin")

    # ------------------------------------------------------------------ Scenario 3: trials, conversion, experiment
    has_trial = r_price.random(n) < C.TRIAL_P
    trial_day = r_price.integers(0, C.TRIAL_START_DAY_MAX + 1, n)
    trial_sec = signup_sec + trial_day * DAY
    has_trial &= trial_sec < end_sec
    signup_date_idx = day_off
    country_code = np.array(C.COUNTRIES)[country]
    is_pilot_country = np.isin(country_code, C.PILOT_COUNTRIES)
    pilot = is_pilot_country & (signup_date_idx >= day_idx(C.PILOT_START))
    add(all_u[has_trial], trial_sec[has_trial] + 3600, "paywall_viewed")

    pe = C.PRICE_EXPERIMENT
    elig = has_trial & ~is_pilot_country & (signup_date_idx >= day_idx(pe["start"])) & (signup_date_idx <= day_idx(pe["end"]))
    elig_idx = np.where(elig)[0]
    n_pe = min(int(round(pe["sample_share_of_users"] * n)), elig_idx.size)
    pe_users = np.sort(r_exp.choice(elig_idx, n_pe, replace=False))
    perm = r_exp.permutation(n_pe)
    pe_treat = np.zeros(n, bool)
    pe_treat[pe_users[perm < n_pe // 2]] = True
    pe_in = np.zeros(n, bool)
    pe_in[pe_users] = True

    ca_p = pilot & (country_code == "CA")
    au_p = pilot & (country_code == "AU")
    p_conv = np.full(n, C.CONVERSION_BASE)
    p_conv = np.where(ca_p, p_conv * C.CONVERSION_MULT["CA_pilot"], p_conv)
    p_conv = np.where(au_p, p_conv * C.CONVERSION_MULT["AU_pilot"], p_conv)
    p_conv = np.where(pe_treat, p_conv * C.CONVERSION_MULT["exp_treatment"], p_conv)
    converted = has_trial & (r_price.random(n) < p_conv)
    price = np.where(pilot | pe_treat, C.PRICE_PILOT, C.PRICE_STANDARD)
    p_churn = np.full(n, C.MONTHLY_CHURN["standard"])
    p_churn = np.where(ca_p, C.MONTHLY_CHURN["CA_pilot"], p_churn)
    p_churn = np.where(au_p, C.MONTHLY_CHURN["AU_pilot"], p_churn)
    p_churn = np.where(pe_treat, C.MONTHLY_CHURN["exp_treatment"], p_churn)
    months = r_price.geometric(p_churn)

    trial_start_idx = day_off + trial_day
    ti = np.where(has_trial)[0]
    t_rows = pd.DataFrame({
        "user_idx": ti, "plan": "free_trial", "price_monthly": 0.0,
        "start_idx": trial_start_idx[ti], "end_idx": trial_start_idx[ti] + C.TRIAL_LENGTH_DAYS,
        "status": np.where(converted[ti], "trial_converted", "trial_expired"),
    })
    ci = np.where(converted)[0]
    prem_start = trial_start_idx[ci] + C.TRIAL_LENGTH_DAYS
    prem_end = prem_start + 30 * months[ci]
    cancelled = prem_end <= end_idx
    p_rows = pd.DataFrame({
        "user_idx": ci, "plan": "premium", "price_monthly": price[ci],
        "start_idx": prem_start, "end_idx": np.where(cancelled, prem_end, -1),
        "status": np.where(cancelled, "cancelled", "active"),
    })
    subs = pd.concat([t_rows, p_rows], ignore_index=True)
    subs = subs[subs["start_idx"] <= end_idx].sort_values(["start_idx", "user_idx", "plan"], kind="stable").reset_index(drop=True)

    def idx_to_date(a):
        base = np.datetime64(cfg.window_start, "D")
        out = pd.Series(base + a.astype("timedelta64[D]"))
        return out.dt.strftime("%Y-%m-%d").where(a >= 0, "")      # "" loads as NULL (open-ended)

    subscriptions = pd.DataFrame({
        "subscription_id": np.arange(1, len(subs) + 1),
        "user_id": subs["user_idx"].to_numpy() + 1,
        "plan": subs["plan"].to_numpy(),
        "price_monthly": subs["price_monthly"].round(2).to_numpy(),
        "start_date": idx_to_date(subs["start_idx"].to_numpy().astype(np.int64)).to_numpy(),
        "end_date": idx_to_date(subs["end_idx"].to_numpy().astype(np.int64)).to_numpy(),
        "status": subs["status"].to_numpy(),
        "is_synthetic": True,
    })

    # ------------------------------------------------------------------ Scenario 1 experiment (weak, imbalanced, short)
    ae = C.AI_EXPERIMENT
    s_i, e_i = day_idx(ae["start"]), day_idx(ae["end"])
    p0, p1 = day_idx(ae["prior_activity_window"][0]), day_idx(ae["prior_activity_window"][1])
    abs_day = day_off[a_uid] + a_day
    active_prior = np.zeros(n, bool)
    active_prior[a_uid[(abs_day >= p0) & (abs_day <= p1)]] = True
    ae_elig = np.where(active_prior & (day_off < s_i))[0]
    n_ae = min(int(round(ae["sample_share_of_users"] * n)), ae_elig.size)
    w = np.array(ae["tier_selection_weights"])[tier[ae_elig]]
    ae_users = np.sort(r_exp.choice(ae_elig, n_ae, replace=False, p=w / w.sum()))
    perm = r_exp.permutation(n_ae)
    n_treat = int(round(ae["treatment_share_actual"] * n_ae))
    ae_treat_mask = perm < n_treat
    ae_treat = ae_users[ae_treat_mask]
    ae_ctrl = ae_users[~ae_treat_mask]
    ws, we = T0 + s_i * DAY, T0 + (e_i + 1) * DAY
    k_w = r_exp.poisson(ae["extra_workouts_mean"], ae_treat.size)
    add(np.repeat(ae_treat, k_w), r_exp.integers(ws, we, int(k_w.sum())), "workout_completed")
    k_s = r_exp.poisson(ae["extra_sessions_mean"], ae_treat.size)
    add(np.repeat(ae_treat, k_s), r_exp.integers(ws, we, int(k_s.sum())), "ai_coach_session")
    contaminated = ae_ctrl[r_exp.random(ae_ctrl.size) < ae["control_contamination_share"]]
    k_c = r_exp.poisson(ae["contamination_sessions_mean"], contaminated.size) + 1
    add(np.repeat(contaminated, k_c), r_exp.integers(ws, we, int(k_c.sum())), "ai_coach_session")

    # ------------------------------------------------------------------ assemble events
    all_uid = np.concatenate(ev_uid)
    all_ts = np.concatenate(ev_ts)
    all_code = np.concatenate(ev_code)
    o = np.lexsort((all_code, all_uid, all_ts))
    all_uid, all_ts, all_code = all_uid[o], all_ts[o], all_code[o]

    # experiment outcome: completed workouts in the experiment window (derived from the event stream)
    in_w = (all_code == EV["workout_completed"]) & (all_ts >= ws) & (all_ts < we)
    workouts = np.bincount(all_uid[in_w], minlength=n)

    ev_day = (all_ts - T0) // DAY
    post = ev_day >= day_idx(C.DEFECT_START)
    plat_codes = platform[all_uid]
    pre_v = np.array([C.APP_VERSIONS_PRE[p] for p in C.PLATFORMS])
    post_v = np.array([C.APP_VERSIONS_POST[p] for p in C.PLATFORMS])
    app_version = np.where(post, post_v[plat_codes], pre_v[plat_codes])
    ts_str = pd.to_datetime(all_ts, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = pd.DataFrame({
        "event_id": np.arange(1, all_uid.size + 1),
        "user_id": all_uid + 1,
        "event_ts": ts_str,
        "event_name": np.array(EVENT_NAMES)[all_code],
        "platform": np.array(C.PLATFORMS)[plat_codes],
        "app_version": app_version,
        "is_synthetic": True,
    })

    users = pd.DataFrame({
        "user_id": np.arange(1, n + 1),
        "signup_ts": pd.to_datetime(signup_sec, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": np.array(C.PLATFORMS)[platform],
        "country": country_code,
        "acquisition_channel": np.array(C.CHANNELS)[channel],
        "engagement_style": np.array(C.STYLE_NAMES)[style],
        "prior_engagement_tier": np.array(C.TIER_NAMES)[tier_obs],
        "is_synthetic": True,
    })

    # ------------------------------------------------------------------ experiment tables
    asg = pd.concat([
        pd.DataFrame({"experiment_key": pe["key"], "user_id": pe_users + 1,
                      "variant": np.where(pe_treat[pe_users], "treatment_11_99", "control_9_99"),
                      "assigned_at": pd.to_datetime(trial_sec[pe_users] + 3600, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")}),
        pd.DataFrame({"experiment_key": ae["key"], "user_id": ae_users + 1,
                      "variant": np.where(ae_treat_mask, "ai_coach", "holdout"),
                      "assigned_at": pd.to_datetime(ws, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")}),
    ], ignore_index=True)
    asg["is_synthetic"] = True
    outc = pd.concat([
        pd.DataFrame({"experiment_key": pe["key"], "user_id": pe_users + 1, "metric_name": "converted_to_paid",
                      "value": converted[pe_users].astype(int)}),
        pd.DataFrame({"experiment_key": ae["key"], "user_id": ae_users + 1, "metric_name": "workouts_14d",
                      "value": workouts[ae_users]}),
    ], ignore_index=True)
    outc["is_synthetic"] = True

    # ------------------------------------------------------------------ AI inference costs
    ai_mask = all_code == EV["ai_coach_session"]
    cost = pd.DataFrame({"user_id": all_uid[ai_mask] + 1,
                         "cost_month": pd.to_datetime(all_ts[ai_mask], unit="s", utc=True).strftime("%Y-%m-01")})
    cost = cost.groupby(["user_id", "cost_month"], as_index=False).size().rename(columns={"size": "sessions"})
    cost["cost_usd"] = (cost["sessions"] * C.AI_COST_PER_SESSION_USD + C.AI_FIXED_COST_PER_ACTIVE_MONTH_USD).round(2)
    cost["is_synthetic"] = True

    # ------------------------------------------------------------------ pricing model inputs
    active_subs = int((subscriptions["plan"].eq("premium") & subscriptions["status"].eq("active")).sum())
    inputs = list(C.PRICING_INPUTS)
    inputs.insert(2, ("active_premium_subscribers", active_subs, "subscribers", False,
                      "Count of active premium subscriptions at window end (synthetic)"))
    pricing_inputs = pd.DataFrame(inputs, columns=["input_key", "value", "unit", "is_assumption", "source_note"])
    pricing_inputs["is_synthetic"] = True

    # ------------------------------------------------------------------ feedback
    fb_rows: list[tuple] = []   # (user_idx, created_sec, theme, source, scenario)

    def fb(uidx, created, themes, sources, scenario):
        for a, b, c, d in zip(uidx, created, themes, sources):
            fb_rows.append((int(a), int(min(b, end_sec - 1)), c, d, scenario))

    # AI Coach: positive-leaning customer feedback among adopters
    m_ai_fb = min(int(round(C.FEEDBACK_AI_ADOPTER_SHARE * ad_idx.size)), ad_idx.size)
    sel = np.sort(r_fb.choice(ad_idx, m_ai_fb, replace=False))
    th = r_fb.choice(["ai_coach_positive", "ai_coach_negative", "ai_coach_neutral"], sel.size, p=[0.72, 0.13, 0.15])
    src = r_fb.choice(["app_review", "survey"], sel.size, p=[0.6, 0.4])
    fb(sel, signup_sec[sel] + ((adopt_day[sel] + r_fb.uniform(3, 40, sel.size)) * DAY).astype(np.int64), th, src, "ai_coach")

    # Onboarding complaints (rate rises after the release date, both platforms, more on android)
    non_comp = ~comp
    p_cmp = np.where(post_signup, np.where(is_android, C.ONB_COMPLAINT_P_POST_ANDROID, C.ONB_COMPLAINT_P_POST),
                     C.ONB_COMPLAINT_P_PRE)
    sel = np.where(non_comp & (r_fb.random(n) < p_cmp))[0]
    src = r_fb.choice(["support_ticket", "app_review"], sel.size, p=[0.8, 0.2])
    fb(sel, signup_sec[sel] + r_fb.integers(3600, 3 * DAY, sel.size), ["onboarding_complaint"] * sel.size, src, "onboarding")

    # Pricing: price-sensitive feedback (heavier in the CA pilot), some value-positive feedback
    p_sens = np.where(ca_p, 0.13, np.where(au_p, 0.07, 0.05))
    r1 = r_fb.random(n)
    sel = np.where(has_trial & (r1 < p_sens))[0]
    src = r_fb.choice(["survey", "app_review"], sel.size, p=[0.7, 0.3])
    fb(sel, trial_sec[sel] + r_fb.integers(DAY, 13 * DAY, sel.size), ["pricing_sensitive"] * sel.size, src, "pricing")
    sel = np.where(has_trial & (r1 >= p_sens) & (r1 < p_sens + 0.04))[0]
    src = r_fb.choice(["survey", "app_review"], sel.size, p=[0.7, 0.3])
    fb(sel, trial_sec[sel] + r_fb.integers(DAY, 13 * DAY, sel.size), ["pricing_value"] * sel.size, src, "pricing")

    # Community feedback by engagement style
    for s_i2, p_fb, themes, probs in [
        (0, 0.15, ["community_positive", "community_neutral"], [0.9, 0.1]),
        (1, 0.05, ["community_neutral"], [1.0]),
        (2, 0.20, ["community_negative_notifications"], [1.0]),
    ]:
        sel = np.where(joined & (style == s_i2) & (r_fb.random(n) < p_fb))[0]
        th = r_fb.choice(themes, sel.size, p=probs)
        src = r_fb.choice(["app_review", "survey"], sel.size, p=[0.6, 0.4])
        fb(sel, signup_sec[sel] + ((join_day[sel] + r_fb.uniform(2, 30, sel.size)) * DAY).astype(np.int64), th, src, "community")

    # Generic baseline noise
    m_g = int(round(C.FEEDBACK_GENERIC_SHARE * n))
    sel = np.sort(r_fb.choice(n, m_g, replace=False))
    th = r_fb.choice(["generic_positive", "generic_negative", "generic_neutral"], sel.size, p=[0.5, 0.2, 0.3])
    src = r_fb.choice(["app_review", "survey"], sel.size, p=[0.7, 0.3])
    span = np.maximum(end_sec - signup_sec[sel] - 1, 1)
    fb(sel, signup_sec[sel] + (r_fb.random(sel.size) * span).astype(np.int64), th, src, "generic")

    fbdf = pd.DataFrame(fb_rows, columns=["user_idx", "created_sec", "theme", "source", "scenario"])
    fbdf = fbdf.sort_values(["created_sec", "user_idx", "theme"], kind="stable").reset_index(drop=True)
    texts, ratings = [], []
    for theme, source in zip(fbdf["theme"], fbdf["source"]):
        texts.append(render(theme, r_fb))
        ratings.append(rating_for(THEME_SENTIMENT[theme], source, r_fb))
    fbdf["feedback_id"] = np.arange(1, len(fbdf) + 1)
    feedback = pd.DataFrame({
        "feedback_id": fbdf["feedback_id"], "user_id": fbdf["user_idx"] + 1,
        "created_at": pd.to_datetime(fbdf["created_sec"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": fbdf["source"], "rating": pd.array(ratings, dtype="Int64"), "body": texts, "is_synthetic": True,
    })
    truth_fb = pd.DataFrame({
        "feedback_id": fbdf["feedback_id"], "scenario_key": fbdf["scenario"], "theme": fbdf["theme"],
        "sentiment": [THEME_SENTIMENT[t] for t in fbdf["theme"]], "is_synthetic": True,
    })

    # ------------------------------------------------------------------ ground-truth statistics for the manifest
    pre_mask = (day_off >= day_idx(dt.date(2026, 6, 1))) & (day_off < day_idx(C.DEFECT_START))
    meta = {
        "users": n,
        "events": int(all_uid.size),
        "true_onboarding_completion_pre": round(float(comp[pre_mask].mean()), 4),
        "true_onboarding_completion_post": round(float(comp[post_signup].mean()), 4),
        "ai_adopters": int(adopter.sum()),
        "ai_adopter_share_by_latent_tier": [round(float(adopter[tier == t].mean()), 4) for t in range(3)],
        "community_joiners": int(joined.sum()),
        "community_join_rate_by_style": [round(float(joined[style == s].mean()), 4) for s in range(3)],
        "pricing_experiment_n": int(n_pe),
        "pricing_experiment_per_arm_planned": int(round(pe["planned_per_arm_share_of_users"] * n)),
        "ai_experiment_n": int(n_ae),
        "ai_experiment_treatment_n": int(ae_treat.size),
        "ai_experiment_planned_total": int(round(ae["planned_share_of_users"] * n)),
    }
    tables = {
        "users": users, "events": events, "subscriptions": subscriptions, "feedback": feedback,
        "feedback_ground_truth": truth_fb, "experiment_assignments": asg, "experiment_outcomes": outc,
        "ai_inference_costs": cost, "pricing_model_inputs": pricing_inputs,
    }
    return tables, meta
