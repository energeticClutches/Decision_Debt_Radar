# Day 3: Implementation Notes

Parent: [day-3-implementation-brief.md](day-3-implementation-brief.md) (binding), [DDI-spec.md](DDI-spec.md), [NBE-spec.md](NBE-spec.md), [decision-lifecycle.md](decision-lifecycle.md). **FitConnect is a fictional company. All FitConnect data is SYNTHETIC.**

Scope: the deterministic business-logic foundation. Day 3 **consumes** stored evidence, experiment statistics and DQ results. It computes no analytics, calls no LLM, builds no agents, no SQL guard, no brief, no frontend and no Power BI.

## 1. Architecture

```
backend/app/
  core/          config, params (loader + hash check), clock (injectable), errors (HTTP mapping), deps (session, demo identity, services)
  domain/        facts.py (EvidenceFacts), ddi/ (params, scoring, aggregate, sensitivity, engine), nbe/ (params, engine),
                 lifecycle.py, permissions.py, canvas.py, errors.py          <- no sqlalchemy / fastapi / psycopg imports
  db/            models.py (mirror of the live schema, 22 tables), session.py, csv_loader.py (Day 2)
  repositories/  one module per aggregate + evidence_facts.py (EvidenceFacts builder and evidence fingerprint)
  services/      decisions, evidence, assessments, reviews, decision_records, recommendations, dq, audit, lifecycle, base (unit of work)
  schemas/       requests.py, responses.py (presenters)
  api/routes/    system, decisions, assessments
```

Rules: SQLAlchemy 2.0 synchronous; `Base.metadata.create_all` is never called (a test scans the code base); only services open transactions (a test checks that repositories, domain and API contain no commit/begin/rollback); the DDI/NBE engines never read the clock (the as-of date is injected, a test checks the domain for wall-clock calls); the Day-2 placeholder packages `backend/app/engines/` were removed and `app.config` re-exports `app.core.config`.

## 2. Product Owner decisions (R1-R14) and the clarifications of 2026-10-02: where implemented

| Decision | Implementation |
|---|---|
| R1 meaning of DDI | `DdiResult.positioning` text; an evidence-direction summary is computed beside the DDI and never read by it (tests 33-37) |
| R2 cap reconciliation | `aggregate.finalize`: contributions scaled by 100 ÷ uncapped; `cap_applied`, `uncapped_ddi` stored |
| R3 bands, rounding | round half up to one decimal first, then band; the YAML critical band is `max_inclusive: true`; largest-remainder allocation of displayed contributions |
| R4 EvidenceFacts | `domain/facts.py` immutable dataclasses; `repositories/evidence_facts.py` builds them; engine takes facts + params + injected `as_of`; every default is reported as structured `defaulted_inputs` |
| R5 assessment execution | one insert of the completed row; no "running" state; DQ gate rules (open blocks, accepted warns, resolved ignored; earlier versions of the same decision stay relevant) |
| R6 concurrency | `SELECT ... FOR UPDATE` on the decision, evidence fingerprint captured, facts built, results calculated, fingerprint re-verified, 409 if changed |
| R7 current assessment | highest version including partial; previous scored version returned separately (`previous_scored_assessment`, `historical: true`) |
| R8 NBE applicability | rule per action, thresholds in `nbe_params_v0.1.yaml` `applicability` |
| R9 potential reduction | D2 improvement when a missing checklist type is supplied; D6 cap lift by the holdout; floored at 0; actions at their ceiling excluded; `clears_heterogeneity_floor` removed |
| R10 insufficient NBE | `recommendations.blockers_resolved`; `expected_reduction = 0`; the API reports `impact_unit` |
| R11 NBE timing/versioning | no Reviewer relevance; NBE version and hash stored; loader verifies the NBE file references the active DDI version |
| R12 human review/override | `POST /assessments/{id}/reviews`; override rules in section 7 |
| R13 migration 0004 | canvas edit stale rule (inside `ddr_decision_lifecycle_guard`), decided-write guards, `assessed` requires a row |
| R14 role switcher | header `X-Demo-User`; role and team read from the database; not authentication |
| Clarification 1 | direction rule: `min_total_weight` withdrawn, `min_direction_bearing_items: 2` added, output contract with `supporting_share`, `contradicting_share`, `neutral_share`, `direction_basis_weight`, `threshold`, `direction_bearing_items` |
| Clarification 2 | P1 recorded as a methodology change: quality-adjusted (weight includes `dq_factor`), neutral excluded |
| Clarification 3 | defaulted inputs are `{name, value, source: "observed" | "default", default_reason}`; each dimension has `inputs[]` and `defaulted_inputs[]` |
| Clarification 4 | code uses `priority = relevance * potential_ddi_reduction / effort_days`; the repository maps it to the column `expected_reduction` |
| Clarification 5 | trigger `ddr_assessment_immutable` rejects updates of the protected columns |

