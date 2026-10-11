// The one typed API client. It sends the demo identity header (X-Demo-User, not authentication) and throws ApiError.
// Calls go to /api/... (same origin); next.config.mjs rewrites them to the backend, so no CORS change is needed.

import type {
  AnalysisOut, AnalysisSummary, AssessmentOut, AuditRow, BriefListItem, BriefOut, CustomerEvidence, DecisionOut, DecisionRecordOut,
  DqCheck, EvidenceOut, Health, Metric, PipelineRun, RecommendationOut, ReviewDetail, SynthesisOut, SynthesisRun, TraceabilityRow, UserOut,
} from "./types";

export const IDENTITY_KEY = "ddr.demo_user";
export const API_BASE = "/api";
/** The free API host sleeps when idle; for about a minute after the first request it answers 502, 503 or 504. */
export const WAKING_MESSAGE = "The free demo server is waking up (about a minute). Retrying…";
const READ_TIMEOUT_MS = 45_000;

export class ApiError extends Error {
  status: number;
  code: string;
  detail: Record<string, unknown> | null;
  constructor(status: number, code: string, message: string, detail: Record<string, unknown> | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
  /** The roles the server says may perform the refused action (401/403 detail.allowed_roles). */
  get allowedRoles(): string[] {
    const roles = this.detail?.allowed_roles;
    return Array.isArray(roles) ? roles.map(String) : [];
  }
  /** Field-level messages of a 422 (detail.fields or a FastAPI validation list), keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const fields = this.detail?.fields;
    if (fields && typeof fields === "object") {
      for (const [k, v] of Object.entries(fields as Record<string, unknown>)) out[k] = String(v);
    }
    return out;
  }
}

export function getStoredUser(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(IDENTITY_KEY);
  } catch {
    return null;
  }
}

export function setStoredUser(id: string): void {
  try {
    window.localStorage.setItem(IDENTITY_KEY, id);
  } catch {
    /* storage can be unavailable: the identity then lasts for the session only */
  }
}

/** Builds an ApiError from a failed response body. Pure, so it is unit-tested. */
export function toApiError(status: number, body: unknown): ApiError {
  const err = (body && typeof body === "object" ? (body as Record<string, unknown>).error : null) as
    | { code?: string; message?: string; detail?: Record<string, unknown> | null }
    | null;
  if (err && typeof err === "object" && err.message) {
    return new ApiError(status, String(err.code ?? "error"), String(err.message), (err.detail as Record<string, unknown> | null) ?? null);
  }
  const validation = body && typeof body === "object" ? (body as Record<string, unknown>).detail : null;
  if (status === 422 && Array.isArray(validation)) {
    const fields: Record<string, string> = {};
    for (const item of validation as Array<{ loc?: unknown[]; msg?: string }>) {
      const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
      fields[loc || "body"] = String(item.msg ?? "invalid");
    }
    return new ApiError(422, "validation", "Some fields are not valid.", { fields });
  }
  if (status === 502 || status === 503 || status === 504) return new ApiError(status, "unavailable", WAKING_MESSAGE);
  if (status >= 500) return new ApiError(status, "server_error", "Something went wrong on the server. Please retry.");
  return new ApiError(status, "error", `The request failed (${status}).`);
}

async function request<T>(method: string, path: string, body?: unknown, opts?: { identity?: string | null }): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const identity = opts?.identity === undefined ? getStoredUser() : opts.identity;
  if (identity) headers["X-Demo-User"] = identity;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    // A read that never answers (the host is still starting) is aborted and treated like a network failure, which the hooks retry.
    const signal = method === "GET" && typeof AbortSignal !== "undefined" && "timeout" in AbortSignal ? AbortSignal.timeout(READ_TIMEOUT_MS) : undefined;
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", signal });
  } catch {
    throw new ApiError(0, "network", "The server cannot be reached. Please retry.");
  }
  let parsed: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  // The API answers every error with a JSON body; a plain 500 without one comes from the proxy in front of it (the API host is down or starting).
  if (res.status === 500 && parsed === null) throw new ApiError(502, "unavailable", WAKING_MESSAGE);
  if (!res.ok) throw toApiError(res.status, parsed);
  return parsed as T;
}

