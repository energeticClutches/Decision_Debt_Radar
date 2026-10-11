# Production readiness: implementation notes

Implements `docs/production-readiness-brief.md` (free full-stack deployment: Vercel + Render + Neon). Baseline `12476f9`. Nothing is deployed and nothing is
pushed; the steps for the Product Owner are in [deployment.md](deployment.md).

## What changed, and what did not

**Frozen (zero diff against `12476f9`, checked with `git diff 12476f9 -- <paths>`):** `backend/app/domain/**`, `backend/config/**`, `backend/app/analytics/**`,
`backend/app/customer/**`, `backend/app/synthesis/**`, `backend/app/services/lifecycle.py`, `database/sql/0001` to `0006` and the fixtures (`tests/fixtures/**`,
`backend/demo_fixtures/**`). No methodology or behaviour change: the DDI and NBE engines, the validators, the SQL guard and its executor are untouched.

| Area | Change |
|---|---|
| Database | New migration **0007** (`database/sql/0007_deploy_compat.sql` and its down, `database/migrations/versions/0007_deploy_compat.py`): grants the connecting role membership in `ddr_readonly` with the SET option and without INHERIT. No schema or semantic change. |
| Settings (`backend/app/core/config.py`) | `DDR_ENV=production` (alias of `APP_ENV`) pins `DDR_LLM_MODE=replay` and `DDR_AS_OF_DATE=2026-10-01` (an explicit date still wins), and turns on the request log, the rate limit and trusted forwarded headers. `postgres://` and `postgresql://` URLs (Neon) are normalised to `postgresql+psycopg://`; the same in the Alembic `env.py` and the seed's `to_conninfo`. |
| Middleware (`backend/app/core/ratelimit.py`, `middleware.py`, `main.py`, `errors.py`) | In-process sliding-window rate limit (standard library only), keyed by the first `X-Forwarded-For` address: mutating requests 30 per 10 minutes, pipeline runs and re-synthesis 5 per 10 minutes; HTTP 429 with the API's error body and `Retry-After`. One JSON log line per request (method, path without query, status, ms, address). A catch-all handler returns a JSON 500 with no stack trace and no exception text. `/health` is unchanged (no database hit). |
| Replay fixtures (`backend/app/llm/replay.py`, `backend/demo_fixtures_deploy/**`, `scripts/build_demo_fixtures.py --supplement`) | See "Finding 1". |
| Scripts | `demo_prepare.py --reset --users N` (data goes to `data/generated/users_N`, so the 50,000-user files are never overwritten); it switches its own rate limit and request log off. `demo_check.py` picks the manifest that matches the loaded scale. |
| Deploy files | `render.yaml`, `.github/workflows/ci.yml`, `.github/workflows/demo-reset.yml`, `.env.example` (documented, placeholders only), `docs/deployment.md`, a README section. |
| Frontend | `next.config.mjs`: `API_ORIGIN` (default `http://127.0.0.1:8000`; `DDR_API_ORIGIN` still read), security headers on every route (nosniff, Referrer-Policy, X-Frame-Options DENY, minimal Permissions-Policy, a conservative CSP). Cold start: `lib/wake.ts` (retry with backoff on 502, 503, 504, timeout or network failure; a global "waking" state), the existing `Loading` and `ErrorBox` components and a banner under the header; the public-demo note in the header (`NEXT_PUBLIC_DDR_PUBLIC_DEMO=1`). Test IDs and trust rules are unchanged. |

New tests: `tests/unit/test_deploy_profile.py` (URL normalisation, production profile, rate limit, 429 shape, request log, no stack trace, deploy fixtures),
`tests/db/test_migrations.py::test_0007_*`, `frontend/tests/deploy.test.tsx` (cold start mapping and retry, `ErrorBox`, security headers, the rewrite).
No existing test was weakened or deleted.

## Finding 1: the replay fixtures were written for 50,000 users

At 20,000 users the pipeline did not reach the demo state: `fixture_missing` for the classification of the last batches, then, with those added, the
number validator (V-NUM, frozen) correctly dropped the claims whose literal numbers (for example "37.8% D90 retention", "970 mentions") are the 50,000-user values.
The validators were right; the fixtures were scale-specific. Fix, with no change to any frozen code:

