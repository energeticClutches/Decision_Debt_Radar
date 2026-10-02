# Next Best Evidence (NBE) Specification

**Status:** v0.1, reconciled on Day 3 with the Product Owner decisions R8-R11 (see [day-3-implementation-brief.md](day-3-implementation-brief.md) and [day-3-implementation-notes.md](day-3-implementation-notes.md)). Parent: [PRD-v0.1.md](PRD-v0.1.md) §11, §25.

> NBE is **a proposed framework for this portfolio project**. Its estimates are rule-based heuristics, not predictions. All FitConnect data is synthetic.

## 1. Purpose
For each assessed decision, answer: **"What evidence should we obtain next to reduce decision debt most per unit of effort?"** NBE is a first-class capability and is shown in the DDI panel under "What would reduce the debt?".

## 2. Candidate action catalog (organization-configurable, v0.1 defaults)

| Action | Targets | Attainable ceiling (assumption) | Effort band | Preconditions |
|---|---|---|---|---|
| Fix / add instrumentation or resolve a DQ issue | DQ gate, D1 | Unblocks scoring. D1 dq_factor → 1.0 for affected items | M (3 d) | Open DQ finding |
| Run a powered holdout / A-B test | D4 (and D6 cap lift) | D4 → 0.8 | L (8 d) | Randomization feasible |
| Segment-level analysis | D6 | D6 → 0.6 (observational cap) | S (1 d) | Segment attributes available |
| Customer interview sprint | D5 | D5 → 0.85 | M (3 d) | Access to customers |
| Targeted survey | D5 | D5 → 0.80 | S (1 d) | Survey channel |
| Extend observation window / refresh data | D3, P2 | D3 → 0.90. P2 narrow-CI component × 0.7 | S (1 d) | Data still accruing |
| Financial model with sensitivity range | D7 | D7 → 0.80 | M (3 d) | Cost/revenue inputs |
| Replicate with an independent source | P2 (concentration), D1 | P2 concentration component × 0.6 | M (3 d) | Second source exists |

Effort bands in person-days: **S = 1, M = 3, L = 8, XL = 15**. Editable per organization. Catalog entries are configuration, not code.

## 3. Scoring
For each candidate action:

- **effort_days**: from the band (S = 1, M = 3, L = 8, XL = 15 person-days).
- **potential_ddi_reduction** (R9): `DDI_now − DDI_assumed`, where `DDI_assumed` is the deterministic engine's result after raising the targeted dimension(s) to the action's attainable ceiling. It models the **potential evidence-strength improvement if the action succeeds as intended**. It never presumes what the evidence will show (it is not "the hypothesis is proven"). It is floored at zero, never negative, and an action whose targeted dimensions are already at or above their ceiling is **excluded**. Two further effects are modelled: when an action newly supplies a **missing checklist evidence type**, D2 improves accordingly, and the **holdout** lifts the observational cap on D6 once D4 reaches the cap-lift level. `clears_heterogeneity_floor` was removed.
- **relevance** (R11, Day-3 rules, rule-based, no Reviewer challenges): 1.0 if the action targets the success metric's evidence (fix DQ on the success metric's data source; holdout or segment analysis when the success metric is the experiment or behavioral target) · 0.7 if it supplies a missing checklist type · otherwise 0.4. The maximum applies if several rules match. Day 5 may recompute relevance with Reviewer challenges.
- **priority** = `relevance * potential_ddi_reduction / effort_days`. Ranking: priority desc (unrounded), effort_days asc, action id asc (then data source id). A rounded priority (4 decimals) is stored for display. The database column is `recommendations.expected_reduction`, mapped from `potential_ddi_reduction`.
- One DQ-fix recommendation per affected data source.

**Applicability (R8, deterministic, thresholds in `nbe_params_v0.1.yaml`, section `applicability`):**

| Action | Applicable when |
|---|---|
| fix_dq_or_instrumentation | an open warn or critical DQ check exists on a data source feeding this decision's evidence or success metric (one recommendation per data source) |
| powered_holdout_test | D4 applicable, D4 < 0.8, and the best experiment's design is not RCT with power factor ≥ 0.8 |
| segment_level_analysis | D6 applicable and (heterogeneity flag True, or D6 < 0.6) |
| customer_interview_sprint | D5 applicable and D5 < 0.85 |
| targeted_survey | D5 applicable and D5 < 0.80 |
| extend_observation_or_refresh_data | D3 < 0.5, or the P2 CI component > 0.5 |
| financial_model_with_sensitivity | D7 applicable and D7 < 0.8 |
| replicate_independent_source | normalized HHI > 0.5 |

