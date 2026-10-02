# Day-1 Implementation Readiness and Log

Parent: [PRD-v0.1.md](PRD-v0.1.md) §20. Recorded at the start of Day 1 implementation (2026-10-01).

## Environment readiness checks

| Check | Result | Note |
|---|---|---|
| Git | OK (2.53) | User identity configured |
| Python | **Deviation** | Approved: 3.11. Available: 3.12 (venv used) and 3.14. The backend declares `>=3.11,<3.14`, the Docker image uses `python:3.11-slim`, local development uses 3.12 |
| Node / npm | OK (Node 24, npm 11) | Docker image uses Node 22 LTS |
| Docker / Docker Compose | **Not installed** | Compose file validated structurally only. Needed to run PostgreSQL via Compose |
| PostgreSQL client (`psql`) | Not installed | Not needed if Docker is installed |
| Power BI Desktop | Installed (Microsoft Store package) | Needed on Day 6 |
| `ANTHROPIC_API_KEY` | Not set | Not needed until Day 4. Never commit it |
| Opus availability | Unknown | Reviewer falls back to Sonnet and logs it (ADR-007) |

## Day-1 scope delivered
Git repository, approved folder structure, Compose skeleton, backend/frontend skeletons, versioned DDI/NBE parameter files, test structure, environment template. See the root README for run commands.

## Not implemented (by design)
PostgreSQL schema, synthetic generator, analytics, DDI/NBE engines, agents, frontend functionality, Power BI. Day 2 onward.
