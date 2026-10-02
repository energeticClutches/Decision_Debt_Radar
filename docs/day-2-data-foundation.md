# Day 2: Database and Synthetic Data Foundation

Parent: [PRD-v0.1.md](PRD-v0.1.md) §14, [ERD.md](ERD.md). **FitConnect is a fictional company. All FitConnect data is SYNTHETIC.**
Scope: schema, migrations, synthetic data, manifest, reporting views, seed and verification. No DDI/NBE calculation, SQL guard, agents, LLM calls, analytics, frontend or Power BI.

## Rebuild from an empty PostgreSQL 16 instance

```bash
cp .env.example .env                                  # local placeholders only
docker compose up -d db                               # PostgreSQL 16, waits for the health check
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -e "backend[dev]"
export PYTHONPATH=backend:.                           # PowerShell: $env:PYTHONPATH="backend;."
cd database && ../backend/.venv/Scripts/python -m alembic -c alembic.ini upgrade head && cd ..
backend/.venv/Scripts/python -m database.seed.run --regenerate     # generate CSVs (fixed seed), COPY into fc_, seed core
backend/.venv/Scripts/python -m database.seed.validate             # 33 manifest checks against the loaded data
backend/.venv/Scripts/python -m pytest                             # 65 tests at the end of Day 2, 262 after Day 3 (migration 0004 is part of `upgrade head`)
```

Full reset of a populated database: `alembic downgrade base`, then repeat from `upgrade head` (or `database.seed.run --reset`).
Smaller scale for quick work: `python -m database.seed.run --regenerate --reset --users 10000`. Scenario semantics are unchanged but manifest pattern thresholds are calibrated for the default 50,000 users (the pattern test skips below 20,000).

## What exists

| Layer | Content |
|---|---|
| Migrations | `0001` core schema (14 enums, 22 tables, constraints, guards), `0002` `fc_` schema (9 tables), `0003` views, lookups and the read-only role, `0004` (Day 3) assessment metadata, `blockers_resolved`, canvas-edit stale rule, decided-write guards and assessment immutability. SQL lives in `database/sql/`, executed by Alembic revisions |
| Generator | `data/generator/` (config, generate, feedback, manifest, CLI). Seeded NumPy streams, deterministic ordering, no wall-clock values |
| Manifest | `data/manifest/fitconnect_manifest.json` (canonical copy) and `fitconnect_digests.json` (SHA-256 of each default-seed output file). 33 machine-checkable validation queries |
| Loader | `backend/app/db/csv_loader.py`: header validation and COPY streaming. The database enforces `is_synthetic` |
| Seed | `database/seed/` (`run`, `core_seed`, `validate`, `digest`) |

## Database-level rules implemented
- **Canvas** columns on `decisions`; 1–5 criteria of 10–300 characters (CHECK via `ddr_valid_criteria`); required fields NOT NULL; hypothesis ≤ 500, title ≤ 120, decision type from the configured list.
- **Lifecycle** guard trigger: only the transitions in `decision-lifecycle.md`; new decisions start at `created`; leaving `created` needs a data-sourced metric or evidence; canvas lock is permanent; returning to `evidence_gathered` requires `assessment_stale`; `decided` requires a final human record; `decided` rows are immutable.
- **Score iff scored:** `ddi_score` and `ddi_band` exist only when `state = scored`. `insufficient_evidence` requires at least one blocking reason.
- **Human decision record** only on `validated` decisions; BR-11 acknowledgement for High/Critical or non-scored assessments; insert-only; one final record per decision (`defer` records are historical).
- **Insert-only** `audit_logs` and `decision_records`. Claims may cite only evidence of the same decision.
- **Synthetic labelling:** `is_synthetic` NOT NULL (no default) on all 22 core tables. All 9 `fc_` tables carry `CHECK (is_synthetic)`. The core schema has no foreign key into `fc_`.
- **Read-only role** `ddr_readonly` (NOLOGIN, `SET ROLE`): SELECT on views only. No access to `fc_` base tables or the ground-truth table.

## Deviations and additions relative to ERD.md and PRD §14 (all minor, for review)
1. **Schema name** is literally `fc_`.
2. **Reconciled before Day 3** (now documented in PRD §14.1 and ERD §5, or removed):
   - `claims.conclusion_ref` (text): **kept**. Required by the traceability matrix `conclusion_ref` column.
   - `experiments.source_ref` (text): **kept**. Required so the Experiment Evidence stage can find a registered experiment's raw data without a core-to-demo foreign key.
   - `decision_assessments.is_superseded`: **removed**. "Superseded" is derived (any version lower than the decision's latest), so a stored flag was redundant and could drift. Views compute it.
   - Partial unique index on `decision_records(decision_id) WHERE outcome <> 'defer'`: **kept**. Required by the lifecycle rule that deferral records are kept while at most one final decision exists.
4. `data_sources.source_type`, `experiments.design/status` and similar short vocabularies use CHECK constraints rather than enum types (ERD §4 lists only the 14 central enums).
5. SQL lookups `ddr_half_life_days`, `ddr_tier_factor`, `ddr_grade_factor` and `v_coverage_checklist` duplicate the `ddi_params_v0.1` factors so the views can compute descriptive freshness, reliability and coverage. A test asserts parity with the YAML. They do **not** compute a DDI.
6. `v_agent_quality` summarizes `agent_runs` only (the ERD lists evaluation results too, but no table holds them yet).
7. `metric_observations` holds plain weekly/monthly counts and rates (new users, 7-day activation overall and by platform, trial conversion, AI cost per active user). This is data preparation, not analysis.
8. The ORM layer (SQLAlchemy models) was not created on Day 2. Migrations are SQL files executed by Alembic. **Update (Day 3):** models now exist in `backend/app/db/models.py`, mirror the live schema and are verified by a reflection test. The schema is still created only by the SQL migrations (`create_all` is never used).

## Not populated on purpose
`evidence`, `analysis_results`, `decision_assessments`, `claims`, `dq_checks`, `recommendations`, `decision_reviews`, `customer_insights`, `experiment_results`, `agent_runs`, `decision_records`. These are produced by pipeline stages (Day 3 onward). A test asserts they are empty.

## Known limitations
- Pattern thresholds are calibrated for the default seed and scale. They are checks that the *seeded* patterns exist, not statistical guarantees.
- Community scenario demonstrates **aggregate-vs-segment heterogeneity / aggregate masking**: segment A is strongly positive, B is about zero, C is negative, and the aggregate is strongly positive because joiners are concentrated in segment A. It is related to Simpson-type aggregation risks but does not claim to reproduce a textbook Simpson's paradox (no sign reversal in every segment). This matches PRD §12 and AC-5.
- AI Coach: adopters must survive to adoption day, so some immortal-time bias is intentionally present alongside the selection effect. Within-tier gap is about 42% of the raw gap.
- Experiment outcomes for the pricing test come from the same simulated subscriptions. The AI Coach experiment outcome is the completed-workout count in the experiment window derived from the event stream.
- File digests are stable on this machine's NumPy/pandas versions. A different library version could change them (the DB-level scenario checks would still be the guard).