const get = <T,>(path: string) => request<T>("GET", path);
const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body === undefined ? {} : body);
const patch = <T,>(path: string, body: unknown) => request<T>("PATCH", path, body);

export const api = {
  health: () => get<Health>("/health"),
  users: () => request<UserOut[]>("GET", "/users", undefined, { identity: null }),
  me: () => get<UserOut>("/me"),
  metrics: () => get<Metric[]>("/metrics"),
  decisions: () => get<DecisionOut[]>("/decisions"),
  decision: (id: string) => get<DecisionOut>(`/decisions/${id}`),
  createDecision: (body: Record<string, unknown>) => post<DecisionOut>("/decisions", body),
  patchCanvas: (id: string, body: Record<string, unknown>) => patch<DecisionOut>(`/decisions/${id}/canvas`, body),
  confirmEvidence: (id: string) => post<DecisionOut>(`/decisions/${id}/confirm-evidence`),
  evidence: (id: string) => get<EvidenceOut[]>(`/decisions/${id}/evidence`),
  customerEvidence: (id: string) => get<CustomerEvidence>(`/decisions/${id}/customer-evidence`),
  approveEvidence: (evidenceId: string, action: "approve" | "reject", note: string) =>
    patch<EvidenceOut>(`/evidence/${evidenceId}/approval`, { action, note }),
  dqChecks: (id: string) => get<DqCheck[]>(`/decisions/${id}/dq-checks`),
  patchDq: (checkId: string, status: "resolved" | "accepted", note: string) => patch<DqCheck>(`/dq-checks/${checkId}`, { status, note }),
  analyses: (id: string) => get<AnalysisSummary[]>(`/decisions/${id}/analyses`),
  analysis: (analysisId: string) => get<AnalysisOut>(`/analyses/${analysisId}`),
  pipelineRun: (id: string) => post<PipelineRun>(`/decisions/${id}/pipeline-runs`),
  assessments: (id: string) => get<AssessmentOut[]>(`/decisions/${id}/assessments`),
  assessment: (assessmentId: string) => get<AssessmentOut>(`/assessments/${assessmentId}`),
  recommendations: (assessmentId: string) => get<RecommendationOut[]>(`/assessments/${assessmentId}/recommendations`),
  reviews: (assessmentId: string) => get<ReviewDetail[]>(`/assessments/${assessmentId}/reviews`),
  postReview: (assessmentId: string, verdict: "ready" | "needs_rework", humanResponse: string) =>
    post(`/assessments/${assessmentId}/reviews`, { verdict, human_response: humanResponse }),
  syntheses: (assessmentId: string) => get<SynthesisOut[]>(`/assessments/${assessmentId}/syntheses`),
  resynthesise: (assessmentId: string, force = true) => post<SynthesisRun>(`/assessments/${assessmentId}/syntheses`, { force }),
  validate: (id: string) => post<DecisionOut>(`/decisions/${id}/validate`),
  briefs: (assessmentId: string) => get<BriefListItem[]>(`/assessments/${assessmentId}/briefs`),
  createBrief: (assessmentId: string, kind: "decision_brief" | "gated_evidence_summary") =>
    post<BriefOut>(`/assessments/${assessmentId}/briefs`, { kind }),
  brief: (briefId: string) => get<BriefOut>(`/briefs/${briefId}`),
  traceability: (assessmentId: string) => get<TraceabilityRow[]>(`/assessments/${assessmentId}/traceability`),
  decisionRecord: (id: string) => get<DecisionRecordOut>(`/decisions/${id}/decision-record`),
  recordDecision: (id: string, body: { outcome: string; rationale: string; acknowledged_risk: boolean }) =>
    post<DecisionRecordOut>(`/decisions/${id}/decision-record`, body),
  audit: (id: string) => get<AuditRow[]>(`/decisions/${id}/audit`),
  patchRecommendation: (recId: string, status: "accepted" | "rejected" | "deferred", note: string) =>
    patch<RecommendationOut>(`/recommendations/${recId}`, { status, note }),
};
