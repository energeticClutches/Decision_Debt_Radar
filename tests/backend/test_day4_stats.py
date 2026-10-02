"""Pure Day-4 statistics (no database): heterogeneity T-HET-3/4/5, experiment maths T-EXP-1/2/3, stance T-EVD-4,
grading T-EVD-7 and the DQ severity rules T-DQ-3."""

from __future__ import annotations

import itertools
import math

import pytest
from scipy import stats as sps

from app.analytics import dq as dq_mod
from app.analytics import stats as S
from app.analytics.dq import apply_impact_rule, severity_from_size
from app.core.params import get_analytics_params

PARAMS = get_analytics_params()
HET = dict(materiality=0.02, min_segment_n=500, alpha=0.05, min_eligible_segments=2)


def seg(name, nt, kt, nc, kc):
    return S.SegmentStat(name, nt, kt, nc, kc)


# ---------------------------------------------------------------- T-HET-3
def test_het_3_segments_below_min_segment_n_are_excluded_and_fewer_than_two_eligible_is_unknown():
    big_a = seg("a", 600, 360, 600, 300)
    big_b = seg("b", 600, 270, 600, 330)
    tiny_c = seg("c", 499, 400, 600, 100)                    # treatment arm one short of the minimum
    tiny_d = seg("d", 600, 400, 499, 100)                    # comparison arm one short
    boundary = seg("e", 500, 400, 500, 100)                  # exactly min_segment_n is eligible
    r = S.evaluate_heterogeneity([big_a, big_b, tiny_c, tiny_d], **HET)
    assert r.payload["segments_scanned"] == 4 and r.payload["segments_eligible"] == 2
    assert [s["segment"] for s in r.payload["segments"] if s["eligible"]] == ["a", "b"]
    assert not any(p["segment_a"] in ("c", "d") or p["segment_b"] in ("c", "d") for p in r.payload["pairs"])
    assert S.evaluate_heterogeneity([big_a, boundary], **HET).payload["segments_eligible"] == 2
    # fewer than 2 eligible segments: unknown (None), never False
    for segments in ([big_a, tiny_c, tiny_d], [big_a], [tiny_c, tiny_d], []):
        r = S.evaluate_heterogeneity(segments, **HET)
        assert r.flag is None and r.payload["flag"] is None
    # two eligible segments with no divergence: False (a known "no")
    assert S.evaluate_heterogeneity([seg("a", 600, 330, 600, 300), seg("b", 600, 331, 600, 300)], **HET).flag is False


# ---------------------------------------------------------------- T-HET-4
def test_het_4_bonferroni_a_pair_significant_at_alpha_but_not_at_alpha_over_m_does_not_trigger_rule_b():
    a = seg("A", 800, 480, 800, 400)                         # +0.100
    b = seg("B", 800, 428, 800, 408)                         # +0.025
    c = seg("C", 800, 428, 800, 408)                         # identical to B
    _, p_ab = S.pair_difference_test(a, b)
    assert 0.05 / 3 < p_ab < 0.05, p_ab                       # significant at alpha, not at alpha / 3
    assert abs(a.effect - b.effect) >= HET["materiality"]
    # m = 1 pair: alpha applies, rule B triggers
    two = S.evaluate_heterogeneity([a, b], **HET)
    assert two.payload["pairs_tested"] == 1 and two.payload["alpha_adjusted"] == pytest.approx(0.05)
    assert two.flag is True and two.payload["triggering_pairs"][0]["rule_b_difference_significant"] is True
    # m = 3 pairs: alpha / 3 applies, the same pair no longer triggers
    three = S.evaluate_heterogeneity([a, b, c], **HET)
    assert three.payload["pairs_tested"] == 3 and three.payload["alpha_adjusted"] == pytest.approx(0.05 / 3)
    assert three.payload["multiple_comparison_method"] == "bonferroni"
    assert three.flag is False and three.payload["triggering_pairs"] == []
    assert not any(p["rule_b_difference_significant"] for p in three.payload["pairs"])


