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

# The model names stored as the REQUESTED model of a replayed call. They are stub names on purpose: a stored row must never claim
# that a real model (for example claude-sonnet-5-5) produced a replayed fixture.
REPLAY_MODELS = {"classify": "stub:keyword_rules_v1", "synthesize": "stub:handauthored_synthesis_v1",
                 "review": "stub:handauthored_review_v1", "primary": "stub:handauthored_synthesis_v1"}


class ReplayDemoClient:
    def __init__(self, directory: Path | str | None = None):
        self._recorded = RecordedClient(directory=directory or FIXTURE_DIR)
        self.calls: list[LlmRequest] = []

    @property
    def fixture_count(self) -> int:
        return len(self._recorded.fixtures)

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        return self._recorded.complete(request)