## 3. Parameters and hashes

`ddi_params_v0.1.yaml` and `nbe_params_v0.1.yaml` were amended in place **before any assessment used them**. Their SHA-256 (of the file bytes) is recorded once in `backend/config/params_hashes.json`. `app.core.params` raises `ParamsError` if the file is missing, unregistered, edited after registration, has a `version` field that differs from the requested version, or (NBE) references a DDI version other than the active one. Assessments store `params_version`, `params_hash`, `nbe_params_version`, `nbe_params_hash` and `as_of_date`. `.gitattributes` marks the YAML files `-text` so line-ending conversion cannot change a hash.

| File | SHA-256 |
|---|---|
| `backend/config/ddi/ddi_params_v0.1.yaml` | `fd2541522b34f0fa2344076048f656fee8df8e9023148445fe53b3c7c119bcee` |
| `backend/config/nbe/nbe_params_v0.1.yaml` | `8a7c730edb77fc7b7f69cce487bce99fba5ace660f1c028c8cb6692221546ff7` |

DDI additions: `bands.critical.max_inclusive`, `small_n_threshold`, `behavioral.materiality_threshold`, `behavioral.n_required`, `customer.default_relevance`, `customer.default_segment_coverage`, `experiment.default_power_factor`, `experiment.default_informativeness`, `financial.quantified_estimate_rule`, `financial.sensitivity_range_rule`, `uncertainty.ci_component_when_effect_zero`, `uncertainty.hhi_normalization`, `direction.majority_share`, `direction.min_direction_bearing_items`. NBE additions: `applicability.*` thresholds, per-action `supplies_evidence_type`, `resolves_blockers`, `d6_cap_lift_when_d4_at_least`; `clears_heterogeneity_floor` removed.

## 4. Migration 0004 (`database/sql/0004_day3_assessment_and_guards.sql`)

- `decision_assessments`: `params_hash` NOT NULL, `nbe_params_version`, `nbe_params_hash`, `evidence_fingerprint` NOT NULL, `as_of_date` NOT NULL (existing rows backfilled before the defaults are dropped).
- `recommendations.blockers_resolved integer NOT NULL DEFAULT 0 CHECK (>= 0)`.
- `ddr_decision_lifecycle_guard` replaced in place: canvas edit after the lock sets `assessment_stale` and returns to `evidence_gathered`; entering `assessed` requires a non-partial assessment row.
- Decided-write guards (INSERT/UPDATE/DELETE) on `evidence`, `decision_assessments`, `recommendations`, `decision_reviews`, `dq_checks`, `analysis_results`, `claims`, `claim_evidence`, `agent_runs`. The guard takes `FOR SHARE` on the decision row, so a concurrent writer waits for an in-flight decision and then sees its result. `audit_logs` is not guarded.
- Assessment immutability trigger.
- `0004_..._down.sql` restores the 0001 guard function and removes everything above. The migration test upgrades from empty, downgrades to base and upgrades again.

## 5. Methodology as implemented

**DDI.** `Support = sum_k w_k D_k` over applicable dimensions (equal weights renormalized), `Penalty = 1 + 0.5 P1 + 0.25 P2`, `uncapped = 100 (1 - Support) Penalty`, displayed `= round1(min(100, uncapped))`. Dimension contribution `100 (1 - D_k) w_k`; penalty contribution `(sum of dimension contributions) x coefficient x P`. The three breakdown stores are `dimension_scores` (top level: `ddi_display`, `uncapped_ddi`, `cap_applied`, `band`, `params_version`, `params_hash`, `as_of_date`, `dimensions`, `what_drove_this_result`, `evidence_direction`, `warnings`), `penalty_scores` and `sensitivity` (base, min, max, count 2K+6, unchanged-band share, `band_stable`, `label`, most influential perturbation, every run). Non-applicable dimensions are reported as "Not applicable". An INSUFFICIENT assessment stores no dimension breakdown, no band and no sensitivity.

