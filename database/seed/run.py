"""Seed runner: python -m database.seed.run [--users N] [--seed S] [--data-dir DIR] [--reset]

Pipeline: (1) generate SYNTHETIC CSVs if missing, (2) load fc_ tables via COPY,
(3) seed the core demo records. Requires `alembic upgrade head` first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg

from app.db.csv_loader import load_csv, to_conninfo
from data.generator import config as C
from data.generator.__main__ import LOAD_ORDER, TABLE_SPECS, write_dataset
from database.seed.core_seed import seed_core

ROOT = Path(__file__).resolve().parents[2]
FC_TABLES = {n: f"fc_.{n}" for n in LOAD_ORDER}
CORE_TRUNCATE = ("audit_logs, decision_reviews, recommendations, claim_evidence, claims, dq_checks, evidence, "
                 "analysis_results, agent_runs, decision_records, decision_assessments, customer_insights, "
                 "experiment_results, experiments, evidence_sources, decisions, metric_observations, metrics, "
                 "data_sources, users, teams, organizations")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL is not set (see .env.example)")


def main() -> None:
    p = argparse.ArgumentParser(description="Load SYNTHETIC FitConnect data and seed core demo records.")
    p.add_argument("--data-dir", default=str(ROOT / "data" / "generated"))
    p.add_argument("--users", type=int, default=C.GenConfig.users)
    p.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    p.add_argument("--reset", action="store_true", help="truncate fc_ and core tables before loading")
    p.add_argument("--regenerate", action="store_true", help="regenerate CSVs even if present")
    a = p.parse_args()
    out = Path(a.data_dir)
    t0 = time.time()

    if a.regenerate or not (out / "manifest.json").exists():
        print(f"generating synthetic data (seed={a.seed}, users={a.users}) ...", flush=True)
        write_dataset(C.GenConfig(seed=a.seed, users=a.users), out)
        print(f"  generated in {time.time() - t0:.1f}s", flush=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("synthetic"):
        raise SystemExit("refusing to load data whose manifest is not marked synthetic")

    with psycopg.connect(to_conninfo(database_url())) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        if a.reset:
            conn.execute(f"TRUNCATE {', '.join(FC_TABLES.values())}, {CORE_TRUNCATE} CASCADE")
            conn.commit()
        elif conn.execute("SELECT count(*) FROM fc_.users").fetchone()[0]:
            raise SystemExit("database already contains data. Use --reset or rebuild with alembic downgrade/upgrade")
        counts = {}
        for name in LOAD_ORDER:
            t = time.time()
            counts[name] = load_csv(conn, FC_TABLES[name], out / f"{name}.csv", TABLE_SPECS[name])
            print(f"  loaded {FC_TABLES[name]:<32} {counts[name]:>9} rows  ({time.time() - t:.1f}s)", flush=True)
        conn.commit()
        conn.autocommit = True
        for name in LOAD_ORDER:
            conn.execute(f"ANALYZE {FC_TABLES[name]}")
        conn.autocommit = False
        gt = manifest["generator_truth"]
        seed_core(conn, gt, {"ai": C.AI_EXPERIMENT, "pricing": C.PRICE_EXPERIMENT})
        print("  seeded core demo records", flush=True)
    print(json.dumps({"seconds": round(time.time() - t0, 1), "rows": counts}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
