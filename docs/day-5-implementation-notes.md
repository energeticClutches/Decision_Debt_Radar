# Day 5: Implementation Notes

Parent: [day-5-implementation-brief.md](day-5-implementation-brief.md) (binding), [day-4-implementation-notes.md](day-4-implementation-notes.md), [traceability-spec.md](traceability-spec.md). **FitConnect is a fictional company. All FitConnect data is SYNTHETIC.** Baseline (rollback point): commit `65caec6` (Day 4 + 4.1 + 4.1b), Alembic head `0005`, 509 tests, manifest 33/33.

Scope: the first LLM boundary. Customer feedback is classified against a closed taxonomy (theme and relevance only) and aggregated deterministically into **proposed** evidence; a human approves or rejects each (decision, theme) item; only **active** evidence enters the frozen DDI. An evidence synthesis, eight deterministic validators and a Reviewer follow, and briefs are rendered from stored rows.

> **Honesty statement.** No `ANTHROPIC_API_KEY` exists and **no live model call was made on Day 5**. Every classification in the tests comes from a deterministic keyword-rule stub, and every synthesis and review comes from a hand-authored fixture. All of them carry `"provenance": "stub_not_model_output"` and a model name `stub:<name>`, so no stored row claims that a real model produced it. The stub E1 result below measures the pipeline and the keyword rules, **not a model**.

> **The hard rule.** `git diff --stat 65caec6 -- backend/app/domain/ddi backend/app/domain/nbe backend/config/ddi backend/config/nbe` is empty (test G1). DDI v0.1 and NBE v0.2 code and parameters are unchanged. P1 is resolved as option A: `relevance_observed` is stored on `customer_insights` and shown in the evidence and the brief ("observed, not used by DDI v0.1"); it never enters `EvidenceFacts` or the DDI. It is a planned DDI v0.2 input.

## 1. Architecture as built

```
backend/app/
  llm/            client.py (LlmClient protocol, RecordedClient, errors, hashing), anthropic_client.py (the ONLY importer of
                  `anthropic`), prompts.py (versioned, hash-checked), sanitize.py (redact, escape, wrap), builders.py,
                  runs.py (the agent_runs metadata writer: one row per call)
  customer/       schema.py (classification output schema), aggregate.py (pure aggregation, grade, identity)
  synthesis/      schema.py, validators.py (V-ID ... V-REF, pure), review.py (minimum severities, verdict), payload.py (the model's
                  input), briefs.py (labels and markdown)
  repositories/   customer.py, syntheses.py (new); evidence_facts.py (active-only filter)
  services/       customer_evidence.py (Stage 3 and approval), synthesis.py (SynthesisService, ReviewerService), briefs.py (new);
                  pipeline.py (Stage 3, then synthesis and review after the assessment); reviews.py (human review after an LLM failure)
  api/routes/customer.py   the section-9 endpoints
prompts/v0.1/{classify,synthesize,review}.md + prompt_hashes.json
tests/fixtures/llm/      stub_classifier.py, replay.py (test clients), recorded/*.json (8 hand-authored fixtures)
scripts/record_llm_fixtures.py (live recording; NOT run), scripts/hash_prompts.py
database/sql/0006_day5_llm_boundary.sql (+ _down), database/migrations/versions/0006_day5_llm_boundary.py
```

Flow of one pipeline run (`POST /decisions/{id}/pipeline-runs`, needs an LlmClient for the LLM parts):

