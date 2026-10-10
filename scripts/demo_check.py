"""Preflight for the demo (docs/day-7-implementation-brief.md section 6). READ-ONLY: it changes nothing.

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/demo_check.py

Checks, each printed as PASS, FAIL or SKIP with the exact fix command:
  1. Docker is running and the database container is healthy on 127.0.0.1:5432
  2. Alembic is at head
  3. the synthetic seed is present (the manifest row counts)
  4. the demo state: the four decisions at their target stage (AI Coach, Community and Pricing scored and challenged; Onboarding
     challenged with INSUFFICIENT EVIDENCE and no DDI)
  5. the API answers /health (and reports llm_mode); SKIP if it is not running
  6. the frontend answers on 127.0.0.1:3000; SKIP if it is not running

Exit code 1 if any check FAILS. Everything it looks at is SYNTHETIC (FitConnect is a fictional company).
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

PY = "backend/.venv/Scripts/python"
FIX_DB = "docker compose up -d db   (if Docker Desktop is stopped, start it first and wait for `docker info`)"
FIX_MIGRATE = f'cd database && PYTHONPATH="../backend;.." ../{PY} -m alembic -c alembic.ini upgrade head'
FIX_SEED = f'PYTHONPATH="backend;." {PY} -m database.seed.run --reset'
FIX_DEMO = f'PYTHONPATH="backend;." DDR_LLM_MODE=replay {PY} scripts/demo_prepare.py --reset'
FIX_API = f'DDR_LLM_MODE=replay DDR_AS_OF_DATE=2026-10-01 PYTHONPATH="backend;." {PY} -m uvicorn app.main:app --host 127.0.0.1 --port 8000'
FIX_WEB = "cd frontend && npm run build && npx next start -H 127.0.0.1 -p 3000"

TARGETS = {  # title -> (state, scored)
    "Invest in expanding the AI Coach": ("scored", True),
    "Invest in community challenges": ("scored", True),
    "Fund a full onboarding redesign": ("insufficient_evidence", False),
    "Raise the premium subscription price": ("scored", True),
}

results: list[tuple[str, str, str, str]] = []


def record(status: str, name: str, detail: str, fix: str = "") -> None:
    results.append((status, name, detail, fix))
    print(f"{status:<5} {name}: {detail}" + (f"\n        fix: {fix}" if status == "FAIL" and fix else ""))


def check_docker() -> None:
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return record("FAIL", "docker", f"docker is not available ({exc.__class__.__name__})", FIX_DB)
    if info.returncode != 0:
        return record("FAIL", "docker", "the Docker daemon is not running", FIX_DB)
    ps = subprocess.run(["docker", "compose", "ps", "--format", "json", "db"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    rows = []
    for line in ps.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if not rows:
        # another compose project (or a local PostgreSQL) may own the database: what matters is that 127.0.0.1:5432 answers
        try:
            import socket
            socket.create_connection(("127.0.0.1", 5432), timeout=3).close()
            return record("PASS", "docker and database container", "Docker is running; PostgreSQL answers on 127.0.0.1:5432 (not managed by this compose project)")
        except OSError:
            return record("FAIL", "database container", "the db service is not running", FIX_DB)
    health = rows[0].get("Health") or rows[0].get("Status", "")
    if "healthy" not in str(health) and "healthy" not in str(rows[0].get("Status", "")):
        return record("FAIL", "database container", f"the db service is {rows[0].get('State')} but not healthy", FIX_DB)
    record("PASS", "docker and database container", "Docker is running and db is healthy on 127.0.0.1:5432")


def connect():
    from sqlalchemy import create_engine

    from app.core.config import get_settings
    url = get_settings().database_url
    if "localhost" in url:
        record("FAIL", "database url", "DATABASE_URL uses localhost; use 127.0.0.1", "edit .env: DATABASE_URL=...@127.0.0.1:5432/ddr")
    return create_engine(url, future=True, connect_args={"connect_timeout": 5})


def check_database() -> None:
    from sqlalchemy import text
    engine = connect()
    try:
        with engine.connect() as c:
            current = c.execute(text("select version_num from alembic_version")).scalar()
            heads = sorted(p.stem.split("_")[0] for p in (ROOT / "database" / "migrations" / "versions").glob("[0-9]*.py"))
            if current != heads[-1]:
                record("FAIL", "alembic", f"database is at {current}, head is {heads[-1]}", FIX_MIGRATE)
            else:
                record("PASS", "alembic", f"at head ({current})")
            mpath = ROOT / "data" / "generated" / "manifest.json"
            if not mpath.exists():                                  # data/generated is git-ignored: fall back to the tracked copy
                mpath = ROOT / "data" / "manifest" / "fitconnect_manifest.json"
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            bad = []
            for table, want in manifest["row_counts"].items():
                got = c.execute(text(f"select count(*) from fc_.{table}")).scalar()
                if got != want:
                    bad.append(f"{table} {got} != {want}")
            if bad:
                record("FAIL", "seed", "row counts differ from the manifest: " + "; ".join(bad), FIX_SEED)
            else:
                record("PASS", "seed", f"{len(manifest['row_counts'])} tables match the manifest row counts (synthetic data)")
            rows = {r[0]: r for r in c.execute(text(
                "select d.title, d.lifecycle_stage, d.assessment_stale, a.state from decisions d left join lateral "
                "(select x.state from decision_assessments x where x.decision_id = d.id order by x.version desc limit 1) a on true"))}
            problems = []
            for title, (state, _scored) in TARGETS.items():
                r = rows.get(title)
                if r is None:
                    problems.append(f"{title}: missing")
                elif r[1] != "challenged" or r[2] or r[3] != state:
                    problems.append(f"{title}: stage {r[1]}, state {r[3]}, stale {r[2]}")
            if problems:
                record("FAIL", "demo state", "; ".join(problems), FIX_DEMO)
            else:
                record("PASS", "demo state", "the four decisions are challenged (Onboarding: INSUFFICIENT EVIDENCE, no DDI)")
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "database", f"cannot read the database: {str(exc).splitlines()[0][:160]}", FIX_DB)
    finally:
        engine.dispose()


def http(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None, ""


def check_servers() -> None:
    status, body = http("http://127.0.0.1:8000/health")
    if status is None:
        record("SKIP", "api", "not running on 127.0.0.1:8000", FIX_API)
    else:
        try:
            health = json.loads(body)
            mode = health.get("llm_mode")
            record("PASS" if status == 200 and mode else "FAIL", "api", f"/health {status}, llm_mode={mode}"
                   + ("" if mode == "replay" else " (the demo expects replay)"), FIX_API)
        except ValueError:
            record("FAIL", "api", "/health did not return JSON", FIX_API)
    status, _ = http("http://127.0.0.1:3000/")
    if status is None:
        record("SKIP", "frontend", "not running on 127.0.0.1:3000", FIX_WEB)
    else:
        record("PASS" if status == 200 else "FAIL", "frontend", f"/ answered {status}", FIX_WEB)


def main() -> int:
    print("Decision Debt Radar demo preflight (read-only). All data is synthetic.\n")
    check_docker()
    if any(r[0] == "FAIL" and r[1] in ("docker", "database container") for r in results):
        record("SKIP", "database checks", "skipped because the database container is not available")
    else:
        check_database()
    check_servers()
    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(1 for r in results if r[0] == 'PASS')} passed, {len(fails)} failed, {sum(1 for r in results if r[0] == 'SKIP')} skipped")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
