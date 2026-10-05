# Day 5 Implementation Brief: customer evidence, synthesis, review, brief (first LLM boundary)

**Status:** APPROVED for implementation (2026-10-04). Decisions D5-01 to D5-12 were frozen by the Product Owner (PO) on 2026-10-02, with the PO's three tightenings (§1.2). The two open points in §2 were resolved with the recommended defaults, and the PO explicitly confirmed both: P1 option A and stub fixtures. Everything else is binding. Where this brief is silent, stop and report. Do not invent methodology.
**Baseline:** commit `65caec6` (Day 4 + 4.1 + 4.1b), Alembic head `0005`, 509 tests, manifest 33/33.

> All FitConnect data is synthetic. DDI is a transparent evidence-risk heuristic, not an industry standard. The LLM never makes or recommends the business decision.

---

## 0. Architecture (frozen)

```
Raw customer feedback (fc_.v_feedback)
  → LLM classification (theme + relevance only, closed taxonomy)           [Stage 3, Sonnet]
  → immutable classification records
  → deterministic aggregation per (decision, theme)
  → PROPOSED customer evidence
  → human approval (BA / product analyst)
  → ACTIVE evidence → EvidenceFacts → frozen DDI / NBE                     [Day-3 assessment]
  ───────────────────────────────────────────────────────────────────────
  → LLM evidence synthesis                                                 [Stage 5, Sonnet]
  → deterministic validators (grounding, semantic citation, numbers, causal, recommendation)
  → Reviewer / Critic                                                      [Stage 6, Opus → logged Sonnet fallback]
  → code-derived verdict → human validation (existing R12 override)
  → Validated Decision Brief   (or, for a gated assessment, a Gated Evidence Summary)
```

**Hard rules:**
- DDI v0.1 and NBE v0.2 code, parameters and semantics are unchanged.
- T-GUARD-1 extends to `65caec6`:
  - no diff in `backend/app/domain/ddi/**`, `backend/app/domain/nbe/**`, `backend/config/ddi/**`, `backend/config/nbe/**`;
  - no exception (§2 P1 resolved as option A).
- No new agents.
- No LLM-written SQL.
- No database access by the model.
- No tool use by the model.

## 1. Frozen decisions

### 1.1 D5-01 to D5-12 (as approved)

| # | Rule |
|---|---|
| D5-01 | The LLM assigns only `theme` (from a closed, per-decision taxonomy, or `null`) and `relevance` (`direct` / `adjacent` / `not_relevant`). Nothing else. |
| D5-02 | Evidence derived from classification is created with status `proposed`. Only `active` (human-approved) evidence enters EvidenceFacts. |
| D5-03 | Stance comes from a human-authored, versioned, hashed theme → stance map in tenant config. The LLM never chooses stance. |
| D5-04 | One evidence item per (decision, theme), created only if relevant mentions ≥ `min_theme_mentions` (default 30, in `analytics_params`; see §3). Themes below that threshold are reported as gaps. |
| D5-05 | Observed relevance, with segment coverage explicitly defaulted. Per §2 P1 (option A), the observed relevance is stored and displayed, but the DDI keeps its default relevance. |
| D5-06 | Grade is deterministic: **C** if mentions ≥ 100 and at least 2 source types, otherwise **D**. Never A or B. Tier comes from the feedback data source. `observed_end` = the latest mention date. |
| D5-07 | Order: synthesis → review → validated → Decision Brief. |
| D5-08 | An LLM failure leaves the deterministic assessment valid. A failure never counts as a review pass. |
| D5-09 | Any blocking finding gives verdict `needs_rework`. The verdict is derived by code, never by the model. A human may override with a reason (R12) or request a re-synthesis (a new synthesis version). |
| D5-10 | No business recommendation anywhere. A validator rejects recommendation phrasing. |
| D5-11 | Sonnet for classification and synthesis; Opus for review, with `model_fallback=true` logged when Opus is unavailable. Temperature 0. Reproducibility comes from **stored outputs**, never from re-generation. |
| D5-12 | An `LlmClient` interface with a recorded-fixture fake for every CI test. Live calls only through `@pytest.mark.llm` plus `ANTHROPIC_API_KEY`. |

