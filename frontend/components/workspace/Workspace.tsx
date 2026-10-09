"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { api, ApiError } from "../../lib/api";
import type { NextAction, TabId } from "../../lib/actions";
import { useIdentity } from "../../lib/identity";
import type { PipelineRun } from "../../lib/types";
import { useResource } from "../../lib/useResource";
import { ErrorBox, Loading } from "../ui";
import { AssessmentTab } from "./AssessmentTab";
import { AuditTab } from "./AuditTab";
import { BriefRecordTab } from "./BriefRecordTab";
import { CanvasTab } from "./CanvasTab";
import { DrawerHost, itemParam } from "./Drawers";
import { EvidenceTab } from "./EvidenceTab";
import { OverviewTab } from "./OverviewTab";
import { PipelinePanel } from "./PipelinePanel";
import { ReviewTab, ValidateDialog } from "./ReviewTab";
import { TraceabilityTab } from "./TraceabilityTab";
import type { ItemKind, Result, WorkspaceActions, WorkspaceData } from "./types";
import { WorkspaceHeader } from "./WorkspaceHeader";

export const TABS: Array<[TabId, string]> = [
  ["overview", "Overview"], ["canvas", "Canvas"], ["evidence", "Evidence"], ["assessment", "Assessment"], ["review", "Review"],
  ["traceability", "Traceability"], ["brief", "Brief & Record"], ["audit", "Audit"],
];

function isTab(value: string | null): value is TabId {
  return TABS.some(([id]) => id === value);
}

