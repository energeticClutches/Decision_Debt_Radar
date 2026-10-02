"""The deterministic DDI engine.

    assess(facts, params, as_of) -> DdiResult

`as_of` is injected (the engine never reads the clock). Identical facts + params + as_of give an identical
result. No LLM, no I/O. See docs/DDI-spec.md and docs/day-3-implementation-notes.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.domain.ddi.aggregate import Aggregate, aggregate, band_for, finalize
from app.domain.ddi.params import DIMENSION_NAMES, POSITIVE_DIMENSIONS, DdiParams
from app.domain.ddi.scoring import (
    BlockingReason,
    Components,
    DimScore,
    EvidenceDirection,
    P2Parts,
    PenaltyScore,
    applicable_dimensions,
    compute_components,
    evaluate_gate,
    evidence_direction,
)
from app.domain.ddi.sensitivity import Sensitivity, run_sensitivity
from app.domain.facts import EvidenceFacts

SCORED = "scored"
INSUFFICIENT = "insufficient_evidence"
POSITIONING = "DDI is an evidence-risk heuristic, not a measure of decision quality."


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


@dataclass(frozen=True)
class DimensionOut:
    id: str
    name: str
    score: float | None
    applicable: bool
    weight: float
    raw_contribution: float
    display_contribution: float
    defaulted_inputs: tuple[dict, ...]
    explanation: str
    details: Mapping[str, object] = field(default_factory=dict)
    inputs: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "score": _r(self.score),
                "applicable": self.applicable,
                "status": "Applicable" if self.applicable else "Not applicable",
                "weight": _r(self.weight), "raw_contribution": _r(self.raw_contribution),
                "display_contribution": self.display_contribution,
                "inputs": list(self.inputs), "defaulted_inputs": list(self.defaulted_inputs), "explanation": self.explanation,
                "details": dict(self.details)}


@dataclass(frozen=True)
class PenaltyOut:
    id: str
    name: str
    score: float
    coefficient: float
    raw_contribution: float
    display_contribution: float
    defaulted_inputs: tuple[dict, ...]
    explanation: str
    details: Mapping[str, object] = field(default_factory=dict)
    inputs: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "score": _r(self.score), "coefficient": self.coefficient,
                "raw_contribution": _r(self.raw_contribution), "display_contribution": self.display_contribution,
                "inputs": list(self.inputs), "defaulted_inputs": list(self.defaulted_inputs), "explanation": self.explanation,
                "details": dict(self.details)}


@dataclass(frozen=True)
class DdiResult:
    state: str
    params_version: str
    params_hash: str
    as_of: date
    decision_type: str
    direction: EvidenceDirection
    blocking_reasons: tuple[BlockingReason, ...] = ()
    warnings: tuple[dict, ...] = ()
    ddi: float | None = None                  # displayed value (one decimal). None unless scored
    uncapped_ddi: float | None = None
    cap_applied: bool | None = None
    band: str | None = None
    support: float | None = None
    penalty_multiplier: float | None = None
    dimensions: tuple[DimensionOut, ...] = ()
    penalties: tuple[PenaltyOut, ...] = ()
    sensitivity: Sensitivity | None = None
    what_drove: str | None = None
    components: Components | None = None      # engine-internal detail used by the NBE engine; never serialized

    @property
    def scored(self) -> bool:
        return self.state == SCORED

    # ---- storage payloads for decision_assessments (3.5)
    def dimension_scores_payload(self) -> dict:
        payload: dict = {
            "params_version": self.params_version, "params_hash": self.params_hash,
            "as_of_date": self.as_of.isoformat(), "state": self.state,
            "ddi_display": self.ddi, "uncapped_ddi": self.uncapped_ddi, "cap_applied": self.cap_applied,
            "band": self.band, "support": _r(self.support), "penalty_multiplier": _r(self.penalty_multiplier),
            "positioning": POSITIONING,
            "dimensions": {d.id: d.to_dict() for d in self.dimensions},
            "what_drove_this_result": self.what_drove,
            "evidence_direction": self.direction.to_dict(),
            "warnings": list(self.warnings),
        }
        return payload

    def penalty_scores_payload(self) -> dict:
        if not self.scored:
            return {}
        return {"penalties": {p.id: p.to_dict() for p in self.penalties},
                "coefficients": {"P1": self.penalties[0].coefficient, "P2": self.penalties[1].coefficient},
                "penalty_multiplier": _r(self.penalty_multiplier)}

    def sensitivity_payload(self) -> dict:
        return self.sensitivity.to_dict() if self.sensitivity else {}

    def blocking_payload(self) -> list[dict]:
        return [r.to_dict() for r in self.blocking_reasons]


# ---------------------------------------------------------------- narrative


def _drivers_text(ddi: float, band: str, dims: tuple[DimensionOut, ...], pens: tuple[PenaltyOut, ...],
                  cap_applied: bool, uncapped: float) -> str:
    rows = [(d.display_contribution, d.name) for d in dims if d.applicable]
    rows.sort(key=lambda r: -r[0])
    top = rows[:3]
    text = (f"DDI {ddi:.1f} ({band.capitalize()}). The largest contributions to the evidence debt are "
            + ", ".join(f"{name} ({val:.1f} points)" for val, name in top) + ".")
    p1, p2 = pens[0].display_contribution, pens[1].display_contribution
    text += f" Penalties add {p1 + p2:.1f} points (contradiction {p1:.1f}, uncertainty {p2:.1f})."
    na = [d.name for d in dims if not d.applicable]
    if na:
        text += f" Not applicable for this decision type: {', '.join(na)}."
    if cap_applied:
        text += f" The uncapped value {uncapped:.1f} was capped at 100 and all contributions were scaled to match."
    return text


# ---------------------------------------------------------------- assembly


def _scored_result(components: Components, params: DdiParams, as_of: date, direction: EvidenceDirection,
                   warnings: tuple[dict, ...]) -> DdiResult:
    applicable = components.applicable
    agg: Aggregate = aggregate(components.scores(), applicable, components.p1.score, components.p2.score, params)
    fin = finalize(agg, applicable)
    band = band_for(fin.ddi_display, params)
    dims: list[DimensionOut] = []
    for d in POSITIVE_DIMENSIONS:
        ds: DimScore = components.dims[d]
        if d in applicable:
            dims.append(DimensionOut(d, DIMENSION_NAMES[d], ds.score, True, agg.weights[d], fin.raw[d], fin.display[d],
                                     tuple(i.to_dict() for i in ds.defaulted_inputs), ds.explanation, ds.details,
                                     tuple(i.to_dict() for i in ds.inputs)))
        else:
            dims.append(DimensionOut(d, DIMENSION_NAMES[d], None, False, 0.0, 0.0, 0.0, (), ds.explanation, {}))
    pens: list[PenaltyOut] = []
    for pid, pen, coef in (("P1", components.p1, params.contradiction_coefficient),
                           ("P2", components.p2, params.uncertainty_coefficient)):
        pens.append(PenaltyOut(pid, DIMENSION_NAMES[pid], pen.score, coef, fin.raw[pid], fin.display[pid],
                               tuple(i.to_dict() for i in pen.defaulted_inputs), pen.explanation, pen.details,
                               tuple(i.to_dict() for i in pen.inputs)))
    sens = run_sensitivity(components, params, fin.ddi_display, band)
    drove = _drivers_text(fin.ddi_display, band, tuple(dims), tuple(pens), fin.cap_applied, fin.uncapped_display)
    return DdiResult(
        state=SCORED, params_version=params.version, params_hash=params.content_hash, as_of=as_of,
        decision_type=components.decision_type, direction=direction, warnings=warnings,
        ddi=fin.ddi_display, uncapped_ddi=fin.uncapped_display, cap_applied=fin.cap_applied, band=band,
        support=agg.support, penalty_multiplier=agg.penalty_multiplier, dimensions=tuple(dims), penalties=tuple(pens),
        sensitivity=sens, what_drove=drove, components=components)


def score_components(components: Components, params: DdiParams, as_of: date,
                     direction: EvidenceDirection | None = None, warnings: tuple[dict, ...] = ()) -> DdiResult:
    """Aggregate precomputed components into a scored result (used by assess() and by test fixtures)."""
    direction = direction or EvidenceDirection("uncertain", 0.0, 0.0, 0.0, 0.0, params.direction_majority_share, 0,
                                               "No direction was supplied.")
    return _scored_result(components, params, as_of, direction, warnings)


def components_from_scores(decision_type: str, scores: Mapping[str, float], p1: float, p2: float, params: DdiParams, *,
                           p2_parts: P2Parts | None = None, d6_raw: float | None = None,
                           types_present: frozenset[str] = frozenset(), success_metric_is_target: bool = True,
                           heterogeneity_flag: bool = False,
                           details: Mapping[str, Mapping[str, object]] | None = None) -> Components:
    """Build Components from given dimension scores (illustrative examples and tests, e.g. DDI-spec section 9)."""
    applicable = applicable_dimensions(decision_type, params)
    details = details or {}
    dims = {d: (DimScore(scores[d], True, (), f"given {scores[d]}", dict(details.get(d, {}))) if d in applicable
                else DimScore(None, False, (), f"Not applicable for decision type {decision_type}.", {}))
            for d in POSITIVE_DIMENSIONS}
    return Components(
        decision_type=decision_type, dims=dims, applicable=applicable, p1=PenaltyScore(p1, (), f"given {p1}", {}),
        p2=PenaltyScore(p2, (), f"given {p2}", {}), p2_parts=p2_parts or P2Parts(ci=p2), d6_raw=d6_raw,
        checklist=params.coverage_checklists[decision_type], types_present=types_present,
        heterogeneity_flag=heterogeneity_flag, success_metric_is_target=success_metric_is_target)


def assess(facts: EvidenceFacts, params: DdiParams, as_of: date) -> DdiResult:
    gate = evaluate_gate(facts, params)
    if gate.blocked:
        direction = evidence_direction(facts, params, as_of, insufficient=True)
        return DdiResult(state=INSUFFICIENT, params_version=params.version, params_hash=params.content_hash,
                         as_of=as_of, decision_type=facts.decision_type, direction=direction,
                         blocking_reasons=gate.reasons, warnings=gate.warnings)
    direction = evidence_direction(facts, params, as_of, insufficient=False)
    components = compute_components(facts, params, as_of)
    return _scored_result(components, params, as_of, direction, gate.warnings)
