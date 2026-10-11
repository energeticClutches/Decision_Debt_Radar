# Deploying the free hosted demo ($0)

This puts Decision Debt Radar on the internet with **no credit card and no paid service**:

```
Browser --> Vercel (Next.js, root: frontend/) --rewrite /api/*--> Render free web service (FastAPI, replay mode)
                                                                        |
                                                                        +--> Neon free Postgres (direct connection, sslmode=require)
GitHub Actions (free): CI on every push + a nightly reset of the demo database
```

Everything shown is **synthetic** (FitConnect is a fictional company) and the model layer is **replayed** (no API key, no model call). The hosted
demo runs the same frozen DDI v0.1 and NBE v0.2 engines as the local setup; only the data scale (20,000 users instead of 50,000) and the hosting differ.

**You (the Product Owner) do the steps below; the code never creates an account or pushes anything for you.** Screen labels on the three
dashboards change from time to time: the names below are what to look for, not exact pixel instructions.

## Cost: $0

| Service | Plan | What it hosts | The limit that matters | Cost |
|---|---|---|---|---|
| GitHub | Free (public or private repository) | The code, CI, the nightly reset | Actions minutes: this uses about 5 minutes a day; the free allowance is far larger | $0 |
| Neon | Free | The Postgres database | **0.5 GB storage** (the demo database is about 205 MB); compute sleeps after 5 minutes idle and wakes in about a second | $0 |
| Render | Free web service | The FastAPI backend | **512 MB RAM** (the backend peaks at about 225 MB); **sleeps after 15 minutes without traffic, a cold start takes about a minute**; shared fractional CPU; 750 free instance hours a month | $0 |
| Vercel | Hobby | The Next.js frontend only | Personal, non-commercial use; the frontend is small and well inside the limits (the Python backend is deliberately **not** on Vercel: its dependencies are about 450 MB and a Vercel Python function is capped at 250 MB) | $0 |

No add-on, no custom domain and no card is needed. If a dashboard asks for a card, you chose a paid plan: go back and pick Free.

## What sleeps, and when

| Piece | Sleeps when | Wake-up | What a visitor sees |
|---|---|---|---|
| Render API | 15 minutes without a request | about 1 minute | "The free demo server is waking up (about a minute). Retrying..." and the page retries by itself, then loads |
| Neon compute | 5 minutes idle | about 1 second | nothing (the first query is slightly slower) |
| Vercel frontend | never (static assets and a small server) | none | nothing |

The nightly reset (03:17 UTC) also gives every visitor the same clean starting state.

## Steps

### 1. GitHub: create the repository and push

1. Sign in at github.com (create a free account if you have none). Click **New repository** (the "+" menu, top right).
2. Name it, for example `decision-debt-radar`. Public or private both work and both are free. Do **not** add a README, .gitignore or licence (the project has them). Click **Create repository**.
3. In a terminal in the project folder, add the remote and push the current branch. GitHub shows these exact lines on the empty repository page:
   ```bash
   git remote add origin https://github.com/<your-user>/decision-debt-radar.git
   git push -u origin main
   ```
   (The repository contains no secret: connection strings live only in the Render, GitHub and Vercel settings.)
4. Open the **Actions** tab. The `ci` workflow starts on the push and should end green in about 3 minutes (backend tests that need no database, then `tsc`, Vitest and `next build`).

### 2. Neon: create the free database and copy the DIRECT connection string

1. Sign up at neon.tech (a GitHub or Google sign-in is fine; no card). Click **Create project**.
2. Name it `decision-debt-radar`, keep the default Postgres version (16 or newer), pick the region closest to you and **use the same region family as Render** (for example both in Europe, or both in the US) to keep latency low. Click **Create**. Leave the default database `neondb` and its owner role.
3. On the project dashboard click **Connect**. In the dialog find the toggle **Connection pooling** and **turn it OFF**. The host name in the string must **not** contain `-pooler`. Copy the string; it looks like:
   `postgresql://<owner>:<password>@ep-xxxx.<region>.aws.neon.tech/neondb?sslmode=require`
4. Keep it private. You will paste it in two places (GitHub and Render), never into a file in the repository.

> **Why the direct (unpooled) string.** Neon's pooled endpoint is PgBouncer in transaction mode, which does not keep session state between statements. The application's own session settings (`SET LOCAL ROLE ddr_readonly`, `set_config(..., true)`) are transaction-scoped and would survive that, but the seed and demo scripts use session-level settings and `COPY`, psycopg prepares statements on the server, and the whole application was tested only on direct connections. One small web service does not need pooling (it opens at most 15 connections). **Use the direct string everywhere**: Render, the GitHub secret and any local run against Neon.

### 3. GitHub: add the `DATABASE_URL` secret and run `demo-reset` once

1. In the repository: **Settings > Secrets and variables > Actions > New repository secret**.
2. Name: `DATABASE_URL`. Value: the direct Neon string from step 2. Click **Add secret**.
3. Open **Actions > demo-reset > Run workflow > Run workflow**. It migrates the empty database to head, generates 20,000 synthetic users, loads them and prepares the four demo decisions through the real API with the replay client. It takes about 3 to 5 minutes. It must end green.
4. If it fails, open the failed step: see **Troubleshooting** (a failed reset).

