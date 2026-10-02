# Decision Debt Radar

**Agentic Decision Intelligence for Evidence-Based Organizations.**

Decision Debt Radar (DDR) helps an organization see how well an important business decision is supported by evidence. It does not make decisions. It tells you how well your decision is supported, what could invalidate your reasoning, and what evidence you should gather next. A human always records the final decision.

> **Framework disclaimer.** "Decision Debt" and the Decision Debt Index (DDI) are a proposed framework created for this portfolio project. DDI is a transparent evidence-risk heuristic for business decisions. It is not an objective measure of decision quality, not scientifically validated, not an industry standard and not a predictor of business outcomes.
>
> **Data disclaimer.** FitConnect is a fictional company used as the demo tenant. **All FitConnect data is synthetic.** The platform core is industry-agnostic.

## Status

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