# ---------------------------------------------------------------- T-HET-5
def test_het_5_rule_a_alone_opposite_signs_both_at_least_materiality():
    x, y = seg("x", 500, 275, 500, 250), seg("y", 500, 235, 500, 250)       # +0.05 and -0.03, not significant (p about 0.07)
    r = S.evaluate_heterogeneity([x, y], **HET)
    (row,) = r.payload["pairs"]
    assert row["rule_a_opposite_signs"] is True and row["rule_b_difference_significant"] is False
    assert r.flag is True


def test_het_5_rule_a_needs_both_effects_to_reach_materiality():
    x, y = seg("x", 500, 275, 500, 250), seg("y", 500, 255, 500, 250)       # +0.05 and +0.01 (same sign anyway)
    z = seg("z", 500, 245, 500, 250)                                         # -0.01: opposite sign but below materiality
    r = S.evaluate_heterogeneity([x, z], **HET)
    assert r.payload["pairs"][0]["rule_a_opposite_signs"] is False
    assert r.flag is False
    assert S.evaluate_heterogeneity([x, y], **HET).payload["pairs"][0]["rule_a_opposite_signs"] is False


def test_het_5_rule_b_alone_same_sign_large_significant_difference():
    p1, p2 = seg("p1", 3000, 2100, 3000, 1500), seg("p2", 3000, 1650, 3000, 1500)   # +0.20 and +0.05
    r = S.evaluate_heterogeneity([p1, p2], **HET)
    (row,) = r.payload["pairs"]
    assert row["rule_a_opposite_signs"] is False and row["rule_b_difference_significant"] is True and r.flag is True


def test_het_5_rule_b_needs_the_difference_to_reach_materiality():
    # significant but tiny: +0.200 vs +0.190 with huge n
    big_a, big_b = seg("a", 400000, 240000, 400000, 160000), seg("b", 400000, 236000, 400000, 160000)
    assert abs(big_a.effect - big_b.effect) < HET["materiality"]
    r = S.evaluate_heterogeneity([big_a, big_b], **HET)
    assert r.payload["pairs"][0]["p_value"] < 0.001 and r.flag is False


def test_het_5_neither_rule_gives_false_and_the_gap_to_the_aggregate_is_not_a_criterion():
    q1, q2 = seg("q1", 2000, 1100, 2000, 1000), seg("q2", 2000, 1090, 2000, 1000)
    assert S.evaluate_heterogeneity([q1, q2], **HET).flag is False
    # a confounded aggregate: every within-segment effect is the same (+0.10) but the groups are composed very differently
    s1, s2 = seg("s1", 5000, 4500, 500, 400), seg("s2", 500, 300, 5000, 2500)   # +0.10 each
    assert s1.effect == pytest.approx(0.10) and s2.effect == pytest.approx(0.10)
    r = S.evaluate_heterogeneity([s1, s2], **HET)
    assert r.flag is False                                                        # no heterogeneity, whatever the pooled number says


def test_het_5_payload_fields_and_pair_ordering_are_deterministic():
    a, b = seg("b", 800, 480, 800, 400), seg("a", 800, 428, 800, 408)
    r1, r2 = S.evaluate_heterogeneity([a, b], **HET), S.evaluate_heterogeneity([b, a], **HET)
    assert r1.payload == r2.payload and [s["segment"] for s in r1.payload["segments"]] == ["a", "b"]


# ---------------------------------------------------------------- T-EXP-1 (pure part)
def test_exp_1_effect_is_treatment_minus_control_on_the_natural_scale_with_a_ci_on_the_same_scale():
    d = S.two_proportion_difference(k_t=344, n_t=1000, k_c=365, n_c=1000)
    assert d.effect == pytest.approx(0.344 - 0.365)                       # a proportion difference, not a percentage
    se = math.sqrt(0.344 * 0.656 / 1000 + 0.365 * 0.635 / 1000)
    z = sps.norm.ppf(0.975)
    assert (d.ci_low, d.ci_high) == (pytest.approx(d.effect - z * se), pytest.approx(d.effect + z * se))
    assert d.ci_low < d.effect < d.ci_high
    # swapping the arms flips the sign and mirrors the interval
    r = S.two_proportion_difference(k_t=365, n_t=1000, k_c=344, n_c=1000)
    assert r.effect == pytest.approx(-d.effect) and r.ci_low == pytest.approx(-d.ci_high) and r.ci_high == pytest.approx(-d.ci_low)
    w = S.welch_difference(mean_t=2.0267, sd_t=1.5974, n_t=450, mean_c=1.7333, sd_c=1.5644, n_c=1050)
    assert w.effect == pytest.approx(2.0267 - 1.7333)                      # natural scale: workouts
    se_w = math.sqrt(1.5974 ** 2 / 450 + 1.5644 ** 2 / 1050)
    assert (w.ci_high - w.ci_low) / 2 == pytest.approx(sps.t.ppf(0.975, w.df) * se_w)
    assert w.method == "welch_t" and d.method == "two_proportion_z" and 0 < w.p_value < 0.01


