"""Replay mode (D6-01, N7): the product ReplayDemoClient over backend/demo_fixtures, its provenance end to end, the mode switch,
and the failure path (a missing fixture is a recorded failure, never invented output)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from day4_support import TODAY
from day6_support import H, ok, replay_http, run_to_challenged  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import deps
from app.core.clock import FixedClock
from app.core.config import get_settings
from app.db import models as m
from app.domain.ddi import assess
from app.llm import LlmFixtureMissingError, get_llm_client
from app.llm.replay import FIXTURE_DIR, REPLAY_MODELS, ReplayDemoClient
from app.main import app
from app.repositories.evidence_facts import build_facts

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"


# ================================================================ fixtures on disk
def fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.rglob("*.json"))


def test_every_demo_fixture_is_marked_stub_not_model_output_and_names_a_stub_model():
    files = fixture_files()
    assert len(files) >= 24                     # 16 classification + 4 synthesis + 4 review
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["provenance"] == "stub_not_model_output", path.name
        assert data["model"].startswith("stub:"), path.name
        assert data["purpose"] in ("classify", "synthesize", "review") and path.parent.name == data["purpose"], path.name
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{path.name} has a BOM"


def test_classification_fixtures_are_keyed_by_a_unique_input_hash_and_the_other_purposes_by_scenario():
    classify = [json.loads(p.read_text(encoding="utf-8")) for p in (FIXTURE_DIR / "classify").glob("*.json")]
    hashes = [f["input_sha256"] for f in classify]
    assert len(classify) == 16 and len(set(hashes)) == len(hashes) and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
    assert {f["model"] for f in classify} == {"stub:keyword_rules_v1"}
    for purpose in ("synthesize", "review"):
        fx = [json.loads(p.read_text(encoding="utf-8")) for p in (FIXTURE_DIR / purpose).glob("*.json")]
        assert sorted(f["scenario_key"] for f in fx) == ["ai_coach", "community", "onboarding", "pricing"]
        assert all("input_sha256" not in f for f in fx)


def test_the_fixture_directory_is_text_for_git_and_product_code_never_imports_from_tests():
    assert "backend/demo_fixtures/**/*.json -text" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
    offenders = []
    for path in list(APP.rglob("*.py")) + [ROOT / "scripts" / "demo_prepare.py"]:
        src = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(from|import)\s+(tests|stub_classifier|replay)\b", src, re.M) or "tests/fixtures" in src or "tests\\fixtures" in src:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    assert FIXTURE_DIR == ROOT / "backend" / "demo_fixtures"


# ================================================================ the mode switch
@pytest.fixture()
def settings_env(monkeypatch):
    def set_mode(mode, key=None):
        monkeypatch.setenv("DDR_LLM_MODE", mode)
        if key is None:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ANTHROPIC_API_KEY", key)
        get_settings.cache_clear()
    yield set_mode
    monkeypatch.undo()
    get_settings.cache_clear()


def test_ddr_llm_mode_selects_the_client(settings_env):
    settings_env("off")
    assert get_llm_client() is None and deps.get_llm_models() is None
    settings_env("replay")
    client = get_llm_client()
    assert isinstance(client, ReplayDemoClient) and client.fixture_count >= 24
    assert deps.get_llm_models() == REPLAY_MODELS and all(v.startswith("stub:") for v in REPLAY_MODELS.values())
    settings_env("live")                                   # live needs a key: without one there is no client (the Day-5 behaviour)
    assert get_llm_client() is None
    settings_env("live", key="sk-test-not-a-real-key")
    from app.llm.anthropic_client import AnthropicClient
    assert isinstance(get_llm_client(), AnthropicClient) and deps.get_llm_models() is None
    settings_env("bogus")
    with pytest.raises(Exception):
        get_settings()


def test_the_test_configuration_forces_llm_mode_off_unless_a_client_is_injected():
    assert get_settings().ddr_llm_mode == "off"


def test_health_reports_the_llm_mode(session, settings_env):
    for mode in ("off", "replay"):
        settings_env(mode)
        body = TestClient(app).get("/health").json()
        assert body["status"] == "ok" and body["llm_mode"] == mode


# ================================================================ end to end on AI Coach
def test_replay_end_to_end_on_ai_coach_stores_nothing_that_claims_a_live_model(session, seed, replay_http):
    http, client = replay_http
    run = run_to_challenged(http, seed, "ai_coach", session)
    second = run["second"]
    assert second["assessment"]["state"] == "scored" and second["synthesis"]["status"] == "succeeded"
    assert second["review"]["status"] == "reviewed" and second["review"]["verdict"] == "needs_rework"
    # the pipeline response names the provenance and the model of the synthesis and of the review
    assert (second["synthesis"]["provenance"], second["synthesis"]["model"]) == ("stub_not_model_output", "stub:handauthored_synthesis_v1")
    assert (second["review"]["provenance"], second["review"]["model"]) == ("stub_not_model_output", "stub:handauthored_review_v1")
    assert run["first"]["synthesis"]["provenance"] is None                      # the first synthesis failed (no fixture): nothing to attribute
    # the stored assessment equals what the frozen engine returns for the stored facts (nothing is hard-coded)
    d = seed.decisions["ai_coach"]
    facts = build_facts(session, d.id)
    result = assess(facts, __import__("app.core.params", fromlist=["x"]).get_ddi_params(), TODAY)
    assert second["assessment"]["ddi"] == result.ddi and second["assessment"]["band"] == result.band
    # every LLM run of the decision carries the stub provenance and a stub model name
    runs = list(session.scalars(select(m.AgentRun).where(m.AgentRun.decision_id == d.id, m.AgentRun.purpose.is_not(None))))
    done = [r for r in runs if r.status == "succeeded"]
    assert {r.purpose for r in done} == {"classify", "synthesize", "review"}
    for r in done:
        assert (r.output or {}).get("provenance") == "stub_not_model_output" and r.model.startswith("stub:"), (r.purpose, r.model)
    # the pre-approval synthesis has no fixture: a recorded failure with no output, never an invented one
    failed = [r for r in runs if r.status == "failed"]
    assert failed and all(r.purpose == "synthesize" and r.error_class == "fixture_missing" and r.output is None for r in failed)
    assert {c.model for c in session.scalars(select(m.LlmClassification).where(m.LlmClassification.decision_id == d.id).limit(50))} \
        <= {REPLAY_MODELS["classify"]}
    # the API exposes it everywhere an LLM output is shown
    aid = run["assessment_id"]
    assert ok(http.get(f"/assessments/{aid}/syntheses", headers=H(seed.pm)))[0]["provenance"] == "stub_not_model_output"
    assert ok(http.get(f"/assessments/{aid}/reviews", headers=H(seed.pm)))[0]["provenance"] == "stub_not_model_output"
    cust = ok(http.get(f"/decisions/{d.id}/customer-evidence", headers=H(seed.pm)))
    assert cust["classification_counts"][0]["provenance"] == "stub_not_model_output"
    # the validators, the code findings and the lifecycle ran unchanged after the replay client
    stage = ok(http.get(f"/decisions/{d.id}", headers=H(seed.pm)))["lifecycle_stage"]
    assert stage == "challenged" and client.calls and all(c.purpose in ("classify", "synthesize", "review") for c in client.calls)


# ================================================================ a missing fixture is a recorded failure
def test_a_missing_fixture_raises_fixture_missing_and_never_invents_output(tmp_path):
    empty = ReplayDemoClient(tmp_path)
    assert empty.fixture_count == 0
    request = type("R", (), {"purpose": "classify", "prompt_version": "v0.1", "input_sha256": "0" * 64, "meta": {}})()
    with pytest.raises(LlmFixtureMissingError) as exc:
        empty.complete(request)
    assert exc.value.error_class == "fixture_missing"


def test_a_missing_classification_fixture_is_a_recorded_failure_and_proposes_no_evidence(session, seed, tmp_path):
    for sub in ("synthesize", "review"):
        shutil.copytree(FIXTURE_DIR / sub, tmp_path / sub)                         # no classify fixtures at all
    client = ReplayDemoClient(tmp_path)
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    app.dependency_overrides[deps.get_llm] = lambda: client
    app.dependency_overrides[deps.get_llm_models] = lambda: dict(REPLAY_MODELS)
    try:
        http = TestClient(app, raise_server_exceptions=False)
        d = seed.decisions["community"]
        session.refresh(d)
        body = ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    finally:
        app.dependency_overrides.clear()
    customer = next(s for s in body["stages"] if s["stage"] == "customer")
    assert customer["status"] == "partial" and customer["output"]["outcome"] == "llm_failed" and customer["output"]["error_class"] == "fixture_missing"
    assert body["pending_approvals"] == [] and body["assessment"]["state"] == "insufficient_evidence"            # the pipeline still ran
    failed = list(session.scalars(select(m.AgentRun).where(m.AgentRun.decision_id == d.id, m.AgentRun.status == "failed",
                                                          m.AgentRun.purpose == "classify")))
    assert failed and all(r.error_class == "fixture_missing" and r.output is None for r in failed)
    assert not list(session.scalars(select(m.Evidence).where(m.Evidence.decision_id == d.id, m.Evidence.evidence_type == "customer")))


def test_a_missing_synthesis_fixture_is_a_failed_synthesis_with_fixture_missing(session, seed, tmp_path):
    shutil.copytree(FIXTURE_DIR / "classify", tmp_path / "classify")                # classification works, synthesis and review do not
    client = ReplayDemoClient(tmp_path)
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    app.dependency_overrides[deps.get_llm] = lambda: client
    app.dependency_overrides[deps.get_llm_models] = lambda: dict(REPLAY_MODELS)
    try:
        http = TestClient(app, raise_server_exceptions=False)
        d = seed.decisions["onboarding"]
        session.refresh(d)
        body = ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
        aid = body["assessment"]["id"]
        syn = ok(http.get(f"/assessments/{aid}/syntheses", headers=H(seed.pm)))
        view = ok(http.get(f"/decisions/{d.id}", headers=H(seed.pm)))
    finally:
        app.dependency_overrides.clear()
    assert body["synthesis"]["status"] == "failed" and body["synthesis"]["error_class"] == "fixture_missing"
    assert body["review"]["status"] == "skipped"
    assert syn[0]["status"] == "failed" and syn[0]["output"] is None and syn[0]["provenance"] is None
    assert view["lifecycle_stage"] == "assessed"                                  # a failure never counts as a review pass


def test_a_stub_model_is_never_presented_as_live_even_without_a_stored_provenance():
    """Defence in depth (Opus verification): the `stub:` model name wins over a missing or wrong provenance field."""
    from app.services.readmodels import PROVENANCE_LIVE, PROVENANCE_STUB, provenance_of
    assert provenance_of(m.AgentRun(model="stub:keyword_rules_v1", output={"raw_text": "{}"})) == PROVENANCE_STUB
    assert provenance_of(m.AgentRun(model="stub:x", output={"raw_text": "{}", "provenance": PROVENANCE_LIVE})) == PROVENANCE_STUB
    assert provenance_of(m.AgentRun(model="claude-sonnet-5-5", output={"raw_text": "{}"})) == PROVENANCE_LIVE
    assert provenance_of(m.AgentRun(model="stub:x", output=None)) is None