**Judgement calls inside unspecified detail** (all documented in DDI-spec section 3.2 and flagged here for the Product Owner):
1. D6 (Behavioral Evidence Strength) aggregates ALL behavioral items on the success metric, regardless of stance (PO correction at Day-3 acceptance) by the **mean** of adequacy x materiality (consistent with the "mean over items" of D1 and D3). D4 and D7 use the **best** item.
2. D5 uses only insights reached through `evidence.insight_id`. Customer evidence without a linked insight scores 0 on D5 and is flagged as defaulted. Segment coverage and relevance are always defaulted on Day 3 (no column exists).
3. An unknown SRM result (`srm_flag` is null) is treated conservatively as failed (integrity 0.3) and flagged as defaulted. Achieved power is never stored on Day 3, so the power factor is always defaulted.
4. An item's DQ factor is the worst severity among its data source's **open and accepted** DQ checks. Accepted checks do not block scoring (R5) but the issue still lowers the item's `dq_factor`. Resolved checks are ignored.
5. DQ checks are scoped to the assessments of the same decision (the table has no other link).
6. **Resolved at acceptance:** D6 is stance-agnostic (it previously counted only supporting behavioral items). Flipping stance leaves D6 and every other dimension and P2 unchanged. The DDI changes only through P1, and the direction label may change. Tests: `test_d6_*` in tests/backend/test_direction_and_defaults.py. Also added at acceptance: a BEFORE DELETE guard on decision_assessments (assessments can never be deleted, tests in tests/db/test_day3_guards.py) and an explicit READ COMMITTED pin for the assessment transaction (engine-level in app.db.session, applied per transaction when possible and always verified, tests in tests/backend/test_concurrency.py).

**Monotonicity invariant (test 9) and its scope.** Tested: improving an attribute (tier, grade, DQ status, recency, n_sample) of an existing item never increases the DDI, all else equal. This holds for supporting and neutral items for every attribute, and for any item's `n_sample`. For a **contradicting** item, a higher tier, grade, recency or DQ status raises its weight and therefore P1, which is exactly what the P1 definition and golden test 38 specify (a critical-DQ contradicting item adds less contradiction weight). So those attributes cannot be monotone for contradicting items. The suite asserts the property where it holds and asserts the contradicting-item behavior explicitly (`test_09b`). **This is a conflict between the literal wording of test 9 and the approved P1 definition, reported to the Product Owner.**

**Evidence direction.** See DDI-spec section 14. Stored in `dimension_scores.evidence_direction`, returned next to the DDI. A test flips every stance and asserts D1-D7 and P2 are unchanged and only P1 and the direction move, and another test changes the direction parameters and asserts an identical DDI.

**Sensitivity.** 2K weight runs (x0.5, x1.5, renormalized) + 6 penalty-coefficient runs (both together, each separately). Base excluded from the count, included in min/max. Bands of perturbations use the round-then-band rule. `band_stable` is true when the share of unchanged bands is at least 0.9 (inclusive).

**NBE.** Applicability, relevance, the insufficient-state blocker map and the updated worked example are in NBE-spec. Implementation notes: actions are scored by recomputing the aggregation with the targeted dimensions at their ceilings (`fix_dq_or_instrumentation` re-runs the full DDI computation with the affected data source's items restored to `dq_factor` 1.0); an action is excluded when none of its targeted quantities changes; in the insufficient state only actions that resolve at least one blocker are listed, and an action that resolves `success_metric_evidence` has relevance 1.0 (it targets the success metric's evidence). `recommendations.description` stores the catalog description, a newline and `Why this: ...`; the API splits them.

## 6. Lifecycle, services and audit

