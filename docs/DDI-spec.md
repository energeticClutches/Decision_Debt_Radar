# Decision Debt Index (DDI) Specification

**Status:** v0.1, reconciled on Day 3 with the Product Owner decisions R1-R14 and the Day-3 clarifications (see [day-3-implementation-brief.md](day-3-implementation-brief.md) and [day-3-implementation-notes.md](day-3-implementation-notes.md)). Parent: [PRD-v0.1.md](PRD-v0.1.md) §13, §25, §27. **The aggregation model is unchanged.** Day 3 fixes the band edge, the rounding, the cap reconciliation, the P1 definition (quality-adjusted), the P2 normalization, the missing constants and the evidence-direction summary (§14).

> **Positioning.** DDI is **a transparent evidence-risk heuristic for business decisions.** It is a proposed framework for this portfolio project. It is not an objective measure of decision quality, not a scientifically validated universal score, not an industry standard and not a predictor of business outcomes.
>
> *The value of DDI is primarily in decomposing evidence quality, coverage, freshness, experimental strength, customer/behavioral/financial evidence, contradiction and uncertainty into an auditable framework. The numeric score is a configurable heuristic and should be interpreted within an organization's configuration.*
>
> All FitConnect data is synthetic.

## 1. Principles
1. Deterministic: same inputs and parameters give the same output. No LLM in the calculation (BR-5).
2. Decomposable: every point of DDI is attributable to a dimension or a penalty.
3. Honest: INSUFFICIENT EVIDENCE is a valid outcome and no score is forced.
4. Configurable and versioned: parameters live in a versioned config (`ddi_params_v0.1`). Every assessment stores the version.
5. Defended by sensitivity: every scored assessment reports how fragile the band is.

Direction: DDI ∈ [0, 100]. **Higher = more decision debt (weaker evidence support).**

**What DDI means (R1).** DDI measures *evidence debt*: the weakness of the evidence base behind a decision. It does **not** measure the probability that the decision is correct. Strong, reliable evidence that contradicts the hypothesis can produce a LOW DDI. Every DDI is therefore accompanied by a separate, deterministic **evidence-direction summary** (§14). There is no contradiction floor.

## 2. Inputs
Structured attributes of evidence items and analyses: `evidence_type`, `stance`, `strength_grade`, source `reliability_tier`, `observed_start/end`, `n_sample`, `effect_size`, CI, DQ status, experiment design and results, decision type. The LLM may *propose* classification fields (stance, type, theme, relevance) and a grade suggestion. All are validated against enums and the rubric (§4), visible and human-editable. Numeric facts (n, CI, design, SRM) come from code, never from LLM prose.

## 3. Dimensions

Scores are in [0, 1], where 1 = strong support. Penalties are in [0, 1], where 1 = worst.

### 3.1 Item-level factors (v0.1 defaults, assumptions)

| Factor | Values |
|---|---|
| `tier_factor` (source reliability tier 1–4) | 1.00 / 0.75 / 0.50 / 0.25 |
| `grade_factor` (strength grade A–D) | 1.00 / 0.75 / 0.50 / 0.25 |
| `dq_factor` (pass / warn / critical) | 1.0 / 0.7 / 0.0 |
| `freshness_factor` = 0.5^(age_days / half_life) | Half-lives (days): behavioral 90, experiment 180, customer 180, financial 120, market 365, anecdotal 90 |
| `item_weight` w_i = tier_factor × grade_factor × freshness_factor | Used by P1 |

Age is measured from `observed_end` to the assessment date.

### 3.2 Positive dimensions

