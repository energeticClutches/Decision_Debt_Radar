"""Helpers for the Day-4 database tests. Everything runs in the rolled-back transaction of the `session` fixture.

The analytics read the committed FitConnect data through the read-only executor (a separate connection); everything the
tests write (decisions, DQ checks, analyses, evidence, assessments) stays inside the rolled-back transaction.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from types import SimpleNamespace

from flow import Flow
from sqlalchemy import text

from app.core.clock import FixedClock
from app.core.params import get_analytics_params, get_ddi_params, get_nbe_params, get_tenant_config
from app.services import PipelineService, ServiceContext

TODAY = date(2026, 10, 1)

SCENARIOS = {
    "ai_coach": dict(metric="d90_retention", decision_type="product_feature_investment", expected_direction="increase"),
    "community": dict(metric="d90_retention", decision_type="product_feature_investment", expected_direction="increase"),
    "pricing": dict(metric="paid_conversion_rate", decision_type="pricing_change", expected_direction="no_material_decrease"),
    "onboarding": dict(metric="activation_rate_7d", decision_type="process_or_ux_change", expected_direction="increase"),
}


def make_ctx(session, **over) -> ServiceContext:
    fields = dict(session=session, clock=FixedClock(TODAY), ddi_params=get_ddi_params(), nbe_params=get_nbe_params(),
                  analytics_params=get_analytics_params(), tenant=get_tenant_config())
    fields.update(over)
    return ServiceContext(**fields)


def pipeline(session, **over) -> PipelineService:
    return PipelineService(make_ctx(session, **over))


def no_run():
    """A stand-in for the agent_runs row of a stage when a stage function is called directly."""
    return SimpleNamespace(id=None)


def clone_decision(flow: Flow, seed, scenario: str, *, title: str | None = None):
    """A new decision at stage evidence_gathered with the configuration of a seeded scenario (same metric, type, expected
    direction and scenario_key), and copies of that scenario's experiments."""
    spec = SCENARIOS[scenario]
    metric_id = str(seed.metrics[spec["metric"]].id)
    d = flow.new_decision(title=title or f"Clone of {scenario}", success_metric_id=metric_id, decision_type=spec["decision_type"],
                          expected_direction=spec["expected_direction"])
    seeded = seed.decisions[scenario]
    flow.session.execute(text("UPDATE decisions SET scenario_key = :s WHERE id = :d"), {"s": scenario, "d": d.id})
    flow.session.execute(text(
        "INSERT INTO experiments (org_id, decision_id, name, hypothesis, design, start_date, end_date, status, primary_metric_id,"
        " planned_sample, mde, source_ref, planned_treatment_share, control_variant, outcome_key, is_synthetic)"
        " SELECT org_id, :new, name, hypothesis, design, start_date, end_date, status, primary_metric_id, planned_sample, mde,"
        " source_ref, planned_treatment_share, control_variant, outcome_key, is_synthetic FROM experiments WHERE decision_id = :old"),
        {"new": d.id, "old": seeded.id})
    flow.session.refresh(d)
    return flow.decisions.confirm_evidence(seed.pm, d.id)


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normalized(value) -> str:
    """Canonical JSON with every UUID replaced by a placeholder (assessment payloads compared 'excluding ids')."""
    return UUID_RE.sub("<id>", json.dumps(value, sort_keys=True, default=str))


def assessment_payload(a, *, with_fingerprint: bool = False) -> dict:
    payload = {"state": a.state, "ddi_score": None if a.ddi_score is None else float(a.ddi_score), "ddi_band": a.ddi_band,
               "dimension_scores": a.dimension_scores, "penalty_scores": a.penalty_scores, "blocking_reasons": a.blocking_reasons,
               "sensitivity": a.sensitivity, "narrative": a.narrative, "params_version": a.params_version,
               "params_hash": a.params_hash, "nbe_params_version": a.nbe_params_version, "nbe_params_hash": a.nbe_params_hash,
               "as_of_date": a.as_of_date.isoformat()}
    if with_fingerprint:
        payload["evidence_fingerprint"] = a.evidence_fingerprint
    return payload


def insert_synthesis(session, assessment) -> uuid.UUID:
    """A syntheses row (and its agent run) so a test can insert a claim: since migration 0006 every new claim names its synthesis."""
    run = session.execute(text(
        "INSERT INTO agent_runs (decision_id, assessment_id, stage, agent_name, status, purpose, model, is_synthetic)"
        " VALUES (:d,:a,'synthesis','evidence_synthesis','succeeded','synthesize','stub:test',true) RETURNING id"),
        {"d": assessment.decision_id, "a": assessment.id}).scalar()
    version = session.execute(text("SELECT coalesce(max(version),0)+1 FROM syntheses WHERE assessment_id=:a"), {"a": assessment.id}).scalar()
    return session.execute(text(
        "INSERT INTO syntheses (assessment_id, version, agent_run_id, status, input_sha256, output_sha256, output, is_synthetic)"
        " VALUES (:a,:v,:r,'succeeded','h','h','{}'::jsonb,true) RETURNING id"), {"a": assessment.id, "v": version, "r": run}).scalar()


def new_id() -> uuid.UUID:
    return uuid.uuid4()
