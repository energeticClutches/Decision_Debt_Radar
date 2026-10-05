"""Pipeline: stages 1, 2 and 4 of the seven-stage design plus materialisation and the Day-3 assessment
(docs/day-4-implementation-brief.md section 10), and since Day 5 the LLM boundary: Stage 3 customer evidence (classification and
proposal, docs/day-5-implementation-brief.md section 5), then Stage 5 synthesis and Stage 6 review after the assessment.
`agent_runs.agent_name` records data_analytics and orchestrator with model = NULL for the deterministic stages; every LLM call
writes its own row (evidence_synthesis or reviewer) with the model, prompt hash and call metadata.

    run_pipeline(actor, decision_id)      precondition: the decision is at stage evidence_gathered
      1. data quality (commit)
      2. quantitative analyses, skipped for the success metric while an open critical DQ check affects it (commit)
      3. customer evidence (Day 5): LLM classification, deterministic aggregation, PROPOSED evidence (only human-approved active
         evidence enters the assessment). Without an LlmClient the stage is recorded as skipped_no_llm_client
      4. experiment analysis (commit)
      5. evidence materialisation (commit)
      6. the Day-3 assessment run (unchanged service and transaction)
      7. synthesis and review (Day 5, only with an LlmClient): after the assessment is stored. A synthesis or review failure never
         changes the assessment or the DDI and never counts as a review pass (D5-08); the decision then stays `assessed`

Each stage writes one agent_runs row. If a stage raises: its transaction is rolled back, a `partial` assessment with
blocking_reasons = [{"code": "stage_failed", "stage", "message"}] is inserted (assessment metadata still recorded), a failed
agent_runs row is written, and the pipeline stops. The decision stays at evidence_gathered.

Determinism: the as-of date is injected (the clock), nothing in the analytics reads the wall clock. Only latency is measured
with a monotonic timer and it is stored in agent_runs.latency_ms only.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.analytics import analyses as analyses_mod
from app.analytics import dq as dq_mod
from app.analytics import dq_store
from app.analytics import experiments as exp_mod
from app.analytics import store as analysis_store
from app.analytics.analyses import AnalysisDraft, DecisionInfo
from app.analytics.executor import ReadOnlyExecutor
from app.core.params import get_analytics_params, get_tenant_config
from app.db.models import AgentRun, Decision, DecisionAssessment
from app.domain import permissions as perm
from app.domain.errors import DomainError, InvalidInput, StateConflict
from app.domain.permissions import Actor
from app.repositories import agent_runs as runs_repo
from app.repositories import assessments as assessments_repo
from app.repositories import decisions as decisions_repo
from app.repositories import dq as dq_repo
from app.repositories import evidence as evidence_repo
from app.repositories import experiments as experiments_repo
from app.repositories.evidence_facts import evidence_fingerprint
from app.services.assessments import AssessmentService
from app.services.customer_evidence import CustomerEvidenceService
from app.services.base import ServiceContext, unit_of_work
from app.services.evidence_materialization import EvidenceMaterializationService
from app.services.lifecycle import LifecycleHelpers
from app.services.synthesis import ReviewerService, SynthesisService

PIPELINE_STAGES = ("dq", "quant", "customer", "experiment", "materialize", "assessment", "synthesis", "review")


class _StageFailure(Exception):
    def __init__(self, stage: str, exc: Exception):
        super().__init__(f"{stage}: {exc}")
        self.stage = stage
        self.exc = exc


@dataclass
class PipelineResult:
    decision_id: uuid.UUID
    stages: list[dict] = field(default_factory=list)
    assessment: DecisionAssessment | None = None
    partial: bool = False
    failed_stage: str | None = None
    error: str | None = None
    analysis_ids: list[uuid.UUID] = field(default_factory=list)
    # Day 5
    synthesis: dict | None = None
    review: dict | None = None
    pending_approvals: list[dict] = field(default_factory=list)


class PipelineService(LifecycleHelpers):
    def __init__(self, ctx: ServiceContext, *, executor: ReadOnlyExecutor | None = None):
        super().__init__(ctx)
        self.params = ctx.analytics_params or get_analytics_params()
        self.tenant = ctx.tenant or get_tenant_config()
        self.executor = executor or ctx.executor or ReadOnlyExecutor(max_rows=self.params.max_rows,
                                                                    statement_timeout=self.params.statement_timeout)
        self.materializer = EvidenceMaterializationService(ctx)
        self._ds_cache: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

    # ================================================================ helpers
    def _decision_info(self, decision: Decision) -> DecisionInfo:
        metric = decisions_repo.get_metric(self.session, decision.success_metric_id)
        exps = experiments_repo.list_for_decision(self.session, decision.id)
        return DecisionInfo(decision_id=str(decision.id), scenario_key=decision.scenario_key, metric_name=metric.name,
                            metric_id=str(metric.id), expected_direction=decision.expected_direction,
                            experiment_keys=tuple(sorted(e.source_ref for e in exps if e.source_ref)))

    def _data_source_id(self, org_id: uuid.UUID, ref: str) -> uuid.UUID:
        key = (org_id, ref)
        if key not in self._ds_cache:
            source = evidence_repo.evidence_source_by_ref(self.session, org_id, ref)
            if source is None or source.data_source_id is None:
                raise InvalidInput(f"No registered data source for {ref}.", detail={"ref": ref})
            self._ds_cache[key] = source.data_source_id
        return self._ds_cache[key]

    def _base_input(self, decision: Decision) -> dict[str, Any]:
        return {"decision_id": str(decision.id), "as_of": self.clock.today().isoformat(),
                "analytics_params": {"version": self.params.version, "hash": self.params.content_hash},
                "tenant_config": {"version": self.tenant.version, "hash": self.tenant.content_hash}}

    def _dq_status_for(self, decision: Decision, draft: AnalysisDraft) -> tuple[str, str]:
        """Worst severity of the decision's open or accepted DQ checks on the data sources the analysis read, and a note."""
        ds_ids = {self._data_source_id(decision.org_id, self.tenant.data_source_ref(v)) for v in draft.source_views}
        relevant = [c for c in dq_repo.list_for_decision(self.session, decision.id)
                    if c.data_source_id in ds_ids and c.status != "resolved" and c.severity != "pass"]
        worst = "pass"
        for c in relevant:
            if dq_mod.SEVERITY_ORDER[c.severity] > dq_mod.SEVERITY_ORDER[worst]:
                worst = c.severity
        if not relevant:
            return "pass", "Data quality: no open or accepted warn or critical finding on the data read."
        n_warn = sum(1 for c in relevant if c.severity == "warn")
        n_crit = sum(1 for c in relevant if c.severity == "critical")
        targets = ", ".join(f"{c.target} ({c.severity})" for c in sorted(relevant, key=lambda c: (-dq_mod.SEVERITY_ORDER[c.severity], c.target))[:5])
        more = f" and {len(relevant) - 5} more" if len(relevant) > 5 else ""
        return worst, (f"Data quality: {n_crit} critical and {n_warn} warn finding(s) are open or accepted on the data read "
                       f"({targets}{more}).")

    # ================================================================ stage runner
    def _run_stage(self, actor: Actor, decision_id, stage: str, agent_name: str, enum: str | None,
                   fn: Callable[[Decision, AgentRun], tuple[dict, str]], result: PipelineResult) -> dict:
        t0 = time.perf_counter()
        try:
            with unit_of_work(self.session):
                decision = self.decision_or_404(actor, decision_id, lock=True)
                if decision.lifecycle_stage != "evidence_gathered":
                    raise StateConflict(f"The pipeline can only run from stage 'evidence_gathered' (the decision is "
                                        f"'{decision.lifecycle_stage}').", detail={"lifecycle_stage": decision.lifecycle_stage})
                run = runs_repo.add_run(self.session, decision_id=decision.id, stage=enum, agent_name=agent_name, status="running",
                                        input={**self._base_input(decision), "pipeline_stage": stage}, model=None, prompt_version=None,
                                        is_synthetic=decision.is_synthetic)
                try:
                    output, status = fn(decision, run)
                except Exception as exc:  # noqa: BLE001 (any failure of the stage becomes a partial assessment)
                    raise _StageFailure(stage, exc) from exc
                run.output = {"pipeline_stage": stage, **output}
                run.status = status
                run.latency_ms = int((time.perf_counter() - t0) * 1000)
                self.session.flush()
                info = {"stage": stage, "agent_name": agent_name, "status": status, "agent_run_id": str(run.id), "output": run.output}
        except _StageFailure as failure:
            self._record_failure(actor, decision_id, failure, agent_name, enum, int((time.perf_counter() - t0) * 1000), result)
            raise
        result.stages.append(info)
        return info

    def _record_failure(self, actor: Actor, decision_id, failure: _StageFailure, agent_name: str, enum: str | None, latency_ms: int,
                        result: PipelineResult) -> None:
        message = str(failure.exc)[:500] or type(failure.exc).__name__
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            fingerprint = evidence_fingerprint(self.session, decision.id)
            version = assessments_repo.max_version(self.session, decision.id) + 1
            reason = {"code": "stage_failed", "stage": failure.stage, "message": message}
            partial = assessments_repo.add_assessment(
                self.session, decision_id=decision.id, version=version, state="partial", ddi_score=None, ddi_band=None,
                dimension_scores={}, penalty_scores={}, blocking_reasons=[reason], sensitivity={},
                params_version=self.ctx.ddi_params.version, params_hash=self.ctx.ddi_params.content_hash,
                nbe_params_version=self.ctx.nbe_params.version, nbe_params_hash=self.ctx.nbe_params.content_hash,
                evidence_fingerprint=fingerprint, as_of_date=self.clock.today(),
                narrative=f"PARTIAL ASSESSMENT: pipeline stage '{failure.stage}' failed ({message}). No score is shown.",
                is_synthetic=decision.is_synthetic)
            run = runs_repo.add_run(self.session, decision_id=decision.id, assessment_id=partial.id, stage=enum, agent_name=agent_name,
                                    status="failed", input={**self._base_input(decision), "pipeline_stage": failure.stage},
                                    output={"pipeline_stage": failure.stage, "outcome": "failed"}, model=None, prompt_version=None,
                                    latency_ms=latency_ms, error=message, is_synthetic=decision.is_synthetic)
            self.audit(actor, "pipeline.stage_failed", "assessment", partial.id, decision,
                       before={"lifecycle_stage": decision.lifecycle_stage},
                       after={"stage": failure.stage, "message": message, "assessment_id": str(partial.id), "version": version,
                              "agent_run_id": str(run.id), "lifecycle_stage": decision.lifecycle_stage})
            result.assessment = partial
            result.partial = True
            result.failed_stage = failure.stage
            result.error = message
            result.stages.append({"stage": failure.stage, "agent_name": agent_name, "status": "failed", "agent_run_id": str(run.id),
                                  "output": run.output, "error": message})

    # ================================================================ stage implementations (each returns (output, status))
    def stage_dq(self, decision: Decision, run: AgentRun) -> tuple[dict, str]:
        info = self._decision_info(decision)
        plan = dq_mod.plan_for(self.tenant, metric_name=info.metric_name, scenario_key=info.scenario_key,
                               linked_experiments=bool(info.experiment_keys))
        dq_run = dq_mod.run_checks(self.executor, self.params, self.tenant, plan, self.clock.today())
        refs = sorted({f.data_source_ref for f in dq_run.findings})
        ds_ids = {r: self._data_source_id(decision.org_id, r) for r in refs}
        summary = dq_store.reconcile(self.session, decision, dq_run.findings, data_source_ids=ds_ids, now=self.clock.now())
        if summary.status_changed:
            self.mark_stale_system(decision, "data-quality status changed after the assessment")
        non_pass = [{"check_key": dq_store.check_key(ds_ids[f.data_source_ref], f), "check_type": f.check_type, "target": f.target,
                     "severity": f.severity, "observed_value": f.observed_value, "threshold": f.threshold}
                    for f in dq_run.findings if f.severity != "pass"]
        return ({"outcome": "completed", "counts": dq_mod.summarize(dq_run.findings), "reconcile": summary.as_dict(),
                 "windows": dq_run.windows.as_dict() if dq_run.windows else None, "notes": dq_run.notes, "non_pass": non_pass},
                "succeeded")

    def _blocking_checks(self, decision: Decision):
        return [c for c in dq_repo.list_for_decision(self.session, decision.id)
                if c.status == "open" and c.severity == "critical" and c.affects_success_metric]

    def stage_quant(self, decision: Decision, run: AgentRun, analysis_ids: list[uuid.UUID]) -> tuple[dict, str]:
        info = self._decision_info(decision)
        metric_cfg = self.tenant.metric(info.metric_name)
        if metric_cfg is None:
            return {"outcome": "no_configured_analyses", "analyses": [], "skipped": []}, "succeeded"
        spec = self.tenant.decision_analyses(info.scenario_key)
        planned = (["comparison", "segmentation"] if spec.get("comparison") else []) + ["trend"] + (["funnel"] if spec.get("funnel") else [])
        blocked = self._blocking_checks(decision)
        if blocked:
            ids = sorted(str(c.id) for c in blocked)
            return ({"outcome": "blocked", "analyses": [],
                     "skipped": [{"analysis": a, "status": "skipped (blocked)", "reason": "open_critical_dq", "dq_check_ids": ids}
                                 for a in planned]}, "partial")
        as_of = self.clock.today()
        drafts: list[AnalysisDraft] = []
        drafts.extend(analyses_mod.comparison_analyses(self.executor, self.params, self.tenant, info, as_of))
        trend = analyses_mod.trend_analysis(self.executor, self.params, self.tenant, info, as_of)
        if trend:
            drafts.append(trend)
        funnel = analyses_mod.funnel_analysis(self.executor, self.params, self.tenant, info, as_of)
        if funnel:
            drafts.append(funnel)
        produced = []
        for draft in drafts:
            dq_status, dq_note = self._dq_status_for(decision, draft)
            stored = analysis_store.persist(self.session, decision, draft, params=self.params, tenant=self.tenant, dq_status=dq_status,
                                            dq_note=dq_note, as_of=as_of, agent_run_id=run.id)
            analysis_ids.append(stored.row.id)
            produced.append({"analysis_type": draft.analysis_type, "analysis_id": str(stored.row.id), "reused": stored.reused,
                             "dq_status": dq_status, "n": draft.n, "creates_evidence": draft.creates_evidence,
                             **({"heterogeneity_flag": draft.extra.get("flag")} if draft.analysis_type == "segmentation" else {})})
        return {"outcome": "completed", "analyses": produced, "skipped": []}, "succeeded"

    def stage_customer(self, decision: Decision, run: AgentRun) -> tuple[dict, str]:
        if self.ctx.llm is None:
            return ({"outcome": "skipped_no_llm_client",
                     "reason": "no LlmClient is configured (set ANTHROPIC_API_KEY); no customer evidence was classified or proposed"},
                    "succeeded")
        return CustomerEvidenceService(self.ctx, executor=self.executor).run_stage(decision, run, client=self.ctx.llm)

    def stage_experiment(self, decision: Decision, run: AgentRun, analysis_ids: list[uuid.UUID]) -> tuple[dict, str]:
        info = self._decision_info(decision)
        experiments = experiments_repo.list_for_decision(self.session, decision.id)
        blocked = self._blocking_checks(decision)
        as_of = self.clock.today()
        produced, skipped = [], []
        for exp in experiments:
            if blocked and exp.primary_metric_id == decision.success_metric_id:
                skipped.append({"experiment": exp.name, "status": "skipped (blocked)", "reason": "open_critical_dq",
                                "dq_check_ids": sorted(str(c.id) for c in blocked)})
                continue
            spec = exp_mod.ExperimentSpec(
                id=str(exp.id), name=exp.name, design=exp.design, source_ref=exp.source_ref, control_variant=exp.control_variant,
                outcome_key=exp.outcome_key,
                planned_treatment_share=float(exp.planned_treatment_share) if exp.planned_treatment_share is not None else None,
                mde=float(exp.mde) if exp.mde is not None else None, planned_sample=exp.planned_sample, start_date=exp.start_date,
                end_date=exp.end_date, primary_metric_id=str(exp.primary_metric_id) if exp.primary_metric_id else None)
            rank = self.ctx.ddi_params.design_rank.get(exp.design)
            draft, analysis = analyses_mod.experiment_draft(self.executor, self.params, self.tenant, info, spec, design_rank=rank)
            experiments_repo.upsert_results(self.session, exp, exp_mod.experiment_results_rows(analysis))
            dq_status, dq_note = self._dq_status_for(decision, draft)
            stored = analysis_store.persist(self.session, decision, draft, params=self.params, tenant=self.tenant, dq_status=dq_status,
                                            dq_note=dq_note, as_of=as_of, agent_run_id=run.id)
            analysis_ids.append(stored.row.id)
            d = analysis.difference
            produced.append({"experiment_id": str(exp.id), "analysis_id": str(stored.row.id), "reused": stored.reused,
                             "effect": d.effect, "ci_low": d.ci_low, "ci_high": d.ci_high, "p_value": d.p_value,
                             "srm_flag": analysis.srm.flag if analysis.srm else None, "srm_chi2": analysis.srm.chi2 if analysis.srm else None,
                             "srm_p_value": analysis.srm.p_value if analysis.srm else None, "design_power": analysis.design_power,
                             "dq_status": dq_status})
        status = "partial" if skipped else "succeeded"
        return {"outcome": "completed" if not skipped else "blocked", "experiments": produced, "skipped": skipped}, status

    def stage_materialize(self, decision: Decision, run: AgentRun, analysis_ids: list[uuid.UUID]) -> tuple[dict, str]:
        summary = self.materializer.apply(decision, analysis_ids, agent_run_id=run.id)
        return {"outcome": "completed", **summary.as_dict()}, "succeeded"

    # ================================================================ the run
    def run(self, actor: Actor, decision_id) -> PipelineResult:
        perm.authorize_role(actor, perm.RUN_ASSESSMENT)
        decision = self.decision_or_404(actor, decision_id)
        if decision.lifecycle_stage != "evidence_gathered":
            raise StateConflict(
                f"The pipeline can only run from stage 'evidence_gathered' (the decision is '{decision.lifecycle_stage}'). Confirm the "
                f"evidence base, or add/change evidence after a previous assessment, first.",
                detail={"lifecycle_stage": decision.lifecycle_stage})
        result = PipelineResult(decision_id=decision.id)
        analysis_ids: list[uuid.UUID] = []
        try:
            self._run_stage(actor, decision_id, "dq", "data_analytics", "dq", self.stage_dq, result)
            self._run_stage(actor, decision_id, "quant", "data_analytics", "quant",
                            lambda d, r: self.stage_quant(d, r, analysis_ids), result)
            self._run_stage(actor, decision_id, "customer", "orchestrator", "customer", self.stage_customer, result)
            self._run_stage(actor, decision_id, "experiment", "data_analytics", "experiment",
                            lambda d, r: self.stage_experiment(d, r, analysis_ids), result)
            self._run_stage(actor, decision_id, "materialize", "orchestrator", None,
                            lambda d, r: self.stage_materialize(d, r, analysis_ids), result)
        except _StageFailure:
            result.analysis_ids = list(analysis_ids)
            return result
        result.analysis_ids = list(analysis_ids)
        t0 = time.perf_counter()
        try:
            assessment = AssessmentService(self.ctx).run(actor, decision_id)          # unchanged Day-3 service and transaction
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            failure = _StageFailure("assessment", exc)
            self._record_failure(actor, decision_id, failure, "orchestrator", None, int((time.perf_counter() - t0) * 1000), result)
            return result
        result.assessment = assessment
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            run = runs_repo.add_run(
                self.session, decision_id=decision.id, assessment_id=assessment.id, stage=None, agent_name="orchestrator",
                status="succeeded", input={**self._base_input(decision), "pipeline_stage": "assessment"},
                output={"pipeline_stage": "assessment", "assessment_id": str(assessment.id), "version": assessment.version,
                        "state": assessment.state, "blocking_codes": [r.get("code") for r in (assessment.blocking_reasons or [])]},
                model=None, prompt_version=None, latency_ms=int((time.perf_counter() - t0) * 1000), is_synthetic=decision.is_synthetic)
            result.stages.append({"stage": "assessment", "agent_name": "orchestrator", "status": "succeeded", "agent_run_id": str(run.id),
                                  "output": run.output})
        self._llm_stages(actor, decision_id, assessment, result)
        return result

    # ================================================================ Day 5: synthesis and review after the assessment
    def _llm_stages(self, actor: Actor, decision_id, assessment: DecisionAssessment, result: PipelineResult) -> None:
        """Stage 5 and Stage 6. Every failure is recorded and returned as a status. The assessment is already committed and is
        never touched here, so the DDI is unchanged whatever happens (D5-08)."""
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id)
            result.pending_approvals = CustomerEvidenceService(self.ctx, executor=self.executor).pending_approvals(decision)
        if self.ctx.llm is None:
            note = {"status": "not_run", "reason": "no LlmClient is configured"}
            result.synthesis, result.review = dict(note), dict(note)
            return
        try:
            syn = SynthesisService(self.ctx).synthesize(actor, assessment.id, authorize=False)
        except Exception as exc:  # noqa: BLE001  (an LLM stage must never turn a stored assessment into an error)
            self.session.rollback()
            result.synthesis = {"status": "failed", "error_class": getattr(exc, "code", type(exc).__name__), "error": str(exc)[:300]}
            result.review = {"status": "skipped", "reason": "no succeeded synthesis to review"}
            result.stages.append({"stage": "synthesis", "agent_name": "evidence_synthesis", "status": "failed", "output": result.synthesis})
            return
        result.synthesis = syn.summary()
        result.stages.append({"stage": "synthesis", "agent_name": "evidence_synthesis",
                              "status": "succeeded" if syn.status == "succeeded" else "failed",
                              "agent_run_id": None if syn.synthesis is None else str(syn.synthesis.agent_run_id), "output": result.synthesis})
        if syn.status != "succeeded":
            result.review = {"status": "skipped", "reason": f"the synthesis is '{syn.status}': there is nothing to review. "
                                                             "A human review (with a reason) is required"}
            return
        try:
            rev = ReviewerService(self.ctx).review(actor, syn.synthesis.id, authorize=False)
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            result.review = {"status": "failed", "error_class": getattr(exc, "code", type(exc).__name__), "error": str(exc)[:300]}
            result.stages.append({"stage": "review", "agent_name": "reviewer", "status": "failed", "output": result.review})
            return
        result.review = rev.summary()
        result.stages.append({"stage": "review", "agent_name": "reviewer", "status": "succeeded" if rev.status == "reviewed" else "failed",
                              "agent_run_id": None if rev.review is None or rev.review.agent_run_id is None else str(rev.review.agent_run_id),
                              "output": result.review})