| ID | Dimension | Calculation | Data required | Limitations / bias |
|---|---|---|---|---|
| D1 | Evidence Quality | Mean over active items of `tier_factor × grade_factor × dq_factor` | Evidence, sources, DQ | Tier/grade assignment subjective. Rubric (§4) reduces but does not remove this |
| D2 | Evidence Coverage | `types_present ÷ types_required` using the checklist for the decision type (§5) | Decision type, evidence types | Counts presence, not depth. Checklist is a judgment |
| D3 | Evidence Freshness | Mean of `freshness_factor` over active items | `observed_end`, half-lives | Half-lives are assumptions. Recent ≠ relevant |
| D4 | Experimental Strength | Best experiment: `design_rank × power_factor × integrity_factor × informativeness_factor`. 0 if no experiment | Experiments, results | Most decisions lack experiments (correctly penalized). Significance ≠ business significance |
| D5 | Customer Evidence | `0.5 × sample_adequacy + 0.3 × segment_coverage + 0.2 × relevance` | Customer insights | Self-selection, vocal minority. Sentiment ≠ behavior |
| D6 | Behavioral Evidence **Strength** | Over behavioral items on the success metric, **whatever their stance**: `adequacy × materiality` (materiality uses \|effect\|), capped at 0.6 if only observational. Cap lifted to 1.0 when D4 ≥ 0.6 | Observations, analyses | Correlation ≠ causation. Selection, survivorship |
| D7 | Financial / Business Evidence | 0 if none. Otherwise 0.5 (quantified estimate) + 0.3 (source tier ≤ 2) + 0.2 (sensitivity range present) | Financial evidence | Often modelled not observed. Assumptions dominate |

