"""Record or check the golden snapshot of the evaluation suite (docs/day-7-implementation-brief.md D7-01).

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_snapshot.py --write     # (re)generate tests/evals/golden/observed.json
    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_snapshot.py --check     # compare the current engine output with the snapshot
    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_snapshot.py --show      # run every spec and print the observation

No band is chosen in advance: the snapshot holds what the FROZEN DDI and NBE engines returned for each spec, run on a rolled-back
transaction (nothing is written to the demo database). The file is never edited by hand; a changed engine output is a deliberate act that
needs this command and the Product Owner's approval. Every spec and every value is SYNTHETIC.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT), str(ROOT / "tests" / "evals")]

import eval_harness  # noqa: E402

eval_harness.setup_path()
import eval_runner as er  # noqa: E402


def run_all(specs=None):
    results = []
    for spec in specs or er.load_specs():
        with eval_harness.rolled_back_session() as (session, seed):
            results.append(er.run_spec(session, seed, spec))
    return results


def build_snapshot(results) -> dict:
    return {"header": er.GOLDEN_HEADER.format(date=date.today().isoformat()), "synthetic": True,
            "specs": {r.spec_id: r.golden for r in results if r.golden is not None and r.error is None}}


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--show", action="store_true")
    ap.add_argument("--only", help="comma-separated spec ids")
    args = ap.parse_args()
    specs = er.load_specs()
    if args.only:
        wanted = set(args.only.split(","))
        specs = [s for s in specs if s["id"] in wanted]
    results = run_all(specs)
    errors = [r for r in results if r.error]
    for r in results:
        print(f"{r.spec_id:<40} {er.observed_summary(r)}")
    for r in results:
        for c in r.checks:
            if not c.ok and not c.name.startswith("golden"):
                print(f"  FAIL {r.spec_id}: {c.name} expected {c.expected!r} observed {c.observed!r} {c.note}")
    if errors:
        print(f"\n{len(errors)} spec(s) could not run; the snapshot is not written.")
        return 1
    if args.show:
        return 0
    new = build_snapshot(results)
    if args.write:
        if args.only:
            print("--write needs every spec (no --only)")
            return 1
        path = er.GOLDEN_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {path} ({len(new['specs'])} specs)")
        return 0
    old = er.load_golden().get("specs", {})
    drift = {k: (old.get(k), v) for k, v in new["specs"].items() if old.get(k) != v}
    for k, (was, now) in drift.items():
        print(f"DRIFT {k}\n  snapshot: {was}\n  observed: {now}")
    print("snapshot matches the engine" if not drift else f"{len(drift)} spec(s) drifted")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
