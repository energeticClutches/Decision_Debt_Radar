"use client";

import { api } from "../../lib/api";
import { fmtDate, fmtNumber, fmtValue, titleCase } from "../../lib/format";
import { useResource } from "../../lib/useResource";
import type { Finding } from "../../lib/types";
import { Drawer, ErrorBox, KeyValues, Loading, Pill, SeverityPill, StancePill } from "../ui";
import { latestSynthesis, type ItemKind, type WorkspaceActions, type WorkspaceData } from "./types";

export function parseItem(item: string | null): { kind: ItemKind; id: string } | null {
  if (!item) return null;
  const idx = item.indexOf(":");
  if (idx < 1) return null;
  const kind = item.slice(0, idx);
  if (kind !== "evidence" && kind !== "analysis" && kind !== "claim" && kind !== "finding") return null;
  return { kind, id: item.slice(idx + 1) };
}

export function itemParam(kind: ItemKind, id: string): string {
  return `${kind}:${id}`;
}

function EvidenceDrawer({ id, ws, act }: { id: string; ws: WorkspaceData; act: WorkspaceActions }) {
  const e = ws.evidence.find((x) => x.id === id);
  if (!e) return <p className="muted">This evidence item is not part of this decision.</p>;
  const customer = ws.customer?.items.find((x) => x.evidence.id === id);
  const fresh = e.freshness;
  return (
    <>
      <p>{e.summary}</p>
      <KeyValues rows={[
        ["Type", titleCase(e.evidence_type)],
        ["Stance", <StancePill key="s" stance={e.stance} />],
        ["Grade", e.strength_grade],
        ["Status", titleCase(e.status)],
        ["Source", `${e.source_name ?? "n/a"}${e.reliability_tier ? ` (tier ${e.reliability_tier})` : ""}`],
        ["Observed", `${fmtDate(e.observed_start)} to ${fmtDate(e.observed_end)}`],
        ["Freshness", fresh ? `${fresh.age_days} days old as of ${fresh.as_of}; half-life ${fresh.half_life_days} days (${fresh.within_half_life ? "within" : "past"} it)` : "n/a (only active evidence has a freshness)"],
        ["Sample size", e.n_sample ?? "n/a"],
        ["Effect", e.effect_size === null ? "n/a" : fmtNumber(e.effect_size, 4)],
        ["95% interval", e.ci_low === null ? "n/a" : `${fmtNumber(e.ci_low, 4)} to ${fmtNumber(e.ci_high, 4)}`],
        ["Created by", e.created_by],
        ["Approval", e.approved_by ? `${titleCase(e.status)} ${fmtDate(e.approved_at)}${e.approval_note ? `: ${e.approval_note}` : ""}` : "n/a"],
      ]} />
      {e.analysis_id ? <button className="chip" onClick={() => act.openItem("analysis", e.analysis_id as string)}>Open the analysis behind this item</button> : null}
      {customer?.insight ? (
        <section>
          <h3>Customer theme: {titleCase(customer.insight.theme)}</h3>
          <p className="small muted">{customer.insight.relevance_note}. Stance set by taxonomy, not by AI.</p>
          {customer.insight.sample_quotes.map((q, i) => <blockquote key={i} className="quote">{String(q.text ?? q.quote ?? JSON.stringify(q))}</blockquote>)}
        </section>
      ) : null}
    </>
  );
}

function AnalysisDrawer({ id, act }: { id: string; act: WorkspaceActions }) {
  const res = useResource(() => api.analysis(id), [id]);
  if (res.loading && !res.data) return <Loading label="Loading analysis" />;
  if (res.error) return <ErrorBox error={res.error} onRetry={res.reload} />;
  const a = res.data;
  if (!a) return null;
  const r = a.result ?? {};
  const num = (v: unknown) => (typeof v === "number" ? fmtNumber(v, 4) : "n/a");
  return (
    <>
      <KeyValues rows={[
        ["Type", titleCase(a.analysis_type)],
        ["Key", a.key ?? "n/a"],
        ["n", a.n ?? "n/a"],
        ["Effect", num(r.effect)],
        ["95% interval", typeof r.ci_low === "number" ? `${num(r.ci_low)} to ${num(r.ci_high)}` : "n/a"],
        ["Data quality", a.dq_status ?? "n/a"],
        ["Identity", <span key="i" className="mono">{a.analysis_identity ?? "n/a"}</span>],
      ]} />
      {a.limitations ? <section><h3>Limitations</h3><p className="small">{a.limitations}</p></section> : null}
      <details className="disclosure"><summary>Parameters</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(a.params, null, 2)}</pre></details>
      {a.query_text ? <details className="disclosure"><summary>Query (read-only)</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{a.query_text}</pre></details> : null}
      <section>
        <h3>Evidence from this analysis</h3>
        {a.evidence_ids.length ? a.evidence_ids.map((e) => <button key={e} className="chip" onClick={() => act.openItem("evidence", e)} style={{ marginRight: 4 }}>{e.slice(0, 8)}</button>) : <p className="small muted">This analysis creates no evidence item.</p>}
      </section>
    </>
  );
}

