"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { fmtDateTime, fmtNumber, fmtPercent, isReplayProvenance, titleCase } from "../../lib/format";
import type { AnalysisOut, CustomerEvidence, DqCheck, EvidenceOut } from "../../lib/types";
import { Empty, ErrorBox, Pill, ProvenanceNotice, SeverityPill, StancePill } from "../ui";
import { Guarded } from "./Guarded";
import { isLocked, type TabProps, type WorkspaceActions, type WorkspaceData } from "./types";

export const APPROVAL_WARNING = "Approval changes the evidence: the current assessment becomes stale. Rejection is permanent for this item.";
export const CUSTOMER_STANCE_COPY = "Set by taxonomy, not by AI";

type Sub = "register" | "customer" | "dq" | "analyses";
const SUBS: Array<[Sub, string]> = [["register", "Register"], ["customer", "Customer evidence"], ["dq", "Data quality"], ["analyses", "Analyses"]];

export function EvidenceTab({ ws, act }: TabProps) {
  const [sub, setSub] = useState<Sub>("register");
  return (
    <div className="stack" data-testid="tab-panel-evidence">
      <div className="row" role="tablist" aria-label="Evidence sections">
        {SUBS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={sub === id} className={`btn${sub === id ? " primary" : ""}`} onClick={() => setSub(id)} data-testid={`evidence-sub-${id}`}>
            {label}{id === "customer" && ws.decision.pending_approvals > 0 ? ` (${ws.decision.pending_approvals} pending)` : ""}
          </button>
        ))}
      </div>
      {sub === "register" ? <Register ws={ws} act={act} /> : null}
      {sub === "customer" ? <CustomerSection ws={ws} act={act} /> : null}
      {sub === "dq" ? <DqSection ws={ws} act={act} /> : null}
      {sub === "analyses" ? <AnalysesSection ws={ws} act={act} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------- register
export function EvidenceRegister({ evidence, history, onOpen }: { evidence: EvidenceOut[]; history: boolean; onOpen: (id: string) => void }) {
  const rows = evidence.filter((e) => history || e.status === "active" || e.status === "proposed");
  if (!rows.length) return <Empty testId="register-empty">No evidence has been recorded for this decision yet.</Empty>;
  return (
    <div className="card tbl-wrap">
      <table className="tbl" data-testid="evidence-table">
        <thead><tr><th>Type</th><th>Summary</th><th>Stance</th><th>Grade</th><th>Source (tier)</th><th>Freshness</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} data-testid="evidence-row" data-status={e.status}>
              <td><button className="chip" onClick={() => onOpen(e.id)} data-testid="evidence-open">{titleCase(e.evidence_type)}</button></td>
              <td className="small">{e.summary.slice(0, 160)}{e.summary.length > 160 ? "..." : ""}</td>
              <td><StancePill stance={e.stance} /></td>
              <td>{e.strength_grade}</td>
              <td className="small">{e.source_name ?? "n/a"} {e.reliability_tier ? `(tier ${e.reliability_tier})` : ""}</td>
              <td className="small">{e.freshness ? `${e.freshness.age_days} days old, ${e.freshness.within_half_life ? "within" : "past"} the ${e.freshness.half_life_days}-day half-life` : "n/a (not active)"}</td>
              <td>{e.status === "active" ? <Pill tone="ok">Active</Pill> : e.status === "proposed" ? <Pill tone="warn">Proposed</Pill> : <Pill tone="stale">{titleCase(e.status)}</Pill>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Register({ ws, act }: TabProps) {
  const [history, setHistory] = useState(false);
  const hidden = ws.evidence.filter((e) => e.status === "superseded" || e.status === "rejected").length;
  return (
    <div className="stack">
      <label className="row center small">
        <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} data-testid="history-toggle" />
        Show history: superseded and rejected items ({hidden})
      </label>
      <EvidenceRegister evidence={ws.evidence} history={history} onOpen={(id) => act.openItem("evidence", id)} />
    </div>
  );
}

// ---------------------------------------------------------------- customer evidence
export function CustomerCard({
  item, ws, act, note, setNote, busy,
}: {
  item: CustomerEvidence["items"][number];
  ws: Pick<WorkspaceData, "decision" | "me">;
  act: Pick<WorkspaceActions, "openItem"> & { decide?: (id: string, action: "approve" | "reject", note: string) => void };
  note: string;
  setNote: (v: string) => void;
  busy: boolean;
}) {
  const e = item.evidence;
  const i = item.insight;
  const proposed = e.status === "proposed";
  const locked = ws.decision.lifecycle_stage === "decided";
  const needsNote = !note.trim();
  return (
    <article className="card" data-testid={`customer-card-${i?.theme ?? e.id}`} data-status={e.status}>
      <div className="row center">
        <h3 style={{ margin: 0 }}>{i ? titleCase(i.theme) : "Customer evidence"}</h3>
        <StancePill stance={e.stance} />
        <span className="small muted" data-testid="stance-source">{CUSTOMER_STANCE_COPY}</span>
        {e.status === "active" ? <Pill tone="ok">Approved</Pill> : e.status === "proposed" ? <Pill tone="warn" testId="proposed-pill">Proposed: awaiting approval</Pill> : <Pill tone="stale">{titleCase(e.status)}</Pill>}
      </div>
      <p className="small">{e.summary}</p>
      <p className="small muted">
        {i ? <>Mentions: {i.mentions}. {i.relevance_note}: {fmtPercent(i.relevance_observed, 0)} direct. </> : null}
        Grade {e.strength_grade}. Source {e.source_name ?? "n/a"}{e.reliability_tier ? ` (tier ${e.reliability_tier})` : ""}.
      </p>
      {item.classification_counts ? (
        <p className="small muted">
          Classified {item.classification_counts.total} texts with {item.classification_counts.model ?? "n/a"}. <ProvenanceNotice provenance={item.classification_counts.provenance} model={item.classification_counts.model} />
        </p>
      ) : null}
      {i && i.sample_quotes.length ? (
        <details className="disclosure">
          <summary>Sample quotes ({i.sample_quotes.length})</summary>
          {i.sample_quotes.map((q, idx) => <blockquote key={idx} className="quote" data-testid="customer-quote">{String(q.text ?? q.quote ?? JSON.stringify(q))}</blockquote>)}
        </details>
      ) : null}
      {e.approved_by ? <p className="small muted">{e.status === "rejected" ? "Rejected" : "Approved"} {fmtDateTime(e.approved_at)}{e.approval_note ? `: ${e.approval_note}` : ""}</p> : null}
      {proposed ? (
        <div className="stack" style={{ marginTop: 8 }}>
          <div className="banner warn small" data-testid="approval-warning">{APPROVAL_WARNING}</div>
          <div className="field">
            <label htmlFor={`note-${e.id}`}>Approval note (required)</label>
            <textarea id={`note-${e.id}`} rows={2} value={note} onChange={(ev) => setNote(ev.target.value)} data-testid={`approval-note-${e.id}`} />
          </div>
          <div className="row">
            <Guarded action="approve_evidence" decision={ws.decision} me={ws.me} locked={locked} extraDisabled={needsNote || busy} testId={`approve-${e.id}`} className="btn primary"
              onClick={() => act.decide?.(e.id, "approve", note.trim())}>Approve</Guarded>
            <Guarded action="approve_evidence" decision={ws.decision} me={ws.me} locked={locked} extraDisabled={needsNote || busy} testId={`reject-${e.id}`} className="btn danger"
              onClick={() => act.decide?.(e.id, "reject", note.trim())}>Reject</Guarded>
          </div>
        </div>
      ) : null}
      <button className="chip" onClick={() => act.openItem("evidence", e.id)} style={{ marginTop: 6 }}>Open evidence details</button>
    </article>
  );
}

function CustomerSection({ ws, act }: TabProps) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<import("../../lib/api").ApiError | null>(null);
  const cust = ws.customer;
  if (!cust) return <Empty>Customer evidence is loading or unavailable.</Empty>;
  const withItems = new Set(cust.items.map((i) => i.insight?.theme).filter(Boolean) as string[]);
  const gaps = cust.classification_counts.flatMap((c) => Object.entries(c.by_theme)
    .filter(([theme]) => theme !== "(none)" && !withItems.has(theme)).map(([theme, byRel]) => ({ theme, byRel, taxonomy: c.taxonomy_version })));
  const decide = async (id: string, action: "approve" | "reject", note: string) => {
    setBusy(true);
    setError(null);
    const r = await act.perform(action === "approve" ? "Approving" : "Rejecting", () => api.approveEvidence(id, action, note));
    setBusy(false);
    if (!r.ok) setError(r.error);
  };
  return (
    <div className="stack" data-testid="customer-section">
      <p className="small muted">Customer feedback is classified by theme and relevance only. The stance of each theme comes from a human-authored map. A person approves or rejects each item before it can enter the assessment.</p>
      {error ? <ErrorBox error={error} onDismiss={() => setError(null)} /> : null}
      {cust.items.length === 0 ? <Empty testId="customer-empty">No customer evidence has been proposed yet. Run the assessment to classify the feedback.</Empty> : null}
      {cust.items.map((it) => (
        <CustomerCard key={it.evidence.id} item={it} ws={ws} act={{ openItem: act.openItem, decide }} note={notes[it.evidence.id] ?? ""} setNote={(v) => setNotes((n) => ({ ...n, [it.evidence.id]: v }))} busy={busy} />
      ))}
      {gaps.length ? (
        <section className="card" data-testid="customer-gaps">
          <h3>Below the threshold</h3>
          <p className="small muted">These themes were classified, but too few relevant mentions exist, so no evidence item was proposed.</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {gaps.map((g) => <li key={g.theme} data-testid="gap-row"><span className="mono">{g.theme}</span>: {Object.entries(g.byRel).map(([k, v]) => `${k} ${v}`).join(", ")}</li>)}
          </ul>
        </section>
      ) : null}
      {cust.classification_counts.map((c) => (
        <p key={c.taxonomy_version} className="small muted">Classification run for {c.taxonomy_version}: {c.total} texts by {c.model ?? "n/a"} <ProvenanceNotice provenance={c.provenance} model={c.model} />
          {!isReplayProvenance(c.provenance) ? null : null}</p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- data quality
function DqRow({ check, ws, act }: { check: DqCheck; ws: WorkspaceData; act: WorkspaceActions }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<import("../../lib/api").ApiError | null>(null);
  const open = check.status === "open" && check.severity !== "pass";
  const set = async (status: "resolved" | "accepted") => {
    const r = await act.perform("Updating the data-quality check", () => api.patchDq(check.id, status, note.trim()));
    if (!r.ok) setError(r.error);
  };
  return (
    <tr data-testid="dq-row" data-severity={check.severity} data-status={check.status}>
      <td><span className="mono">{check.target}</span><div className="small muted">{titleCase(check.check_type)}</div></td>
      <td><SeverityPill severity={check.severity === "critical" ? "blocking" : check.severity === "warn" ? "warning" : "info"} /> <span className="small">{titleCase(check.severity)}</span>{check.affects_success_metric ? <div className="small"><Pill tone="bad">Affects the success metric</Pill></div> : null}</td>
      <td className="small">{check.finding}<div className="muted">Observed {fmtNumber(check.observed_value, 4)}, threshold {fmtNumber(check.threshold, 4)}</div></td>
      <td><Pill tone={check.status === "open" ? "warn" : "ok"}>{titleCase(check.status)}</Pill></td>
      <td>
        {open ? (
          <div className="stack">
            <input aria-label="Note" placeholder="Note" value={note} onChange={(e) => setNote(e.target.value)} data-testid="dq-note" />
            <div className="row">
              <Guarded action="update_dq_check" decision={ws.decision} me={ws.me} locked={isLocked(ws)} className="btn small" testId="dq-resolve" onClick={() => set("resolved")}>Mark resolved</Guarded>
              <Guarded action="update_dq_check" decision={ws.decision} me={ws.me} locked={isLocked(ws)} className="btn small" testId="dq-accept" onClick={() => set("accepted")}>Accept the risk</Guarded>
            </div>
            {error ? <ErrorBox error={error} onDismiss={() => setError(null)} /> : null}
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function DqSection({ ws, act }: TabProps) {
  if (!ws.dq.length) return <Empty testId="dq-empty">No data-quality checks have been run for this decision yet.</Empty>;
  const issues = ws.dq.filter((c) => c.severity !== "pass");
  const passes = ws.dq.length - issues.length;
  return (
    <div className="stack" data-testid="dq-section">
      <p className="small muted">{issues.length} finding(s) need attention; {passes} check(s) passed. Resolving or accepting a check after an assessment makes that assessment stale.</p>
      <div className="card tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Check</th><th>Severity</th><th>Finding</th><th>Status</th><th>Update</th></tr></thead>
          <tbody>{issues.map((c) => <DqRow key={c.id} check={c} ws={ws} act={act} />)}</tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- analyses
function numberOf(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The experiment status line. "inconclusive" when the confidence interval spans 0 (display of two stored numbers; the stance is the server's). */
export function experimentStatus(lo: number | null, hi: number | null): { label: string; text: string } {
  if (lo === null || hi === null) return { label: "unknown", text: "No confidence interval is stored." };
  if (lo <= 0 && hi >= 0) return { label: "inconclusive", text: "The confidence interval spans 0, so the data do not show the effect is different from no effect." };
  return { label: "interval excludes 0", text: "The confidence interval does not include 0." };
}

export function ExperimentPanel({ analysis }: { analysis: AnalysisOut }) {
  const r = analysis.result ?? {};
  const lo = numberOf(r.ci_low);
  const hi = numberOf(r.ci_high);
  const status = experimentStatus(lo, hi);
  const srm = (r.srm ?? null) as { flag?: boolean } | null;
  const power = (r.design_power ?? null) as { value?: number | null } | null;
  return (
    <section className="card" data-testid="experiment-panel">
      <h3>Experiment: {String(r.experiment_name ?? analysis.key ?? "experiment")}</h3>
      <p data-testid="experiment-status"><Pill tone={status.label === "inconclusive" ? "warn" : "info"}>Status: {status.label}</Pill> <span className="small">{status.text}</span></p>
      <p className="small">
        Effect {fmtNumber(numberOf(r.effect), 4)}, 95% interval {fmtNumber(lo, 4)} to {fmtNumber(hi, 4)}, n {analysis.n ?? "n/a"}, design {String(r.design ?? "n/a")}.
        {srm ? <> Sample-ratio check: {srm.flag ? "mismatch flagged" : "no mismatch"}.</> : null}
        {power && power.value !== null && power.value !== undefined ? <> Design power {fmtNumber(power.value, 2)} (a planning figure, not a result).</> : null}
      </p>
      {analysis.limitations ? <p className="small muted">{analysis.limitations}</p> : null}
    </section>
  );
}

export function HeterogeneityPanel({ analysis }: { analysis: AnalysisOut }) {
  const r = analysis.result ?? {};
  const flag = r.flag as boolean | null | undefined;
  const segments = (Array.isArray(r.segments) ? r.segments : []) as Array<Record<string, unknown>>;
  return (
    <section className="card" data-testid="heterogeneity" data-flag={String(flag)}>
      <h3>Heterogeneity by {String(r.segment_key ?? "segment")}</h3>
      <p>
        <Pill tone={flag ? "warn" : flag === false ? "ok" : "info"} testId="heterogeneity-flag">
          {flag ? "Heterogeneity flagged: the effect differs across segments" : flag === false ? "No heterogeneity flagged" : "Not enough eligible segments to judge"}
        </Pill>
      </p>
      <p className="small muted">An aggregate effect can hide opposite effects in segments. Only within-segment effects are compared. Aggregate effect {fmtNumber(numberOf(r.aggregate_effect), 4)}.</p>
      {segments.length ? (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Segment</th><th>Effect</th><th>n treatment</th><th>n comparison</th><th>Eligible</th></tr></thead>
            <tbody>
              {segments.map((s) => (
                <tr key={String(s.segment)}><td>{String(s.segment)}</td><td>{fmtNumber(numberOf(s.effect), 4)}</td><td>{String(s.n_treatment)}</td><td>{String(s.n_comparison)}</td><td>{s.eligible ? "yes" : "no"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function AnalysesSection({ ws, act }: TabProps) {
  const [details, setDetails] = useState<AnalysisOut[] | null>(null);
  const [error, setError] = useState<import("../../lib/api").ApiError | null>(null);
  const ids = ws.analyses.map((a) => a.id).join(",");
  useEffect(() => {
    let cancelled = false;
    Promise.all(ws.analyses.map((a) => api.analysis(a.id))).then(
      (d) => { if (!cancelled) setDetails(d); },
      (e) => { if (!cancelled) setError(e); },
    );
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);
  if (!ws.analyses.length) return <Empty testId="analyses-empty">No analyses have been run for this decision yet.</Empty>;
  return (
    <div className="stack" data-testid="analyses-section">
      {error ? <ErrorBox error={error} /> : null}
      {details?.filter((a) => a.analysis_type === "experiment").map((a) => <ExperimentPanel key={a.id} analysis={a} />)}
      {details?.filter((a) => a.analysis_type === "segmentation").map((a) => <HeterogeneityPanel key={a.id} analysis={a} />)}
      <div className="card tbl-wrap">
        <table className="tbl" data-testid="analyses-table">
          <thead><tr><th>Analysis</th><th>n</th><th>Effect</th><th>95% interval</th><th>Data quality</th><th>Creates evidence</th></tr></thead>
          <tbody>
            {ws.analyses.map((a) => {
              const d = details?.find((x) => x.id === a.id);
              const r = d?.result ?? {};
              return (
                <tr key={a.id} data-testid="analysis-row">
                  <td><button className="chip" onClick={() => act.openItem("analysis", a.id)} data-testid="analysis-open">{titleCase(a.analysis_type)}</button> <span className="small muted">{a.key ?? ""}</span></td>
                  <td>{a.n ?? "n/a"}</td>
                  <td>{fmtNumber(numberOf(r.effect), 4)}</td>
                  <td>{numberOf(r.ci_low) !== null ? `${fmtNumber(numberOf(r.ci_low), 4)} to ${fmtNumber(numberOf(r.ci_high), 4)}` : "n/a"}</td>
                  <td>{a.dq_status ? titleCase(a.dq_status) : "n/a"}</td>
                  <td>{a.creates_evidence ? "yes" : "no"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
