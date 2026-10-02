# database/

PostgreSQL 16 schema, Alembic migrations and seed tooling. Canonical design: [docs/ERD.md](../docs/ERD.md). Day-2 notes: [docs/day-2-data-foundation.md](../docs/day-2-data-foundation.md).

```
database/
├── alembic.ini
├── migrations/   env.py (DATABASE_URL from the environment or ../.env), sqlfile.py, versions/0001..0004
├── sql/          0001_core_schema, 0002_fc_schema, 0003_views_and_roles, 0004_day3_assessment_and_guards (+ *_down.sql)
└── seed/         run.py (load + seed), core_seed.py, validate.py (manifest checks), digest.py (reproducibility)
```

```bash
cd database && python -m alembic -c alembic.ini upgrade head     # empty database to head (0004)
python -m alembic -c alembic.ini downgrade base                  # back to empty
```

Seed (from the repository root, with `PYTHONPATH=backend:.`): `python -m database.seed.run --regenerate`.
All FitConnect rows are synthetic (FitConnect is fictional).
