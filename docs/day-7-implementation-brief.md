# Day 7 Implementation Brief: evaluation, Power BI, documentation and demo

**Status:** APPROVED (2026-10-09). The Day-7 design review was accepted, and the Product Owner (PO) approved every recommendation (D7-01 to D7-07). **No API key will be provided.** Everything here is binding. Where this brief is silent, choose the most conservative reading and record it in the Day-7 notes. Do not invent methodology.

**Baseline:** commit `92cba81` (Day 6), Alembic head `0006`, pytest 702 passed and 2 live tests skipped, Vitest 70, Playwright 17, manifest 33/33.

> Day 7 proves what was built and makes it presentable. It is not a feature day. **Honest reporting outranks a green table:** a criterion that is not evidenced is reported as NOT EVIDENCED, never made to pass.

---

## 0. Hard rules

- **Frozen code: zero diff against `92cba81`** in:
  - `backend/app/domain/ddi/**`, `backend/app/domain/nbe/**`, `backend/config/**`;
  - `backend/app/analytics/**`, `backend/app/customer/**`, `backend/app/services/lifecycle.py`;
  - `database/sql/**` (no migration 0007).
- **One exception:** `backend/app/synthesis/validators.py` may change **only** for the V-NUM sign check (§5).
- **Fixtures are frozen.** Never edit `backend/demo_fixtures/**` or `tests/fixtures/llm/**` to make a criterion or metric pass. Editing them would fabricate evidence of model behaviour.
- **No new product features** beyond §5. No authentication, hosting, new agents, new lifecycle states or background workers.
- **No live LLM call** (no key). Every model-behaviour metric is reported as **"not measured: no live model (replay fixtures are hand-authored)"**.
- **The evaluation never pollutes the demo database.** Variants run inside pytest transactions on cloned decisions and are rolled back.
- **Labels everywhere:** every output (report, CSV, Power BI page, screenshot caption) is labelled "Synthetic data". Anything derived from the LLM is also labelled "stub, not model output".
- Do not commit or push. Write UTF-8 without a BOM.

## 1. Approved decisions

| # | Decision |
|---|---|
| D7-01 | **No band is chosen in advance. The engine's observed band is recorded as a golden snapshot.** <ul><li>Each eval spec's band field is filled from the **observed engine output**, stored in `tests/evals/golden/observed.json` with a header ("observed frozen-engine output, recorded <date>, approved by PO at Day-7 verification").</li><li>The tests check two things: the stored result equals `assess(facts)` recomputed, **and** it equals the snapshot (drift detection).</li><li>To regenerate the snapshot, run `scripts/eval_snapshot.py --write`. Never edit it by hand.</li></ul> |
| D7-02 | **No key. Model-behaviour items are reported as NOT EVIDENCED:** <ul><li>reviewer recall and false-flag rate;</li><li>real classification accuracy;</li><li>the reviewer clauses of AC-4 and AC-5;</li><li>live schema validity.</li></ul> Keep the `@pytest.mark.llm` harnesses, skipped. |
| D7-03 | **Power BI reads a CSV snapshot:** `scripts/export_reporting_views.py` writes `analytics/powerbi/data/*.csv`. An optional model parameter switches to live PostgreSQL through `ddr_readonly`; that path is documented, not the default. |
| D7-04 | **The report is a PBIP project** (TMDL semantic model plus report definition) in `analytics/powerbi/`, written as text by the implementer. **Opus then opens, refreshes, checks and saves the `.pbix` in Power BI Desktop through computer use**, at verification and with the PO's on-screen approval. The implementer does not drive the desktop. |
| D7-05 | **AC-4 and AC-5 are reported PARTIAL.** The deterministic clauses are evidenced; the reviewer clauses are NOT EVIDENCED. |
| D7-06 | **Small fixes are approved:** <ul><li>the Pricing per-dimension version comparison;</li><li>the V-NUM sign check;</li><li>the AC-1 wording ("7 dimensions and 2 penalties").</li></ul> |
| D7-07 | **The portfolio keeps the four honest decisions.** Evaluation variants never enter the demo database. |

