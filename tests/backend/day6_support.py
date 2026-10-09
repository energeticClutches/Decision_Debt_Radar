"""Helpers for the Day-6 tests: the application over HTTP with the product replay client (backend/demo_fixtures), on the rolled-back session."""

from __future__ import annotations

import pytest
from day4_support import TODAY
from fastapi.testclient import TestClient

from app.core import deps
from app.core.clock import FixedClock
from app.llm.replay import REPLAY_MODELS, ReplayDemoClient
from app.main import app


def H(actor) -> dict:
    return {"X-Demo-User": actor.id}


@pytest.fixture()
def replay_http(session):
    """(TestClient, ReplayDemoClient): the real routes, the rolled-back session, a fixed clock and the product replay client."""
    client = ReplayDemoClient()
    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_clock] = lambda: FixedClock(TODAY)
    app.dependency_overrides[deps.get_llm] = lambda: client
    app.dependency_overrides[deps.get_llm_models] = lambda: dict(REPLAY_MODELS)
    yield TestClient(app, raise_server_exceptions=False), client
    app.dependency_overrides.clear()


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def run_to_challenged(http, seed, scenario: str, session) -> dict:
    """pipeline (proposals) -> approve every proposed item as the BA -> pipeline again. Returns the ids and bodies."""
    d = seed.decisions[scenario]
    session.refresh(d)
    first = ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    items = ok(http.get(f"/decisions/{d.id}/customer-evidence", headers=H(seed.ba)))["items"]
    for it in items:
        ok(http.patch(f"/evidence/{it['evidence']['id']}/approval", headers=H(seed.ba), json={"action": "approve", "note": "demo preparation"}))
    second = ok(http.post(f"/decisions/{d.id}/pipeline-runs", headers=H(seed.analyst)), 201)
    return {"decision_id": str(d.id), "assessment_id": second["assessment"]["id"], "first": first, "second": second, "items": items}
