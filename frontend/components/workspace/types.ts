import type { TabId } from "../../lib/actions";
import type { ApiError } from "../../lib/api";
import type {
  AnalysisSummary, AssessmentOut, AuditRow, BriefListItem, CustomerEvidence, DecisionOut, DecisionRecordOut, DqCheck, EvidenceOut, Metric,
  RecommendationOut, ReviewDetail, SynthesisOut, TraceabilityRow, UserOut,
} from "../../lib/types";

/** Everything the tabs show. All values are the server's stored values; the browser derives nothing from them but display. */
export interface WorkspaceData {
  decision: DecisionOut;
  me: UserOut | null;
  users: UserOut[];
  assessment: AssessmentOut | null;        // the current assessment (the highest version)
  assessments: AssessmentOut[];            // newest first; only version, state and date are shown for older ones
  recommendations: RecommendationOut[];
  reviews: ReviewDetail[];                 // oldest first
  syntheses: SynthesisOut[];
  evidence: EvidenceOut[];
  customer: CustomerEvidence | null;
  dq: DqCheck[];
  analyses: AnalysisSummary[];
  briefs: BriefListItem[];
  traceability: TraceabilityRow[];
  record: DecisionRecordOut | null;
  audit: AuditRow[];
  metrics: Metric[];
}

export type ItemKind = "evidence" | "analysis" | "claim" | "finding";

export type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

export interface WorkspaceActions {
  refresh: () => void;
  /** Runs a mutation, then reloads the decision and every panel (the lifecycle and the stale flag can change on any write). */
  perform: <T>(label: string, fn: () => Promise<T>) => Promise<Result<T>>;
  runPipeline: () => void;
  goTab: (tab: TabId) => void;
  openItem: (kind: ItemKind, id: string) => void;
  openValidate: () => void;
}

export interface TabProps {
  ws: WorkspaceData;
  act: WorkspaceActions;
}

export function isLocked(ws: Pick<WorkspaceData, "decision">): boolean {
  return ws.decision.lifecycle_stage === "decided";
}

export function agentReviews(ws: Pick<WorkspaceData, "reviews">): ReviewDetail[] {
  return ws.reviews.filter((r) => r.reviewer_type === "agent");
}

/** The latest succeeded synthesis (the one a reader sees). */
export function latestSynthesis(ws: Pick<WorkspaceData, "syntheses">) {
  const ok = ws.syntheses.filter((s) => s.status === "succeeded");
  return ok.length ? ok[ok.length - 1] : null;
}