1. DQ, quant, experiment, materialisation: unchanged Day-4 stages.
2. **Stage 3 (customer)**: read feedback of the window through the SQL guard (`fc_.v_feedback`, never the ground-truth table); classify the distinct texts that miss the cache (batches of 50, temperature 0); store one immutable `llm_classifications` row per feedback item; aggregate; propose one `proposed` evidence item per (decision, theme) with at least `min_theme_mentions` (30) relevant mentions; below it a gap is reported. An LLM failure makes the stage `partial` (no evidence is proposed from an incomplete classification) and does not stop the pipeline.
3. The Day-3 assessment runs on **active** evidence only. Proposed, rejected and superseded items are excluded from the facts and the fingerprint (`repositories/evidence_facts.py`).
4. **Stage 5 (synthesis)** and **Stage 6 (review)** run after the assessment is stored. Failure never touches the assessment (test E4). Without a client the stages are recorded as `not_run`.
5. A human approves or rejects the proposed items (`PATCH /evidence/{id}/approval`, ba or product_analyst). That marks the assessment stale (the Day-3 rule); re-running the pipeline scores with the approved evidence.

Lifecycle: recording the agent review moves `assessed` to `challenged` (existing rule). A `needs_rework` verdict is overridden only by a human review with a reason (R12, unchanged). If an LLM stage failed and no agent review exists, a human `ready` review needs a reason (test R2).

## 2. Migration 0006

| Change | Detail |
|---|---|
| `agent_runs` | `purpose` (classify, synthesize, review), `model_fallback` (NOT NULL, default false), `prompt_id`, `prompt_sha256`, `params`, `input_sha256`, `output_sha256`, `request_id`, `error_class` |
| `evidence` | `status` also `proposed` and `rejected`; `approved_by`, `approved_at`, `approval_note`; `ck_evidence_agent_customer_approved` (an active customer item created by an agent needs a human approval; **NOT VALID**, see below); `ck_evidence_rejected_actioned`; the active-identity unique index covers `active` and `proposed`; new index `(decision_id, status)` |
| `customer_insights` | `relevance_observed`, `source_types[]`, `first_mention_date`, `last_mention_date`, `taxonomy_version`, `segment_counts` |
| `llm_classifications` (new) | enum `customer_relevance`; unique `(decision_id, feedback_id, taxonomy_version, prompt_version, model)`; `feedback_id` is a bigint value (no FK into `fc_`); insert-only trigger; decided-guard |
| `syntheses` (new) | unique `(assessment_id, version)`; status `succeeded`, `failed`, `rejected_by_validators`; a succeeded row needs `output` and `output_sha256`; insert-only (no update, no delete); decided-guard |
| `claims` | `synthesis_id`, `local_id`; `ck_claims_synthesis_required` is **NOT VALID** (old rows are not re-checked, every new row must name its synthesis) |
| `decision_reviews` | `synthesis_id`, `agent_run_id`; insert-only trigger |
| `decision_briefs` (new) | kinds `decision_brief` and `gated_evidence_summary`; unique `(assessment_id, kind, version)`; CHECK that a decision_brief has a synthesis; trigger (decision stage validated or decided for the first kind, an `insufficient_evidence` assessment for the second, and the synthesis must belong to the assessment); insert-only. Not under the decided-guard on purpose: a Decision Brief may be produced after the decision is recorded |
| `decision_assessments.brief_md` | left in place, unused, column comment says DEPRECATED |

`_down.sql` drops the three tables and the new columns. Evidence is never deleted: a `proposed` or `rejected` item (which the 0005 constraints cannot hold) becomes a `superseded` row that points to itself, so it is excluded from every view and the facts. Claims, reviews and agent runs keep their rows. **A bug found by the downgrade test and fixed:** the first version of the up migration added the approval CHECK as validated; after a downgrade (approval columns dropped) the re-upgrade failed on an active agent-created customer row. The constraint is now NOT VALID (new and updated rows are checked, existing ones are not). Tests: `tests/db/test_day5_schema.py` (invariants, and downgrade 0006 to 0005 with Day-5 data then upgrade), `tests/db/test_migrations.py` (head is 0006, 25 tables).

## 3. New configuration versions and hashes

