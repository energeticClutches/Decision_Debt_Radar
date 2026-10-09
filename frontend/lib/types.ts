// Response types. They mirror backend/app/schemas/responses.py (the server is the only source of DDI, NBE, direction, stance and permissions).

export type Role = "pm" | "ba" | "product_analyst" | "bizops" | "dept_leader" | "executive";
export type LifecycleStage = "created" | "evidence_gathered" | "assessed" | "challenged" | "validated" | "decided";
export type AssessmentState = "scored" | "insufficient_evidence" | "partial";
export type Band = "low" | "moderate" | "high" | "critical";
export type Provenance = "live_model_output" | "stub_not_model_output" | "recorded_model_output";

export interface UserOut {
  id: string;
  name: string;
  email: string;
  role: Role;
  team_id: string | null;
  team_name: string | null;
  notice: string;
}

export interface Health {
  status: string;
  service: string;
  env: string;
  llm_mode: "live" | "replay" | "off";
}

export interface AssessmentSummary {
  id: string;
  version: number;
  state: AssessmentState;
  is_current: boolean;
  historical: boolean;
  ddi: number | null;
  band: Band | null;
  evidence_direction: string | null;
  created_at: string;
}

export interface DecisionOut {
  id: string;
  org_id: string;
  team_id: string;
  owner_id: string;
  title: string;
  description: string;
  hypothesis: string;
  success_metric_id: string;
  decision_due_date: string;
  risk_level: "low" | "medium" | "high";
  current_evidence_notes: string | null;
  change_my_mind_criteria: string[];
  decision_type: string;
  expected_direction: "increase" | "decrease" | "no_material_decrease";
  lifecycle_stage: LifecycleStage;
  lifecycle_label: string;
  assessment_stale: boolean;
  canvas_completed_at: string;
  canvas_locked_at: string | null;
  is_synthetic: boolean;
  synthetic_notice: string | null;
  created_at: string;
  updated_at: string;
  warnings: Array<Record<string, unknown>>;
  current_assessment: AssessmentSummary | null;
  previous_scored_assessment: AssessmentSummary | null;
  stale_reason: string | null;
  stale_at: string | null;
  pending_approvals: number;
}

export interface Freshness {
  age_days: number;
  half_life_days: number;
  within_half_life: boolean;
  as_of: string;
}

export interface EvidenceOut {
  id: string;
  decision_id: string;
  evidence_source_id: string;
  evidence_type: string;
  summary: string;
  stance: "supports" | "contradicts" | "neutral";
  strength_grade: "A" | "B" | "C" | "D";
  observed_start: string;
  observed_end: string;
  n_sample: number | null;
  effect_size: number | null;
  ci_low: number | null;
  ci_high: number | null;
  metric_id: string | null;
  experiment_id: string | null;
  insight_id: string | null;
  created_by: string;
  is_synthetic: boolean;
  created_at: string;
  updated_at: string;
  status: "active" | "superseded" | "proposed" | "rejected";
  analysis_id: string | null;
  analysis_identity: string | null;
  source_fingerprint: string | null;
  superseded_by: string | null;
  superseded_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_note: string | null;
  source_name: string | null;
  reliability_tier: number | null;
  freshness: Freshness | null;
}

export interface InputValue {
  name: string;
  value: unknown;
  source: "observed" | "default";
  default_reason: string | null;
}

export interface DimensionOut {
  id: string;
  name: string;
  score: number | null;
  applicable: boolean;
  status: string;
  weight: number;
  raw_contribution: number;
  display_contribution: number;
  inputs: InputValue[];
  defaulted_inputs: InputValue[];
  explanation: string;
  details: Record<string, unknown>;
}

export interface PenaltyOut {
  id: string;
  name: string;
  score: number;
  coefficient: number;
  raw_contribution: number;
  display_contribution: number;
  inputs: InputValue[];
  defaulted_inputs: InputValue[];
  explanation: string;
  details: Record<string, unknown>;
}

