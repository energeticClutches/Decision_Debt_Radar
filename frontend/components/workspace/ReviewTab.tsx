"use client";

import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { hasAgentReview, NO_AUTOMATED_REVIEW } from "../../lib/actions";
import { sentences } from "../../lib/claims";
import { fmtDateTime, titleCase } from "../../lib/format";
import type { Finding, ReviewDetail, SynthesisOut } from "../../lib/types";
import { ClaimText } from "../ClaimText";
import { Empty, ErrorBox, Field, Modal, Pill, ProvenanceNotice, SeverityPill, StancePill } from "../ui";
import { Guarded } from "./Guarded";
import { ValidatedBadge, REVIEWER_COPY } from "./OverviewTab";
import { agentReviews, isLocked, latestSynthesis, type TabProps, type WorkspaceActions, type WorkspaceData } from "./types";

export const SYNTHESIS_HEADER = "AI-generated interpretation · validated by code checks · version";
export const VALIDATE_CHECKBOX = "I understand this validates the evidence assessment, not the decision.";

export function SynthesisHeader({ synthesis }: { synthesis: SynthesisOut }) {
  return (
    <div className="row center" data-testid="synthesis-header">
      <strong>{`${SYNTHESIS_HEADER} ${synthesis.version}`}</strong>
      <ProvenanceNotice provenance={synthesis.provenance} model={synthesis.model} />
    </div>
  );
}

const SECTION_TITLES: Array<["summary" | "supporting" | "contradicting" | "uncertainty", string]> = [
  ["summary", "What the evidence says"], ["supporting", "Supporting evidence"], ["contradicting", "Contradicting evidence"], ["uncertainty", "Uncertainty"],
];