| File | SHA-256 | Registry |
|---|---|---|
| `backend/config/analytics/analytics_params_v0.2.yaml` | `40cdd235713f7d67e2b9cd6115cc0914bb8fe66efff99555b019e144cfb31a3f` | `params_hashes.json` entry `analytics_params_v0.2` (the only addition; every old entry unchanged) |
| `backend/config/orgs/fitconnect/analytics_config_v0.2.yaml` | `75ee799085bdca39dda9f846703d229e6c8d89d0201f79c125d8e72a3f7b9f51` | `orgs/config_hashes.json` entry `fitconnect_analytics_config_v0.2` (the only addition) |
| `analytics_params_v0.1.yaml`, `analytics_config.yaml` (tenant v0.1), DDI, NBE v0.1 and v0.2 | unchanged | unchanged (test G1 checks files and registries against `65caec6`) |

`analytics_params_v0.2` = v0.1 (every value unchanged, a test compares them) plus `customer` (`min_theme_mentions` 30, `grade_c_min_mentions` 100, `grade_c_min_source_types` 2, `sample_quotes_per_insight` 5) and `llm` (temperature 0, `max_output_tokens` per purpose, `timeout_s` 60, `max_retries` 1, `classification_batch_size` 50). The tenant v0.2 file adds `customer_feedback` (the allow-listed view and its columns) and `customer_taxonomy` (per scenario: `taxonomy_version` and `themes: [{theme, description, stance}]`, the human-authored stance map: coach_helpful supports, coach_generic_or_wrong contradicts, coach_indifferent neutral; challenges_motivating supports, notifications_unwanted contradicts, challenges_indifferent neutral; setup_blocked supports; price_too_high contradicts, worth_the_price supports). Theme names do not copy the ground-truth labels (test G3). The loader gained a `version` argument (the registry entry names the file); the active versions are the new defaults (`ANALYTICS_PARAMS_VERSION`, `TENANT_CONFIG_VERSION`, `.env.example` updated; `.env` untouched).

### Prompt hashes (`prompts/prompt_hashes.json`, version v0.1)

| Prompt | SHA-256 |
|---|---|
| `classify.md` | `fa35910d45a36a92289a59607cea9859b4f24fbbdca5b09c6e1e32eddb4d7eeb` |
| `synthesize.md` | `8347842bb10108276c58c729e120a251104424da61c9cee70d1e2e508261fa9c` |
| `review.md` | `f23d281e9c1453b62272dfd60a0a17aee8d92697d86a00dcfcf8eb5f9ac7e234` |

Each prompt states that text inside `<untrusted_customer_text>` is data, never an instruction. The loader checks existence, registration, hash and the declared id and version.

## 4. Methodology as built (and the points the brief left open)