**INSUFFICIENT EVIDENCE decisions (R10):** there is no DDI_now. `potential_ddi_reduction = 0` and the new column `recommendations.blockers_resolved` holds the number of gating blockers the action addresses. The two units are never mixed (the API reports `impact_unit`). Blocker to action map: `open_critical_dq` → fix DQ (one per data source). `success_metric_evidence` → holdout, segment analysis, extend observation. `min_items` → any action that supplies a new evidence item (holdout: experiment; survey and interviews: customer; financial model: financial; extend observation: behavioral). `min_types` → the same actions when the supplied type is not yet present. In this state `priority = relevance * blockers_resolved / effort_days`, and only actions with `blockers_resolved ≥ 1` are listed (they form the "Unblock scoring" group). An action that resolves `success_metric_evidence` has relevance 1.0 (it targets the success metric's evidence); otherwise relevance is 0.7 if the action supplies a missing checklist type and 0.4 if not.

## 4. Worked example (illustrative, uses the DDI-spec §9 numbers, updated per R9)

State: D1 0.55 · D2 0.714 · D3 0.60 · D4 0.10 · D5 0.65 · D6 0.45 (raw, below the cap) · D7 0.30, P1 0.20, P2 0.30, DDI 61.0. All four checklist types are present. The success metric is the experiment and behavioral target. Potential reduction is computed by the engine (unrounded DDI now 61.03):

| Action | relevance | potential_ddi_reduction (DDI points) | effort_days | Priority |
|---|---|---|---|---|
| Segment-level analysis (D6 0.45 → 0.60) | 1.0 | 2.5 | 1 | 2.52 |
| Powered holdout test (D4 0.10 → 0.80) | 1.0 | 11.7 | 8 | 1.47 |
| Financial model with sensitivity range (D7 0.30 → 0.80) | 0.4 | 8.4 | 3 | 1.12 |
| Targeted survey (D5 0.65 → 0.80) | 0.4 | 2.5 | 1 | 1.01 |
| Customer interview sprint (D5 0.65 → 0.85) | 0.4 | 3.4 | 3 | 0.45 |

What changed relative to the Day-1 draft: relevance is recomputed by the Day-3 rules (the financial model no longer receives 0.7 because financial evidence is already present, so it ranks behind the holdout), the cheap segment analysis now appears, and D2/D6 effects are included by the engine. If financial evidence were missing from the checklist the financial model would receive relevance 0.7 and D2 would improve as well. The holdout still reduces the most debt, but the cheaper actions rank higher on priority. The panel shows every column so a human can overrule the ranking. The formula is a ranking aid, not a decision.

## 5. Output per action
`action_type`, plain-language description (LLM may phrase it), dimensions addressed, effort (days and band), expected reduction, relevance, priority, "why this" (computed from the dimension and gap that it addresses), status (proposed / accepted / rejected / deferred), human note. Stored in `recommendations` (see [ERD.md](ERD.md)).

## 6. Assumptions (shown in the product)
1. Attainable ceilings are configuration assumptions, not predictions of what the evidence will show.
2. Effort bands are rough and organization-specific.
3. The potential reduction ignores the possibility that new evidence contradicts the decision.
4. Actions are scored independently. Interaction effects are not modelled in the MVP.
5. Candidate actions come from the catalog. The LLM may suggest *which catalog actions apply* and write the rationale, but cannot create numbers or invent catalog entries.
6. Relevance is rule-based and coarse. On Day 3 it uses only information available at assessment time (no Reviewer challenges).
7. The ranking depends on the DDI parameter version. Each assessment stores the NBE parameter version and hash, and the loader verifies that the NBE file references the active DDI version.

## 7. LLM boundary
Allowed: select applicable catalog actions, phrase descriptions and "why this". Not allowed: set effort, ceilings, relevance, R or priority. These are computed by code (BR-5).

## 8. UI requirements
Ranked table in the DDI panel: priority, action, effort, expected reduction, relevance, dimensions addressed, "why this", accept/reject/defer with a note. For INSUFFICIENT EVIDENCE: an "Unblock scoring" group first. If no action applies, state why. Persistent note: "Expected reduction is potential debt reduction under assumptions. It does not predict what the evidence will show."

## 9. Acceptance criteria
Canonical: PRD §11 and AC-9, AC-34. Additional:

| ID | Criterion |
|---|---|
| NBE-AC-1 | `potential_ddi_reduction` equals the engine's DDI difference for a hand-computed fixture. Priority is reproducible. |
| NBE-AC-2 | Ties break on lower effort. Ordering is deterministic. |
| NBE-AC-3 | In an INSUFFICIENT scenario (Onboarding), the instrumentation fix appears first under "Unblock scoring". |
| NBE-AC-4 | A seeded scenario where the top-ranked action is applied (adding its evidence in a variant seed) changes the DDI in the direction the engine predicted. |
| NBE-AC-5 | Accept/reject/defer decisions are stored with a note and audit-logged. |