### 1.2 PO tightenings

- **T1. Approval granularity.** A human approves or rejects the **(decision, theme) evidence item**, not individual classifications. Classifications stay immutable, auditable inputs.
- **T2. Gated Evidence Summary.** A **Validated Decision Brief** exists only after `validated`. An assessment in `insufficient_evidence` state may have a **Gated Evidence Summary**, which:
  - is labelled on every rendering as *"Gated Evidence Summary: not a validated decision artifact"*;
  - can never be used as a Decision Brief;
  - explains the blocking reasons.
- **T3. Semantic citation validation.** Citing an evidence ID that appears in the input isn't enough. A deterministic validator checks that the cited evidence **supports the claim's permitted type, stance and scope** (§6.2).

## 2. Resolved points (recommended defaults, 2026-10-04)

**P1 → option A. D5 relevance stays defaulted in the DDI.** `scoring.py:393` always uses `params.default_relevance` for D5, and there is no input path for an observed value.
- `relevance_observed` is computed and stored on `customer_insights`, and shown in the evidence and the brief.
- It is labelled "observed, not used by DDI v0.1".
- It does **not** enter EvidenceFacts or the DDI. It is documented as a planned DDI v0.2 input.
- There is no T-GUARD-1 exception: zero diff in the DDI and NBE paths.
- Rejected alternative (B): a DDI v0.1.1 change.

**P2 → deterministic stub fixtures, clearly labelled. Live recording is deferred.** `ANTHROPIC_API_KEY` is empty in `.env` and unset in the environment.
- **Classification fixtures** cannot be hand-written for ~6k texts. Instead, generate them with a **deterministic keyword-rule stub** in `tests/fixtures/llm/stub_classifier.py`:
  - test-only;
  - rules are authored from the taxonomy descriptions;
  - it must **never** read `feedback_ground_truth` (G3 covers it).
- **Synthesis and review fixtures** are hand-authored JSON for the four scenarios. Each is built from the actual deterministic payload of that scenario, with the injected faults that A1 and A4 require.
- **Every stub fixture carries `"provenance": "stub_not_model_output"`.** `agent_runs.model` records `stub:<name>` for them, so stored rows never claim a real model produced them.
- **E1 runs against the stub.** It is reported as "stub classifier vs ground truth: measures the pipeline, not the model". Model E1 is `@pytest.mark.llm` and is skipped without a key.
- **Provide `scripts/record_llm_fixtures.py`.** It is a live run that writes fixtures with `"provenance": "recorded_model_output"`. It runs only when the key is set and is not executed on Day 5.

## 3. Configuration

**`analytics_params_v0.2.yaml`** (new version; v0.1 unchanged, hash-registered):
- adds a `customer` section: `min_theme_mentions: 30`, `grade_c_min_mentions: 100`, `grade_c_min_source_types: 2`, `sample_quotes_per_insight: 5`;
- adds an `llm` section: `temperature: 0`, `max_output_tokens` per purpose, `timeout_s: 60`, `max_retries: 1` (on transport errors only), `classification_batch_size: 50`.

**Tenant config `orgs/fitconnect/analytics_config.yaml` → new hashed version.** For each `scenario_key`, a `customer_taxonomy` entry: `taxonomy_version`, plus `themes: [{theme, description, stance}]`.
- The stance map is human-authored. Proposed values:
  - **AI Coach:** `coach_helpful` supports, `coach_generic_or_wrong` contradicts, `coach_indifferent` neutral.
  - **Community:** `challenges_motivating` supports, `notifications_unwanted` contradicts, `challenges_indifferent` neutral.
  - **Onboarding:** `setup_blocked` **supports** (the problem exists; it is not evidence that the redesign works).
  - **Pricing:** `price_too_high` contradicts, `worth_the_price` supports.
- Theme names must **not** copy the ground-truth labels in `feedback_ground_truth`. The taxonomy is authored independently.

