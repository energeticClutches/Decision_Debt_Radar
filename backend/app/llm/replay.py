"""Replay mode (D6-01): the LlmClient of the local demo. No network, no API key.

`ReplayDemoClient` serves the recorded responses in `backend/demo_fixtures/`:

    classify/     one response per classification request, keyed by `input_sha256` (generated once by scripts/build_demo_fixtures.py)
    synthesize/   the hand-authored Day-5 scenario fixtures (symbolic evidence selectors, resolved against the request's evidence index)
    review/       the same for the Reviewer

Every fixture carries "provenance": "stub_not_model_output" and a model name "stub:<name>", so a stored agent_runs row, synthesis, review
or classification never claims that a real model produced it, and the UI shows "Replayed demo fixture, not live model output".

The class implements `LlmClient` exactly (it is a thin wrapper around `RecordedClient`): the validators, the agent_runs metadata, the
review enforcement, the code findings and the lifecycle all run unchanged after it. A request without a fixture raises
`LlmFixtureMissingError` (error class `fixture_missing`), which the callers record as a failure. It never invents output.

Product code never imports from `tests/`: the fixtures are product data under `backend/demo_fixtures/`.
"""

from __future__ import annotations

from pathlib import Path

from app.llm.client import LlmRequest, LlmResponse, RecordedClient

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "demo_fixtures"
# Deploy profile: classification fixtures recorded for the smaller hosted-demo data scale (20,000 users). A classification request is
# keyed by the hash of its input, and at another scale the last batch of distinct feedback texts differs, so it has its own fixtures.
# They are loaded in addition to FIXTURE_DIR; a request still without a fixture fails loudly (fixture_missing), as before.
DEPLOY_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "demo_fixtures_deploy"

# The model names stored as the REQUESTED model of a replayed call. They are stub names on purpose: a stored row must never claim
# that a real model (for example claude-sonnet-5-5) produced a replayed fixture.
REPLAY_MODELS = {"classify": "stub:keyword_rules_v1", "synthesize": "stub:handauthored_synthesis_v1",
                 "review": "stub:handauthored_review_v1", "primary": "stub:handauthored_synthesis_v1"}


class ReplayDemoClient:
    def __init__(self, directory: Path | str | None = None):
        self._recorded = RecordedClient(directory=directory or FIXTURE_DIR)
        # Fixtures written for the deploy data scale: classification ones are keyed by input hash, like the base ones. A synthesis
        # fixture names the evidence sample sizes it was written for (`match_evidence_n`) and is used only for a request with exactly those.
        self._scaled: list[dict] = []
        if directory is None and DEPLOY_FIXTURE_DIR.is_dir():
            for fixture in RecordedClient(directory=DEPLOY_FIXTURE_DIR).fixtures:
                (self._scaled if "match_evidence_n" in fixture else self._recorded.fixtures).append(fixture)
        self.calls: list[LlmRequest] = []

    @property
    def fixture_count(self) -> int:
        return len(self._recorded.fixtures)

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        scaled = self._scaled_fixture(request)
        if scaled is not None:
            return RecordedClient(fixtures=[scaled]).complete(request)
        return self._recorded.complete(request)

    def _scaled_fixture(self, request: LlmRequest) -> dict | None:
        if not self._scaled:
            return None
        sizes = sorted(e.get("n_sample") for e in (request.input_obj.get("evidence") or []) if isinstance(e, dict) and e.get("n_sample") is not None)
        for fixture in self._scaled:
            if (fixture.get("purpose") == request.purpose and fixture.get("prompt_version") == request.prompt_version
                    and fixture.get("scenario_key") == request.meta.get("scenario_key")
                    and (fixture.get("variant") or "default") == (request.meta.get("variant") or "default")
                    and fixture["match_evidence_n"] == sizes):
                return fixture
        return None
