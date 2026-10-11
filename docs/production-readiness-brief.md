# Production-Readiness Brief: free full-stack deployment

**Status:** APPROVED by the PO (2026-10-10). The deployment shape is **full stack on free tiers, $0**. **Baseline:** commit `12476f9`.

```
Browser ──> Vercel (Next.js, root: frontend/) ──rewrite /api/*──> Render free web service (FastAPI, replay mode)
                                                                      └──> Neon free Postgres (pooled, sslmode=require)
GitHub Actions (free): CI on push + nightly demo reset against Neon
```

**Free-tier facts the design must respect:**
- **Vercel Hobby:** the Next.js frontend only, because Python functions are capped at 250 MB and the backend dependencies are about 450 MB.
- **Render free web service:** 512 MB RAM; it sleeps after 15 minutes idle, and a cold start takes about 1 minute.
- **Neon free:** 0.5 GB storage.
- **GitHub Actions:** free minutes.

No credit card and no paid add-on may be required. The implementer creates **no accounts** and pushes **nothing**: those are the PO's steps, documented in §8.

## 0. Hard rules

- **Frozen code: no change to methodology or behaviour.** That means zero diff against `12476f9` in:
  - `backend/app/domain/**`, `backend/config/**`, `backend/app/analytics/**`, `backend/app/customer/**`;
  - `backend/app/synthesis/**`, `backend/app/services/lifecycle.py`;
  - `database/sql/0001`–`0006` and the fixtures.
- **New SQL only in a new migration `0007`, and only for deploy compatibility** (for example a role membership grant). No schema or semantic change.
- **No secrets in the repo.** All connection strings live in Render, GitHub or Vercel settings. Keep `.env.example` in sync. Run a final `git grep` for secrets.
- **No paid services, no new SaaS dependencies.** New Python or npm runtime dependencies only if unavoidable, and justified in the notes.
- **The local developer setup must keep working unchanged** (50,000 users, Docker, `demo_prepare --reset`). All existing tests keep passing.
- Do not commit or push. Write UTF-8 files without a BOM.

## 1. Data scale for the hosted demo

- Add a deploy profile: `demo_prepare --reset --users N` passes the scale through to the seed.
- **Choose the smallest `N ≥ 20000` that keeps the database under 300 MB**, leaving headroom under Neon's 0.5 GB. Measure it with `pg_database_size`.
- **Verify the four scenarios at that scale with `demo_prepare`:**
  - AI Coach is scored;
  - Community is scored, with the heterogeneity flag true;
  - Onboarding is gated, with `open_critical_dq` among the blocking reasons;
  - Pricing is scored, and its experiment confidence interval spans zero.
- **Record the observed DDI and band at that scale.** These come from the engine and are never hard-coded. They will differ from the 50k values; document that.
- **If any scenario changes state at that scale, try a larger `N` up to the size limit. If none works, STOP and report.**
- The manifest pattern test only runs at 20,000 users or more, so stay at or above 20,000.

## 2. Non-superuser database compatibility (Neon)

On Neon the app connects as a database owner that is **not** a superuser. Locally, create such a role in the Docker Postgres (`LOGIN CREATEROLE`, owns a fresh database, NOT superuser) and run the following against it:
- migrations `0001`–head;
- the seed;
- `demo_prepare`;
- a pipeline run (which exercises `SET ROLE ddr_readonly` in the SQL guard executor);
- `demo_check`.

Fix whatever fails, for example by granting membership in `ddr_readonly` to the connecting role in migration `0007`, or with extension or ownership adjustments. Methodology must not change.

Neon pooled connections (PgBouncer, transaction mode) break session state such as `SET ROLE` and `SET LOCAL`. Document which connection string to use. If the app relies on session state, use Neon's **direct** (unpooled) connection string.

## 3. Backend production settings

- **`DDR_ENV=production`** turns on:
  - `DDR_LLM_MODE=replay` (no key);
  - a fixed `DDR_AS_OF_DATE` (2026-10-01);
  - JSON or plain stdout logging with a request line (method, path, status, ms);
  - no stack traces in responses (already the case; verify);
  - `--proxy-headers` with forwarded IPs trusted.
- **Database URL:** accept Neon's `postgres://…?sslmode=require` and normalise it to the `postgresql+psycopg` driver.
- **Rate limiting** (in-process, standard library only), keyed by the first `X-Forwarded-For` address:
  - mutating requests (POST, PATCH): about 30 per 10 minutes per IP;
  - `POST /decisions/{id}/pipeline-runs` and re-synthesis: about 5 per 10 minutes per IP;
  - when exceeded, return 429 with the existing error body shape and a friendly message.