## 2. Evaluation suite (`tests/evals/`)

**Specs:** `tests/evals/scenarios/*.yaml`, at least 14 and aiming for about 20. Each is marked `synthetic: true`.

| Group | Specs |
|---|---|
| **Core (4)** | AI Coach, Community, Onboarding, Pricing, after approval (the demo path) |
| **PRD §19 variants (6)** | <ul><li>Onboarding with the data-quality issue resolved (through `PATCH /dq-checks`, as a BA);</li><li>a clean strong-evidence decision;</li><li>an empty-evidence decision;</li><li>a contradictory-evidence variant;</li><li>a stale-evidence variant (as-of date moved forward);</li><li>injection text in customer feedback (test-only rows outside `fc_`, as in Day-5 E3).</li></ul> |
| **Extra (aim for about 10)** | <ul><li>customer evidence rejected;</li><li>customer evidence left proposed (it stays out of the facts);</li><li>the reviewer failing (`review_failed`);</li><li>malformed synthesis output (the repair, then `failed`);</li><li>a canvas edit after assessment (stale);</li><li>a needs-rework override path;</li><li>a decided record that freezes writes;</li><li>the gated summary path;</li><li>defer (stale);</li><li>an approval bypass attempt (refused by the database).</li></ul> |

**Each spec states:**
- `base_scenario` and `mutations` (declarative steps the runner applies through **services or the API only**, never raw SQL on product tables);
- `expect`:
  - `state`, and `blocking_reasons` (an exact set);
  - `band: golden` (D7-01), or `no_ddi: true`;
  - `nbe_must_include` and `nbe_rank1`;
  - `code_findings_must_include` (validator rules and critic categories);
  - `lifecycle`;
  - `properties`, from a closed list the runner implements: `d4_unchanged`, `no_ddi_number`, `proposed_excluded_from_facts`, `stance_from_map`, `review_not_ready`, `writes_frozen`.

**Runner:** `tests/evals/test_eval_suite.py` parametrises over the specs. It writes per-spec results to `analytics/eval/results.json` and `analytics/eval/results.csv` (columns: spec, group, expected, observed, pass, notes, synthetic).

**Mutation suite for code-check recall:** `tests/evals/mutations.yaml`, about 20 seeded flaws applied to valid syntheses built from real payloads:
- unsupported claim;
- unknown ID and foreign-decision ID;
- valid but irrelevant citation;
- mixed-stance citation;
- invented DDI, percentage, effect, p-value, CI or sample size;
- a wrong sign;
- causal claim from observational evidence;
- a recommendation ("Management should…");
- "sufficient" text while gated;
- an omitted contradiction;
- an ignored critical data-quality issue;
- high confidence on grade C/D evidence.

Each flaw records which layer must catch it (validator rule or critic category). Also run **clean controls** (valid syntheses for the four scenarios) to measure the code-check false-flag rate.

**Metrics:** `scripts/eval_report.py` runs the suite (or reads `results.json`) and writes `analytics/eval/metrics.json` and `docs/evaluation-report.md`.

| Metric (PRD §17/§19) | How | Target |
|---|---|---|
| DDI reproducibility | run the same facts twice through the engine, per spec | 100% |
| Expected-state match | core + variants vs spec | 100% core |
| Citation validity before and after filtering | validator reports over specs and mutations | post 100% |
| SQL-guard pass rate | the existing guard test corpus (renamed from "SQL validity": no LLM SQL by design) | 100% |
| Data-quality seeded-defect recall | manifest defects vs open DQ checks | ≥ 90% |
| Golden-answer accuracy | analyses vs manifest values within tolerance | report |
| Code-check recall and false-flag rate | mutation suite and clean controls | report; no target set |
| Reviewer recall and false flags | **NOT EVIDENCED** (no live model) | n/a |
| Classification accuracy | stub vs ground truth, **labelled "stub, not model"**, with the templated-text caveat | report |
| Product KPIs (§17) | from the demo database after `demo_prepare` and the eval runs: coverage, insufficient-evidence rate, acknowledged-risk decisions, traceability rate | report, labelled "demo data" |

