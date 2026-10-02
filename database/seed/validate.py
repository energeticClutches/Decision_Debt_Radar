"""Validate the loaded SYNTHETIC data against the defect/pattern manifest.

python -m database.seed.validate [--manifest data/generated/manifest.json]
Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

from app.db.csv_loader import to_conninfo
from database.seed.run import ROOT, database_url


def evaluate(op: str, value: float, bound) -> bool:
    if op == ">=":
        return value >= bound
    if op == "<=":
        return value <= bound
    if op == "<":
        return value < bound
    if op == "==":
        return value == bound
    if op == "between":
        return bound[0] <= value <= bound[1]
    raise ValueError(op)


def run_checks(conn: psycopg.Connection, manifest: dict) -> list[dict]:
    results = []
    for chk in manifest["checks"]:
        value = conn.execute(chk["sql"]).fetchone()[0]
        value = float(value) if value is not None else None
        ok = value is not None and evaluate(chk["op"], value, chk["bound"])
        results.append({"id": chk["id"], "scenario": chk["scenario"], "description": chk["description"],
                        "value": None if value is None else round(value, 4), "op": chk["op"],
                        "bound": chk["bound"], "passed": ok})
    return results


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default=str(ROOT / "data" / "generated" / "manifest.json"))
    a = p.parse_args()
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    with psycopg.connect(to_conninfo(database_url())) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        results = run_checks(conn, manifest)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<8} {r['value']!s:>10}  {r['op']} {r['bound']!s:<12} {r['description']}")
    failed = [r for r in results if not r["passed"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} manifest checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
