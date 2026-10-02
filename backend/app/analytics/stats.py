"""Pure statistics for the Day-4 analytics (no I/O, no clock, no randomness). docs/day-4-implementation-brief.md
sections 6, 7 and 8.

  * two-proportion difference (Wald confidence interval, pooled z test) and Welch's t for continuous outcomes
  * sample-ratio mismatch (chi-square goodness of fit against the planned allocation)
  * DESIGN power at the pre-registered MDE with the achieved n and allocation. It is a property of the design
    (MDE, n, allocation and the control baseline / pooled spread). It is NOT "observed power" and does not depend on the
    observed effect
  * heterogeneity across segments (rule A: opposite signs, rule B: Bonferroni-corrected two-proportion z test)
  * the stance rule and the A-D strength grade
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from scipy import stats as sps
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import proportion_effectsize

DESIGN_POWER_LABEL = "design power at the pre-registered MDE"


# ---------------------------------------------------------------- differences
@dataclass(frozen=True)
class Difference:
    effect: float                      # treatment - comparison, on the natural scale of the outcome
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    statistic: float
    method: str
    confidence_level: float
    df: float | None = None


def two_proportion_difference(k_t: int, n_t: int, k_c: int, n_c: int, confidence: float = 0.95) -> Difference:
    """effect = p_t - p_c. Wald CI with the unpooled standard error, p value from the pooled two-proportion z test."""
    if n_t <= 0 or n_c <= 0:
        raise ValueError("both groups need at least one observation")
    p_t, p_c = k_t / n_t, k_c / n_c
    effect = p_t - p_c
    se = math.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
    z_crit = float(sps.norm.ppf(1 - (1 - confidence) / 2))
    pooled = (k_t + k_c) / (n_t + n_c)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n_t + 1 / n_c))
    if se_pooled == 0:
        z, p = 0.0, 1.0
    else:
        z = effect / se_pooled
        p = float(2 * sps.norm.sf(abs(z)))
    return Difference(effect=effect, se=se, ci_low=effect - z_crit * se, ci_high=effect + z_crit * se, p_value=p,
                      statistic=z, method="two_proportion_z", confidence_level=confidence)


def welch_difference(mean_t: float, sd_t: float, n_t: int, mean_c: float, sd_c: float, n_c: int,
                     confidence: float = 0.95) -> Difference:
    """effect = mean_t - mean_c. Welch's t test and interval (Welch-Satterthwaite degrees of freedom)."""
    if n_t < 2 or n_c < 2:
        raise ValueError("Welch's t needs at least two observations per group")
    v_t, v_c = sd_t ** 2 / n_t, sd_c ** 2 / n_c
    se = math.sqrt(v_t + v_c)
    effect = mean_t - mean_c
    if se == 0:
        return Difference(effect, 0.0, effect, effect, 1.0 if effect == 0 else 0.0, 0.0, "welch_t", confidence, float(n_t + n_c - 2))
    df = (v_t + v_c) ** 2 / (v_t ** 2 / (n_t - 1) + v_c ** 2 / (n_c - 1))
    t_crit = float(sps.t.ppf(1 - (1 - confidence) / 2, df))
    t = effect / se
    return Difference(effect=effect, se=se, ci_low=effect - t_crit * se, ci_high=effect + t_crit * se,
                      p_value=float(2 * sps.t.sf(abs(t), df)), statistic=t, method="welch_t", confidence_level=confidence, df=df)


# ---------------------------------------------------------------- sample-ratio mismatch
@dataclass(frozen=True)
class SrmResult:
    planned_treatment_share: float
    planned_allocation: dict[str, float]
    observed_allocation: dict[str, float]
    expected_counts: dict[str, float]
    observed_counts: dict[str, int]
    chi2: float
    p_value: float
    alpha: float
    flag: bool                         # True = sample-ratio mismatch detected (p < alpha)


def srm_test(observed: Mapping[str, int], *, control: str, treatment: str, planned_treatment_share: float,
             alpha: float) -> SrmResult:
    """Chi-square goodness of fit of the observed per-arm counts against the planned allocation."""
    if not 0 < planned_treatment_share < 1:
        raise ValueError("planned_treatment_share must be strictly between 0 and 1")
    n_c, n_t = int(observed[control]), int(observed[treatment])
    total = n_c + n_t
    expected = {control: total * (1 - planned_treatment_share), treatment: total * planned_treatment_share}
    chi2, p = sps.chisquare([n_c, n_t], [expected[control], expected[treatment]])
    return SrmResult(
        planned_treatment_share=planned_treatment_share,
        planned_allocation={control: 1 - planned_treatment_share, treatment: planned_treatment_share},
        observed_allocation={control: n_c / total, treatment: n_t / total}, expected_counts=expected,
        observed_counts={control: n_c, treatment: n_t}, chi2=float(chi2), p_value=float(p), alpha=alpha, flag=bool(p < alpha))


