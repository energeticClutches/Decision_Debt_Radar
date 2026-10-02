"""The deterministic Next Best Evidence (NBE) engine (docs/NBE-spec.md, R8-R11).

    recommend(ddi_result, facts, ddi_params, nbe_params) -> ranked list of Recommendation

Scored state: potential_ddi_reduction = DDI now - DDI assumed, where "DDI assumed" is the DDI engine's result after
raising the targeted dimension(s) to the action's attainable ceiling. This models the potential evidence-strength
improvement if the action succeeds as intended. It never presumes what the evidence will show, is floored at zero,
and actions at or above their ceiling are excluded.

Insufficient state: potential_ddi_reduction = 0 and `blockers_resolved` counts the gating blockers the action addresses.

    priority = relevance * potential_ddi_reduction / effort_days
    (insufficient state: relevance * blockers_resolved / effort_days)

Ranking: priority (unrounded) desc, effort_days asc, action id asc (then data source id). Relevance is rule-based and
uses only information available at assessment time (no Reviewer challenges). The database column
`recommendations.expected_reduction` is mapped from `potential_ddi_reduction` in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.ddi.aggregate import aggregate
from app.domain.ddi.engine import DdiResult
from app.domain.ddi.params import DdiParams
from app.domain.ddi.scoring import Components, P2Parts, compute_components, coverage_score, d6_from_raw
from app.domain.facts import EvidenceFacts, EvidenceItem
from app.domain.nbe.params import NbeAction, NbeParams

FIX_DQ = "fix_dq_or_instrumentation"
HOLDOUT = "powered_holdout_test"
SEGMENT = "segment_level_analysis"
INTERVIEW = "customer_interview_sprint"
SURVEY = "targeted_survey"
EXTEND = "extend_observation_or_refresh_data"
FINANCIAL = "financial_model_with_sensitivity"
REPLICATE = "replicate_independent_source"

NOTE = ("The potential DDI reduction is potential debt reduction under assumptions. It does not predict what the evidence "
        "will show.")
_EPS = 1e-12


@dataclass(frozen=True)
class Recommendation:
    action_id: str
    description: str
    effort_band: str
    effort_days: float
    potential_ddi_reduction: float
    blockers_resolved: int
    relevance: float
    priority: float                       # unrounded, used for ranking
    dimensions_addressed: tuple[str, ...]
    why_this: str
    group: str                            # unblock_scoring | reduce_debt
    data_source_id: str | None = None     # set for fix_dq (one recommendation per affected data source)
    rank: int = 0

    @property
    def priority_rounded(self) -> float:
        return round(self.priority, 4)


def _ddi_value(components: Components, params: DdiParams) -> float:
    p1, p2 = components.p1.score, components.p2.score
    return aggregate(components.scores(), components.applicable, p1, p2, params).capped


def _with(components: Components, dims: dict[str, float] | None = None, p2_parts: P2Parts | None = None) -> Components:
    new_dims = dict(components.dims)
    for d, s in (dims or {}).items():
        new_dims[d] = replace(components.dims[d], score=s)
    kw: dict = {}
    if p2_parts is not None:
        kw = {"p2_parts": p2_parts, "p2": replace(components.p2, score=p2_parts.value())}
    return replace(components, dims=new_dims, **kw)


def _missing_entries(components: Components) -> list[tuple[str, ...]]:
    return [e for e in components.checklist if not any(t in components.types_present for t in e)]


def _supplies_missing(action: NbeAction, components: Components) -> bool:
    t = action.supplies_evidence_type
    return bool(t) and any(t in e for e in _missing_entries(components))


def _d2_with_supply(action: NbeAction, components: Components) -> float | None:
    """D2 after the action supplies a currently-missing checklist type (R9)."""
    if "D2" not in components.applicable or not _supplies_missing(action, components):
        return None
    return coverage_score(components.checklist, set(components.types_present) | {action.supplies_evidence_type})


# ---------------------------------------------------------------- per-action assumed state (scored)


def _assumed(action: NbeAction, comps: Components, ddi: DdiParams, nbe: NbeParams) -> tuple[Components, str] | None:
    """Return (assumed components, why text) or None when the action is not applicable / at its ceiling."""
    a = nbe.applicability
    s = comps.scores()
    app = set(comps.applicable)
    d2 = _d2_with_supply(action, comps)
    dims: dict[str, float] = {}
    p2_parts: P2Parts | None = None
    why = ""

    if action.id == HOLDOUT:
        if "D4" not in app or s["D4"] >= a["holdout_d4_below"]:
            return None
        det = comps.dims["D4"].details
        if det.get("best_design") == "rct" and (det.get("best_power_factor") or 0.0) >= a["holdout_best_power_factor_at_least"]:
            return None
        d4_new = max(s["D4"], action.ceilings["D4"])
        dims["D4"] = d4_new
        if "D6" in app and comps.d6_raw is not None:
            dims["D6"] = d6_from_raw(comps.d6_raw, d4_new, ddi)[0]
        why = (f"Experimental Strength (D4) is {s['D4']:.2f}. A powered holdout could raise it to {d4_new:.2f} "
               f"and lift the observational cap on Behavioral Evidence (D6).")
    elif action.id == SEGMENT:
        if "D6" not in app or not (comps.heterogeneity_flag or s["D6"] < a["segment_d6_below"]):
            return None
        d6_new = max(s["D6"], action.ceilings["D6"])
        dims["D6"] = d6_new
        why = (f"Behavioral Evidence (D6) is {s['D6']:.2f}"
               + (" and a segment-level divergence was flagged" if comps.heterogeneity_flag else "")
               + f". A segment-level analysis could raise it to {d6_new:.2f}.")
    elif action.id in (INTERVIEW, SURVEY):
        key = "customer_interview_d5_below" if action.id == INTERVIEW else "targeted_survey_d5_below"
        if "D5" not in app or s["D5"] >= a[key]:
            return None
        dims["D5"] = max(s["D5"], action.ceilings["D5"])
        why = f"Customer Evidence (D5) is {s['D5']:.2f}. This could raise it to {dims['D5']:.2f}."
    elif action.id == EXTEND:
        ci = comps.p2_parts.ci
        if not (s["D3"] < a["freshness_threshold"] or (ci is not None and ci > a["ci_component_threshold"])):
            return None
        if "D3" in app:
            dims["D3"] = max(s["D3"], action.ceilings["D3"])
        if ci is not None and action.p2_ci_component_multiplier is not None:
            p2_parts = replace(comps.p2_parts, ci=ci * action.p2_ci_component_multiplier)
        why = (f"Evidence Freshness (D3) is {s['D3']:.2f}"
               + (f" and the CI-width component of Uncertainty is {ci:.2f}" if ci is not None else "")
               + ". Extending the window or refreshing data could improve both.")
    elif action.id == FINANCIAL:
        if "D7" not in app or s["D7"] >= a["financial_d7_below"]:
            return None
        dims["D7"] = max(s["D7"], action.ceilings["D7"])
        why = f"Financial / Business Evidence (D7) is {s['D7']:.2f}. A sensitivity-ranged model could raise it to {dims['D7']:.2f}."
    elif action.id == REPLICATE:
        hhi = comps.p2_parts.hhi
        if hhi is None or hhi <= a["concentration_threshold"]:
            return None
        p2_parts = replace(comps.p2_parts, hhi=hhi * action.p2_concentration_component_multiplier)
        why = f"Evidence is concentrated in few sources (normalized concentration {hhi:.2f}). An independent source reduces it."
    else:
        return None
    if d2 is not None and d2 > s["D2"] + _EPS:
        dims["D2"] = d2
        why += f" It also supplies a missing checklist evidence type (D2 {s['D2']:.2f} to {d2:.2f})."
    changed = any(abs(v - s[k]) > _EPS for k, v in dims.items()) or (
        p2_parts is not None and abs(p2_parts.value() - comps.p2_parts.value()) > _EPS)
    if not changed:
        return None                                  # at or above its ceiling: excluded (R9)
    return _with(comps, dims, p2_parts), why


def _dq_sources(facts: EvidenceFacts) -> list[str]:
    """Data sources feeding the evidence or the success metric with an open warn/critical DQ check."""
    feeding = {i.data_source_id for i in facts.items if i.data_source_id}
    if facts.success_metric_data_source_id:
        feeding.add(facts.success_metric_data_source_id)
    return sorted({q.data_source_id for q in facts.dq_issues
                   if q.status == "open" and q.severity in ("warn", "critical") and q.data_source_id in feeding})


def _dq_targets_success_metric(facts: EvidenceFacts, ds: str) -> bool:
    return ds == facts.success_metric_data_source_id or any(
        q.data_source_id == ds and q.affects_metric_id == facts.success_metric_id and q.status == "open"
        for q in facts.dq_issues)


def _with_dq_fixed(facts: EvidenceFacts, ds: str) -> EvidenceFacts:
    fixed: tuple[EvidenceItem, ...] = tuple(replace(i, dq_status="pass") if i.data_source_id == ds else i for i in facts.items)
    return replace(facts, items=fixed)


def _relevance(action: NbeAction, nbe: NbeParams, comps: Components | None, *, targets_success_metric: bool) -> float:
    relevance = nbe.relevance_secondary
    if comps is not None and _supplies_missing(action, comps):
        relevance = max(relevance, nbe.relevance_checklist_gap)
    if targets_success_metric:
        relevance = max(relevance, nbe.relevance_direct)
    return relevance


def rank_recommendations(recs: list[Recommendation]) -> list[Recommendation]:
    recs = sorted(recs, key=lambda r: (-(1 if r.blockers_resolved > 0 else 0), -r.priority, r.effort_days,
                                       r.action_id, r.data_source_id or ""))
    return [replace(r, rank=i + 1) for i, r in enumerate(recs)]


# ---------------------------------------------------------------- public API


def recommend(result: DdiResult, facts: EvidenceFacts | None, ddi: DdiParams, nbe: NbeParams) -> list[Recommendation]:
    if result.scored:
        return _recommend_scored(result, facts, ddi, nbe)
    if facts is None:
        raise ValueError("facts are required to recommend actions for an insufficient-evidence assessment")
    return _recommend_insufficient(result, facts, ddi, nbe)


def _recommend_scored(result: DdiResult, facts: EvidenceFacts | None, ddi: DdiParams, nbe: NbeParams) -> list[Recommendation]:
    comps = result.components
    assert comps is not None
    ddi_now = _ddi_value(comps, ddi)
    out: list[Recommendation] = []
    for action in nbe.actions:
        effort_days = nbe.effort_days(action)
        if action.id == FIX_DQ:
            if facts is None:
                continue
            for ds in _dq_sources(facts):
                affected = [i for i in facts.items if i.data_source_id == ds and i.dq_status != "pass"]
                if not affected:
                    continue                          # nothing below its ceiling
                ddi_assumed = _ddi_value(compute_components(_with_dq_fixed(facts, ds), ddi, result.as_of), ddi)
                potential_ddi_reduction = max(0.0, ddi_now - ddi_assumed)
                relevance = _relevance(action, nbe, comps, targets_success_metric=_dq_targets_success_metric(facts, ds))
                out.append(Recommendation(
                    action.id, action.description, action.effort_band, effort_days, potential_ddi_reduction, 0, relevance,
                    relevance * potential_ddi_reduction / effort_days, ("DQ_GATE", "D1"),
                    f"{len(affected)} evidence item(s) rely on data source {facts.data_source_name(ds)} ({ds}), which has an "
                    f"open data-quality issue. Resolving it restores their data-quality factor to 1.0.",
                    "reduce_debt", ds))
            continue
        assumed = _assumed(action, comps, ddi, nbe)
        if assumed is None:
            continue
        assumed_comps, why = assumed
        potential_ddi_reduction = max(0.0, ddi_now - _ddi_value(assumed_comps, ddi))
        targets = comps.success_metric_is_target and action.id in (HOLDOUT, SEGMENT)
        relevance = _relevance(action, nbe, comps, targets_success_metric=targets)
        out.append(Recommendation(action.id, action.description, action.effort_band, effort_days, potential_ddi_reduction, 0,
                                  relevance, relevance * potential_ddi_reduction / effort_days, action.targets, why,
                                  "reduce_debt"))
    return rank_recommendations(out)


def _recommend_insufficient(result: DdiResult, facts: EvidenceFacts, ddi: DdiParams, nbe: NbeParams) -> list[Recommendation]:
    codes = [r.code for r in result.blocking_reasons]
    types_present = {i.evidence_type for i in facts.items}
    checklist = ddi.coverage_checklists[facts.decision_type]
    missing_entries = [e for e in checklist if not any(t in types_present for t in e)]
    out: list[Recommendation] = []
    for action in nbe.actions:
        effort_days = nbe.effort_days(action)
        if action.id == FIX_DQ:
            if "open_critical_dq" not in codes:
                continue
            reason = next(r for r in result.blocking_reasons if r.code == "open_critical_dq")
            for ds in sorted(reason.detail.get("data_source_ids", [])):
                relevance = _relevance(action, nbe, None, targets_success_metric=_dq_targets_success_metric(facts, ds))
                out.append(Recommendation(
                    action.id, action.description, action.effort_band, effort_days, 0.0, 1, relevance,
                    relevance * 1 / effort_days,
                    ("DQ_GATE",),
                    f"An open critical data-quality issue on data source {facts.data_source_name(ds)} ({ds}) blocks scoring. "
                    f"Resolving it removes the open_critical_dq blocker.", "unblock_scoring", ds))
            continue
        resolved: list[str] = []
        for b in action.resolves_blockers:
            if b not in codes:
                continue
            if not nbe.may_claim_blocker(action, b, codes):      # v0.2 dependency (empty under v0.1)
                continue
            if b == "min_types" and (action.supplies_evidence_type is None or action.supplies_evidence_type in types_present):
                continue
            resolved.append(b)
        if not resolved:
            continue
        direct = "success_metric_evidence" in resolved       # the action targets the success metric's evidence
        relevance = nbe.relevance_direct if direct else nbe.relevance_checklist_gap if action.supplies_evidence_type and \
            action.supplies_evidence_type not in types_present else nbe.relevance_secondary
        out.append(Recommendation(
            action.id, action.description, action.effort_band, effort_days, 0.0, len(resolved), relevance,
            relevance * len(resolved) / effort_days, action.targets,
            f"Addresses {len(resolved)} blocker(s) that prevent scoring: {', '.join(resolved)}.", "unblock_scoring"))
    return rank_recommendations(out)


__all__ = ["NOTE", "Recommendation", "rank_recommendations", "recommend"]