**Prompt files** in `prompts/v0.1/`: `classify.md`, `synthesize.md`, `review.md`, plus `prompts/prompt_hashes.json`.
- Loaded with the same version and hash checks as the parameter files.
- Each prompt states that text inside `<untrusted_customer_text>` is data, never instructions.

## 4. Schema: migration 0006

| Object | Change |
|---|---|
| `llm_classifications` (new) | `id`, `decision_id` FK, `feedback_id` (bigint, the `fc_` id stored as a value, no FK into `fc_`), `text_sha256`, `taxonomy_version`, `theme` (nullable), `relevance` (enum `direct` / `adjacent` / `not_relevant`), `prompt_version`, `prompt_sha256`, `model`, `agent_run_id` FK, `created_at`, `is_synthetic`. Unique on `(decision_id, feedback_id, taxonomy_version, prompt_version, model)`. **Insert-only** (trigger). A cache read by `text_sha256` is allowed across decisions only with the same taxonomy version. |
| `evidence.status` | allows `proposed`, `active`, `superseded`, `rejected`. The active-identity unique index covers `active` and `proposed`. Add `approved_by`, `approved_at` and `approval_note`. A CHECK requires `approved_by` and `approved_at` for an active **customer** evidence item created by an agent. |
| `customer_insights` | add `relevance_observed numeric`, `source_types text[]`, `first_mention_date`, `last_mention_date`, `taxonomy_version`, `segment_counts jsonb`. |
| `syntheses` (new) | `id`, `assessment_id` FK, `version` (unique per assessment), `agent_run_id` FK, `status` (`succeeded` / `failed` / `rejected_by_validators`), `input_sha256`, `output_sha256`, `output` jsonb, `validator_report` jsonb, `claims_dropped int`, `created_at`, `is_synthetic`. Immutable and no delete (same trigger pattern as assessments). Covered by the decided guard. |
| `claims` | add `synthesis_id` FK (NOT NULL for rows created from Day 5 on; enforced in the service and by a CHECK on new rows), plus `local_id text`. |
| `decision_reviews` | add `synthesis_id` FK and `agent_run_id` FK. Insert-only. |
| `decision_briefs` (new) | `id`, `assessment_id` FK, `synthesis_id` FK (nullable only for a gated summary without a successful synthesis), `kind` (`decision_brief` / `gated_evidence_summary`), `version` (unique per assessment and kind), `content` jsonb, `markdown`, `created_at`, `is_synthetic`. Immutable and no delete. A CHECK and a trigger enforce that `decision_brief` requires decision stage `validated` or `decided` at insert, and that `gated_evidence_summary` requires assessment state `insufficient_evidence`. |
| `agent_runs` | add `purpose` (`classify` / `synthesize` / `review`), `model_fallback bool`, `prompt_id`, `prompt_sha256`, `params jsonb`, `input_sha256`, `output_sha256`, `request_id`, `error_class`. |
| `decision_assessments.brief_md` | left in place and unused. Documented as deprecated. |

The facts builder and fingerprint read only `status = 'active'` evidence. `proposed` and `rejected` items are excluded from DDI and NBE.

## 5. Stage 3: customer evidence

1. **Select candidates.** Feedback in the decision's analysis window (ending at or before the as-of date), from `fc_.v_feedback` through the SQL guard. Never read `feedback_ground_truth`.
2. **Classify** each distinct text, batched.
   - Cache lookup by `(text_sha256, taxonomy_version, prompt_version, model)`. Only misses call the LLM.
   - The model output must parse against a schema of `{text_ref, theme ∈ taxonomy ∪ {null}, relevance}`.
   - Any out-of-taxonomy theme or unknown `text_ref` fails the batch.
3. **Aggregate deterministically.** For each theme with relevant mentions ≥ `min_theme_mentions`:
   - one `customer_insights` row with counts, sentiment = the theme stance's label, `relevance_observed` = the share of `direct`, segment counts, and deterministic sample quotes (the lowest `text_sha256` order);
   - one evidence item with `type=customer`, `insight_id`, stance from the map, the D5-06 grade, tier from the data source, `metric_id=NULL`, `analysis_identity` = sha256(decision | theme | taxonomy_version | prompt_version | model), and `status=proposed`.
