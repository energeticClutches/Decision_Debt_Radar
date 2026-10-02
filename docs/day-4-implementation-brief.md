# Day 4 Implementation Brief: Data & Analytics foundation

**Status:** APPROVED for implementation. Decisions D4-01 to D4-25 were frozen by the PO on 2026-10-02, and open points O1, O2 and O3 were approved as recommended on 2026-10-02. Everything in this brief is binding. Where this brief is silent, stop and report. Do not invent methodology.
**Baseline:** commit `f6209e9` (Days 1–3 accepted). Rollback point.

> All FitConnect data is synthetic. DDI is a transparent evidence-risk heuristic, not an industry standard.

---

## 0. Objective and the one hard rule

Day 4 turns raw organisational data into the structured inputs that the frozen engines already consume. It covers data quality, deterministic analyses, experiment statistics, heterogeneity, generated evidence with full traceability, the SQL guard, and a deterministic pipeline (stages 1, 2 and 4).

**Hard rule (D4-25):** Day 4 must not change the DDI or NBE mathematics, parameters, bands or semantics. The following must show **no diff** against `f6209e9`:
- `backend/app/domain/ddi/**`
- `backend/app/domain/nbe/**`
- `backend/config/ddi/**`
- `backend/config/nbe/**`
- `backend/config/params_hashes.json` (except a new `analytics_params_v0.1` entry)

A test enforces this (§11, T-GUARD-1). Changes to the facts builder (`repositories/evidence_facts.py`) are allowed only where this brief names them.

## 1. Non-goals (hard stop)

- No LLM calls and no Anthropic SDK.
- No LLM-generated SQL.
- No Evidence Synthesis, Reviewer, customer-theme extraction (Stage 3) or brief generation. Those belong to Day 5.
- No anomaly detection, revenue modelling, causal inference or ML.
- No frontend and no Power BI.
- No new DDI dimension or NBE action.
- No use of `fc_.feedback_ground_truth` by product code. It is evaluation data only.
- **No DDI band expectations in Day-4 acceptance (D4-24).**

---

## 2. Former open points: all APPROVED by the PO as recommended (2026-10-02)

**O1. Expected direction for non-inferiority hypotheses (Pricing).** D4-20 allows `increase | decrease`. The Pricing hypothesis is "conversion does **not fall materially**", which is a non-inferiority claim, neither increase nor decrease.
- With `increase`, the CA pilot's conversion drop correctly becomes `contradicts`. But a flat, precise result would only ever be `neutral` and could never support the hypothesis.
- **Recommendation:** add a third value, `no_material_decrease`:
  - **supports** if the CI's lower bound is above −materiality;
  - **contradicts** if the CI's upper bound is below −materiality;
  - otherwise **neutral**.
- Seeded values: AI Coach `increase`, Onboarding `increase`, Community `increase`, Pricing `no_material_decrease`.

**O2. Day-4 assessments for Community and resolved-DQ Onboarding stay INSUFFICIENT EVIDENCE.** Day 4 generates only **behavioral** and **experiment** evidence. Customer evidence arrives with Day 5 (Stage 3), and financial evidence is not generated.
- Community and Onboarding have no experiment, so they hit the "fewer than 2 evidence types" gate. This is correct behaviour, not a defect.
- **Recommendation:** for those two cases, the acceptance tests add one *manually entered* customer evidence item through the existing Day-3 API. That shows the scored path, including the Community P1 floor of 0.3, without generating customer evidence.

**O3. Code location.** `agents/` stays reserved for the LLM agents (Day 5). The Day-3 scope guard forbids `backend/app` from importing `agents` or `sqlglot`.
- **Recommendation:** put the deterministic Data & Analytics capability in `backend/app/analytics/`, and the pipeline (orchestrator) in `backend/app/services/pipeline.py`.
- `agent_runs.agent_name` still records `data_analytics` and `orchestrator`, with `model = NULL`.
- The scope guard changes: `sqlglot` is allowed only in `backend/app/analytics/sql_guard.py`. `anthropic` and `agents` stay forbidden.

---

## 3. Schema: migration 0005

One migration (`database/sql/0005_day4_analytics.sql`, `_down.sql`, `versions/0005_*.py`). Do not edit migrations 0001–0004.