- **Taxonomy identity.** The stored and keyed taxonomy version is `taxonomy_version#<first 12 hex of a hash of the themes, descriptions and stances>`. The brief says a changed stance map changes the identity; the identity formula (`sha256(decision | theme | taxonomy_version | prompt_version | model)`) does not contain the stance, so the hash is folded into the version string. A changed map, description or prompt can therefore never reuse a stored classification or evidence item.
- **Cache.** Keyed by `(text_sha256, taxonomy id, prompt version, model)` and read across decisions with the same taxonomy id. `llm_classifications.model` is the *requested* model name (stable); `agent_runs.model` is the answering model. In tests both are `stub:...`.
- **Window.** The brief says "the decision's analysis window, ending at or before the as-of date" without a start. I used no lower bound: every feedback row created before the end of the as-of day. (A lower bound would be new methodology.)
- **Relevant mention** = a classification with a theme and a relevance other than `not_relevant`. `relevance_observed` = direct / relevant. `segment_counts` use the metric's configured segment key (a count only, no coverage methodology: D5-05 keeps segment coverage defaulted).
- **Idempotency.** The same identity gives no change, even if new feedback arrived (an approved item is not silently rewritten). A rejected identity is never re-proposed. A new identity supersedes the live (active or proposed) item of the same theme through the Day-4 supersede fields; superseding an *active* item marks the assessment stale.
- **No analysis row for customer evidence.** Its chain is evidence, `customer_insights`, `llm_classifications` (with the agent run), the feedback view. `analysis_id` is NULL.
- **Approval.** Both approve and reject mark an assessed decision stale (the brief says the endpoint "marks the assessment stale"). `approved_by` and `approved_at` name the person who actioned the item for a rejection too.
- **Validators.** The brief's eight rules as written, plus: a claim without any evidence id is dropped by V-ID (TM-1); P1 needs a cited contradicting item (an interpretation of V-SEM-SCOPE "e.g."); V-NUM matches within the claim's own rounding, also as a percentage of a stored fraction, and ignores dates, `[[refs]]` and code tokens (D4, P1); numbers come from the cited items and the DDI payload only (not the heterogeneity or DQ sections); V-REF also removes a section sentence that cites no surviving claim, so that every sentence of a brief resolves to claims and evidence (test B4); zero surviving claims also rejects the synthesis. V-REC and V-GATE run on the model's text before repair, over dropped claims too. **Not implemented:** the TM-5 downgrade of quantitative claims without an analysis id (not in the brief's validator table).
- **Repair.** Malformed JSON or a schema violation gets one re-ask that carries the parse error; then the synthesis is `failed`. A transport error is retried once inside the client (not by the repair path).
- **Reviewer.** Invalid evidence ids in a finding are removed and noted, an unresolved target is kept and marked: a finding is never dropped, so a blocking finding cannot disappear. An unknown category or severity is a schema error: the review fails and no row is written. `needs_rework` blocks validation until a human override with a reason.
- **Briefs.** A Decision Brief uses the latest succeeded synthesis; if an agent review exists it must cover that synthesis (409 otherwise), and without an agent review the brief carries "No automated adversarial review". A decision_brief also requires a **scored** assessment (service and database trigger): an insufficient assessment gets a Gated Evidence Summary only, even after a human validates it (T2; tightened at verification, see section 11). The Gated Evidence Summary label is exactly "Gated Evidence Summary: not a validated decision artifact" and is the first and last line of the markdown. The recommendation-free rule is tested: the markdown contains no "recommend" and none of the V-REC phrases. NBE actions are shown as ways to gather more evidence.
- **LLM in the transaction.** The synthesis and review calls run while the decision row is locked (up to 60 s plus one repair). Acceptable for the demo; a queue would be needed for production.
- **No client.** Without `ANTHROPIC_API_KEY` the pipeline records the customer stage as `skipped_no_llm_client` and no synthesis or review stage exists (the Day-4 stage list is unchanged); `POST /assessments/{id}/syntheses` returns 409.

## 5. Fixture provenance

| Fixture | Source | Provenance field |
|---|---|---|
| `tests/fixtures/llm/stub_classifier.py` | deterministic keyword rules written from the taxonomy descriptions; no database, no ground truth | responses carry `stub_not_model_output`, model `stub:keyword_rules_v1` |
| `tests/fixtures/llm/recorded/synthesis_*.json`, `review_*.json` (8) | hand-authored from each scenario's real deterministic input after approval, with the injected faults (AI Coach: a causal overclaim; Pricing: a "no harm" claim) | `stub_not_model_output`, model `stub:handauthored_synthesis_v1` and `stub:handauthored_review_v1` |
| scripted clients (tests only) | queued texts and failures | `stub_not_model_output` |
| `scripts/record_llm_fixtures.py` | a future live recording (`recorded_model_output`), keyed by input hash for classification and by scenario with symbolic evidence selectors for synthesis and review | **not run on Day 5** |

Fixture evidence ids are symbolic selectors (`@customer:coach_helpful`, `@behavioral:comparison`) that `RecordedClient` resolves against the request's evidence index, because database ids are random per run. A hand-authored fixture is matched by purpose, prompt version and scenario; a recording by input hash. Because the reviewer fixtures are hand-written, the scenario tests prove the plumbing, the code-enforced severity and the code-derived verdict, **not** that a model finds these faults. The live Reviewer check is `@pytest.mark.llm` (skipped without a key).

