"""Bring the four FitConnect demo decisions to their demo state through the REAL API (docs/day-6-implementation-brief.md, N8).

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/demo_prepare.py [--reset] [--as-of 2026-10-01]

Target state: AI Coach, Community and Pricing `challenged` with a scored assessment and an automated review; Onboarding `challenged`
with an INSUFFICIENT EVIDENCE (gated) assessment. The DDI values come from the pipeline; none is written here.

How it works
  * FastAPI's TestClient calls the application IN-PROCESS (no server needed) with the replay client (`ReplayDemoClient`, no API key,
    every output marked stub_not_model_output). It calls only API endpoints: pipeline runs, approvals as the business-analyst persona
    with the note "demo preparation", and the pipeline again. It never writes SQL and never calls the DDI or NBE engines.
  * Idempotent: a decision that already shows the target state is left alone (no write). A second run therefore changes nothing; the
    run reports the audit-row count and the assessment versions before and after to prove it.
  * A decision that is already `validated` or `decided` is never touched; it is reported as already advanced.
  * `--reset` first reseeds the database (`python -m database.seed.run --reset`, about 6 minutes) for a clean demo.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

NOTE = "demo preparation"
DEFAULT_AS_OF = "2026-10-01"
# The four seeded demo decisions, identified by title (the API does not expose the scenario key).
SCENARIO_TITLES = {
    "Invest in expanding the AI Coach": "AI Coach",
    "Invest in community challenges": "Community",
    "Fund a full onboarding redesign": "Onboarding",
    "Raise the premium subscription price": "Pricing",
}
ADVANCED = ("validated", "decided")


@dataclass
class Row:
    name: str
    decision_id: str
    stage: str = ""
    state: str = ""
    ddi: float | None = None
    band: str | None = None
    direction: str | None = None
    verdict: str | None = None
    note: str = ""
    writes: int = 0


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)

    @property
    def writes(self) -> int:
        return sum(r.writes for r in self.rows)

    def table(self) -> str:
        parts = []
        for r in self.rows:
            if r.state == "scored":
                shown = f"DDI {r.ddi} ({r.band})"
            elif r.state == "insufficient_evidence":
                shown = "INSUFFICIENT EVIDENCE (gated, no DDI)"
            else:
                shown = r.state or "no assessment"
            parts.append(f"{r.name}: {r.stage} | {shown} | review {r.verdict or 'none'}{' | ' + r.note if r.note else ''}")
        return "  ||  ".join(parts)


class Api:
    """The in-process API with the demo personas."""

    def __init__(self, http):
        self.http = http
        users = self.get("/users", None)
        by_role = {}
        for u in users:
            by_role.setdefault(u["role"], u["id"])
        self.ids = by_role
        missing = [r for r in ("product_analyst", "ba", "pm") if r not in by_role]
        if missing:
            raise SystemExit(f"the demo users {missing} are not seeded: run database.seed.run first")

    def headers(self, role: str | None) -> dict:
        return {} if role is None else {"X-Demo-User": self.ids[role]}

    def get(self, path: str, role: str | None = "pm"):
        r = self.http.get(path, headers=self.headers(role))
        if r.status_code != 200:
            raise SystemExit(f"GET {path} failed: {r.status_code} {r.text[:300]}")
        return r.json()

    def send(self, method: str, path: str, role: str, json=None):
        r = self.http.request(method, path, headers=self.headers(role), json=json)
        if r.status_code >= 300:
            raise SystemExit(f"{method} {path} as {role} failed: {r.status_code} {r.text[:400]}")
        return r.json()


def _snapshot(api: Api, decisions: list[dict]) -> dict:
    snap = {}
    for d in decisions:
        audit = api.get(f"/decisions/{d['id']}/audit")
        versions = [a["version"] for a in api.get(f"/decisions/{d['id']}/assessments")]
        snap[d["title"]] = {"audit_rows": len(audit), "assessment_versions": sorted(versions)}
    return snap


def _read(api: Api, decision_id: str) -> tuple[dict, list[dict]]:
    dec = api.get(f"/decisions/{decision_id}")
    cur = dec.get("current_assessment")
    reviews = api.get(f"/assessments/{cur['id']}/reviews") if cur else []
    return dec, reviews


def at_target(dec: dict, reviews: list[dict]) -> bool:
    cur = dec.get("current_assessment")
    return bool(dec["lifecycle_stage"] == "challenged" and not dec["assessment_stale"] and dec["pending_approvals"] == 0 and cur
                and cur["state"] in ("scored", "insufficient_evidence") and any(r["reviewer_type"] == "agent" for r in reviews))


def _prepare_one(api: Api, row: Row) -> None:
    for _ in range(4):
        dec, reviews = _read(api, row.decision_id)
        stage = dec["lifecycle_stage"]
        if stage in ADVANCED:
            row.note = f"already advanced ({stage}); not touched"
            return
        if at_target(dec, reviews):
            return
        did = row.decision_id
        if stage == "evidence_gathered":
            api.send("POST", f"/decisions/{did}/pipeline-runs", "product_analyst")
            row.writes += 1
            continue
        if dec["pending_approvals"] > 0:
            listing = api.get(f"/decisions/{did}/customer-evidence", "ba")
            for item in listing["items"]:
                if item["evidence"]["status"] == "proposed":
                    api.send("PATCH", f"/evidence/{item['evidence']['id']}/approval", "ba", {"action": "approve", "note": NOTE})
                    row.writes += 1
            continue
        cur = dec.get("current_assessment")
        if stage == "assessed" and cur and cur["state"] in ("scored", "insufficient_evidence") and not any(r["reviewer_type"] == "agent" for r in reviews):
            api.send("POST", f"/assessments/{cur['id']}/syntheses", "pm", {})        # the automated review did not run: run it
            row.writes += 1
            continue
        row.note = f"cannot advance automatically from '{stage}'"
        return
    row.note = row.note or "did not reach the target state"


def prepare(http) -> Report:
    """Bring the four demo decisions to their target state. `http` is a TestClient (or any client with the same interface)."""
    api = Api(http)
    decisions = [d for d in api.get("/decisions") if d["title"] in SCENARIO_TITLES]
    if len(decisions) != 4:
        raise SystemExit(f"expected the four seeded demo decisions, found {len(decisions)}: run database.seed.run first")
    order = list(SCENARIO_TITLES.values())
    decisions.sort(key=lambda d: order.index(SCENARIO_TITLES[d["title"]]))
    report = Report(before=_snapshot(api, decisions))
    for d in decisions:
        row = Row(name=SCENARIO_TITLES[d["title"]], decision_id=d["id"])
        _prepare_one(api, row)
        dec, reviews = _read(api, d["id"])
        cur = dec.get("current_assessment") or {}
        agent = [r for r in reviews if r["reviewer_type"] == "agent"]
        row.stage, row.state = dec["lifecycle_stage"], cur.get("state", "")
        row.ddi, row.band, row.direction = cur.get("ddi"), cur.get("band"), cur.get("evidence_direction")
        row.verdict = agent[-1]["verdict"] if agent else None
        if row.stage not in ADVANCED and not at_target(dec, reviews) and not row.note:
            row.note = "target state not reached"
        report.rows.append(row)
    report.after = _snapshot(api, decisions)
    return report


def _reset() -> None:
    print("reseeding the database (python -m database.seed.run --reset), about 6 minutes ...", flush=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT)])}
    subprocess.run([sys.executable, "-m", "database.seed.run", "--reset"], cwd=ROOT, env=env, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="reseed the database first (clean demo)")
    parser.add_argument("--as-of", default=os.environ.get("DDR_AS_OF_DATE") or DEFAULT_AS_OF, help="the demo as-of date (default 2026-10-01)")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    os.environ["DDR_AS_OF_DATE"] = args.as_of
    os.environ["DDR_LLM_MODE"] = "replay"
    if args.reset:
        _reset()
    from fastapi.testclient import TestClient

    from app.core import deps
    from app.llm.replay import REPLAY_MODELS, ReplayDemoClient
    from app.main import app
    client = ReplayDemoClient()
    app.dependency_overrides[deps.get_llm] = lambda: client
    app.dependency_overrides[deps.get_llm_models] = lambda: dict(REPLAY_MODELS)
    try:
        report = prepare(TestClient(app, raise_server_exceptions=False))
    finally:
        app.dependency_overrides.clear()
    print(report.table())
    unchanged = report.before == report.after
    print(f"writes this run: {report.writes}; audit rows and assessment versions "
          f"{'unchanged' if unchanged else 'CHANGED'}: {report.after}")
    if report.writes == 0 and not unchanged:
        print("ERROR: no write was made but the state changed")
        return 2
    bad = [r for r in report.rows if r.note and not r.note.startswith("already advanced")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