# ---------------------------------------------------------------- T-EXP-2 (pure part)
def test_exp_2_srm_uses_the_planned_treatment_share():
    ai = S.srm_test({"holdout": 1050, "ai_coach": 450}, control="holdout", treatment="ai_coach", planned_treatment_share=0.5, alpha=0.001)
    assert ai.flag is True and ai.chi2 == pytest.approx(240.0) and ai.p_value < 1e-50
    assert ai.expected_counts == {"holdout": 750.0, "ai_coach": 750.0} and ai.planned_allocation == {"holdout": 0.5, "ai_coach": 0.5}
    assert ai.observed_allocation["ai_coach"] == pytest.approx(0.30)
    price = S.srm_test({"control_9_99": 587, "treatment_11_99": 587}, control="control_9_99", treatment="treatment_11_99",
                       planned_treatment_share=0.5, alpha=0.001)
    assert price.flag is False and price.chi2 == pytest.approx(0.0) and price.p_value == pytest.approx(1.0)
    # the planned share is what is tested against: the same 450/1050 split is fine when 30% was planned
    planned30 = S.srm_test({"holdout": 1050, "ai_coach": 450}, control="holdout", treatment="ai_coach", planned_treatment_share=0.3, alpha=0.001)
    assert planned30.flag is False and planned30.chi2 == pytest.approx(0.0)
    with pytest.raises(ValueError):
        S.srm_test({"a": 1, "b": 1}, control="a", treatment="b", planned_treatment_share=1.0, alpha=0.001)
    # the threshold is alpha: p just above / below it
    borderline = S.srm_test({"a": 5000, "b": 5200}, control="a", treatment="b", planned_treatment_share=0.5, alpha=0.001)
    assert borderline.flag == (borderline.p_value < 0.001)


# ---------------------------------------------------------------- T-EXP-3 (pure part)
def test_exp_3_design_power_depends_on_mde_and_n_not_on_the_observed_effect():
    kw = dict(n_control=587, n_treatment=587, p_control=0.365, alpha=0.05)
    base = S.design_power_binary(mde=0.02, **kw)
    assert 0.05 < base < 0.2                                               # well below 0.8 at this n and MDE
    assert S.design_power_binary(mde=0.02, **kw) == base                   # deterministic
    assert S.design_power_binary(mde=0.10, **kw) > base                    # a larger MDE is easier to detect
    assert S.design_power_binary(mde=0.02, **{**kw, "n_control": 5870, "n_treatment": 5870}) > base     # more users, more power
    assert S.design_power_binary(mde=None, **kw) is None and S.design_power_binary(mde=0, **kw) is None   # no MDE: None
    # allocation matters: the same total n split 30/70 has less power than 50/50
    even = S.design_power_binary(mde=0.05, n_control=500, n_treatment=500, p_control=0.3, alpha=0.05)
    skew = S.design_power_binary(mde=0.05, n_control=700, n_treatment=300, p_control=0.3, alpha=0.05)
    assert skew < even
    cont = S.design_power_continuous(mde=0.5, n_control=1050, n_treatment=450, pooled_sd_value=1.58, alpha=0.05)
    assert cont > 0.99
    assert S.design_power_continuous(mde=0.5, n_control=1050, n_treatment=450, pooled_sd_value=1.58, alpha=0.05) == cont
    assert S.design_power_continuous(mde=None, n_control=1050, n_treatment=450, pooled_sd_value=1.58, alpha=0.05) is None
    assert S.design_power_continuous(mde=0.5, n_control=1050, n_treatment=450, pooled_sd_value=3.16, alpha=0.05) < cont   # noisier outcome


