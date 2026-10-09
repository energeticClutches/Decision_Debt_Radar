// Pure UI logic. The frontend never computes DDI, NBE, direction, stance or permissions: `can` only decides whether a button is
// hidden or disabled (it mirrors ROLE_ACTIONS of backend/app/domain/permissions.py, checked by a parity test). The server is authoritative.

import type { AssessmentOut, AssessmentSummary, DecisionOut, ReviewDetail, Role, UserOut } from "./types";

export type Action =
  | "create_decision" | "edit_canvas" | "confirm_evidence" | "add_evidence" | "run_assessment" | "human_review" | "validate"
  | "record_decision" | "update_dq_check" | "update_recommendation" | "approve_evidence" | "run_synthesis" | "create_brief";

export const ROLE_ACTIONS: Record<Action, readonly Role[]> = {
  create_decision: ["pm", "ba"],
  edit_canvas: ["pm", "ba"],
  confirm_evidence: ["pm", "ba", "product_analyst"],
  add_evidence: ["pm", "ba", "product_analyst"],
  run_assessment: ["pm", "ba", "product_analyst"],
  human_review: ["pm", "ba", "dept_leader", "executive"],
  validate: ["pm", "ba", "dept_leader", "executive"],
  record_decision: ["dept_leader", "executive"],
  update_dq_check: ["product_analyst", "ba"],
  update_recommendation: ["pm", "ba", "product_analyst"],
  approve_evidence: ["ba", "product_analyst"],
  run_synthesis: ["pm", "ba"],
  create_brief: ["pm", "ba"],
};

/** A department leader may validate and record only on decisions of their own team; the decision owner may always record. */
export const LEADER_OWN_TEAM_ONLY: readonly Action[] = ["validate", "record_decision"];
export const OWNER_ALSO_ALLOWED: readonly Action[] = ["record_decision"];

export const ROLE_LABEL: Record<Role, string> = {
  pm: "Product Manager",
  ba: "Business Analyst",
  product_analyst: "Product Analyst",
  bizops: "Strategy and Business Operations",
  dept_leader: "Department Leader",
  executive: "Executive",
};

export interface ActionContext {
  userId?: string | null;
  teamId?: string | null;
  decisionOwnerId?: string | null;
  decisionTeamId?: string | null;
}

export function rolesFor(action: Action): readonly Role[] {
  return ROLE_ACTIONS[action];
}

/** Whether a control should be enabled for the role. Display only: the server repeats every check. */
export function can(role: Role | null | undefined, action: Action, ctx?: ActionContext): boolean {
  if (!role) return false;
  if (ctx && OWNER_ALSO_ALLOWED.includes(action) && ctx.userId && ctx.decisionOwnerId && ctx.userId === ctx.decisionOwnerId) return true;
  if (!ROLE_ACTIONS[action].includes(role)) return false;
  if (ctx && role === "dept_leader" && LEADER_OWN_TEAM_ONLY.includes(action) && ctx.decisionTeamId && ctx.teamId !== ctx.decisionTeamId) return false;
  return true;
}

export function canOnDecision(me: UserOut | null | undefined, action: Action, decision: DecisionOut | null | undefined): boolean {
  if (!me) return false;
  return can(me.role, action, { userId: me.id, teamId: me.team_id, decisionOwnerId: decision?.owner_id, decisionTeamId: decision?.team_id });
}

export function rolesText(action: Action): string {
  return ROLE_ACTIONS[action].map((r) => ROLE_LABEL[r]).join(", ");
}

// ---------------------------------------------------------------- the next action

export type NextActionId =
  | "confirm_evidence" | "approve_evidence" | "run_assessment" | "rerun_assessment" | "run_review" | "resolve_review" | "validate" | "record_decision";

export type TabId = "overview" | "canvas" | "evidence" | "assessment" | "review" | "traceability" | "brief" | "audit";

export interface NextAction {
  id: NextActionId;
  label: string;
  action: Action;
  roles: readonly Role[];
  enabled: boolean;
  /** Why the button is disabled, naming the roles that can perform the action. Null when enabled. */
  disabledReason: string | null;
  /** The tab that carries the control (null: the button performs the action itself). */
  tab: TabId | null;
}

function latestReview(reviews: readonly ReviewDetail[]): ReviewDetail | null {
  return reviews.length ? reviews[reviews.length - 1] : null;
}

export function hasAgentReview(reviews: readonly ReviewDetail[]): boolean {
  return reviews.some((r) => r.reviewer_type === "agent");
}

function build(id: NextActionId, label: string, action: Action, tab: TabId | null, me: UserOut | null, decision: DecisionOut): NextAction {
  const roles = ROLE_ACTIONS[action];
  const enabled = canOnDecision(me, action, decision);
  const names = roles.map((r) => ROLE_LABEL[r]).join(", ");
  return { id, label, action, roles, enabled, tab, disabledReason: enabled ? null : `Your role cannot do this. Allowed roles: ${names}.` };
}