4. **Idempotency.** Same identity → no change. A new identity (taxonomy or prompt change) supersedes the old item through the Day-4 rules.
5. **Pipeline behaviour.** The pipeline then continues to the assessment, which uses **active evidence only**. The response lists pending approvals.
6. **Approval** (`PATCH /evidence/{id}/approval`) is an evidence change, so the Day-3 stale rule applies: re-run the pipeline or assessment to score with the approved evidence. Rejected items are never re-proposed for the same identity.

## 6. Stage 5: synthesis

### 6.1 Contract

**Input:** a minimal JSON object containing:
- the canvas (title, hypothesis, `expected_direction`, success metric, change-my-mind criteria);
- the DDI result payload (state, band, contributions, penalties, sensitivity, direction, blocking reasons, NBE);
- **active** evidence items (id, type, stance, grade, tier, summary, effect, CI, n, `analysis_id`, DQ status, `experiment` design and SRM);
- non-pass DQ findings;
- the heterogeneity result;
- customer insights, with sample quotes inside `<untrusted_customer_text>`.

**Output:** a validated JSON schema:
- `claims[]`: `{local_id, text, claim_type ∈ {descriptive, associative, causal, financial, customer, risk}, stance, confidence ∈ {low, medium, high}, evidence_ids[≥1], conclusion_ref}`
- `uncertainties[]` and `gaps[]`: `{text, evidence_ids[] | gap_type}`
- `criteria_assessment[]`: `{criterion_index, status ∈ {met, not_met, not_testable}, evidence_ids[]}`
- `sections`: `{summary, supporting, contradicting, uncertainty}`. Free text may reference claims only as `[[local_id]]`.

### 6.2 Deterministic validators (run before storing claims)

| ID | Rule | On failure |
|---|---|---|
| V-ID | Every cited evidence ID is in the supplied active set | drop the claim, log it |
| V-SEM-TYPE | claim_type is compatible with the cited types: `customer` needs ≥1 customer item; `financial` needs financial; `causal` needs an experiment with design ≥ holdout and SRM passed (else reclassified to `associative`, as in TM-6); `associative` needs behavioral or experiment | drop or reclassify, log it |
| V-SEM-STANCE | a `supports` claim cites ≥1 supporting item and no contradicting item only; a `contradicts` claim cites ≥1 contradicting item; `neutral` is unrestricted | drop, log it |
| V-SEM-SCOPE | `conclusion_ref` (D1–D7, P1, P2, gate) is consistent with the cited types, e.g. D5 needs customer, D4 needs experiment, D6 needs behavioral with an effect | drop, log it |
| V-NUM | every number in a claim's text must appear, within rounding, in the **cited** items' fields or the DDI payload | drop, log it |
| V-REC | no imperative or recommendation phrasing in any field ("should approve", "we recommend", "go ahead", …; deny-list plus pattern) | the synthesis becomes `rejected_by_validators` |
| V-GATE | for an insufficient assessment, no text may describe the evidence as sufficient or present a DDI number | `rejected_by_validators` |
| V-REF | every `[[local_id]]` in a section refers to a surviving claim; references to dropped claims are removed and noted | repair, log it |

- If more than 50% of the claims are dropped, the synthesis is `rejected_by_validators`.
- Malformed JSON gets one repair attempt (a re-ask with the parse error), then `failed`.
- The validator report is stored. The Reviewer receives it.

## 7. Stage 6: Reviewer / Critic

- **Input:** the synthesis output, the validator report and the same structured facts.
- **Output:** `findings[]` with `{category, severity ∈ {blocking, warning, info}, target_type ∈ {claim, section, criterion, synthesis}, target_id, rationale, evidence_ids[]}`.
- **Categories (closed):** `unsupported_claim`, `missing_evidence`, `incorrect_citation`, `contradiction_ignored`, `uncertainty_understated`, `evidence_overstated`, `causal_from_observational`, `statistical_misinterpretation`, `dq_issue_ignored`, `customer_overgeneralization`, `stale_evidence`, `conflicting_evidence`, `scope_mismatch`, `criterion_mismatch`, `recommendation_as_fact`, `narrative_inconsistent_with_facts`.
- **Minimum severities** are enforced in code, so the model can raise but never lower them. These are always **blocking**:
  - `unsupported_claim`, `incorrect_citation`, `causal_from_observational`, `dq_issue_ignored`, `recommendation_as_fact`, `narrative_inconsistent_with_facts`, `contradiction_ignored`.
