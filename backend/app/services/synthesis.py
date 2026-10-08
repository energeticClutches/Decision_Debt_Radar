"""Stage 5 Evidence Synthesis and Stage 6 Reviewer (docs/day-5-implementation-brief.md sections 6, 7 and 9).

    SynthesisService.synthesize   one LLM call (plus one repair call after malformed JSON), the deterministic validators, then the
                                  claims are stored. The synthesis row is versioned per assessment and immutable
    ReviewerService.review        one LLM call, code-enforced minimum severities, a code-derived verdict, an immutable
                                  decision_reviews row (reviewer_type agent). Recording it moves `assessed` to `challenged`

Failure semantics (D5-08): an LLM failure, malformed output or a rejected synthesis is recorded (agent_runs, a `failed` or
`rejected_by_validators` synthesis) and returned as a status. It never counts as a review pass, never changes the assessment or
the DDI, and never raises through the pipeline. The Reviewer has no row on failure: the decision stays `assessed`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.params import get_analytics_params
from app.db.models import DecisionAssessment, DecisionReview, Synthesis
from app.domain import permissions as perm
from app.domain.errors import NotFound, StateConflict
from app.domain.permissions import Actor
from app.llm.builders import build_request, default_models
from app.llm.client import sha256_json
from app.llm.prompts import load_prompt
from app.llm.runs import call_llm, mark_run_failed
from app.repositories import assessments as assessments_repo
from app.repositories import audit as audit_repo
from app.repositories import reviews as reviews_repo
from app.repositories import syntheses as syn_repo
from app.repositories.users import parse_uuid
from app.services.base import ServiceContext, unit_of_work
from app.services.lifecycle import LifecycleHelpers, apply_transition
from app.synthesis import payload as payload_mod
from app.synthesis import review as review_mod
from app.synthesis import validators
from app.synthesis.schema import OutputSchemaError, parse_review, parse_synthesis

REVIEWABLE_STAGES = ("assessed", "challenged")


@dataclass
class SynthesisOutcome:
    status: str                                   # succeeded | failed | rejected_by_validators
    synthesis: Synthesis | None = None
    reused: bool = False
    error_class: str | None = None
    error: str | None = None
    claims_stored: int = 0

    def summary(self) -> dict[str, Any]:
        s = self.synthesis
        return {"status": self.status, "reused": self.reused, "synthesis_id": None if s is None else str(s.id),
                "version": None if s is None else s.version, "claims_dropped": None if s is None else s.claims_dropped,
                "claims_stored": self.claims_stored, "error_class": self.error_class, "error": self.error,
                "validator_status": None if s is None else (s.validator_report or {}).get("status")}


@dataclass
class ReviewOutcome:
    status: str                                   # reviewed | review_failed | skipped
    review: DecisionReview | None = None
    reused: bool = False
    error_class: str | None = None
    error: str | None = None
    findings: list[dict] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        r = self.review
        return {"status": self.status, "reused": self.reused, "review_id": None if r is None else str(r.id),
                "verdict": None if r is None else r.verdict, "blocking": sum(1 for f in (r.challenges if r else []) if f.get("severity") == "blocking"),
                "findings": len(r.challenges) if r else 0, "error_class": self.error_class, "error": self.error}


class _LlmStageBase(LifecycleHelpers):
    def __init__(self, ctx: ServiceContext):
        super().__init__(ctx)
        self.params = ctx.analytics_params or get_analytics_params()

    def _client(self):
        if self.ctx.llm is None:
            raise StateConflict("No LLM client is configured (set ANTHROPIC_API_KEY); the LLM stages cannot run.",
                                detail={"reason": "no_llm_client"})
        return self.ctx.llm

    def _load(self, actor: Actor, assessment_id):
        aid = parse_uuid(assessment_id)
        assessment = assessments_repo.get_assessment(self.session, aid) if aid else None
        if assessment is None:
            raise NotFound("Assessment not found.")
        decision = self.decision_or_404(actor, assessment.decision_id, lock=True)
        return assessment, decision

    def _require_current(self, decision, assessment: DecisionAssessment) -> None:
        if decision.lifecycle_stage not in REVIEWABLE_STAGES:
            raise StateConflict(f"Synthesis and review run only at stage 'assessed' or 'challenged' (the decision is "
                                f"'{decision.lifecycle_stage}').", detail={"lifecycle_stage": decision.lifecycle_stage})
        current = assessments_repo.current_assessment(self.session, decision.id)
        if current is None or current.id != assessment.id:
            raise StateConflict("Only the current assessment (the highest version) can be synthesised or reviewed.",
                                detail={"current_version": current.version if current else None})
        if assessment.state == "partial":
            raise StateConflict("A partial assessment has no synthesis.")


class SynthesisService(_LlmStageBase):
    def synthesize(self, actor: Actor, assessment_id, *, force: bool = False, authorize: bool = True) -> SynthesisOutcome:
        if authorize:
            perm.authorize_role(actor, perm.RUN_SYNTHESIS)
        with unit_of_work(self.session):
            assessment, decision = self._load(actor, assessment_id)
            client = self._client()
            self._require_current(decision, assessment)
            models = dict(self.ctx.llm_models or default_models())
            prompt = load_prompt("synthesize", self.ctx.prompt_version)
            payload, index = payload_mod.build_input(self.session, decision, assessment)
            request = build_request(purpose="synthesize", prompt=prompt, input_obj=payload, model=models["synthesize"],
                                    llm_params=self.params.llm, meta={"scenario_key": decision.scenario_key, "evidence_index": index})
            if not force:
                prior = syn_repo.latest_synthesis(self.session, assessment.id)
                if prior is not None and prior.input_sha256 == request.input_sha256 and prior.status in ("succeeded", "rejected_by_validators"):
                    return SynthesisOutcome(status=prior.status, synthesis=prior, reused=True)
            outcome = self._run(decision, assessment, client, request, prompt, payload, index)
            audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="agent", action="synthesis.created",
                                 entity_type="synthesis", entity_id=None if outcome.synthesis is None else outcome.synthesis.id,
                                 decision_id=decision.id, before=None,
                                 after={"assessment_id": str(assessment.id), "status": outcome.status,
                                        "version": None if outcome.synthesis is None else outcome.synthesis.version,
                                        "claims_dropped": None if outcome.synthesis is None else outcome.synthesis.claims_dropped,
                                        "requested_by": actor.id},
                                 is_synthetic=decision.is_synthetic)
            return outcome

    # ---- the LLM call, the one repair attempt, validation and storage
    def _run(self, decision, assessment, client, request, prompt, payload, index) -> SynthesisOutcome:
        def call(req):
            return call_llm(self.session, client, req, decision_id=decision.id, assessment_id=assessment.id, stage="synthesis",
                            agent_name="evidence_synthesis", is_synthetic=decision.is_synthetic)

        first = call(request)
        last = first
        parsed = None
        if first.ok:
            try:
                parsed = parse_synthesis(first.response.text)
            except OutputSchemaError as exc:
                mark_run_failed(self.session, first.run, "schema_error", str(exc))
                repair_input = {**payload, "repair": {"parse_error": str(exc)[:300],
                                                      "instruction": "Return exactly one JSON object that matches the output schema."}}
                repair_req = build_request(purpose="synthesize", prompt=prompt, input_obj=repair_input, model=request.model,
                                           llm_params=self.params.llm, meta={**request.meta, "variant": "repair"})
                last = call(repair_req)
                if last.ok:
                    try:
                        parsed = parse_synthesis(last.response.text)
                    except OutputSchemaError as exc2:
                        mark_run_failed(self.session, last.run, "schema_error", str(exc2))
        if parsed is None:
            err_class = (last.error.error_class if last.error is not None else "schema_error")
            message = str(last.error) if last.error is not None else "the output is not valid JSON or does not match the schema (after one repair attempt)"
            row = syn_repo.add_synthesis(
                self.session, assessment_id=assessment.id, version=syn_repo.max_version(self.session, assessment.id) + 1,
                agent_run_id=last.run.id, status="failed", input_sha256=request.input_sha256, output_sha256=None, output=None,
                validator_report={"status": "failed", "error_class": err_class, "error": message[:300],
                                  "repair_attempted": first.ok}, claims_dropped=0, is_synthetic=decision.is_synthetic)
            return SynthesisOutcome(status="failed", synthesis=row, error_class=err_class, error=message[:300])

        ctx = validators.ValidationContext(
            evidence={e["id"]: e for e in payload["evidence"]}, assessment=payload["assessment"],
            assessment_state=assessment.state, criteria_count=len(payload["decision"]["criteria"]),
            design_rank=dict(self.ctx.ddi_params.design_rank))
        validated, report = validators.validate_synthesis(parsed, ctx)
        report_dict = report.as_dict()
        report_dict["repair_attempted"] = last is not first
        status = "succeeded" if report.status == "passed" else "rejected_by_validators"
        # the dropped claims are part of the LLM run's metadata too, not only of the synthesis row
        last.run.output = {**(last.run.output or {}), "validator": {"status": report.status, "claims_total": report.claims_total,
                                                                     "claims_dropped": report.claims_dropped, "dropped": report.dropped,
                                                                     "rejections": report.rejections}}
        row = syn_repo.add_synthesis(
            self.session, assessment_id=assessment.id, version=syn_repo.max_version(self.session, assessment.id) + 1,
            agent_run_id=last.run.id, status=status, input_sha256=request.input_sha256,
            output_sha256=sha256_json(validated) if status == "succeeded" else None, output=validated if status == "succeeded" else None,
            validator_report=report_dict, claims_dropped=report.claims_dropped, is_synthetic=decision.is_synthetic)
        stored = 0
        if status == "succeeded":
            for claim in validated["claims"]:
                syn_repo.add_claim(self.session, assessment_id=assessment.id, synthesis_id=row.id, local_id=claim["local_id"],
                                   text=claim["text"], claim_type=claim["claim_type"], stance=claim["stance"],
                                   confidence=claim["confidence"], conclusion_ref=claim["conclusion_ref"],
                                   evidence_ids=[uuid.UUID(e) for e in claim["evidence_ids"]], is_synthetic=decision.is_synthetic)
                stored += 1
        else:
            last.run.status = "failed"
            last.run.error_class = "rejected_by_validators"
            last.run.error = "; ".join(sorted({r["rule"] for r in report.rejections}))[:300]
            self.session.flush()
        return SynthesisOutcome(status=status, synthesis=row, claims_stored=stored,
                                error_class=None if status == "succeeded" else "rejected_by_validators",
                                error=None if status == "succeeded" else last.run.error)

    # ---- reads
    def list(self, actor: Actor, assessment_id) -> list[Synthesis]:
        aid = parse_uuid(assessment_id)
        assessment = assessments_repo.get_assessment(self.session, aid) if aid else None
        if assessment is None:
            raise NotFound("Assessment not found.")
        self.decision_or_404(actor, assessment.decision_id)
        return syn_repo.list_syntheses(self.session, assessment.id)


class ReviewerService(_LlmStageBase):
    def review(self, actor: Actor, synthesis_id, *, authorize: bool = True) -> ReviewOutcome:
        if authorize:
            perm.authorize_role(actor, perm.RUN_SYNTHESIS)
        sid = parse_uuid(synthesis_id)
        synthesis = syn_repo.get_synthesis(self.session, sid) if sid else None
        if synthesis is None:
            raise NotFound("Synthesis not found.")
        with unit_of_work(self.session):
            assessment, decision = self._load(actor, synthesis.assessment_id)
            client = self._client()
            self._require_current(decision, assessment)
            if synthesis.status != "succeeded":
                raise StateConflict(f"Only a succeeded synthesis can be reviewed (this one is '{synthesis.status}').",
                                    detail={"status": synthesis.status})
            latest = syn_repo.latest_synthesis(self.session, assessment.id)
            if latest is None or latest.id != synthesis.id:
                raise StateConflict("Only the latest synthesis of the assessment can be reviewed.")
            existing = syn_repo.agent_review_for_synthesis(self.session, synthesis.id)
            if existing is not None:
                return ReviewOutcome(status="reviewed", review=existing, reused=True)
            return self._review(actor, decision, assessment, synthesis, client)

    def _review(self, actor, decision, assessment, synthesis, client) -> ReviewOutcome:
        models = dict(self.ctx.llm_models or default_models())
        prompt = load_prompt("review", self.ctx.prompt_version)
        facts, index = payload_mod.build_input(self.session, decision, assessment, task="review")
        input_obj = {**facts, "synthesis": synthesis.output, "validator_report": synthesis.validator_report}
        meta = {"scenario_key": decision.scenario_key, "evidence_index": index}
        request = build_request(purpose="review", prompt=prompt, input_obj=input_obj, model=models["review"], llm_params=self.params.llm, meta=meta)
        fallback = (build_request(purpose="review", prompt=prompt, input_obj=input_obj, model=models["primary"], llm_params=self.params.llm, meta=meta)
                    if models["primary"] != models["review"] else None)
        call = call_llm(self.session, client, request, decision_id=decision.id, assessment_id=assessment.id, stage="review",
                        agent_name="reviewer", is_synthetic=decision.is_synthetic, fallback=fallback)
        if not call.ok:
            return self._failed(decision, assessment, synthesis, call.error.error_class, str(call.error))
        try:
            raw_findings = parse_review(call.response.text)
        except OutputSchemaError as exc:
            mark_run_failed(self.session, call.run, "schema_error", str(exc))
            return self._failed(decision, assessment, synthesis, "schema_error", str(exc))
        claims = syn_repo.claims_for_synthesis(self.session, synthesis.id)
        claim_by_local = {c.local_id: c for c, _ in claims}
        enforce = dict(evidence_ids={e["id"] for e in input_obj["evidence"]}, claim_ids=set(claim_by_local),
                       criteria_count=len(input_obj["decision"]["criteria"]))
        findings = [{**f, "source": "model"} for f in review_mod.enforce_findings(raw_findings, **enforce)]
        findings += [{**f, "source": "code"}
                     for f in review_mod.enforce_findings(review_mod.code_findings(synthesis.output, facts), **enforce)]
        for f in findings:
            if f["target_type"] == "claim" and f["target_id"] in claim_by_local:
                f["target_local_id"], f["target_id"] = f["target_id"], str(claim_by_local[f["target_id"]].id)
        verdict = review_mod.derive_verdict(findings)
        review = reviews_repo.add_review(
            self.session, assessment_id=assessment.id, reviewer_type="agent", reviewer_id=None, verdict=verdict, challenges=findings,
            human_response=None, synthesis_id=synthesis.id, agent_run_id=call.run.id, is_synthetic=decision.is_synthetic)
        before_stage = decision.lifecycle_stage
        if before_stage == "assessed":
            apply_transition(self.session, decision, "challenged")
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="agent", action="review.completed",
                             entity_type="review", entity_id=review.id, decision_id=decision.id,
                             before={"lifecycle_stage": before_stage},
                             after={"lifecycle_stage": decision.lifecycle_stage, "assessment_id": str(assessment.id), "verdict": verdict,
                                    "reviewer_type": "agent", "synthesis_id": str(synthesis.id), "findings": len(findings),
                                    "blocking": sum(1 for f in findings if f["severity"] == "blocking"),
                                    "model_fallback": bool(call.run.model_fallback), "requested_by": actor.id},
                             is_synthetic=decision.is_synthetic)
        return ReviewOutcome(status="reviewed", review=review, findings=findings)

    def _failed(self, decision, assessment, synthesis, error_class: str, error: str) -> ReviewOutcome:
        """A reviewer failure is recorded as `review_failed` (audited), never as `ready` and never as "no findings". No review row
        is written, so validation needs a human review with an explicit reason (R2)."""
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="agent", action="review.failed",
                             entity_type="synthesis", entity_id=synthesis.id, decision_id=decision.id, before=None,
                             after={"status": "review_failed", "assessment_id": str(assessment.id), "error_class": error_class},
                             is_synthetic=decision.is_synthetic)
        return ReviewOutcome(status="review_failed", error_class=error_class, error=error[:300])

