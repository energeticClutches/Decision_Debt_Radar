# Day 7: Implementation Notes (evaluation, Power BI, documentation, demo)

Parent: [day-7-implementation-brief.md](day-7-implementation-brief.md) (binding). Baseline: commit `92cba81` (Day 6), Alembic head `0006` (no migration 0007), pytest 702 passed and 2 skipped, Vitest 70, Playwright 17, manifest 33/33. **FitConnect is a fictional company. All data is SYNTHETIC.** DDI is an evidence-risk heuristic, not a measure of decision quality.

> **Honesty statement.** No live model was called. Every model-behaviour item is reported as "not measured: no live model (replay fixtures are hand-authored)": reviewer recall and false flags, real classification accuracy, live schema validity, and the reviewer clauses of AC-4 and AC-5. Nothing in `backend/demo_fixtures/` or `tests/fixtures/llm/` was edited.

## 1. What was implemented (brief order)

1. **Evaluation specs and runner** (`tests/evals/`): 21 specs in `scenarios/*.yaml` (4 core, 6 PRD section 19 variants, 11 extra), all `synthetic: true`. `eval_runner.py` applies declarative mutations through the real API (the application in process), compares with the spec, recomputes the frozen engine (`assess(facts)`) and checks the golden snapshot. `test_eval_suite.py` runs one test per spec on rolled-back transactions, asserts the demo database row counts are unchanged, and writes `analytics/eval/results.json` and `results.csv`. `eval_harness.py` gives the scripts the same rolled-back session.
2. **Golden snapshot** (D7-01): `scripts/eval_snapshot.py --write` generated `tests/evals/golden/observed.json` (header: "observed frozen-engine output, recorded 2026-10-09, approved by PO at Day-7 verification"). No band was written into a spec; `band: golden` is the only value allowed. Never edited by hand.
3. **Mutation suite** (`tests/evals/mutations.yaml`, `mutations.py`, `test_mutations.py`): 22 flaw families, 61 instances, applied to valid syntheses built from the real payloads of the four scenarios, plus 4 clean controls. Result in `analytics/eval/mutation_results.json`.
4. **Metrics, report and spot-audit** (`scripts/eval_report.py`): `analytics/eval/metrics.json`, [evaluation-report.md](evaluation-report.md) (7 sections), [spot-audit.md](spot-audit.md) (5 deterministic sampled claims and every finding per core scenario, PO columns blank).
5. **Acceptance matrix** ([acceptance-matrix.md](acceptance-matrix.md)): AC-1 to AC-43.
6. **CSV export** (`scripts/export_reporting_views.py`): the 7 reporting views through `SET LOCAL ROLE ddr_readonly`, `decisions_lifecycle.csv`, `eval_metrics.csv`, `README.txt`. Deterministic (run twice, identical hashes).
7. **PBIP project** (`scripts/build_pbip.py` writes `analytics/powerbi/`): TMDL semantic model and PBIR report definition (4 pages), `visuals-spec.md`, `README.md`. See section 4.
8. **Small fixes (D7-06):** the V-NUM sign check (`validators.py`, only that hunk), the Pricing per-dimension version comparison (frontend), the AC-1 wording (PRD amended, dated 2026-10-10).
9. **Screenshots, README, demo script, preflight:** `frontend/e2e/screenshots.spec.ts` (on demand, 7 captures to `docs/screenshots/`), README rewritten (top section for a recruiter, existing technical sections kept below), [demo-script.md](demo-script.md), `scripts/demo_check.py` (read-only).
10. **Extra tests added:** `tests/backend/test_day7_sign_check.py` (15), `tests/backend/test_day7_demo_check.py` (2), `tests/db/test_day7_evidence_health.py` (2, AC-29), Vitest `tests/version-compare.test.tsx` (5), Playwright Pricing comparison and Onboarding no-comparison (2).

## 2. Evaluation metrics (actual numbers; synthetic data, no model)

