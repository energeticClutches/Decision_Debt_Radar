# Decision Debt Radar

**Agentic Decision Intelligence for Evidence-Based Organizations.**

Decision Debt Radar (DDR) helps an organization see how well an important business decision is supported by evidence. It does not make decisions. It tells you how well your decision is supported, what could invalidate your reasoning, and what evidence you should gather next. A human always records the final decision.

> **Framework disclaimer.** "Decision Debt" and the Decision Debt Index (DDI) are a proposed framework created for this portfolio project. DDI is a transparent evidence-risk heuristic for business decisions. It is not an objective measure of decision quality, not scientifically validated, not an industry standard and not a predictor of business outcomes.
>
> **Data disclaimer.** FitConnect is a fictional company used as the demo tenant. **All FitConnect data is synthetic.** The platform core is industry-agnostic.

## Status

**Day 4 of 7: data and analytics foundation (deterministic, no LLM).** On top of Day 3: per-decision data-quality checks reconciled on re-run, experiment statistics (SRM, effect with CI, design power), group comparison, trend, funnel and heterogeneity analyses, evidence generated from analyses with full traceability (identity, supersede), the SQL guard with read-only execution, and a deterministic pipeline (stages 1, 2 and 4 plus the Day-3 assessment) behind `POST /decisions/{id}/pipeline-runs`. The DDI is unchanged and NBE v0.1 is preserved (a test enforces it). **Day 4.1 remediation:** NBE v0.2 (active default) adds the success-metric blocker dependency under an open critical DQ issue, and descriptive trend and funnel evidence no longer counts toward D6. See [docs/day-4-implementation-notes.md](docs/day-4-implementation-notes.md). Still no LLM, agent, frontend feature or Power BI report.

**Day 3 of 7: deterministic business-logic foundation.** On top of the Day-2 database and synthetic data: the pure DDI and NBE engines (gating, contribution breakdown, sensitivity, evidence-direction summary), versioned and hash-checked parameters, the decision lifecycle, assessment versioning, human review and decision record, SQLAlchemy models, repositories, services and the FastAPI API with a demo role switcher (`X-Demo-User`, not authentication). There is no LLM, agent, analytics, frontend feature or Power BI report yet. See [docs/day-3-implementation-notes.md](docs/day-3-implementation-notes.md), [docs/day-2-data-foundation.md](docs/day-2-data-foundation.md) (rebuild commands included) and [docs/day-1-readiness.md](docs/day-1-readiness.md).

## Documentation (source of truth)

| Doc | Purpose |
|---|---|
| [docs/PRD-v0.1.md](docs/PRD-v0.1.md) | Product requirements (revision 2) |
| [docs/DDI-spec.md](docs/DDI-spec.md) | DDI methodology and parameters |
| [docs/NBE-spec.md](docs/NBE-spec.md) | Next Best Evidence framework |
| [docs/traceability-spec.md](docs/traceability-spec.md) | Evidence Traceability Matrix |
| [docs/ERD.md](docs/ERD.md) | Data model relationships and constraints |
| [docs/decision-lifecycle.md](docs/decision-lifecycle.md) | Decision lifecycle |
| [docs/decision-canvas.md](docs/decision-canvas.md) | Decision Canvas |
| [docs/ADRs.md](docs/ADRs.md) | Architecture decisions |
| [docs/day-4-implementation-brief.md](docs/day-4-implementation-brief.md) | Day-4 decisions D4-01 to D4-25, O1 to O3, required tests |
| [docs/day-4-implementation-notes.md](docs/day-4-implementation-notes.md) | Day-4 implementation notes (architecture, migration 0005, hashes, methodology as built, parameter justification, expected vs observed) |
| [docs/day-3-implementation-brief.md](docs/day-3-implementation-brief.md) | Day-3 decisions R1-R14, resolutions and required tests |
| [docs/day-3-implementation-notes.md](docs/day-3-implementation-notes.md) | Day-3 implementation notes (methodology as built, parameters, migration 0004, API, tests) |

## Repository layout

```
docs/  prompts/  data/  database/  backend/  agents/  frontend/  analytics/  tests/
docker-compose.yml  .env.example  pytest.ini
```

## Run the skeleton

Prerequisites: Python 3.11–3.13, Node 22+, Docker (optional on Day 1).

```bash
cp .env.example .env            # edit locally. .env is git-ignored
```

Backend (host):

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -e "backend[dev]"      # Windows. Use .venv/bin/python on macOS/Linux
PYTHONPATH=backend:. backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000
# http://localhost:8000/health   and   http://localhost:8000/docs
```

Frontend (host):

```bash
cd frontend && npm install && npm run dev      # http://localhost:3000
```

Tests (from the repository root):

```bash
backend/.venv/Scripts/python -m pytest
```

Docker (incremental):

```bash
docker compose up -d db                  # PostgreSQL only. No schema yet (Day 2)
docker compose --profile app up --build  # also builds backend and frontend skeletons
```

## Technology

Python, FastAPI, SQLAlchemy + Alembic, Pydantic, sqlglot, pandas, scipy/statsmodels, PostgreSQL 16, Next.js + TypeScript, Docker Compose, Power BI Desktop, Anthropic SDK (Claude Sonnet primary, Opus for the Reviewer where available). Plain Python orchestration, no agent framework. CSV-only ingestion. Role-switcher instead of authentication. Local-first.