# ---------------------------------------------------------------- design power
def design_power_binary(*, mde: float | None, n_control: int, n_treatment: int, p_control: float, alpha: float,
                        alternative: str = "two-sided") -> float | None:
    """Power to detect `mde` (absolute difference in proportions) over the control baseline `p_control`, with the achieved
    group sizes (Cohen's h, NormalIndPower). Independent of the observed treatment effect. None without an MDE."""
    if mde is None or mde <= 0 or n_control < 2 or n_treatment < 2 or not 0 < p_control < 1:
        return None
    p_alt = min(p_control + mde, 1 - 1e-9)
    h = float(proportion_effectsize(p_alt, p_control))
    return float(NormalIndPower().power(effect_size=h, nobs1=n_control, alpha=alpha, ratio=n_treatment / n_control,
                                        alternative=alternative))


def pooled_sd(sd_control: float, n_control: int, sd_treatment: float, n_treatment: int) -> float:
    return math.sqrt(((n_control - 1) * sd_control ** 2 + (n_treatment - 1) * sd_treatment ** 2) / (n_control + n_treatment - 2))


def design_power_continuous(*, mde: float | None, n_control: int, n_treatment: int, pooled_sd_value: float, alpha: float,
                            alternative: str = "two-sided") -> float | None:
    """Power to detect `mde` with d = mde / pooled SD (TTestIndPower) at the achieved group sizes. None without an MDE."""
    if mde is None or mde <= 0 or n_control < 2 or n_treatment < 2 or pooled_sd_value <= 0:
        return None
    d = mde / pooled_sd_value
    return float(TTestIndPower().power(effect_size=d, nobs1=n_control, alpha=alpha, ratio=n_treatment / n_control,
                                       alternative=alternative))


# ---------------------------------------------------------------- heterogeneity (aggregate masking)
@dataclass(frozen=True)
class SegmentStat:
    segment: str
    n_treatment: int
    k_treatment: int
    n_comparison: int
    k_comparison: int

    @property
    def effect(self) -> float | None:
        if self.n_treatment <= 0 or self.n_comparison <= 0:
            return None
        return self.k_treatment / self.n_treatment - self.k_comparison / self.n_comparison

    @property
    def variance(self) -> float:
        p_t, p_c = self.k_treatment / self.n_treatment, self.k_comparison / self.n_comparison
        return p_t * (1 - p_t) / self.n_treatment + p_c * (1 - p_c) / self.n_comparison

    def eligible(self, min_n: int) -> bool:
        return self.n_treatment >= min_n and self.n_comparison >= min_n


@dataclass(frozen=True)
class HeterogeneityResult:
    flag: bool | None
    payload: dict = field(default_factory=dict)


def pair_difference_test(a: SegmentStat, b: SegmentStat) -> tuple[float, float]:
    """Two-proportion z test of the difference between two segments' effects. Returns (z, two-sided p)."""
    var = a.variance + b.variance
    diff = a.effect - b.effect
    if var <= 0:
        return (0.0, 1.0) if diff == 0 else (math.inf, 0.0)
    z = diff / math.sqrt(var)
    return z, float(2 * sps.norm.sf(abs(z)))


