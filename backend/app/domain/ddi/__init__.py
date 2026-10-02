"""DDI engine package (pure). Parameters: backend/config/ddi/. Specification: docs/DDI-spec.md."""

from app.domain.ddi.aggregate import aggregate, band_for, finalize, largest_remainder, round_half_up
from app.domain.ddi.engine import (
    INSUFFICIENT,
    SCORED,
    DdiResult,
    assess,
    components_from_scores,
    score_components,
)
from app.domain.ddi.params import DdiParams
from app.domain.ddi.scoring import (
    Components,
    compute_components,
    evaluate_gate,
    evidence_direction,
    item_weight,
)
from app.domain.ddi.sensitivity import Run, Sensitivity, run_sensitivity, summarize

__all__ = [
    "INSUFFICIENT", "SCORED", "Components", "DdiParams", "DdiResult", "Run", "Sensitivity", "aggregate", "assess",
    "band_for", "components_from_scores", "compute_components", "evaluate_gate", "evidence_direction", "finalize",
    "item_weight", "largest_remainder", "round_half_up", "run_sensitivity", "score_components", "summarize",
]
