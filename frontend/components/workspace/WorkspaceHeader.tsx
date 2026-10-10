"use client";

import { createPortal } from "react-dom";

import { nextAction, statusStrip, type NextAction, type StatusStrip } from "../../lib/actions";
import { STAGES } from "../../lib/format";
import type { DecisionOut, LifecycleStage, ReviewDetail, UserOut, AssessmentOut } from "../../lib/types";
import { SvgIcon } from "../icons";
import { useTabsSlot } from "../AppShell";
import { Icon } from "../ui";

const STEP_NAMES: Record<LifecycleStage, string> = {
  created: "Created", evidence_gathered: "Evidence", assessed: "Assessed", challenged: "Challenged", validated: "Validated", decided: "Decided",
};

export function Stepper({ decision }: { decision: Pick<DecisionOut, "lifecycle_stage" | "lifecycle_label"> }) {
  const current = STAGES.indexOf(decision.lifecycle_stage);
  return (
    <div data-testid="stepper" data-stage={decision.lifecycle_stage}>
      <ol className="stepper" aria-label="Decision lifecycle">
        {STAGES.map((s, i) => (
          <li key={s} aria-current={i === current ? "step" : undefined} data-step={s} data-state={i < current ? "done" : i === current ? "current" : "todo"}>
            <span className="step">
              <span className="node" aria-hidden="true">{i < current ? <SvgIcon name="check" size={12} /> : i + 1}</span>
              <span className="step-label">{STEP_NAMES[s]}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="small muted lifecycle-label" data-testid="lifecycle-label">{decision.lifecycle_label}</div>
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
    <div className="card" data-testid="workspace-header">
      <div className="ws-head">
        <div className="titles">
          <h1 data-testid="workspace-title">{decision.title}</h1>
          <div className="meta">{owner ? `Owner: ${owner.name}${owner.team_name ? `, ${owner.team_name}` : ""}` : ""}</div>
        </div>
        <div className="action">
          {next ? (
            <>
              <button className="btn primary" disabled={!next.enabled || busy} onClick={() => onNext(next)} data-testid="next-action" data-action={next.id} title={next.disabledReason ?? undefined}>
                {next.label}
              </button>
              {next.disabledReason ? <span className="small muted" data-testid="next-action-reason">{next.disabledReason}</span> : null}
            </>
          ) : <span className="badge info" data-testid="next-action-none"><Icon name="lock" /> No further action</span>}
        </div>
      </div>
      <div className="callout hypothesis">
        <SvgIcon name="bulb" size={16} />
        <span className="text" title={decision.hypothesis} data-testid="workspace-hypothesis">{decision.hypothesis}</span>
      </div>
      <Stepper decision={decision} />
      <div className="ws-status"><StripView strip={strip} /></div>
    </div>
  );
}

/** The workspace tabs. They are rendered into the top bar as underline tabs (a portal) and fall back to an inline row where there is no bar. */
export function WorkspaceTabs<T extends string>({ tabs, tab, onSelect }: { tabs: ReadonlyArray<readonly [T, string]>; tab: T; onSelect: (t: T) => void }) {
  const { slot } = useTabsSlot();
  const nav = (
    <nav role="tablist" aria-label="Workspace sections" className={`tabs${slot ? "" : " inline"}`}>
      {tabs.map(([t, label]) => (
        <button key={t} role="tab" aria-selected={tab === t} className="tab" onClick={() => onSelect(t)} data-testid={`tab-${t}`}>{label}</button>
      ))}
    </nav>
  );
  return slot ? createPortal(nav, slot) : nav;
}
