# Tests

| Folder | Purpose |
|---|---|
| `unit/` | Parameter-file structure, health endpoint, generator fixed-seed reproducibility (no database) |
| `db/` | Migrations on a scratch database, schema/ERD structure, canvas/lifecycle/assessment/insert-only constraints, reporting views, seeded-data and manifest validation, synthetic labelling, read-only role |
| `backend/` | Day 3: pure DDI and NBE engines (golden, property and gating tests), parameter loader, SQLAlchemy model reflection, lifecycle and services on the real database (rolled back), concurrency on a scratch database, API role matrix, scope guard |
| `backend/` (Day 4) | SQL guard and read-only execution, hashed analytics configuration, data quality and its reconciliation, heterogeneity and experiment statistics, evidence materialisation (identity, supersede, traceability), the deterministic pipeline and its API, the DDI/NBE no-change guard (needs `git` and the baseline commit `f6209e9`), a scratch-database test with committed data changes |
| `backend/` (Day 4.1) | NBE v0.2 blocker dependency and the v0.1 preservation proof against golden output generated from the baseline code (`test_nbe_v02.py`, `nbe_v01_cases.py`, `golden_nbe_v01.json`); descriptive evidence does not count toward D6 (`test_d6_descriptive.py`, pure; `test_d6_descriptive_db.py`, real pipeline). The no-change guard now freezes DDI and NBE v0.1 and allows only the v0.2 dependency in NBE code |
| `backend/` (Day 5) | Guards G1 to G3 (zero diff against `65caec6`, scope guard, ground truth never read by product code), customer evidence C1 to C7, validators V1 and the deterministic mutation checks E2, synthesis and review S1 S2 R1 to R3 E3 E4, briefs B1 to B4, scenarios A1 to A4 and the Day-5 API, evaluation E1. Every LLM call is served by `tests/fixtures/llm` (keyword-rule stub classifier, hand-authored synthesis and review fixtures, scripted failures); all carry `stub_not_model_output`. Tests marked `@pytest.mark.llm` call a live model and are skipped without `ANTHROPIC_API_KEY` |
| `db/` (Day 5) | Migration 0006 invariants and its downgrade with Day-5 data (`test_day5_schema.py`) |
| `evals/` | Agent evaluation scenarios (Day 7) |

Database tests need the Compose `db` service, a migrated schema and the seed. They skip cleanly otherwise. Data-changing tests run in rolled-back transactions.

```bash
PYTHONPATH=backend:. backend/.venv/Scripts/python -m pytest        # see docs/day-3-implementation-notes.md and docs/day-4-implementation-notes.md for the count
```

Evaluation scenarios and labels are synthetic and say so.