export interface Sensitivity {
  base: number;
  base_band: Band;
  min: number;
  max: number;
  range: [number, number];
  count: number;
  unchanged_band_share: number;
  band_stable: boolean;
  label: string;
  label_text: string;
  most_influential: Record<string, unknown>;
  perturbs: string;
}

export interface EvidenceDirection {
  label: string;
  supporting_share: number;
  contradicting_share: number;
  neutral_share: number;
  direction_basis_weight: number;
  threshold: number;
  direction_bearing_items: number;
  explanation: string;
  note?: string;
}

export interface BlockingReason {
  code: string;
  message: string;
  detail?: Record<string, unknown>;
}

export interface AssessmentOut {
  id: string;
  decision_id: string;
  version: number;
  state: AssessmentState;
  is_current: boolean;
  is_superseded: boolean;
  historical: boolean;
  ddi: number | null;
  band: Band | null;
  uncapped_ddi: number | null;
  cap_applied: boolean | null;
  support: number | null;
  penalty_multiplier: number | null;
  dimensions: DimensionOut[];
  penalties: PenaltyOut[];
  sensitivity: Sensitivity | null;
  blocking_reasons: BlockingReason[];
  warnings: Array<Record<string, unknown>>;
  what_drove_this_result: string | null;
  evidence_direction: EvidenceDirection | null;
  params: { ddi_params_version: string; ddi_params_hash: string; nbe_params_version: string; nbe_params_hash: string };
  as_of_date: string;
  narrative: string | null;
  positioning: string;
  insufficient_evidence_label: string | null;
  is_synthetic: boolean;
  synthetic_notice: string | null;
  created_at: string;
  previous_scored_assessment: AssessmentSummary | null;
}

export interface RecommendationOut {
  id: string;
  assessment_id: string;
  rank: number;
  action_type: string;
  description: string;
  why_this: string | null;
  group: "unblock_scoring" | "reduce_debt";
  effort_days: number;
  expected_reduction: number;
  potential_ddi_reduction: number;
  blockers_resolved: number;
  impact: number;
  impact_unit: string;
  relevance: number;
  priority_score: number;
  dimensions_addressed: string[];
  status: string;
  human_note: string | null;
  note: string;
}

export interface Finding {
  category: string | null;
  severity: "blocking" | "warning" | "info" | string | null;
  severity_model: string | null;
  source: "model" | "code" | string;
  target_type: string | null;
  target_id: string | null;
  target_local_id: string | null;
  rationale: string | null;
  evidence_ids: string[];
  notes: string[];
}

export interface ReviewDetail {
  id: string;
  assessment_id: string;
  synthesis_id: string | null;
  agent_run_id: string | null;
  reviewer_type: "agent" | "human";
  reviewer_id: string | null;
  verdict: "ready" | "needs_rework";
  human_response: string | null;
  created_at: string;
  provenance: Provenance | null;
  model: string | null;
  model_fallback: boolean;
  findings: Finding[];
}

export interface SynthesisClaim {
  local_id: string;
  text: string;
  claim_type: string;
  stance: "supports" | "contradicts" | "neutral";
  confidence: string;
  evidence_ids: string[];
  conclusion_ref: string | null;
}

export interface SynthesisOutput {
  claims: SynthesisClaim[];
  uncertainties: Array<{ text: string; evidence_ids?: string[] }>;
  gaps: Array<{ text: string; gap_type: string }>;
  criteria_assessment: Array<{ criterion_index: number; status: string; evidence_ids: string[] }>;
  sections: Record<"summary" | "supporting" | "contradicting" | "uncertainty", string>;
}

export interface ValidatorReport {
  status?: string;
  claims_total?: number;
  claims_dropped?: number;
  dropped?: Array<Record<string, unknown>>;
  reclassified?: Array<Record<string, unknown>>;
  rejections?: Array<Record<string, unknown>>;
  error_class?: string;
  error?: string;
  [key: string]: unknown;
}

