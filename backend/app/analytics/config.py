"""Typed access to the two hashed analytics configuration files (docs/day-4-implementation-brief.md section 4).

  * analytics_params_v0.1.yaml    generic methods and thresholds (registered in backend/config/params_hashes.json)
  * orgs/<org>/analytics_config.yaml   tenant configuration: every organisation-specific value lives here only

Loading, hashing and ParamsError checks are in app.core.params. This module validates the parsed structure and
exposes small accessors, so analysis code never reads loose dictionaries or hard-codes a tenant value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.errors import ParamsError

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
METRIC_KINDS = ("proportion", "count")
OUTCOME_TYPES = ("event_after_days", "event_within_days", "subscription_status")
COMPARISON_TYPES = ("event_users", "cohort_split")
EXPECTED_DIRECTIONS = ("increase", "decrease", "no_material_decrease")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise ParamsError(message)


def _num(mapping: Mapping, key: str, where: str) -> float:
    v = mapping.get(key) if isinstance(mapping, Mapping) else None
    _need(isinstance(v, (int, float)) and not isinstance(v, bool), f"{where}.{key} must be a number")
    return float(v)


@dataclass(frozen=True)
class AnalyticsParams:
    version: str
    content_hash: str
    data: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], content_hash: str) -> AnalyticsParams:
        for section in ("sql", "dq", "severity_rule", "comparisons", "trend", "funnel", "heterogeneity", "experiments",
                        "grading", "stance"):
            _need(isinstance(raw.get(section), Mapping), f"analytics params: section '{section}' is missing")
        dq = raw["dq"]
        for key in ("window_days", "baseline_days", "recent_days", "min_sustained_days"):
            _need(isinstance(dq.get(key), int) and dq[key] > 0, f"analytics params: dq.{key} must be a positive integer")
        _need(dq["baseline_days"] + dq["recent_days"] <= dq["window_days"],
              "analytics params: baseline_days + recent_days must fit inside window_days")
        _need(dq["min_sustained_days"] <= dq["recent_days"], "analytics params: min_sustained_days exceeds recent_days")
        for check, warn_key, crit_key in (("volume", "warn_pct_drop", "critical_pct_drop"),
                                          ("sequence", "warn_rate", "critical_rate"),
                                          ("completeness", "warn_null_rate", "critical_null_rate"),
                                          ("duplicates", "warn_rate", "critical_rate"),
                                          ("referential", "warn_rate", "critical_rate")):
            block = dq.get(check)
            _need(isinstance(block, Mapping), f"analytics params: dq.{check} is missing")
            warn, crit = _num(block, warn_key, f"dq.{check}"), _num(block, crit_key, f"dq.{check}")
            _need(0 <= warn <= crit <= 1, f"analytics params: dq.{check} needs 0 <= warn <= critical <= 1")
        het = raw["heterogeneity"]
        _need(het.get("test") == "two_proportion_z" and het.get("correction") == "bonferroni",
              "analytics params: heterogeneity supports only two_proportion_z with bonferroni")
        _need(0 < _num(het, "alpha", "heterogeneity") < 1, "analytics params: heterogeneity.alpha must be in (0, 1)")
        _need(isinstance(het.get("min_segment_n"), int) and isinstance(het.get("min_eligible_segments"), int),
              "analytics params: heterogeneity.min_segment_n and min_eligible_segments must be integers")
        exp = raw["experiments"]
        _need(0 < _num(exp, "srm_alpha", "experiments") < 1 and 0 < _num(exp, "power_alpha", "experiments") < 1,
              "analytics params: experiments.srm_alpha and power_alpha must be in (0, 1)")
        _need(exp.get("power_alternative") in ("two-sided", "larger", "smaller"),
              "analytics params: experiments.power_alternative is invalid")
        _need(0 < _num(exp, "confidence_level", "experiments") < 1, "analytics params: experiments.confidence_level is invalid")
        _need(0 < _num(raw["comparisons"], "confidence_level", "comparisons") < 1,
              "analytics params: comparisons.confidence_level is invalid")
        _need(tuple(raw["stance"].get("expected_directions", ())) == EXPECTED_DIRECTIONS,
              f"analytics params: stance.expected_directions must be {EXPECTED_DIRECTIONS}")
        _need(list(raw["grading"].get("order", [])) == ["D", "C", "A", "B"], "analytics params: grading.order must be D, C, A, B")
        _need(isinstance(raw["sql"].get("max_rows"), int) and raw["sql"]["max_rows"] > 0, "analytics params: sql.max_rows is invalid")
        return cls(version=str(raw["version"]), content_hash=content_hash, data=raw)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @property
    def dq(self) -> Mapping[str, Any]:
        return self.data["dq"]

    @property
    def heterogeneity(self) -> Mapping[str, Any]:
        return self.data["heterogeneity"]

    @property
    def experiments(self) -> Mapping[str, Any]:
        return self.data["experiments"]

    @property
    def grading(self) -> Mapping[str, Any]:
        return self.data["grading"]

    @property
    def max_rows(self) -> int:
        return int(self.data["sql"]["max_rows"])

    @property
    def statement_timeout(self) -> str:
        return str(self.data["sql"].get("statement_timeout", "30s"))


@dataclass(frozen=True)
class TenantConfig:
    version: str
    org_key: str
    content_hash: str
    analytics_params_version: str
    data: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], content_hash: str) -> TenantConfig:
        for section in ("views", "metrics", "segment_keys", "funnels", "decision_analyses", "experiment_outcomes"):
            _need(isinstance(raw.get(section), Mapping), f"tenant config: section '{section}' is missing")
        _need(isinstance(raw.get("org_key"), str) and raw.get("analytics_params_version"), "tenant config: org_key / analytics_params_version missing")
        views = raw["views"]
        for name, spec in views.items():
            _need(re.fullmatch(r"fc_\.v_[a-z_]+", name) is not None, f"tenant config: view '{name}' is not an allow-listed fc_ view")
            _need(isinstance(spec.get("data_source_ref"), str), f"tenant config: view {name} needs data_source_ref")
            cols = list(spec.get("required_columns", []))
            for key in spec.get("key_columns", []):
                cols += list(key)
            for col in cols + [spec.get("ts_column"), spec.get("user_column")]:
                _need(col is None or IDENTIFIER.match(col) is not None, f"tenant config: '{col}' is not a valid column identifier")
        users_cols = set(views.get("fc_.v_users", {}).get("required_columns", []))
        for name, metric in raw["metrics"].items():
            _need(metric.get("kind") in METRIC_KINDS, f"tenant config: metric {name} has an invalid kind")
            _need(metric.get("source_view") in views, f"tenant config: metric {name} source_view is not a configured view")
            _need(all(v in views for v in metric.get("lineage_views", [])), f"tenant config: metric {name} lineage_views unknown")
            _need(isinstance(metric.get("materiality"), (int, float)) and metric["materiality"] > 0,
                  f"tenant config: metric {name} needs a positive materiality")
            _need(isinstance(metric.get("maturity_days"), int) and metric["maturity_days"] >= 0, f"tenant config: metric {name} maturity_days")
            _need(metric.get("outcome", {}).get("type") in OUTCOME_TYPES, f"tenant config: metric {name} outcome type is invalid")
            _need(metric.get("denominator") in ("users", "trial_starters"), f"tenant config: metric {name} denominator is invalid")
        for metric, col in raw["segment_keys"].items():
            _need(metric in raw["metrics"], f"tenant config: segment_keys names unknown metric {metric}")
            _need(col in users_cols and IDENTIFIER.match(col) is not None, f"tenant config: segment key {col} is not a v_users column")
        for key, spec in raw["funnels"].items():
            _need(isinstance(spec, list) and len(spec) >= 2, f"tenant config: funnel {key} needs at least two steps")
        for scen, spec in raw["decision_analyses"].items():
            comp = spec.get("comparison")
            if comp is not None:
                _need(comp.get("type") in COMPARISON_TYPES, f"tenant config: {scen} comparison type is invalid")
                pop = comp.get("population")
                if pop:
                    _need(pop.get("column") in users_cols and IDENTIFIER.match(pop["column"]) is not None,
                          f"tenant config: {scen} population column is not a v_users column")
            if spec.get("funnel") is not None:
                _need(spec["funnel"] in raw["funnels"], f"tenant config: {scen} funnel is not configured")
        return cls(version=str(raw["version"]), org_key=str(raw["org_key"]), content_hash=content_hash,
                   analytics_params_version=str(raw["analytics_params_version"]), data=raw)

    # ---- accessors
    @property
    def views(self) -> Mapping[str, Any]:
        return self.data["views"]

    def view(self, name: str) -> Mapping[str, Any]:
        if name not in self.views:
            raise ParamsError(f"view {name} is not configured for this tenant")
        return self.views[name]

    def metric(self, name: str) -> Mapping[str, Any] | None:
        return self.data["metrics"].get(name)

    def require_metric(self, name: str) -> Mapping[str, Any]:
        m = self.metric(name)
        if m is None:
            raise ParamsError(f"metric {name} has no analytics configuration")
        return m

    def segment_key(self, metric_name: str) -> str | None:
        return self.data["segment_keys"].get(metric_name)

    def funnel(self, name: str) -> list[str]:
        return list(self.data["funnels"][name])

    def decision_analyses(self, scenario_key: str | None) -> Mapping[str, Any]:
        return self.data["decision_analyses"].get(scenario_key or "", {})

    def experiment_outcome(self, outcome_key: str | None) -> Mapping[str, Any] | None:
        return self.data["experiment_outcomes"].get(outcome_key or "")

    def data_source_ref(self, view: str) -> str:
        return str(self.view(view)["data_source_ref"])
