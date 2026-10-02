"""Experiment statistics (docs/day-4-implementation-brief.md section 7, D4-11 to D4-15).

Experiments are found through experiments.decision_id. Raw data is read through source_ref (the experiment key),
control_variant and outcome_key from the allow-listed views, via the read-only executor.

  * effect = treatment - control on the natural scale of the outcome (D4-13); the CI uses the same scale
  * proportions: two-proportion test (Wald CI); continuous outcomes: Welch's t
  * SRM: chi-square goodness of fit of the per-arm counts against planned_treatment_share (flag when p < srm_alpha);
    with no planned share the flag is None and the DDI default applies. SRM is an integrity diagnostic, not an effect
  * design power at the experiment's MDE with the achieved n and allocation (labelled "design power at the pre-registered
    MDE", never "observed power"); None without an MDE, so the DDI reports the power as defaulted
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.analytics import queries as Q
from app.analytics import stats
from app.analytics.config import AnalyticsParams
from app.analytics.executor import ReadOnlyExecutor


class AnalyticsError(Exception):
    """An analysis cannot be run (unexpected data shape or missing configuration)."""


@dataclass(frozen=True)
class ExperimentSpec:
    """The columns of the experiments row that the analysis needs (plain data, no ORM object)."""
    id: str
    name: str
    design: str
    source_ref: str | None
    control_variant: str | None
    outcome_key: str | None
    planned_treatment_share: float | None
    mde: float | None
    planned_sample: int | None
    start_date: date
    end_date: date | None
    primary_metric_id: str | None


@dataclass(frozen=True)
class ExperimentAnalysis:
    spec: ExperimentSpec
    kind: str                                  # binary | continuous
    control: str
    treatment: str
    variants: dict[str, dict[str, float | int]]
    difference: stats.Difference
    srm: stats.SrmResult | None
    design_power: float | None
    design_power_baseline: dict[str, float]
    n: int
    limitations: str
    rows: list[dict]                           # the aggregated query rows the analysis read (for the source fingerprint)

    def result_payload(self, params: AnalyticsParams, design_rank: float | None) -> dict[str, Any]:
        exp_params = params.experiments
        d = self.difference
        payload: dict[str, Any] = {
            "experiment_id": self.spec.id, "experiment_name": self.spec.name, "source_ref": self.spec.source_ref,
            "outcome_key": self.spec.outcome_key, "outcome_kind": self.kind, "control_variant": self.control,
            "treatment_variant": self.treatment, "design": self.spec.design, "design_rank": design_rank,
            "variants": {k: dict(v) for k, v in self.variants.items()},
            "effect": d.effect, "effect_scale": "natural scale of the outcome (treatment minus control)",
            "ci_low": d.ci_low, "ci_high": d.ci_high, "ci_width": d.ci_high - d.ci_low, "confidence_level": d.confidence_level,
            "p_value": d.p_value, "statistic": d.statistic, "method": d.method, "standard_error": d.se,
            "mde": self.spec.mde, "planned_sample": self.spec.planned_sample, "n": self.n,
            "design_power": {"value": self.design_power, "label": stats.DESIGN_POWER_LABEL, "mde": self.spec.mde,
                             "alpha": exp_params["power_alpha"], "alternative": exp_params["power_alternative"],
                             "method": ("NormalIndPower + proportion_effectsize" if self.kind == "binary"
                                        else "TTestIndPower with d = mde / pooled SD"),
                             "baseline": self.design_power_baseline, "n_control": self.variants[self.control]["n"],
                             "n_treatment": self.variants[self.treatment]["n"]},
            "srm": None, "limitations": self.limitations,
        }
        if self.srm is not None:
            s = self.srm
            payload["srm"] = {"planned_treatment_share": s.planned_treatment_share, "planned_allocation": s.planned_allocation,
                              "observed_allocation": s.observed_allocation, "expected_counts": s.expected_counts,
                              "observed_counts": s.observed_counts, "chi2": s.chi2, "p_value": s.p_value, "alpha": s.alpha,
                              "flag": s.flag}
        return payload


def _limitations(spec: ExperimentSpec, kind: str, n_total: int, d: stats.Difference, srm: stats.SrmResult | None,
                 power: float | None, treatment: str) -> str:
    notes: list[str] = []
    if srm is None:
        notes.append("No planned treatment share is registered, so the sample-ratio check was not run.")
    elif srm.flag:
        notes.append(f"Sample-ratio mismatch: {srm.observed_allocation[treatment]:.0%} of users were allocated to {treatment} against "
                     f"{srm.planned_treatment_share:.0%} planned (chi-square {srm.chi2:.1f}, p {srm.p_value:.2g}). "
                     "Randomisation integrity is in doubt.")
    if spec.mde is None:
        notes.append("No pre-registered minimum detectable effect, so the design power was not computed.")
    elif power is not None and power < 0.8:
        notes.append(f"Design power at the pre-registered MDE ({spec.mde:g}) is {power:.2f}, below 0.8.")
    if spec.planned_sample:
        notes.append(f"Enrolled {n_total} users against a planned sample of {spec.planned_sample} ({n_total / spec.planned_sample:.0%}).")
    if d.ci_low <= 0 <= d.ci_high:
        notes.append("The confidence interval spans zero: the experiment is inconclusive about the direction of the effect.")
    return " ".join(notes)


def analyze_experiment(executor: ReadOnlyExecutor, params: AnalyticsParams, spec: ExperimentSpec) -> ExperimentAnalysis:
    if not spec.source_ref or not spec.outcome_key or not spec.control_variant:
        raise AnalyticsError(f"experiment {spec.name!r} is missing source_ref, outcome_key or control_variant")
    max_rows = params.max_rows
    exp_params = params.experiments
    assigned = {r["variant"]: int(r["n"]) for r in executor.run(Q.experiment_assignments_query(max_rows), {"experiment_key": spec.source_ref})}
    if spec.control_variant not in assigned or len(assigned) != 2:
        raise AnalyticsError(f"experiment {spec.name!r}: expected exactly two variants including control "
                             f"{spec.control_variant!r}, found {sorted(assigned)}")
    control = spec.control_variant
    treatment = next(v for v in assigned if v != control)
    out_rows = executor.run(Q.experiment_outcomes_query(max_rows), {"experiment_key": spec.source_ref, "outcome_key": spec.outcome_key})
    by_variant = {r["variant"]: r for r in out_rows}
    if control not in by_variant or treatment not in by_variant:
        raise AnalyticsError(f"experiment {spec.name!r}: outcome {spec.outcome_key!r} is missing for a variant")
    n_c, n_t = int(by_variant[control]["n"]), int(by_variant[treatment]["n"])
    mean_c, mean_t = float(by_variant[control]["mean"]), float(by_variant[treatment]["mean"])
    sd_c = float(by_variant[control]["sd"] or 0.0)
    sd_t = float(by_variant[treatment]["sd"] or 0.0)
    binary = int(by_variant[control]["non_binary"]) == 0 and int(by_variant[treatment]["non_binary"]) == 0
    confidence = exp_params["confidence_level"]
    alpha, alternative = exp_params["power_alpha"], exp_params["power_alternative"]
    if binary:
        kind = "binary"
        diff = stats.two_proportion_difference(round(mean_t * n_t), n_t, round(mean_c * n_c), n_c, confidence)
        power = stats.design_power_binary(mde=spec.mde, n_control=n_c, n_treatment=n_t, p_control=mean_c, alpha=alpha,
                                          alternative=alternative)
        baseline = {"control_rate": mean_c}
    else:
        kind = "continuous"
        diff = stats.welch_difference(mean_t, sd_t, n_t, mean_c, sd_c, n_c, confidence)
        pooled = stats.pooled_sd(sd_c, n_c, sd_t, n_t)
        power = stats.design_power_continuous(mde=spec.mde, n_control=n_c, n_treatment=n_t, pooled_sd_value=pooled, alpha=alpha,
                                              alternative=alternative)
        baseline = {"pooled_sd": pooled}
    srm = None
    if spec.planned_treatment_share is not None:
        srm = stats.srm_test(assigned, control=control, treatment=treatment, planned_treatment_share=spec.planned_treatment_share,
                             alpha=exp_params["srm_alpha"])
    variants = {control: {"n": n_c, "metric_value": mean_c, "sd": sd_c, "assigned": assigned[control]},
                treatment: {"n": n_t, "metric_value": mean_t, "sd": sd_t, "assigned": assigned[treatment]}}
    n_total = n_c + n_t
    return ExperimentAnalysis(
        spec=spec, kind=kind, control=control, treatment=treatment, variants=variants, difference=diff, srm=srm, design_power=power,
        design_power_baseline=baseline, n=n_total, limitations=_limitations(spec, kind, n_total, diff, srm, power, treatment),
        rows=[{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in r.items()} for r in out_rows]
             + [{"variant": v, "assigned": c} for v, c in sorted(assigned.items())])


def experiment_results_rows(analysis: ExperimentAnalysis) -> list[Mapping[str, Any]]:
    """The canonical experiment_results rows: one per variant. Effect, CI, p and the SRM flag are on the treatment row only."""
    d = analysis.difference
    rows: list[Mapping[str, Any]] = []
    for variant in (analysis.control, analysis.treatment):
        v = analysis.variants[variant]
        row: dict[str, Any] = {"variant": variant, "n": int(v["n"]), "metric_value": float(v["metric_value"]), "effect_size": None,
                               "ci_low": None, "ci_high": None, "p_value": None, "srm_flag": None,
                               "notes": f"{d.method}; outcome {analysis.spec.outcome_key}"}
        if variant == analysis.treatment:
            row.update(effect_size=d.effect, ci_low=d.ci_low, ci_high=d.ci_high, p_value=d.p_value,
                       srm_flag=analysis.srm.flag if analysis.srm is not None else None)
        rows.append(row)
    return rows
