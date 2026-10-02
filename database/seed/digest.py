"""Deterministic digest of the loaded database, for fixed-seed reproducibility checks.

python -m database.seed.digest

Order-independent checksums (sum of per-row hashes) over every fc_ table and the seeded core
tables, plus the value of every manifest check. Timestamps that depend on wall-clock time
(created_at / updated_at) and nothing else non-deterministic are excluded.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import psycopg

from app.db.csv_loader import to_conninfo
from data.generator.__main__ import LOAD_ORDER
from database.seed.run import ROOT, database_url
from database.seed.validate import run_checks

CORE = ["organizations", "teams", "users", "data_sources", "metrics", "metric_observations", "decisions",
        "evidence_sources", "experiments", "audit_logs"]


def compute(conn: psycopg.Connection, manifest: dict) -> dict:
    out: dict = {"tables": {}, "checks": {}}
    for name in LOAD_ORDER:
        row = conn.execute(
            f"SELECT count(*), COALESCE(sum(hashtextextended(t::text, 0)::numeric), 0) FROM fc_.{name} t").fetchone()
        out["tables"][f"fc_.{name}"] = [row[0], str(row[1])]
    for name in CORE:
        row = conn.execute(
            f"SELECT count(*), COALESCE(sum(hashtextextended((to_jsonb(t) - 'created_at' - 'updated_at')::text, 0)::numeric), 0) "
            f"FROM {name} t").fetchone()
        out["tables"][name] = [row[0], str(row[1])]
    for r in run_checks(conn, manifest):
        out["checks"][r["id"]] = r["value"]
    out["sha256"] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return out


def main() -> int:
    manifest = json.loads((ROOT / "data" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    with psycopg.connect(to_conninfo(database_url())) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute("SELECT set_config('ddr.as_of', '2026-10-01', false)")
        result = compute(conn, manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