- 8 classification fixtures for the 20,000-user data, recorded with the same keyword-rule stub by `scripts/build_demo_fixtures.py --supplement`, keyed by input hash like the base ones (`backend/demo_fixtures_deploy/classify`). Base fixtures are never overridden.
- 4 hand-authored synthesis fixtures (`backend/demo_fixtures_deploy/synthesize`): the same claims, flaws and sections as the base ones (including the deliberately wrong claims the Reviewer must catch), with the numbers of the 20,000-user evidence. A deploy fixture lists the evidence sample sizes it was written for (`match_evidence_n`) and is used only for a request with exactly those; at 50,000 users the base fixtures apply, as before. Review fixtures contain no scale-dependent numbers and are unchanged.
- All are marked `stub_not_model_output`; the UI says "Replayed demo fixture, not live model output" as before.

The data generator is deterministic across platforms: the nightly workflow's path (an empty database, Linux, freshly generated data) reproduced exactly the same classification hashes and the same four results as the Windows run.

## Finding 2: a non-superuser owner cannot `SET ROLE ddr_readonly`

Tested on a separate Postgres 16 whose database owner is `LOGIN CREATEROLE`, not a superuser (a stand-in for Neon). Migrations 0001 to 0006, the seed, `demo_prepare` and a pipeline run all work, except that the SQL guard executor's `SET LOCAL ROLE ddr_readonly` is refused: on PostgreSQL 16 and later the creator of a role gets `ADMIN OPTION` but not `SET`. Migration 0003 creates the role as the connecting user, so the fix is a one-line grant, which is what 0007 does (`GRANT ddr_readonly TO CURRENT_USER WITH SET TRUE, INHERIT FALSE`; plain `GRANT` before PostgreSQL 16; a warning instead of a failure if the connecting role lacks the right to grant). No extension, ownership or other adjustment was needed. After 0007 the whole path passes as a non-superuser, including `demo_check`.

## Decision: Neon direct connection, not pooled

The application keeps no state between transactions that a PgBouncer transaction pool would break in the executor (`SET LOCAL`, `set_config(..., true)` and the isolation level are per transaction), but the seed and demo scripts use session-level `set_config(..., false)` and `COPY`, psycopg 3 prepares statements on the server after five executions, and only direct connections were tested. The service opens at most 15 connections. **Use the direct string for Render, the GitHub secret and any local run.** A pooled string was not tested.

## Deviations and limits

1. **Test updates, not weakened:** `tests/db/test_migrations.py` and `tests/db/test_day5_schema.py` asserted that the head revision is `0006`; a new migration makes it `0007` (three assertions changed, one new test added).
2. **A second Docker container** (`ddr-neonlike`, port 5433) was used for the non-superuser and deploy-scale experiments instead of a second database in the local container: `ddr_readonly` is a cluster-level role that already exists there (created by a superuser), which would have hidden the problem 0007 fixes. The container and its database were removed at the end.
3. **Fixtures added** for the deploy scale (Finding 1): data files plus a small `ReplayDemoClient` extension. The brief did not foresee them; without them the four scenarios cannot be reproduced at 20,000 users.
4. **`app.main` always installs the JSON 500 handler.** Before, an unexpected error returned a plain-text 500 from the framework (no trace either). The frontend relies on the JSON body to tell the API's own 500 from the proxy's 500 when the API host is down.
5. The Power BI project keeps its `DataFolder` parameter (an absolute path to the author's machine) in `analytics/powerbi/**/expressions.tmdl`: it is a Power BI parameter that is edited in Power BI Desktop (see `analytics/powerbi/README.md`), not documentation, and changing it would break the author's local report. No document in `docs/` or the README contains a local absolute path.
6. **Pricing's confidence interval spans zero by a small margin** at 20,000 users (-0.169 to +0.00366), so the demo state is correct but not far from the edge: if the generator or the seed ever changes, re-check it (`demo_prepare` prints the engine values).
7. **Not measured:** the real Render free CPU. A pipeline run took 1.5 s here and 5 to 6 s in a container; the free instance has a fraction of a CPU, so a visitor's pipeline run may take tens of seconds, and the page shows its normal working state while it waits.
8. **The rate limit is a convenience, not security:** it trusts the first `X-Forwarded-For` address, which a client can forge, and it lives in one process's memory (it clears on a restart).

## Memory

The API (uvicorn, production profile) peaked at **225 MB** resident after four pipeline runs, in a Linux container capped at 512 MB with no swap and no out-of-memory kill (limit used: 450 MB). What uses it: the interpreter plus pandas, scipy, statsmodels and sqlglot imported by the analytics code. `demo_prepare` (in-process) peaked at about 210 MB working set on Windows; the generator and seed process peaks near 560 MB and runs on the GitHub runner, not on Render.
