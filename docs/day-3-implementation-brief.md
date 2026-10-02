# Day 3 Implementation Brief (approved)

**Status:** Approved by the Product Owner on 2026-10-02 after the Opus architecture review. Decisions R1–R14 below are **final** and must not be reinterpreted. Where the brief left a detail open, §3 records the resolution; follow it exactly. If anything is still ambiguous, stop and report instead of inventing methodology.

**Day-3 objective:** the deterministic business-logic foundation: DDI engine, gating, contribution breakdown, sensitivity, evidence-direction summary, NBE engine, lifecycle service, assessment/version handling, human review/override, SQLAlchemy 2.0 models, repositories and EvidenceFacts builder, FastAPI API, demo-user role switcher, audit handling, and tests.

Day 3 **consumes** stored evidence, stored experiment statistics and stored DQ results. It does **not** compute upstream analytics.

---

## 1. Final Product Owner decisions (R1–R14)

**R1 Meaning of DDI.** DDI measures *evidence debt*, the weakness in the evidence base supporting a decision. It does **not** measure the probability that the decision is correct. Strong evidence that contradicts the hypothesis can produce a LOW DDI. DDI is always accompanied by a deterministic **evidence-direction summary** (§3.4). No contradiction floor and no change to the maths.

**R2 Cap reconciliation.** Compute all raw contributions and the uncapped DDI = 100 × (1 − Support) × Penalty. Displayed DDI = min(100, uncapped). If uncapped > 100, scale every contribution component by 100 / uncapped and expose `cap_applied = true` with `uncapped_ddi`.

**R3 Bands and rounding.** Low < 25 · Moderate ≥ 25 and < 50 · High ≥ 50 and < 75 · Critical ≥ 75 and ≤ 100. **A DDI of exactly 100 is Critical** (fix the YAML). Round DDI to one decimal **first**, then derive the band. Displayed contributions (dimensions + penalties) use **largest-remainder** allocation at one decimal so they sum exactly to the displayed DDI.

**R4 EvidenceFacts contract.** One immutable domain structure, `EvidenceFacts`. Flow: Database → repository → EvidenceFacts → DDI engine → DDI result. The engine receives EvidenceFacts + DDI params + **injected as-of date** (never `datetime.now()` in the engine) and is deterministic. Missing optional facts use **documented conservative defaults** and are marked `defaulted/unknown` in the breakdown with an explanation. Add all missing constants to the parameter file and store/validate a **content hash**.

**R5 Assessment execution.** Compute the whole assessment in memory and insert the completed row once. No "running" state on Day 3. **DQ gate:** block if an **open critical** DQ check affects the success metric's data source. `open` blocks. `accepted` does not block but appears as a warning. `resolved` does not block. Open critical issues from earlier assessment versions of the same decision remain relevant.

**R6 Concurrency.** One transaction: BEGIN → `SELECT decision FOR UPDATE` → capture evidence fingerprint → build EvidenceFacts → calculate DDI + NBE → verify fingerprint → insert assessment → update lifecycle → audit → COMMIT. If the fingerprint changed, reject (409) and require a rerun. Concurrent assessment requests serialize on the row lock.

**R7 Current assessment.** The highest version is current, **including partial**. If the latest is partial, expose the previous scored version separately as historical. Never silently fall back.

**R8 NBE applicability.** Deterministic rule per action, no LLM. Thresholds live in the NBE parameter file (§3.6).

**R9 NBE expected reduction.** Remove `clears_heterogeneity_floor`. Reduction models *potential evidence-strength improvement if the action succeeds as intended*, never "the hypothesis is proven". Include the D2 improvement when an action newly supplies a missing checklist type, and the D6 cap lift for the holdout. Floor at zero. Never negative. Actions at or above their ceiling are excluded.

**R10 Insufficient-evidence NBE.** Add `recommendations.blockers_resolved INT`. For insufficient assessments `expected_reduction = 0` and `blockers_resolved` holds the number of gating blockers the action addresses. Never mix units.

**R11 NBE timing and versioning.** Day-3 NBE uses only information available at assessment time. **No Reviewer-challenge relevance** (Day 5 may recompute). Store the NBE parameter version and hash. Verify that the NBE file references the active DDI parameter version.