export function Workspace({ id }: { id: string }) {
  const { me, users, ready } = useIdentity();
  const router = useRouter();
  const params = useSearchParams();
  const tabParam = params.get("tab");
  const tab: TabId = isTab(tabParam) ? tabParam : "overview";
  const item = params.get("item");
  const [rev, setRev] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [validateOpen, setValidateOpen] = useState(false);
  const [pipeline, setPipeline] = useState<{ running: boolean; result: PipelineRun | null; error: ApiError | null } | null>(null);

  const on = ready && !!me;
  const key = [id, me?.id, rev] as const;
  const decision = useResource(() => api.decision(id), key, on);
  const gotDecision = on && !!decision.data;
  const assessments = useResource(() => api.assessments(id), [...key, decision.data?.current_assessment?.id], gotDecision);
  const current = assessments.data?.[0] ?? null;
  const aid = current?.id;
  const withAssessment = gotDecision && !!aid;
  const recommendations = useResource(() => api.recommendations(aid as string), [...key, aid], withAssessment);
  const reviews = useResource(() => api.reviews(aid as string), [...key, aid], withAssessment);
  const syntheses = useResource(() => api.syntheses(aid as string), [...key, aid], withAssessment);
  const briefs = useResource(() => api.briefs(aid as string), [...key, aid], withAssessment);
  const traceability = useResource(() => api.traceability(aid as string), [...key, aid], withAssessment);
  const evidence = useResource(() => api.evidence(id), key, gotDecision);
  const customer = useResource(() => api.customerEvidence(id), key, gotDecision);
  const dq = useResource(() => api.dqChecks(id), key, gotDecision);
  const analyses = useResource(() => api.analyses(id), key, gotDecision);
  const audit = useResource(() => api.audit(id), key, gotDecision);
  const record = useResource(() => api.decisionRecord(id).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }), key, gotDecision);
  const metrics = useResource(() => api.metrics(), [me?.id], on);

  const refresh = useCallback(() => setRev((r) => r + 1), []);
  const setQuery = useCallback((next: { tab?: TabId; item?: string | null }) => {
    const q = new URLSearchParams(params.toString());
    if (next.tab) q.set("tab", next.tab);
    if (next.item === null) q.delete("item");
    else if (next.item) q.set("item", next.item);
    router.replace(`/decisions/${id}?${q.toString()}`, { scroll: false });
  }, [params, router, id]);

  const perform = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<Result<T>> => {
    setBusy(label);
    setActionError(null);
    try {
      const value = await fn();
      return { ok: true, value };
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, "error", "Something went wrong. Please retry.");
      // a 422 with field messages is shown next to its form field by the caller; everything else is shown here
      if (!(error.status === 422 && Object.keys(error.fieldErrors).length)) setActionError(error);
      return { ok: false, error };
    } finally {
      setBusy(null);
      refresh();                                  // the lifecycle and the stale flag can change on any write (and after a 409)
    }
  }, [refresh]);

  const runPipeline = useCallback(() => {
    setPipeline({ running: true, result: null, error: null });
    setActionError(null);
    api.pipelineRun(id).then(
      (result) => { setPipeline({ running: false, result, error: null }); refresh(); },
      (e: unknown) => {
        setPipeline({ running: false, result: null, error: e instanceof ApiError ? e : new ApiError(0, "error", "Something went wrong. Please retry.") });
        refresh();
      },
    );
  }, [id, refresh]);

  const act = useMemo<WorkspaceActions>(() => ({
    refresh, perform, runPipeline,
    goTab: (t) => setQuery({ tab: t, item: null }),
    openItem: (kind: ItemKind, itemId: string) => setQuery({ item: itemParam(kind, itemId) }),
    openValidate: () => setValidateOpen(true),
  }), [refresh, perform, runPipeline, setQuery]);

  if (!ready || (on && decision.loading && !decision.data)) return <Loading label="Loading the decision" />;
  if (decision.error && !decision.data) return <ErrorBox error={decision.error} onRetry={decision.reload} />;
  if (!decision.data) return <Loading label="Loading the decision" />;

  const ws: WorkspaceData = {
    decision: decision.data, me, users, assessment: current, assessments: assessments.data ?? [], recommendations: recommendations.data ?? [],
    reviews: reviews.data ?? [], syntheses: syntheses.data ?? [], evidence: evidence.data ?? [], customer: customer.data, dq: dq.data ?? [],
    analyses: analyses.data ?? [], briefs: briefs.data ?? [], traceability: traceability.data ?? [], record: record.data, audit: audit.data ?? [],
    metrics: metrics.data ?? [],
  };
  const owner = users.find((u) => u.id === ws.decision.owner_id) ?? null;
  const panelError = [assessments, recommendations, reviews, syntheses, evidence, customer, dq, analyses, audit].find((r) => r.error && r.error.status !== 404)?.error ?? null;

  const onNext = (next: NextAction) => {
    if (next.id === "confirm_evidence") void perform("Confirming the evidence base", () => api.confirmEvidence(id));
    else if (next.id === "run_assessment" || next.id === "rerun_assessment") runPipeline();
    else if (next.id === "run_review") void perform("Running the automated review", () => api.resynthesise(aid as string, false));
    else if (next.id === "validate") { act.goTab("review"); setValidateOpen(true); }
    else if (next.tab) act.goTab(next.tab);
  };

  const common = { ws, act };
  return (
    <div className="stack" data-testid="workspace" data-decision-id={id}>
      <WorkspaceHeader decision={ws.decision} assessment={ws.assessment} reviews={ws.reviews} me={me} owner={owner} busy={!!busy || pipeline?.running === true} onNext={onNext} />
      {busy ? <div className="banner info" role="status" data-testid="busy">{busy}...</div> : null}
      {actionError ? <ErrorBox error={actionError} onDismiss={() => setActionError(null)} onRetry={refresh} /> : null}
      {panelError ? <ErrorBox error={panelError} onRetry={refresh} /> : null}
      <nav role="tablist" aria-label="Workspace sections" className="row" style={{ gap: 6 }}>
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`btn${tab === t ? " primary" : ""}`} onClick={() => act.goTab(t)} data-testid={`tab-${t}`}>{label}</button>
        ))}
      </nav>
      <div role="tabpanel" aria-label={tab}>
        {tab === "overview" ? <OverviewTab {...common} /> : null}
        {tab === "canvas" ? <CanvasTab {...common} /> : null}
        {tab === "evidence" ? <EvidenceTab {...common} /> : null}
        {tab === "assessment" ? <AssessmentTab {...common} /> : null}
        {tab === "review" ? <ReviewTab {...common} /> : null}
        {tab === "traceability" ? <TraceabilityTab {...common} /> : null}
        {tab === "brief" ? <BriefRecordTab {...common} /> : null}
        {tab === "audit" ? <AuditTab {...common} /> : null}
      </div>
      <DrawerHost item={item} ws={ws} act={act} onClose={() => setQuery({ item: null })} />
      {validateOpen ? <ValidateDialog ws={ws} act={act} onClose={() => setValidateOpen(false)} /> : null}
      {pipeline ? <PipelinePanel running={pipeline.running} result={pipeline.result} error={pipeline.error} onClose={() => setPipeline(null)} /> : null}
    </div>
  );
}