export function SynthesisView({ synthesis, criteria, onOpenClaim }: { synthesis: SynthesisOut; criteria: string[]; onOpenClaim?: (id: string) => void }) {
  const out = synthesis.output;
  if (!out) return null;
  const known = new Set(out.claims.map((c) => c.local_id));
  return (
    <section className="card" data-testid="synthesis-view">
      <SynthesisHeader synthesis={synthesis} />
      {SECTION_TITLES.map(([key, title]) => (
        <div key={key} data-testid={`synthesis-${key}`}>
          <h3 style={{ marginTop: 10 }}>{title}</h3>
          {out.sections[key] ? sentences(out.sections[key]).map((s, i) => <p key={i} style={{ margin: "0 0 4px" }}><ClaimText text={s} known={known} onOpen={onOpenClaim} /></p>) : <p className="small muted">Nothing is stated here.</p>}
        </div>
      ))}
      <h3>Claims</h3>
      <div className="tbl-wrap">
        <table className="tbl" data-testid="claims-table">
          <thead><tr><th>Claim</th><th>Text</th><th>Type</th><th>Stance</th><th>Confidence</th></tr></thead>
          <tbody>
            {out.claims.map((c) => (
              <tr key={c.local_id} data-testid="claim-row">
                <td>{onOpenClaim ? <button className="chip" onClick={() => onOpenClaim(c.local_id)}>{c.local_id}</button> : <span className="chip">{c.local_id}</span>}</td>
                <td className="small">{c.text}</td><td>{titleCase(c.claim_type)}</td><td><StancePill stance={c.stance} /></td><td>{titleCase(c.confidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Gaps and uncertainties</h3>
      <ul style={{ margin: 0, paddingLeft: 18 }} data-testid="synthesis-gaps">
        {out.gaps.map((g, i) => <li key={`g${i}`} className="small">Gap ({titleCase(g.gap_type)}): {g.text}</li>)}
        {out.uncertainties.map((u, i) => <li key={`u${i}`} className="small">Uncertainty: {u.text}</li>)}
        {!out.gaps.length && !out.uncertainties.length ? <li className="small muted">None stated.</li> : null}
      </ul>
      <h3>What would change the conclusion</h3>
      {out.criteria_assessment.length ? (
        <ul style={{ margin: 0, paddingLeft: 18 }} data-testid="criteria-assessment">
          {out.criteria_assessment.map((c) => <li key={c.criterion_index} className="small">{criteria[c.criterion_index] ?? `Criterion ${c.criterion_index + 1}`}: <Pill>{titleCase(c.status)}</Pill></li>)}
        </ul>
      ) : <p className="small muted">No criterion was assessed.</p>}
    </section>
  );
}

export function ValidatorReportView({ synthesis }: { synthesis: SynthesisOut }) {
  const r = synthesis.validator_report;
  const dropped = (r.dropped ?? []) as Array<Record<string, unknown>>;
  const reclassified = (r.reclassified ?? []) as Array<Record<string, unknown>>;
  return (
    <details className="disclosure card" data-testid="validator-report">
      <summary>Validator report: {synthesis.claims_dropped} claim(s) dropped, {reclassified.length} reclassified</summary>
      {dropped.length ? (
        <ul>{dropped.map((d, i) => <li key={i} className="small"><span className="mono">{String(d.local_id ?? d.claim ?? "claim")}</span> dropped by {String(d.rule ?? "a rule")}: {String(d.reason ?? "")}</li>)}</ul>
      ) : <p className="small muted">No claim was dropped.</p>}
      {reclassified.length ? (
        <ul>{reclassified.map((d, i) => <li key={i} className="small"><span className="mono">{String(d.local_id ?? "claim")}</span>: {String(d.reason ?? JSON.stringify(d))}</li>)}</ul>
      ) : null}
    </details>
  );
}

export function FindingsView({ review, onOpen }: { review: ReviewDetail; onOpen?: (index: number) => void }) {
  const groups: Array<[string, string]> = [["blocking", "Blocking"], ["warning", "Warning"], ["info", "Info"]];
  return (
    <section className="card" data-testid="findings">
      <div className="row center">
        <h3 style={{ margin: 0 }}>Reviewer findings</h3>
        <Pill tone={review.verdict === "ready" ? "ok" : "bad"} testId="reviewer-verdict">{review.verdict === "ready" ? "✓ Verdict: ready" : "⊘ Verdict: needs rework"}</Pill>
        <ProvenanceNotice provenance={review.provenance} model={review.model} />
      </div>
      <p className="small muted" data-testid="reviewer-copy">{REVIEWER_COPY}</p>
      {groups.map(([sev, title]) => {
        const items = review.findings.map((f, i) => ({ f, i })).filter(({ f }) => f.severity === sev);
        return (
          <div key={sev} data-testid={`findings-${sev}`}>
            <h3>{title} ({items.length})</h3>
            {items.length ? items.map(({ f, i }) => <FindingRow key={i} f={f} index={i} onOpen={onOpen} />) : <p className="small muted">None.</p>}
          </div>
        );
      })}
    </section>
  );
}

function FindingRow({ f, index, onOpen }: { f: Finding; index: number; onOpen?: (index: number) => void }) {
  return (
    <div className="banner" style={{ marginBottom: 6 }} data-testid={`finding-${f.severity}`} data-category={f.category ?? ""}>
      <div className="row center">
        <SeverityPill severity={f.severity} />
        <Pill tone={f.source === "code" ? "info" : undefined} testId="finding-source">{f.source === "code" ? "Automated check" : "Reviewer"}</Pill>
        <span className="mono">{f.category}</span>
        {f.target_local_id ? <span className="small muted">on claim {f.target_local_id}</span> : f.target_type ? <span className="small muted">on the {f.target_type}</span> : null}
        {onOpen ? <button className="chip right" onClick={() => onOpen(index)}>Details</button> : null}
      </div>
      <div className="small">{f.rationale}</div>
      {f.notes.map((n) => <div key={n} className="small muted">{n}</div>)}
    </div>
  );
}

function Controls({ ws, act }: { ws: WorkspaceData; act: WorkspaceActions }) {
  const { decision, assessment } = ws;
  const stage = decision.lifecycle_stage;
  const reviewable = (stage === "assessed" || stage === "challenged") && !decision.assessment_stale && !!assessment && assessment.state !== "partial";
  const reviews = ws.reviews;
  const latest = reviews.length ? reviews[reviews.length - 1] : null;
  const rework = latest?.verdict === "needs_rework";
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const locked = isLocked(ws);
  const doOverride = async () => {
    if (!assessment) return;
    setError(null);
    const r = await act.perform("Recording the review", () => api.postReview(assessment.id, "ready", reason.trim()));
    if (r.ok) setReason("");
    else setError(r.error);
  };
  const doResynthesise = async () => {
    if (!assessment) return;
    const r = await act.perform("Re-synthesising", () => api.resynthesise(assessment.id, true));
    if (!r.ok) setError(r.error);
  };
  const canValidate = stage === "challenged" && !!latest && latest.verdict === "ready";
  return (
    <section className="card" data-testid="review-controls">
      <h3>Actions</h3>
      {error ? <ErrorBox error={error} onDismiss={() => setError(null)} /> : null}
      {!reviewable && !locked && stage !== "validated" ? <p className="small muted" data-testid="review-not-available">Review actions are available once the assessment is current. {decision.assessment_stale ? "Re-run the assessment first." : ""}</p> : null}
      <div className="row">
        <Guarded action="run_synthesis" decision={decision} me={ws.me} locked={locked} extraDisabled={!reviewable} testId="resynthesise" onClick={doResynthesise}>Re-synthesise</Guarded>
        <Guarded action="validate" decision={decision} me={ws.me} locked={locked} extraDisabled={!canValidate} testId="validate-open" className="btn primary" onClick={act.openValidate}>Validate the assessment</Guarded>
      </div>
      {rework ? <p className="small muted">A needs-rework verdict blocks validation until a person overrides it with a reason.</p> : null}
      <div className="stack" style={{ marginTop: 10 }} data-testid="override-form">
        <Field label={rework ? "Human override: reason (required)" : "Record a human review: reason (required)"} htmlFor="override-reason">
          <textarea id="override-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="override-reason" />
        </Field>
        <div>
          <Guarded action="human_review" decision={decision} me={ws.me} locked={locked} extraDisabled={!reviewable || !reason.trim()} testId={rework ? "rework-override" : "human-review-ready"} className="btn" onClick={doOverride}>
            {rework ? "Override with this reason (mark ready)" : "Record review: ready"}
          </Guarded>
        </div>
      </div>
    </section>
  );
}

export function ReviewTab({ ws, act }: TabProps) {
  const syn = latestSynthesis(ws);
  const agents = agentReviews(ws);
  const latestAgent = agents.length ? agents[agents.length - 1] : null;
  const failedSyn = ws.syntheses.length ? ws.syntheses[ws.syntheses.length - 1] : null;
  const openClaim = (id: string) => act.openItem("claim", id);
  return (
    <div className="stack" data-testid="tab-panel-review">
      <ValidatedBadge stage={ws.decision.lifecycle_stage} />
      {!ws.assessment ? <Empty testId="no-assessment">No assessment yet, so there is nothing to review.</Empty> : null}
      {ws.assessment && !syn ? (
        <section className="card" data-testid="no-synthesis">
          <h3>Evidence synthesis</h3>
          {failedSyn ? (
            <p>The latest synthesis is <strong>{titleCase(failedSyn.status)}</strong>{failedSyn.validator_report.error_class ? ` (${failedSyn.validator_report.error_class})` : ""}. It is recorded as a failure, never as a pass.</p>
          ) : <p>No synthesis exists for this assessment yet.</p>}
          <Pill tone="warn">{NO_AUTOMATED_REVIEW}</Pill>
        </section>
      ) : null}
      {syn ? <SynthesisView synthesis={syn} criteria={ws.decision.change_my_mind_criteria} onOpenClaim={openClaim} /> : null}
      {syn ? <ValidatorReportView synthesis={syn} /> : null}
      {ws.assessment && !hasAgentReview(ws.reviews) && syn ? <div className="banner warn" data-testid="review-failed">{NO_AUTOMATED_REVIEW}</div> : null}
      {latestAgent ? <FindingsView review={latestAgent} onOpen={(i) => act.openItem("finding", `${latestAgent.id}.${i}`)} /> : null}
      {ws.reviews.filter((r) => r.reviewer_type === "human").length ? (
        <section className="card" data-testid="human-reviews">
          <h3>Human reviews</h3>
          {ws.reviews.filter((r) => r.reviewer_type === "human").map((r) => (
            <p key={r.id} className="small"><Pill tone={r.verdict === "ready" ? "ok" : "bad"}>{titleCase(r.verdict)}</Pill> {r.human_response ?? ""} <span className="muted">{fmtDateTime(r.created_at)}</span></p>
          ))}
        </section>
      ) : null}
      {ws.assessment ? <Controls ws={ws} act={act} /> : null}
    </div>
  );
}

export function ValidateDialog({ ws, act, onClose }: { ws: WorkspaceData; act: WorkspaceActions; onClose: () => void }) {
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const r = await act.perform("Validating", () => api.validate(ws.decision.id));
    setBusy(false);
    if (r.ok) onClose();
    else setError(r.error);
  };
  return (
    <Modal title="Validate the assessment" onClose={onClose} testId="validate-dialog">
      <p>Validation records that the evidence assessment passed review. It does not approve the decision: a person records the decision separately.</p>
      <label className="row center" style={{ marginBottom: 10 }}>
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} data-testid="validate-checkbox" />
        <span>{VALIDATE_CHECKBOX}</span>
      </label>
      {error ? <ErrorBox error={error} onDismiss={() => setError(null)} /> : null}
      <div className="row">
        <Guarded action="validate" decision={ws.decision} me={ws.me} locked={isLocked(ws)} extraDisabled={!checked || busy} testId="validate-confirm" className="btn primary" onClick={go}>Validate</Guarded>
        <button className="btn" onClick={onClose} data-testid="validate-cancel">Cancel</button>
      </div>
    </Modal>
  );
}
