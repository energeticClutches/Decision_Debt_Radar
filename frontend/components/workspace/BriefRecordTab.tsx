"use client";

import Link from "next/link";
import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { fmtDateTime, titleCase } from "../../lib/format";
import { Empty, ErrorBox, Field, Pill } from "../ui";
import { Guarded } from "./Guarded";
import { isLocked, type TabProps } from "./types";

export const DEFER_WARNING = "Defer returns the decision to evidence gathering and makes the assessment stale.";
const OUTCOMES: Array<[string, string]> = [["approve", "Approve"], ["approve_conditional", "Approve with conditions"], ["reject", "Reject"], ["defer", "Defer"]];

export function BriefRecordTab({ ws, act }: TabProps) {
  const { decision, assessment } = ws;
  const locked = isLocked(ws);
  const [briefError, setBriefError] = useState<ApiError | null>(null);
  const [outcome, setOutcome] = useState("approve");
  const [rationale, setRationale] = useState("");
  const [ack, setAck] = useState(false);
  const [recError, setRecError] = useState<ApiError | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const stage = decision.lifecycle_stage;

  const create = async (kind: "decision_brief" | "gated_evidence_summary") => {
    if (!assessment) return;
    setBriefError(null);
    setCreated(null);
    const r = await act.perform("Creating the brief", () => api.createBrief(assessment.id, kind));
    if (r.ok) setCreated(r.value.id);
    else setBriefError(r.error);
  };
  const record = async () => {
    setRecError(null);
    const r = await act.perform("Recording the decision", () => api.recordDecision(decision.id, { outcome, rationale: rationale.trim(), acknowledged_risk: ack }));
    if (!r.ok) setRecError(r.error);
  };
  const fieldErr = recError?.fieldErrors ?? {};
  const ackProblem = recError && (recError.detail?.code === "acknowledgement_required" || /acknowledg/i.test(recError.message)) ? recError.message : fieldErr.acknowledged_risk;
  const rationaleProblem = recError && /rationale/i.test(recError.message) ? recError.message : fieldErr.rationale;
  const otherProblem = recError && !ackProblem && !rationaleProblem ? recError : null;

  return (
    <div className="stack" data-testid="tab-panel-brief">
      <section className="card" data-testid="brief-section">
        <h3>Briefs</h3>
        <p className="small muted">A Decision Brief exists only after the assessment is validated. A Gated Evidence Summary exists only for an INSUFFICIENT EVIDENCE assessment. Neither contains a recommendation.</p>
        {briefError ? <div data-testid="brief-error"><ErrorBox error={briefError} onDismiss={() => setBriefError(null)} /></div> : null}
        <div className="row">
          <Guarded action="create_brief" decision={decision} me={ws.me} locked={locked} extraDisabled={!assessment} testId="create-decision-brief" className="btn primary" onClick={() => create("decision_brief")}>Create Decision Brief</Guarded>
          <Guarded action="create_brief" decision={decision} me={ws.me} locked={locked} extraDisabled={!assessment} testId="create-gated-summary" className="btn" onClick={() => create("gated_evidence_summary")}>Create Gated Evidence Summary</Guarded>
        </div>
        {created ? <p data-testid="brief-created"><Link href={`/briefs/${created}`}>Open the new brief</Link></p> : null}
        <h3 style={{ marginTop: 12 }}>Briefs of this assessment</h3>
        {ws.briefs.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }} data-testid="brief-list">
            {ws.briefs.map((b) => (
              <li key={b.id} data-testid="brief-list-item"><Link href={`/briefs/${b.id}`}>{b.label} (version {b.version})</Link> <span className="small muted">{fmtDateTime(b.created_at)}</span></li>
            ))}
          </ul>
        ) : <p className="small muted" data-testid="brief-list-empty">No brief has been created for this assessment.</p>}
      </section>

      <section className="card" data-testid="record-section">
        <h3>Decision record</h3>
        {ws.record && stage === "decided" ? (
          <div data-testid="record-existing">
            <p><Pill tone="ok">{titleCase(ws.record.outcome)}</Pill> {fmtDateTime(ws.record.decided_at)}{ws.record.acknowledged_risk ? " · risk acknowledged" : ""}</p>
            <p>{ws.record.rationale}</p>
          </div>
        ) : null}
        {stage === "decided" ? <div className="banner info" data-testid="decided-lock">Decision recorded. Writes are frozen.</div> : (
          <div className="stack">
            <p className="small muted">A person records the decision. DDI and the assessment inform it; they do not make it.</p>
            <Field label="Outcome" htmlFor="record-outcome">
              <select id="record-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} data-testid="record-outcome">
                {OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            {outcome === "defer" ? <div className="banner warn small" data-testid="defer-warning">{DEFER_WARNING}</div> : null}
            <Field label="Rationale" htmlFor="record-rationale" error={rationaleProblem}>
              <textarea id="record-rationale" rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} data-testid="record-rationale" />
            </Field>
            <Field label="" error={ackProblem}>
              <label className="row center">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="record-ack" />
                <span>I acknowledge the risk: this decision rests on high evidence debt or on insufficient evidence.</span>
              </label>
            </Field>
            {otherProblem ? <ErrorBox error={otherProblem} onDismiss={() => setRecError(null)} /> : null}
            {stage !== "validated" ? <p className="small muted" data-testid="record-not-ready">A decision can be recorded once the assessment is validated by review.</p> : null}
            <div>
              <Guarded action="record_decision" decision={decision} me={ws.me} locked={locked} extraDisabled={stage !== "validated" || !rationale.trim()} testId="record-submit" className="btn primary" onClick={record}>Record the decision</Guarded>
            </div>
          </div>
        )}
        {!ws.record && stage === "decided" ? <Empty>No record is available.</Empty> : null}
      </section>
    </div>
  );
}
