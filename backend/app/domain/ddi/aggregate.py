"""Aggregation, cap reconciliation, rounding, bands and largest-remainder allocation (R2, R3).

    Support = sum_k w_k D_k            (w_k equal over applicable dimensions, or perturbed and renormalized)
    Penalty = 1 + c1 P1 + c2 P2
    uncapped = 100 (1 - Support) Penalty        displayed = round1(min(100, uncapped))

Contributions: dimension k contributes 100 (1 - D_k) w_k. Penalty i contributes (sum of dimension
contributions) x c_i x P_i. They sum to `uncapped`. When uncapped > 100, every contribution is scaled by
100 / uncapped so the displayed components still add up to the displayed DDI.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.ddi.params import DdiParams


def round_half_up(x: float, ndigits: int = 1) -> float:
    """Round half up after removing binary float noise (49.95 -> 50.0)."""
    q = Decimal(1).scaleb(-ndigits)
    return float(Decimal(repr(round(x, 9))).quantize(q, rounding=ROUND_HALF_UP))


def band_for(display_ddi: float, params: DdiParams) -> str:
    """Band of an already-rounded (one-decimal) DDI. The last band includes its upper bound (100 is Critical)."""
    for b in params.bands:
        if display_ddi >= b.min and (display_ddi < b.max or (b.max_inclusive and display_ddi <= b.max)):
            return b.name
    raise ValueError(f"DDI {display_ddi} is outside every band")


@dataclass(frozen=True)
class Aggregate:
    weights: Mapping[str, float]
    support: float
    penalty_multiplier: float
    dim_contributions: Mapping[str, float]      # raw, before cap scaling
    penalty_contributions: Mapping[str, float]  # P1, P2 raw
    uncapped: float

    @property
    def capped(self) -> float:
        return min(100.0, self.uncapped)


def aggregate(scores: Mapping[str, float], applicable: Sequence[str], p1: float, p2: float, params: DdiParams, *,
              weight_multipliers: Mapping[str, float] | None = None,
              coefficient_multipliers: tuple[float, float] = (1.0, 1.0)) -> Aggregate:
    if not applicable:
        raise ValueError("at least one dimension must be applicable")
    m = {d: (weight_multipliers or {}).get(d, 1.0) for d in applicable}
    total = sum(m.values())
    weights = {d: m[d] / total for d in applicable}
    support = sum(weights[d] * scores[d] for d in applicable)
    c1 = params.contradiction_coefficient * coefficient_multipliers[0]
    c2 = params.uncertainty_coefficient * coefficient_multipliers[1]
    dim_c = {d: 100.0 * (1.0 - scores[d]) * weights[d] for d in applicable}
    base = sum(dim_c.values())
    pen_c = {"P1": base * c1 * p1, "P2": base * c2 * p2}
    return Aggregate(weights, support, 1.0 + c1 * p1 + c2 * p2, dim_c, pen_c, base + pen_c["P1"] + pen_c["P2"])


@dataclass(frozen=True)
class Finalized:
    ddi_display: float
    uncapped_display: float
    cap_applied: bool
    raw: Mapping[str, float]          # scaled contributions (dimensions then penalties), unrounded
    display: Mapping[str, float]      # one-decimal, sum exactly to ddi_display


def largest_remainder(values: Mapping[str, float], target_tenths: int) -> dict[str, float]:
    """Allocate `target_tenths` units of 0.1 across the keys proportionally (largest remainder).

    Ties on the remainder go to the earlier key, so the result is deterministic.
    """
    keys = list(values)
    scaled = {k: round(values[k] * 10.0, 6) for k in keys}
    floors = {k: math.floor(scaled[k] + 1e-9) for k in keys}
    remainders = {k: round(scaled[k] - floors[k], 6) for k in keys}
    extra = target_tenths - sum(floors.values())
    order = sorted(keys, key=lambda k: (-remainders[k], keys.index(k)))
    alloc = dict(floors)
    step = 1 if extra >= 0 else -1
    for k in order[: abs(extra)]:
        alloc[k] += step
    return {k: alloc[k] / 10.0 for k in keys}


def finalize(agg: Aggregate, applicable: Sequence[str]) -> Finalized:
    uncapped = agg.uncapped
    cap_applied = uncapped > 100.0 + 1e-12
    scale = 100.0 / uncapped if cap_applied else 1.0
    raw = {d: agg.dim_contributions[d] * scale for d in applicable}
    raw["P1"] = agg.penalty_contributions["P1"] * scale
    raw["P2"] = agg.penalty_contributions["P2"] * scale
    ddi = round_half_up(min(100.0, uncapped), 1)
    display = largest_remainder(raw, int(round(ddi * 10)))
    return Finalized(ddi, round_half_up(uncapped, 1), cap_applied, raw, display)