**`docs/evaluation-report.md` sections:**
1. scope and honesty statement;
2. method;
3. results tables;
4. failures and not-evidenced items;
5. the stub and templated-data caveats;
6. how to reproduce;
7. the version and hash of every parameter set and prompt.

**`docs/spot-audit.md`:** for each core scenario, 5 sampled stored claims and every finding, with blank PO columns (`agrees`, `note`). The implementer never fills those columns.

## 3. Acceptance matrix (`docs/acceptance-matrix.md`)

AC-1 to AC-43, including §23.4, §24.6, §25.4 and §26.5. Each row has:
- the criterion;
- a status: PASS, PARTIAL or NOT EVIDENCED;
- the evidence: test node IDs, Playwright spec, screenshot, document section;
- notes.

- **AC-4 and AC-5 are PARTIAL** (D7-05).
- **AC-16 rests on the fresh-clone test** (§7).
- **AC-15 and AC-43 rest on the Power BI pages and the screenshots.**
- A criterion is never PASS without linked evidence.

## 4. Power BI (`analytics/powerbi/`)

**Data:** `scripts/export_reporting_views.py` writes:
- the 7 reporting views (`v_debt_radar`, `v_evidence_health`, `v_evidence_freshness`, `v_coverage_checklist`, `v_nbe_ranking`, `v_traceability_matrix`, `v_agent_quality`);
- `decisions_lifecycle.csv` (from the decisions table: title, team, type, stage, stale, latest assessment state, band, as-of date);
- `eval_metrics.csv`.

Each CSV has an `is_synthetic` column and a header comment row only if Power BI can skip it; otherwise use a `README.txt`. The export runs after `demo_prepare` and is deterministic for a given database state.

**PBIP project** (`DecisionDebtRadar.pbip`, `*.SemanticModel/`, `*.Report/`):
- **Model:** tables from the CSVs through a `DataFolder` parameter (default `analytics/powerbi/data`, absolute path documented). Relationships on `decision_id`. Measures:
  - number of decisions;
  - scored, insufficient and stale counts;
  - average DDI of scored decisions only;
  - number of open critical DQ issues;
  - decided while High/Critical/insufficient;
  - days since the last assessment.
- **Pages:** each has a footer: "Synthetic data · DDI is an evidence-risk heuristic, not a measure of decision quality".
  1. **Portfolio debt:** DDI by band; debt by team and decision type; insufficient count; the decided-while-high-risk table.
  2. **Evidence health:** freshness distribution, coverage checklist, open data-quality issues.
  3. **Lifecycle and NBE:** stage per decision, time since the last assessment, the NBE ranking.
  4. **Quality:** `eval_metrics` and `v_agent_quality`, with "stub, not model output" on LLM-derived figures and NOT EVIDENCED rows shown as such.
- **Never show a DDI value for an insufficient decision.** A neutral scale for bands, with text labels (no red/green verdict).
- **Format:** keep it to report definitions Power BI Desktop 2.158 opens: use the PBIR / report JSON format that version supports. Document the format and version in `analytics/powerbi/README.md`. If the report-definition format proves unreliable, deliver the semantic model plus a page and visual specification (`visuals-spec.md`) and record it as a deviation. Opus then builds the visuals in Desktop at verification (D7-04).

**Opus verification step** (not the implementer): open the `.pbip` in Desktop, refresh from the CSVs, check every page and label, save `analytics/powerbi/DecisionDebtRadar.pbix`, and take screenshots of the pages.

## 5. Small fixes (D7-06)

1. **Pricing version comparison** (frontend only, stored data only):
   - in the Assessment tab version history, choosing a superseded scored version shows a per-dimension table (score, contribution, inputs, previous vs current) and the penalties;
   - insufficient versions show "no DDI" and never a number;
   - Vitest covers the "no number for insufficient" rule; Playwright Pricing shows D4 unchanged between v1 and v2.
