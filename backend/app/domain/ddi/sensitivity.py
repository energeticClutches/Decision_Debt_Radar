"""Sensitivity analysis (DDI-spec section 8, R-brief section 2).

For each applicable dimension the weight is multiplied by 0.5 and by 1.5 (then renormalized): 2K runs.
The penalty coefficients are multiplied by 0.5 and 1.5 together, and each coefficient separately: 6 runs.
Total = 2K + 6. The base case is NOT one of the perturbations. Item-level factors are not perturbed.
Each perturbation is rounded to one decimal first and then banded, like the base case.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.ddi.aggregate import aggregate, band_for, round_half_up
from app.domain.ddi.params import DdiParams
from app.domain.ddi.scoring import Components


@dataclass(frozen=True)
class Run:
    label: str
    ddi: float
    band: str


@dataclass(frozen=True)
class Sensitivity:
    base: float
    base_band: str
    min: float
    max: float
    count: int
    unchanged_band_share: float
    band_stable: bool
    label: str                       # robust | sensitive
    most_influential: dict
    runs: tuple[Run, ...]

    def to_dict(self) -> dict:
        return {
            "base": self.base, "base_band": self.base_band, "min": self.min, "max": self.max,
            "range": [self.min, self.max], "count": self.count,
            "unchanged_band_share": round(self.unchanged_band_share, 4),
            "band_stable": self.band_stable, "label": self.label,
            "label_text": ("Robust to aggregation weights and penalty coefficients." if self.band_stable
                           else "Sensitive: the band changes under some weight or coefficient perturbations."),
            "most_influential": self.most_influential,
            "runs": [{"label": r.label, "ddi": r.ddi, "band": r.band} for r in self.runs],
            "perturbs": "aggregation weights and penalty coefficients only; item-level factors are not perturbed",
        }


def summarize(base: float, base_band: str, runs: list[Run], robust_share: float) -> Sensitivity:
    """Pure summary of a list of perturbation runs (separately testable at exactly the 90% threshold)."""
    count = len(runs)
    unchanged = sum(1 for r in runs if r.band == base_band)
    share = unchanged / count if count else 1.0
    values = [base] + [r.ddi for r in runs]
    top = max(runs, key=lambda r: abs(r.ddi - base)) if runs else None
    most = ({"label": top.label, "ddi": top.ddi, "delta": round_half_up(top.ddi - base, 1)} if top else {})
    stable = share >= robust_share - 1e-9
    return Sensitivity(base, base_band, min(values), max(values), count, share, stable,
                       "robust" if stable else "sensitive", most, tuple(runs))


def run_sensitivity(components: Components, params: DdiParams, base_display: float, base_band: str) -> Sensitivity:
    scores = components.scores()
    p1, p2 = components.p1.score, components.p2.score
    applicable = components.applicable
    runs: list[Run] = []

    def add(label: str, **kw) -> None:
        agg = aggregate(scores, applicable, p1, p2, params, **kw)
        d = round_half_up(agg.capped, 1)
        runs.append(Run(label, d, band_for(d, params)))

    for dim in applicable:
        for mult in params.weight_multipliers:
            add(f"weight {dim} x{mult:g}", weight_multipliers={dim: mult})
    for mult in params.penalty_multipliers:
        add(f"penalty coefficients x{mult:g}", coefficient_multipliers=(mult, mult))
    for mult in params.penalty_multipliers:
        add(f"P1 coefficient x{mult:g}", coefficient_multipliers=(mult, 1.0))
    for mult in params.penalty_multipliers:
        add(f"P2 coefficient x{mult:g}", coefficient_multipliers=(1.0, mult))
    return summarize(base_display, base_band, runs, params.robust_share)
