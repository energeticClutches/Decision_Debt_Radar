# Evaluation report (Day 7)

> **Synthetic data.** FitConnect is a fictional company. Anything derived from an LLM stage is **stub, not model output**. DDI is an evidence-risk heuristic, not a measure of decision quality.

## 1. Scope and honesty statement

This report evaluates the **deterministic** parts of Decision Debt Radar and the **plumbing** around the LLM boundary: the frozen DDI and NBE engines, the validators, the deterministic critic checks, the lifecycle and permission rules, the data-quality checks, the analytics against the seed manifest, and the human gate on customer evidence.

**No live model was called, ever.** No API key exists. The classification, synthesis and review in every run are *replayed*: a keyword-rule stub and hand-authored fixtures, each marked `stub_not_model_output`. Therefore this report **does not measure any model behaviour**. The following are **NOT EVIDENCED** (not measured: no live model (replay fixtures are hand-authored)):

- Reviewer recall of seeded flaws and the Reviewer's false-flag rate (PRD target: recall >= 80%, <= 20% false flags);
- real classification accuracy (the stub's score below says nothing about a model);
- live schema validity and repair-retry rate of a real model;
- prompt-injection resistance and refusal correctness of a real model (here a *scripted* compromised output is shown to be rejected by code).

A criterion that is not evidenced is reported as NOT EVIDENCED, never made to pass. Nothing in `backend/demo_fixtures/` or `tests/fixtures/llm/` was edited to make a result pass.

## 2. Method

- **Specs.** 21 declarative scenarios in `tests/evals/scenarios/*.yaml` (4 core, 6 PRD section 19 variants, 11 extra), each marked `synthetic: true`. A spec names a base scenario, a list of **mutations** applied through the real API (services), and what it expects: state, blocking reasons (an exact set), a band **or** no DDI, NBE actions, code findings, lifecycle stage and named properties.
- **No band is chosen in advance (D7-01).** A spec states `band: golden`. The engine's observed output is recorded in `tests/evals/golden/observed.json` by `scripts/eval_snapshot.py --write` (never by hand). Every run checks that the stored result equals `assess(facts)` recomputed on the stored facts **and** equals the snapshot (drift detection).
- **Isolation.** Every spec runs inside a pytest transaction on the seeded database and is rolled back; the demo database is never written (a test compares row counts before and after). Mutations never use raw SQL on product tables, with two documented test-only exceptions: the Day-5 E3 injected insight row, and the approval-bypass *attempt* (a statement the database must refuse, run in a rolled-back savepoint).
- **Code-layer mutation suite.** 22 flaw families (`tests/evals/mutations.yaml`) are seeded into valid syntheses built from the real input payloads of the four scenarios; each records the validator rule or critic category that must catch it. Valid syntheses of the four scenarios are the clean controls.
- **Clock.** The as-of date is fixed (2026-10-01) except in the stale-evidence variant, which moves it forward on purpose.

## 3. Results

### 3.1 Metrics against the PRD section 17/19 targets

| Metric | Result | Target | Status |
|---|---|---|---|
| DDI reproducibility | 21/21 | 100% | MET |
| Stored result equals recomputed engine | 20/20 | 100% | MET |
| Expected-state match, core | 4/4 | 100% | MET |
| Expected-state match, variants | 6/6 | report | reported |
| Citation validity before filtering (specs) | 98.8% (84/85) | report | reported |
| Citation validity after filtering (specs) | 100.0% (78/78) | 100% | MET |
| Citation validity before / after filtering (mutation suite) | 97.5% (354/363) / 100.0% (323/323) | after 100% | MET |
| SQL-guard pass rate (existing guard corpus; no LLM SQL by design) | 100.0% (74/74) | 100% | MET |
| Data-quality seeded-defect recall | 2/2 | >= 90% | MET |
| Golden-answer accuracy (analyses vs manifest, tolerance 0.005) | 11/11 | report | reported |
| Code-check recall (validators and deterministic critic) | 61/61 (100.0%) | report; no target set | reported |
| Code-check false-flag rate (clean controls) | 0/4 | report; no target set | reported |
| Reviewer recall and false flags | NOT EVIDENCED | >= 80% / <= 20% | not measured: no live model (replay fixtures are hand-authored) |
| Classification accuracy (stub, not model output) | see 3.5 | report | stub only; real model not measured: no live model (replay fixtures are hand-authored) |

### 3.2 Specs

Full spec pass (every expectation met): core 3/4, variants 6/6, extra 11/11. Expected-state match is the `state` expectation only (a spec with a documented known gap still matches its state).

| Spec | Group | Expected | Observed | Pass |
|---|---|---|---|---|
| core_ai_coach | core | state=scored; lifecycle=challenged; blocking=none; band=golden; nbe+=powered_holdout_test; findings+=V-SEM-TYPE; props=stance_from_map,review_not_ready | state=scored; band=high; lifecycle=challenged; nbe_rank1=financial_model_with_sensitivity | yes |
| core_community | core | state=scored; lifecycle=challenged; blocking=none; band=golden; nbe+=powered_holdout_test,segment_level_analysis; props=stance_from_map | state=scored; band=high; lifecycle=challenged; nbe_rank1=financial_model_with_sensitivity | NO |
| core_onboarding | core | state=insufficient_evidence; lifecycle=challenged; blocking=min_items,min_types,open_critical_dq,success_metric_evidence; no_ddi; nbe_rank1=fix_dq_or_instrumentation; props=no_ddi_number,stance_from_map | state=insufficient_evidence; blocking=min_items,min_types,open_critical_dq,success_metric_evidence; lifecycle=challenged; nbe_rank1=fix_dq_or_instrumentation | yes |
| core_pricing | core | state=scored; lifecycle=challenged; blocking=none; band=golden; nbe+=financial_model_with_sensitivity,powered_holdout_test; props=d4_unchanged,review_not_ready,stance_from_map | state=scored; band=high; lifecycle=challenged; nbe_rank1=financial_model_with_sensitivity | yes |
| var_onboarding_dq_resolved | variant | state=insufficient_evidence; lifecycle=assessed; blocking=min_items,min_types,success_metric_evidence; no_ddi; nbe+=extend_observation_or_refresh_data; props=no_ddi_number | state=insufficient_evidence; blocking=min_items,min_types,success_metric_evidence; lifecycle=assessed; nbe_rank1=extend_observation_or_refresh_data | yes |
| var_clean_strong_evidence | variant | state=scored; lifecycle=assessed; blocking=none; band=golden | state=scored; band=moderate; lifecycle=assessed; nbe_rank1=targeted_survey | yes |
| var_empty_evidence | variant | state=insufficient_evidence; lifecycle=assessed; blocking=min_items,min_types,success_metric_evidence; no_ddi; props=no_ddi_number | state=insufficient_evidence; blocking=min_items,min_types,success_metric_evidence; lifecycle=assessed; nbe_rank1=extend_observation_or_refresh_data | yes |
| var_contradictory_evidence | variant | state=scored; lifecycle=assessed; blocking=none; band=golden | state=scored; band=critical; lifecycle=assessed; nbe_rank1=targeted_survey | yes |
| var_stale_evidence | variant | state=scored; lifecycle=assessed; band=golden; props=ddi_not_lower_when_older | state=scored; band=high; lifecycle=assessed; nbe_rank1=extend_observation_or_refresh_data | yes |
| var_injection_in_customer_text | variant | state=scored; lifecycle=challenged; band=golden; findings+=V-REC,V-ID,synthesis_rejected_by_validators | state=scored; band=high; lifecycle=challenged; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_customer_rejected | extra | state=scored; band=golden; props=proposed_excluded_from_facts | state=scored; band=high; lifecycle=assessed; nbe_rank1=targeted_survey | yes |
| extra_customer_left_proposed | extra | state=scored; lifecycle=assessed; band=golden; props=proposed_excluded_from_facts | state=scored; band=high; lifecycle=assessed; nbe_rank1=targeted_survey | yes |
| extra_reviewer_failing | extra | state=scored; lifecycle=assessed; band=golden; props=review_not_ready | state=scored; band=high; lifecycle=assessed; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_malformed_synthesis | extra | state=scored; lifecycle=assessed; band=golden; findings+=synthesis_failed; props=review_not_ready | state=scored; band=high; lifecycle=assessed; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_canvas_edit_stale | extra | state=scored; lifecycle=evidence_gathered (stale); band=golden | state=scored; band=high; lifecycle=evidence_gathered; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_needs_rework_override | extra | state=scored; lifecycle=validated; band=golden | state=scored; band=high; lifecycle=validated; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_decided_freezes_writes | extra | state=scored; lifecycle=decided; band=golden; props=writes_frozen | state=scored; band=high; lifecycle=decided; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_gated_summary_path | extra | state=insufficient_evidence; lifecycle=validated; no_ddi; props=no_ddi_number | state=insufficient_evidence; blocking=min_items,min_types,open_critical_dq,success_metric_evidence; lifecycle=validated; nbe_rank1=fix_dq_or_instrumentation | yes |
| extra_defer_stale | extra | state=scored; lifecycle=evidence_gathered (stale); band=golden | state=scored; band=high; lifecycle=evidence_gathered; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_approval_bypass_refused | extra | state=scored; lifecycle=challenged; band=golden; refused=approval_bypass | state=scored; band=high; lifecycle=challenged; nbe_rank1=financial_model_with_sensitivity | yes |
| extra_dq_resolved_pipeline_reopens | extra | state=insufficient_evidence; blocking=min_items,min_types,open_critical_dq,success_metric_evidence; no_ddi; nbe_rank1=fix_dq_or_instrumentation; props=no_ddi_number | state=insufficient_evidence; blocking=min_items,min_types,open_critical_dq,success_metric_evidence; lifecycle=challenged; nbe_rank1=fix_dq_or_instrumentation | yes |

The full per-check detail is in `analytics/eval/results.json`; the flat table is `analytics/eval/results.csv`.

### 3.3 Golden bands (observed frozen-engine output, D7-01)

These bands are the engine's output recorded in the snapshot. They were not chosen in advance and are not judged right or wrong here.

| Spec | State | DDI | Band | NBE rank 1 |
|---|---|---|---|---|
| core_ai_coach | scored | 60.5 | high | financial_model_with_sensitivity |
| core_community | scored | 66.5 | high | financial_model_with_sensitivity |
| core_onboarding | insufficient_evidence | no DDI | none | fix_dq_or_instrumentation |
| core_pricing | scored | 73.7 | high | financial_model_with_sensitivity |
| var_onboarding_dq_resolved | insufficient_evidence | no DDI | none | extend_observation_or_refresh_data |
| var_clean_strong_evidence | scored | 47.1 | moderate | targeted_survey |
| var_empty_evidence | insufficient_evidence | no DDI | none | extend_observation_or_refresh_data |
| var_contradictory_evidence | scored | 84.1 | critical | targeted_survey |
| var_stale_evidence | scored | 64.7 | high | extend_observation_or_refresh_data |
| var_injection_in_customer_text | scored | 60.5 | high | financial_model_with_sensitivity |
| extra_customer_rejected | scored | 69.2 | high | targeted_survey |
| extra_customer_left_proposed | scored | 69.2 | high | targeted_survey |
| extra_reviewer_failing | scored | 73.7 | high | financial_model_with_sensitivity |
| extra_malformed_synthesis | scored | 73.7 | high | financial_model_with_sensitivity |
| extra_canvas_edit_stale | scored | 73.7 | high | financial_model_with_sensitivity |
| extra_needs_rework_override | scored | 60.5 | high | financial_model_with_sensitivity |
| extra_decided_freezes_writes | scored | 60.5 | high | financial_model_with_sensitivity |
| extra_gated_summary_path | insufficient_evidence | no DDI | none | fix_dq_or_instrumentation |
| extra_defer_stale | scored | 73.7 | high | financial_model_with_sensitivity |
| extra_approval_bypass_refused | scored | 66.5 | high | financial_model_with_sensitivity |
| extra_dq_resolved_pipeline_reopens | insufficient_evidence | no DDI | none | fix_dq_or_instrumentation |

**The manifest's expected bands, for comparison (informational).** `data/generated/manifest.json` lists an expected DDI band set for each scenario:

| Scenario | Manifest expects state | Observed state | Manifest expects band | Observed band | Verdict |
|---|---|---|---|---|---|
| ai_coach | scored | scored | moderate, high | high | within the expected set |
| community | scored | scored | moderate | high | OUTSIDE the expected set |
| onboarding | insufficient_evidence | insufficient_evidence | none | none (INSUFFICIENT) | match (no band expected) |
| pricing | scored | scored | high | high | within the expected set |

### 3.4 Data quality and golden answers

| Seeded defect | Target | Detected (open check) | Checks |
|---|---|---|---|
| DEF-ONB-001 | onboarding_step_2_completed@android | yes | volume (warn) |
| DEF-ONB-002 | onboarding_completed@android | yes | volume (critical) |

| Quantity | Manifest check | Manifest value | Analysis value | Abs. diff | Within 0.005 |
|---|---|---|---|---|---|
| AI Coach: adopters minus non-adopters, D90 retention (comparison effect) | AI-001 | 0.2304 | 0.2304 | 0.0 | yes |
| AI Coach: experiment treatment share (observed allocation) | AI-006 | 0.3 | 0.3 | 0.0 | yes |
| AI Coach: experiment enrolled share of planned sample | AI-008 | 0.375 | 0.375 | 0.0 | yes |
| Community: joiners minus non-joiners, D90 retention (comparison effect) | COM-001 | 0.1452 | 0.1452 | 0.0 | yes |
| Community: segment social_exerciser effect | COM-002 | 0.1956 | 0.1956 | 0.0 | yes |
| Community: segment solo_athlete effect | COM-003 | 0.0001 | 0.0001 | 0.0 | yes |
| Community: segment time_pressed effect | COM-004 | -0.0795 | -0.0795 | 0.0 | yes |
| Pricing: CA pilot trial-to-paid change (comparison effect) | PRC-003 | -0.112 | -0.112 | 0.0 | yes |
| Pricing: experiment enrolled share of planned sample | PRC-008 | 0.1467 | 0.1467 | 0.0 | yes |
| Community: heterogeneity flag (manifest: True) | COM-002..004 (expected_downstream) | True | True | None | yes |
| AI Coach: heterogeneity flag (Day-4 expected: False) | day-4 expected vs observed | False | False | None | yes |

### 3.5 Classification (the keyword-rule stub, not a model)

**stub, not model output.** The classifier here is a deterministic keyword-rule stub whose cues were written while the generator's template sentences were visible. The synthetic feedback is **templated**: 195 distinct sentences for 6,083 rows. Near-perfect agreement therefore measures the pipeline and the stub, and says nothing about real customer text or a real model. **Real classification accuracy: NOT EVIDENCED** (not measured: no live model (replay fixtures are hand-authored)).

| Theme | Precision | Recall | True positives | Predicted | Actual |
|---|---|---|---|---|---|
| coach_helpful | 1.0 | 1.0 | 706 | 706 | 706 |
| coach_generic_or_wrong | 1.0 | 1.0 | 113 | 113 | 113 |
| coach_indifferent | 1.0 | 1.0 | 128 | 128 | 128 |
| challenges_motivating | 1.0 | 1.0 | 970 | 970 | 970 |
| notifications_unwanted | 1.0 | 1.0 | 184 | 184 | 184 |
| challenges_indifferent | 1.0 | 1.0 | 210 | 210 | 210 |
| setup_blocked | 1.0 | 1.0 | 325 | 325 | 325 |
| price_too_high | 1.0 | 1.0 | 1126 | 1126 | 1126 |
| worth_the_price | 1.0 | 1.0 | 821 | 821 | 821 |

### 3.6 Code-layer mutation suite

22 flaw families, 61 seeded instances: **61 caught (100.0%)**. Clean controls flagged: 0 of 4. This measures the validators and the deterministic critic checks only. A Reviewer *model* was not involved.

| Id | Flaw | Must be caught by | Caught |
|---|---|---|---|
| M01 | unsupported_claim | validator: V-ID | 3/3 |
| M02 | unknown_evidence_id | validator: V-ID | 4/4 |
| M03 | foreign_decision_id | validator: V-ID | 2/2 |
| M04 | valid_but_irrelevant_citation_type | validator: V-SEM-TYPE | 3/3 |
| M05 | valid_but_irrelevant_citation_scope | validator: V-SEM-SCOPE | 3/3 |
| M06 | mixed_stance_citation | validator: V-SEM-STANCE | 3/3 |
| M07 | invented_ddi | validator: V-NUM | 3/3 |
| M08 | invented_percentage | validator: V-NUM | 3/3 |
| M09 | invented_effect_size | validator: V-NUM | 3/3 |
| M10 | invented_p_value | validator: V-NUM | 3/3 |
| M11 | invented_confidence_interval | validator: V-NUM | 3/3 |
| M12 | invented_sample_size | validator: V-NUM | 3/3 |
| M13 | wrong_sign | validator: V-NUM | 3/3 |
| M14 | causal_claim_from_observational_evidence | validator: V-SEM-TYPE | 3/3 |
| M15 | recommendation_management_should | validator: V-REC | 4/4 |
| M16 | recommendation_imperative | validator: V-REC | 2/2 |
| M17 | sufficient_text_while_gated | validator: V-GATE | 1/1 |
| M18 | ddi_number_while_gated | validator: V-GATE | 1/1 |
| M19 | sentence_without_claim_reference | validator: V-REF | 3/3 |
| M20 | omitted_contradiction | critic: contradiction_ignored | 3/3 |
| M21 | ignored_critical_dq_issue | critic: dq_issue_ignored | 1/1 |
| M22 | high_confidence_on_grade_c_or_d | critic: evidence_overstated | 4/4 |

### 3.7 Product KPIs (PRD section 17), demo data

*Labelled demo data (synthetic). Syntheses and reviews in the demo database are replayed fixtures (stub, not model output).*

| KPI | Value | Note |
|---|---|---|
| Assessment coverage | 100.0% (4/4) | decisions with >= 1 completed assessment |
| Insufficient-evidence rate | 37.5% (3/8) | of all stored completed assessment versions, superseded ones included (monitored, not minimised) |
| Acknowledged-risk decisions | 0 decided while High/Critical/insufficient; 0 of 0 records acknowledge risk | the demo state has no decided decision unless a Playwright run advanced one |
| Traceability rate | 100.0% (22/22) | claims with >= 1 evidence id and one source |
| Quantitative claims with an analysis | 100.0% (12/12) | behavioral/experiment claims whose cited evidence has an analysis id |
| NBE acceptance rate | n/a | no recommendation has been accepted or rejected in the demo state |
| Time-to-assessment vs a manual baseline | not measured | no manual baseline exists |
| Observed DDI reduction after an accepted NBE action | not measured | no accepted NBE action has been followed by a re-assessment |

## 4. Failures and not-evidenced items

**Known gaps (a documented expectation that the frozen engines do not meet; the spec records it as a failure, nothing was tuned):**

- `core_community` / `nbe_includes:segment_level_analysis`: OBSERVED GAP, not tuned away. The manifest expects segment-aware validation, but the frozen NBE excludes an action at or above its ceiling (NBE spec R9): Community D6 is 0.60, equal to the 0.6 ceiling of segment_level_analysis, so the action would reduce nothing and is not listed, although the heterogeneity flag fires. The AC-5 clause "NBE recommends segment-aware validation" is therefore NOT MET by the frozen NBE v0.2 (Day-7 report, acceptance matrix AC-5).

No unexpected failure: every expectation of every spec is met except the known gaps above.

**Found and fixed by the evaluation (D7-06).** Before the V-NUM sign check, the seeded wrong-sign flaw (M13: a claim saying the outcome *decreased* by the exact magnitude of a positive effect) was **missed in 3 of 3 instances** (code-check recall 58/61 = 95.1%). After the sign check all 61 are caught, the clean controls are still not flagged, and the Day-5 fixtures still pass.

**Community band vs manifest.** The manifest expects a *moderate* band for Community; the frozen engine returns *high*. The snapshot records the engine output (D7-01); the manifest's band set was a Day-1 expectation, not a validated target. It is reported, not tuned.

**NOT EVIDENCED** (not measured: no live model (replay fixtures are hand-authored)): reviewer recall, reviewer false-flag rate, real classification accuracy, live schema validity, repair-retry rate, real-model injection resistance, real-model refusal correctness, time-to-assessment against a manual baseline.

## 5. The stub and templated-data caveats

- Every classification, synthesis and review in this report is a **replayed fixture or a keyword-rule stub (stub, not model output)**. The hand-authored synthesis and review fixtures deliberately contain injected flaws (a causal overclaim for AI Coach, a "no harm" claim for Pricing) so the pipeline can be exercised; the Reviewer that flags them is a fixture, not evidence that a model would.
- The synthetic customer feedback is templated (195 distinct sentences for 6,083 rows). Any agreement with the generator's labels is optimistic by construction.
- FitConnect data is synthetic and generated from a fixed seed; segment effects, defects and experiment shapes were authored to exercise the engines.
- The DDI v0.1 parameters are *proposed defaults*, not validated. The golden bands are what the engine returns for these synthetic inputs, not a claim about the real world.
- The clean controls and mutated syntheses are built by code from real payloads; they are not human- or model-written text, so the false-flag rate of the code layers on real model output is unknown.

## 6. How to reproduce

```bash
docker compose up -d db
PYTHONPATH="backend;." backend/.venv/Scripts/python -m database.seed.run --reset      # clean synthetic data
PYTHONPATH="backend;." DDR_LLM_MODE=replay backend/.venv/Scripts/python scripts/demo_prepare.py       # demo state (KPIs and the spot-audit read it)
backend/.venv/Scripts/python -m pytest tests/evals                                                    # specs + mutation suite, rolled back; writes analytics/eval/*
PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_snapshot.py --check                 # engine output vs the golden snapshot
PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_report.py                           # metrics.json, this report, the spot-audit sheet
```
To re-record the golden snapshot after a deliberate, approved engine change: `scripts/eval_snapshot.py --write` (never edit the file by hand).

## 7. Versions and hashes of every parameter set and prompt

| Kind | Version / name | File | SHA-256 |
|---|---|---|---|
| engine parameters | ddi_params_v0.1 | ddi/ddi_params_v0.1.yaml | `fd2541522b34f0fa2344076048f656fee8df8e9023148445fe53b3c7c119bcee` |
| engine parameters | nbe_params_v0.1 | nbe/nbe_params_v0.1.yaml | `8a7c730edb77fc7b7f69cce487bce99fba5ace660f1c028c8cb6692221546ff7` |
| engine parameters | nbe_params_v0.2 | nbe/nbe_params_v0.2.yaml | `c46727dd40fc642c01ea1cb490b346e41242dce11823bc55481210dc747658b2` |
| engine parameters | analytics_params_v0.1 | analytics/analytics_params_v0.1.yaml | `b3dfcee11c9e0d61572f471905f03e19f5641ddbdabc723f61abae62a1fa2e05` |
| engine parameters | analytics_params_v0.2 | analytics/analytics_params_v0.2.yaml | `40cdd235713f7d67e2b9cd6115cc0914bb8fe66efff99555b019e144cfb31a3f` |
| tenant configuration | fitconnect_analytics_config_v0.1 | orgs/fitconnect/analytics_config.yaml | `912ba893711b2105cad2fc100f8ede2d28f604aac753f604b48539f96e868bc9` |
| tenant configuration | fitconnect_analytics_config_v0.2 | orgs/fitconnect/analytics_config_v0.2.yaml | `75ee799085bdca39dda9f846703d229e6c8d89d0201f79c125d8e72a3f7b9f51` |
| prompt | v0.1/classify | v0.1/classify.md | `fa35910d45a36a92289a59607cea9859b4f24fbbdca5b09c6e1e32eddb4d7eeb` |
| prompt | v0.1/review | v0.1/review.md | `f23d281e9c1453b62272dfd60a0a17aee8d92697d86a00dcfcf8eb5f9ac7e234` |
| prompt | v0.1/synthesize | v0.1/synthesize.md | `8347842bb10108276c58c729e120a251104424da61c9cee70d1e2e508261fa9c` |
| evaluation input | 01_core_ai_coach.yaml | tests/evals/scenarios/01_core_ai_coach.yaml | `9ede5747c113e9f0ccfacfc34067f50d55e0458f429ad1a47f57c81eed3410d5` |
| evaluation input | 02_core_community.yaml | tests/evals/scenarios/02_core_community.yaml | `25f970101ba65d9db1e6429d9c3c0b272d512df06af024ee4359d6ff82aef002` |
| evaluation input | 03_core_onboarding.yaml | tests/evals/scenarios/03_core_onboarding.yaml | `f7bffd8e3baf027d7f972fea682ed102964797a3d34d028caf4dfa4d324996a8` |
| evaluation input | 04_core_pricing.yaml | tests/evals/scenarios/04_core_pricing.yaml | `e270c76d37dd36a4b987e3cceb85c805b052812579ca66c70543e1e0f9260fc0` |
| evaluation input | 10_var_onboarding_dq_resolved.yaml | tests/evals/scenarios/10_var_onboarding_dq_resolved.yaml | `ae773abb3f568c6bc21832ff75a39e633a4c1e688141ced83c8e8ad0c9594d4d` |
| evaluation input | 11_var_clean_strong_evidence.yaml | tests/evals/scenarios/11_var_clean_strong_evidence.yaml | `86a8f2be6f655f2bc85c03da5ed05f98bf0d93d4aeb03f9275369af6f85da70c` |
| evaluation input | 12_var_empty_evidence.yaml | tests/evals/scenarios/12_var_empty_evidence.yaml | `8bb13f28bbc4a50483fd9dc77bb19e7306cefdb51c8d439f4df1bd55287eca63` |
| evaluation input | 13_var_contradictory_evidence.yaml | tests/evals/scenarios/13_var_contradictory_evidence.yaml | `96b4d9880d68755b2114083f469ec86148dd5b504b059ac636ce06549de753ff` |
| evaluation input | 14_var_stale_evidence.yaml | tests/evals/scenarios/14_var_stale_evidence.yaml | `f6917af417d3c96170f40cd29c34d538c5e6552ff846d756e434565a868d11b2` |
| evaluation input | 15_var_injection_in_customer_text.yaml | tests/evals/scenarios/15_var_injection_in_customer_text.yaml | `48e70ef84f8916c830469c6cb02c4fed255461ca728d0074b389f8a151110a38` |
| evaluation input | 20_extra_customer_rejected.yaml | tests/evals/scenarios/20_extra_customer_rejected.yaml | `bb070ee0257eefeea277dbced32d1e2f79bcc15526c4e37046fa64f3ef84b98f` |
| evaluation input | 21_extra_customer_left_proposed.yaml | tests/evals/scenarios/21_extra_customer_left_proposed.yaml | `bd4608bf0df4046d83f24ae4297dc38a16653a27d9f6d464b4b2c4fb4edc354b` |
| evaluation input | 22_extra_reviewer_failing.yaml | tests/evals/scenarios/22_extra_reviewer_failing.yaml | `0d759776b289d94b3ebcfb651638ab642468679797d58c49b2bba14ff1f80541` |
| evaluation input | 23_extra_malformed_synthesis.yaml | tests/evals/scenarios/23_extra_malformed_synthesis.yaml | `fc6c74dbc1d2689800367e612f44a71390528720d44f038bb4e95bf3aba7de93` |
| evaluation input | 24_extra_canvas_edit_stale.yaml | tests/evals/scenarios/24_extra_canvas_edit_stale.yaml | `054fd54bf4ba1950692a0f3e5e7669b6e9fc6d46eb64a49ec63997aede48b8df` |
| evaluation input | 25_extra_needs_rework_override.yaml | tests/evals/scenarios/25_extra_needs_rework_override.yaml | `430e3524f0c2a5c0b7789b5bf5be279e19e43ba340165d916c5dd8477e409f44` |
| evaluation input | 26_extra_decided_freezes_writes.yaml | tests/evals/scenarios/26_extra_decided_freezes_writes.yaml | `e6e5689ee4914dc292e6e6b78a1590e9fbcfea6eb1aa15709f80d36442033c0e` |
| evaluation input | 27_extra_gated_summary_path.yaml | tests/evals/scenarios/27_extra_gated_summary_path.yaml | `64e1f4b4f3ff050e876a7b7ce7ebd4b7155ba5ce739836a0b45a11bc11c6c63b` |
| evaluation input | 28_extra_defer_stale.yaml | tests/evals/scenarios/28_extra_defer_stale.yaml | `3781b56423397466a8a1429989e65ab050fbe657a187100cc05adf885f287f5d` |
| evaluation input | 29_extra_approval_bypass_refused.yaml | tests/evals/scenarios/29_extra_approval_bypass_refused.yaml | `629cc3e6bff1fd47bed98c291e9377ac1ed21db3a949ec89802f6171f0e1b8e6` |
| evaluation input | 30_extra_dq_resolved_pipeline_reopens.yaml | tests/evals/scenarios/30_extra_dq_resolved_pipeline_reopens.yaml | `f1cfbe01269f62fbba4b02d5a7209299e197cb67e4058f3e59de0d2728cae8ff` |
| evaluation input | mutations.yaml | tests/evals/mutations.yaml | `9907d748a9b0c98029170224ff39f424f94cd19717a8d8baa3804402cf336868` |
| evaluation input | observed.json | tests/evals/golden/observed.json | `856dee081a4899bab55c686dbdf55abd1e5c286804c3be5a91dcc0c78fdcb635` |

