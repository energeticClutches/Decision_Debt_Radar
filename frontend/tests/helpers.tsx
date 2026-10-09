import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { AssessmentOut, AssessmentSummary, DecisionOut, RecommendationOut, ReviewDetail, UserOut } from "../lib/types";

export function html(el: ReactElement): string {
  return renderToStaticMarkup(el);
}

/** The inner markup of the first element whose opening tag contains `attr="value"` (balanced on the same tag name). */
export function region(markup: string, attr: string, value: string): string | null {
  const marker = `${attr}="${value}"`;
  const at = markup.indexOf(marker);
  if (at < 0) return null;
  const open = markup.lastIndexOf("<", at);
  const name = /^<([a-zA-Z0-9]+)/.exec(markup.slice(open))?.[1];
  if (!name) return null;
  const openEnd = markup.indexOf(">", at) + 1;
  const re = new RegExp(`<(/?)${name}\\b`, "gi");
  re.lastIndex = openEnd;
  let depth = 1;
  let m: RegExpExecArray | null;
  while ((m = re.exec(markup))) {
    depth += m[1] ? -1 : 1;
    if (depth === 0) return markup.slice(openEnd, m.index);
  }
  return markup.slice(openEnd);
}

export function text(markup: string): string {
  return markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();
}

export function summary(over: Partial<AssessmentSummary> = {}): AssessmentSummary {
  return { id: "a1", version: 2, state: "scored", is_current: true, historical: false, ddi: 61.5, band: "high", evidence_direction: "mixed", created_at: "2026-10-01T10:00:00Z", ...over };
}

export function decision(over: Partial<DecisionOut> = {}): DecisionOut {
  return {
    id: "d1", org_id: "o1", team_id: "t1", owner_id: "u-owner", title: "Invest in expanding the AI Coach", description: "desc", hypothesis: "If we expand the AI Coach then retention increases.",
    success_metric_id: "m1", decision_due_date: "2026-10-31", risk_level: "high", current_evidence_notes: null, change_my_mind_criteria: ["a criterion that is long enough"],
    decision_type: "product_feature_investment", expected_direction: "increase", lifecycle_stage: "challenged", lifecycle_label: "Evidence challenged",
    assessment_stale: false, canvas_completed_at: "2026-09-01T00:00:00Z", canvas_locked_at: "2026-10-01T00:00:00Z", is_synthetic: true, synthetic_notice: "Synthetic",
    created_at: "2026-09-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", warnings: [], current_assessment: summary(), previous_scored_assessment: null,
    stale_reason: null, stale_at: null, pending_approvals: 0, ...over,
  };
}

export function user(role: UserOut["role"], over: Partial<UserOut> = {}): UserOut {
  return { id: `u-${role}`, name: `Test ${role}`, email: `${role}@example.test`, role, team_id: "t1", team_name: "Product", notice: "Demo identity only", ...over };
}

export function assessment(over: Partial<AssessmentOut> = {}): AssessmentOut {
  return {
    id: "a1", decision_id: "d1", version: 2, state: "scored", is_current: true, is_superseded: false, historical: false, ddi: 61.5, band: "high", uncapped_ddi: 61.5,
    cap_applied: false, support: 0.4, penalty_multiplier: 1.1,
    dimensions: [{ id: "D1", name: "Evidence quality", score: 0.5, applicable: true, status: "Applicable", weight: 0.2, raw_contribution: 10, display_contribution: 10, inputs: [{ name: "x", value: 1, source: "observed", default_reason: null }], defaulted_inputs: [], explanation: "e", details: {} }],
    penalties: [{ id: "P1", name: "Contradiction", score: 0.3, coefficient: 0.5, raw_contribution: 1, display_contribution: 1, inputs: [], defaulted_inputs: [], explanation: "e", details: { floor_applied: true } }],
    sensitivity: { base: 61.5, base_band: "high", min: 58, max: 66, range: [58, 66], count: 10, unchanged_band_share: 1, band_stable: true, label: "robust", label_text: "Robust to aggregation weights.", most_influential: {}, perturbs: "x" },
    blocking_reasons: [], warnings: [], what_drove_this_result: "D4 drove the result.",
    evidence_direction: { label: "mixed", supporting_share: 0.5, contradicting_share: 0.5, neutral_share: 0, direction_basis_weight: 1, threshold: 0.6, direction_bearing_items: 3, explanation: "" },
    params: { ddi_params_version: "ddi_params_v0.1", ddi_params_hash: "h", nbe_params_version: "nbe_params_v0.2", nbe_params_hash: "h" },
    as_of_date: "2026-10-01", narrative: null, positioning: "DDI is an evidence-risk heuristic.", insufficient_evidence_label: null, is_synthetic: true, synthetic_notice: "Synthetic",
    created_at: "2026-10-01T10:00:00Z", previous_scored_assessment: null, ...over,
  };
}

export function gated(over: Partial<AssessmentOut> = {}): AssessmentOut {
  return assessment({
    state: "insufficient_evidence", ddi: null, band: null, uncapped_ddi: null, cap_applied: null, support: null, penalty_multiplier: null, dimensions: [], penalties: [],
    sensitivity: null, insufficient_evidence_label: "INSUFFICIENT EVIDENCE",
    blocking_reasons: [
      { code: "min_items", message: "At least 3 evidence items are required (found 1).", detail: {} },
      { code: "open_critical_dq", message: "A critical data-quality issue is open on the success metric.", detail: { dq_check_ids: ["q1"] } },
    ], ...over,
  });
}

export function recommendation(over: Partial<RecommendationOut> = {}): RecommendationOut {
  return {
    id: "r1", assessment_id: "a1", rank: 1, action_type: "fix_dq", description: "Fix or add instrumentation", why_this: "It unblocks scoring", group: "unblock_scoring", effort_days: 3,
    expected_reduction: 12.5, potential_ddi_reduction: 12.5, blockers_resolved: 2, impact: 2, impact_unit: "blockers_resolved", relevance: 1, priority_score: 4, dimensions_addressed: ["D1"],
    status: "proposed", human_note: null, note: "Ways to gather more evidence, not advice on the decision.", ...over,
  };
}

export function review(over: Partial<ReviewDetail> = {}): ReviewDetail {
  return {
    id: "rv1", assessment_id: "a1", synthesis_id: "s1", agent_run_id: "ar1", reviewer_type: "agent", reviewer_id: null, verdict: "ready", human_response: null,
    created_at: "2026-10-01T10:05:00Z", provenance: "stub_not_model_output", model: "stub:handauthored_review_v1", model_fallback: false, findings: [], ...over,
  };
}