/** The single next action of a decision, derived only from stored lifecycle facts. Null once the decision is decided. */
export function nextAction(
  decision: DecisionOut,
  assessment: Pick<AssessmentOut, "state"> | Pick<AssessmentSummary, "state"> | null,
  reviews: readonly ReviewDetail[],
  me: UserOut | null,
): NextAction | null {
  const stage = decision.lifecycle_stage;
  if (stage === "decided") return null;
  if (stage === "created") return build("confirm_evidence", "Confirm evidence base", "confirm_evidence", null, me, decision);
  if (stage === "evidence_gathered") {
    if (decision.pending_approvals > 0) return build("approve_evidence", "Review proposed customer evidence", "approve_evidence", "evidence", me, decision);
    if (decision.assessment_stale) return build("rerun_assessment", "Re-run assessment", "run_assessment", null, me, decision);
    return build("run_assessment", "Run assessment", "run_assessment", null, me, decision);
  }
  if (stage === "assessed") {
    if (!hasAgentReview(reviews)) return build("run_review", "Run automated review", "run_synthesis", "review", me, decision);
    return build("resolve_review", "Record a review", "human_review", "review", me, decision);
  }
  if (stage === "challenged") {
    const latest = latestReview(reviews);
    if (latest && latest.verdict === "needs_rework") return build("resolve_review", "Resolve review findings", "human_review", "review", me, decision);
    return build("validate", "Validate the assessment", "validate", "review", me, decision);
  }
  // validated
  void assessment;
  return build("record_decision", "Record the decision", "record_decision", "brief", me, decision);
}

// ---------------------------------------------------------------- the status strip

export type StripKind = "decided" | "stale" | "gated" | "partial" | "needs_rework" | "review_failed" | "pending_approvals" | "normal";

export interface StatusStrip {
  kind: StripKind;
  text: string;
  icon: string;
}

export const STALE_BANNER_TEXT = "Stale: this assessment no longer reflects the current evidence.";
export const DECIDED_TEXT = "Decision recorded. Writes are frozen.";
export const NO_AUTOMATED_REVIEW = "No automated adversarial review";

/** Priority order: decided lock, stale, gated, needs rework, review failed, pending approvals, normal ("partial" ranks with gated). */
export function statusStrip(
  decision: DecisionOut,
  assessment: Pick<AssessmentOut, "state"> | Pick<AssessmentSummary, "state"> | null,
  reviews: readonly ReviewDetail[],
): StatusStrip {
  if (decision.lifecycle_stage === "decided") return { kind: "decided", text: DECIDED_TEXT, icon: "lock" };
  if (decision.assessment_stale) return { kind: "stale", text: STALE_BANNER_TEXT, icon: "clock" };
  if (assessment?.state === "insufficient_evidence") return { kind: "gated", text: "INSUFFICIENT EVIDENCE: no DDI is shown.", icon: "stop" };
  if (assessment?.state === "partial") return { kind: "partial", text: "PARTIAL ASSESSMENT: a pipeline stage failed. No score is shown.", icon: "stop" };
  const latest = latestReview(reviews);
  if (latest && latest.verdict === "needs_rework") {
    const blocking = latest.findings.filter((f) => f.severity === "blocking").length;
    return { kind: "needs_rework", text: `Review verdict: needs rework (${blocking} blocking finding${blocking === 1 ? "" : "s"}).`, icon: "alert" };
  }
  if (assessment && decision.lifecycle_stage !== "created" && !hasAgentReview(reviews)) {
    return { kind: "review_failed", text: NO_AUTOMATED_REVIEW, icon: "alert" };
  }
  if (decision.pending_approvals > 0) {
    const n = decision.pending_approvals;
    return { kind: "pending_approvals", text: `${n} customer evidence item${n === 1 ? "" : "s"} await${n === 1 ? "s" : ""} approval.`, icon: "hourglass" };
  }
  return { kind: "normal", text: assessment ? "The assessment reflects the current evidence." : "No assessment yet.", icon: "check" };
}

// ---------------------------------------------------------------- what the portfolio and the workspace may headline

export type HeadlineKind = "scored" | "gated" | "stale" | "partial" | "none";

export interface Headline {
  kind: HeadlineKind;
  text: string;
}

/** The one headline of a decision: "DDI x · Band", INSUFFICIENT EVIDENCE or Stale. It never uses previous_scored_assessment. */
export function headline(decision: Pick<DecisionOut, "assessment_stale" | "current_assessment">): Headline {
  if (decision.assessment_stale) return { kind: "stale", text: "Stale" };
  const cur = decision.current_assessment;
  if (!cur) return { kind: "none", text: "No assessment yet" };
  if (cur.state === "insufficient_evidence") return { kind: "gated", text: "INSUFFICIENT EVIDENCE" };
  if (cur.state === "partial") return { kind: "partial", text: "PARTIAL ASSESSMENT" };
  const band = cur.band ? cur.band.charAt(0).toUpperCase() + cur.band.slice(1) : "";
  return { kind: "scored", text: cur.ddi === null ? band : `DDI ${cur.ddi.toFixed(1)} · ${band}` };
}

/** True when a DDI number, band or contribution may be shown for this assessment (never when gated, partial or missing). */
export function mayShowDdi(assessment: Pick<AssessmentOut, "state"> | Pick<AssessmentSummary, "state"> | null): boolean {
  return assessment?.state === "scored";
}

/** Older scored versions appear only as "vN, superseded" (never as a headline and never with a number). */
export function supersededLabel(version: number): string {
  return `v${version}, superseded`;
}