def test_exp_3_the_power_function_has_no_effect_input():
    import inspect
    for fn in (S.design_power_binary, S.design_power_continuous):
        names = set(inspect.signature(fn).parameters)
        assert not {"effect", "observed_effect", "effect_size", "mean_t", "mean_treatment", "k_treatment", "p_treatment"} & names


# ---------------------------------------------------------------- T-EVD-4
def _stance(direction, effect, lo, hi, m=0.02):
    return S.stance_for(effect=effect, ci_low=lo, ci_high=hi, materiality=m, expected_direction=direction)


@pytest.mark.parametrize("effect,lo,hi,expected", [
    (0.05, 0.03, 0.07, "supports"),          # CI excludes 0, in direction, >= m
    (0.02, 0.005, 0.035, "supports"),        # exactly materiality counts
    (0.05, -0.01, 0.11, "neutral"),          # CI spans zero
    (0.015, 0.005, 0.025, "neutral"),        # CI excludes zero but below materiality
    (-0.05, -0.07, -0.03, "contradicts"),    # opposite direction, >= m
    (-0.015, -0.025, -0.005, "neutral"),     # opposite but below materiality
    (0.0, -0.01, 0.01, "neutral"),
])
def test_evd_4_stance_truth_table_increase(effect, lo, hi, expected):
    assert _stance("increase", effect, lo, hi) == expected


@pytest.mark.parametrize("effect,lo,hi,expected", [
    (-0.05, -0.07, -0.03, "supports"), (-0.02, -0.035, -0.005, "supports"), (-0.05, -0.11, 0.01, "neutral"),
    (-0.015, -0.025, -0.005, "neutral"), (0.05, 0.03, 0.07, "contradicts"), (0.015, 0.005, 0.025, "neutral"),
])
def test_evd_4_stance_truth_table_decrease(effect, lo, hi, expected):
    assert _stance("decrease", effect, lo, hi) == expected


@pytest.mark.parametrize("effect,lo,hi,expected", [
    (0.0, -0.01, 0.01, "supports"),          # lower bound above -m: no material decrease
    (0.03, 0.01, 0.05, "supports"),          # an increase also satisfies non-inferiority
    (-0.005, -0.019, 0.009, "supports"),     # lower bound -0.019 > -0.02
    (-0.0204, -0.0752, 0.0343, "neutral"),   # the seeded Pricing experiment: spans -m, inconclusive
    (-0.02, -0.04, 0.0, "neutral"),          # lower bound below -m, upper bound not below -m
    (-0.112, -0.143, -0.081, "contradicts"), # the seeded CA cohort: upper bound below -m
    (-0.05, -0.08, -0.021, "contradicts"),
    (-0.05, -0.08, -0.02, "neutral"),        # upper bound exactly -m is not below it
])
def test_evd_4_stance_truth_table_no_material_decrease(effect, lo, hi, expected):
    assert _stance("no_material_decrease", effect, lo, hi) == expected


def test_evd_4_stance_edge_cases():
    assert S.stance_for(effect=None, ci_low=None, ci_high=None, materiality=0.02, expected_direction="increase") == "neutral"
    assert S.stance_for(effect=0.1, ci_low=0.05, ci_high=0.15, materiality=None, expected_direction="increase") == "neutral"
    with pytest.raises(ValueError):
        S.stance_for(effect=0.1, ci_low=0.05, ci_high=0.15, materiality=0.02, expected_direction="sideways")
    # the three directions are exhaustive in the parameters
    assert tuple(PARAMS["stance"]["expected_directions"]) == ("increase", "decrease", "no_material_decrease")


# ---------------------------------------------------------------- T-EVD-7
G = PARAMS.grading


def grade(**kw):
    base = dict(grading=G, item_dq="pass", n=5000)
    base.update(kw)
    return S.strength_grade(**base)


