"use client";

import { useState } from "react";

import { titleCase } from "../../lib/format";
import type { TraceabilityRow } from "../../lib/types";
import { Empty, Pill, StancePill } from "../ui";
import { latestSynthesis, type TabProps } from "./types";

type View = "claims" | "evidence";

/** The rows of the latest synthesis (claim links) and the gap rows. Superseded evidence stays visible with its status. */
export function visibleRows(rows: TraceabilityRow[], synthesisId: string | null): TraceabilityRow[] {
  return rows.filter((r) => r.row_type === "gap" || !synthesisId || r.synthesis_id === synthesisId);
}

export function TraceabilityTable({ rows, view, onOpenEvidence, onOpenClaim, filterEvidence }: {
  rows: TraceabilityRow[]; view: View; onOpenEvidence?: (id: string) => void; onOpenClaim?: (id: string) => void; filterEvidence?: string | null;
}) {
  const gaps = rows.filter((r) => r.row_type === "gap");
  const links = rows.filter((r) => r.row_type === "claim_link" && (!filterEvidence || r.evidence_id === filterEvidence));
  const keyOf = (r: TraceabilityRow) => (view === "claims" ? r.claim_id : r.evidence_id) ?? "";
  const groups = new Map<string, TraceabilityRow[]>();
  for (const r of links) groups.set(keyOf(r), [...(groups.get(keyOf(r)) ?? []), r]);
  return (
    <div className="stack">
      {gaps.length ? (
        <section className="card" data-testid="trace-gaps">
          <h3>Gaps</h3>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{gaps.map((g, i) => <li key={i} data-testid="gap-row" className="small">{g.claim_text} <span className="muted">(feeds {g.conclusion_ref})</span></li>)}</ul>
        </section>
      ) : null}
      {Array.from(groups.entries()).map(([key, group]) => {
        const head = group[0];
        return (
          <section className="card" key={key} data-testid={view === "claims" ? "trace-claim" : "trace-evidence"}>
            {view === "claims" ? (
              <h3>
                {head.claim_local_id && onOpenClaim ? <button className="chip" onClick={() => onOpenClaim(head.claim_local_id as string)}>{head.claim_local_id}</button> : null} {head.claim_text}
                <span className="small muted"> {titleCase(head.claim_type)} · <StancePill stance={head.stance} /> · confidence {titleCase(head.claim_confidence)} · feeds {head.conclusion_ref ?? "n/a"}</span>
              </h3>
            ) : (
              <h3>
                {head.evidence_id && onOpenEvidence ? <button className="chip" onClick={() => onOpenEvidence(head.evidence_id as string)}>{(head.evidence_id as string).slice(0, 8)}</button> : null} {head.evidence_summary}
                {head.evidence_status && head.evidence_status !== "active" ? <> <Pill tone="stale" testId="evidence-status">{titleCase(head.evidence_status)}</Pill></> : null}
              </h3>
            )}
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>{view === "claims"
                  ? <tr><th>Evidence</th><th>Type, grade</th><th>Source</th><th>Analysis</th><th>Data quality</th><th>Status</th></tr>
                  : <tr><th>Claim</th><th>Stance</th><th>Confidence</th><th>Source</th><th>Feeds</th></tr>}</thead>
                <tbody>
                  {group.map((r, i) => view === "claims" ? (
                    <tr key={i} data-testid="trace-row">
                      <td className="small">{r.evidence_id && onOpenEvidence ? <button className="chip" onClick={() => onOpenEvidence(r.evidence_id as string)}>{(r.evidence_id as string).slice(0, 8)}</button> : null} {r.evidence_summary?.slice(0, 100)}</td>
                      <td>{titleCase(r.evidence_type)} · {r.strength_grade}</td>
                      <td className="small">{r.source_name} {r.reliability_tier ? `(tier ${r.reliability_tier})` : ""}</td>
                      <td>{r.analysis_type ? titleCase(r.analysis_type) : "n/a"}</td>
                      <td>{r.dq_status ? titleCase(r.dq_status) : "n/a"}</td>
                      <td>{r.evidence_status === "active" ? <Pill tone="ok">Active</Pill> : <Pill tone="stale" testId="evidence-status">{titleCase(r.evidence_status)}</Pill>}</td>
                    </tr>
                  ) : (
                    <tr key={i} data-testid="trace-row">
                      <td className="small">{r.claim_local_id ? <span className="chip">{r.claim_local_id}</span> : null} {r.claim_text}</td>
                      <td><StancePill stance={r.stance} /></td><td>{titleCase(r.claim_confidence)}</td>
                      <td className="small">{r.source_name} {r.reliability_tier ? `(tier ${r.reliability_tier})` : ""}</td><td>{r.conclusion_ref ?? "n/a"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      {!groups.size && !gaps.length ? <Empty testId="trace-empty">No traceability rows exist for this assessment yet.</Empty> : null}
    </div>
  );
}

export function TraceabilityTab({ ws, act }: TabProps) {
  const [view, setView] = useState<View>("claims");
  const [evidenceId, setEvidenceId] = useState<string>("");
  const syn = latestSynthesis(ws);
  const rows = visibleRows(ws.traceability, syn?.id ?? null);
  const cited = Array.from(new Map(rows.filter((r) => r.evidence_id).map((r) => [r.evidence_id as string, r.evidence_summary ?? ""])).entries());
  return (
    <div className="stack" data-testid="tab-panel-traceability">
      <p className="small muted">Every claim links to the evidence it cites, and each evidence item to its source and analysis. Rows come straight from the traceability view; gaps are evidence types that are missing.</p>
      <div className="row center">
        <button className={`btn${view === "claims" ? " primary" : ""}`} onClick={() => setView("claims")} data-testid="trace-view-claims">Claim to evidence</button>
        <button className={`btn${view === "evidence" ? " primary" : ""}`} onClick={() => setView("evidence")} data-testid="trace-view-evidence">Evidence to claims</button>
        {view === "evidence" ? (
          <label className="small">Filter by evidence{" "}
            <select value={evidenceId} onChange={(e) => setEvidenceId(e.target.value)} data-testid="trace-filter">
              <option value="">All evidence</option>
              {cited.map(([id, summary]) => <option key={id} value={id}>{`${id.slice(0, 8)} ${summary.slice(0, 50)}`}</option>)}
            </select>
          </label>
        ) : null}
      </div>
      <TraceabilityTable rows={rows} view={view} filterEvidence={evidenceId || null}
        onOpenEvidence={(id) => act.openItem("evidence", id)} onOpenClaim={(id) => act.openItem("claim", id)} />
    </div>
  );
}
