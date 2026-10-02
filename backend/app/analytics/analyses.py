"""The deterministic quantitative analyses of Day 4 (docs/day-4-implementation-brief.md sections 4, 6, 7, 8).

Each function reads data only through the read-only executor (catalogue SQL) and returns an AnalysisDraft: the type, the
parameters that define the analysis (hashed into its identity), the executed query, the result and the rows it consumed (hashed
into the source fingerprint). Storing a draft as an analysis_results row is app.analytics.store. Turning an analysis into an
evidence item is the evidence materialisation service. The analytics layer never writes evidence.

  comparison    treatment vs comparison group on the success metric (creates evidence: behavioral)
  segmentation  the same groups by the metric's single segment key, heterogeneity flag (creates NO evidence)
  trend         weekly series of the success metric (descriptive; creates evidence: behavioral, neutral)
  funnel        ordered steps of a configured funnel (descriptive; creates evidence: behavioral, neutral)
  experiment    experiment statistics (creates evidence: experiment)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.analytics import experiments as exp_mod
from app.analytics import queries as Q
from app.analytics import stats
from app.analytics.config import AnalyticsParams, TenantConfig
from app.analytics.dq import utc_midnight
from app.analytics.executor import ReadOnlyExecutor
from app.analytics.experiments import AnalyticsError, ExperimentSpec


@dataclass(frozen=True)
class DecisionInfo:
    """Plain facts about the decision that the analyses need."""
    decision_id: str
    scenario_key: str | None
    metric_name: str
    metric_id: str
    expected_direction: str
    experiment_keys: tuple[str, ...] = ()


@dataclass
class AnalysisDraft:
    analysis_type: str                 # comparison | segmentation | trend | funnel | experiment
    key: str                           # experiment id | segment key | cohort key | funnel name | 'weekly'
    metric_name: str | None
    metric_id: str | None
    source_views: list[str]
    identity_params: dict[str, Any]    # everything that defines the analysis (hashed into the analysis identity)
    query_text: str
    result: dict[str, Any]
    n: int | None
    rows: list[Any]                    # the aggregated rows the analysis consumed (fingerprinted)
    method_limitations: str = ""
    creates_evidence: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def _jsonable_rows(rows: Sequence[Mapping]) -> list[dict]:
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if hasattr(v, "as_tuple"):
                v = float(v)
            elif isinstance(v, date):
                v = v.isoformat()
            elif hasattr(v, "isoformat"):
                v = v.isoformat()
            row[k] = v
        out.append(row)
    return out


def cohort_end(metric: Mapping, as_of: date):
    """Cohorts that signed up at least maturity_days before the as-of date (so the outcome has had time to happen)."""
    return utc_midnight(as_of) - timedelta(days=int(metric["maturity_days"]))


def _base_identity(params: AnalyticsParams, tenant: TenantConfig, metric_name: str, *sections: str) -> dict[str, Any]:
    """The configuration an analysis depends on. Hashing it makes a parameter change a NEW analysis identity."""
    base: dict[str, Any] = {"analytics_params_version": params.version, "metric": {"name": metric_name, **dict(tenant.require_metric(metric_name))}}
    for s in sections:
        base[s] = dict(params[s])
    return base


# ---------------------------------------------------------------- group comparison + segmentation
def comparison_analyses(executor: ReadOnlyExecutor, params: AnalyticsParams, tenant: TenantConfig, info: DecisionInfo,
                        as_of: date) -> list[AnalysisDraft]:
    spec = tenant.decision_analyses(info.scenario_key)
    comp = spec.get("comparison")
    if not comp:
        return []
    metric = tenant.require_metric(info.metric_name)
    if metric["kind"] != "proportion":
        raise AnalyticsError(f"group comparison supports proportion metrics only ({info.metric_name} is {metric['kind']})")
    segment_key = tenant.segment_key(info.metric_name)
    if segment_key is None:
        raise AnalyticsError(f"metric {info.metric_name} has no configured segment key")
    template = Q.comparison_query(metric["outcome"], segment_key, comp, params.max_rows)
    qparams: dict[str, Any] = {**Q.outcome_params(metric["outcome"]), "cohort_end": cohort_end(metric, as_of)}
    if comp["type"] == "event_users":
        qparams["treatment_event"] = comp["treatment_event"]
        if comp.get("exclude_experiment_participants"):
            qparams["excluded_experiments"] = sorted(info.experiment_keys)
    else:
        qparams["split_ts"] = utc_midnight(date.fromisoformat(str(comp["split_date"])))
    pop = comp.get("population") or {}
    if pop:
        qparams["population_value"] = pop["value"]
    rows = executor.run(template, qparams)
    seg: dict[str, dict[str, Any]] = {}
    firsts, lasts = [], []
    for r in rows:
        s = seg.setdefault(str(r["segment"]), {"treatment": (0, 0), "comparison": (0, 0)})
        s[r["arm"]] = (int(r["n"]), int(r["k"]))
        firsts.append(r["first_signup"])
        lasts.append(r["last_signup"])
    totals = {arm: (sum(v[arm][0] for v in seg.values()), sum(v[arm][1] for v in seg.values())) for arm in ("treatment", "comparison")}
    if totals["treatment"][0] == 0 or totals["comparison"][0] == 0:
        raise AnalyticsError(f"comparison for {info.scenario_key}: an arm is empty (treatment n={totals['treatment'][0]}, "
                             f"comparison n={totals['comparison'][0]})")
    (n_t, k_t), (n_c, k_c) = totals["treatment"], totals["comparison"]
    diff = stats.two_proportion_difference(k_t, n_t, k_c, n_c, params["comparisons"]["confidence_level"])
    observed_start, observed_end = min(firsts).date(), max(lasts).date()
    cohort_key = f"{info.scenario_key}:{comp['type']}"
    source_views = sorted({metric["source_view"], *metric.get("lineage_views", []),
                           *(["fc_.v_experiment_assignments"] if comp.get("exclude_experiment_participants") else [])})
    qparams_json = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in qparams.items()}
    group_def = {"type": comp["type"], **{k: v for k, v in comp.items() if k != "type"}}
    comparison_result = {
        "metric": info.metric_name, "kind": "proportion", "treatment": {"n": n_t, "k": k_t, "rate": k_t / n_t},
        "comparison": {"n": n_c, "k": k_c, "rate": k_c / n_c}, "effect": diff.effect,
        "effect_scale": "difference in proportions (treatment minus comparison)", "ci_low": diff.ci_low, "ci_high": diff.ci_high,
        "ci_width": diff.ci_high - diff.ci_low, "confidence_level": diff.confidence_level, "p_value": diff.p_value,
        "method": diff.method, "standard_error": diff.se, "n": n_t + n_c, "group_definition": group_def,
        "observed_start": observed_start.isoformat(), "observed_end": observed_end.isoformat(),
        "materiality": metric["materiality"],
    }
    comparison_limits = ("Observational comparison of groups that were not randomised: it is not a causal estimate. "
                         "Group membership may be related to prior engagement (selection).")
    identity = _base_identity(params, tenant, info.metric_name, "comparisons")
    identity.update({"group_definition": group_def, "segment_key": segment_key, "cohort_end_rule": {"maturity_days": metric["maturity_days"]}})
    json_rows = _jsonable_rows(rows)
    drafts = [AnalysisDraft(
        analysis_type="comparison", key=cohort_key, metric_name=info.metric_name, metric_id=info.metric_id, source_views=source_views,
        identity_params=identity, query_text=template.sql, result=comparison_result, n=n_t + n_c, rows=json_rows,
        method_limitations=comparison_limits, creates_evidence=True,
        extra={"query_params": qparams_json, "query_name": template.name, "primary_view": metric["source_view"]})]

    # ---- segmentation by the metric's single segment key (feeds heterogeneity_flag only, creates no evidence)
    het = params.heterogeneity
    materiality = float(metric["materiality"])
    stat_rows = [stats.SegmentStat(segment=s, n_treatment=v["treatment"][0], k_treatment=v["treatment"][1],
                                   n_comparison=v["comparison"][0], k_comparison=v["comparison"][1])
                 for s, v in sorted(seg.items()) if v["treatment"][0] > 0 and v["comparison"][0] > 0]
    outcome = stats.evaluate_heterogeneity(stat_rows, materiality=materiality, min_segment_n=het["min_segment_n"], alpha=het["alpha"],
                                           min_eligible_segments=het["min_eligible_segments"])
    seg_result = {"segment_key": segment_key, "metric": info.metric_name, "terminology": "heterogeneity / aggregate masking",
                  "aggregate_effect": diff.effect, **outcome.payload}
    seg_identity = _base_identity(params, tenant, info.metric_name, "heterogeneity")
    seg_identity.update({"group_definition": group_def, "segment_key": segment_key})
    drafts.append(AnalysisDraft(
        analysis_type="segmentation", key=segment_key, metric_name=info.metric_name, metric_id=info.metric_id,
        source_views=source_views, identity_params=seg_identity, query_text=template.sql, result=seg_result, n=n_t + n_c, rows=json_rows,
        method_limitations=("Within-segment effects only: the aggregate-versus-segment gap is not a criterion (that is confounding). "
                            "Segments below the minimum size are excluded."),
        creates_evidence=False, extra={"query_params": qparams_json, "query_name": template.name, "flag": outcome.flag,
                                       "primary_view": metric["source_view"]}))
    return drafts


# ---------------------------------------------------------------- trend
def trend_analysis(executor: ReadOnlyExecutor, params: AnalyticsParams, tenant: TenantConfig, info: DecisionInfo,
                   as_of: date) -> AnalysisDraft | None:
    metric = tenant.metric(info.metric_name)
    if metric is None:
        return None
    if metric["kind"] != "proportion":
        raise AnalyticsError(f"trend supports proportion metrics only ({info.metric_name} is {metric['kind']})")
    tr = params["trend"]
    end = cohort_end(metric, as_of)
    start = end - timedelta(weeks=tr["lookback_weeks"])
    template = Q.trend_query(metric["outcome"], params.max_rows)
    qparams = {**Q.outcome_params(metric["outcome"]), "cohort_end": end, "trend_start": start}
    rows = executor.run(template, qparams)
    if not rows:
        raise AnalyticsError(f"trend for {info.metric_name}: no cohorts in the look-back window")
    last_signup = max(r["last_signup_date"] for r in rows)
    weeks = [r for r in rows if r["week_start"] >= start.date() and r["week_start"] + timedelta(days=6) <= last_signup]
    if len(weeks) < 2:
        raise AnalyticsError(f"trend for {info.metric_name}: fewer than two complete weeks")
    series = [{"week_start": r["week_start"].isoformat(), "n": int(r["n"]), "k": int(r["k"]), "value": int(r["k"]) / int(r["n"])} for r in weeks]
    recent = series[-tr["recent_weeks"]:]
    prior = series[:-tr["recent_weeks"]]
    pooled = lambda part: sum(p["k"] for p in part) / sum(p["n"] for p in part)  # noqa: E731
    result = {
        "metric": info.metric_name, "kind": "proportion", "period": "signup week (complete weeks only)", "weeks": series,
        "n": sum(p["n"] for p in series), "first_week": series[0]["week_start"], "last_week": series[-1]["week_start"],
        "recent_weeks": len(recent), "recent_value": pooled(recent),
        "prior_value": pooled(prior) if prior else None,
        "change_recent_vs_prior": (pooled(recent) - pooled(prior)) if prior else None,
        "descriptive_only": True, "observed_start": series[0]["week_start"],
        "observed_end": (date.fromisoformat(series[-1]["week_start"]) + timedelta(days=6)).isoformat(),
    }
    identity = _base_identity(params, tenant, info.metric_name, "trend")
    identity["cohort_end_rule"] = {"maturity_days": metric["maturity_days"]}
    return AnalysisDraft(
        analysis_type="trend", key="weekly", metric_name=info.metric_name, metric_id=info.metric_id,
        source_views=sorted({metric["source_view"], *metric.get("lineage_views", [])}), identity_params=identity,
        query_text=template.sql, result=result, n=result["n"], rows=_jsonable_rows(rows),
        method_limitations="Descriptive trend by signup week. No hypothesis test or causal claim; a change over time is not an explanation.",
        creates_evidence=True,
        extra={"query_params": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in qparams.items()}, "query_name": template.name,
               "primary_view": metric["source_view"]})


# ---------------------------------------------------------------- funnel
def funnel_analysis(executor: ReadOnlyExecutor, params: AnalyticsParams, tenant: TenantConfig, info: DecisionInfo,
                    as_of: date) -> AnalysisDraft | None:
    spec = tenant.decision_analyses(info.scenario_key)
    name = spec.get("funnel")
    if not name or tenant.metric(info.metric_name) is None:
        return None
    steps = tenant.funnel(name)
    anchor_rows = executor.run(Q.anchor_query(params.max_rows), {"as_of_ts": utc_midnight(as_of)})
    anchor = anchor_rows[0]["last_signup_date"] or (as_of - timedelta(days=1))
    end = utc_midnight(anchor + timedelta(days=1))
    start = end - timedelta(days=params["funnel"]["cohort_window_days"])
    cohort_rows = executor.run(Q.funnel_cohort_query(params.max_rows), {"window_start": start, "window_end": end})
    template = Q.funnel_steps_query(params.max_rows)
    step_rows = executor.run(template, {"window_start": start, "window_end": end, "steps": steps})
    cohort = {r["platform"]: int(r["users"]) for r in cohort_rows}
    reached: dict[str, dict[str, int]] = {p: {} for p in cohort}
    for r in step_rows:
        reached.setdefault(r["platform"], {})[r["event_name"]] = int(r["users"])
    platforms = sorted(cohort)

    def table(counts: dict[str, int], n: int) -> list[dict]:
        out, prev = [], None
        for step in steps:
            users = counts.get(step, 0)
            out.append({"step": step, "users": users, "share_of_cohort": users / n if n else None,
                        "share_of_previous_step": (users / prev) if prev else None})
            prev = users
        return out

    total = sum(cohort.values())
    overall = {s: sum(reached.get(p, {}).get(s, 0) for p in platforms) for s in steps}
    result = {
        "funnel": name, "steps": steps, "cohort_window": [start.date().isoformat(), end.date().isoformat()],
        "cohort_users": total, "overall": table(overall, total),
        "by_platform": {p: {"cohort_users": cohort[p], "steps": table(reached.get(p, {}), cohort[p])} for p in platforms},
        "n": total, "descriptive_only": True, "observed_start": start.date().isoformat(),
        "observed_end": (end - timedelta(days=1)).date().isoformat(),
    }
    identity = _base_identity(params, tenant, info.metric_name, "funnel")
    identity["funnel"] = {"name": name, "steps": steps}
    return AnalysisDraft(
        analysis_type="funnel", key=name, metric_name=info.metric_name, metric_id=info.metric_id,
        source_views=["fc_.v_events", "fc_.v_users"], identity_params=identity, query_text=template.sql, result=result, n=total,
        rows=_jsonable_rows(cohort_rows) + _jsonable_rows(step_rows),
        method_limitations=("Descriptive funnel over the signups of the window. Step counts depend on event tracking: a tracking "
                            "defect on a step appears as a drop that is not a change in user behaviour."),
        creates_evidence=True,
        extra={"query_params": {"window_start": start.isoformat(), "window_end": end.isoformat(), "steps": steps},
               "query_name": template.name, "primary_view": "fc_.v_events"})


# ---------------------------------------------------------------- experiment
def experiment_draft(executor: ReadOnlyExecutor, params: AnalyticsParams, tenant: TenantConfig, info: DecisionInfo,
                     spec: ExperimentSpec, *, design_rank: float | None) -> tuple[AnalysisDraft, exp_mod.ExperimentAnalysis]:
    analysis = exp_mod.analyze_experiment(executor, params, spec)
    result = analysis.result_payload(params, design_rank)
    result["observed_start"] = spec.start_date.isoformat()
    result["observed_end"] = (spec.end_date or spec.start_date).isoformat()
    metric_name = info.metric_name
    # Materiality: the experiment's primary metric if it has one (the decision's success metric here), else the configured
    # outcome (tenant experiment_outcomes). Without either the stance stays neutral.
    materiality = None
    if spec.primary_metric_id and spec.primary_metric_id == info.metric_id and tenant.metric(info.metric_name):
        materiality = tenant.metric(info.metric_name)["materiality"]
    else:
        cfg = tenant.experiment_outcome(spec.outcome_key)
        materiality = cfg["materiality"] if cfg else None
    result["materiality"] = materiality
    exp_params = params.experiments
    identity = {"analytics_params_version": params.version, "experiments": dict(exp_params), "grading": dict(params["grading"]),
                "experiment": {"source_ref": spec.source_ref, "design": spec.design, "control_variant": spec.control_variant,
                               "outcome_key": spec.outcome_key, "planned_treatment_share": spec.planned_treatment_share,
                               "mde": spec.mde, "materiality": materiality},
                "metric": metric_name}
    draft = AnalysisDraft(
        analysis_type="experiment", key=spec.id, metric_name=metric_name if spec.primary_metric_id else None,
        metric_id=spec.primary_metric_id, source_views=["fc_.v_experiment_assignments", "fc_.v_experiment_outcomes"],
        identity_params=identity,
        query_text=Q.experiment_outcomes_query(params.max_rows).sql, result=result, n=analysis.n, rows=analysis.rows,
        method_limitations=analysis.limitations, creates_evidence=True,
        extra={"query_params": {"experiment_key": spec.source_ref, "outcome_key": spec.outcome_key},
               "query_name": "experiment.outcomes", "experiment_id": spec.id, "primary_view": "fc_.v_experiment_assignments"})
    return draft, analysis