def test_evd_7_grading_truth_table():
    exp_ok = dict(is_experiment=True, design="rct", srm_flag=False, design_power=0.85, ci_width=0.03, mde=0.02)
    # D: critical DQ, or n < 100 (first match wins over everything else)
    assert grade(item_dq="critical") == "D" and grade(n=99) == "D" and grade(n=100) != "D"
    assert grade(item_dq="critical", **exp_ok) == "D" and grade(n=50, **exp_ok) == "D"
    assert grade(item_dq="critical", n=50) == "D"
    # C: DQ warn, SRM failed, design power < 0.5, n < 1000
    assert grade(item_dq="warn") == "C" and grade(n=999) == "C" and grade(n=1000) == "B"
    assert grade(**{**exp_ok, "srm_flag": True}) == "C"
    assert grade(**{**exp_ok, "design_power": 0.49}) == "C" and grade(**{**exp_ok, "design_power": 0.5}) != "C"
    assert grade(item_dq="warn", **exp_ok) == "C"
    # A: RCT or holdout, SRM passed, design power >= 0.8, CI width <= 2 x MDE
    assert grade(**exp_ok) == "A"
    assert grade(**{**exp_ok, "design": "holdout"}) == "A"
    assert grade(**{**exp_ok, "design": "pre_post"}) == "B" and grade(**{**exp_ok, "design": "other"}) == "B"
    assert grade(**{**exp_ok, "design_power": 0.79}) == "B"
    assert grade(**{**exp_ok, "ci_width": 0.0401}) == "B" and grade(**{**exp_ok, "ci_width": 0.04}) == "A"
    assert grade(**{**exp_ok, "srm_flag": None}) == "B"                      # an unknown SRM can never earn an A
    assert grade(**{**exp_ok, "design_power": None}) == "B" and grade(**{**exp_ok, "mde": None}) == "B"
    assert grade(**{k: v for k, v in exp_ok.items() if k != "is_experiment"}) == "B"      # a non-experiment is never an A
    # B: everything else
    assert grade() == "B" and grade(item_dq="pass", n=None) == "B"
    # the seeded outcomes the brief names: AI Coach holdout (SRM failed) is C, the underpowered Pricing test is C
    assert grade(n=1500, is_experiment=True, design="holdout", srm_flag=True, design_power=0.9998, ci_width=0.35, mde=0.5) == "C"
    assert grade(n=1174, is_experiment=True, design="rct", srm_flag=False, design_power=0.109, ci_width=0.109, mde=0.02) == "C"


def test_evd_7_grading_is_a_function_only_of_its_inputs_over_the_full_grid():
    seen = set()
    for dq, n, srm, power in itertools.product(("pass", "warn", "critical"), (50, 500, 1500), (None, True, False), (None, 0.3, 0.9)):
        g1 = grade(item_dq=dq, n=n, is_experiment=True, design="rct", srm_flag=srm, design_power=power, ci_width=0.01, mde=0.02)
        assert g1 == grade(item_dq=dq, n=n, is_experiment=True, design="rct", srm_flag=srm, design_power=power, ci_width=0.01, mde=0.02)
        seen.add(g1)
    assert seen == {"A", "B", "C", "D"}


# ---------------------------------------------------------------- T-DQ-3
RULE = PARAMS["severity_rule"]


def test_dq_3_impact_rule_a_critical_size_on_a_non_lineage_target_becomes_warn():
    vol = PARAMS.dq["volume"]
    size = vol["critical_pct_drop"]                                      # exactly at the critical threshold
    assert severity_from_size(size, vol["warn_pct_drop"], vol["critical_pct_drop"]) == "critical"
    assert apply_impact_rule("critical", True, RULE) == "critical"        # in the success metric's lineage
    assert apply_impact_rule("critical", False, RULE) == "warn"           # not in the lineage: capped
    assert apply_impact_rule("warn", False, RULE) == "warn" and apply_impact_rule("pass", False, RULE) == "pass"