- **Verdict (code):** any blocking finding → `needs_rework`, otherwise `ready`.
- Stored as a `decision_reviews` row (`reviewer_type=agent`, with `synthesis_id` and `agent_run_id`). Recording it moves the decision `assessed → challenged` (the existing rule).
- **Reviewer failure:** no review row. The decision stays `assessed`. A human review (with reason) is then required, and the brief carries the banner **"No automated adversarial review"**.

## 8. Briefs

- **Validated Decision Brief** (`kind=decision_brief`): only when the decision is `validated` or `decided`, and only from the latest succeeded synthesis that the validating review covered.
  - **Deterministic sections:** header (as-of date, every version and hash), DDI panel, direction, gate reasons, evidence table (with status), DQ, heterogeneity, NBE, the traceability appendix, review findings plus human responses, and the decision record if one exists.
  - **LLM sections:** copied verbatim from the validated synthesis (summary, supporting, contradicting, uncertainty, criteria), with citations.
  - **No recommendation section.**
- **Gated Evidence Summary** (`kind=gated_evidence_summary`): only for an `insufficient_evidence` assessment. Contents:
  - the deterministic sections;
  - the blocking reasons explained;
  - the unblocking NBE actions;
  - plus the synthesis sections if a succeeded synthesis exists.
  - The label from T2 appears on every rendering.
- Both kinds are immutable and versioned. Regenerating creates a new version.

## 9. API (minimal)

| Endpoint | Permission | Notes |
|---|---|---|
| existing `POST /decisions/{id}/pipeline-runs` | run assessment | now runs Stages 3, 5 and 6. The response includes pending approvals and the synthesis and review status |
| `GET /decisions/{id}/customer-evidence` | read | proposed, active and rejected items with an insight summary and classification counts |
| `PATCH /evidence/{id}/approval` `{action: approve\|reject, note}` | ba, product_analyst | proposed items only; audited; marks the assessment stale |
| `POST /assessments/{id}/syntheses` | pm, ba | re-synthesis; idempotent on `input_sha256` unless `force=true`; creates a new version and a new agent review |
| `GET /assessments/{id}/syntheses` | read | |
| `POST /assessments/{id}/briefs` `{kind}` | pm, ba | 409 if the stage or state rule isn't met |
| `GET /briefs/{id}` | read | |

There is no generic agent endpoint. The existing human review, validate and decision-record endpoints are unchanged.

## 10. LLM client, metadata, security

- **Client:** `backend/app/llm/client.py` defines the `LlmClient` protocol, `AnthropicClient` (the only importer of `anthropic`) and `RecordedClient` (fixtures keyed by purpose, prompt version and `input_sha256`).
- **Scope guard:** `anthropic` may be imported only in `backend/app/llm/anthropic_client.py`.
- **Calls:** timeout 60 s; one retry on transport, rate-limit or 5xx errors; no retry on schema errors (the repair path in §6.2 applies).
- **Every call writes one `agent_runs` row** with the §4 metadata, raw input and raw output. Hashes are SHA-256 of the canonical JSON.
- **Security:**
  - only synthetic data leaves the app;
  - customer text is wrapped and escaped;
  - basic redaction (emails, phone-like digit runs) before sending;
  - every model-output ID is validated against the input set;
  - the model output is never executed or used as SQL;
  - system prompts are never echoed into stored user-visible text.

## 11. Required tests

**Guards**
- G1: T-GUARD-1 against `65caec6` for the DDI and NBE paths (zero diff).
- G2: the scope guard (`anthropic` only in the client module; no `agents`; `sqlglot` only in the SQL guard).
- G3: `feedback_ground_truth` is never read by product code, prompts or config.