def evaluate_heterogeneity(segments: Sequence[SegmentStat], *, materiality: float, min_segment_n: int,
                           alpha: float, min_eligible_segments: int) -> HeterogeneityResult:
    """Flag = True if any pair of eligible segments meets rule A (opposite signs, both |effect| >= materiality) or rule B
    (|effect_A - effect_B| >= materiality and p < alpha / m, Bonferroni over the m eligible pairs).
    None when fewer than `min_eligible_segments` segments are eligible (unknown, not False). Only within-segment effects
    are compared: the aggregate-versus-segment gap is deliberately NOT a criterion (that is confounding)."""
    ordered = sorted(segments, key=lambda s: s.segment)
    eligible = [s for s in ordered if s.eligible(min_segment_n)]
    pairs = list(combinations(eligible, 2))
    m = len(pairs)
    adjusted = alpha / m if m else alpha
    triggers: list[dict] = []
    pair_rows: list[dict] = []
    for a, b in pairs:
        ea, eb = a.effect, b.effect
        rule_a = (ea * eb < 0) and abs(ea) >= materiality and abs(eb) >= materiality
        z, p = pair_difference_test(a, b)
        rule_b = abs(ea - eb) >= materiality and p < adjusted
        row = {"segment_a": a.segment, "segment_b": b.segment, "effect_a": ea, "effect_b": eb,
               "difference": ea - eb, "z": None if math.isinf(z) else z, "p_value": p,
               "rule_a_opposite_signs": bool(rule_a), "rule_b_difference_significant": bool(rule_b)}
        pair_rows.append(row)
        if rule_a or rule_b:
            triggers.append(row)
    if len(eligible) < min_eligible_segments:
        flag: bool | None = None
    else:
        flag = bool(triggers)
    payload = {
        "segments_scanned": len(ordered), "segments_eligible": len(eligible), "min_segment_n": min_segment_n,
        "materiality_threshold": materiality, "multiple_comparison_method": "bonferroni", "alpha": alpha,
        "pairs_tested": m, "alpha_adjusted": adjusted,
        "segments": [{"segment": s.segment, "effect": s.effect, "n_treatment": s.n_treatment,
                      "k_treatment": s.k_treatment, "n_comparison": s.n_comparison, "k_comparison": s.k_comparison,
                      "eligible": s.eligible(min_segment_n)} for s in ordered],
        "pairs": pair_rows, "triggering_pairs": triggers, "flag": flag,
    }
    return HeterogeneityResult(flag=flag, payload=payload)


# ---------------------------------------------------------------- stance (D4-21, O1)
def stance_for(*, effect: float | None, ci_low: float | None, ci_high: float | None, materiality: float | None,
               expected_direction: str) -> str:
    """supports | contradicts | neutral for a comparative analysis.

    increase / decrease: supports if the CI excludes 0, the effect is in the expected direction and |effect| >= materiality;
    contradicts if the CI excludes 0, the effect is opposite and |effect| >= materiality; neutral otherwise.
    no_material_decrease (non-inferiority): supports if the CI lower bound is above -materiality, contradicts if the CI upper
    bound is below -materiality, neutral otherwise. Without the numbers or a materiality the stance is neutral."""
    if effect is None or ci_low is None or ci_high is None or materiality is None:
        return "neutral"
    if expected_direction == "no_material_decrease":
        if ci_low > -materiality:
            return "supports"
        if ci_high < -materiality:
            return "contradicts"
        return "neutral"
    if expected_direction not in ("increase", "decrease"):
        raise ValueError(f"unknown expected direction {expected_direction!r}")
    excludes_zero = ci_low > 0 or ci_high < 0
    if not excludes_zero or abs(effect) < materiality:
        return "neutral"
    in_direction = effect > 0 if expected_direction == "increase" else effect < 0
    return "supports" if in_direction else "contradicts"


# ---------------------------------------------------------------- strength grade (DDI-spec section 4, first match wins)
def strength_grade(*, grading: Mapping, item_dq: str, n: int | None, is_experiment: bool = False, design: str | None = None,
                   srm_flag: bool | None = None, design_power: float | None = None, ci_width: float | None = None,
                   mde: float | None = None) -> str:
    """Deterministic A-D grade. D: item DQ critical or n < 100. C: DQ warn, or SRM failed, or design power < 0.5, or
    n < 1000. A: an RCT or holdout experiment, SRM passed, design power >= 0.8 and CI width <= 2 x MDE. B: everything else.
    SRM, power and the experiment criteria apply only where they exist (an unknown SRM never counts as failed or passed)."""
    d, c, a = grading["D"], grading["C"], grading["A"]
    if item_dq == d["item_dq"] or (n is not None and n < d["n_below"]):
        return "D"
    if (item_dq == c["item_dq"] or (c["srm_failed"] and srm_flag is True)
            or (design_power is not None and design_power < c["design_power_below"])
            or (n is not None and n < c["n_below"])):
        return "C"
    if (is_experiment and design in a["designs"] and srm_flag is False and design_power is not None
            and design_power >= a["design_power_at_least"] and ci_width is not None and mde is not None and mde > 0
            and ci_width <= a["ci_width_at_most_mde_multiple"] * mde):
        return "A"
    return "B"