| Table | Change | Decision |
|---|---|---|
| `dq_checks` | add `decision_id uuid NOT NULL` (FK); `assessment_id` becomes nullable; add `check_key text NOT NULL`, `target text NOT NULL`, `observed_value numeric`, `threshold numeric`, `affects_success_metric boolean NOT NULL DEFAULT false`, `source_snapshot text`, `last_run_at timestamptz`; `UNIQUE(decision_id, check_key)` | D4-01/02/03 |
| `dq_checks` decided-guard | re-point the 0004 guard to `decision_id`. Today it reaches the decision through `assessment_id`, which can now be NULL | follows from D4-02 |
| `experiments` | add `planned_treatment_share numeric CHECK (> 0 AND < 1)`, `control_variant text`, `outcome_key text` (the outcome `metric_name` in the source data) | D4-12 |
| `experiment_results` | `UNIQUE(experiment_id, variant)` (upsert target) | D4-14 |
| `evidence` | add `status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded'))`, `superseded_by uuid REFERENCES evidence(id)`, `superseded_at timestamptz`, `analysis_identity text`, `source_fingerprint text`; partial unique index `(decision_id, analysis_identity) WHERE status = 'active' AND analysis_identity IS NOT NULL` | D4-16/19 |
| `analysis_results` | add `analysis_identity text`, `params_hash text`, `source_fingerprint text` (rows are historical and are never updated after insert, except `agent_run_id`) | D4-15 |
| `decisions` | add `expected_direction text NOT NULL CHECK (IN ('increase','decrease','no_material_decrease'))` (O1 approved). Backfill the seeded decisions per O1. Add it to the canvas-stale column list in the lifecycle guard; that guard function must be replaced again in 0005 (same pattern as 0004) | D4-20 |
| views | `v_evidence_freshness` and `v_evidence_health` count only `status = 'active'` evidence. `v_traceability_matrix` keeps every evidence row, because claims of historical assessments must still resolve. It adds an `evidence_status` column | D4-19 |

**Facts builder and fingerprint changes (named, allowed):**
- Read DQ checks by `dq_checks.decision_id` (D4-05).
- Exclude `status = 'superseded'` evidence.
- Fill `heterogeneity_flag` from the **latest** `analysis_results` row with `analysis_type = 'segmentation'` for the decision's success metric (§6). Use `None` if there is none.
- Fill `ExperimentFact.achieved_power` from the experiment analysis that the evidence item's `analysis_id` points to (§7). Use `None` if there is none.
- The evidence fingerprint must cover these same inputs.

Update `core_seed.py` for the new columns:
- `planned_treatment_share = 0.5` on both experiments;
- `control_variant` = `holdout` / `control_9_99`;
- `outcome_key` = `workouts_14d` / `converted_to_paid`;
- `expected_direction` for the four decisions per O1.

---

## 4. Configuration: two new hashed files

