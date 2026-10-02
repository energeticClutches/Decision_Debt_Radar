# Decision Canvas Specification

**Status:** DRAFT v0.1 (Day-1 spec, pending Product Owner approval). Parent: [PRD-v0.1.md](PRD-v0.1.md) §26.

## 1. Purpose
A lightweight PM/BA artifact in the decision-creation workflow. It forces the decision owner to define the decision, the success criteria and the conditions that would change their mind **before** any evidence is assessed. It is **a form on the Decision object, not a separate feature or entity.**

## 2. Fields

| # | Canvas prompt | Stored in (`decisions`) | Type | Required | Notes |
|---|---|---|---|---|---|
| 1 | What are we deciding? | `title` (≤120), `description` | text | Yes | Title states the choice ("Invest in X", "Raise price of Y") |
| 2 | What is the hypothesis? | `hypothesis` | text (≤500) | Yes | Prompt: "If we … then … because …" |
| 3 | What is the success metric? | `success_metric_id` | FK → `metrics` | Yes | Metric must exist and have a definition |
| 4 | When must the decision be made? | `decision_due_date` | date | Yes | |
| 5 | Risk level | `risk_level` | enum low/medium/high | Yes | Subjective. Shown on the brief. Does not change the DDI |
| 6 | Current evidence | `current_evidence_notes` | text | Optional | Free text. Actual evidence is added in the evidence register |
| 7 | What evidence would change our mind? | `change_my_mind_criteria` | jsonb array of 1–5 strings | Yes | E.g. "A holdout test showing < +2 pp D90 retention" |
| – | Decision type | `decision_type` | enum (configured types) | Yes | Selects the coverage checklist (DDI-spec §5) |
| – | Team / owner | `team_id`, `owner_id` | FK | Yes | |

System fields: `canvas_completed_at`, `canvas_locked_at`, `lifecycle_stage`.

## 3. Validation rules

| ID | Rule | Severity |
|---|---|---|
| CV-1 | All required fields present | Block |
| CV-2 | Hypothesis names a measurable outcome (references the success metric name, or a direction word: increase / decrease / reduce / improve) | Warn |
| CV-3 | Success metric exists and has a definition. If no linked data source: "Quantitative evidence will depend on manually linked evidence" | Block (missing) / Warn (no data source) |
| CV-4 | `decision_due_date` ≥ today at creation | Block |
| CV-5 | 1–5 change-my-mind criteria, each 10–300 characters | Block |
| CV-6 | `decision_type` is in the configured list | Block |
| CV-7 | Canvas locks at the first assessment. Later edits are allowed but audit-logged, flagged "canvas changed after assessment" on the brief, and mark the assessment stale | Rule. **Implemented on Day 3** as a database invariant (inside the lifecycle guard) plus the `canvas.edited` audit row with `canvas_changed_after_assessment` |

## 4. Connection to the existing Decision object
- No new table. Canvas columns are added to `decisions` (see [ERD.md](ERD.md)).
- Creating a valid canvas creates the Decision in lifecycle stage `created` ([decision-lifecycle.md](decision-lifecycle.md)).
- **Orchestrator** reads success metric, decision type and risk level to configure the run.
- **Evidence Synthesis** reads hypothesis, criteria and notes. The brief reports each criterion as *met / not met / not testable with available evidence*, citing evidence IDs.
- **Reviewer** checks that the criteria were evaluated fairly, and flags a hypothesis being read generously or criteria being quietly reinterpreted.
- Criteria assessment is a classification by the LLM against validated evidence IDs. It never feeds the DDI number (BR-5).

## 5. UX (lightweight)
One page, about seven fields, inline validation, a "completeness" indicator, and one primary action ("Create decision"). Role: PM and BA can create. Other personas are read-only. No canvas templates, no versioned canvases, no collaboration in the MVP.

## 6. Example (FitConnect, synthetic)
- **Deciding:** Invest in expanding the AI Coach.
- **Hypothesis:** If we expand AI Coach, then 90-day retention increases, because users get personalised guidance.
- **Success metric:** D90 retention.
- **Due:** a date shortly after the demo date.
- **Risk:** high.
- **Current evidence:** Retention is higher among AI Coach users. Feedback is positive. Inference cost is high.
- **Would change our mind:** a properly powered holdout showing less than a +2 pp D90 effect · an effect that disappears after controlling for prior engagement · cost per retained user above the plan threshold.

## 7. Acceptance criteria
Canonical: PRD §26.5 (AC-37 to AC-42).

## 8. Day-3 implementation notes
- CV-1, CV-4, CV-5 and CV-6 block (HTTP 422). CV-2 and CV-3 (no data source) are returned as `warnings` on the created decision and never block. CV-4 uses the injected clock.
- "Canvas columns" for the stale rule are all fields of section 2: `title`, `description`, `hypothesis`, `success_metric_id`, `decision_due_date`, `risk_level`, `current_evidence_notes`, `change_my_mind_criteria`, `decision_type`, `team_id`, `owner_id`.
- The canvas is created through `POST /decisions` and edited through `PATCH /decisions/{id}/canvas` (PM and BA only).