**R12 Human review / override.** Day 3 includes a human-review endpoint (verdict, human_response/reason, actor, timestamp). A `needs_rework` assessment cannot become validated unless an explicit human review with a non-empty reason exists.

**R13 Migration 0004 invariants** (database). (a) Canvas edits after lock mark the assessment stale. (b) Any write against a decided decision is rejected. (c) `assessed` requires an assessment row. All other workflow stays in services.

**R14 Role switcher.** Header `X-Demo-User: <seeded user uuid>`. The server reads role and team from the database. Demo identity only, **not authentication**. Department Leader ownership: `user.team_id = decision.team_id`.

**Additional PO corrections.** (i) Monotonicity: do **not** test "adding evidence reduces DDI". Test "**improving an attribute of an existing evidence item never increases DDI, all else equal**". (ii) Source concentration: **normalize** HHI (§3.3). (iii) No market dimension. Non-applicable dimensions are reported as "Not applicable" and the equal prior applies only across applicable dimensions. (iv) Test the evidence-direction summary separately from DDI (§4, tests 33–35).

---

## 2. DDI and NBE methodology (as implemented on Day 3)

Unchanged from `docs/DDI-spec.md` except where R1–R14 and §3 say otherwise:
- Positive dimensions D1–D7, penalty dimensions P1 Contradiction and P2 Uncertainty.
- Support = Σ w_k D_k over applicable positive dimensions, equal weights renormalized over applicable dimensions.
- Penalty = 1 + 0.5 × P1 + 0.25 × P2. Uncapped = 100 × (1 − Support) × Penalty. Displayed = min(100, uncapped).
- Gating (insufficient evidence) if ANY: fewer than 3 evidence items · fewer than 2 evidence types · no evidence directly linked to the success metric · open critical DQ on the success metric's data source. When gated: score, band and sensitivity range are null, and blocking reasons are populated in this **fixed order**: `min_items`, `min_types`, `success_metric_evidence`, `open_critical_dq`.
- **Sensitivity:** for each applicable dimension, weight × 0.5 and × 1.5 (renormalized); penalty coefficients × 0.5 and × 1.5 together, and each separately (6 runs). Count = 2K + 6, with the base case **not** included. Report base, min, max, count, the share with an unchanged band, `band_stable` (= robust: share ≥ 0.9), and `label: "robust"|"sensitive"`. UI text: "Robust to aggregation weights and penalty coefficients." Item-level factors are not perturbed. Bands for perturbations use the same round-then-band rule.
- **NBE:** the eight YAML actions (no new action). Effort S=1, M=3, L=8, XL=15. **priority = relevance × potential_ddi_reduction ÷ effort_days** (relevance 1.0 / 0.7 / 0.4; reduction in DDI points; effort in person-days). Use these explicit names in code (§3.4c). Ranking: priority desc (unrounded), effort asc, action_id asc. Store a rounded priority (4 dp) for display. One DQ-fix recommendation per affected data source.

---

## 3. Resolutions of open details (made by Opus, binding for Day 3)

**3.1 Lifecycle names.** Keep the existing DB enum values (`created`, `evidence_gathered`, `assessed`, `challenged`, `validated`, `decided`). "decision_created" in the draft brief means `created`. API responses include `lifecycle_stage` plus a display label. For `validated` the label is exactly **"Assessment validated by review"**.

**3.2 Where versions and hashes are stored.** Migration 0004 adds to `decision_assessments`: `params_hash text NOT NULL`, `nbe_params_version text`, `nbe_params_hash text`, `evidence_fingerprint text NOT NULL`, `as_of_date date NOT NULL`. It adds `recommendations.blockers_resolved integer NOT NULL DEFAULT 0 CHECK (>= 0)` (R10). The hash is SHA-256 of the YAML file bytes. The loader raises if the file hash does not match the hash recorded in `backend/config/params_hashes.json` (the committed registry). The parameter-file amendments (below) happen **before** any assessment uses v0.1, so v0.1 is amended in place and its hash recorded once.

**3.3 Missing DDI constants and defaults** (add to `ddi_params_v0.1.yaml`, document in DDI-spec):