The same workflow then runs every night at 03:17 UTC and on demand; each run wipes what visitors changed.

### 4. Render: create the API from the Blueprint

1. Sign up at render.com (a GitHub sign-in is easiest; no card for the Free plan). Allow Render to read the repository when it asks.
2. **New + > Blueprint**. Pick the repository. Render reads `render.yaml` and shows one web service, `ddr-api`, on the **Free** plan.
3. It asks for the one secret marked in the file, `DATABASE_URL`. Paste the **direct** Neon string from step 2. Click **Apply** (or **Deploy Blueprint**).
4. Wait for the first deploy (a few minutes: it installs the dependencies, migrates the database, starts the server). The service page shows the public URL, for example `https://ddr-api.onrender.com`.
5. Open `https://<your-service>.onrender.com/health`. You should see JSON with `"status":"ok"`, `"env":"production"` and `"llm_mode":"replay"`. (After a sleep, the first request takes about a minute.)

What `render.yaml` sets: Python 3.12, `pip install ./backend`, start = `alembic upgrade head` then `uvicorn` on `$PORT` with `--proxy-headers`, and the environment `DDR_ENV=production`, `DDR_LLM_MODE=replay`, `DDR_AS_OF_DATE=2026-10-01`. Production mode also turns on a JSON request log on stdout (method, path, status, milliseconds), the rate limit and trusted forwarded headers, and never returns a stack trace.

### 5. Vercel: import the repository for the frontend

1. Sign up at vercel.com (**Hobby** plan, a GitHub sign-in is easiest). **Add New > Project** and import the repository.
2. **Root Directory: `frontend`** (click Edit next to it). Framework preset: Next.js (detected). Leave the build and install commands at their defaults.
3. **Environment Variables** (all environments):
   - `API_ORIGIN` = `https://<your-service>.onrender.com` (the Render URL from step 4, no trailing slash)
   - `NEXT_PUBLIC_DDR_PUBLIC_DEMO` = `1`
4. Click **Deploy**. When it finishes, open the Vercel URL.

The browser only ever talks to the Vercel address: Next.js forwards `/api/*` to Render (`next.config.mjs`), so there is no CORS setting anywhere. `API_ORIGIN` is read when the app is built, so after changing it, **redeploy**.

### 6. Check that everything works

- The portfolio shows four decisions and a header note **"Public demo . shared data . resets nightly"** next to "Synthetic data" and "Demo mode: replayed fixtures".
- The four states you should see at this data scale (these numbers come from the engine; they differ from the 50,000-user local demo):

  | Decision | State at 20,000 users | Local 50,000 users |
  |---|---|---|
  | AI Coach | DDI 58.2 (high), scored | 60.5 (high) |
  | Community | DDI 69.2 (high), scored, heterogeneity flag true | 66.5 (high) |
  | Onboarding | INSUFFICIENT EVIDENCE (gated; no DDI anywhere); `open_critical_dq` is among the blocking reasons | same |
  | Pricing | DDI 74.6 (high), scored; the experiment's confidence interval spans zero (-0.169 to +0.00366) | 73.7 (high) |

- `https://<your-service>.onrender.com/health` answers `ok` with `llm_mode: replay`.
- Leave it 15 minutes, reload the Vercel URL: you see "The free demo server is waking up (about a minute). Retrying...", then the data.
- Do not expect to run the Playwright or database test suites against the hosted copy: they stay local (they reseed the 50,000-user database).

## Measurements (this machine, Docker Postgres 16, Windows; and a Linux container as a GitHub runner stand-in)

| What | Value |
|---|---|
| Chosen scale | **N = 20,000 users** (the smallest allowed: at least 20,000 keeps the manifest pattern checks valid) |
| Database size (`pg_database_size`) | 198 MB after the seed, **205 MB** after the demo preparation (limit used: 300 MB; Neon free: 512 MB) |
| Rows | 20,000 users, 844,210 events, 11,015 subscriptions, 2,424 feedback |
| Peak memory of the API (Render sizing) | **225 MB** resident after four pipeline runs, measured in a Linux container capped at 512 MB (no out-of-memory kill); limit used: 450 MB |
| Peak memory of `demo_prepare` (in-process API calls) | about 210 MB working set. The data generator and seed (a separate process, run on the GitHub runner, not on Render) peak at about 560 MB, far below a runner's 7 GB |
| Pipeline run (one decision) | about 1.5 s on the development machine, 5 to 6 s in a container; the Render free CPU is a shared fraction, so allow tens of seconds |
| Reset (`demo_prepare --reset --users 20000`) | **about 41 s** locally (seed 26 s + prepare); about 60 s for the script in a Linux container with fresh data generation, plus 1 to 2 minutes of `pip install` in the workflow: **3 to 5 minutes per nightly run** |
| Idempotence | a second `demo_prepare` run makes 0 writes |

## Reproduce the production simulation locally (no accounts needed)

