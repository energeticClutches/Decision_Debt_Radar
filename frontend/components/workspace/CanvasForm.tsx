"use client";

import { useState } from "react";

import type { ApiError } from "../../lib/api";
import { titleCase } from "../../lib/format";
import type { Metric } from "../../lib/types";
import { ErrorBox, Field } from "../ui";

export const DECISION_TYPES = ["product_feature_investment", "pricing_change", "process_or_ux_change", "strategy_or_market_entry", "policy_or_operations"];
export const EXPECTED_DIRECTIONS: Array<[string, string]> = [["increase", "Increase"], ["decrease", "Decrease"], ["no_material_decrease", "No material decrease"]];

export interface CanvasValues {
  title: string;
  description: string;
  hypothesis: string;
  success_metric_id: string;
  decision_due_date: string;
  risk_level: string;
  decision_type: string;
  expected_direction: string;
  current_evidence_notes: string;
  change_my_mind_criteria: string[];
}

export const EMPTY_CANVAS: CanvasValues = {
  title: "", description: "", hypothesis: "", success_metric_id: "", decision_due_date: "", risk_level: "medium",
  decision_type: "product_feature_investment", expected_direction: "increase", current_evidence_notes: "", change_my_mind_criteria: [""],
};

/** The canvas form. The server validates every rule (CV-1 to CV-6) and a 422 puts its message next to the field. */
export function CanvasForm({ initial, metrics, submitLabel, onSubmit, onCancel, disabled = false }: {
  initial: CanvasValues;
  metrics: Metric[];
  submitLabel: string;
  onSubmit: (values: CanvasValues) => Promise<ApiError | null>;
  onCancel?: () => void;
  disabled?: boolean;
}) {
  const [v, setV] = useState<CanvasValues>(initial);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = error?.fieldErrors ?? {};
  const set = <K extends keyof CanvasValues>(k: K, val: CanvasValues[K]) => setV((s) => ({ ...s, [k]: val }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(await onSubmit({ ...v, change_my_mind_criteria: v.change_my_mind_criteria.map((c) => c.trim()).filter(Boolean) }));
    setBusy(false);
  };
  return (
    <form onSubmit={submit} className="stack" data-testid="canvas-form" noValidate>
      <Field label="Title" htmlFor="cv-title" error={fields.title}><input id="cv-title" value={v.title} onChange={(e) => set("title", e.target.value)} data-testid="cv-title" /></Field>
      <Field label="Description" htmlFor="cv-desc" error={fields.description}><textarea id="cv-desc" rows={2} value={v.description} onChange={(e) => set("description", e.target.value)} /></Field>
      <Field label="Hypothesis (if we do X, then Y, because Z)" htmlFor="cv-hyp" error={fields.hypothesis}><textarea id="cv-hyp" rows={2} value={v.hypothesis} onChange={(e) => set("hypothesis", e.target.value)} /></Field>
      <div className="row">
        <div className="grow"><Field label="Success metric" htmlFor="cv-metric" error={fields.success_metric_id}>
          <select id="cv-metric" value={v.success_metric_id} onChange={(e) => set("success_metric_id", e.target.value)}>
            <option value="">Choose a metric</option>
            {metrics.map((m) => <option key={m.id} value={m.id}>{`${m.name} (${m.unit})`}</option>)}
          </select>
        </Field></div>
        <div className="grow"><Field label="Expected direction" htmlFor="cv-dir" error={fields.expected_direction}>
          <select id="cv-dir" value={v.expected_direction} onChange={(e) => set("expected_direction", e.target.value)}>
            {EXPECTED_DIRECTIONS.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
          </select>
        </Field></div>
      </div>
      <div className="row">
        <div className="grow"><Field label="Decision type" htmlFor="cv-type" error={fields.decision_type}>
          <select id="cv-type" value={v.decision_type} onChange={(e) => set("decision_type", e.target.value)}>
            {DECISION_TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </select>
        </Field></div>
        <div className="grow"><Field label="Risk level" htmlFor="cv-risk" error={fields.risk_level}>
          <select id="cv-risk" value={v.risk_level} onChange={(e) => set("risk_level", e.target.value)}>
            {["low", "medium", "high"].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </select>
        </Field></div>
        <div className="grow"><Field label="Decision due date" htmlFor="cv-due" error={fields.decision_due_date}>
          <input id="cv-due" type="date" value={v.decision_due_date} onChange={(e) => set("decision_due_date", e.target.value)} />
        </Field></div>
      </div>
      <Field label="Current evidence notes (optional)" htmlFor="cv-notes"><textarea id="cv-notes" rows={2} value={v.current_evidence_notes} onChange={(e) => set("current_evidence_notes", e.target.value)} /></Field>
      <Field label="What would change my mind (1 to 5 criteria, 10 to 300 characters each)" error={fields.change_my_mind_criteria}>
        <div className="stack">
          {v.change_my_mind_criteria.map((c, i) => (
            <div key={i} className="row center">
              <input aria-label={`Criterion ${i + 1}`} className="grow" value={c} onChange={(e) => set("change_my_mind_criteria", v.change_my_mind_criteria.map((x, j) => (j === i ? e.target.value : x)))} />
              <button type="button" className="btn small" onClick={() => set("change_my_mind_criteria", v.change_my_mind_criteria.filter((_, j) => j !== i))} disabled={v.change_my_mind_criteria.length <= 1}>Remove</button>
            </div>
          ))}
          <div><button type="button" className="btn small" onClick={() => set("change_my_mind_criteria", [...v.change_my_mind_criteria, ""])} disabled={v.change_my_mind_criteria.length >= 5}>Add a criterion</button></div>
        </div>
      </Field>
      {error && !Object.keys(fields).length ? <ErrorBox error={error} onDismiss={() => setError(null)} /> : null}
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy || disabled} data-testid="canvas-submit">{submitLabel}</button>
        {onCancel ? <button type="button" className="btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  );
}