| Constant | Value | Use |
|---|---|---|
| `bands` critical | `{min: 75, max: 100, max_inclusive: true}` | R3 |
| `small_n_threshold` | 100 | P2 small-n flag (n_sample < 100) |
| `behavioral.materiality_threshold` | 0.02 (absolute effect) | D6 materiality = min(1, \|effect\| / threshold) |
| `behavioral.n_required` | 1000 | D6 adequacy = min(1, n / n_required). The metrics table has no MDE, so this is a fixed v0.1 constant |
| `customer.default_relevance` | 0.5 (adjacent), defaulted flag | D5 when relevance unknown (no column exists) |
| `customer.default_segment_coverage` | 0.5, defaulted flag | D5 when segment coverage unknown |
| `experiment.default_power_factor` | 0.5, defaulted flag | D4 when achieved power is not stored |
| `experiment.default_informativeness` | 0.3, defaulted flag | D4 when CI or MDE is missing |
| `financial.sensitivity_range_rule` | `ci_low and ci_high present` | D7 "sensitivity range present" |
| `uncertainty.ci_component_when_effect_zero` | 1.0 | P2 when effect = 0 |
| `uncertainty.hhi_normalization` | `(HHI − 1/n) / (1 − 1/n)`, 1.0 when n = 1 | normalized concentration in [0, 1] |
| `direction.majority_share` | 0.6 | §3.4 |
| `direction.min_direction_bearing_items` | 2 | §3.4 (replaces the withdrawn `min_total_weight`) |

Definitions:
- **Evidence set:** all `evidence` rows of the decision at the snapshot. There is no "active" flag.
- **Items with a critical DQ issue** count toward the gate's item and type counts (the DQ gate handles blocking separately), and score `dq_factor = 0` in D1.
- **"Directly linked to the success metric":** `evidence.metric_id = success_metric_id`, OR the linked experiment's `primary_metric_id = success_metric_id`.
- **Experiments only via `evidence.experiment_id`.** Customer insights only via `evidence.insight_id`. Effect, CI, p and srm come from the `experiment_results` row whose `variant` is not the control (the row with non-null `effect_size`). If several exist, use the one with the largest n.
- **D4:** design rank × power factor × integrity × informativeness for the best experiment. Unknown power gives the default plus a flag.
- **P1:** item weight w = tier × grade × freshness **× dq_factor**. The denominator is all items with stance supports or contradicts. Neutral items are excluded so they don't dilute contradiction. With zero non-neutral weight, P1 = 0. The heterogeneity floor applies only when `facts.heterogeneity_flag` is True. The default is False with an "unknown" flag, because Day 4 produces it.
- **P2:** mean of the available components among {CI component, small-n share, normalized HHI}. The breakdown lists which components were available.

**3.4 Evidence-direction summary** (PO-approved 2026-10-02). It is a parallel interpretation of the evidence and **must never modify the DDI** (no DDI input or output may read it).

Item weight w as in P1 (tier × grade × freshness × dq_factor). Direction-bearing items are those with stance supports or contradicts and w > 0.
- `supporting_share` = supporting weight ÷ direction-bearing weight. `contradicting_share` = contradicting weight ÷ direction-bearing weight. These two sum to 1, or are both 0 when there is no direction-bearing weight.
- `neutral_share` = neutral weight ÷ total weight.
- `direction_basis_weight` = direction-bearing weight ÷ total weight (0–1).

Label:
- **`uncertain`** if the assessment is gated (insufficient_evidence), OR there are fewer than `direction.min_direction_bearing_items` (2) direction-bearing items, OR direction-bearing weight is 0. In words: the available direction-bearing evidence is insufficient to classify.
- otherwise **`supporting`** if supporting_share ≥ 0.6 (60/40 is supporting);
- **`contradicting`** if contradicting_share ≥ 0.6 (40/60 is contradicting);
- otherwise **`mixed`**: neither side reaches 0.6 while there is sufficient direction-bearing evidence (55/45 is mixed).

The earlier rule "uncertain when total weight < 1.0" is **withdrawn**. Remove `direction.min_total_weight` and add `direction.min_direction_bearing_items: 2`. Non-applicable DDI dimensions have no influence on direction.

Output contract (stored in `decision_assessments.dimension_scores.evidence_direction` and returned next to, never inside, the DDI):
```yaml
evidence_direction:
  label: supporting | contradicting | mixed | uncertain
  supporting_share: 0.00-1.00
  contradicting_share: 0.00-1.00
  neutral_share: 0.00-1.00
  direction_basis_weight: 0.00-1.00
  threshold: 0.60
  direction_bearing_items: <int>
```