export interface SynthesisOut {
  id: string;
  assessment_id: string;
  version: number;
  status: "succeeded" | "failed" | "rejected_by_validators";
  agent_run_id: string;
  input_sha256: string;
  output_sha256: string | null;
  output: SynthesisOutput | null;
  validator_report: ValidatorReport;
  claims_dropped: number;
  created_at: string;
  is_synthetic: boolean;
  synthetic_notice: string | null;
  provenance: Provenance | null;
  model: string | null;
}

export interface SynthesisRun {
  reused: boolean;
  synthesis: SynthesisOut | null;
  synthesis_status: string;
  review: Record<string, unknown> | null;
}

export interface DecisionRecordOut {
  id: string;
  decision_id: string;
  decided_by: string;
  outcome: "approve" | "reject" | "defer" | "approve_conditional";
  rationale: string;
  acknowledged_risk: boolean;
  decided_at: string;
  lifecycle_stage: LifecycleStage;
  lifecycle_label: string;
}

export interface DqCheck {
  id: string;
  decision_id: string;
  assessment_id: string | null;
  data_source_id: string;
  check_key: string;
  check_type: string;
  target: string;
  severity: "pass" | "warn" | "critical";
  finding: string;
  observed_value: number | null;
  threshold: number | null;
  affects_metric_id: string | null;
  affects_success_metric: boolean;
  source_snapshot: string | null;
  last_run_at: string | null;
  status: "open" | "resolved" | "accepted";
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface AnalysisSummary {
  id: string;
  decision_id: string;
  analysis_type: string;
  key: string | null;
  metric_id: string | null;
  n: number | null;
  dq_status: string | null;
  analysis_identity: string | null;
  params_hash: string | null;
  source_fingerprint: string | null;
  creates_evidence: boolean;
  created_at: string;
}

export interface AnalysisOut extends AnalysisSummary {
  agent_run_id: string | null;
  params: Record<string, unknown>;
  query_text: string | null;
  result: Record<string, unknown> | null;
  limitations: string | null;
  evidence_ids: string[];
  is_synthetic: boolean;
  synthetic_notice: string | null;
}

export interface Insight {
  id: string;
  theme: string;
  sentiment: string;
  mentions: number;
  relevance_observed: number | null;
  relevance_note: string;
  source_types: string[] | null;
  first_mention_date: string | null;
  last_mention_date: string | null;
  taxonomy_version: string | null;
  segment_counts: Record<string, unknown> | null;
  sample_quotes: Array<Record<string, unknown>>;
}

export interface ClassificationCounts {
  taxonomy_version: string;
  total: number;
  by_relevance: Record<string, number>;
  by_theme: Record<string, Record<string, number>>;
  provenance: Provenance | null;
  model: string | null;
}

export interface CustomerEvidence {
  decision_id: string;
  pending_approvals: number;
  items: Array<{ evidence: EvidenceOut; insight: Insight | null; classification_counts: ClassificationCounts | null }>;
  classification_counts: ClassificationCounts[];
}

export interface BriefListItem {
  id: string;
  kind: "decision_brief" | "gated_evidence_summary";
  version: number;
  label: string;
  synthesis_id: string | null;
  created_at: string;
}

export interface BriefOut {
  id: string;
  assessment_id: string;
  synthesis_id: string | null;
  kind: "decision_brief" | "gated_evidence_summary";
  version: number;
  label: string;
  content: BriefContent;
  markdown: string;
  created_at: string;
  is_synthetic: boolean;
  synthetic_notice: string | null;
}

/** The stored brief content (backend/app/services/briefs.py). Only the fields the page reads are typed. */
export interface BriefContent {
  kind: string;
  label: string;
  title: string;
  version: number;
  banners: string[];
  header: {
    decision: Record<string, unknown> & { title: string; hypothesis: string; success_metric: string | null; lifecycle_label: string; criteria: string[] };
    assessment: { id: string; version: number; state: string; as_of_date: string; evidence_fingerprint: string };
    versions: Record<string, string>;
  };
  ddi_panel: {
    state: string;
    ddi: number | null;
    band: Band | null;
    dimensions: DimensionOut[];
    penalties: PenaltyOut[];
    positioning: string;
    insufficient_evidence_label: string | null;
    what_drove_this_result: string | null;
    sensitivity: Sensitivity | null;
    blocking_reasons: BlockingReason[];
  };
  direction: Partial<EvidenceDirection>;
  gate_reasons: BlockingReason[];
  blocking_reasons_explained?: Array<{ code: string; explanation: string }>;
  unblocking_actions?: Array<{ action_type: string; description: string; blockers_resolved: number; effort_days: number }>;
  evidence_table: Array<Record<string, unknown> & { id: string; evidence_type: string; stance: string; grade: string; tier: number; status: string; summary: string; source: string }>;
  dq: Array<Record<string, unknown> & { target: string; severity: string; status: string; finding: string }>;
  heterogeneity: Record<string, unknown>;
  nbe: Array<{ action_type: string; description: string; effort_days: number; blockers_resolved: number }>;
  review: {
    agent_review: null | { review_id: string; verdict: string; findings: Finding[]; model: string | null; model_fallback: boolean };
    human_reviews: Array<{ review_id: string; verdict: string; human_response: string | null; created_at: string }>;
  };
  decision_record: null | { outcome: string; rationale: string; acknowledged_risk: boolean; decided_at: string };
  synthesis: null | { id: string; version: number; model: string | null; provenance: string; input_sha256: string; output_sha256: string | null; claims_dropped: number };
  llm_sections: Record<"summary" | "supporting" | "contradicting" | "uncertainty", Array<{ text: string; claim_refs: Array<{ local_id: string; claim_id: string; evidence_ids: string[] }> }>>;
  claims: Array<{ local_id: string; claim_id: string; text: string; claim_type: string; stance: string; confidence: string; conclusion_ref: string | null; evidence_ids: string[] }>;
  uncertainties: Array<{ text: string }>;
  gaps: Array<{ text: string; gap_type: string }>;
  criteria_assessment: Array<{ criterion_index: number; text: string; status: string; evidence_ids: string[] }>;
  traceability: TraceabilityRow[];
}

export interface TraceabilityRow {
  row_type: "claim_link" | "gap";
  claim_id: string | null;
  claim_local_id?: string | null;
  synthesis_id?: string | null;
  claim_text: string;
  claim_type: string | null;
  stance: string | null;
  claim_confidence?: string | null;
  evidence_id: string | null;
  evidence_summary: string | null;
  evidence_type: string | null;
  strength_grade: string | null;
  source_id?: string | null;
  source_name: string | null;
  reliability_tier: number | null;
  analysis_id: string | null;
  analysis_type: string | null;
  dq_status: string | null;
  conclusion_ref: string | null;
  evidence_status: string | null;
  [key: string]: unknown;
}

export interface Metric {
  id: string;
  name: string;
  definition: string;
  unit: string;
  grain: string;
}

export interface AuditRow {
  id: string;
  ts: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PipelineStage {
  stage: string;
  agent_name: string;
  status: string;
  agent_run_id?: string | null;
  output?: Record<string, unknown>;
  error?: string;
}

export interface PipelineRun {
  decision_id: string;
  lifecycle_stage: LifecycleStage;
  partial: boolean;
  failed_stage: string | null;
  error: string | null;
  stages: PipelineStage[];
  analysis_ids: string[];
  assessment: AssessmentOut | null;
  pending_approvals: Array<Record<string, unknown>>;
  synthesis: Record<string, unknown> | null;
  review: Record<string, unknown> | null;
}