**Customer evidence**
- C1: classification output schema; out-of-taxonomy themes and unknown refs fail.
- C2: the cache prevents a second LLM call (the fake client counts calls).
- C3: aggregation gives one item per (decision, theme) at or above the threshold; below-threshold themes become gaps.
- C4: stance comes only from the map; a changed map changes the identity and the old item is superseded.
- C5: grading truth table, never A or B.
- C6: `proposed` items are excluded from the facts and fingerprint; approval → active → stale; rejection is permanent for that identity.
- C7: customer evidence never changes D4 or the experiment fields (Pricing).

**Validators** (pure, no LLM)
- V1: V-ID, V-SEM-TYPE, V-SEM-STANCE, V-SEM-SCOPE, V-NUM, V-REC, V-GATE and V-REF, each with pass and fail cases, including **an in-input but semantically wrong citation** (T3).

**Synthesis and review**
- S1: malformed JSON → one repair → `failed`; the assessment is unchanged.
- S2: more than 50% of claims dropped → `rejected_by_validators`.
- R1: the code-derived verdict; the model can't lower minimum severities.
- R2: a reviewer failure → no pass; validation needs a human override; the brief banner appears.
- R3: re-synthesis creates a new version and a new review; old rows are unchanged.

**Briefs**
- B1: `decision_brief` is refused before `validated`.
- B2: `gated_evidence_summary` exists only for insufficient assessments and carries the label.
- B3: briefs are immutable and versioned; there is no recommendation text.
- B4: every LLM sentence in a brief resolves to claims and evidence.

**Evaluation**
- E1: classification precision and recall per theme against `feedback_ground_truth` (test-only). The templated-text caveat is recorded.
- E2: mutation suite. Injected unsupported, overstated, contradiction-omitted and DQ-ignored claims are caught by the validators (deterministic) or the reviewer (live, opt-in).
- E3: prompt-injection fixtures (test-only feedback rows outside `fc_`) change neither the schema, the IDs nor the verdict.
- E4: reproducibility. Same input → same `input_sha256` → stored output reused; the DDI is unchanged when synthesis or review fails.

**Scenarios** (recorded client; **no band asserted in advance**)
- A1 **AI Coach:** after approval the gate passes, the assessment is scored, and the band is whatever the frozen engine produces. The synthesis is grounded. The reviewer flags an injected causal overclaim. The brief is traceable.
- A2 **Community:** scored after approval. The heterogeneity floor still applies. The synthesis discusses aggregate vs segment, and the notification-complaints theme is present as contradicting evidence.
- A3 **Onboarding:** complaints become proposed and then active customer evidence, but the gate **still blocks** on the open critical DQ issue. No number anywhere. A Gated Evidence Summary is available. A Decision Brief is refused.
- A4 **Pricing:** D4 is unchanged by customer evidence. The synthesis keeps the experiment inconclusive. The reviewer flags an injected "no harm" claim.

**Regression**
- All 509 prior tests pass (adjusted only where 0006 changes behaviour, each one listed).
- Clean rebuild.
- Downgrade 0006 → 0005.
- Manifest 33/33.

## 12. Not in Day 5

- No new agents.
- No DDI or NBE changes.
- No LLM-written SQL.
- No segment-coverage methodology.
- No automatic approval.
- No PII pipeline beyond basic redaction.
- No real customer data.
- No frontend or Power BI.
- No full evaluation report (Day 7).

## 13. Execution order

1. Migration 0006, the new config versions and prompt files with hashes.
2. LLM client (protocol, Anthropic client, recorded client) and the metadata writer.
3. Classification, aggregation, proposed evidence and approval.
4. Facts-builder `active` filter.
5. Validators.
6. Synthesis.
7. Reviewer and verdict.
8. Pipeline Stages 3, 5 and 6, with failure handling.
9. Briefs.
10. Evaluation tests.
11. Documentation.
12. Clean rebuild and full regression.

**Cut order if behind:** live LLM evaluation, then criteria assessment, then markdown rendering (keep the JSON).
