"""Evidence materialisation service (docs/day-4-implementation-brief.md section 8, D4-16 to D4-21).

The analytics layer writes analysis_results only. This service creates or updates evidence from those analysis results,
through the existing evidence repository and the existing evidence validation.

| analysis                                              | evidence item                                                |
| comparison on the success metric                      | behavioral, metric_id = the success metric, stance by rule   |
| experiment                                            | experiment, experiment_id, analysis_id, stance by rule       |
| trend on the success metric                           | behavioral, metric_id NULL, stance always neutral (descriptive) |
| funnel                                                | behavioral, metric_id NULL, stance always neutral (descriptive) |
| segmentation, evidence comparison                     | none (segmentation feeds heterogeneity_flag only)            |

Descriptive evidence (trend, funnel; no effect size) is NOT linked to the success metric: evidence.metric_id is NULL, so the
frozen DDI D6 selection (behavioral evidence whose metric_id is the success metric) excludes it (Day 4.1, option (a)). The metric
it describes stays traceable through analysis_id (the analysis row records the metric) and is named in the summary. The identity
below is unaffected: it uses the analysed metric taken from the analysis, never evidence.metric_id.

Identity: analysis_identity = sha256(decision | analysis_type | metric_id | experiment-or-segment-or-cohort key |
analysis_params_hash). The source fingerprint is NOT part of it. With the same identity: if the values differ the active evidence
is updated in place (summary, n, effect, CI, grade, stance, observed_end, source_fingerprint, analysis_id), which triggers the
Day-3 stale rule; if nothing differs nothing is written and the decision is NOT marked stale. A new identity (the parameters
changed) inserts new evidence and marks the old item superseded (superseded_by and superseded_at set, never deleted).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.analytics import stats
from app.analytics.config import AnalyticsParams, TenantConfig
from app.core.params import get_analytics_params, get_tenant_config
from app.db.models import AnalysisResult, Decision
from app.domain.canvas import validate_evidence
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.repositories import analysis as analysis_repo
from app.repositories import audit as audit_repo
from app.repositories import evidence as evidence_repo
from app.services.base import ServiceContext, unit_of_work
from app.services.lifecycle import LifecycleHelpers

EVIDENCE_ANALYSES = ("comparison", "trend", "funnel", "experiment")
COMPARED_FIELDS = ("summary", "n_sample", "effect_size", "ci_low", "ci_high", "strength_grade", "stance", "observed_end",
                   "source_fingerprint")


def _num(x: float | Decimal | None) -> Decimal | None:
    return None if x is None else Decimal(format(round(float(x), 10), ".10f"))


@dataclass
class MaterializationSummary:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    superseded: int = 0
    skipped: int = 0
    items: list[dict] = field(default_factory=list)
    stale: bool = False

    def as_dict(self) -> dict:
        return {"created": self.created, "updated": self.updated, "unchanged": self.unchanged, "superseded": self.superseded,
                "skipped_without_evidence": self.skipped, "items": self.items, "marked_stale": self.stale}


# ---------------------------------------------------------------- deterministic summary templates
def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _spct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def _group_text(defn: Mapping) -> tuple[str, str]:
    if defn.get("type") == "event_users":
        extra = ", excluding experiment participants" if defn.get("exclude_experiment_participants") else ""
        return f"users with {defn['treatment_event']}{extra}", "all other users"
    pop = defn.get("population") or {}
    where = f" in {pop['column']} = {pop['value']}" if pop else ""
    return f"signups on or after {defn['split_date']}{where}", f"signups before {defn['split_date']}{where}"


def summary_text(analysis_type: str, result: Mapping[str, Any], metric_name: str | None = None) -> str:
    if analysis_type == "comparison":
        t, c = result["treatment"], result["comparison"]
        tg, cg = _group_text(result["group_definition"])
        return (f"{result['metric']}: {tg} {_pct(t['rate'])} (n={t['n']}) vs {cg} {_pct(c['rate'])} (n={c['n']}); difference "
                f"{_spct(result['effect'])} (95% CI {_spct(result['ci_low'])} to {_spct(result['ci_high'])}). "
                "Observational comparison, not randomised.")
    if analysis_type == "trend":
        prior = (f" vs {_pct(result['prior_value'])} before ({_spct(result['change_recent_vs_prior'])})"
                 if result.get("prior_value") is not None else "")
        return (f"{result['metric']} by signup week, {result['first_week']} to {result['last_week']}: "
                f"{_pct(result['recent_value'])} over the last {result['recent_weeks']} weeks{prior}. Descriptive, no test.")
    if analysis_type == "funnel":
        steps = "; ".join(f"{s['step']} {_pct(s['share_of_cohort'])}" for s in result["overall"])
        context = f" Descriptive context for the metric {metric_name}." if metric_name else ""
        return (f"Funnel {result['funnel']} for {result['cohort_users']} signups ({result['cohort_window'][0]} to "
                f"{result['cohort_window'][1]}): {steps}. Descriptive.{context}")
    if analysis_type == "experiment":
        v = result["variants"]
        c, t = result["control_variant"], result["treatment_variant"]
        srm = result.get("srm")
        srm_text = ("SRM not checked" if srm is None else
                    f"SRM {'FAILED' if srm['flag'] else 'passed'} (p={srm['p_value']:.3g})")
        power = result["design_power"]["value"]
        power_text = "design power at the pre-registered MDE not computed" if power is None else (
            f"design power at the pre-registered MDE {power:.2f}")
        return (f"{result['experiment_name']}: {t} {v[t]['metric_value']:.3g} vs {c} {v[c]['metric_value']:.3g} on "
                f"{result['outcome_key']} (n={result['n']}); effect {result['effect']:+.3g} (95% CI {result['ci_low']:+.3g} to "
                f"{result['ci_high']:+.3g}); {srm_text}; {power_text}.")
    raise ValueError(f"no evidence template for analysis type {analysis_type!r}")


# ---------------------------------------------------------------- candidate
@dataclass(frozen=True)
class Candidate:
    analysis: AnalysisResult
    evidence_type: str
    stance: str
    grade: str
    summary: str
    observed_start: date
    observed_end: date
    n_sample: int | None
    effect_size: float | None
    ci_low: float | None
    ci_high: float | None
    metric_id: uuid.UUID | None
    experiment_id: uuid.UUID | None
    evidence_source_id: uuid.UUID


def build_candidate(analysis: AnalysisResult, decision: Decision, *, params: AnalyticsParams, tenant: TenantConfig,
                    evidence_source_id: uuid.UUID, as_of: date) -> Candidate:
    res = analysis.result or {}
    t = analysis.analysis_type
    is_experiment = t == "experiment"
    comparative = t in ("comparison", "experiment")
    stance = "neutral"
    effect = ci_low = ci_high = None
    if comparative:
        effect, ci_low, ci_high = res.get("effect"), res.get("ci_low"), res.get("ci_high")
        stance = stats.stance_for(effect=effect, ci_low=ci_low, ci_high=ci_high, materiality=res.get("materiality"),
                                  expected_direction=decision.expected_direction)
    srm = res.get("srm") or {}
    power = (res.get("design_power") or {}).get("value") if is_experiment else None
    grade = stats.strength_grade(
        grading=params.grading, item_dq=analysis.dq_status or "pass", n=analysis.n, is_experiment=is_experiment,
        design=res.get("design") if is_experiment else None, srm_flag=srm.get("flag") if is_experiment and srm else None,
        design_power=power, ci_width=res.get("ci_width") if is_experiment else None, mde=res.get("mde") if is_experiment else None)
    start = date.fromisoformat(res["observed_start"])
    end = min(date.fromisoformat(res["observed_end"]), as_of)          # the analysis window ends at or before the as-of date
    start = min(start, end)
    return Candidate(
        analysis=analysis, evidence_type="experiment" if is_experiment else "behavioral", stance=stance, grade=grade,
        summary=summary_text(t, res, (analysis.params or {}).get("metric_name")), observed_start=start, observed_end=end, n_sample=analysis.n, effect_size=effect,
        ci_low=ci_low, ci_high=ci_high,
        metric_id=decision.success_metric_id if t == "comparison" else None,      # descriptive (trend, funnel) and experiment: NULL
        experiment_id=uuid.UUID(res["experiment_id"]) if is_experiment else None, evidence_source_id=evidence_source_id)


# ---------------------------------------------------------------- the service
class EvidenceMaterializationService(LifecycleHelpers):
    def __init__(self, ctx: ServiceContext):
        super().__init__(ctx)
        self.params = ctx.analytics_params or get_analytics_params()
        self.tenant = ctx.tenant or get_tenant_config()

    def materialize(self, actor, decision_id, analysis_ids: Sequence[uuid.UUID | str], *,
                    agent_run_id: uuid.UUID | None = None) -> MaterializationSummary:
        """Stand-alone entry point (own transaction). The pipeline calls `apply` inside its stage transaction."""
        from app.domain import permissions as perm
        perm.authorize_role(actor, perm.RUN_ASSESSMENT)
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            return self.apply(decision, analysis_ids, agent_run_id=agent_run_id)

    def apply(self, decision: Decision, analysis_ids: Iterable[uuid.UUID | str], *, agent_run_id: uuid.UUID | None = None) -> MaterializationSummary:
        if decision.lifecycle_stage == "decided":
            raise StateConflict("The decision is decided: evidence can no longer be generated.")
        out = MaterializationSummary()
        as_of = self.clock.today()
        for raw_id in analysis_ids:
            aid = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
            analysis = analysis_repo.get_analysis(self.session, aid)
            if analysis is None or analysis.decision_id != decision.id:
                raise NotFound("Analysis not found for this decision.", detail={"analysis_id": str(raw_id)})
            if analysis.analysis_type not in EVIDENCE_ANALYSES:
                out.skipped += 1                        # segmentation (and any evidence comparison) create no evidence
                continue
            primary = (analysis.params or {}).get("primary_source_view")
            ref = self.tenant.data_source_ref(primary)
            source = evidence_repo.evidence_source_by_ref(self.session, decision.org_id, ref)
            if source is None:
                raise InvalidInput(f"No evidence source is registered for {ref}.", detail={"ref": ref})
            cand = build_candidate(analysis, decision, params=self.params, tenant=self.tenant, evidence_source_id=source.id, as_of=as_of)
            self._apply_candidate(decision, cand, agent_run_id, out)
        if out.created or out.updated or out.superseded:
            out.stale = self.mark_stale_system(decision, "evidence generated or changed after the assessment")
        return out

    # ---- one candidate
    def _fields(self, c: Candidate) -> dict[str, Any]:
        return dict(summary=c.summary, stance=c.stance, strength_grade=c.grade, evidence_type=c.evidence_type,
                    observed_start=c.observed_start, observed_end=c.observed_end, n_sample=c.n_sample, effect_size=c.effect_size,
                    ci_low=c.ci_low, ci_high=c.ci_high)

    def _apply_candidate(self, decision: Decision, c: Candidate, agent_run_id, out: MaterializationSummary) -> None:
        analysis = c.analysis
        identity = analysis.analysis_identity
        validate_evidence(self._fields(c))
        active = evidence_repo.get_active_by_identity(self.session, decision.id, identity)
        if active is not None:
            new = {"summary": c.summary, "n_sample": c.n_sample, "effect_size": _num(c.effect_size), "ci_low": _num(c.ci_low),
                   "ci_high": _num(c.ci_high), "strength_grade": c.grade, "stance": c.stance, "observed_end": c.observed_end,
                   "source_fingerprint": analysis.source_fingerprint}
            old = {k: (_num(getattr(active, k)) if k in ("effect_size", "ci_low", "ci_high") else getattr(active, k)) for k in COMPARED_FIELDS}
            diff = {k: v for k, v in new.items() if old[k] != v}
            if not diff:
                out.unchanged += 1
                out.items.append({"analysis_type": analysis.analysis_type, "evidence_id": str(active.id), "action": "unchanged",
                                  "stance": active.stance, "strength_grade": active.strength_grade})
                return
            before = {k: (float(old[k]) if isinstance(old[k], Decimal) else (old[k].isoformat() if isinstance(old[k], date) else old[k]))
                      for k in diff}
            for k, v in diff.items():
                setattr(active, k, float(v) if isinstance(v, Decimal) else v)
            active.analysis_id = analysis.id
            active.agent_run_id = agent_run_id
            self.session.flush()
            self.session.refresh(active)
            audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="evidence.updated",
                                 entity_type="evidence", entity_id=active.id, decision_id=decision.id, before=before,
                                 after={"changed": sorted(diff), "analysis_id": str(analysis.id), "generated": True},
                                 is_synthetic=decision.is_synthetic)
            out.updated += 1
            out.items.append({"analysis_type": analysis.analysis_type, "evidence_id": str(active.id), "action": "updated",
                              "stance": active.stance, "strength_grade": active.strength_grade, "changed": sorted(diff)})
            return
        slot = (analysis.params or {}).get("slot")
        old_items = evidence_repo.active_in_slot(self.session, decision.id, slot, except_identity=identity) if slot else []
        ev = evidence_repo.add_evidence(
            self.session, decision_id=decision.id, evidence_source_id=c.evidence_source_id, analysis_id=analysis.id,
            metric_id=c.metric_id, experiment_id=c.experiment_id, created_by="agent", agent_run_id=agent_run_id,
            is_synthetic=decision.is_synthetic, analysis_identity=identity, source_fingerprint=analysis.source_fingerprint,
            **self._fields(c))
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="evidence.generated",
                             entity_type="evidence", entity_id=ev.id, decision_id=decision.id, before=None,
                             after={"analysis_id": str(analysis.id), "analysis_type": analysis.analysis_type, "stance": ev.stance,
                                    "strength_grade": ev.strength_grade, "evidence_type": ev.evidence_type},
                             is_synthetic=decision.is_synthetic)
        out.created += 1
        out.items.append({"analysis_type": analysis.analysis_type, "evidence_id": str(ev.id), "action": "created",
                          "stance": ev.stance, "strength_grade": ev.strength_grade})
        for old in old_items:
            old.status = "superseded"
            old.superseded_by = ev.id
            old.superseded_at = func.clock_timestamp()
            self.session.flush()
            self.session.refresh(old)
            audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="evidence.superseded",
                                 entity_type="evidence", entity_id=old.id, decision_id=decision.id,
                                 before={"status": "active"}, after={"status": "superseded", "superseded_by": str(ev.id),
                                                                      "reason": "analysis parameters changed"},
                                 is_synthetic=decision.is_synthetic)
            out.superseded += 1
            out.items.append({"analysis_type": analysis.analysis_type, "evidence_id": str(old.id), "action": "superseded",
                              "superseded_by": str(ev.id)})


__all__ = ["Candidate", "EVIDENCE_ANALYSES", "EvidenceMaterializationService", "MaterializationSummary", "build_candidate",
           "summary_text"]
