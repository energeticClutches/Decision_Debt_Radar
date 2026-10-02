"""Typed, immutable view of a DDI parameter file (ddi_params_v0.1.yaml).

The YAML is parsed and hash-verified by app.core.params. This module only converts the parsed mapping
into a frozen structure so the engine never reads loose dictionaries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.errors import ParamsError

POSITIVE_DIMENSIONS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7")
PENALTY_DIMENSIONS = ("P1", "P2")

DIMENSION_NAMES = {
    "D1": "Evidence Quality",
    "D2": "Evidence Coverage",
    "D3": "Evidence Freshness",
    "D4": "Experimental Strength",
    "D5": "Customer Evidence",
    "D6": "Behavioral Evidence",
    "D7": "Financial / Business Evidence",
    "P1": "Contradiction",
    "P2": "Uncertainty",
}


@dataclass(frozen=True)
class Band:
    name: str
    min: float
    max: float
    max_inclusive: bool = False


@dataclass(frozen=True)
class DdiParams:
    version: str
    content_hash: str
    tier_factor: Mapping[int, float]
    grade_factor: Mapping[str, float]
    dq_factor: Mapping[str, float]
    half_life_days: Mapping[str, float]
    design_rank: Mapping[str, float]
    small_n_threshold: int
    power_target: float
    srm_fail_integrity_factor: float
    informativeness: tuple[tuple[float | None, float], ...]
    default_power_factor: float
    default_informativeness: float
    customer_weights: tuple[float, float, float]          # sample_adequacy, segment_coverage, relevance
    quote_count_for_full_adequacy: float
    default_relevance: float
    default_segment_coverage: float
    observational_cap: float
    cap_lifted_when_d4_at_least: float
    materiality_threshold: float
    n_required: float
    financial_components: tuple[float, float, float]      # quantified, tier<=2, sensitivity range
    contradiction_coefficient: float
    uncertainty_coefficient: float
    segment_divergence_floor_p1: float
    ci_component_when_effect_zero: float
    direction_majority_share: float
    direction_min_bearing_items: int
    bands: tuple[Band, ...]
    min_evidence_items: int
    min_evidence_types: int
    require_success_metric_evidence: bool
    block_on_open_critical_dq: bool
    coverage_checklists: Mapping[str, tuple[tuple[str, ...], ...]]   # each entry = accepted evidence types
    not_applicable_dimensions: Mapping[str, tuple[str, ...]]
    weight_multipliers: tuple[float, ...]
    penalty_multipliers: tuple[float, ...]
    robust_share: float

    @classmethod
    def from_mapping(cls, raw: Mapping, content_hash: str) -> DdiParams:
        try:
            cw = raw["customer"]["weights"]
            fc = raw["financial"]["components"]
            checklists = {}
            for dtype, entries in raw["coverage_checklists"].items():
                parsed = []
                for e in entries:
                    parsed.append(tuple(e["any_of"]) if isinstance(e, Mapping) else (e,))
                checklists[dtype] = tuple(parsed)
            return cls(
                version=str(raw["version"]),
                content_hash=content_hash,
                tier_factor={int(k): float(v) for k, v in raw["tier_factor"].items()},
                grade_factor={str(k): float(v) for k, v in raw["grade_factor"].items()},
                dq_factor={str(k): float(v) for k, v in raw["dq_factor"].items()},
                half_life_days={str(k): float(v) for k, v in raw["half_life_days"].items()},
                design_rank={str(k): float(v) for k, v in raw["design_rank"].items()},
                small_n_threshold=int(raw["small_n_threshold"]),
                power_target=float(raw["experiment"]["power_target"]),
                srm_fail_integrity_factor=float(raw["experiment"]["srm_fail_integrity_factor"]),
                informativeness=tuple(
                    (None if r["max_ci_width_to_mde_ratio"] is None else float(r["max_ci_width_to_mde_ratio"]),
                     float(r["factor"]))
                    for r in raw["experiment"]["informativeness"]),
                default_power_factor=float(raw["experiment"]["default_power_factor"]),
                default_informativeness=float(raw["experiment"]["default_informativeness"]),
                customer_weights=(float(cw["sample_adequacy"]), float(cw["segment_coverage"]), float(cw["relevance"])),
                quote_count_for_full_adequacy=float(raw["customer"]["quote_count_for_full_adequacy"]),
                default_relevance=float(raw["customer"]["default_relevance"]),
                default_segment_coverage=float(raw["customer"]["default_segment_coverage"]),
                observational_cap=float(raw["behavioral"]["observational_cap"]),
                cap_lifted_when_d4_at_least=float(raw["behavioral"]["cap_lifted_when_d4_at_least"]),
                materiality_threshold=float(raw["behavioral"]["materiality_threshold"]),
                n_required=float(raw["behavioral"]["n_required"]),
                financial_components=(float(fc["quantified_estimate"]), float(fc["source_tier_at_most_2"]),
                                      float(fc["sensitivity_range_present"])),
                contradiction_coefficient=float(raw["penalties"]["contradiction_coefficient"]),
                uncertainty_coefficient=float(raw["penalties"]["uncertainty_coefficient"]),
                segment_divergence_floor_p1=float(raw["penalties"]["segment_divergence_floor_p1"]),
                ci_component_when_effect_zero=float(raw["uncertainty"]["ci_component_when_effect_zero"]),
                direction_majority_share=float(raw["direction"]["majority_share"]),
                direction_min_bearing_items=int(raw["direction"]["min_direction_bearing_items"]),
                bands=tuple(Band(b["name"], float(b["min"]), float(b["max"]), bool(b.get("max_inclusive", False)))
                            for b in raw["bands"]),
                min_evidence_items=int(raw["gating"]["min_evidence_items"]),
                min_evidence_types=int(raw["gating"]["min_evidence_types"]),
                require_success_metric_evidence=bool(raw["gating"]["require_success_metric_evidence"]),
                block_on_open_critical_dq=bool(raw["gating"]["block_on_open_critical_dq_for_success_metric"]),
                coverage_checklists=checklists,
                not_applicable_dimensions={k: tuple(v) for k, v in raw["not_applicable_dimensions"].items()},
                weight_multipliers=tuple(float(x) for x in raw["sensitivity"]["weight_multipliers"]),
                penalty_multipliers=tuple(float(x) for x in raw["sensitivity"]["penalty_multipliers"]),
                robust_share=float(raw["sensitivity"]["robust_if_band_unchanged_share_at_least"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ParamsError(f"DDI parameter file is incomplete or malformed: {exc!r}") from exc