**3.4a P1 definition (methodology change from the original spec, PO-approved, record it in the Day-3 decision log).** P1 is "strength-weighted contradiction among direction-bearing evidence, adjusted for evidence quality". Neutral items are excluded from the denominator. Item weights include `dq_factor`. Required golden test: a contradicting item with an open critical DQ issue contributes less contradiction weight than the same item without it.

**3.4b Defaulted values (PO rule).** Every input that falls back to a default is surfaced as structured metadata, never silently. Each such input in the breakdown has `{value, source: "observed" | "default", default_reason}`, for example `{"value": 0.5, "source": "default", "default_reason": "no explicit customer relevance was supplied"}`. Dimension-level `defaulted_inputs[]` lists them. API and UI text can render "Customer relevance: 0.50 (defaulted because no explicit relevance value was supplied)".

**3.4c Explicit names (PO rule).** Do not use V/R/E variable names in code. Use `priority = relevance * potential_ddi_reduction / effort_days`. The DB column stays `recommendations.expected_reduction`, mapped from `potential_ddi_reduction` in the repository.

**3.4d Assessment immutability (PO rule).** An assessment is a historical artifact. Migration 0004 adds a trigger rejecting any UPDATE of `decision_assessments` that changes: version, state, ddi_score, ddi_band, dimension_scores, penalty_scores, blocking_reasons, sensitivity, params_version, params_hash, nbe_params_version, nbe_params_hash, evidence_fingerprint, as_of_date, decision_id. Only `narrative` and `brief_md` (populated by later days) may change. Add a test.

**3.5 Breakdown payload** (stored in `dimension_scores` / `penalty_scores` / `sensitivity`). Per dimension: `score`, `applicable`, `weight`, `raw_contribution`, `display_contribution`, `defaulted_inputs[]`, `explanation`. Penalties are shown the same way. Top level: `ddi_display`, `uncapped_ddi`, `cap_applied`, `band`, `params_version`, `params_hash`, `as_of_date`. The "what drove this result" text is a deterministic template from the largest contributions. No LLM.

**3.6 NBE applicability rules** (thresholds in `nbe_params_v0.1.yaml`, `applicability` section):

| Action | Applicable when |
|---|---|
| fix_dq_or_instrumentation | an open warn or critical DQ check exists on a data source feeding this decision's evidence or success metric (one recommendation per data source) |
| powered_holdout_test | D4 applicable, D4 < 0.8, and the best experiment's design is not RCT with power factor ≥ 0.8 |
| segment_level_analysis | D6 applicable and (heterogeneity_flag is True, or D6 < 0.6) |
| customer_interview_sprint | D5 applicable and D5 < 0.85 |
| targeted_survey | D5 applicable and D5 < 0.80 |
| extend_observation_or_refresh_data | D3 < `applicability.freshness_threshold` (0.5), or the P2 CI component > 0.5 |
| financial_model_with_sensitivity | D7 applicable and D7 < 0.8 |
| replicate_independent_source | normalized HHI > `applicability.concentration_threshold` (0.5) |

- **Relevance (Day 3):** 1.0 if the action targets the success metric's evidence (fix DQ on the success metric's source, holdout or segment analysis when the success metric is the experiment or behavioral target). 0.7 if it supplies a missing checklist type. Otherwise 0.4. Take the max if several apply. **No Reviewer-based relevance on Day 3.**
- **Insufficient state:** blocker → action map: `open_critical_dq` → fix_dq. `success_metric_evidence` → holdout, segment analysis, extend observation. `min_items` / `min_types` → any action that supplies a new evidence item or type (holdout supplies experiment, survey and interviews supply customer, financial model supplies financial, extend observation supplies behavioral). `blockers_resolved` = number of mapped blockers present. Priority = V × blockers_resolved / E. Rows with blockers_resolved ≥ 1 rank first.

