"use client";

import Link from "next/link";

import { api } from "../lib/api";
import { headline } from "../lib/actions";
import { fmtDate, titleCase } from "../lib/format";
import { useIdentity } from "../lib/identity";
import type { DecisionOut } from "../lib/types";
import { useResource } from "../lib/useResource";
import { canOnDecision } from "../lib/actions";
import { Empty, ErrorBox, Icon, Loading, Pill } from "./ui";

/** One decision of the portfolio. Exactly one headline: "DDI x · Band", INSUFFICIENT EVIDENCE or Stale. previous_scored_assessment is never read. */
export function PortfolioCard({ decision }: { decision: DecisionOut }) {
  const h = headline(decision);
  const cur = decision.current_assessment;
  const showDirection = cur && cur.state !== "partial" && !decision.assessment_stale && cur.evidence_direction;
  return (
    <article className={`card${h.kind === "stale" ? " stale" : ""}`} data-testid={`decision-card-${decision.id}`} data-headline={h.kind}>
      <div className="row center">
        <h2 style={{ margin: 0 }}><Link href={`/decisions/${decision.id}`} data-testid="decision-link">{decision.title}</Link></h2>
        <Pill>{titleCase(decision.decision_type)}</Pill>
        <Pill tone="info" testId="lifecycle-label">{decision.lifecycle_label}</Pill>
      </div>
      <div className="row center" style={{ marginTop: 8 }}>
        {h.kind === "scored" ? (
          <span className="big sm" data-testid="headline" data-ddi-value={cur?.ddi ?? undefined}>{h.text}</span>
        ) : h.kind === "gated" ? (
          <span className="big sm" data-testid="headline"><Icon name="stop" size={24} /> {h.text}</span>
        ) : h.kind === "stale" ? (
          <span className="big sm" data-testid="headline"><Icon name="clock" size={24} /> {h.text}</span>
        ) : (
          <span className="big sm muted" data-testid="headline">{h.text}</span>
        )}
      </div>
      <div className="row small muted" style={{ marginTop: 8 }}>
        <span data-testid="direction">Direction: {showDirection ? titleCase(cur?.evidence_direction) : "n/a"}</span>
        <span data-testid="pending-approvals">Pending approvals: {decision.pending_approvals}</span>
        <span data-testid="due-date">Due {fmtDate(decision.decision_due_date)}</span>
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>{decision.hypothesis}</p>
    </article>
  );
}

export function PortfolioList({ decisions }: { decisions: DecisionOut[] }) {
  if (!decisions.length) return <Empty testId="portfolio-empty">No decisions yet. Create the first one.</Empty>;
  return (
    <div className="stack">
      {decisions.map((d) => <PortfolioCard key={d.id} decision={d} />)}
    </div>
  );
}

export function Portfolio() {
  const { me, ready } = useIdentity();
  const res = useResource(() => api.decisions(), [me?.id], ready && !!me);
  return (
    <div className="stack">
      <div className="row center">
        <h1 style={{ margin: 0 }}>Decision portfolio</h1>
        <span className="small muted">All FitConnect data is synthetic. DDI is an evidence-risk heuristic, not a measure of decision quality.</span>
        <span className="right" />
        {canOnDecision(me, "create_decision", null) ? <Link className="btn primary" href="/decisions/new" data-testid="new-decision">New decision</Link> : (
          <button className="btn" disabled title="Only a Product Manager or Business Analyst can create a decision" data-testid="new-decision">New decision</button>
        )}
      </div>
      {res.error ? <ErrorBox error={res.error} onRetry={res.reload} /> : null}
      {res.loading && !res.data ? <Loading label="Loading decisions" /> : null}
      {res.data ? <PortfolioList decisions={res.data} /> : null}
    </div>
  );
}
