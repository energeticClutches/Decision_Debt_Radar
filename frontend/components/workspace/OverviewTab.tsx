"use client";

import { canOnDecision, hasAgentReview, NO_AUTOMATED_REVIEW } from "../../lib/actions";
import { fmtDateTime, titleCase } from "../../lib/format";
import type { EvidenceOut } from "../../lib/types";
import { DdiCard, DirectionCard, GateCard, NbeTable, PartialCard, StaleBanner } from "../assessment/Cards";
import { SvgIcon } from "../icons";
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
      <strong><SvgIcon name="check" size={14} /> {VALIDATED_BADGE}</strong>
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
  const counts = {
    blocking: latest ? latest.findings.filter((f) => f.severity === "blocking").length : 0,
    warning: latest ? latest.findings.filter((f) => f.severity === "warning").length : 0,
    info: latest ? latest.findings.filter((f) => f.severity === "info").length : 0,
  };
  const supports = topItems(ws.evidence, "supports", 3);
  const contradicts = topItems(ws.evidence, "contradicts", 3);
  return (
    <div className="stack" data-testid="tab-panel-overview">
      <ValidatedBadge stage={decision.lifecycle_stage} />
      <StaleBanner decision={decision} onRerun={act.runPipeline} canRerun={canRerun} rerunHint={canRerun ? undefined : "Allowed roles: Product Manager, Business Analyst, Product Analyst"} />
      <div className="grid">
        <div className="span-6 stack">
          {assessment ? (
            <>
              <DdiCard assessment={assessment} stale={stale} />
              <GateCard assessment={assessment} recommendations={ws.recommendations} onOpenDq={() => act.goTab("evidence")} />
              <PartialCard assessment={assessment} />
            </>
          ) : <Empty testId="no-assessment">No assessment yet. Run the assessment to see the Decision Debt Index or the reasons it cannot be scored.</Empty>}
        </div>
        <div className="span-6">{assessment ? <DirectionCard assessment={assessment} /> : null}</div>
      </div>
      {assessment ? <NbeTable recommendations={ws.recommendations} gated={!!gated} stale={stale} limit={3} /> : null}

      <div className="grid">
        <section className="card span-6" data-testid="overview-review">
          <div className="card-title"><SvgIcon name="doc" size={16} />Review</div>
          {latest ? (
            <>
              <div className="row center">
                <Pill tone={latest.verdict === "ready" ? "ok" : "bad"} testId="overview-verdict">
                  {latest.verdict === "ready" ? <SvgIcon name="check" size={12} /> : <SvgIcon name="stop" size={12} />}{latest.verdict === "ready" ? " Ready" : " Needs rework"}
                </Pill>
              </div>
              <p className="callout">{REVIEWER_COPY}</p>
              <div className="tiles" aria-hidden="true">
                <div className="tile"><div className="label"><SvgIcon name="stop" size={12} />Blocking</div><div className="value">{counts.blocking}</div></div>
                <div className="tile"><div className="label"><SvgIcon name="alert" size={12} />Warning</div><div className="value">{counts.warning}</div></div>
                <div className="tile"><div className="label"><SvgIcon name="info" size={12} />Info</div><div className="value">{counts.info}</div></div>
              </div>
              <p className="sr-only">{counts.blocking} blocking, {counts.warning} warning, {counts.info} info findings.</p>
            </>
          ) : assessment && decision.lifecycle_stage !== "created" ? (
            <p data-testid="overview-no-review"><Pill tone="warn">{NO_AUTOMATED_REVIEW}</Pill></p>
          ) : <p className="muted small">No review yet.</p>}
          {ws.reviews.filter((r) => r.reviewer_type === "human").map((r) => (
            <p key={r.id} className="small">Human review: {titleCase(r.verdict)}{r.human_response ? ` - ${r.human_response}` : ""} <span className="muted">({fmtDateTime(r.created_at)})</span></p>
          ))}
          {!hasAgentReview(ws.reviews) ? null : null}
        </section>

        <div className="card span-6">
          {[{ title: "Top supporting evidence", items: supports, icon: "up" }, { title: "Top contradicting evidence", items: contradicts, icon: "down" }].map((group) => (
            <section key={group.title} className="ev-group" data-testid={`overview-${group.title.includes("supporting") ? "supporting" : "contradicting"}`}>
              <h3><SvgIcon name={group.icon} size={14} />{group.title}</h3>
              {group.items.length ? (
                <ul className="ev-list">
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
      </div>

      {ws.record ? (
        <section className="card" data-testid="overview-record">
          <div className="card-title"><SvgIcon name="lock" size={16} />Decision record</div>
          <p><strong>{titleCase(ws.record.outcome)}</strong> on {fmtDateTime(ws.record.decided_at)}{ws.record.acknowledged_risk ? " (risk acknowledged)" : ""}</p>
          <p>{ws.record.rationale}</p>
        </section>
      ) : null}
    </div>
  );
}
