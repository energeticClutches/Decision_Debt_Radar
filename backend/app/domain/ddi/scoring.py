"""Dimension and penalty scoring, gating and the evidence-direction summary.

Pure functions of (EvidenceFacts, DdiParams, as_of). `as_of` is always injected: this module never reads
the clock. Items are processed in id order so the result does not depend on input ordering.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.domain.ddi.params import DIMENSION_NAMES, POSITIVE_DIMENSIONS, DdiParams
from app.domain.facts import EvidenceFacts, EvidenceItem, ExperimentFact

# ---------------------------------------------------------------- result structures


@dataclass(frozen=True)
class InputValue:
    """One input of a dimension or penalty. A value that fell back to a documented default is NEVER presented
    as observed: `source` is "default" and `default_reason` explains why (PO rule 3.4b)."""

    name: str
    value: object
    source: str                       # "observed" | "default"
    default_reason: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "source": self.source, "default_reason": self.default_reason}


def observed(name: str, value) -> InputValue:
    return InputValue(name, value, "observed", None)


def defaulted(name: str, value, reason: str) -> InputValue:
    return InputValue(name, value, "default", reason)


@dataclass(frozen=True)
class DimScore:
    score: float | None               # None only when the dimension is not applicable
    applicable: bool = True
    inputs: tuple[InputValue, ...] = ()
    explanation: str = ""
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def defaulted_inputs(self) -> tuple[InputValue, ...]:
        return tuple(i for i in self.inputs if i.source == "default")


@dataclass(frozen=True)
class P2Parts:
    ci: float | None = None
    small_n: float | None = None
    hhi: float | None = None

    def available(self) -> dict[str, float]:
        return {k: v for k, v in (("ci_width", self.ci), ("small_n_share", self.small_n),
                                  ("source_concentration", self.hhi)) if v is not None}

    def value(self) -> float:
        parts = self.available()
        return sum(parts.values()) / len(parts) if parts else 0.0


@dataclass(frozen=True)
class PenaltyScore:
    score: float
    inputs: tuple[InputValue, ...] = ()
    explanation: str = ""
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def defaulted_inputs(self) -> tuple[InputValue, ...]:
        return tuple(i for i in self.inputs if i.source == "default")


@dataclass(frozen=True)
class Components:
    """Everything the aggregation and the NBE engine need, before aggregation."""

    decision_type: str
    dims: Mapping[str, DimScore]
    applicable: tuple[str, ...]
    p1: PenaltyScore
    p2: PenaltyScore
    p2_parts: P2Parts
    d6_raw: float | None
    checklist: tuple[tuple[str, ...], ...]
    types_present: frozenset[str]
    heterogeneity_flag: bool
    success_metric_is_target: bool

    def score(self, dim: str) -> float:
        s = self.dims[dim].score
        return 0.0 if s is None else s

    def scores(self) -> dict[str, float]:
        return {d: self.score(d) for d in self.applicable}


@dataclass(frozen=True)
class BlockingReason:
    code: str
    message: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}


@dataclass(frozen=True)
class Gate:
    reasons: tuple[BlockingReason, ...]
    warnings: tuple[dict, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True)
class EvidenceDirection:
    """Evidence-direction summary (3.4). A parallel interpretation of the evidence: it never feeds the DDI."""

    label: str                         # supporting | contradicting | mixed | uncertain
    supporting_share: float            # supporting weight / direction-bearing weight
    contradicting_share: float         # contradicting weight / direction-bearing weight
    neutral_share: float               # neutral weight / total weight
    direction_basis_weight: float      # direction-bearing weight / total weight
    threshold: float
    direction_bearing_items: int
    explanation: str = ""

    def to_dict(self) -> dict:
        return {"label": self.label, "supporting_share": round(self.supporting_share, 4),
                "contradicting_share": round(self.contradicting_share, 4), "neutral_share": round(self.neutral_share, 4),
                "direction_basis_weight": round(self.direction_basis_weight, 4), "threshold": self.threshold,
                "direction_bearing_items": self.direction_bearing_items, "explanation": self.explanation,
                "note": "Evidence direction is separate from the DDI. DDI measures evidence debt, not whether the "
                        "hypothesis is right."}


# ---------------------------------------------------------------- item-level factors


def age_days(as_of: date, observed_end: date) -> int:
    return max(0, (as_of - observed_end).days)


def freshness_factor(item: EvidenceItem, params: DdiParams, as_of: date) -> float:
    return 0.5 ** (age_days(as_of, item.observed_end) / params.half_life_days[item.evidence_type])


def quality_factor(item: EvidenceItem, params: DdiParams) -> float:
    """tier x grade x dq (the D1 term)."""
    return (params.tier_factor[item.reliability_tier] * params.grade_factor[item.strength_grade]
            * params.dq_factor[item.dq_status])


def item_weight(item: EvidenceItem, params: DdiParams, as_of: date) -> float:
    """w = tier x grade x freshness x dq_factor (P1 and the direction summary)."""
    return quality_factor(item, params) * freshness_factor(item, params, as_of)


def _sorted_items(facts: EvidenceFacts) -> list[EvidenceItem]:
    return sorted(facts.items, key=lambda i: i.id)


def applicable_dimensions(decision_type: str, params: DdiParams) -> tuple[str, ...]:
    na = set(params.not_applicable_dimensions.get(decision_type, ()))
    return tuple(d for d in POSITIVE_DIMENSIONS if d not in na)


# ---------------------------------------------------------------- gating


def _linked_to_success_metric(item: EvidenceItem, facts: EvidenceFacts) -> bool:
    if item.metric_id is not None and item.metric_id == facts.success_metric_id:
        return True
    exp = facts.experiment(item.experiment_id)
    return exp is not None and exp.primary_metric_id == facts.success_metric_id


def _dq_affects_success_metric(issue, facts: EvidenceFacts) -> bool:
    if issue.affects_metric_id is not None and issue.affects_metric_id == facts.success_metric_id:
        return True
    return (facts.success_metric_data_source_id is not None
            and issue.data_source_id == facts.success_metric_data_source_id)


def evaluate_gate(facts: EvidenceFacts, params: DdiParams) -> Gate:
    """BR-1 to BR-3. Reasons are always reported in the fixed order
    min_items, min_types, success_metric_evidence, open_critical_dq (R5)."""
    reasons: list[BlockingReason] = []
    n_items = len(facts.items)
    types = sorted({i.evidence_type for i in facts.items})
    if n_items < params.min_evidence_items:
        reasons.append(BlockingReason(
            "min_items", f"Fewer than {params.min_evidence_items} evidence items ({n_items} found).",
            {"required": params.min_evidence_items, "found": n_items}))
    if len(types) < params.min_evidence_types:
        reasons.append(BlockingReason(
            "min_types", f"Fewer than {params.min_evidence_types} distinct evidence types ({len(types)} found).",
            {"required": params.min_evidence_types, "found": len(types), "types": types}))
    if params.require_success_metric_evidence and not any(_linked_to_success_metric(i, facts) for i in facts.items):
        reasons.append(BlockingReason(
            "success_metric_evidence", "No evidence relates directly to the decision's success metric.",
            {"success_metric_id": facts.success_metric_id}))
    warnings: list[dict] = []
    open_critical = [q for q in facts.dq_issues
                     if q.status == "open" and q.severity == "critical" and _dq_affects_success_metric(q, facts)]
    if params.block_on_open_critical_dq and open_critical:
        reasons.append(BlockingReason(
            "open_critical_dq",
            "An open critical data-quality issue affects the data source of the success metric.",
            {"dq_check_ids": sorted(q.id for q in open_critical),
             "data_source_ids": sorted({q.data_source_id for q in open_critical})}))
    for q in sorted(facts.dq_issues, key=lambda q: q.id):
        if q.status == "accepted" and q.severity == "critical" and _dq_affects_success_metric(q, facts):
            warnings.append({"code": "accepted_critical_dq", "dq_check_id": q.id, "data_source_id": q.data_source_id,
                             "message": "A critical data-quality issue on the success metric's data source was "
                                        "accepted as a limitation. It does not block scoring."})
    return Gate(tuple(reasons), tuple(warnings))


# ---------------------------------------------------------------- evidence direction (R1, section 3.4)


def evidence_direction(facts: EvidenceFacts, params: DdiParams, as_of: date, *, insufficient: bool) -> EvidenceDirection:
    supporting = contradicting = neutral = 0.0
    bearing_items = 0
    for it in _sorted_items(facts):
        weight = item_weight(it, params, as_of)
        if it.stance == "neutral":
            neutral += weight
        elif weight > 0:
            bearing_items += 1
            if it.stance == "supports":
                supporting += weight
            else:
                contradicting += weight
    bearing = supporting + contradicting
    total = bearing + neutral
    sup_share = supporting / bearing if bearing > 0 else 0.0
    con_share = contradicting / bearing if bearing > 0 else 0.0
    neutral_share = neutral / total if total > 0 else 0.0
    basis = bearing / total if total > 0 else 0.0
    threshold = params.direction_majority_share
    if insufficient:
        label, why = "uncertain", "The assessment has insufficient evidence, so no direction is claimed."
    elif bearing_items < params.direction_min_bearing_items or bearing <= 0:
        label, why = "uncertain", (f"Only {bearing_items} direction-bearing evidence item(s); at least "
                                   f"{params.direction_min_bearing_items} with weight above zero are needed to classify a direction.")
    elif sup_share >= threshold:
        label, why = "supporting", f"{sup_share:.0%} of the direction-bearing weight supports the hypothesis."
    elif con_share >= threshold:
        label, why = "contradicting", f"{con_share:.0%} of the direction-bearing weight contradicts the hypothesis."
    else:
        label, why = "mixed", "Neither supporting nor contradicting evidence reaches the majority share of the direction-bearing weight."
    return EvidenceDirection(label, sup_share, con_share, neutral_share, basis, threshold, bearing_items, why)


# ---------------------------------------------------------------- dimensions


def _coverage(checklist: tuple[tuple[str, ...], ...], types_present: frozenset[str] | set[str]) -> tuple[float, list[str]]:
    covered = 0
    missing: list[str] = []
    for entry in checklist:
        if any(t in types_present for t in entry):
            covered += 1
        else:
            missing.append(" or ".join(entry))
    return covered / len(checklist), missing


def coverage_score(checklist: tuple[tuple[str, ...], ...], types_present) -> float:
    return _coverage(checklist, types_present)[0]


def _experiment_strength(exp: ExperimentFact, params: DdiParams) -> tuple[float, list[InputValue], dict]:
    inputs: list[InputValue] = []
    rank = params.design_rank.get(exp.design, params.design_rank.get("other", 0.2))
    if exp.achieved_power is not None:
        power_factor = min(1.0, exp.achieved_power / params.power_target)
        inputs.append(observed("power_factor", power_factor))
    else:
        power_factor = params.default_power_factor
        inputs.append(defaulted("power_factor", power_factor, "achieved power is not stored for this experiment"))
    if exp.srm_flag is None:
        integrity = params.srm_fail_integrity_factor
        inputs.append(defaulted("integrity_factor", integrity, "no SRM check result is stored (treated conservatively as failed)"))
    else:
        integrity = params.srm_fail_integrity_factor if exp.srm_flag else 1.0
        inputs.append(observed("integrity_factor", integrity))
    width = (exp.ci_high - exp.ci_low) if exp.ci_low is not None and exp.ci_high is not None else None
    if width is None or exp.mde is None or exp.mde <= 0:
        informativeness = params.default_informativeness
        inputs.append(defaulted("informativeness_factor", informativeness,
                                "the experiment has no stored confidence interval or minimum detectable effect"))
    else:
        ratio = width / exp.mde
        informativeness = params.informativeness[-1][1]
        for max_ratio, factor in params.informativeness:
            if max_ratio is None or ratio <= max_ratio:
                informativeness = factor
                break
        inputs.append(observed("informativeness_factor", informativeness))
    score = rank * power_factor * integrity * informativeness
    return score, inputs, {"experiment_id": exp.id, "design": exp.design, "design_rank": rank,
                           "power_factor": power_factor, "integrity_factor": integrity,
                           "informativeness_factor": informativeness}


def d6_from_raw(raw: float, d4: float, params: DdiParams) -> tuple[float, float | None]:
    """Apply the observational cap (lifted when D4 is high enough). Returns (score, cap or None)."""
    if d4 >= params.cap_lifted_when_d4_at_least:
        return min(1.0, raw), None
    return min(raw, params.observational_cap), params.observational_cap


def compute_components(facts: EvidenceFacts, params: DdiParams, as_of: date) -> Components:
    items = _sorted_items(facts)
    n = len(items)
    na = set(params.not_applicable_dimensions.get(facts.decision_type, ()))
    applicable = applicable_dimensions(facts.decision_type, params)
    checklist = params.coverage_checklists[facts.decision_type]
    types_present = frozenset(i.evidence_type for i in items)
    dims: dict[str, DimScore] = {}

    # D1 Evidence Quality
    if n:
        d1 = sum(quality_factor(i, params) for i in items) / n
        crit = sum(1 for i in items if i.dq_status == "critical")
        warn = sum(1 for i in items if i.dq_status == "warn")
        dims["D1"] = DimScore(d1, True, (), f"Mean of tier x grade x data-quality factor over {n} items = {d1:.2f}"
                              + (f" ({crit} item(s) with a critical DQ issue score 0, {warn} with a DQ warning x0.7)." if crit or warn else "."),
                              {"items": n, "critical_dq_items": crit, "warn_dq_items": warn})
    else:
        dims["D1"] = DimScore(0.0, True, (), "No evidence items.", {"items": 0})

    # D2 Evidence Coverage
    d2, missing = _coverage(checklist, types_present)
    dims["D2"] = DimScore(d2, True, (), f"{len(checklist) - len(missing)} of {len(checklist)} required evidence types present"
                          + (f"; missing: {', '.join(missing)}." if missing else "."),
                          {"types_required": len(checklist), "types_present": len(checklist) - len(missing), "missing": missing})

    # D3 Evidence Freshness
    if n:
        d3 = sum(freshness_factor(i, params, as_of) for i in items) / n
        dims["D3"] = DimScore(d3, True, (), f"Mean freshness factor over {n} items = {d3:.2f} (half-lives by evidence type).", {"items": n})
    else:
        dims["D3"] = DimScore(0.0, True, (), "No evidence items.", {})

    # D4 Experimental Strength
    if "D4" in na:
        d4 = 0.0
    else:
        used = sorted({i.experiment_id for i in items if i.experiment_id is not None and facts.experiment(i.experiment_id)})
        best = None
        for eid in used:
            exp = facts.experiment(eid)
            score, exp_inputs, detail = _experiment_strength(exp, params)
            if best is None or score > best[0]:
                best = (score, exp_inputs, detail)
        if best is None:
            d4 = 0.0
            dims["D4"] = DimScore(0.0, True, (), "No linked experiment evidence.", {"best_design": None})
        else:
            d4 = best[0]
            dims["D4"] = DimScore(d4, True, tuple(best[1]),
                                  f"Best experiment ({best[2]['design']}): design x power x integrity x informativeness = {d4:.2f}.",
                                  {**best[2], "best_design": best[2]["design"], "best_power_factor": best[2]["power_factor"]})

    # D5 Customer Evidence
    insight_ids = {i.insight_id for i in items if i.insight_id is not None}
    linked = [q for q in facts.insights if q.id in insight_ids]
    if not linked:
        has_customer_items = any(i.evidence_type == "customer" for i in items)
        dims["D5"] = DimScore(
            0.0, True,
            (defaulted("sample_adequacy", 0.0, "customer evidence exists but no customer insight with a quote count is linked"),)
            if has_customer_items else (),
            "No customer insight is linked to the evidence.", {"quote_count": 0})
    else:
        quotes = sum(q.quote_count for q in linked)
        adequacy = min(1.0, quotes / params.quote_count_for_full_adequacy)
        w_a, w_s, w_r = params.customer_weights
        d5 = w_a * adequacy + w_s * params.default_segment_coverage + w_r * params.default_relevance
        dims["D5"] = DimScore(
            d5, True,
            (observed("sample_adequacy", adequacy),
             defaulted("segment_coverage", params.default_segment_coverage, "no relevant-segment list exists to measure coverage against"),
             defaulted("relevance", params.default_relevance, "no explicit customer relevance value was supplied")),
            f"{quotes} quotes across {len(linked)} insight(s): 0.5 x adequacy {adequacy:.2f} + 0.3 x segment coverage "
            f"{params.default_segment_coverage} + 0.2 x relevance {params.default_relevance} = {d5:.2f}.",
            {"quote_count": quotes, "sample_adequacy": adequacy})

    # D6 Behavioral Evidence
    d6_raw: float | None = None
    if "D6" in na:
        pass
    else:
        # D6 measures Behavioral Evidence STRENGTH on the success metric, independent of stance (PO correction, R1):
        # a behavioral item that contradicts the hypothesis is just as strong evidence as one that supports it, so
        # the stance never enters D6. Direction is reported separately and reaches the DDI only through P1.
        beh = [i for i in items if i.evidence_type == "behavioral"
               and i.metric_id is not None and i.metric_id == facts.success_metric_id]
        inputs6: list[InputValue] = []
        if not beh:
            d6_raw = 0.0
            dims["D6"] = DimScore(0.0, True, (), "No behavioral evidence on the success metric.", {"raw": 0.0, "cap": None})
        else:
            vals = []
            for i in beh:
                if i.n_sample is None:
                    inputs6.append(defaulted(f"adequacy[{i.id}]", 0.0, "the evidence item has no sample size (n_sample)"))
                    adequacy6 = 0.0
                else:
                    adequacy6 = min(1.0, i.n_sample / params.n_required)
                    inputs6.append(observed(f"adequacy[{i.id}]", adequacy6))
                if i.effect_size is None:
                    inputs6.append(defaulted(f"materiality[{i.id}]", 0.0, "the evidence item has no effect size"))
                    materiality = 0.0
                else:
                    materiality = min(1.0, abs(i.effect_size) / params.materiality_threshold)
                    inputs6.append(observed(f"materiality[{i.id}]", materiality))
                vals.append(adequacy6 * materiality)
            d6_raw = sum(vals) / len(vals)
            d6, cap = d6_from_raw(d6_raw, d4, params)
            dims["D6"] = DimScore(
                d6, True, tuple(inputs6),
                f"Mean adequacy x |effect| materiality over {len(beh)} behavioral item(s) on the success metric = {d6_raw:.2f}"
                + (f", capped at {cap} because the evidence is observational (D4 < {params.cap_lifted_when_d4_at_least})."
                   if cap is not None and d6_raw > cap else "."),
                {"raw": d6_raw, "cap": cap, "items": len(beh)})
    # D7 Financial / Business Evidence
    fin = [i for i in items if i.evidence_type == "financial"]
    if not fin:
        dims["D7"] = DimScore(0.0, True, (), "No financial evidence.", {})
    else:
        q_w, t_w, s_w = params.financial_components
        best7 = 0.0
        for i in fin:
            s = (q_w if i.effect_size is not None else 0.0) + (t_w if i.reliability_tier <= 2 else 0.0) \
                + (s_w if i.ci_low is not None and i.ci_high is not None else 0.0)
            best7 = max(best7, s)
        dims["D7"] = DimScore(best7, True, (), f"Best financial item: quantified 0.5 + source tier <= 2 0.3 + sensitivity range 0.2 = {best7:.2f}.", {})

    # Not-applicable dimensions are reported, not scored
    for d in POSITIVE_DIMENSIONS:
        if d in na:
            dims[d] = DimScore(None, False, (), f"Not applicable for decision type {facts.decision_type}.", {})

    # P1 Contradiction
    num = den = 0.0
    contra: list[tuple[float, str]] = []
    for i in items:
        if i.stance == "neutral":
            continue
        w = item_weight(i, params, as_of)
        den += w
        if i.stance == "contradicts":
            num += w
            contra.append((w, i.id))
    p1 = num / den if den > 0 else 0.0
    floor_applied = False
    if facts.heterogeneity_flag is None:
        p1_inputs = (defaulted("heterogeneity_flag", False,
                               "segment heterogeneity has not been analysed yet (produced by later analytics)"),)
    else:
        p1_inputs = (observed("heterogeneity_flag", bool(facts.heterogeneity_flag)),)
        if facts.heterogeneity_flag and p1 < params.segment_divergence_floor_p1:
            p1, floor_applied = params.segment_divergence_floor_p1, True
    top = [{"evidence_id": eid, "weight": round(w, 4)} for w, eid in sorted(contra, key=lambda x: (-x[0], x[1]))[:3]]
    p1_pen = PenaltyScore(p1, p1_inputs,
                          f"Strength-weighted contradiction among direction-bearing evidence, adjusted for evidence quality = {p1:.2f}"
                          + (f" (raised to the segment-divergence floor {params.segment_divergence_floor_p1})." if floor_applied else "."),
                          {"top_contradicting": top, "floor_applied": floor_applied,
                           "contradicting_weight": round(num, 6), "direction_bearing_weight": round(den, 6)})

    # P2 Uncertainty
    ci_parts = []
    for i in items:
        if i.ci_low is not None and i.ci_high is not None and i.effect_size is not None:
            width = i.ci_high - i.ci_low
            if i.effect_size == 0:
                ci_parts.append(params.ci_component_when_effect_zero)
            else:
                ci_parts.append(min(1.0, width / (2 * abs(i.effect_size))))
    ci_comp = sum(ci_parts) / len(ci_parts) if ci_parts else None
    known_n = [i for i in items if i.n_sample is not None]
    small_n = (sum(1 for i in known_n if i.n_sample < params.small_n_threshold) / len(known_n)) if known_n else None
    hhi_norm = None
    if items:
        counts: dict[str, int] = {}
        for i in items:
            counts[i.source_id] = counts.get(i.source_id, 0) + 1
        k = len(counts)
        hhi = sum((c / n) ** 2 for c in counts.values())
        hhi_norm = 1.0 if k == 1 else max(0.0, min(1.0, (hhi - 1 / k) / (1 - 1 / k)))
    parts = P2Parts(ci_comp, small_n, hhi_norm)
    avail = parts.available()
    p2_pen = PenaltyScore(parts.value(), (),
                          "Mean of the available uncertainty components: " + (", ".join(f"{k} {v:.2f}" for k, v in avail.items()) or "none")
                          + f" = {parts.value():.2f}.",
                          {"available_components": list(avail), "components": {k: round(v, 4) for k, v in avail.items()}})

    target = any((i.evidence_type == "behavioral" and i.metric_id == facts.success_metric_id) for i in items) \
        or any(e.primary_metric_id == facts.success_metric_id for e in facts.experiments)
    return Components(
        decision_type=facts.decision_type, dims=dims, applicable=applicable, p1=p1_pen, p2=p2_pen, p2_parts=parts,
        d6_raw=d6_raw, checklist=checklist, types_present=types_present,
        heterogeneity_flag=bool(facts.heterogeneity_flag), success_metric_is_target=target)


__all__ = ["BlockingReason", "Components", "DIMENSION_NAMES", "DimScore", "EvidenceDirection", "Gate", "InputValue",
           "P2Parts", "PenaltyScore", "defaulted", "observed", "applicable_dimensions", "compute_components", "coverage_score", "d6_from_raw",
           "evaluate_gate", "evidence_direction", "freshness_factor", "item_weight", "quality_factor"]