Sub-factor definitions (v0.1 assumptions):
- `design_rank`: RCT 1.0, holdout 0.8, pre/post 0.4, other 0.2, none 0.
- `power_factor` = min(1, achieved_power ÷ 0.8).
- `integrity_factor` = 1.0 if SRM check passes, else 0.3.
- `informativeness_factor` = 1.0 if CI width ≤ 2×MDE, 0.6 if ≤ 4×MDE, else 0.3.
- `sample_adequacy` = min(1, quote_count ÷ 100). `segment_coverage` = relevant segments covered ÷ relevant segments. `relevance` ∈ {1.0 direct, 0.5 adjacent} (classified, validated enum).
- `adequacy` = min(1, n ÷ n_required for the metric's MDE). `materiality` = min(1, |effect| ÷ materiality_threshold), counted only if direction supports the hypothesis.

**Day-3 constants and conservative defaults (all in `ddi_params_v0.1.yaml`, hash-verified).**

| Constant | Value | Use |
|---|---|---|
| `bands.critical` | `{min 75, max 100, max_inclusive true}` | a DDI of exactly 100 is Critical |
| `small_n_threshold` | 100 | P2 small-n flag: `n_sample < 100` |
| `behavioral.materiality_threshold` | 0.02 (absolute effect) | D6 materiality = min(1, \|effect\| ÷ 0.02) |
| `behavioral.n_required` | 1000 | D6 adequacy = min(1, n ÷ 1000). The metrics table has no MDE |
| `customer.default_relevance` | 0.5 (adjacent) | D5 relevance when no explicit relevance exists (always on Day 3) |
| `customer.default_segment_coverage` | 0.5 | D5 when no relevant-segment list exists (always on Day 3) |
| `experiment.default_power_factor` | 0.5 | D4 when achieved power is not stored (always on Day 3) |
| `experiment.default_informativeness` | 0.3 | D4 when the CI or MDE is missing |
| `financial.sensitivity_range_rule` | `ci_low and ci_high present` | D7 "sensitivity range present" |
| `uncertainty.ci_component_when_effect_zero` | 1.0 | P2 CI component when the effect is 0 |
| `uncertainty.hhi_normalization` | `(HHI − 1/n) ÷ (1 − 1/n)`, 1.0 when n = 1 | normalized concentration, n = distinct evidence sources |
| `direction.majority_share` | 0.6 | evidence-direction label (§14) |
| `direction.min_direction_bearing_items` | 2 | evidence-direction label (§14) |

**Defaulted inputs are never silent.** Every input that falls back to a default is reported in the breakdown as `{name, value, source: "observed" | "default", default_reason}`. Each dimension lists `inputs[]` and `defaulted_inputs[]`. A defaulted value is never shown as observed.

**Day-3 reading of the dimensions** (details in [day-3-implementation-notes.md](day-3-implementation-notes.md)):
- Evidence set: all `evidence` rows of the decision. Items with a critical DQ issue still count toward the gate's item and type counts, and score `dq_factor = 0` in D1.
- D4: the best linked experiment (max over experiments reached through `evidence.experiment_id`), using the non-control `experiment_results` row with the largest n. An unknown SRM result is treated conservatively as failed (0.3) and flagged as defaulted.
- D5: only insights reached through `evidence.insight_id`; `sample_adequacy` from the summed quote counts.
- D6 (Behavioral Evidence Strength): mean of adequacy × materiality over behavioral items whose `metric_id` is the success metric, **stance-agnostic** (PO correction at Day-3 acceptance, consistent with R1: D6 measures how strong the behavioral evidence is, not whether it supports the hypothesis; materiality uses the absolute effect). Capped at 0.6 unless D4 ≥ 0.6. Flipping an item's stance leaves D6 unchanged; stance reaches the DDI only through P1.
- D7: the best financial item: quantified estimate (effect size present) 0.5, source tier ≤ 2 0.3, sensitivity range (CI present) 0.2.
- DQ factor of an item: the worst severity among OPEN and ACCEPTED checks on the item's data source (resolved checks are ignored).

### 3.3 Penalty dimensions

| ID | Penalty | Calculation | Limitations |
|---|---|---|---|
| P1 | Contradiction | **Strength-weighted contradiction among direction-bearing evidence, adjusted for evidence quality.** `Σ w_i (contradicting) ÷ Σ w_i (supporting or contradicting)` with `w_i = tier × grade × freshness × dq_factor`. Neutral items are excluded (they do not dilute contradiction). With zero direction-bearing weight, P1 = 0. **Segment-divergence floor:** only when the heterogeneity flag is True (BR-15), P1 ≥ 0.3. The flag is produced by Day-4 analytics, so on Day 3 it is unknown (default: not flagged, reported as defaulted) | Depends on stance labels (the Reviewer audits them). A contradicting item with a critical DQ issue adds no contradiction weight (recorded methodology change, Day 3) |
| P2 | Uncertainty | Mean of the **available** components among: CI component (`min(1, CI_width ÷ (2×|effect|))` over items with effect and CI; 1.0 when the effect is 0), small-n share (share of items with a known `n_sample` below 100) and **normalized** source concentration `(HHI − 1/n) ÷ (1 − 1/n)` (HHI = Σ share² of items per evidence source, n = distinct sources, 1.0 when n = 1). The breakdown lists which components were available | Needs numeric evidence for CI/n. The normalization makes an even spread of sources 0 and a single source 1 |

## 4. Strength grading rubric (A–D)

| Grade | Criteria |
|---|---|
| A | Large adequate sample or intact-design experiment, reliable source (tier 1–2), no open DQ warnings |
| B | Adequate sample, observational or minor design limits, reliable source |
| C | Small sample, or unverified source, or DQ warnings, or analysis with material limitations |
| D | Anecdotal, single quote, unknown provenance, or data with a critical DQ issue |

Where numeric facts exist (n, CI, design, DQ), the grade is **computed by rule** from them. The LLM may only suggest a grade for text-only items, and humans may override with a logged reason.

## 5. Coverage checklists (industry-agnostic, configurable)

| `decision_type` | Required evidence types |
|---|---|
| `product_feature_investment` | behavioral, customer, experiment, financial |
| `pricing_change` | behavioral, customer, experiment, financial |
| `process_or_ux_change` | behavioral, customer, experiment |
| `strategy_or_market_entry` | market, customer, financial |
| `policy_or_operations` | behavioral, anecdotal-or-customer, financial |

Dimensions marked non-applicable for a type (for example D7 on a pure UX change) are excluded and the remaining equal weights renormalized. Applicability is part of the config and shown in the panel.

## 6. Aggregation

```
K        = number of applicable positive dimensions
Support  = (1/K) × Σ D_k                        (equal prior weights)
Penalty  = 1 + 0.5 × P1 + 0.25 × P2
DDI      = min(100, 100 × (1 − Support) × Penalty)
```

Bands (assumed thresholds, configurable): **Low** < 25 · **Moderate** ≥ 25 and < 50 · **High** ≥ 50 and < 75 · **Critical** ≥ 75 and ≤ 100. **A DDI of exactly 100 is Critical** (R3).

**Rounding and bands (R3).** The DDI is rounded to one decimal (half up) **first**, and the band is derived from the rounded value. So 49.95 displays as 50.0 and is High, and 99.99 displays as 100.0 and is Critical.

**Cap reconciliation (R2).** All raw contributions and the uncapped DDI = 100 × (1 − Support) × Penalty are computed first. The displayed DDI is min(100, uncapped). If uncapped > 100, every contribution (dimensions and penalties) is scaled by 100 ÷ uncapped, and the result exposes `cap_applied = true` and `uncapped_ddi`.

**Displayed contributions (R3).** Dimension and penalty contributions are displayed at one decimal using **largest-remainder allocation**, so they sum **exactly** to the displayed DDI. (In the §9 example this gives D6 7.8 rather than 7.9: the individually rounded values 6.4 + 4.1 + 5.7 + 12.9 + 5.0 + 7.9 + 10.0 would sum to 52.0, not 51.9. Remainder ties go to the earlier dimension.)

**Why equal prior weights:** there is no ground truth against which to calibrate. Equal weights make no claim that one dimension matters more. The sensitivity analysis (§8) reports how much that choice matters. The penalty coefficients (0.5 and 0.25) are assumptions that make contradiction a more severe penalty than uncertainty. They are shown in the UI.

**Contribution decomposition (for the transparency panel):**
- Dimension contribution (before penalty) = `100 × (1 − D_k) ÷ K`.
- Penalty contribution = `(Σ dimension contributions) × coefficient × P`, shown separately for P1 and P2.
- The dimension contributions plus the two penalty contributions sum to the DDI (before the 100 cap). Verified by test (AC-31).

## 7. Gating: INSUFFICIENT EVIDENCE
The engine returns `state = insufficient_evidence`, `score = null` and `blocking_reasons[]` if any of the following hold (BR-1 to BR-4):
1. `min_items`: fewer than 3 evidence items.
2. `min_types`: fewer than 2 distinct evidence types.
3. `success_metric_evidence`: no evidence relates directly to the decision's success metric (`evidence.metric_id` is the success metric, or the linked experiment's primary metric is).
4. `open_critical_dq`: an **open critical** DQ check affects the success metric's data source (or names the success metric). DQ checks of every assessment version of the decision remain relevant.