See [decision-lifecycle.md](decision-lifecycle.md) section 8 for the rules, permissions and audit events. Additional detail:
- **Override (R12/BR-13).** A human review stores a verdict and a reason. `validate` needs the latest review to be `ready`; if any review of the assessment was `needs_rework`, the latest must be a human review with a non-empty reason, and the audit event is `assessment.override`. A `ready` after a `needs_rework` without a reason is rejected (422), a human `needs_rework` needs a reason, and an unresolved `needs_rework` blocks validation (409).
- **Stale on DQ status change.** Resolving or accepting a DQ check after an assessment makes the assessment stale and returns the decision to `evidence_gathered` (the DQ gate and every `dq_factor` depend on it, and journey J5 needs a re-run).
- **Concurrency.** Evidence and DQ writes lock the decision row, so they serialize behind a running assessment instead of racing it. The fingerprint check covers changes that do not take that lock (for example a stored statistic, a source tier or a customer insight). Both paths are tested on a scratch database with real commits: a change between snapshot and insert gives 409 and no assessment; an evidence edit waits for the assessment and then marks it stale; two concurrent runs give one assessment and one clean rejection.
- **Rejections.** A state conflict or a refused persona on a lifecycle operation is rolled back and logged as `transition.rejected` in its own transaction.
- **Record ownership.** "The decision owner" may record the decision whatever their role.
- **Evidence update.** The service supports changing an evidence item (`evidence.updated`, stale handling) but, to keep to the approved API list, there is no endpoint for it.

## 7. API

`GET /health` · `GET /users` · `GET /me` · `POST /decisions` · `GET /decisions` · `GET /decisions/{id}` · `PATCH /decisions/{id}/canvas` · `POST /decisions/{id}/confirm-evidence` · `POST /decisions/{id}/evidence` · `GET /decisions/{id}/evidence` · `POST /decisions/{id}/assessments` · `GET /decisions/{id}/assessments` · `GET /assessments/{id}` · `GET /assessments/{id}/recommendations` · `PATCH /recommendations/{id}` · `POST /assessments/{id}/reviews` · `POST /decisions/{id}/validate` · `POST /decisions/{id}/decision-record` · `PATCH /dq-checks/{id}` · `GET /decisions/{id}/audit`.

Identity: `X-Demo-User: <user uuid>`; missing or unknown 401, not permitted 403, not found 404, state conflict 409, invalid input 422. Database constraint and trigger errors are translated (unique, trigger-raised check or integrity violations, `RAISE EXCEPTION`: 409; table CHECK, NOT NULL, foreign key, malformed input: 422); error body `{"error": {"code", "message", "detail"}}`. A numeric DDI appears only for `scored` assessments: for insufficient or partial assessments `ddi`, `band`, `uncapped_ddi`, `support`, `penalty_multiplier` and `sensitivity` are null and `dimensions`/`penalties` are empty.

Run: `PYTHONPATH=backend:. backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000`, then `GET /users` for the role-switcher list. Optional `DDR_AS_OF_DATE=2026-10-01` fixes the as-of date for reproducible demos. Seeded decisions have no evidence, so an assessment correctly returns INSUFFICIENT EVIDENCE with its blockers and the "unblock scoring" actions.

## 8. Tests (all 40 required tests, plus extras)

Full suite after Day 3: **262 passed** (the Day-2 suite had 67 tests, not the 65 stated in the Day-2 notes; 195 are new). Plus the 33 manifest checks (`python -m database.seed.validate`). Verified from an empty database: `alembic downgrade base`, `upgrade head`, `database.seed.run --regenerate`, `database.seed.validate`, `pytest`.

| Test no. | Where |
|---|---|
| 1-12, 33-35 | `tests/backend/test_ddi_engine.py` |
| 13 | `tests/backend/test_params_loader.py` |
| 14-18 | `tests/backend/test_nbe_engine.py` |
| 19, 20, 22-25 | `tests/backend/test_lifecycle_services.py` (every one of the 30 stage pairs, service and database) |
| 21 | `tests/backend/test_concurrency.py` (scratch database) |
| 26-30 | `tests/backend/test_api.py` |
| 31 | `tests/backend/test_models_reflection.py` |
| 32 | `tests/backend/test_scope_guard.py` |
| 36-39, NBE naming | `tests/backend/test_direction_and_defaults.py` |
| 40, migration-0004 invariants | `tests/db/test_day3_guards.py` |

Day-2 tests changed only where migration 0004 legitimately changes behavior: inserts into `decision_assessments` now supply the new NOT NULL columns; fixtures create the assessment row before the decision enters `assessed` (R13c); the migration test expects revision `0004`.

## 9. Known limitations and not done
- No DQ computation, no heterogeneity detection, no statistical power: those inputs are absent or defaulted (and reported as such) until Day 4.
- Partial assessments are produced by Day 4. Day 3 reads and exposes them and tests them with rows inserted directly.
- `transition.rejected` is logged for lifecycle operations (state conflicts and refused personas), not for validation errors.
- The model is a heuristic with no calibration (see DDI-spec section 12).