**3.7 Lifecycle and 0004 trigger details.**
- Implement the canvas-edit rule **inside the existing `ddr_decision_lifecycle_guard`** (replace the function in 0004), not as a second BEFORE trigger, to avoid trigger-ordering bugs. When `canvas_locked_at` is set and any canvas column changes while the stage is `assessed`, `challenged` or `validated`, set `assessment_stale = true` and `lifecycle_stage = 'evidence_gathered'`.
- **Writes against a decided decision are rejected** for inserts/updates on: evidence, decision_assessments, recommendations (including status updates), decision_reviews, dq_checks, analysis_results, claims (via assessment), agent_runs. `audit_logs` stays insert-only and is allowed.
- `assessed` requires at least one `decision_assessments` row with state ≠ 'partial' for the decision.
- **Service rules:**
  - an assessment may run only when the stage is `evidence_gathered`;
  - adding or updating evidence when the stage is `assessed`, `challenged` or `validated` sets stale and returns the stage to `evidence_gathered`;
  - a partial assessment does not advance the stage;
  - recording a human review moves `assessed` → `challenged`;
  - `validate` requires the current assessment's latest review verdict `ready`, or a human review with a non-empty `human_response` (override);
  - a `defer` outcome stores the record and returns the stage to `evidence_gathered` (stale = true) in one transaction;
  - `decision_due_date ≥ today` (injected clock) at creation.
- **Audit:** every transition, assessment, review, decision record and recommendation status change writes exactly one `audit_logs` row with `actor_id` = the demo user, in the same transaction.

**3.8 Permissions (role switcher)**, from PRD §3:
- create and edit canvas: pm, ba;
- add evidence: pm, ba, product_analyst;
- run assessment: pm, ba, product_analyst;
- human review: pm, ba, dept_leader, executive;
- validate: pm, ba, dept_leader (own team), executive;
- record decision: the decision owner, dept_leader (own team), executive;
- update DQ check status (resolve/accept): product_analyst, ba;
- recommendation status: pm, ba, product_analyst;
- read: all.

Unknown or missing `X-Demo-User` → 401 (demo identity missing). Not permitted → 403.

**3.9 API surface (keep to this list):**
`GET /health` · `GET /users` (switcher list) · `GET /me` · `POST /decisions` (canvas) · `GET /decisions` · `GET /decisions/{id}` · `PATCH /decisions/{id}/canvas` · `POST /decisions/{id}/confirm-evidence` (created → evidence_gathered) · `POST /decisions/{id}/evidence` · `GET /decisions/{id}/evidence` · `POST /decisions/{id}/assessments` · `GET /decisions/{id}/assessments` · `GET /assessments/{id}` (full DDI panel payload, direction summary, current/previous-scored) · `GET /assessments/{id}/recommendations` · `PATCH /recommendations/{id}` (accept/reject/defer + note) · `POST /assessments/{id}/reviews` (human review) · `POST /decisions/{id}/validate` · `POST /decisions/{id}/decision-record` · `PATCH /dq-checks/{id}` (resolve/accept) · `GET /decisions/{id}/audit`.
Trigger/constraint violations map to 409 (state conflict) or 422 (invalid input), never 500.

---

## 4. Definition of done: required tests

**DDI engine (pure)**
1. DDI-spec §9 worked example reproduces DDI 61.0 High, contributions 51.9 + 5.2 + 3.9, and the stated perturbation values.
2. Identical facts + params + as-of give identical output.
3. Each gate alone (min_items, min_types, success_metric_evidence, open_critical_dq) → score, band and range null, reason populated. `accepted` and `resolved` DQ do not block (accepted appears as a warning).
4. All four gates together → all four reasons in fixed order.
5. Bands at 0, 24.9, 25.0, 49.95 (→ 50.0 High), 75.0, 99.99 (→ 100.0 Critical), 100.0.
6. S = 1 → 0 for any penalty. S = 0 → 100 capped, with reconciled contributions and cap_applied.
7. Displayed contributions + penalties equal the displayed DDI exactly (capped and uncapped, property-tested over many random fact sets).
8. Non-applicable dimensions excluded, weights renormalized to sum to 1, reported as "Not applicable".
9. Improving any single attribute of an existing item (tier, grade, DQ status, recency, n) never increases DDI.
10. P1 = 0 with no contradicting items, 1 when all non-neutral weight contradicts. Floor only when heterogeneity_flag.
11. P2 with effect = 0, missing CI and a single item stays in [0, 1]. Normalized HHI is 0 for evenly spread sources and 1 for a single source.
12. Sensitivity count = 2K + 6 for K = 7, 6, 5. The range contains the base. Thresholds tested at exactly 90%. `band_stable` key stored.
13. Param version/hash mismatch, or an NBE file referencing a different DDI version, raises at load.

