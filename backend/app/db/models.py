"""SQLAlchemy 2.0 models mirroring the LIVE schema (migrations 0001-0005).

The schema is created only by the SQL migrations in database/sql/ (never by Base.metadata.create_all).
tests/backend/test_models_reflection.py compares these models with the reflected database
(columns, types, nullability) so they cannot drift. The `fc_` demo schema has no models: the core
never references it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def pg_enum(name: str, *values: str) -> ENUM:
    return ENUM(*values, name=name, create_type=False)


USER_ROLE = pg_enum("user_role", "pm", "ba", "product_analyst", "bizops", "dept_leader", "executive")
LIFECYCLE_STAGE = pg_enum("lifecycle_stage", "created", "evidence_gathered", "assessed", "challenged", "validated", "decided")
RISK_LEVEL = pg_enum("risk_level", "low", "medium", "high")
EVIDENCE_TYPE = pg_enum("evidence_type", "behavioral", "experiment", "customer", "financial", "market", "anecdotal")
STANCE = pg_enum("stance", "supports", "contradicts", "neutral")
STRENGTH_GRADE = pg_enum("strength_grade", "A", "B", "C", "D")
ASSESSMENT_STATE = pg_enum("assessment_state", "scored", "insufficient_evidence", "partial")
DDI_BAND = pg_enum("ddi_band", "low", "moderate", "high", "critical")
DQ_SEVERITY = pg_enum("dq_severity", "pass", "warn", "critical")
DQ_STATUS = pg_enum("dq_status", "open", "resolved", "accepted")
RECOMMENDATION_STATUS = pg_enum("recommendation_status", "proposed", "accepted", "rejected", "deferred")
REVIEW_VERDICT = pg_enum("review_verdict", "ready", "needs_rework")
DECISION_OUTCOME = pg_enum("decision_outcome", "approve", "reject", "defer", "approve_conditional")
PIPELINE_STAGE = pg_enum("pipeline_stage", "dq", "quant", "customer", "experiment", "synthesis", "review", "brief")

UUID_T = UUID(as_uuid=True)
TS = DateTime(timezone=True)
_NOW = text("now()")
_UUID_DEFAULT = text("gen_random_uuid()")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID_T, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT)


def _created() -> Mapped[datetime]:
    return mapped_column(TS, server_default=_NOW)


def _updated() -> Mapped[datetime]:
    return mapped_column(TS, server_default=_NOW)


# ---------------------------------------------------------------- core


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("teams.id"))
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(USER_ROLE)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("users.id"))
    refresh_cadence: Mapped[str | None] = mapped_column(Text)
    last_loaded_at: Mapped[datetime | None] = mapped_column(TS)
    reliability_tier: Mapped[int] = mapped_column(SmallInteger)
    tier_rationale: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text)
    definition: Mapped[str] = mapped_column(Text)
    sql_logic: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    grain: Mapped[str] = mapped_column(Text)
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("data_sources.id"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("users.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    id: Mapped[uuid.UUID] = _pk()
    metric_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("metrics.id"))
    observed_at: Mapped[date] = mapped_column(Date)
    segment_key: Mapped[str | None] = mapped_column(Text)
    segment_value: Mapped[str | None] = mapped_column(Text)
    value: Mapped[Decimal] = mapped_column(Numeric)
    n_sample: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    team_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("teams.id"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str] = mapped_column(Text)
    success_metric_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("metrics.id"))
    decision_due_date: Mapped[date] = mapped_column(Date)
    risk_level: Mapped[str] = mapped_column(RISK_LEVEL)
    current_evidence_notes: Mapped[str | None] = mapped_column(Text)
    change_my_mind_criteria: Mapped[list] = mapped_column(JSONB)
    decision_type: Mapped[str] = mapped_column(Text)
    canvas_completed_at: Mapped[datetime] = mapped_column(TS)
    canvas_locked_at: Mapped[datetime | None] = mapped_column(TS)
    lifecycle_stage: Mapped[str] = mapped_column(LIFECYCLE_STAGE, server_default=text("'created'"))
    assessment_stale: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("users.id"))
    scenario_key: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    # migration 0005 (D4-20, O1): increase | decrease | no_material_decrease
    expected_direction: Mapped[str] = mapped_column(Text)


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("data_sources.id"))
    title: Mapped[str] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[datetime | None] = mapped_column(TS)
    reliability_tier: Mapped[int] = mapped_column(SmallInteger)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    name: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str] = mapped_column(Text)
    design: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    primary_metric_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("metrics.id"))
    planned_sample: Mapped[int | None] = mapped_column(Integer)
    mde: Mapped[Decimal | None] = mapped_column(Numeric)
    source_ref: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    # migration 0005 (D4-12)
    planned_treatment_share: Mapped[Decimal | None] = mapped_column(Numeric)
    control_variant: Mapped[str | None] = mapped_column(Text)
    outcome_key: Mapped[str | None] = mapped_column(Text)


class ExperimentResult(Base):
    __tablename__ = "experiment_results"
    id: Mapped[uuid.UUID] = _pk()
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("experiments.id"))
    variant: Mapped[str] = mapped_column(Text)
    n: Mapped[int] = mapped_column(Integer)
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric)
    effect_size: Mapped[Decimal | None] = mapped_column(Numeric)
    ci_low: Mapped[Decimal | None] = mapped_column(Numeric)
    ci_high: Mapped[Decimal | None] = mapped_column(Numeric)
    p_value: Mapped[Decimal | None] = mapped_column(Numeric)
    srm_flag: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


class CustomerInsight(Base):
    __tablename__ = "customer_insights"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("data_sources.id"))
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    theme: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    segment: Mapped[str | None] = mapped_column(Text)
    quote_count: Mapped[int] = mapped_column(Integer)
    sample_quotes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    collected_at: Mapped[datetime | None] = mapped_column(TS)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- assessment layer


class DecisionAssessment(Base):
    __tablename__ = "decision_assessments"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(ASSESSMENT_STATE)
    ddi_score: Mapped[Decimal | None] = mapped_column(Numeric)
    ddi_band: Mapped[str | None] = mapped_column(DDI_BAND)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    penalty_scores: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    blocking_reasons: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    sensitivity: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    params_version: Mapped[str] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)
    brief_md: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    # migration 0004
    params_hash: Mapped[str] = mapped_column(Text)
    nbe_params_version: Mapped[str | None] = mapped_column(Text)
    nbe_params_hash: Mapped[str | None] = mapped_column(Text)
    evidence_fingerprint: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[date] = mapped_column(Date)


class DecisionRecord(Base):
    __tablename__ = "decision_records"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("users.id"))
    outcome: Mapped[str] = mapped_column(DECISION_OUTCOME)
    rationale: Mapped[str] = mapped_column(Text)
    acknowledged_risk: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    decided_at: Mapped[datetime] = mapped_column(TS, server_default=_NOW)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("decision_assessments.id"))
    stage: Mapped[str | None] = mapped_column(PIPELINE_STAGE)
    agent_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("agent_runs.id"))
    analysis_type: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    query_text: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    n: Mapped[int | None] = mapped_column(Integer)
    limitations: Mapped[str | None] = mapped_column(Text)
    dq_status: Mapped[str | None] = mapped_column(DQ_SEVERITY)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    # migration 0005 (D4-15)
    analysis_identity: Mapped[str | None] = mapped_column(Text)
    params_hash: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    evidence_source_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("evidence_sources.id"))
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("analysis_results.id"))
    evidence_type: Mapped[str] = mapped_column(EVIDENCE_TYPE)
    summary: Mapped[str] = mapped_column(Text)
    stance: Mapped[str] = mapped_column(STANCE)
    strength_grade: Mapped[str] = mapped_column(STRENGTH_GRADE)
    observed_start: Mapped[date] = mapped_column(Date)
    observed_end: Mapped[date] = mapped_column(Date)
    n_sample: Mapped[int | None] = mapped_column(Integer)
    effect_size: Mapped[Decimal | None] = mapped_column(Numeric)
    ci_low: Mapped[Decimal | None] = mapped_column(Numeric)
    ci_high: Mapped[Decimal | None] = mapped_column(Numeric)
    metric_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("metrics.id"))
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("experiments.id"))
    insight_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("customer_insights.id"))
    created_by: Mapped[str] = mapped_column(Text)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("agent_runs.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    # migration 0005 (D4-16, D4-19)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("evidence.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(TS)
    analysis_identity: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str | None] = mapped_column(Text)


class DqCheck(Base):
    __tablename__ = "dq_checks"
    id: Mapped[uuid.UUID] = _pk()
    # migration 0005: the assessment link is optional; a check belongs to a decision (D4-02)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("decision_assessments.id"))
    data_source_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("data_sources.id"))
    check_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(DQ_SEVERITY)
    finding: Mapped[str] = mapped_column(Text)
    affects_metric_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("metrics.id"))
    status: Mapped[str] = mapped_column(DQ_STATUS, server_default=text("'open'"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    # migration 0005 (D4-01, D4-02, D4-03)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decisions.id"))
    check_key: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric)
    affects_success_metric: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    source_snapshot: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(TS)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decision_assessments.id"))
    claim_text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(Text)
    stance: Mapped[str] = mapped_column(STANCE)
    confidence: Mapped[str] = mapped_column(Text)
    conclusion_ref: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("evidence.id"), primary_key=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decision_assessments.id"))
    action_type: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    effort_days: Mapped[Decimal] = mapped_column(Numeric)
    expected_reduction: Mapped[Decimal] = mapped_column(Numeric)
    relevance: Mapped[Decimal] = mapped_column(Numeric)
    priority_score: Mapped[Decimal] = mapped_column(Numeric)
    dimensions_addressed: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(RECOMMENDATION_STATUS, server_default=text("'proposed'"))
    human_note: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    blockers_resolved: Mapped[int] = mapped_column(Integer, server_default=text("0"))   # migration 0004 (R10)


class DecisionReview(Base):
    __tablename__ = "decision_reviews"
    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("decision_assessments.id"))
    reviewer_type: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T, ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(REVIEW_VERDICT)
    challenges: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    human_response: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID_T, ForeignKey("organizations.id"))
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID_T)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(TS, server_default=_NOW)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