## 6. E1: stub classifier vs ground truth (test-only read)

Measured by `tests/backend/test_day5_evals.py` over all 6,083 feedback rows (195 distinct texts). **This measures the pipeline and the stub, not a model.**

| Theme | Precision | Recall | Predicted | Actual |
|---|---|---|---|---|
| coach_helpful | 1.000 | 1.000 | 706 | 706 |
| coach_generic_or_wrong | 1.000 | 1.000 | 113 | 113 |
| coach_indifferent | 1.000 | 1.000 | 128 | 128 |
| challenges_motivating | 1.000 | 1.000 | 970 | 970 |
| notifications_unwanted | 1.000 | 1.000 | 184 | 184 |
| challenges_indifferent | 1.000 | 1.000 | 210 | 210 |
| setup_blocked | 1.000 | 1.000 | 325 | 325 |
| price_too_high | 1.000 | 1.000 | 1126 | 1126 |
| worth_the_price | 1.000 | 1.000 | 821 | 821 |

**Caveat (templated text).** The synthetic feedback has 195 distinct sentences for 6,083 rows, generated from a few templates per theme, and the stub's cues were written while those template sentences were visible. Perfect agreement is therefore expected and says nothing about real customer text or about any model. The stub only ever answers `direct`, so `relevance_observed` is 1.0 for every item. The model E1 (`test_e1_model_classification_precision_and_recall_per_theme_live`) is skipped without a key.

## 7. Observed DDI state per scenario after approval

Produced by the frozen engine for the stored facts; **no test asserts a band in advance** (each test recomputes `assess(facts)` and compares). First run = before approval, second = after approval of every proposed item.

| Scenario | Before approval (assessment 1) | After approval (assessment 2) |
|---|---|---|
| AI Coach | scored, high, 69.2 | scored, **high, 60.5** (three customer items active) |
| Community | insufficient evidence (min_items, min_types) | scored, **high, 66.5** (heterogeneity flag true) |
| Onboarding | insufficient evidence (min_items, min_types, success_metric_evidence, open_critical_dq) | **insufficient evidence**, same reasons: the open critical DQ issue still blocks. No number anywhere |
| Pricing | scored, critical, 100.0 | scored, **high, 73.7**; D4 score and inputs identical before and after (test C7) |

Reviewer outcome with the hand-authored fixtures: AI Coach `needs_rework` (the model wrote `warning` for the causal overclaim, code made it blocking); Community `ready`; Onboarding `ready` (the assessment stays insufficient); Pricing `needs_rework` (the injected "no harm" claim). The pre-approval synthesis of each scenario fails with `fixture_missing` (no fixture covers an assessment without the approved customer evidence), which also shows the failure path: the assessment is unchanged and the decision stays `assessed`.

## 8. API

New: `GET /decisions/{id}/customer-evidence`, `PATCH /evidence/{id}/approval`, `POST` and `GET /assessments/{id}/syntheses`, `POST /assessments/{id}/briefs`, `GET /briefs/{id}`. `POST .../pipeline-runs` now also returns `pending_approvals`, `synthesis` and `review`. Permissions: approval ba and product_analyst; re-synthesis and briefs pm and ba; the GETs are open to every demo persona (as every Day-3 read). Re-synthesis is 201 for a new version and 200 when the stored output is reused (same `input_sha256`, no `force`); it also creates the agent review. No generic agent endpoint exists (test G2).

## 9. Prior tests adjusted (each with its reason)