**4.1 `backend/config/analytics/analytics_params_v0.1.yaml`** contains the generic methods and thresholds. It is registered in `params_hashes.json` and loaded with the same version, hash and ParamsError checks as the DDI file.
- `dq`:
  - `window_days: 56`, `baseline_days: 28`, `recent_days: 14`, `min_sustained_days: 7`
  - `volume.warn_pct_drop: 0.25`, `volume.critical_pct_drop: 0.50` (the drop in an event's per-signup daily rate, recent window vs baseline, per platform)
  - `sequence.warn_rate: 0.02`, `sequence.critical_rate: 0.10` (the share of users with step k but without step k−1)
  - `completeness.warn_null_rate: 0.01`, `completeness.critical_null_rate: 0.05`
  - `duplicates.warn_rate: 0.001`, `duplicates.critical_rate: 0.01`
  - `referential.warn_rate: 0.0`, `referential.critical_rate: 0.001`
- `severity_rule`: a finding at the **critical** threshold is `critical` only if its target is in the success metric's lineage. Otherwise it is capped at `warn` (impact over size).
- `heterogeneity`: `min_segment_n: 500`, `test: two_proportion_z`, `alpha: 0.05`, `correction: bonferroni` (over eligible segment pairs), `min_eligible_segments: 2`. The materiality threshold comes from the metric (4.2).
- `experiments`: `srm_alpha: 0.001`, `power_alpha: 0.05`, `power_alternative: two-sided`. The method is a two-proportion test for binary outcomes and Welch's t-test for continuous ones. **Design power** is computed at the experiment's `mde` with the achieved n and allocation (D4-11): statsmodels `NormalIndPower` with `proportion_effectsize` for proportions, and `TTestIndPower` with d = mde / pooled SD for continuous outcomes. With no `mde`, power is `None` and the DDI default applies.
- `grading` (A–D, deterministic, using the DDI-spec §4 rubric; first match wins):
  - **D**: item DQ is critical, or n < 100.
  - **C**: DQ warn, or SRM failed, or design power < 0.5, or n < 1000.
  - **A**: an experiment with RCT or holdout design, SRM passed, design power ≥ 0.8, and CI width ≤ 2 × MDE.
  - **B**: everything else.
- `stance`: the rule from §8. Materiality comes from the metric.

**4.2 `backend/config/orgs/fitconnect/analytics_config.yaml`** is the tenant configuration. FitConnect-specific values live **only** here, never in core code. It is hashed, and its hash is stored in `analysis_results.params`.
- `metrics` (D4-22), keyed by metric name:
  - `source_view` (allow-listed);
  - `kind: proportion | count`;
  - `defining_events`;
  - `denominator: users | trial_starters`;
  - `materiality` on the natural scale. Proposed: d90_retention 0.02, activation_rate_7d 0.02, paid_conversion_rate 0.02.
- `segment_keys`: one per metric (D4-09). `d90_retention: engagement_style`, `activation_rate_7d: platform`, `paid_conversion_rate: country`.
- `funnels`: the ordered onboarding steps (for the sequence check and the funnel analysis).
- `decision_analyses`, keyed by `scenario_key`, set the comparison-group definitions:
  - `ai_coach`: treatment = users with `ai_coach_session`, excluding experiment participants;
  - `community`: treatment = users with `challenge_joined`;
  - `pricing`: cohort = CA signups ≥ 2026-04-01 vs CA signups before it (`paid_conversion_rate`);
  - `onboarding`: funnel and trend on `activation_rate_7d`.

  Decisions without an entry get only the metric-level analyses and the analyses of their linked experiments.

---

## 5. Data quality (D4-01 to D4-05, D4-23)

- **Scope:** DQ runs per decision, over the views in its success metric's lineage and the views its planned analyses read.
- **Checks:**
  - **volume / tracking gap:** for each lineage event × platform, the per-signup daily rate in the recent window vs the baseline;
  - **sequence:** for configured funnels;
  - **completeness:** on required columns of the lineage views;
  - **duplicates:** `event_id`, and also (user, event, ts);
  - **referential:** event `user_id` not present in `v_users`.
- **`check_key`** = `"{data_source_id}|{check_type}|{target}"`, for example `…|volume|onboarding_completed@android`.
- **Severity** follows the thresholds, then the impact rule (4.1). Every finding stores `check_type`, `data_source_id`, `target`, `affects_metric_id`, `affects_success_metric`, `observed_value`, `threshold`, `severity`, and a deterministic `finding` text.
- **Re-runs update the row in place** (D4-03). Status reconciliation (D4-04):

| Current status | Re-run result | Action |
|---|---|---|
| open | defect present (any severity) | stays open, severity updated |
| open | defect gone (pass) | stays open with severity `pass`, because only a human resolves a check (audited as `dq.auto_cleared_pending_review`). Pass rows never block. |
| accepted | same or lower severity | stays accepted |
| accepted | worse | reopened as `open` + audit |
| resolved | defect still present | reopened as `open` + audit |
| resolved | defect gone | stays resolved |

  Automatic changes are audited with `actor_type = 'system'`. A status change after an assessment marks it stale (Day-3 rule).
- **Gate (frozen):** an open, critical check affecting the success metric's data source blocks. Accepted produces a warning. Resolved and pass are ignored.
- **Expected on seeded data:**
  - DEF-ONB-002 (`onboarding_completed@android`, a 60% drop) is **critical**, because it is in the lineage of `activation_rate_7d`.
  - DEF-ONB-001 (`onboarding_step_2_completed@android`, a 100% drop) and the step-3-without-step-2 sequence violation are **warn**, because step 2 is not a defining event.
  - AI Coach, Community and Pricing have **no critical** finding.

## 6. Heterogeneity (D4-06 to D4-10)

- **Inputs:** the decision's comparison-group definition, the success metric, and its single configured segment key.
- **Per segment:** effect = treatment rate − comparison rate, with n per arm. A segment is *eligible* if both arms have n ≥ `min_segment_n`. With fewer than `min_eligible_segments` eligible segments, the flag is **None (unknown)**, not False.
- **Flag = True** if any pair of eligible segments meets either rule:
  - **(A)** the effects have opposite signs and both |effects| are ≥ materiality;
  - **(B)** |effect_A − effect_B| ≥ materiality, and the two-proportion z-test of the difference has p < α / m, where m is the number of eligible pairs (Bonferroni).
- **Otherwise the flag is False.** Only within-segment effects are compared. The aggregate-vs-segment gap is **not** a criterion, because that is confounding (Reviewer territory).
- **Stored result** in `analysis_results.result`: `segment_key`, `segments_scanned`, `segments_eligible`, `min_segment_n`, `materiality_threshold`, `multiple_comparison_method`, `pairs_tested`, `alpha_adjusted`, per-segment effects and n, the triggering pair or pairs, and `flag`.
- **Segmentation produces no evidence item.** It feeds `heterogeneity_flag` only, which avoids counting the same data twice.
- **Expected:**
  - **Community: True**, from segments social_exerciser +0.196 and time_pressed −0.080.
  - **AI Coach** (segmenting on its configured key, `engagement_style`): **False**. Its adopter gap is positive in every segment; the inflation of the aggregate comes from selection on engagement tier, which is confounding, not heterogeneity.

  > If the seeded data does not give False for AI Coach, **report it with the numbers**. Do not tune thresholds to force the expected result.
- **Terminology:** "heterogeneity / aggregate masking". Never "Simpson's paradox".

## 7. Experiment statistics (D4-11 to D4-15)

- Experiments are discovered via `experiments.decision_id`. Raw data is read through `source_ref` (the experiment key), `control_variant` and `outcome_key` from the allow-listed views.
- **`experiment_results` (canonical, upserted per variant):**
  - n and `metric_value` for each variant;
  - on the treatment row only: effect = treatment − control on the natural scale (D4-13), CI and p (two-proportion or Welch), and `srm_flag`. The control row leaves these NULL.
- **SRM:** chi-square goodness-of-fit of the observed per-arm counts vs `planned_treatment_share`. The flag is set when p < `srm_alpha`. With no planned share, the flag is NULL and the DDI default applies. SRM is an integrity diagnostic, not evidence of an effect.
- **`analysis_results` (historical, insert-only):**
  - the method and design power at the MDE (labelled **"design power at the pre-registered MDE"**, never "observed power");
  - `mde`, the planned and observed allocation, expected and observed counts, chi-square and p;
  - `design_rank` and `limitations`;
  - the data-source fingerprint and parameter hashes.
- **Expected:**
  - **AI Coach holdout:** the SRM flag is **True** (30/70 vs a planned 50/50), design power is low, and the evidence is graded C.
  - **Pricing test:** the CI spans zero (inconclusive), design power at MDE 0.02 is well below 0.8, SRM passes, and the stance is neutral (`no_material_decrease`: the CI lower bound is not above −materiality and the upper bound is not below it).
  - D4 receives **observed**, not defaulted, power and SRM inputs whenever an MDE and a planned share exist.

## 8. Evidence materialisation (D4-16 to D4-21)

- **Ownership:** the analytics layer writes `analysis_results` only. A dedicated **evidence materialisation service** creates or updates evidence from analysis results through the existing evidence repository and validation.
- **Which analyses create evidence** (one item each):

| Analysis | Evidence item |
|---|---|
| group comparison on the success metric (AI Coach, Community, Pricing cohorts) | `behavioral`, `metric_id` = the success metric |
| experiment analysis | `experiment`, with `experiment_id` and `analysis_id` |
| trend on the success metric | `behavioral`, stance always **neutral** (descriptive) |
| funnel | `behavioral`, stance always **neutral** (descriptive) |

  Segmentation and evidence comparison create **no** evidence.
- **Identity:** `analysis_identity = sha256(decision_id | analysis_type | metric_id | experiment_id-or-segment_key-or-cohort_key | analysis_params_hash)`. The source fingerprint is **not** part of it (D4-16).
- **Same identity:**
  - if the values differ, update the active evidence in place (summary, n, effect, CI, grade, stance, `observed_end`, `source_fingerprint`, `analysis_id`), which triggers the Day-3 stale rule;
  - if nothing differs, do nothing. A no-op must **not** mark the decision stale.
- **New identity** (the parameters changed): insert new evidence. Set the old one to `status = 'superseded'`, with `superseded_by` and `superseded_at` filled. Never delete it (D4-19).
- **Stance (D4-21)**, comparative analyses only. With materiality *m* from the metric config:
  - **supports:** the CI excludes 0, the effect is in the expected direction, and |effect| ≥ m;
  - **contradicts:** the CI excludes 0, the effect is opposite to the expected direction, and |effect| ≥ m;
  - **neutral:** otherwise.

  - **`no_material_decrease`** (O1, approved): supports if the CI lower bound is above −m; contradicts if the CI upper bound is below −m; otherwise neutral.
- **Other fields:**
  - grade comes from §4.1 `grading`;
  - reliability tier comes from the `evidence_source` mapped from the analysis's `source_view` → `data_source`;
  - `observed_start` / `observed_end` come from the analysis window, which ends at or before the injected as-of date;
  - `created_by = 'agent'`;
  - `agent_run_id` is set;
  - the summary is a deterministic template.
- **Traceability:** every generated item has `analysis_id`. That `analysis_results` row has `query_text`, `params`, `n`, `result`, `limitations` and `dq_status`, so evidence → analysis → query → view → DQ resolves.

## 9. SQL guard and read-only execution

- **`backend/app/analytics/sql_guard.py`:**
  - parse with sqlglot (PostgreSQL dialect);
  - exactly one statement, and it must be SELECT (CTEs allowed);
  - no DML or DDL, no `SELECT INTO`, no locking clauses, no function calls in a deny-list (`pg_sleep`, `dblink*`, `lo_*`, `pg_read_file` and similar);
  - every table reference must be in the allow-list: the eight `fc_.v_*` views, `public.metric_observations` read-only, and nothing else;
  - a LIMIT is required, capped at `max_rows` (default 100,000; aggregation queries are fine);
  - rejections raise `SqlRejected`, which is logged.
- **Execution:**
  - its own transaction, with `SET LOCAL ROLE ddr_readonly`, `SET LOCAL statement_timeout = '30s'` and `SET TRANSACTION READ ONLY`;
  - parameters are bound, never interpolated.
  - The role is the real security boundary; the parser is defence in depth. The read-only role needs SELECT on `metric_observations` (add the grant in 0005).
- **All Day-4 analysis SQL** comes from parameterised templates in a catalogue, and **all of it goes through the guard**. No LLM SQL.

## 10. Pipeline, services and API

- **`services/pipeline.py` `run_pipeline(actor, decision_id)`:**
  - **Precondition:** the stage is `evidence_gathered`.
  - **Stages:**
    1. DQ (commit);
    2. Quantitative analyses, skipped for the success metric when an open critical DQ check affects it. A skipped analysis is recorded as skipped (blocked) in `agent_runs` output (commit);
    3. Customer evidence: **skipped, Day 5** (recorded as `skipped_day5`);
    4. Experiment analysis (commit);
    5. Evidence materialisation (commit);
    6. The Day-3 assessment run (unchanged service and transaction).
  - Each stage writes one `agent_runs` row (`model` NULL, `prompt_version` NULL, latency, status).
  - **If a stage raises:** insert a `partial` assessment with `blocking_reasons = [{"code": "stage_failed", "stage": …, "message": …}]` and stop. The stage stays at `evidence_gathered`, and the assessment metadata (hashes, fingerprint, as-of) is still required.
  - Determinism: injected as-of (`DDR_AS_OF_DATE`), and no wall clock in analytics.
- **API additions** (permission = run assessment):
  - `POST /decisions/{id}/pipeline-runs`
  - `GET /decisions/{id}/dq-checks`
  - `GET /decisions/{id}/analyses`
  - `GET /analyses/{id}`
- **Existing endpoint changes:**
  - `PATCH /dq-checks/{id}` keeps its Day-3 semantics.
  - The canvas endpoints accept and require `expected_direction`.

## 11. Required tests (definition of done)

**Guards**
- T-GUARD-1: `git diff f6209e9` shows no change to the frozen DDI and NBE paths in §0.
- T-GUARD-2: scope guard. `anthropic` and `agents` are never imported in `backend/app`; `sqlglot` appears only in `analytics/sql_guard.py`; no LLM SQL path exists.

**Configuration**
- T-CFG-1: analytics params and FitConnect config load with version and hash checks; a mismatch raises.

**Data quality**
- T-DQ-1: re-running unchanged data → the same rows (count and ids). No duplicates.
- T-DQ-2: each row of the §5 reconciliation table, including audit rows.
- T-DQ-3: impact rule. A size at the critical threshold on a non-lineage target becomes warn.
- T-DQ-4: Onboarding → DEF-ONB-002 critical with `affects_success_metric = true`; DEF-ONB-001 is warn.
- T-DQ-5: AI Coach, Community and Pricing → no critical finding.
- T-DQ-6: the facts builder reads checks by `decision_id`, and a check with a NULL `assessment_id` gates.

**Heterogeneity**
- T-HET-1: Community → True; the stored result has every field listed in §6.
- T-HET-2: AI Coach → False.
- T-HET-3: segments below `min_segment_n` are excluded; fewer than 2 eligible segments → None.
- T-HET-4: Bonferroni. A pair significant at α but not at α / m does not trigger rule B.
- T-HET-5: synthetic unit cases for rule A and rule B independently.

**Experiments**
- T-EXP-1: effect = treatment − control on the natural scale, and the CI uses the same scale.
- T-EXP-2: SRM uses `planned_treatment_share`. AI Coach → flag True; Pricing → False; a missing share → NULL.
- T-EXP-3: design power uses the MDE and the achieved n, and is independent of the observed effect (changing the outcome values without changing n leaves power identical). A missing MDE → None, so the DDI reports power as defaulted.
- T-EXP-4: Pricing CI spans 0 → stance neutral under `no_material_decrease`.
- T-EXP-5: `experiment_results` upsert → one row per (experiment, variant) after re-runs.

**Evidence**
- T-EVD-1: run → N; re-run unchanged → N, with no stale flag.
- T-EVD-2: change the source data → still N, values updated, decision stale.
- T-EVD-3: change the parameters → a new identity, the old item superseded (not deleted), and historical traceability still resolves.
- T-EVD-4: stance-rule truth table, for increase, decrease and no_material_decrease.
- T-EVD-5: `expected_direction` is required by the canvas and is in the stale-column list.
- T-EVD-6: every generated item has `analysis_id`, and the traceability chain resolves through to the query and view.
- T-EVD-7: grading truth table.

**SQL guard**
- T-SQL-1: the guard rejects:
  - multiple statements and DML or DDL;
  - non-allow-listed tables (including `fc_.users`, `fc_.feedback_ground_truth` and core tables);
  - denied functions;
  - a missing LIMIT;
  - `SELECT INTO`.
- T-SQL-2: execution runs as `ddr_readonly` in a read-only transaction with a timeout. A mutation slipped past the parser is still rejected by the database.

**Pipeline**
- T-PIPE-1: end-to-end runs for all four seeded decisions. Assert **states and inputs, not bands**:
  - **Onboarding:** INSUFFICIENT with an `open_critical_dq` reason, and no number anywhere.
  - **Onboarding after resolving DEF-ONB-002** (accepting is also valid): the DQ reason is gone, and the gate reasons are only type and count related (O2).
  - **AI Coach and Pricing:** scored or insufficient as the evidence dictates. D4 inputs are **observed** (power and SRM not defaulted).
  - **Community:** the heterogeneity flag is True in the facts. After adding one manual customer evidence item (O2), the assessment is scored with **P1 ≥ 0.3**.
- T-PIPE-2: stage failure → partial assessment, stage unchanged, an `agent_runs` failure row.
- T-PIPE-3: determinism. Two pipeline runs on the same data give byte-identical assessment payloads (excluding ids and timestamps).

**Regression**
- T-REG-1: all 272 Day-3 tests still pass (adjust only where 0005 legitimately changes behaviour, and list each one).
- T-REG-2: clean rebuild (`downgrade base` → `upgrade head` → seed → validate 33/33 → pytest).
- T-REG-3: downgrade `0005` → `0004` works.

## 12. Documentation to update

- `docs/day-4-implementation-notes.md` (new): decisions D4-01 to D4-25 and the O1–O3 answers, parameter values with their justification against the seeded data, the hashes, migration 0005, and the expected-vs-observed table for the seeded scenarios.
- ERD, PRD (§14, §15 A2, §16, §20), traceability spec (evidence status), decision-canvas (`expected_direction`), DDI-spec (a pointer only: "inputs now observed when available", no maths change).

## 13. Execution order

1. Migration 0005 and the seed updates.
2. Config files, loaders and hashes.
3. SQL guard and read-only executor.
4. DQ, with its reconciliation.
5. Experiment statistics.
6. Group comparison, trend and funnel.
7. Heterogeneity.
8. Evidence materialisation.
9. Facts-builder changes.
10. Pipeline and API.
11. Tests.
12. Documentation.
13. Clean rebuild.

Stop after Day 4. Report any deviation explicitly.