def test_dq_3_thresholds_for_every_check_type():
    for check, warn_key, crit_key in (("volume", "warn_pct_drop", "critical_pct_drop"), ("sequence", "warn_rate", "critical_rate"),
                                      ("completeness", "warn_null_rate", "critical_null_rate"), ("duplicates", "warn_rate", "critical_rate"),
                                      ("referential", "warn_rate", "critical_rate")):
        warn, crit = PARAMS.dq[check][warn_key], PARAMS.dq[check][crit_key]
        assert severity_from_size(crit, warn, crit) == "critical"
        assert severity_from_size(crit * 1.0001, warn, crit) == "critical"
        if warn < crit:
            assert severity_from_size(max(warn, 1e-12), warn, crit) == "warn"
            assert severity_from_size(crit * 0.999, warn, crit) in ("warn", "pass")
        assert severity_from_size(0, warn, crit) == "pass" and severity_from_size(None, warn, crit) == "pass"
        assert severity_from_size(-0.5, warn, crit) == "pass"                # a rise in volume is not a defect
    # referential warn_rate 0.0: any orphan is a warning, 0.1% or more is critical
    ref = PARAMS.dq["referential"]
    assert severity_from_size(1e-9, ref["warn_rate"], ref["critical_rate"]) == "warn"
    assert severity_from_size(0.001, ref["warn_rate"], ref["critical_rate"]) == "critical"


def test_dq_3_the_finding_text_and_threshold_record_the_cap():
    f = dq_mod._finding(check_type="volume", view="fc_.v_events", ref="r", target="x@android", in_lineage=False, size=1.0, warn=0.25,
                        critical=0.5, params=PARAMS, text="x on android fell 100%.", snapshot="s")
    assert (f.raw_severity, f.severity, f.threshold) == ("critical", "warn", 0.5)
    assert "capped at warn" in f.finding
    g = dq_mod._finding(check_type="volume", view="fc_.v_events", ref="r", target="y@android", in_lineage=True, size=0.62, warn=0.25,
                        critical=0.5, params=PARAMS, text="y.", snapshot="s")
    assert (g.raw_severity, g.severity) == ("critical", "critical") and "capped" not in g.finding


def test_dq_volume_rule_needs_a_sustained_drop_and_a_baseline():
    from datetime import date, timedelta
    windows = dq_mod.compute_windows(date(2026, 8, 31), date(2026, 10, 1), PARAMS)
    days = [windows.window_start.date() + timedelta(days=i) for i in range(56)]
    signups = {d: 100 for d in days}
    steady = {d: 50 for d in days}
    drop, _, _ = dq_mod.evaluate_volume(event="e", platform="p", daily_events=steady, daily_signups=signups, windows=windows, params=PARAMS)
    assert drop == pytest.approx(0.0)
    sustained = {d: (10 if d >= windows.recent_start.date() else 50) for d in days}
    drop, _, details = dq_mod.evaluate_volume(event="e", platform="p", daily_events=sustained, daily_signups=signups, windows=windows, params=PARAMS)
    assert drop == pytest.approx(0.8) and details["recent_days_below_warn_level"] == 14
    # a drop (35.7% on average) driven by only 5 of the 14 recent days is not sustained (min_sustained_days = 7): not reported
    blip = {d: (0 if windows.recent_start.date() <= d < windows.recent_start.date() + timedelta(days=5) else 50) for d in days}
    drop, text, _ = dq_mod.evaluate_volume(event="e", platform="p", daily_events=blip, daily_signups=signups, windows=windows, params=PARAMS)
    assert drop is None and "not reported as a defect" in text
    # no baseline events: cannot be assessed
    none_drop, text, _ = dq_mod.evaluate_volume(event="e", platform="p", daily_events={}, daily_signups=signups, windows=windows, params=PARAMS)
    assert none_drop is None and "no baseline" in text
    # windows: the baseline is the oldest 28 days, the recent window the newest 14, anchored on the last signup day
    assert windows.anchor == date(2026, 8, 31) and windows.window_end.date() == date(2026, 9, 1)
    assert (windows.baseline_start.date(), windows.baseline_end.date()) == (date(2026, 7, 7), date(2026, 8, 4))
    assert (windows.recent_start.date(), windows.recent_end.date()) == (date(2026, 8, 18), date(2026, 9, 1))
