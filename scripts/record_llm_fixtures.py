"""Record LIVE model outputs as fixtures (docs/day-5-implementation-brief.md section 2, P2). NOT run on Day 5: no API key exists.

    ANTHROPIC_API_KEY=... python scripts/record_llm_fixtures.py --out tests/fixtures/llm/recorded_live

What it does (only when ANTHROPIC_API_KEY is set; it refuses otherwise):
  * opens a database transaction that is ROLLED BACK at the end (nothing is committed), runs the full Day-5 path for each seeded
    scenario with the live client: pipeline (classification and proposals), approval of every proposed item (a demo business analyst),
    pipeline again (assessment, synthesis, review)
  * records every call as a fixture with "provenance": "recorded_model_output" and the answering model name
  * classification fixtures are keyed by `input_sha256` (the classification input has no database ids, so the hash replays exactly)
  * synthesis and review fixtures are keyed by scenario: evidence ids are random per run, so every id in the recorded output is
    replaced by a symbolic selector (@type:theme-or-analysis) that RecordedClient resolves against the new request

It never reads the evaluation ground-truth labels and never writes into the committed hand-authored fixtures
(tests/fixtures/llm/recorded). Review the written files before committing them: they are real model output about SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

SCENARIOS = ("ai_coach", "community", "onboarding", "pricing")
PROVENANCE = "recorded_model_output"


def selector_map(index: list[dict]) -> dict[str, str]:
    """evidence id -> symbolic selector, unique per request."""
    out: dict[str, str] = {}
    for e in index:
        key = e.get("theme") or e.get("analysis_type") or ""
        out[str(e["id"])] = f"@{e['evidence_type']}" + (f":{key}" if key else "")
    if len(set(out.values())) != len(out):
        raise SystemExit("ambiguous evidence selectors: two items share a type and key")
    return out


def replace_ids(value, mapping: dict[str, str]):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [replace_ids(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: replace_ids(v, mapping) for k, v in value.items()}
    return value


class RecordingClient:
    def __init__(self, inner, out_dir: Path, scenario: str):
        self.inner, self.out_dir, self.scenario, self.n = inner, out_dir, scenario, 0

    def complete(self, request):
        response = self.inner.complete(request)
        self.n += 1
        fixture = {"fixture_id": f"{self.scenario}_{request.purpose}_{self.n}", "provenance": PROVENANCE, "model": response.model,
                   "purpose": request.purpose, "prompt_version": request.prompt_version, "request_id": response.request_id,
                   "note": "Recorded from a live model call about SYNTHETIC data by scripts/record_llm_fixtures.py."}
        if request.purpose == "classify":
            fixture["input_sha256"] = request.input_sha256
            fixture["output_text"] = response.text
        else:
            fixture["scenario_key"] = self.scenario
            fixture["input_sha256_recorded"] = request.input_sha256
            if (request.meta or {}).get("variant"):
                fixture["variant"] = request.meta["variant"]
            try:
                fixture["output"] = replace_ids(json.loads(response.text), selector_map(list(request.meta.get("evidence_index") or [])))
            except ValueError:
                fixture["output_text"] = response.text
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{fixture['fixture_id']}.json").write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=str(ROOT / "tests" / "fixtures" / "llm" / "recorded_live"))
    args = parser.parse_args(argv)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ANTHROPIC_API_KEY is not set: refusing to run. This script makes live model calls and is never part of CI.")
        return 2
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.core.clock import FixedClock
    from app.core.params import get_analytics_params, get_ddi_params, get_nbe_params, get_tenant_config
    from app.db import models as m
    from app.db.session import get_engine
    from app.domain.permissions import Actor
    from app.llm.anthropic_client import AnthropicClient
    from app.services import CustomerEvidenceService, PipelineService, ServiceContext

    engine = get_engine()
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        users = {u.email.split("@")[0]: u for u in session.scalars(select(m.User))}

        def actor(k):
            u = users[k]
            return Actor(str(u.id), str(u.org_id), str(u.team_id) if u.team_id else None, u.role, u.name)
        analyst, ba = actor("pa1"), actor("ba1")
        for scenario in SCENARIOS:
            decision = session.scalars(select(m.Decision).where(m.Decision.scenario_key == scenario)).one()
            client = RecordingClient(AnthropicClient(key), Path(args.out), scenario)
            ctx = ServiceContext(session, FixedClock(date(2026, 10, 1)), get_ddi_params(), get_nbe_params(),
                                 analytics_params=get_analytics_params(), tenant=get_tenant_config(), llm=client)
            PipelineService(ctx).run(analyst, decision.id)
            svc = CustomerEvidenceService(ctx)
            for ev in session.scalars(select(m.Evidence).where(m.Evidence.decision_id == decision.id, m.Evidence.status == "proposed")):
                svc.set_approval(ba, ev.id, "approve", "approved while recording fixtures")
            session.refresh(decision)
            PipelineService(ctx).run(analyst, decision.id)
            print(f"{scenario}: recorded {client.n} call(s) into {args.out}")
    finally:
        session.close()
        outer.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
