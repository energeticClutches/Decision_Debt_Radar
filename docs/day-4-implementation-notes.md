# Day 4: Implementation Notes

Parent: [day-4-implementation-brief.md](day-4-implementation-brief.md) (binding), [day-3-implementation-notes.md](day-3-implementation-notes.md), [DDI-spec.md](DDI-spec.md). **FitConnect is a fictional company. All FitConnect data is SYNTHETIC.** Baseline (rollback point): commit `f6209e9`.

Scope: the deterministic **Data & Analytics foundation**: data quality, experiment statistics, group comparison / trend / funnel, heterogeneity, evidence generated from analyses with full traceability, the SQL guard with read-only execution, and the deterministic pipeline (stages 1, 2 and 4, plus materialisation and the unchanged Day-3 assessment). No LLM, no agents, no Evidence Synthesis, Reviewer, customer-theme extraction or brief (Day 5), no anomaly detection, revenue modelling, causal inference or ML, no frontend, no Power BI. `fc_.feedback_ground_truth` is never used by product code.

> **The hard rule (D4-25).** The DDI and NBE mathematics, parameters, bands and semantics are unchanged. `git diff f6209e9 -- backend/app/domain/ddi backend/app/domain/nbe backend/config/ddi backend/config/nbe` is empty, and `params_hashes.json` only gained the `analytics_params_v0.1` entry. Test T-GUARD-1 (`tests/backend/test_day4_guards.py`) enforces it. The only Day-3 code touched outside Day-4 additions is the facts builder and fingerprint (`repositories/evidence_facts.py`), exactly as the brief names.

## 1. Architecture

```
backend/app/
  analytics/        deterministic Data & Analytics capability (no LLM, no agents)
    config.py         AnalyticsParams, TenantConfig (typed access, structural validation)
    sql_guard.py      the ONLY module that imports sqlglot
    queries.py        catalogue of parameterised SQL templates (QueryTemplate)
    executor.py       read-only executor: own connection and transaction, role ddr_readonly
    stats.py          pure statistics: differences, SRM, design power, heterogeneity, stance, grade
    dq.py, dq_store.py   data-quality checks and their reconciliation
    experiments.py    experiment analysis
    analyses.py       comparison, segmentation, trend, funnel, experiment drafts
    store.py          analysis_results rows, identity, fingerprint, de-duplication
  repositories/     analysis.py, agent_runs.py, experiments.py (new); dq.py, evidence.py, evidence_facts.py (extended)
  services/         pipeline.py, evidence_materialization.py, analyses.py (new); lifecycle.py (mark_stale_system)
  api/routes/analytics.py   POST /decisions/{id}/pipeline-runs, GET dq-checks, GET analyses, GET /analyses/{id}
backend/config/analytics/analytics_params_v0.1.yaml    generic methods and thresholds (hashed, registered)
backend/config/orgs/fitconnect/analytics_config.yaml   FitConnect tenant configuration (hashed)
database/sql/0005_day4_analytics.sql (+ _down), database/migrations/versions/0005_day4_analytics.py
```

`agents/` stays reserved for the Day-5 LLM agents and is untouched (O3). `backend/app` still never imports `anthropic` or `agents`; `sqlglot` appears only in `analytics/sql_guard.py` (test T-GUARD-2). The analytics package never commits (only services open transactions) and reads no clock (the as-of date is injected).

## 2. Decisions D4-01 to D4-25 and open points O1 to O3: where implemented

The numbering follows the brief's section references.

