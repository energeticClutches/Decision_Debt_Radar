# Tests

| Folder | Purpose |
|---|---|
| `unit/` | Parameter-file structure, health endpoint, generator fixed-seed reproducibility (no database) |
| `db/` | Migrations on a scratch database, schema/ERD structure, canvas/lifecycle/assessment/insert-only constraints, reporting views, seeded-data and manifest validation, synthetic labelling, read-only role |
| `backend/` | Day 3: pure DDI and NBE engines (golden, property and gating tests), parameter loader, SQLAlchemy model reflection, lifecycle and services on the real database (rolled back), concurrency on a scratch database, API role matrix, scope guard |
| `evals/` | Agent evaluation scenarios (Day 7) |

Database tests need the Compose `db` service, a migrated schema and the seed. They skip cleanly otherwise. Data-changing tests run in rolled-back transactions.

```bash
PYTHONPATH=backend:. backend/.venv/Scripts/python -m pytest        # see docs/day-3-implementation-notes.md for the count
```

Evaluation scenarios and labels are synthetic and say so.