2. **V-NUM sign check** (`validators.py`): a number in a claim that carries an explicit sign or direction word ("decreased", "lower", "fell", or a leading "-" or "+") must match the sign of the candidate value it matched, where that value is signed (effect, CI bounds).
   - Unsigned candidates (counts, n, DDI) are unaffected.
   - Tests: "decreased 5%" against +5% is dropped; "increased 23.0%" against +0.230 passes.
   - The Day-5 fixtures must still pass (verify; never edit them).
3. **PRD AC-1 wording:** "a DDI with its 7-dimension and 2-penalty breakdown". Add a dated note.

## 6. Demo, documentation, screenshots

- **README rewrite** (top section for a recruiter):
  - the one-line idea ("AI deliberately constrained from making the decision");
  - an architecture diagram (Mermaid or ASCII);
  - a quickstart (`demo_check`, then `demo_prepare --reset`, then start both servers);
  - 4 to 6 screenshots;
  - an "Honest limitations" box (synthetic templated data, no live model, replay fixtures, DDI as a proposed heuristic);
  - links to the evaluation report, the acceptance matrix, the demo script and the Power BI folder.

  Keep the existing technical sections below it.
- **`docs/demo-script.md`:** the 5-minute path (AI Coach, then Onboarding, Community and Pricing in brief), the talking point for each screen, and what *not* to claim. For example: "replayed fixtures, not live AI"; "Pricing's drop came from customer evidence".
- **Screenshots:** `frontend/e2e/screenshots.spec.ts` (tagged so it runs on demand) captures the portfolio, AI Coach overview, "Why this score?", the review tab, the Onboarding gate card, customer evidence, and the brief, into `docs/screenshots/*.png` with fixed viewport and theme. Captions in the README are labelled synthetic.
- **`scripts/demo_check.py`:** a preflight that checks:
  - Docker is running and the database container is healthy (127.0.0.1:5432);
  - Alembic is at head;
  - the seed is present (manifest row counts);
  - the demo state (the four target stages);
  - API `/health` (and `llm_mode`) and the frontend respond (if running).

  Each check prints PASS/FAIL and the exact fix command. It is read-only.

## 7. Fresh-clone setup test (AC-16)

Clone the repository from the local path into a temporary folder in the scratchpad, follow the README quickstart **exactly**, and record each command and its result in the Day-7 notes:
- the environment setup;
- `npm ci`;
- the migrations, the seed and `demo_prepare`;
- both servers start;
- `/health` responds.

Any doc gap found is fixed in the README, then re-verified. Use a separate database name only if the README supports it; otherwise reuse the dev database and say so.

## 8. Tests and acceptance gate

Run, in order:
1. A clean rebuild: `downgrade base`, `upgrade head`, `seed --regenerate`, manifest 33/33.
2. The full pytest suite, including `tests/evals`.
3. `demo_prepare` twice (idempotency).
4. `export_reporting_views` (deterministic: run twice, identical CSVs).
5. Vitest.
6. `tsc`.
7. `next build`.
8. Playwright (the 17 existing tests plus the Pricing comparison).
9. The screenshot spec.
10. `eval_report.py` (report regenerated).
11. The fresh-clone test.
12. The frozen-path diff against `92cba81` (§0): empty, except `validators.py` with only the sign-check hunk.

Then write `docs/day-7-implementation-notes.md`:
- what was implemented;
- the eval metrics table;
- the acceptance-matrix summary (counts of PASS, PARTIAL, NOT EVIDENCED);
- the Power BI status (what is left for Opus's Desktop step);
- the fresh-clone log;
- deviations;
- known limitations;
- the frozen-path diff.

Update the README status: "Day 7 of 7".

**Order:**
1. eval specs and runner;
2. the mutation suite;
3. metrics, the evaluation report, the spot-audit sheet;
4. the acceptance matrix;
5. the CSV export;
6. the PBIP project;
7. small fixes;
8. screenshots;
9. README, demo script, `demo_check`;
10. fresh-clone test;
11. gate;
12. notes.

**Cut order if behind:**
1. the spot-audit sheet;
2. the version-comparison view;
3. eval variants beyond the core 4 plus 6;
4. the Power BI Quality page (keep pages 1 to 3).

**Never cut:** the Power BI report, the four core scenarios, the acceptance matrix or the honest reporting.