| Decision | Implementation |
|---|---|
| D4-01/02/03 DQ checks per decision, in place | `dq_checks.decision_id NOT NULL`, `UNIQUE(decision_id, check_key)`, `assessment_id` nullable, new columns (`check_key`, `target`, `observed_value`, `threshold`, `affects_success_metric`, `source_snapshot`, `last_run_at`). `check_key = "{data_source_id}|{check_type}|{target}"`. Re-runs update the row in place (`analytics/dq_store.py`) |
| D4-04 status reconciliation | the six-row table of brief section 5, implemented in `dq_store.reconcile` and tested row by row (`test_day4_dq.py`, T-DQ-2). Automatic changes are audited with `actor_type = 'system'` (`dq.severity_changed`, `dq.auto_cleared_pending_review`, `dq.reopened`). A reopen after an assessment marks it stale |
| D4-05 gate reads checks by `decision_id` | facts builder reads `dq_checks.decision_id`; a check with a NULL `assessment_id` gates (T-DQ-6). The decided-guard on `dq_checks` is re-pointed to `decision_id` in 0005 |
| D4-06 to D4-10 heterogeneity | `analytics/stats.py::evaluate_heterogeneity`, `analytics/analyses.py::comparison_analyses` (the segmentation analysis). Rules A and B, Bonferroni over the eligible pairs, `None` (unknown) below 2 eligible segments, no evidence item, `heterogeneity_flag` from the latest segmentation analysis |
| D4-11 to D4-15 experiment statistics | `analytics/experiments.py`, `stats.py`. `experiment_results` upsert (`UNIQUE(experiment_id, variant)`), SRM against `planned_treatment_share`, design power at the MDE, `analysis_results` insert-only with identity, `params_hash`, `source_fingerprint` |
| D4-16 to D4-21 evidence materialisation | `services/evidence_materialization.py`. Identity, in-place update, no-op, supersede (`status`, `superseded_by`, `superseded_at`), stance rule, grading, traceability |
| D4-20 + O1 `expected_direction` | `decisions.expected_direction NOT NULL CHECK (increase, decrease, no_material_decrease)`, required by the canvas (service, API and database), in the canvas-stale column list of the lifecycle guard. Seeded: AI Coach, Onboarding, Community `increase`; Pricing `no_material_decrease` |
| D4-22 metric configuration | `analytics_config.yaml` `metrics` (source view, kind, defining events, denominator, materiality), `segment_keys`, `funnels`, `decision_analyses` |
| D4-23 impact over size | `analytics_params_v0.1.yaml` `severity_rule`; `dq.apply_impact_rule` |
| D4-24 no DDI band expectations | no Day-4 acceptance test asserts a band |
| D4-25 hard rule | T-GUARD-1 |
| O1 `no_material_decrease` | `stats.stance_for` (supports if the CI lower bound is above -materiality, contradicts if the upper bound is below it, else neutral) |
| O2 | Day 4 generates only behavioral and experiment evidence. Community and the resolved-DQ Onboarding case stay INSUFFICIENT (min_items, min_types). Test T-PIPE-1 adds one manual customer item through the Day-3 API to show the scored path |
| O3 | analytics in `backend/app/analytics/`, pipeline in `backend/app/services/pipeline.py`; `agent_runs.agent_name` records `data_analytics` and `orchestrator` with `model = NULL`. Scope guard: `sqlglot` only in `analytics/sql_guard.py` |

## 3. Migration 0005

`database/sql/0005_day4_analytics.sql` (never edits 0001 to 0004; follows the 0004 pattern; the 0004 lifecycle guard is replaced again with `CREATE OR REPLACE`).

