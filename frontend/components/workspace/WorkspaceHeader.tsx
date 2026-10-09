"use client";

import { nextAction, statusStrip, type NextAction, type StatusStrip } from "../../lib/actions";
import { STAGES } from "../../lib/format";
import type { DecisionOut, LifecycleStage, ReviewDetail, UserOut, AssessmentOut } from "../../lib/types";
import { Icon } from "../ui";

const STEP_NAMES: Record<LifecycleStage, string> = {
  created: "Created", evidence_gathered: "Evidence", assessed: "Assessed", challenged: "Challenged", validated: "Validated", decided: "Decided",
};

export function Stepper({ decision }: { decision: Pick<DecisionOut, "lifecycle_stage" | "lifecycle_label"> }) {
  const current = STAGES.indexOf(decision.lifecycle_stage);
  return (
    <div data-testid="stepper" data-stage={decision.lifecycle_stage}>
      <ol style={{ display: "flex", flexWrap: "wrap", gap: 6, listStyle: "none", padding: 0, margin: 0 }} aria-label="Decision lifecycle">
        {STAGES.map((s, i) => (
          <li key={s} aria-current={i === current ? "step" : undefined} data-step={s} data-state={i < current ? "done" : i === current ? "current" : "todo"}
            className={`badge ${i < current ? "ok" : i === current ? "info" : ""}`}>
            {i < current ? "✓ " : i === current ? "▶ " : ""}{STEP_NAMES[s]}
          </li>
        ))}
      </ol>
      <div className="small muted" data-testid="lifecycle-label">{decision.lifecycle_label}</div>
    </div>
  );
}

export function StripView({ strip }: { strip: StatusStrip }) {
  const tone = strip.kind === "decided" ? "info" : strip.kind === "stale" ? "stale" : strip.kind === "normal" ? "ok" : strip.kind === "pending_approvals" ? "info" : "warn";
  return (
    <div className={`banner ${tone}`} role="status" data-testid="status-strip" data-kind={strip.kind}>
      <Icon name={strip.icon} /> {strip.text}
    </div>
  );
}

/** The sticky header of the workspace: title, hypothesis, owner and team, the stepper, the status strip and ONE next-action button. */
export function WorkspaceHeader({ decision, assessment, reviews, me, owner, busy, onNext }: {
  decision: DecisionOut;
  assessment: AssessmentOut | null;
  reviews: ReviewDetail[];
  me: UserOut | null;
  owner: UserOut | null;
  busy: boolean;
  onNext: (next: NextAction) => void;
}) {
  const strip = statusStrip(decision, assessment, reviews);
  const next = nextAction(decision, assessment, reviews, me);
  return (
    <div className="card" style={{ position: "sticky", top: 0, zIndex: 30 }} data-testid="workspace-header">
      <div className="row center">
        <h1 style={{ margin: 0 }} data-testid="workspace-title">{decision.title}</h1>
        <span className="small muted">{owner ? `Owner: ${owner.name}${owner.team_name ? `, ${owner.team_name}` : ""}` : ""}</span>
      </div>
      <p className="small muted" style={{ margin: "4px 0 8px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={decision.hypothesis} data-testid="workspace-hypothesis">{decision.hypothesis}</p>
      <div className="row center">
        <div className="grow"><Stepper decision={decision} /></div>
      </div>
      <div className="row center" style={{ marginTop: 8 }}>
        <div className="grow"><StripView strip={strip} /></div>
        {next ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <button className="btn primary" disabled={!next.enabled || busy} onClick={() => onNext(next)} data-testid="next-action" data-action={next.id} title={next.disabledReason ?? undefined}>
              {next.label}
            </button>
            {next.disabledReason ? <span className="small muted" data-testid="next-action-reason">{next.disabledReason}</span> : null}
          </div>
        ) : <span className="badge info" data-testid="next-action-none"><Icon name="lock" /> No further action</span>}
      </div>
    </div>
  );
}
