"""Helpers for the Day-5 tests (customer evidence, synthesis, review, briefs, scenarios).

All LLM calls are served by test clients (tests/fixtures/llm): the keyword-rule stub for classification and hand-authored fixtures or
scripted outputs for synthesis and review. No test reaches the network, needs a key or reads the ground-truth table in product code."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from day4_support import TODAY, make_ctx
from replay import STUB_MODELS, ReplayClient, ScriptedClient
from sqlalchemy import select

from app.core.clock import FixedClock
from app.db import models as m
from app.services import (
    BriefService,
    CustomerEvidenceService,
    PipelineService,
    ReviewerService,
    SynthesisService,
    unit_of_work,
)
from app.synthesis import payload as payload_mod

__all__ = ["TODAY", "FixedClock", "STUB_MODELS", "ReplayClient", "ScriptedClient"]


def ctx5(session, llm=None, **over):
    """A ServiceContext with an LlmClient and the stub model names."""
    over.setdefault("llm_models", STUB_MODELS)
    return make_ctx(session, llm=llm, **over)


def with_customer_params(ctx, **customer):
    """A copy of the context whose analytics parameters override some `customer` values (for example min_theme_mentions)."""
    params = ctx.analytics_params
    data = {**params.data, "customer": {**params.data["customer"], **customer}}
    return replace(ctx, analytics_params=type(params)(version=params.version, content_hash=params.content_hash, data=data))


def run_stage3(ctx, actor, decision):
    """Stage 3 alone, in its own transaction (what the pipeline's customer stage does). Returns (output, status)."""
    class _Run:
        id = None
    svc = CustomerEvidenceService(ctx)
    with unit_of_work(ctx.session):
        dec = svc.decision_or_404(actor, decision.id, lock=True)
        return svc.run_stage(dec, _Run(), client=ctx.llm)


def customer_items(session, decision):
    return list(session.scalars(select(m.Evidence).where(m.Evidence.decision_id == decision.id, m.Evidence.evidence_type == "customer")
                                .order_by(m.Evidence.created_at, m.Evidence.id)))


def by_theme(session, decision):
    """theme -> list of customer evidence rows (any status)."""
    out: dict[str, list[m.Evidence]] = {}
    for ev in customer_items(session, decision):
        insight = session.get(m.CustomerInsight, ev.insight_id)
        out.setdefault(insight.theme, []).append(ev)
    return out


def approve_pending(session, ctx, ba, decision, note="test approval"):
    svc = CustomerEvidenceService(ctx)
    ids = [e.id for e in customer_items(session, decision) if e.status == "proposed"]
    for eid in ids:
        svc.set_approval(ba, eid, "approve", note)
    return ids


def pipeline_with(session, llm, **over) -> PipelineService:
    return PipelineService(ctx5(session, llm, **over))


class Scenario:
    """The full Day-5 path on a seeded scenario: pipeline (proposals), approval of every proposed item, pipeline again (scored or
    gated assessment, synthesis, review)."""

    def __init__(self, session, seed, scenario: str, client=None):
        self.session, self.seed, self.scenario = session, seed, scenario
        self.client = client or ReplayClient()
        self.ctx = ctx5(session, self.client)
        self.decision = seed.decisions[scenario]
        session.refresh(self.decision)

    def run(self):
        self.first = PipelineService(self.ctx).run(self.seed.analyst, self.decision.id)
        self.approved = approve_pending(self.session, self.ctx, self.seed.ba, self.decision)
        self.session.refresh(self.decision)
        self.second = PipelineService(self.ctx).run(self.seed.analyst, self.decision.id)
        self.session.refresh(self.decision)
        self.assessment = self.second.assessment
        return self

    def evidence_input(self):
        payload, index = payload_mod.build_input(self.session, self.decision, self.assessment)
        return payload, index


def assessment_state(a) -> dict:
    """The deterministic part of an assessment (what the frozen engine produced), for before/after comparisons."""
    return {"state": a.state, "ddi_score": None if a.ddi_score is None else float(a.ddi_score), "ddi_band": a.ddi_band,
            "dimension_scores": a.dimension_scores, "penalty_scores": a.penalty_scores, "blocking_reasons": a.blocking_reasons,
            "sensitivity": a.sensitivity, "evidence_fingerprint": a.evidence_fingerprint, "version": a.version}


def synthesis_output_for(payload: dict[str, Any], *, extra_claims: list[dict] | None = None, drop_ids: bool = False) -> dict[str, Any]:
    """A VALID synthesis output built from a real input payload (for the service-level tests that do not need a scenario fixture).

    One claim per evidence item, typed and staged so that every validator passes: a behavioral item is `associative`, a customer item
    `customer`, a financial item `financial`, an experiment item `descriptive`. Stances follow the item. Every sentence of the sections
    cites a claim."""
    claims = []
    for i, e in enumerate(payload["evidence"], start=1):
        etype = e["evidence_type"]
        ctype = {"behavioral": "associative", "customer": "customer", "financial": "financial", "experiment": "descriptive"}.get(etype, "descriptive")
        ref = {"behavioral": "D6", "customer": "D5", "financial": "D7", "experiment": "D4"}.get(etype, "D1")
        if ref == "D6" and e.get("effect_size") is None:
            ref = "D1"
        claims.append({"local_id": f"c{i}", "text": f"The {etype} evidence item is described in the structured facts.", "claim_type": ctype,
                       "stance": e["stance"], "confidence": "low", "evidence_ids": [] if drop_ids else [e["id"]], "conclusion_ref": ref})
    claims += list(extra_claims or [])
    refs = " ".join(f"[[{c['local_id']}]]" for c in claims[:1]) or ""
    first = claims[0]["local_id"] if claims else "c1"
    return {"claims": claims, "uncertainties": [], "gaps": [{"text": "No further evidence types are available.", "gap_type": "other"}],
            "criteria_assessment": [],
            "sections": {"summary": f"The assessment is described in the facts [[{first}]].", "supporting": f"Supporting items exist [[{first}]].",
                         "contradicting": "", "uncertainty": f"Uncertainty remains [[{first}]]. {refs}".strip()}}


def review_output(*findings: dict) -> dict:
    return {"findings": list(findings)}


def finding(category="missing_evidence", severity="info", target_type="synthesis", target_id="synthesis", rationale="A test finding.",
            evidence_ids=()):
    return {"category": category, "severity": severity, "target_type": target_type, "target_id": target_id, "rationale": rationale,
            "evidence_ids": list(evidence_ids)}


def services(ctx):
    return SynthesisService(ctx), ReviewerService(ctx), BriefService(ctx)


def dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)