Reasons are always reported in this fixed order. `accepted` DQ issues do not block (they appear as a warning), and `resolved` issues do not block.

No score, band, sensitivity range or estimate is shown in this state, and no dimension breakdown is stored.

## 8. Sensitivity analysis (core safeguard)
Run on every scored assessment:
1. **Weight perturbation.** For each applicable dimension, multiply its weight by 0.5 and by 1.5, renormalize, and recompute DDI (2K runs).
2. **Penalty perturbation.** Scale both penalty coefficients by 0.5 and by 1.5 together, and each coefficient separately (6 runs). Item-level factors are not perturbed.
3. **Range.** Report min–max DDI across the perturbations and the base case. The number of perturbations is **2K + 6**; the base case is not one of them. Each perturbed DDI is capped at 100, rounded to one decimal and then banded (the same round-then-band rule).
4. **Band stability.** `robust` if the band is unchanged in ≥ 90% of perturbations (inclusive), otherwise `sensitive`. The stored `band_stable` boolean is the "Band stable: YES/NO" indicator. The panel text for robust results is "Robust to aggregation weights and penalty coefficients." The result also names the perturbation that moved the score most.
5. **Portfolio rank stability** (Debt Radar): whether the ordering of two decisions flips under any perturbation.

## 9. Worked example (illustrative numbers, not FitConnect output)
Dimension scores: D1 0.55 · D2 0.714 (for example 5 of 7 required types present) · D3 0.60 · D4 0.10 · D5 0.65 · D6 0.45 · D7 0.30. P1 = 0.20, P2 = 0.30. K = 7.

- Support = (0.55 + 0.714 + 0.60 + 0.10 + 0.65 + 0.45 + 0.30) ÷ 7 = 0.481
- Penalty = 1 + 0.5×0.20 + 0.25×0.30 = 1.175
- DDI = 100 × (1 − 0.481) × 1.175 = **61.0 → High**

Contributions (before penalty, largest-remainder at one decimal): D1 6.4 · D2 4.1 · D3 5.7 · D4 12.9 · D5 5.0 · D6 7.8 · D7 10.0 = 51.9. Penalties: contradiction +5.2, uncertainty +3.9. 51.9 + 5.2 + 3.9 = 61.0 ✓. (The unrounded D6 contribution is 7.857. Plain rounding would give 7.9 and a dimension sum of 52.0, which would not reconcile with 61.0.)