| Change | Detail |
|---|---|
| `decisions` | `expected_direction text NOT NULL` with a CHECK. Backfilled by `scenario_key` (pricing `no_material_decrease`, others `increase`), then the default is dropped so the canvas must supply it. The backfill disables the lifecycle guard for that one statement (a schema change, not a canvas edit). The guard function adds `expected_direction` to the canvas-stale list |
| `dq_checks` | `decision_id NOT NULL` (FK), `assessment_id` nullable, `check_key`, `target` NOT NULL, `observed_value`, `threshold`, `affects_success_metric`, `source_snapshot`, `last_run_at`, `UNIQUE(decision_id, check_key)`, index on `decision_id`. Existing rows are backfilled from their assessment. The decided-guard trigger is re-pointed to `ddr_decided_guard_decision_id` |
| `experiments` | `planned_treatment_share` (CHECK > 0 and < 1), `control_variant`, `outcome_key` |
| `experiment_results` | `UNIQUE(experiment_id, variant)` |
| `evidence` | `status` (`active` / `superseded`), `superseded_by`, `superseded_at`, `analysis_identity`, `source_fingerprint`; CHECK that a superseded item has both supersede fields; partial unique index `(decision_id, analysis_identity) WHERE status = 'active' AND analysis_identity IS NOT NULL`; index on `analysis_id` |
| `analysis_results` | `analysis_identity`, `params_hash`, `source_fingerprint`; trigger `ddr_analysis_results_immutable` (rows are historical: only `agent_run_id` may change after insert; **added to enforce the brief's statement**); index `(decision_id, analysis_identity)` |
| views | `v_evidence_freshness` and `v_evidence_health` count active evidence only. `v_traceability_matrix` keeps every evidence row and adds `evidence_status`; its DQ column is per decision; gap rows count active evidence. The views select explicit columns, so they do not depend on later-added columns (a view using `x.*` blocked the 0004 downgrade) |
| role | `GRANT SELECT ON public.metric_observations TO ddr_readonly` |

`_down.sql` restores the 0003 views, the 0004 lifecycle guard and the 0004 `dq_checks` guard, deletes `dq_checks` rows without an assessment link (they exist only from Day 4) and drops the new columns. Superseded evidence is kept as ordinary rows (claims of historical assessments may reference them). Tests: upgrade from empty, `downgrade base`, `upgrade head`; `downgrade 0005 -> 0004` with Day-4 data present, then upgrade again (`tests/db/test_migrations.py`); constraints and guards (`tests/db/test_day4_schema.py`).

`database/seed/core_seed.py` sets `planned_treatment_share = 0.5` on both experiments, `control_variant` to `holdout` / `control_9_99`, `outcome_key` to `workouts_14d` / `converted_to_paid`, and `expected_direction` for the four decisions. The generator and every generated CSV are unchanged.

## 4. Configuration and hashes

| File | SHA-256 | Registry |
|---|---|---|
| `backend/config/analytics/analytics_params_v0.1.yaml` | `b3dfcee11c9e0d61572f471905f03e19f5641ddbdabc723f61abae62a1fa2e05` | `params_hashes.json` entry `analytics_params_v0.1` (the only change to that file) |
| `backend/config/orgs/fitconnect/analytics_config.yaml` | `912ba893711b2105cad2fc100f8ede2d28f604aac753f604b48539f96e868bc9` | `backend/config/orgs/config_hashes.json` (see below) |
| `backend/config/ddi/ddi_params_v0.1.yaml` | `fd2541522b34f0fa2344076048f656fee8df8e9023148445fe53b3c7c119bcee` | unchanged |
| `backend/config/nbe/nbe_params_v0.1.yaml` | `8a7c730edb77fc7b7f69cce487bce99fba5ace660f1c028c8cb6692221546ff7` | unchanged |

`app.core.params.load_analytics_params` uses the same version, hash and `ParamsError` checks as the DDI loader (missing file, unregistered version, hash mismatch, `version` field mismatch). `load_tenant_config` additionally requires the tenant file to declare the active `analytics_params_version` and its own `org_key`. Because `params_hashes.json` may only gain the analytics entry, the tenant configuration's hash is registered in a **separate registry** next to the tenant files (`orgs/config_hashes.json`). Both files are validated structurally at load (thresholds ordered, directions exhaustive, every referenced view, column and funnel exists, identifiers match a strict pattern). `analysis_results.params.config` stores the parameter and tenant versions and hashes. FitConnect-specific values (metric, event, segment and view names, comparison groups) live only in the tenant file (test `test_cfg_1_tenant_values_live_only_in_the_tenant_file`).

## 5. Methodology as implemented (and the points the brief left open)

**SQL guard and executor.** One statement, SELECT only (CTEs allowed, data-modifying and recursive CTEs rejected), no DML, DDL, SELECT INTO, locking clause or command, no table-valued function, every table schema-qualified and allow-listed (the eight `fc_.v_*` views and `public.metric_observations`; CTE names are not tables), deny-listed functions (`pg_sleep*`, `dblink*`, `lo_*`, `pg_read_*`, `set_config`, `generate_series`, `repeat` and similar), an integer-literal LIMIT up to `max_rows` (100,000), and no `;` separator other than one trailing terminator (a belt-and-braces check against a parser differential). Execution: its own connection and transaction, `SET TRANSACTION READ ONLY`, `SET LOCAL ROLE ddr_readonly`, `SET LOCAL statement_timeout = '30s'`, `SET LOCAL TIME ZONE 'UTC'`, parameters bound by the driver. The executor accepts only a catalogue `QueryTemplate`; all analysis SQL is built from parameterised templates in `queries.py`. **Known limit, documented honestly:** in the local stack the application connects as the database owner, so a statement that escaped the parser could `RESET ROLE`; the READ ONLY transaction would still reject every write (tested). A deployment should connect with a role that cannot `SET ROLE`.

**Data quality.**
- *Window anchoring (the brief does not fix it).* Rates are per signup, so the window ends on the **last day on which the source has signups at or before the as-of date** (2026-08-31 in the seeded data; the events run to 2026-09-30 but nothing is signed up after August). With `window_days` 56, the baseline is the oldest 28 days (2026-07-07 to 2026-08-03) and the recent window the newest 14 (2026-08-18 to 2026-08-31). Anchoring on the as-of date would leave no signups in the recent window and the defect could not be seen.
- *Volume.* Per lineage event x platform, rate = events per signup over the window (ratio of sums; events by event platform, signups by user platform); drop = 1 - recent/baseline. *Sustained* (the brief names `min_sustained_days: 7` without defining it): the drop is reported only if at least 7 of the 14 recent days have a daily rate below the warn level (75% of the baseline rate); otherwise the finding is pass with an explanation. No baseline events or no recent signups: pass with an explanation.
- *Sequence.* For each adjacent pair of a configured funnel and each platform, users of the window cohort with step k and without step k-1 as a share of the cohort users. It is in the lineage if either event of the pair is a defining event of the success metric.
- *Completeness, duplicates, referential.* Over the events window for the events view, over all rows for the others. Pass rows are stored (they make re-runs idempotent and never block).
- *Severity.* thresholds use `>=`; a size of 0 or less is always pass (so `referential.warn_rate: 0.0` means any orphan row warns). Then the impact rule. `observed_value` is the measured size, `threshold` the one that decided the raw severity, and the finding text states a cap.
- *Lineage.* A volume or sequence target is in the lineage if its event is a defining event of the success metric; completeness, duplicates and referential targets are in the lineage if the view is a lineage view of the metric.

**Comparisons, trend and funnel.** A metric's per-user outcome is read from the configured source view (`event_after_days`, `event_within_days`, `subscription_status`). A cohort is used only when its signup is at least `maturity_days` before the as-of date (`d90_retention` 92 days, so the cohort is signups before 2026-07-01 as in the metric definition; `activation_rate_7d` 7; `paid_conversion_rate` 0). *Group comparison:* effect = treatment rate - comparison rate, 95% Wald interval (unpooled), pooled z test. AI Coach: treatment = users with an `ai_coach_session` excluding the users of the decision's linked experiments (found through `experiments.source_ref`), comparison = all other users; Community: treatment = users with `challenge_joined`; Pricing: CA signups on or after 2026-04-01 vs CA signups before it. *Trend:* weekly values by signup week over a 26-week look-back, complete weeks only, plus the pooled value of the last 4 weeks against the weeks before it. It is descriptive: no test and no effect or CI is stored. *Funnel:* the ordered steps over the signups of the 56-day window, overall and by platform. The parameters `trend.lookback_weeks` (26), `trend.recent_weeks` (4) and `funnel.cohort_window_days` (56) are Day-4 choices for descriptive analyses (the brief names the analyses without parameters). Every decision also gets the metric-level trend (the brief's "metric-level analyses"); the Community and Onboarding gate counts depend on it (O2).

**Heterogeneity.** The segment key is the metric's single configured key. Pricing's comparison group is CA only, so its country segmentation has one segment and the flag is **None (unknown)**. I did not widen the comparison to other countries (that would be new methodology). Onboarding has no comparison group, so no segmentation is stored and the facts flag is None.

**Experiments.** Outcome kind is read from the data (all values in {0, 1}: proportion, two-proportion test; otherwise continuous, Welch's t). The SRM uses the assignment counts. **Design power** uses the control arm's rate as the baseline for proportions and the pooled SD (as the brief states) for continuous outcomes, with the achieved n and allocation; it takes no observed-effect input (test T-EXP-3 changes the treatment outcomes with n fixed and the power is identical). Materiality for an experiment's stance is the metric's materiality when the experiment's primary metric is the decision's success metric (Pricing), otherwise the tenant `experiment_outcomes` entry for its outcome (`workouts_14d`: 0.5, the experiment's pre-registered MDE, chosen because the retention materiality 0.02 cannot apply to a workout count); without either the stance is neutral.

**Evidence.** Grading and the stance rule are the brief's, implemented in `stats.py`. The analysis' `dq_status` (carried into the grade as the item's DQ) is the worst severity among the decision's open or accepted checks on the data sources the analysis read, the same rule the Day-3 DDI uses for `dq_factor`. Trend and funnel items have `effect_size` NULL. **Superseded by Day 4.1:** they were first materialised linked to the success metric, so D6 reported their materiality as a defaulted 0 and they lowered the D6 mean. They are now materialised with `metric_id = NULL` and do not count toward D6 (section 11). The `analysis_params_hash` covers the analytics-parameter version, the metric configuration, the comparison group, the segment key and the relevant parameter sections, so a parameter change is a new identity, while a data change keeps the identity and updates the item in place. The source fingerprint is the SHA-256 of the aggregated rows an analysis consumed. An analysis whose content hash equals the latest row of the same identity is reused instead of inserted (the table stays insert-only without duplicates).

**Pipeline.** `PipelineService.run`: DQ, quantitative analyses, customer (recorded `skipped_day5`), experiment analysis, materialisation, the unchanged Day-3 assessment. One `agent_runs` row per stage (`data_analytics` for dq, quant, experiment; `orchestrator` for the others; materialisation and assessment rows have no `pipeline_stage` enum value because `synthesis` is reserved for Day 5). A blocked quant stage is recorded as `partial` with `skipped (blocked)` entries. A stage that raises rolls back its own transaction, then inserts a `partial` assessment with `blocking_reasons = [{"code": "stage_failed", ...}]` and the full assessment metadata, writes a `failed` run row and an audit row, and stops; the stage stays `evidence_gathered`. Earlier stages stay committed.

**Resolving versus accepting (an interaction to note).** The reconciliation table reopens a *resolved* check whose defect is still present. So after "resolving" DEF-ONB-002 without fixing the data, the next pipeline run reopens it and blocks again; **accepting** survives a re-run (same severity stays accepted). Both are tested (`test_day4_pipeline.py`). The Day-3 gate on the stored state does ignore a resolved check.

## 6. Parameter values and their justification against the seeded data

| Value | Where | Justification |
|---|---|---|
| DQ window 56 / baseline 28 / recent 14 / sustained 7 | brief | the DEF-ONB defect starts 2026-08-03 and the last signup is 2026-08-31, so the baseline (07-07 to 08-03) is clean and the recent window (08-18 to 08-31) is wholly after the release. Android `onboarding_completed` per-signup rate 0.550 to 0.207 (-62%), below the warn level on 14 of 14 recent days |
| volume warn 25% / critical 50% | brief | android completion -62.4% is critical and in the lineage; ios -0.8% and web -2.7% pass; `app_open` (AI Coach, Community lineage) never drops |
| sequence 2% / 10%, completeness 1% / 5%, duplicates 0.1% / 1%, referential 0 / 0.1% | brief | seeded data: no nulls, no duplicate `event_id` or (user, event, ts), no orphan user in any checked view; the only sequence violation is step 3 without step 2 on android (29.6% of the window's android signups, 1,124 of 3,794) |
| `min_segment_n` 500 | brief | the smallest arm of the seeded comparisons is 735 (Community, time_pressed, treatment), so every engagement segment is eligible. The Pricing country segmentation has one segment |
| heterogeneity alpha 0.05, Bonferroni | brief | 3 eligible segments, 3 pairs, adjusted alpha 0.0167 |
| materiality 0.02 (d90 retention, activation, conversion) | brief proposal | Community: +0.196 and -0.080 are far beyond it. AI Coach: the largest within-segment gap difference is 0.0196, just below 0.02, **but** its p value is 0.21 (adjusted alpha 0.0167), so rule B fails on significance as well: the False result does not depend on the materiality value |
| `workouts_14d` materiality 0.5 | tenant | the pre-registered MDE of the AI Coach holdout |
| `maturity_days` 92 for d90 | tenant | signup before 2026-07-01, identical to the metric definition and the manifest's retention cohort |
| SRM alpha 0.001, power alpha 0.05 two-sided | brief | AI Coach p = 3.9e-54 (flag), Pricing p = 1.0 (pass) |
| grading thresholds | brief (DDI-spec section 4) | AI Coach holdout C (SRM failed), Pricing test C (power 0.11), observational items B (n at least 1,000, DQ pass) |
| confidence level 0.95, trend 26 / 4 weeks, funnel window 56 days | Day-4 choices | descriptive analyses only; they change no gate or score input |

## 7. Expected vs observed: the four seeded scenarios

| | Expected (brief) | Observed |
|---|---|---|
| **Onboarding DQ** | DEF-ONB-002 `onboarding_completed@android` critical, in the lineage; DEF-ONB-001 `onboarding_step_2_completed@android` and the step-3-without-step-2 sequence violation warn | critical 0.6242 (threshold 0.5), `affects_success_metric` true; step 2: size 1.000, raw critical, **warn** (capped, not in the lineage); sequence: size 0.2963, raw critical, **warn** (capped). 41 pass, 2 warn, 1 critical |
| **AI Coach / Community / Pricing DQ** | no critical finding | 35 / 23 / 28 checks, all pass |
| **Community heterogeneity** | True (social_exerciser +0.196, time_pressed -0.080) | **True**: social_exerciser +0.1956 (n 5,556 / 6,564), solo_athlete +0.0001 (2,235 / 18,115), time_pressed -0.0795 (735 / 7,525). Rule A triggered by social vs time_pressed; all three pairs also pass rule B (adjusted alpha 0.0167) |
| **AI Coach heterogeneity** | False | **False**: social_exerciser +0.2400 (1,862 / 10,258), solo_athlete +0.2204 (2,949 / 17,401), time_pressed +0.2281 (1,173 / 7,087); pair differences 0.0196, 0.0119, 0.0077, p = 0.211, 0.539, 0.662. Aggregate +0.2304 |
| **Pricing heterogeneity** | not specified | None (unknown): one eligible segment (CA, 1,559 / 1,848) |
| **AI Coach holdout** | SRM True (30/70 vs 50/50), power low, graded C | SRM **True** (chi-square 240.0, p 3.9e-54), graded **C**. **Design power at the MDE is not low: 0.9999** (MDE 0.5 workouts, pooled SD 1.58, n 450 / 1,050). The grade is C because of the SRM failure, not the power. *Reported, not tuned* |
| **Pricing test** | CI spans 0, power well below 0.8, SRM passes, neutral | effect -0.0204, 95% CI [-0.0752, +0.0343], p 0.464; SRM passes (chi-square 0.0); design power **0.109**; stance **neutral**; graded C |
| **Pricing CA cohort** | (CA conversion falls) | effect -0.1120, CI [-0.1434, -0.0805], n 3,407, stance **contradicts**, grade B |
| **D4 inputs observed** | power and SRM observed whenever MDE and planned share exist | AI Coach and Pricing: `power_factor`, `integrity_factor`, `informativeness_factor` all `observed`, no defaulted D4 input |
| **Onboarding pipeline** | INSUFFICIENT with `open_critical_dq`, no number anywhere | INSUFFICIENT, reasons min_items, min_types, success_metric_evidence, open_critical_dq; quant stage `partial` (trend and funnel skipped as blocked); no number, no evidence |
| **Onboarding after accepting DEF-ONB-002** | the DQ reason is gone, only type and count reasons | reasons `min_items`, `min_types`; two behavioral neutral items (trend, funnel), graded D (an accepted critical issue still lowers the item's DQ). **Day 4.1:** reasons are now `min_items`, `min_types`, `success_metric_evidence` (descriptive items no longer link to the metric) |
| **Community with one manual customer item** | scored, P1 at least 0.3 | scored (version 2), **P1 = 0.3** (floor, heterogeneity flag observed True) |
| **AI Coach / Pricing pipeline** | scored or insufficient as the evidence dictates | both **scored** (3 items, 2 types). DDI values are reported in the run output and are not asserted (D4-24) |

Evidence produced (type, stance, grade, `analysis_id` present):

| Decision | Items |
|---|---|
| AI Coach | behavioral comparison supports B; behavioral trend neutral B; experiment neutral C. All have `analysis_id` |
| Community | behavioral comparison supports B; behavioral trend neutral B (2 items, so INSUFFICIENT until a third item is added) |
| Pricing | behavioral comparison (CA cohort) contradicts B; behavioral trend neutral B; experiment neutral C |
| Onboarding | none while the critical DQ check is open; after acceptance: behavioral funnel neutral D, behavioral trend neutral D |

The AI Coach experiment's stance is neutral because its effect (+0.293 workouts, CI [+0.118, +0.469]) is below its materiality (0.5). Segmentation creates no evidence item.

## 8. API

New: `POST /decisions/{id}/pipeline-runs` (permission: run assessment; 201 with the stage outputs and the assessment, also for a partial run), `GET /decisions/{id}/dq-checks`, `GET /decisions/{id}/analyses`, `GET /analyses/{id}` (with the evidence ids that point at it). The three GETs are read-only and, like every Day-3 read, open to every demo persona (the brief's "permission = run assessment" is applied to the POST; **an interpretation to confirm**). `PATCH /dq-checks/{id}` keeps its Day-3 semantics. The canvas endpoints accept and require `expected_direction` (`POST /decisions` returns 422 without it; `PATCH /decisions/{id}/canvas` may change it and marks an assessed decision stale). Evidence and DQ responses gained the Day-4 fields.

## 9. Tests

All tests named in brief section 11 are implemented:

| Test | File |
|---|---|
| T-GUARD-1, T-GUARD-2, T-CFG-1 | `tests/backend/test_day4_guards.py` (T-GUARD-2 also in the updated `test_scope_guard.py`) |
| T-SQL-1, T-SQL-2 | `tests/backend/test_day4_sql_guard.py` |
| T-DQ-1, 2, 4, 5, 6 | `tests/backend/test_day4_dq.py`; T-DQ-3 in `test_day4_stats.py` |
| T-HET-1, 2 | `tests/backend/test_day4_analytics.py`; T-HET-3, 4, 5 in `test_day4_stats.py` |
| T-EXP-1 to 5 | `test_day4_analytics.py` and `test_day4_stats.py` |
| T-EVD-1, 3, 5, 6 | `tests/backend/test_day4_evidence.py`; T-EVD-2 in `test_day4_scratch_data.py` (a scratch database with committed data changes); T-EVD-4, 7 in `test_day4_stats.py` |
| T-PIPE-1, 2, 3 and the API | `tests/backend/test_day4_pipeline.py` |
| T-REG-1, 2, 3 | the full suite; `tests/db/test_migrations.py` (downgrade 0005 to 0004); the clean rebuild below |
| migration 0005 invariants | `tests/db/test_day4_schema.py` |

**Result.** Full suite after Day 4: **476 passed** (the Day-3 suite had 272; one existing parametrised case was added for `expected_direction`, 203 tests are new), plus the 33 manifest checks (`python -m database.seed.validate`). Verified from an empty database: `alembic downgrade base`, `upgrade head`, `python -m database.seed.run --regenerate` (the generated data is byte-identical: the generator is frozen and only `core_seed.py` changed), `python -m database.seed.validate` (33/33), `pytest`. The `agents/` placeholder docstrings still say "Day 4" and were left untouched on purpose (no `agents/` code on Day 4; O3).

Day-3 tests adjusted only where 0005 legitimately changes behaviour (each listed): `tests/backend/flow.py` canvas gains `expected_direction`; `flow.insert_dq_check` inserts the per-decision columns; `tests/backend/conftest.py` skips unless migrated to 0005; `tests/db/conftest.py::new_decision` supplies `expected_direction`; `tests/db/test_constraints.py` (three raw decision inserts gain the column and two assertions check it is required and limited); `tests/db/test_day3_guards.py` (the dq_checks insert carries `decision_id`, `check_key`, `target`; the canvas-stale column list gains `expected_direction`); `tests/db/test_migrations.py` (revision 0005); `tests/backend/test_scope_guard.py` (sqlglot allowed only in `analytics/sql_guard.py`).

## 10. Known limitations and not done

- No customer evidence is generated (Day 5): Community and the accepted-DQ Onboarding stay INSUFFICIENT until a manual item is added (O2).
- Trend and funnel are descriptive: no slope, CI or test. Since Day 4.1 they do not count toward D6 (section 11).
- Comparisons are observational and say so; no causal claim is made.
- Group comparison and trend support proportion metrics only; a `count` metric raises an analytics error (no seeded decision needs it).
- The sustained-drop rule, the window anchoring, the trend and funnel parameters and the experiment materiality fallback are documented interpretations of points the brief left open (section 5).
- AI Coach's design power at its MDE is high; the brief expected it to be low (section 7).
- The read-only role is a hard boundary only for an application user that cannot `SET ROLE` (section 5).
- The DDI is still an uncalibrated heuristic (DDI-spec section 12); Day 4 supplies its inputs, it does not change it.

## 11. Day 4.1 remediation (two Product Owner findings from the independent Day-4 review)

Baseline: the Day-4 working tree (Alembic head 0005, no new migration). Brief: [day-4.1-remediation-brief.md](day-4.1-remediation-brief.md).

**NBE v0.2 (blocker dependency).** `backend/config/nbe/nbe_params_v0.2.yaml` is `nbe_params_v0.1` plus the `blocker_dependencies` section (three entries since Day 4.1b) (version string and header comment aside, the values are identical; `tests/unit/test_config_params.py` compares them). Hash `c46727dd40fc642c01ea1cb490b346e41242dce11823bc55481210dc747658b2` (after the Day 4.1b widening), registered in `params_hashes.json`, references `ddi_params_v0.1`, validated by the existing loader (hash, version and DDI-reference checks). It is the active default (`NBE_PARAMS_VERSION`, `app.core.config`, `.env.example`); v0.1 stays loadable. Code: `backend/app/domain/nbe/params.py` reads the section (`BlockerDependency`, `NbeParams.may_claim_blocker`), `engine.py` applies it where an insufficient-state action claims a blocker. Rule and effect: [NBE-spec.md](NBE-spec.md) section 3a. Under v0.1 the engine output equals the baseline `f6209e9` (golden file `tests/backend/golden_nbe_v01.json`, generated from the baseline code).

**Descriptive evidence and D6 (option (a), B2).** `evidence_materialization.build_candidate` sets `metric_id = NULL` for trend and funnel evidence (comparison keeps the success metric; experiment evidence already had none). The frozen DDI engine selects D6 items by `metric_id == success_metric_id`, so descriptive items drop out of D6 with no change under `backend/app/domain/ddi`. They stay active evidence with their `analysis_id`, in the evidence list, the facts items and `v_traceability_matrix`. The analysed metric stays in the analysis row and in the trend and funnel summaries. `analysis_identity` is taken from the analysis (it never used `evidence.metric_id`), so identities and the idempotent re-run are unchanged.

**Known consequences (reported, not worked around).**
1. Descriptive evidence no longer counts as evidence directly linked to the success metric for the DDI gate. Gate reasons before and after: AI Coach, Community and Pricing unchanged (each has a comparison item); Onboarding with the DQ issue open unchanged (no evidence exists); **Onboarding after accepting DEF-ONB-002: `min_items`, `min_types` become `min_items`, `min_types`, `success_metric_evidence`**.
2. Rows written by an earlier Day-4 run keep their old `metric_id` until the evidence is regenerated (the in-place update compares summary, n, effect, CI, grade, stance, observed_end and fingerprint, not `metric_id`). The seeds are rebuilt from scratch, so nothing in the repository is affected.
3. **R-NBE-1 (resolved in Day 4.1b, PO-approved).** With the dependency limited to `success_metric_evidence`, extend and targeted_survey (priority 1.4) still outranked fix-DQ (0.333) in the Onboarding open-DQ state. The dependency was widened in place (v0.2 had not been committed or used by a stored assessment) to `min_items` and `min_types` as well: while `open_critical_dq` is present no action may claim any other blocker unless it resolves `open_critical_dq`. No engine code changed. The Onboarding open-DQ recommendations are now only `fix_dq_or_instrumentation` (rank 1, 1 blocker, priority 0.3333); under v0.1 it was rank 7 of 7 behind extend (3.0), survey (1.4), segment (1.0), interview and financial (0.4667), holdout (0.375). New v0.2 hash `c46727dd40fc642c01ea1cb490b346e41242dce11823bc55481210dc747658b2`.

**Tests.** `tests/backend/test_nbe_v02.py` (new), `tests/backend/test_d6_descriptive.py` (new, pure), `tests/backend/test_d6_descriptive_db.py` (new, real pipeline), `tests/backend/nbe_v01_cases.py` and `golden_nbe_v01.json` (the v0.1 preservation proof). Changed pre-existing tests:

| Pre-existing test | Change | Reason |
|---|---|---|
| `test_day4_guards.py` T-GUARD-1 | replaced by five tests: DDI paths unchanged; `nbe_params_v0.1.yaml` unchanged and `nbe_params_v0.2.yaml` the only new NBE file; NBE code changes confined to `params.py` and `engine.py`; the registry gains exactly `analytics_params_v0.1` and `nbe_params_v0.2`; hashes of DDI, v0.1 and v0.2 | B1 |
| `test_params_loader.py` | active NBE is v0.2 and v0.1 still loads; the DDI-reference test runs for both versions; new v0.2 hash and version-mismatch test | v0.2 is the default |
| `tests/unit/test_health.py`, `test_lifecycle_services.py` | expect `nbe_params_v0.2` | v0.2 is the default |
| `tests/unit/test_config_params.py` | one test added (v0.2 equals v0.1 plus the dependency) | document the exact change |
| `test_day4_evidence.py` (T-EVD-1) | the trend item's `metric_id` is None | B2 |
| `test_day4_pipeline.py` (T-PIPE-1, open-DQ test) | Onboarding open-DQ recommendations are exactly `[fix_dq_or_instrumentation]` at rank 1 (Day 4.1b) |
| `test_day4_pipeline.py` (T-PIPE-1) | accepted-DQ Onboarding: items have `metric_id` None and the reasons gain `success_metric_evidence` | B2 known consequence |