```bash
# a throwaway Postgres whose database owner is NOT a superuser (like Neon), on port 5433 so the local 50,000-user database is untouched
docker run -d --name ddr-neonlike -e POSTGRES_PASSWORD=pgsuper_local_only -p 127.0.0.1:5433:5432 postgres:16
docker exec ddr-neonlike psql -U postgres -c "CREATE ROLE neon_owner LOGIN CREATEROLE PASSWORD 'neon_local_only'" -c "CREATE DATABASE ddr_deploy OWNER neon_owner"
export DATABASE_URL="postgres://neon_owner:neon_local_only@127.0.0.1:5433/ddr_deploy"
(cd database && PYTHONPATH="../backend;.." ../backend/.venv/Scripts/python -m alembic -c alembic.ini upgrade head)
DDR_ENV=production PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/demo_prepare.py --reset --users 20000
DDR_ENV=production PYTHONPATH="backend;." backend/.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips="*"
# in a second terminal (build and start with the same two variables):
(cd frontend && export API_ORIGIN=http://127.0.0.1:8000 NEXT_PUBLIC_DDR_PUBLIC_DEMO=1 && npm run build && npx next start -H 127.0.0.1 -p 3000)
# in a third terminal (same DATABASE_URL):
PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/demo_check.py
# clean up afterwards: docker rm -f ddr-neonlike
```

A fresh container matters: `ddr_readonly` is a cluster-level role. On a Postgres where it already exists (created by a superuser, like the local demo database), a non-superuser owner is not allowed to grant itself membership; migration 0007 then prints a warning and an administrator must run `GRANT ddr_readonly TO <owner> WITH SET TRUE;`. On a new Neon project the owner creates the role in migration 0003, so 0007 succeeds on its own.

(On macOS and Linux, use `:` instead of `;` in `PYTHONPATH` and `.venv/bin/python`.) In this simulation the database user is not a superuser, so it also proves that `SET ROLE ddr_readonly` works for a database owner (migration 0007).

## Troubleshooting

**The page says the free demo server is waking up.** That is the Render cold start (about a minute). The page retries by itself for about two and a half minutes. If it ends with a "still waking up" message, press **Retry**. Check `https://<your-service>.onrender.com/health` in a tab: once it answers, the app works.

**It never wakes up / Render shows a failed deploy.** Open the service **Logs**. Common causes: `DATABASE_URL` missing or wrong (the log shows a connection error), or the Neon string is the pooled one (host contains `-pooler`): use the direct string. Fix the variable and choose **Manual Deploy > Deploy latest commit**.

**Neon storage warning (0.5 GB).** The demo uses about 205 MB. If you see growth, the nightly reset truncates and reloads the same tables, so it should not grow; deleted rows are reclaimed by autovacuum. If you changed `--users` upward, go back to 20000. In the Neon dashboard, **Monitoring** shows the storage.

**The demo-reset workflow failed.**
- "Add the DATABASE_URL repository secret": the secret is missing (step 3).
- A connection error (`could not translate host name`, `password authentication failed`, `SSL`): the secret is wrong or truncated. Copy the direct string again, with `?sslmode=require`.
- `permission denied` while migrating or seeding: the string must belong to the **database owner** role Neon created with the project (the default one in the Connect dialog), not a read-only role.
- The step prints `did not reach the target state` or a `fixture_missing` note: the generated data differs from the data the recorded fixtures were written for. This should not happen with the same code and `--users 20000` (it was verified on Linux from an empty database). If you changed the generator or the seed, regenerate the fixtures locally (`scripts/build_demo_fixtures.py --supplement` against the same scale) and commit them.
- Re-run it with **Run workflow**; it is safe to repeat.

**"The public demo is shared, so it limits how often changes can be made" (HTTP 429).** The demo allows about 30 changes (approvals, reviews, decision records) and about 5 pipeline runs or re-syntheses per 10 minutes per visitor address. Wait a few minutes; the limit is in memory and also clears when the API restarts. Reading the data is never limited. To change the numbers, set `DDR_RATE_LIMIT_MUTATIONS`, `DDR_RATE_LIMIT_PIPELINE` or `DDR_RATE_LIMIT_WINDOW_SECONDS` in Render; `DDR_RATE_LIMIT=0` switches it off. The key is the first `X-Forwarded-For` address, which a determined client can forge: this protects a shared demo from loops and casual abuse, it is not a security boundary.

**Something looks wrong after visitors used it.** Run **Actions > demo-reset > Run workflow**.

**I changed `API_ORIGIN` and nothing happened.** It is read when Vercel builds the app: redeploy.

## Connection string summary

| Where | String | Why |
|---|---|---|
| Render `DATABASE_URL` | Neon **direct** (no `-pooler`), `?sslmode=require` | the tested path; at most 15 connections |
| GitHub secret `DATABASE_URL` | the same direct string | the seed uses session settings and `COPY` |
| Local `.env` | `postgresql+psycopg://...@127.0.0.1:5432/ddr` | unchanged |

`postgres://` and `postgresql://` are accepted everywhere and are converted to the `postgresql+psycopg` driver.
