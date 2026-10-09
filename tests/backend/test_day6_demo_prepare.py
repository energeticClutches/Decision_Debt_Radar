"""scripts/demo_prepare.py (N8): the real API through FastAPI's TestClient with the replay client. Target state, idempotency (no writes
the second time), no touching of an advanced decision, no hard-coded DDI and no direct SQL."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from day4_support import TODAY
from day6_support import H, ok, replay_http  # noqa: F401
from sqlalchemy import func, select

from app.core.params import get_ddi_params
from app.db import models as m
from app.domain.ddi import assess
from app.repositories.evidence_facts import build_facts

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_prepare.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_prepare", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_prepare"] = module                      # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def by_name(report):
    return {r.name: r for r in report.rows}


def test_demo_prepare_reaches_the_target_state_with_engine_values_and_a_second_run_writes_nothing(session, seed, replay_http, demo):
    http, _ = replay_http
    first = demo.prepare(http)
    rows = by_name(first)
    assert list(rows) == ["AI Coach", "Community", "Onboarding", "Pricing"]
    assert first.writes > 0 and first.before != first.after
    for name in ("AI Coach", "Community", "Pricing"):
        r = rows[name]
        assert (r.stage, r.state) == ("challenged", "scored") and r.ddi is not None and r.band in ("low", "moderate", "high", "critical")
        assert r.verdict in ("ready", "needs_rework") and r.note == ""
    onboarding = rows["Onboarding"]
    assert (onboarding.stage, onboarding.state, onboarding.ddi, onboarding.band) == ("challenged", "insufficient_evidence", None, None)
    # the values shown are the engine's: recompute them from the stored facts (nothing is hard-coded in the script)
    key = {"AI Coach": "ai_coach", "Community": "community", "Pricing": "pricing"}
    for name, scenario in key.items():
        result = assess(build_facts(session, seed.decisions[scenario].id), get_ddi_params(), TODAY)
        assert result.scored and (rows[name].ddi, rows[name].band) == (result.ddi, result.band)
    # approvals are the BA persona's, with the note "demo preparation"
    approved = list(session.scalars(select(m.Evidence).where(m.Evidence.approved_by.is_not(None))))
    assert approved and {e.approval_note for e in approved} == {"demo preparation"}
    ba_id = next(u.id for u in session.scalars(select(m.User)) if u.role == "ba")
    assert {e.approved_by for e in approved} == {ba_id}
    assert "AI Coach: challenged" in first.table() and "INSUFFICIENT EVIDENCE" in first.table()

    # idempotent: the second run makes no write (audit rows and assessment versions are unchanged)
    audit_before = session.execute(select(func.count()).select_from(m.AuditLog)).scalar_one()
    second = demo.prepare(http)
    assert second.writes == 0 and second.before == second.after == first.after
    assert session.execute(select(func.count()).select_from(m.AuditLog)).scalar_one() == audit_before
    assert [(r.stage, r.state, r.ddi, r.band, r.verdict) for r in second.rows] == [(r.stage, r.state, r.ddi, r.band, r.verdict) for r in first.rows]


def test_demo_prepare_never_touches_a_validated_or_decided_decision(session, seed, replay_http, demo):
    http, _ = replay_http
    demo.prepare(http)
    pricing, community = seed.decisions["pricing"], seed.decisions["community"]
    session.refresh(pricing)
    session.refresh(community)
    # validate Community (its review is `ready`), and carry Pricing all the way to decided
    ok(http.post(f"/decisions/{community.id}/validate", headers=H(seed.pm)))
    aid = ok(http.get(f"/decisions/{pricing.id}", headers=H(seed.pm)))["current_assessment"]["id"]
    ok(http.post(f"/assessments/{aid}/reviews", headers=H(seed.pm), json={"verdict": "ready", "human_response": "Reviewed by hand."}), 201)
    ok(http.post(f"/decisions/{pricing.id}/validate", headers=H(seed.pm)))
    ok(http.post(f"/decisions/{pricing.id}/decision-record", headers=H(seed.executive),
                 json={"outcome": "approve_conditional", "rationale": "Reviewed.", "acknowledged_risk": True}), 201)
    again = demo.prepare(http)
    rows = by_name(again)
    assert again.writes == 0 and again.before == again.after
    assert rows["Community"].stage == "validated" and rows["Community"].note.startswith("already advanced (validated)")
    assert rows["Pricing"].stage == "decided" and rows["Pricing"].note.startswith("already advanced (decided)")
    assert rows["AI Coach"].note == "" and rows["AI Coach"].stage == "challenged"


def test_demo_prepare_resumes_a_half_prepared_decision(session, seed, replay_http, demo):
    """After the first pipeline run and before the approvals the script approves and runs the pipeline again."""
    http, _ = replay_http
    d = seed.decisions["community"]
    session.refresh(d)
    ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    report = demo.prepare(http)
    row = by_name(report)["Community"]
    assert (row.stage, row.state) == ("challenged", "scored") and row.writes >= 4          # 3 approvals and a pipeline run


def test_demo_prepare_uses_only_the_api_no_sql_no_engines_and_no_literal_ddi():
    src = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b\s+(INTO|\w+\s+SET|FROM)", src, re.I) and ".execute(" not in src
    assert not re.search(r"^\s*(from|import)\s+(sqlalchemy|psycopg|app\.domain|app\.db|app\.repositories|app\.services)\b", src, re.M)
    assert "app.domain.ddi" not in src and "app.domain.nbe" not in src
    # the only numbers in the code are the as-of date and loop counts: no DDI value or band threshold
    code = "\n".join(l.split("#")[0] for l in src.split("\n") if not l.strip().startswith(('"""', "#")))
    assert not re.search(r"\b\d{2,3}\.\d\b", code)
    assert '"demo preparation"' in src and "ReplayDemoClient" in src and "TestClient" in src
    assert src.encode("utf-8")[:3] != b"\xef\xbb\xbf"