| Metric | Result | Target | Status |
|---|---|---|---|
| DDI reproducibility | 21/21 specs | 100% | MET |
| Stored result equals recomputed engine | 20/20 (one spec is stale by design, its facts changed) | 100% | MET |
| Expected-state match, core / variants | 4/4 / 6/6 | 100% core | MET |
| Full spec pass (every expectation) | core 3/4, variants 6/6, extra 11/11 | report | one known gap (Community NBE) |
| Citation validity before / after filtering (specs) | 98.8% (84/85) / 100% (78/78) | post 100% | MET |
| Citation validity before / after (mutation suite) | 97.5% (354/363) / 100% (323/323) | post 100% | MET |
| SQL-guard pass rate (existing guard corpus, 74 tests) | 100% | 100% | MET |
| DQ seeded-defect recall (DEF-ONB-001, DEF-ONB-002) | 2/2 | >= 90% | MET |
| Golden-answer accuracy (analyses vs manifest, tolerance 0.005) | 11/11 | report | reported |
| Code-check recall (22 families, 61 instances) | 61/61 (100%); 58/61 before the sign check | report | reported |
| Code-check false-flag rate (4 clean controls) | 0/4 | report | reported |
| Reviewer recall and false flags | NOT EVIDENCED | >= 80% / <= 20% | not measured: no live model |
| Classification accuracy | stub only: precision and recall 1.0 on every theme (stub, not model output; 195 distinct sentences for 6,083 rows) | report | real model NOT EVIDENCED |
| Product KPIs (demo data) | coverage 4/4, insufficient rate 3/8 stored versions, traceability 22/22, quantitative claims with analysis 12/12, no decided decision | report | reported |

