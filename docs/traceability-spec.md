# Evidence Traceability Matrix Specification

**Status:** DRAFT v0.1 (Day-1 BA artifact, pending Product Owner approval). Parent: [PRD-v0.1.md](PRD-v0.1.md) §10.

> All FitConnect data and the examples below are synthetic and illustrative.

## 1. Purpose
Show, for every conclusion, the chain:

**Decision → Claim → Evidence → Source → Analysis → Conclusion**

so that a reviewer can audit the reasoning end to end. Traceability is a Must-have (M10). It also enforces BR-6 (no claim without evidence).

## 2. Chain definition

| Link | Entity | Meaning |
|---|---|---|
| Decision | `decisions` | The decision under assessment |
| Claim | `claims` | An atomic assertion made in the synthesis |
| Evidence | `evidence` via `claim_evidence` (M:N) | The evidence item(s) behind the claim |
| Source | `evidence_sources` (→ `data_sources`) | Where the evidence came from and its reliability tier |
| Analysis | `analysis_results` (nullable) | The reproducible analysis (query, params, n, limitations) that produced or validated the evidence |
| Conclusion | `decision_assessments` (dimension findings, narrative, DDI breakdown) | The assessment-level finding the claim feeds |

## 3. Matrix columns

| Column | Description |
|---|---|
| `decision_id`, `decision_title` | |
| `assessment_id`, `assessment_version` | The matrix is versioned per assessment |
| `claim_id`, `claim_text` | |
| `claim_type` | descriptive / associative / causal / financial / customer / risk |
| `stance` | supports / contradicts / neutral (relative to the hypothesis) |
| `claim_confidence` | low / medium / high (classified, not scored) |
| `evidence_id`, `evidence_summary` | |
| `evidence_type`, `strength_grade` | |
| `source_id`, `source_name`, `reliability_tier` | |
| `analysis_id`, `analysis_type`, `query_ref` | Null for qualitative sources |
| `dq_status` | DQ result of the underlying data |
| `conclusion_ref` | The dimension or finding that the claim feeds (for example D4 Experimental Strength). Stored as `claims.conclusion_ref` |
| `reviewer_challenge_ids` | Reviewer flags attached to the claim |
| `row_type` | `claim_link` or `gap` |
| `is_synthetic` | Always shown for demo data |

## 4. Rules

| ID | Rule |
|---|---|
| TM-1 | A claim with no valid evidence ID is invalid. It is discarded at validation, logged in `agent_runs`, and never appears in the matrix or brief. |
| TM-2 | Many-to-many: a claim may cite several evidence items, and an evidence item may support several claims. |
| TM-3 | The matrix is the database view `v_traceability_matrix` over `claims`, `claim_evidence`, `evidence`, `evidence_sources`, `analysis_results` and `decision_assessments`. It is not hand-maintained. |
| TM-4 | **Gap rows:** each required evidence type missing against the checklist, and each unmet change-my-mind criterion, appears as a `gap` row with `evidence_id = NULL`. |
| TM-5 | Quantitative claims (descriptive, associative, causal, financial) must resolve to an `analysis_id` or experiment. Otherwise the claim is downgraded to `neutral` with a flag, and the Reviewer is told. |
| TM-6 | Causal claims require an experiment of design rank ≥ holdout with a passing SRM check (BR-7). Otherwise the claim type is forced to `associative`. |
| TM-7 | Re-running an assessment creates new claim rows under the new assessment version. Earlier versions are retained and are superseded (any version lower than the latest; derived from `version`, not stored). Day 3: an assessment row is immutable once written (only `narrative` and `brief_md` may change) and stores the parameter version and hash, the NBE parameter version and hash, the as-of date and an evidence fingerprint, so every conclusion can be traced to the exact inputs it used. |
| TM-8 | The matrix exports to CSV and Markdown, and appears in the brief appendix. |

## 4a. Evidence status and generated evidence (Day 4, D4-16 to D4-21)

- Evidence has a `status`: `active` or `superseded` (`superseded_by`, `superseded_at`). A **superseded item is never deleted**: when the analysis parameters change, the new evidence is inserted, the old item is superseded, and claims of historical assessments still resolve through it. The matrix therefore **keeps every evidence row** and has an `evidence_status` column; the DDI, the freshness and the health views count active evidence only. Gap rows (TM-4) count active evidence only.
- Generated evidence (`created_by = agent`) always has an `analysis_id`. The chain resolves **evidence → analysis (`analysis_results`: query text, parameters, n, result, limitations, DQ status) → the allow-listed view(s) it read (`params.source_views`) → the data-quality checks of the decision on that data source**. `analysis_results.params.config` stores the analytics-parameter and tenant-configuration versions and hashes, so the exact parameters are recoverable. `evidence.analysis_identity` and `evidence.source_fingerprint` repeat the analysis identity and the data fingerprint.
- Identity (D4-16): `sha256(decision | analysis_type | metric_id | experiment-or-segment-or-cohort key | analysis_params_hash)`. The data is NOT part of it: with new data the same identity keeps one active item and its values are updated in place (which marks an assessed decision stale); with new parameters the identity changes and the old item is superseded. Analysis rows are insert-only history. Day 4.1: descriptive evidence (trend, funnel) has `evidence.metric_id` NULL (so it does not count toward D6 or satisfy the success-metric gate); the metric it describes is traced through `analysis_id` (the analysis row records it) and the identity above keeps using that analysed metric.

## 5. Enforcement flow
1. Synthesis agent returns structured claims with `evidence_ids`.
2. Validator (code): every ID exists and belongs to this decision. Claim type rules (TM-5, TM-6) applied. Invalid claims dropped and logged.
3. Valid claims stored in `claims` and `claim_evidence`.
4. Reviewer receives claims plus the matrix and may attach challenges to claim or evidence IDs.
5. Brief generation uses only stored claims.

## 6. Illustrative extract (AI Coach, synthetic)

| claim | type | stance | evidence | source (tier) | analysis | feeds |
|---|---|---|---|---|---|---|
| "AI Coach users show higher D90 retention than non-users" | associative | supports | E-014 behavioral, grade B | `fc_events` (2) | A-003 retention cohort | D6 Behavioral |
| "The difference largely disappears after controlling for prior engagement" | associative | contradicts | E-015 behavioral, grade B | `fc_events` (2) | A-004 segmentation | P1 Contradiction |
| "The holdout experiment is underpowered and inconclusive" | descriptive | neutral | E-016 experiment, grade C | `fc_experiments` (2) | A-005 experiment | D4 Experimental |
| (gap) | – | – | none | – | – | Financial evidence missing for cost per retained user |

## 7. Presentation
Matrix table in the app, filterable by stance, evidence type and dimension. Clicking a row opens the evidence, source and analysis (query, params, limitations). Also a compact "Claim → Evidence" popover in the brief.

## 8. Acceptance criteria
Canonical: AC-3, AC-10 (PRD §18). Additional:

| ID | Criterion |
|---|---|
| TR-AC-1 | 100% of claims in any generated brief resolve to ≥1 evidence ID and one source. Quantitative claims also resolve to an analysis ID. Measured as the *traceability rate* KPI. |
| TR-AC-2 | A fabricated evidence ID injected into agent output is rejected, logged and absent from the matrix. |
| TR-AC-3 | A claim typed `causal` without a qualifying experiment is reclassified `associative`. |
| TR-AC-4 | Missing required evidence types and unmet change-my-mind criteria appear as gap rows. |
| TR-AC-5 | Export reproduces the view exactly and carries the "Synthetic data" label for demo data. |
