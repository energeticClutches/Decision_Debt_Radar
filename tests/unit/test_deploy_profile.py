"""Deploy profile (free full-stack hosting): URL normalisation, the production settings, the in-process rate limit, the request log and
the 'no stack trace in a response' rule. None of this needs the database."""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import PRODUCTION_AS_OF, Settings, normalise_database_url
from app.core.errors import install_error_handlers
from app.core.middleware import RequestMiddleware, configure_request_logging, log
from app.core.ratelimit import SlidingWindowLimiter, client_key

ENV_KEYS = ("DDR_ENV", "APP_ENV", "DDR_LLM_MODE", "DDR_AS_OF_DATE", "DATABASE_URL", "DDR_RATE_LIMIT", "DDR_LOG_REQUESTS", "DDR_TRUST_FORWARDED_FOR")


def settings(monkeypatch, **env) -> Settings:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


# ---------------------------------------------------------------- database URL
@pytest.mark.parametrize("given,expected", [
    ("postgres://u:p@ep-x.neon.tech/db?sslmode=require", "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@127.0.0.1:5432/ddr", "postgresql+psycopg://u:p@127.0.0.1:5432/ddr"),
    ("  postgres://u:p@h/db  ", "postgresql+psycopg://u:p@h/db"),
])
def test_database_url_is_normalised_to_the_psycopg_driver(given, expected):
    assert normalise_database_url(given) == expected


def test_settings_normalise_the_database_url_from_the_environment(monkeypatch):
    s = settings(monkeypatch, DATABASE_URL="postgres://owner:pw@ep-cool-123.eu-central-1.aws.neon.tech/neondb?sslmode=require")
    assert s.database_url.startswith("postgresql+psycopg://owner:pw@ep-cool-123") and s.database_url.endswith("?sslmode=require")


