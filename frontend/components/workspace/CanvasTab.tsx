"use client";

import { useState } from "react";

import { api, type ApiError } from "../../lib/api";
import { fmtDate, titleCase } from "../../lib/format";
import { KeyValues, Modal } from "../ui";
import { CanvasForm, type CanvasValues } from "./CanvasForm";
import { Guarded } from "./Guarded";
import { isLocked, type TabProps } from "./types";

export function CanvasTab({ ws, act }: TabProps) {
  const { decision } = ws;
  const locked = isLocked(ws);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState<CanvasValues | null>(null);
  const afterAssessment = !!decision.canvas_locked_at;
  const metric = ws.metrics.find((m) => m.id === decision.success_metric_id);
  const owner = ws.users.find((u) => u.id === decision.owner_id);
  const initial: CanvasValues = {
    title: decision.title, description: decision.description, hypothesis: decision.hypothesis, success_metric_id: decision.success_metric_id,
    decision_due_date: decision.decision_due_date, risk_level: decision.risk_level, decision_type: decision.decision_type,
    expected_direction: decision.expected_direction, current_evidence_notes: decision.current_evidence_notes ?? "",
    change_my_mind_criteria: decision.change_my_mind_criteria.length ? decision.change_my_mind_criteria : [""],
  };

  const save = async (values: CanvasValues): Promise<ApiError | null> => {
    const changes: Record<string, unknown> = {};
    for (const key of Object.keys(values) as Array<keyof CanvasValues>) {
      if (JSON.stringify(values[key]) !== JSON.stringify(initial[key])) changes[key] = key === "current_evidence_notes" && values[key] === "" ? null : values[key];
    }
    if (!Object.keys(changes).length) {
      setEditing(false);
      return null;
    }
    const r = await act.perform("Saving the canvas", () => api.patchCanvas(decision.id, changes));
    if (r.ok) {
      setEditing(false);
      setPending(null);
      return null;
    }
    return r.error;
  };
  // after the first assessment a canvas edit makes the assessment stale: ask first
  const submit = async (values: CanvasValues): Promise<ApiError | null> => {
    if (afterAssessment && !pending) {
      setPending(values);
      return null;
    }
    return save(values);
  };

  return (
    <div className="stack" data-testid="tab-panel-canvas">
      <section className="card">
        <div className="row center">
          <h2 style={{ margin: 0 }}>Decision canvas</h2>
          <span className="right" />
          {!editing ? <Guarded action="edit_canvas" decision={decision} me={ws.me} locked={locked} testId="canvas-edit" onClick={() => setEditing(true)}>Edit canvas</Guarded> : null}
        </div>
        {locked ? <p className="small muted" data-testid="canvas-readonly">The canvas is read-only: the decision is recorded.</p> : null}
        {!editing ? (
          <KeyValues rows={[
            ["Title", decision.title], ["Description", decision.description], ["Hypothesis", decision.hypothesis],
            ["Success metric", metric ? `${metric.name} (${metric.unit}): ${metric.definition}` : decision.success_metric_id],
            ["Expected direction", titleCase(decision.expected_direction)], ["Decision type", titleCase(decision.decision_type)],
            ["Risk level", titleCase(decision.risk_level)], ["Due date", fmtDate(decision.decision_due_date)],
            ["Owner", owner ? `${owner.name} (${owner.team_name ?? "no team"})` : decision.owner_id],
            ["Current evidence notes", decision.current_evidence_notes ?? "None"],
            ["Locked at", decision.canvas_locked_at ? fmtDate(decision.canvas_locked_at) : "Not yet (locked at the first assessment)"],
          ]} />
        ) : (
          <CanvasForm initial={initial} metrics={ws.metrics} submitLabel="Save canvas" onSubmit={submit} onCancel={() => { setEditing(false); setPending(null); }} />
        )}
      </section>
      <section className="card" data-testid="criteria">
        <h3>What would change my mind</h3>
        <ol style={{ margin: 0, paddingLeft: 18 }}>{decision.change_my_mind_criteria.map((c, i) => <li key={i}>{c}</li>)}</ol>
      </section>
      {decision.warnings.length ? (
        <section className="card"><h3>Canvas warnings</h3><ul>{decision.warnings.map((w, i) => <li key={i} className="small">{String(w.message ?? JSON.stringify(w))}</li>)}</ul></section>
      ) : null}
      {pending ? (
        <Modal title="Edit the canvas after the first assessment?" onClose={() => setPending(null)} testId="canvas-confirm">
          <p>The first assessment has run. Changing the canvas makes the current assessment stale: it no longer reflects the canvas, and it must be re-run.</p>
          <div className="row">
            <button className="btn primary" data-testid="canvas-confirm-yes" onClick={async () => { const err = await save(pending); if (err) setPending(null); }}>Save and mark the assessment stale</button>
            <button className="btn" onClick={() => setPending(null)}>Cancel</button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