- **Health:** `/health` stays cheap, with no database hit.
- **Memory:** measure the peak memory of a pipeline run and of `demo_prepare` at the chosen scale. It must stay **under about 450 MB** for Render's 512 MB. If it doesn't, report what uses the memory; do not change the methodology.
- **`render.yaml`** (Blueprint, free plan, Python 3.12):
  - build: `pip install ./backend`;
  - start: `alembic upgrade head`, then `uvicorn` on `$PORT`;
  - environment variables listed, with `DATABASE_URL` marked `sync: false` (secret).

## 4. Frontend production settings

- **API target.** `next.config.mjs` rewrites `/api/:path*` to `${API_ORIGIN}/:path*`, defaulting to `http://127.0.0.1:8000`. API calls stay same-origin, so no CORS change is needed.
- **Security headers** on all routes:
  - `X-Content-Type-Options: nosniff`;
  - `Referrer-Policy: strict-origin-when-cross-origin`;
  - `X-Frame-Options: DENY`;
  - `Permissions-Policy` minimal;
  - a conservative CSP compatible with Next.js and `next/font`. Verify the app still renders and the Playwright tests pass.
- **Cold start.** When the API returns 502, 503 or 504, or times out, show a friendly state: *"The free demo server is waking up (about a minute). Retrying…"*, with automatic retry and backoff. Do this in the existing error and loading components; never claim "no data".
- **Shared-demo notice.** A small header note in production only: *"Public demo · shared data · resets nightly"*. It is shown when `NEXT_PUBLIC_DDR_PUBLIC_DEMO=1`.
- Everything else, the trust rules and the test IDs stay unchanged.

## 5. GitHub Actions (free)

- **`.github/workflows/ci.yml`** runs on push and pull requests:
  - backend: `pip install`, then unit tests that don't need the database (`tests/unit` and the guards that run without it);
  - frontend: `npm ci`, `tsc`, Vitest, `next build`.

  No secrets are needed. Database-backed and Playwright tests stay local (document why: seeding 2M events per CI run is wasteful).
- **`.github/workflows/demo-reset.yml`** runs nightly on a cron and on manual dispatch:
  1. check out the repo and set up Python 3.12;
  2. `pip install ./backend`;
  3. `alembic upgrade head`;
  4. `demo_prepare --reset --users N` against `secrets.DATABASE_URL` (the direct Neon URL).

  It must finish well inside the free limits. Measure the local duration and document it.

## 6. Repository hygiene

- Check that `.gitignore` covers build output, `data/generated`, Playwright reports and `.env*`, and that nothing over 5 MB is tracked.
- Add a `LICENSE` only if the PO asks; otherwise leave it out.
- Remove local-only absolute paths from docs where they would confuse a cloner.

## 7. Gate

1. The full local regression at 50k: pytest, Vitest, `tsc`, `next build`, and Playwright with 20 tests.
2. A **production simulation** against the non-superuser database at deploy scale:
   - run the backend with `DDR_ENV=production`, then `next start` with `API_ORIGIN` pointing at it and `NEXT_PUBLIC_DDR_PUBLIC_DEMO=1`;
   - `demo_check`, `/health`, and the portfolio loads with the four expected states;
   - a burst of POSTs returns 429;
   - stopping the API shows the waking-up state, not an error dump.
3. The memory and duration measurements (§1, §3, §5).
4. The secret scan.
5. The frozen-path diff against `12476f9`: empty.

Then **restore the local 50k demo** (`demo_prepare --reset`). Do not commit.

## 8. Documentation: `docs/deployment.md`

Exact click-by-click steps for the PO, assuming no prior accounts:
1. Create a GitHub repo (public or private, both free) and push.
2. Create a Neon project in the free plan and copy the **direct** connection string.
3. Add the `DATABASE_URL` GitHub secret and run the "demo-reset" workflow once.
4. Create the Render Blueprint from `render.yaml`, set `DATABASE_URL`, deploy and open `/health`.
5. Import the repo into Vercel (root directory `frontend`) with `API_ORIGIN` set to the Render URL and `NEXT_PUBLIC_DDR_PUBLIC_DEMO=1`, then deploy.
6. Check that everything works.

Also include:
- a cost table showing $0, with each free-tier limit;
- what sleeps and when;
- troubleshooting: cold start, Neon storage, a failed reset, 429s.

Link it from the README.