function ClaimDrawer({ id, ws, act }: { id: string; ws: WorkspaceData; act: WorkspaceActions }) {
  const syn = latestSynthesis(ws);
  const claim = syn?.output?.claims.find((c) => c.local_id === id);
  if (!claim) return <p className="muted">This claim is not in the latest synthesis.</p>;
  const rows = ws.traceability.filter((t) => t.claim_local_id === id && (!syn || t.synthesis_id === syn.id));
  return (
    <>
      <p>{claim.text}</p>
      <KeyValues rows={[
        ["Claim", <span key="c" className="mono">{claim.local_id}</span>],
        ["Type", titleCase(claim.claim_type)],
        ["Stance", <StancePill key="s" stance={claim.stance} />],
        ["Confidence", titleCase(claim.confidence)],
        ["Feeds", claim.conclusion_ref ?? "n/a"],
      ]} />
      <section>
        <h3>Evidence cited</h3>
        {claim.evidence_ids.map((e) => (
          <div key={e}><button className="chip" onClick={() => act.openItem("evidence", e)}>{e.slice(0, 8)}</button>{" "}
            <span className="small">{ws.evidence.find((x) => x.id === e)?.summary.slice(0, 110) ?? "evidence of this decision"}</span></div>
        ))}
      </section>
      {rows.length ? <p className="small muted">{rows.length} traceability row(s) link this claim to its evidence and analyses.</p> : null}
    </>
  );
}

function FindingBody({ f }: { f: Finding }) {
  return (
    <>
      <p><SeverityPill severity={f.severity} /> <Pill>{f.source === "code" ? "Automated check" : "Reviewer"}</Pill> <span className="mono">{f.category}</span></p>
      <p>{f.rationale}</p>
      <KeyValues rows={[
        ["Target", `${f.target_type ?? "n/a"} ${f.target_local_id ?? f.target_id ?? ""}`],
        ["Severity set by the model", f.severity_model ? titleCase(f.severity_model) : "n/a"],
        ["Final severity", titleCase(f.severity)],
      ]} />
      {f.notes.length ? <ul>{f.notes.map((n) => <li key={n} className="small">{n}</li>)}</ul> : null}
    </>
  );
}

function FindingDrawer({ id, ws, act }: { id: string; ws: WorkspaceData; act: WorkspaceActions }) {
  const [reviewId, idx] = id.split(".");
  const review = ws.reviews.find((r) => r.id === reviewId);
  const f = review?.findings[Number(idx)];
  if (!f) return <p className="muted">This finding was not found.</p>;
  return (
    <>
      <FindingBody f={f} />
      {f.target_type === "claim" && f.target_local_id ? <button className="chip" onClick={() => act.openItem("claim", f.target_local_id as string)}>Open claim {f.target_local_id}</button> : null}
      {f.evidence_ids.length ? <section><h3>Evidence cited</h3>{f.evidence_ids.map((e) => <button key={e} className="chip" style={{ marginRight: 4 }} onClick={() => act.openItem("evidence", e)}>{e.slice(0, 8)}</button>)}</section> : null}
    </>
  );
}

export function DrawerHost({ item, ws, act, onClose }: { item: string | null; ws: WorkspaceData; act: WorkspaceActions; onClose: () => void }) {
  const parsed = parseItem(item);
  if (!parsed) return null;
  const titles: Record<ItemKind, string> = { evidence: "Evidence", analysis: "Analysis", claim: "Claim", finding: "Review finding" };
  return (
    <Drawer title={titles[parsed.kind]} onClose={onClose} testId={`drawer-${parsed.kind}`}>
      {parsed.kind === "evidence" ? <EvidenceDrawer id={parsed.id} ws={ws} act={act} /> : null}
      {parsed.kind === "analysis" ? <AnalysisDrawer id={parsed.id} act={act} /> : null}
      {parsed.kind === "claim" ? <ClaimDrawer id={parsed.id} ws={ws} act={act} /> : null}
      {parsed.kind === "finding" ? <FindingDrawer id={parsed.id} ws={ws} act={act} /> : null}
    </Drawer>
  );
}

export { fmtValue };