**NBE engine (pure)**
14. NBE-spec worked example (updated per R9) matches.
15. Actions at or above ceiling excluded. No negative reduction.
16. Deterministic ranking (priority, effort, action_id), stable across runs.
17. Insufficient state: expected_reduction 0, blockers_resolved correct, unblocking actions first. In the Onboarding-like case the fix-DQ action ranks first.
18. Applicability rules per action. One DQ action per affected data source.

**Lifecycle and services (DB, rolled back)**
19. All legal transitions succeed. All illegal from/to pairs are rejected by both service and DB.
20. Evidence added or changed, or canvas edited, after assessed/challenged/validated → stale and back to evidence_gathered.
21. Concurrency: evidence change during assessment → 409 and no fresh assessment. Two concurrent runs → versions 1 and 2 or a clean rejection, never 500.
22. Versioning: 1, 2, 3. Current = highest including partial. Previous scored exposed. Runs only from evidence_gathered.
23. Decision record: requires validated. BR-11 acknowledgement. Defer returns to evidence_gathered and keeps the record. One final record. Decided blocks all further writes.
24. Every transition and status change writes exactly one audit row with actor_id.
25. Override: needs_rework blocks validation unless a human review with a non-empty reason exists.

**API**
26. Decided decision cannot be mutated through any endpoint.
27. DB trigger errors map to 409/422, never 500.
28. Role permission matrix, one test per persona. Missing or unknown user → 401.
29. `validated` response label is exactly "Assessment validated by review".
30. No numeric DDI for insufficient/partial assessments in any response.
31. SQLAlchemy models match the live schema (reflection: columns, types, nullability). No `create_all` anywhere.

**Scope guard**
32. A test fails if `anthropic`, `sqlglot` or `agents` is imported anywhere under `backend/app`.

**Evidence direction ≠ DDI (PO addition)**
33. Strong supporting evidence → low DDI + `supporting`.
34. Strong contradicting evidence → low DDI + `contradicting` (same DDI band as case 33).
35. Weak/incomplete evidence → high or insufficient DDI + `uncertain`.

**Added by PO clarifications (2026-10-02)**
36. Direction thresholds: 80/20 supporting, 20/80 contradicting, 55/45 mixed, 60/40 supporting, 40/60 contradicting. Fewer than 2 direction-bearing items → uncertain. Gated → uncertain. The output contract has all fields.
37. Direction never modifies the DDI: identical facts with all stances flipped give an identical DDI, apart from P1 (assert D1–D7 and P2 are equal, and that changing stance only moves P1 and direction).
38. P1 golden test: a contradicting item with an open critical DQ issue adds less contradiction weight than the same item without it. Neutral items do not dilute P1.
39. Defaulted inputs appear with `source: "default"` and a `default_reason`. No defaulted value appears as observed.
40. Assessment immutability: updating any protected column of `decision_assessments` is rejected by the database. Updating `narrative` or `brief_md` succeeds.

---

## 5. Out of scope on Day 3 (hard stop)

Do not:
- generate evidence from fc_ data;
- compute experiment statistics, power, CIs or heterogeneity;
- implement DQ computation;
- build the seven-stage pipeline or an orchestrator;
- add the Anthropic SDK, write prompts, or implement the Reviewer or Evidence Synthesis agents;
- implement the SQL guard or use sqlglot;
- generate the decision brief;
- modify the frontend, build Power BI, add upload endpoints, add agents, or add DDI dimensions.

## 6. Execution order
1. Docs/spec reconciliation (DDI-spec, NBE-spec, PRD sections, ERD, lifecycle spec, traceability spec, `docs/day-3-implementation-notes.md` recording R1–R14, parameter changes, hashes, 0004, the monotonicity invariant, direction semantics).
2. Params loader + version/hash validation.
3. Pure DDI engine + golden tests.
4. Sensitivity.
5. Pure NBE engine.
6. Migration 0004.
7. SQLAlchemy models + reflection test.
8. Repositories + EvidenceFacts builder.
9. Services (lifecycle, assessment, review, decision record, recommendations, DQ status, audit).
10. Pydantic schemas + routes + role switcher.
11. Integrity/API tests.
12. Scope guard.
13. Full suite.
14. Clean rebuild verification.

Stop after Day 3. Do not claim completion if any requirement is skipped. Report deviations explicitly.