| Test | Change | Reason |
|---|---|---|
| `tests/backend/test_models_reflection.py` | 25 tables | three new tables |
| `tests/db/test_schema.py`, `test_migrations.py` | 25 tables, head `0006`, enum `customer_relevance` | migration 0006 |
| `tests/db/conftest.py`, `test_constraints.py`, `test_day3_guards.py`, `test_day4_schema.py`, `test_views.py`, `tests/backend/test_d6_descriptive_db.py`, `test_day4_evidence.py`, `day4_support.py` | claim inserts first create a synthesis (`new_synthesis`, `insert_synthesis`) | every new claim must name its synthesis (NOT VALID CHECK) |
| `tests/backend/test_day4_guards.py` | registry may also gain `analytics_params_v0.2`; v0.1 config tests load the v0.1 files explicitly; the `anthropic` scope allows `llm/anthropic_client.py` | v0.2 is the new default; Day-5 scope rule |
| `tests/backend/test_scope_guard.py` | `anthropic` allowed only in `llm/anthropic_client.py` | Day-5 scope rule (G2 checks it exactly) |
| `tests/backend/test_day4_pipeline.py` | customer outcome `skipped_no_llm_client` | the Day-4 `skipped_day5` stage text no longer applies |
| `pytest.ini` | `llm` marker registered | live tests are opt-in |

## 10. Known limitations and not done

- No live model call exists; real model behaviour (classification quality, synthesis grounding, reviewer recall) is unmeasured. Day 7 evaluation.
- The Reviewer fixtures are hand-authored: reviewer recall is not measured.
- The fixtures cover the approved state of the four scenarios; any other assessment gets `fixture_missing` in tests.
- Segment coverage and observed relevance are not DDI inputs (planned DDI v0.2).
- The stub's `adjacent` path and low-relevance themes are untested against real text.

## 11. Independent verification (Opus, 2026-10-05)

The implementing agent was stopped before its final report. Verification was redone independently from a clean state.

**Run:**
- Alembic `downgrade base` → `upgrade head` → `database.seed.run --regenerate` (50k users, 2.11M events, 6,083 feedback rows).
- `downgrade 0005` → `upgrade head`.
- Full suite: 662 passed, 2 skipped (live `@pytest.mark.llm`), 1 failed. The failure was a new acceptance probe, fixed as below.
- `git diff --stat 65caec6` over the frozen DDI/NBE code and config: empty.

**Acceptance probes added:** `tests/backend/test_day5_acceptance.py`. They cover:
- a wrong number ("42%") with a valid citation;
- a valid but irrelevant citation (wrong type, and a wrong scope for D4);
- mixed-stance citations;
- recommendation phrasing;
- extra classifier fields (for example `stance`), which fail the batch;
- the customer stance coming from the tenant map and the grade being C or D only;
- the stored assessment equalling the frozen engine;
- the database CHECK against approval bypass;
- approval being allowed for proposed items only;
- T2 (below).

**Fixed (P1):**
1. **V-SEM-STANCE was too weak.** A `supports` claim could cite a contradicting item next to a supporting one (and the reverse). The brief says a supports claim cites no contradicting item. Now mixed citations are dropped; mixed evidence must be a `neutral` claim. No fixture was affected.
2. **T2.** A decision_brief was allowed for a human-validated *insufficient* assessment. Now refused in the service and in the `ddr_decision_briefs_guard` trigger (migration 0006 edited before its first commit). The Gated Evidence Summary remains available.

**Documented, not fixed (P2):**
- V-NUM matches against every number in the DDI payload as well as the cited items, and ignores sign. A wrong number that happens to equal some DDI field (for example a contribution) passes, and so does "decreased 5%" against an effect of +5%. Candidate for Day 7: per-claim-type number sources and a sign check.
- Pricing moved from critical 100.0 to high 73.7 once its two customer items were approved. This is the frozen engine's output: D4 is unchanged, and the drop comes from the added customer evidence. Present it as such in the demo, never as the experiment becoming stronger.
- The judgement-based reviewer categories (an ignored contradicting segment, an ignored DQ issue, excessive certainty) are not measurable without a key. The deterministic validators catch unsupported citations, wrong numbers, causal-from-observational claims and recommendation phrasing.
- No frontend or Power BI (out of scope).