def test_conninfo_for_the_seed_accepts_provider_urls():
    from app.db.csv_loader import to_conninfo
    assert to_conninfo("postgres://u:p@h/db?sslmode=require") == "postgresql://u:p@h/db?sslmode=require"
    assert to_conninfo("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"


# ---------------------------------------------------------------- production settings
def test_local_defaults_are_unchanged(monkeypatch):
    s = settings(monkeypatch)
    assert not s.is_production and s.app_env == "local" and s.ddr_as_of_date is None and s.ddr_llm_mode == "replay"
    assert not s.rate_limit_enabled and not s.log_requests and not s.trust_forwarded_for


def test_production_pins_replay_mode_and_the_as_of_date_and_turns_on_the_guards(monkeypatch):
    s = settings(monkeypatch, DDR_ENV="production", DDR_LLM_MODE="live")
    assert s.is_production and s.ddr_llm_mode == "replay"                 # never live, whatever the environment says
    assert s.ddr_as_of_date == PRODUCTION_AS_OF and s.ddr_as_of_date.isoformat() == "2026-10-01"
    assert s.rate_limit_enabled and s.log_requests and s.trust_forwarded_for
    assert settings(monkeypatch, DDR_ENV="production", DDR_AS_OF_DATE="2026-11-02").ddr_as_of_date.isoformat() == "2026-11-02"
    assert not settings(monkeypatch, DDR_ENV="production", DDR_RATE_LIMIT="0").rate_limit_enabled
    assert settings(monkeypatch, APP_ENV="production").is_production                   # the older variable name still works


# ---------------------------------------------------------------- rate limit
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_mutations_are_limited_per_window_and_reads_are_not():
    clock = Clock()
    lim = SlidingWindowLimiter(600, 30, 5, clock=clock)
    assert all(lim.check("1.1.1.1", "GET", "/decisions").allowed for _ in range(200))
    results = [lim.check("1.1.1.1", "PATCH", "/evidence/x/approval").allowed for _ in range(31)]
    assert results[:30] == [True] * 30 and results[30] is False
    assert lim.check("2.2.2.2", "PATCH", "/evidence/x/approval").allowed                   # another address has its own budget
    refused = lim.check("1.1.1.1", "POST", "/decisions")
    assert not refused.allowed and 1 <= refused.retry_after <= 601 and refused.scope == "mutation"
    clock.t += 601
    assert lim.check("1.1.1.1", "POST", "/decisions").allowed                              # the window has drained


def test_pipeline_runs_and_resynthesis_have_the_smaller_budget():
    lim = SlidingWindowLimiter(600, 30, 5, clock=Clock())
    paths = ["/decisions/abc/pipeline-runs", "/assessments/abc/syntheses"]
    for path in paths:
        key = f"ip-{path}"
        results = [lim.check(key, "POST", path).allowed for _ in range(6)]
        assert results == [True] * 5 + [False], path
    assert lim.check("fresh", "GET", "/decisions/abc/pipeline-runs").allowed
    assert lim.classify("POST", "/assessments/abc/syntheses/") == ["mutation", "pipeline"]
    assert lim.classify("POST", "/assessments/abc/briefs") == ["mutation"]


def test_a_zero_limit_is_off():
    lim = SlidingWindowLimiter(600, 0, 0, clock=Clock())
    assert all(lim.check("ip", "POST", "/decisions/x/pipeline-runs").allowed for _ in range(100))


def test_the_client_key_is_the_first_forwarded_address_only_when_trusted():
    headers = [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.2, 10.0.0.3")]
    assert client_key(headers, "10.0.0.3", True) == "203.0.113.9"
    assert client_key(headers, "10.0.0.3", False) == "10.0.0.3"
    assert client_key([], "10.0.0.3", True) == "10.0.0.3"


# ---------------------------------------------------------------- middleware and error body
def app_with(limiter, *, log_requests=True) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/things")
    def create():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail /srv/app/x.py")

    s = Settings(_env_file=None)
    s.ddr_trust_forwarded_for = True
    app.add_middleware(RequestMiddleware, settings=s, limiter=limiter, log_requests=log_requests)
    return app


def test_the_burst_gets_429_with_the_api_error_shape_and_retry_after():
    client = TestClient(app_with(SlidingWindowLimiter(600, 3, 5)))
    headers = {"X-Forwarded-For": "198.51.100.7"}
    codes = [client.post("/things", headers=headers).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    refused = client.post("/things", headers=headers)
    body = refused.json()
    assert set(body) == {"error"} and body["error"]["code"] == "rate_limited"
    assert "wait" in body["error"]["message"].lower() and body["error"]["detail"]["retry_after_seconds"] >= 1
    assert int(refused.headers["retry-after"]) >= 1
    assert client.post("/things", headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 200      # another address
    assert client.get("/health", headers=headers).status_code == 200                                    # reads are never limited


def test_one_json_log_line_per_request_without_headers_or_query():
    stream = io.StringIO()
    for h in list(log.handlers):
        log.removeHandler(h)
    configure_request_logging(stream=stream)
    try:
        client = TestClient(app_with(None))
        client.get("/health?token=should-not-be-logged", headers={"X-Demo-User": "some-user-id", "X-Forwarded-For": "198.51.100.7"})
        client.post("/things")
        lines = [json.loads(x) for x in stream.getvalue().splitlines()]
        assert [(x["method"], x["path"], x["status"]) for x in lines] == [("GET", "/health", 200), ("POST", "/things", 200)]
        assert all(isinstance(x["ms"], (int, float)) for x in lines) and lines[0]["ip"] == "198.51.100.7"
        raw = stream.getvalue()
        assert "should-not-be-logged" not in raw and "some-user-id" not in raw
    finally:
        for h in list(log.handlers):
            log.removeHandler(h)
        log.propagate = True
        log.setLevel(logging.NOTSET)


def test_an_unexpected_error_is_a_json_500_without_a_stack_trace_or_message():
    client = TestClient(app_with(None, log_requests=False), raise_server_exceptions=False)
    res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body == {"error": {"code": "internal_error", "message": "Something went wrong on the server. Please retry.", "detail": None}}
    assert "secret" not in res.text and "Traceback" not in res.text and ".py" not in res.text


# ---------------------------------------------------------------- replay fixtures of the deploy data scale
def test_deploy_fixtures_are_stub_marked_and_a_synthesis_fixture_applies_only_to_its_own_sample_sizes():
    from app.llm.client import LlmRequest
    from app.llm.replay import DEPLOY_FIXTURE_DIR, FIXTURE_DIR, REPLAY_MODELS, ReplayDemoClient

    files = sorted(DEPLOY_FIXTURE_DIR.rglob("*.json"))
    assert len(files) == 12                                              # 8 classification requests and 4 synthesis fixtures
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["provenance"] == "stub_not_model_output" and data["model"].startswith("stub:"), path.name
        assert data["purpose"] in ("classify", "synthesize") and path.parent.name == data["purpose"], path.name
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name
    base_hashes = {json.loads(p.read_text(encoding="utf-8")).get("input_sha256") for p in (FIXTURE_DIR / "classify").glob("*.json")}
    deploy_hashes = {json.loads(p.read_text(encoding="utf-8"))["input_sha256"] for p in (DEPLOY_FIXTURE_DIR / "classify").glob("*.json")}
    assert deploy_hashes and not (base_hashes & deploy_hashes)           # supplements only: no base fixture is overridden

    client = ReplayDemoClient()

    def request(sizes):
        return LlmRequest(purpose="synthesize", model=REPLAY_MODELS["synthesize"], system="s", user="u",
                          input_obj={"evidence": [{"n_sample": n} for n in sizes]}, input_sha256="0" * 64, prompt_id="synthesize",
                          prompt_version="v0.1", prompt_sha256="0" * 64, max_output_tokens=1, temperature=0.0, timeout_s=1, max_retries=0,
                          meta={"scenario_key": "onboarding", "evidence_index": []})

    scaled = json.loads((DEPLOY_FIXTURE_DIR / "synthesize" / "synthesize_onboarding.json").read_text(encoding="utf-8"))
    assert client._scaled_fixture(request(scaled["match_evidence_n"]))["scale_users"] == 20000
    assert client._scaled_fixture(request([325])) is None                # the 50,000-user sample size: the base fixture is used
