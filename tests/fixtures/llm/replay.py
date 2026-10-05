"""Test clients (test-only). Every CI test uses one of these; none reaches the network or needs a key (D5-12).

  ReplayClient   classification -> the deterministic keyword-rule stub; synthesis and review -> hand-authored fixtures through
                 RecordedClient. Every fixture and stub response carries provenance "stub_not_model_output" and a model name
                 "stub:<name>", so stored rows never claim a real model produced them.
  ScriptedClient returns queued raw texts (malformed JSON, schema errors, failures) for one purpose: used by the failure tests.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from stub_classifier import MODEL as STUB_CLASSIFIER_MODEL
from stub_classifier import StubClassifierClient

from app.llm.client import (
    PROVENANCE_STUB,
    LlmError,
    LlmRequest,
    LlmResponse,
    LlmTransportError,
    RecordedClient,
)

FIXTURE_DIR = Path(__file__).resolve().parent
STUB_MODELS = {"classify": STUB_CLASSIFIER_MODEL, "synthesize": "stub:handauthored_synthesis_v1", "review": "stub:handauthored_review_v1",
               "primary": "stub:handauthored_synthesis_v1"}


class ReplayClient:
    def __init__(self, *, fixtures_dir: Path | None = None, fail: dict[str, Exception] | None = None):
        self.classifier = StubClassifierClient()
        self.recorded = RecordedClient(directory=fixtures_dir or FIXTURE_DIR / "recorded")
        self.fail = dict(fail or {})
        self.calls: list[LlmRequest] = []

    def calls_for(self, purpose: str) -> list[LlmRequest]:
        return [c for c in self.calls if c.purpose == purpose]

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        if request.purpose in self.fail:
            raise self.fail[request.purpose]
        if request.purpose == "classify":
            return self.classifier.complete(request)
        return self.recorded.complete(request)


class ScriptedClient:
    """Returns the queued items in order, then repeats the last one. An item is a raw output text or an LlmError to raise."""

    def __init__(self, items, *, model: str = "stub:scripted"):
        self.items = deque(items)
        self.last = None
        self.calls: list[LlmRequest] = []
        self.model = model

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        item = self.items.popleft() if self.items else self.last
        self.last = item
        if isinstance(item, LlmError):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return LlmResponse(text=text, model=self.model, provenance=PROVENANCE_STUB, request_id=f"scripted:{len(self.calls)}")


class RoutedClient:
    """Routes each purpose to its own client (for example the Reviewer to a failing ScriptedClient and the rest to a ReplayClient)."""

    def __init__(self, routes: dict, default=None):
        self.routes = dict(routes)
        self.default = default
        self.calls: list[LlmRequest] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        client = self.routes.get(request.purpose, self.default)
        if client is None:
            raise LlmTransportError(f"no client routed for purpose {request.purpose}")
        return client.complete(request)


__all__ = ["FIXTURE_DIR", "LlmTransportError", "ReplayClient", "RoutedClient", "STUB_MODELS", "ScriptedClient"]
