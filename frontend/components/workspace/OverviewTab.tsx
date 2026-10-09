"use client";

import { canOnDecision, hasAgentReview, NO_AUTOMATED_REVIEW } from "../../lib/actions";
import { fmtDateTime, titleCase } from "../../lib/format";
import type { EvidenceOut } from "../../lib/types";
import { DdiCard, DirectionCard, GateCard, NbeTable, PartialCard, StaleBanner } from "../assessment/Cards";
import { Empty, StancePill, Pill } from "../ui";
import { agentReviews, isLocked, type TabProps } from "./types";

export const VALIDATED_BADGE = "Assessment validated by review";
export const VALIDATED_NOTE = "The evidence assessment passed review. This does not mean the decision is correct.";
export const REVIEWER_COPY = "Verdict derived by code from finding severities.";

const GRADE_ORDER: Record<string, number> = { A: 0, B: 1, C: 2, D: 3 };

function topItems(evidence: EvidenceOut[], stance: string, n: number): EvidenceOut[] {
  return evidence.filter((e) => e.status === "active" && e.stance === stance)
    .sort((a, b) => (GRADE_ORDER[a.strength_grade] ?? 9) - (GRADE_ORDER[b.strength_grade] ?? 9)).slice(0, n);
}

export function ValidatedBadge({ stage }: { stage: string }) {
  if (stage !== "validated" && stage !== "decided") return null;
  return (
    <div className="banner ok" data-testid="validated-badge">
      <strong><span aria-hidden="true">{"✓"}</span> {VALIDATED_BADGE}</strong>
      <div className="small">{VALIDATED_NOTE}</div>
    </div>
  );
}

export function OverviewTab({ ws, act }: TabProps) {
  const { decision, assessment } = ws;
  const stale = decision.assessment_stale;
  const gated = assessment?.state === "insufficient_evidence";
  const canRerun = canOnDecision(ws.me, "run_assessment", decision) && !isLocked(ws);
  const agent = agentReviews(ws);
  const latest = agent.length ? agent[agent.length - 1] : null;
  const supports = topItems(ws.evidence, "supports", 3);
  const contradicts = topItems(ws.evidence, "contradicts", 3);
  return (
    <div className="stack" data-testid="tab-panel-overview">
      <ValidatedBadge stage={decision.lifecycle_stage} />
      <StaleBanner decision={decision} onRerun={act.runPipeline} canRerun={canRerun} rerunHint={canRerun ? undefined : "Allowed roles: Product Manager, Business Analyst, Product Analyst"} />
      <div className="row">
        <div className="grow">
          {assessment ? (
            <>
              <DdiCard assessment={assessment} stale={stale} />
              <GateCard assessment={assessment} recommendations={ws.recommendations} onOpenDq={() => act.goTab("evidence")} />
              <PartialCard assessment={assessment} />
            </>
          ) : <Empty testId="no-assessment">No assessment yet. Run the assessment to see the Decision Debt Index or the reasons it cannot be scored.</Empty>}
        </div>
        <div className="grow">{assessment ? <DirectionCard assessment={assessment} /> : null}</div>
      </div>
      {assessment ? <NbeTable recommendations={ws.recommendations} gated={!!gated} stale={stale} limit={3} /> : null}

      <section className="card" data-testid="overview-review">
        <h3>Review</h3>
        {latest ? (
          <>
            <div className="row center">
              <Pill tone={latest.verdict === "ready" ? "ok" : "bad"} testId="overview-verdict">
                {latest.verdict === "ready" ? "✓ Ready" : "⊘ Needs rework"}
              </Pill>
              <span className="small muted">{REVIEWER_COPY}</span>
            </div>
            <p className="small">{latest.findings.filter((f) => f.severity === "blocking").length} blocking, {latest.findings.filter((f) => f.severity === "warning").length} warning, {latest.findings.filter((f) => f.severity === "info").length} info findings.</p>
          </>
        ) : assessment && decision.lifecycle_stage !== "created" ? (
          <p data-testid="overview-no-review"><Pill tone="warn">{NO_AUTOMATED_REVIEW}</Pill></p>
        ) : <p className="muted small">No review yet.</p>}
        {ws.reviews.filter((r) => r.reviewer_type === "human").map((r) => (
          <p key={r.id} className="small">Human review: {titleCase(r.verdict)}{r.human_response ? ` - ${r.human_response}` : ""} <span className="muted">({fmtDateTime(r.created_at)})</span></p>
        ))}
        {!hasAgentReview(ws.reviews) ? null : null}
      </section>

      <div className="row">
        {[{ title: "Top supporting evidence", items: supports }, { title: "Top contradicting evidence", items: contradicts }].map((group) => (
          <section key={group.title} className="card grow" data-testid={`overview-${group.title.includes("supporting") ? "supporting" : "contradicting"}`}>
            <h3>{group.title}</h3>
            {group.items.length ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {group.items.map((e) => (
                  <li key={e.id}>
                    <button className="chip" onClick={() => act.openItem("evidence", e.id)}>{titleCase(e.evidence_type)} · grade {e.strength_grade}</button>{" "}
                    <StancePill stance={e.stance} /> <span className="small">{e.summary.slice(0, 140)}{e.summary.length > 140 ? "..." : ""}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="muted small">None among the active evidence.</p>}
          </section>
        ))}
      </div>

      {ws.record ? (
        <section className="card" data-testid="overview-record">
          <h3>Decision record</h3>
          <p><strong>{titleCase(ws.record.outcome)}</strong> on {fmtDateTime(ws.record.decided_at)}{ws.record.acknowledged_risk ? " (risk acknowledged)" : ""}</p>
          <p>{ws.record.rationale}</p>
        </section>
      ) : null}
    </div>
  );
}
