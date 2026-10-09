"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { CanvasForm, EMPTY_CANVAS, type CanvasValues } from "../../../components/workspace/CanvasForm";
import { ErrorBox, Loading } from "../../../components/ui";
import { ApiError, api } from "../../../lib/api";
import { canOnDecision } from "../../../lib/actions";
import { useIdentity } from "../../../lib/identity";
import { useResource } from "../../../lib/useResource";

export default function NewDecisionPage() {
  const { me, ready } = useIdentity();
  const router = useRouter();
  const metrics = useResource(() => api.metrics(), [me?.id], ready && !!me);
  const allowed = canOnDecision(me, "create_decision", null);
  const submit = async (v: CanvasValues): Promise<ApiError | null> => {
    try {
      const created = await api.createDecision({
        ...v, current_evidence_notes: v.current_evidence_notes.trim() || null,
      });
      router.push(`/decisions/${created.id}`);
      return null;
    } catch (e) {
      return e instanceof ApiError ? e : new ApiError(0, "error", "Something went wrong. Please retry.");
    }
  };
  return (
    <div className="stack" data-testid="new-decision-page">
      <div className="row center"><h1 style={{ margin: 0 }}>New decision</h1><span className="right" /><Link href="/">Back to the portfolio</Link></div>
      {!allowed && ready ? <div className="banner warn" data-testid="new-decision-denied">Only a Product Manager or a Business Analyst can create a decision. Switch the demo identity to continue.</div> : null}
      {metrics.error ? <ErrorBox error={metrics.error} onRetry={metrics.reload} /> : null}
      {metrics.loading && !metrics.data ? <Loading label="Loading metrics" /> : null}
      {metrics.data ? (
        <div className="card">
          <CanvasForm initial={EMPTY_CANVAS} metrics={metrics.data} submitLabel="Create decision" onSubmit={submit} disabled={!allowed} />
        </div>
      ) : null}
    </div>
  );
}