Sensitivity samples: D4 weight ×0.5 gives about 57.6. D4 weight ×1.5 gives about 64.0. Penalty coefficients ×0.5 gives about 56.5. ×1.5 gives about 65.6. All stay in **High**. The engine reports the min–max over all perturbations. Here the single-perturbation samples are within High, so the band is stable (subject to the full run).

Reading: the biggest debt contributors are weak experimental evidence (D4), thin financial evidence (D7) and observational-only behavioral evidence (D6). That decomposition, not the 61, is the product value.

## 10. LLM boundary
Allowed: classify stance/type/theme/relevance, suggest grades for text-only evidence, explain the computed result. Not allowed: choose or alter any score, parameter or numeric input. The engine ignores numerics in LLM prose. Explanatory text inserts numbers by code.

## 11. Parameter configuration
A versioned configuration (`ddi_params_v0.1`) holds: tier/grade/DQ factors, half-lives, design ranks, sub-factor constants, penalty coefficients, band cutoffs, checklists, applicability and the perturbation set. Changing any value requires a new version. Assessments store the version, the **content hash** (SHA-256 of the file bytes, verified at load time against `backend/config/params_hashes.json`) and the as-of date, and are never silently recomputed. `ddi_params_v0.1` was amended in place on Day 3 *before* any assessment used it (R3 band edge, §3.3 constants, direction block); its hash was recorded once afterwards.

## 12. Known limitations (shown in the product)
- No ground-truth calibration. Parameters are documented assumptions.
- Scores are comparable only within one organization's configuration and version.
- Does not measure whether the decision is *right*, only how well-evidenced it is.
- Sensitive to evidence classification (stance, grade). The Reviewer and human edits mitigate this.
- Rewards presence of evidence types. It cannot detect evidence that is present but irrelevant beyond the relevance field.

## 13. Test requirements
Determinism · monotonicity · gating cases · contribution sum equals DDI · applicability renormalization · sensitivity extrema · INSUFFICIENT state never returns a number · cap behavior · band boundaries · evidence direction independent of DDI · defaulted inputs reported.

**Monotonicity invariant (Day 3, PO correction).** The tested property is: *improving an attribute of an existing evidence item never increases the DDI, all else equal.* It is **not** "adding evidence reduces the DDI". Day-3 scope of the property: it holds for supporting and neutral items for every attribute (tier, grade, DQ status, recency, n_sample) and for any item's `n_sample`. For a **contradicting** item, a higher tier, grade, recency or DQ status raises its weight and therefore P1 (stronger contradiction is more contradiction), so those attributes can raise the DDI by design. The test suite asserts both facts. This follows directly from the specified P1 definition and R1 (DDI is evidence debt, not correctness).

## 14. Evidence-direction summary (Day 3, PO-approved)
A deterministic interpretation of the evidence that runs **beside** the DDI and never modifies it (no DDI input or output reads it). With `w = tier × grade × freshness × dq_factor` as in P1, direction-bearing items are those with stance supports or contradicts and `w > 0`:

| Field | Definition |
|---|---|
| `supporting_share` / `contradicting_share` | supporting (contradicting) weight ÷ direction-bearing weight. They sum to 1, or are both 0 when there is no direction-bearing weight |
| `neutral_share` | neutral weight ÷ total weight |
| `direction_basis_weight` | direction-bearing weight ÷ total weight |
| `threshold` | 0.60 (`direction.majority_share`) |
| `direction_bearing_items` | count of direction-bearing items |

Label: `uncertain` if the assessment is gated, or fewer than 2 direction-bearing items exist (`direction.min_direction_bearing_items`), or the direction-bearing weight is 0. Otherwise `supporting` if supporting_share ≥ 0.6, `contradicting` if contradicting_share ≥ 0.6, else `mixed` (a 55/45 split is mixed). The earlier rule "uncertain when total weight < 1.0" was withdrawn. The summary is stored in `decision_assessments.dimension_scores.evidence_direction` and returned next to, never inside, the DDI. D6 is stance-agnostic, so evidence stance affects the DDI only through P1; the direction summary never feeds the DDI.
