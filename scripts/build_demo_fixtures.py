"""Generate the replay-mode classification fixtures (docs/day-6-implementation-brief.md section 2). A DEV TOOL, never imported by product code.

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/build_demo_fixtures.py [--as-of 2026-10-01] [--check]

What it does:
  * runs Stage 3 of the pipeline for the four seeded scenarios inside a database transaction that is ROLLED BACK at the end (nothing
    is committed), with the deterministic keyword-rule STUB classifier (tests/fixtures/llm/stub_classifier.py) recording every call
  * writes one fixture per classification request to backend/demo_fixtures/classify/, keyed by the request's `input_sha256`
  * every file carries "provenance": "stub_not_model_output" and the model "stub:keyword_rules_v1": the output is NOT model output
  * then replays the four scenarios in a second rolled-back transaction with the product `ReplayDemoClient` and fails if any
    classification request at the as-of date has no fixture (`--check` runs only this verification)

The synthesis and review fixtures (backend/demo_fixtures/synthesize and review) are copies of the hand-authored Day-5 scenario fixtures
and are not regenerated here. The script reads the database only through the product services (the feedback view, never the
evaluation ground truth).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT), str(ROOT / "tests" / "fixtures" / "llm")]

SCENARIOS = ("ai_coach", "community", "onboarding", "pricing")
OUT = ROOT / "backend" / "demo_fixtures" / "classify"
DEFAULT_AS_OF = date(2026, 10, 1)             # the as-of date of the seed and of the demo (DDR_AS_OF_DATE)


class RecordingClassifier:
    """Wraps the stub classifier and keeps every classification request and response."""

    def __init__(self, inner):
        self.inner, self.records = inner, []

    def complete(self, request):
        from app.llm.client import LlmError
        if request.purpose != "classify":
            raise LlmError("the fixture builder only serves classification requests")
        response = self.inner.complete(request)
        self.records.append((request, response))
        return response


def _context(session, client, as_of):
    from app.core.clock import FixedClock
    from app.core.params import get_analytics_params, get_ddi_params, get_nbe_params, get_tenant_config
    from app.llm.replay import REPLAY_MODELS
    from app.services import ServiceContext
    return ServiceContext(session, FixedClock(as_of), get_ddi_params(), get_nbe_params(), analytics_params=get_analytics_params(),
                          tenant=get_tenant_config(), llm=client, llm_models=dict(REPLAY_MODELS))


def _open():
    from sqlalchemy.orm import Session

    from app.db.session import get_engine
    conn = get_engine().connect()
    outer = conn.begin()
    return conn, outer, Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


def _actor_and_decisions(session):
    from sqlalchemy import select

    from app.db import models as m
    from app.domain.permissions import Actor
    users = {u.email.split("@")[0]: u for u in session.scalars(select(m.User))}
    u = users["pa1"]
    analyst = Actor(str(u.id), str(u.org_id), str(u.team_id) if u.team_id else None, u.role, u.name)
    decisions = {d.scenario_key: d for d in session.scalars(select(m.Decision)) if d.scenario_key}
    missing = [s for s in SCENARIOS if s not in decisions]
    if missing:
        raise SystemExit(f"the database has no seeded scenario(s) {missing}: run database.seed.run first")
    return analyst, decisions


def record(as_of: date) -> list[dict]:
    """Run Stage 3 with the recording stub and return the fixtures (one per distinct classification request)."""
    from stub_classifier import MODEL, StubClassifierClient

    from app.llm.client import PROVENANCE_STUB
    from app.llm.prompts import load_prompt
    from app.services import PipelineService

    conn, outer, session = _open()
    fixtures: dict[str, dict] = {}
    try:
        analyst, decisions = _actor_and_decisions(session)
        prompt = load_prompt("classify")
        for scenario in SCENARIOS:
            client = RecordingClassifier(StubClassifierClient())
            PipelineService(_context(session, client, as_of)).run(analyst, decisions[scenario].id)
            for n, (request, response) in enumerate(client.records, start=1):
                sha = request.input_sha256
                fixtures.setdefault(sha, {
                    "fixture_id": f"classify_{scenario}_{n:02d}_{sha[:12]}", "purpose": "classify", "prompt_version": prompt.version,
                    "input_sha256": sha, "provenance": PROVENANCE_STUB, "model": MODEL, "scenario_key": scenario,
                    "note": ("NOT MODEL OUTPUT. Produced by the deterministic keyword-rule stub (tests/fixtures/llm/stub_classifier.py) "
                             "for the classification request with this input hash, by scripts/build_demo_fixtures.py. Synthetic data."),
                    "output": json.loads(response.text)})
            print(f"  {scenario}: {len(client.records)} classification request(s)")
    finally:
        session.close()
        outer.rollback()
        conn.close()
    return list(fixtures.values())


def verify(as_of: date) -> int:
    """Replay the four scenarios with the product ReplayDemoClient: every classification request must have a fixture."""
    from app.llm.replay import ReplayDemoClient
    from app.services import PipelineService

    conn, outer, session = _open()
    problems = 0
    try:
        analyst, decisions = _actor_and_decisions(session)
        for scenario in SCENARIOS:
            client = ReplayDemoClient()
            result = PipelineService(_context(session, client, as_of)).run(analyst, decisions[scenario].id)
            customer = next(s for s in result.stages if s["stage"] == "customer")
            calls = [c for c in client.calls if c.purpose == "classify"]
            ok = customer["status"] == "succeeded" and customer["output"].get("outcome") == "completed"
            problems += 0 if ok else 1
            print(f"  {scenario}: {len(calls)} classification request(s), stage {customer['status']} ({customer['output'].get('outcome')})"
                  f"{'' if ok else '  <-- MISSING FIXTURE: ' + str(customer['output'].get('error'))}")
    finally:
        session.close()
        outer.rollback()
        conn.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--as-of", default=DEFAULT_AS_OF.isoformat())
    parser.add_argument("--check", action="store_true", help="only verify that every classification request has a fixture")
    parser.add_argument("--supplement", action="store_true",
                        help="deploy profile: record against the CURRENT database (for example the 20,000-user hosted-demo scale) and write only the "
                             "requests that have no fixture yet to backend/demo_fixtures_deploy/classify; existing fixtures are never touched")
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of)
    if args.supplement:
        from app.llm.replay import DEPLOY_FIXTURE_DIR, FIXTURE_DIR
        have = {json.loads(p.read_text(encoding="utf-8")).get("input_sha256")
                for d in (FIXTURE_DIR, DEPLOY_FIXTURE_DIR) for p in d.rglob("*.json")}
        print(f"recording classification requests at {as_of} (supplement) ...")
        fresh = [f for f in record(as_of) if f["input_sha256"] not in have]
        out = DEPLOY_FIXTURE_DIR / "classify"
        out.mkdir(parents=True, exist_ok=True)
        for f in fresh:
            (out / f"{f['fixture_id']}.json").write_bytes((json.dumps(f, indent=1, sort_keys=True, ensure_ascii=False) + chr(10)).encode("utf-8"))
        print(f"wrote {len(fresh)} supplementary fixture(s) to {out}")
    elif not args.check:
        print(f"recording classification requests at {as_of} ...")
        fixtures = record(as_of)
        OUT.mkdir(parents=True, exist_ok=True)
        for old in OUT.glob("*.json"):
            old.unlink()
        for f in fixtures:
            (OUT / f"{f['fixture_id']}.json").write_bytes((json.dumps(f, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"wrote {len(fixtures)} fixture(s) to {OUT}")
    print("verifying with ReplayDemoClient ...")
    problems = verify(as_of)
    print("OK: every classification request has a fixture" if problems == 0 else f"FAILED: {problems} scenario(s) lack fixtures")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