**Findings the evaluation produced (reported, not tuned):**
- **Community NBE gap.** The manifest expects `segment_level_analysis`; the frozen NBE excludes an action at or above its ceiling (D6 = 0.60 = the action's 0.6 ceiling), so it is not listed although the heterogeneity flag fires. Recorded as a `known_gaps` entry in `core_community` (a documented failed check). AC-5 is PARTIAL.
- **Community band.** The manifest's Day-1 expectation was *moderate*; the engine returns *high* (66.5). The snapshot records the engine output.
- **Wrong-sign claims were not caught** before D7-06 (mutation M13, 0 of 3); caught 3 of 3 after the sign check.
- Golden bands (engine output): AI Coach 60.5 high, Community 66.5 high, Pricing 73.7 high, Onboarding no DDI; variants: clean strong 47.1 moderate, contradictory 84.1 critical, stale 64.7 high.

## 3. Acceptance matrix summary

43 criteria: **33 PASS, 10 PARTIAL, 0 NOT EVIDENCED.** Not PASS:
- AC-1: the 7-stage list is asserted over the API only; no Playwright test drives the pipeline panel.
- AC-4: reviewer clauses NOT EVIDENCED (D7-05).
- AC-5: reviewer clause NOT EVIDENCED, and the NBE clause is NOT MET (the Community gap above).
- AC-15, AC-28, AC-43: the Power BI pages are not rendered yet (Desktop step).
- AC-16: setup evidenced by the fresh clone; "the Power BI file connects" not evidenced.
- AC-30: portfolio cards and the CSV show the DDI with its band but not the 7+2 rows (reported, not decided).
- AC-36: no test asserts the positioning label on the workspace DDI panel.
- AC-42: no test asserts that every criterion gets met, not met or not testable; real-model behaviour NOT EVIDENCED.

## 4. Power BI status

**Delivered: the PBIP project with a PBIR report definition (not the visuals-spec fallback).** Evidence for confidence: Power BI Desktop 2.158.1304 is installed on this machine and bundles its JSON schemas; I read them from the install folder and validated all 44 report JSON files against report 3.3.0, page 2.1.0, visualContainer 2.13.0, pagesMetadata 1.1.0 and versionMetadata 1.0.0 (JSON Schema draft-07, a throwaway venv outside the repo): 0 invalid. A negative test (an unknown key, a missing required property) was rejected. I did **not** open Desktop or use computer use.

Not verifiable without Desktop (what may need a fix on first open): the TMDL syntax (written from knowledge), the formatting-object names inside `objects` (`labels`, `dataPoint`, text-box `paragraphs`; the schema leaves them open), the M queries (`Csv.Document` typing with `en-US`), the calculated tables `Teams` and `DecisionTypes`, and the nine relationships. `analytics/powerbi/visuals-spec.md` describes every page, visual, field, measure and label so the visuals can be rebuilt by hand if the report definition is rejected.

**Left for the Desktop step (Opus, with the PO's approval):** open `analytics/powerbi/DecisionDebtRadar.pbip`; set the `DataFolder` parameter if the path differs; refresh; check every page, the footer "Synthetic data · DDI is an evidence-risk heuristic, not a measure of decision quality", the neutral colours, that no DDI value shows for the insufficient decision, and the Quality page rows; save `analytics/powerbi/DecisionDebtRadar.pbix`; take screenshots (AC-15, AC-28, AC-43). The CSV snapshot is current as of the final run.

## 5. Gate log (brief section 8, run in order)

| # | Step | Result |
|---|---|---|
| 1 | `alembic downgrade base`, `upgrade head`, `seed --regenerate`, manifest | 33/33 |
| 2 | Full pytest incl. `tests/evals` | **752 passed, 2 skipped (live LLM), 0 failed** (1114 s). `tests/evals` alone: 31 passed. First attempt: 750 passed and 2 failed, both fixed (see 7) |
| 3 | `demo_prepare` twice | first run 17 writes; second 0 writes, audit counts (17, 16, 10, 15) and versions [1, 2] unchanged |
| 4 | `export_reporting_views` twice | identical CSV hashes |
| 5 | Vitest | 75 passed (4 files + `version-compare`: 5 files) |
| 6 | `tsc --noEmit` | 0 errors |
| 7 | `next build` | success |
| 8 | Playwright (full run, reseeds) | **19 passed** (17 existing + Pricing comparison + Onboarding no-comparison). First run: 18 passed, 1 failed (my "D4 unchanged" compared contributions; D4's score and inputs are unchanged but its contribution is rescaled by the 100 cap in v1; the definition was corrected to score and inputs, with a Vitest case) |
| 9 | Screenshot spec | 7 passed, 7 PNGs in `docs/screenshots/` (two re-taken after a visual check) |
| 10 | `eval_report.py` | regenerated `evaluation-report.md`, `spot-audit.md`, `metrics.json` (after `demo_prepare --reset`) |
| 11 | Fresh-clone test | PASS, section 6 |
| 12 | Frozen-path diff vs `92cba81` | empty; `validators.py` only the sign-check hunk (+63, -1) |

The database is left in the prepared demo state. The `demo_prepare` tests and the eval specs need an unprepared database: run `python -m database.seed.run --reset` (or `--regenerate` after a downgrade) before `pytest`, as before.

## 6. Fresh-clone log (AC-16)

Clone of the local repository at committed `HEAD` (92cba81), into the scratchpad `fresh-clone`, following the **committed** README quickstart, with the Day-7 README checked afterwards. The README has no separate-database option, so the clone **reused the dev database** (`COMPOSE_PROJECT_NAME=decision_debt_radar` so `docker compose up -d db` found the running container).

| Command | Result |
|---|---|
| `git clone` | OK |
| `cp .env.example .env` | OK |
| `python -m venv backend/.venv` | **gap**: `python` was 3.14 and `pip install -e "backend[dev]"` refused ("requires 3.11 to 3.13") |
| `py -3.12 -m venv backend/.venv`, `pip install -e "backend[dev]"` | OK (imports with `PYTHONPATH="backend;."`) |
| `npm ci` (frontend) | OK, 0 vulnerabilities |
| `docker compose up -d db` | OK (existing container) |
| `alembic -c alembic.ini upgrade head` (from `database/`) | OK (at 0006) |
| `scripts/demo_prepare.py --reset` | OK: generated and loaded the data, four decisions prepared (17 writes), DDI 60.5 / 66.5 / INSUFFICIENT / 73.7 |
| `uvicorn` on 127.0.0.1:8000 and `npm run build` + `next start` on 127.0.0.1:3000 | OK |
| `GET /health` | 200, `llm_mode: replay` |
| `scripts/demo_check.py` (the Day-7 file copied in, as it is uncommitted) | first run FAIL on "database container" (the clone's compose project owns no container); fixed (a reachable 127.0.0.1:5432 passes); re-run 6 PASS |

Doc gaps found and fixed in the README: the Python version, and the preflight with a database owned by another project. The committed README had no `demo_check` step (new in Day 7). The clone's `node_modules`, venv and `.next` were deleted afterwards; ports 3000 and 8000 were freed.

## 7. Deviations and interpretations

1. **Known-gap mechanism.** The brief's closed `expect` keys have no way to record an honest unmet expectation. Specs may carry `known_gaps` (check name and reason): the check is reported as failed in `results.csv` (`pass=false`) and in the report, pytest requires it to keep failing and fails if it starts to pass. Only `core_community` uses it.
2. **Extra expectation key and property.** `expect.refusals` (for the approval-bypass attempt, which is not a state) and the property `ddi_not_lower_when_older` (the stale variant needs a meaningful assertion). Both are additions to the closed list.
3. **Golden content.** The snapshot stores state, DDI, band, blocking codes, NBE rank 1 and the parameter versions and hashes per spec (the brief says "band"). The drift test compares all of them.
4. **Injection variant.** Test-only exceptions to "no raw SQL on product tables": the Day-5 E3 insight row (ORM) and the approval-bypass attempt (a refused statement in a rolled-back savepoint). The compromised synthesis is a scripted output, so real-model resistance is not measured.
5. **Variant semantics.** "Onboarding with the DQ issue resolved" uses `PATCH /dq-checks` as the BA then the Day-3 assessment on the stored state; it stays INSUFFICIENT (no evidence exists). The extra `extra_dq_resolved_pipeline_reopens` shows that a pipeline re-run reopens the check.
6. **Clean strong-evidence variant** has no registered experiment record, so the engine runs D4 on defaults; it measures the engine, not an experiment (said in the spec).
7. **`decisions_lifecycle.csv`** has three extra columns (`team_id`, `open_critical_dq_issues`, `open_warn_dq_issues`) because the seven views expose no open-DQ count and the model needs team filtering. The CSV has no comment row; `README.txt` carries the label.
8. **Optional live mode** is a model parameter (`DataSource`) for the seven view tables only (decisions and eval tables stay CSV, because `ddr_readonly` is NOLOGIN and cannot read the decisions tables); untested and not the default.
9. **Pricing comparison.** "Unchanged" means score and inputs identical; contributions are shown in their own columns. Only a scored current assessment can be compared (a gated decision shows no contribution anywhere); an insufficient older version shows "no DDI".
10. **AC-1 wording.** PRD amended with a dated note; AC-1 stays PARTIAL because the UI stage display has no test.
11. **Existing test changed, with the reason:** `tests/db/test_views.py::test_v_agent_quality_aggregates_runs` now also filters `model='m'`. The test picked an arbitrary one of two `evidence_synthesis` groups (the `new_synthesis` helper adds a `stub:test` group), so its result depended on the query plan: it failed on the freshly rebuilt database both with and without the Day-7 changes. The assertion is unchanged and stricter, not weaker.
12. **Two guards met:** `test_g3_...never_name_the_ground_truth_table` forbids the table name in `scripts/`; `eval_report.py` reads the labels through the existing test helper instead.
13. **Spec count and E3 style.** 21 specs (the brief asks for at least 14, about 20).
14. **Screenshots** run on demand (`SCREENSHOTS=1`, `playwright.config.ts` ignores the file otherwise, so the default run stays at 19 tests); the last capture validates Community through the API, so the demo state must be restored afterwards.
15. **Nothing cut** from the brief's cut order (spot-audit, version comparison, variants, Quality page are all delivered).

## 8. Known limitations

- Replay output is hand-authored; reviewer, classification and schema behaviour of a real model are unmeasured.
- The Power BI project has not been opened in Desktop; TMDL and `objects` names are unchecked there.
- The spot-audit PO columns are blank (the PO fills them).
- AC-5's NBE clause is not met by the frozen NBE; AC-30 and AC-36 are open readings (section 3).
- Fresh-clone used the shared dev database.
- Python 3.14 is not supported by the backend.

## 9. Frozen-path diff

`git diff --stat 92cba81 -- backend/app/domain/ddi backend/app/domain/nbe backend/config backend/app/analytics backend/app/customer backend/app/services/lifecycle.py database/sql backend/demo_fixtures tests/fixtures/llm`: **empty**. `backend/app/synthesis/validators.py`: 63 insertions and 1 deletion, only the V-NUM sign check (`ClaimNumber` context fields, `signed_leaves`, `claim_sign`, `_close`, and the check in `check_numbers`).

## 10. Independent verification (Opus, 2026-10-10)

**Checked, no problem found:**
- the frozen paths (including both fixture folders) have no diff against `92cba81`;
- the only change to an existing test (`tests/db/test_views.py`) is a legitimate fix for a query that depended on row order;
- all 54 pytest node IDs cited in `docs/acceptance-matrix.md` exist;
- the evaluation report labels every model-behaviour item NOT EVIDENCED and every LLM-derived figure "stub, not model output".

**P0 found and fixed: the UI claimed "no review" and "no NBE" while still loading.**
- **Symptom.** The agent's `02-ai-coach-overview.png` showed "No automated adversarial review" and "No next-best-evidence action is listed" for AI Coach, which has a needs-rework review and 4 NBE actions. A DOM probe confirmed both claims for about 80 ms on every load, until the requests returned.
- **Same cause, two more effects:**
  - `useResource` keeps old data during a reload, so after a re-run the header could show the *previous* assessment's verdict;
  - a failed reviews request was shown as "no review".
- **Fix (`frontend/components/workspace/Workspace.tsx`):**
  - the workspace body renders only once the reviews, recommendations and syntheses of the **current** assessment have loaded (checked by `assessment_id`);
  - a failed load shows an error, never "no review".
- **Regression test:** `frontend/e2e/00-loading-trust.spec.ts`. A MutationObserver installed before any script runs fails the test if either claim ever appears.
- **Note:** the screenshot spec's "wait for NBE rows" in capture 05 was a test-side workaround for the same bug.

**Re-run after the fix:**

| Check | Result |
|---|---|
| Vitest | 75 passed |
| `tsc` | ok |
| `next build` | ok |
| Playwright | 20 passed: 19 + the new trust test |
| Screenshot spec | 7 passed; the 7 PNGs regenerated. 02 now shows "needs rework (1 blocking finding)" and the NBE table. |
| Demo state | restored with `demo_prepare --reset` |

Backend code was not touched after the agent's full pytest run (752 passed, 2 skipped).

**Power BI Desktop step (D7-04): not done.** The PO declined computer-use access to Power BI Desktop. The PBIP project is complete and its report JSON passes the bundled schemas, but it has **not been opened, refreshed or saved** as `.pbix`. AC-15, AC-16, AC-28 and AC-43 stay PARTIAL.

The manual steps for the PO:
1. Open `analytics/powerbi/DecisionDebtRadar.pbip`.
2. Set `DataFolder` if prompted.
3. Refresh, and check every footer and that no DDI is shown for Onboarding.
4. Save `DecisionDebtRadar.pbix`.
