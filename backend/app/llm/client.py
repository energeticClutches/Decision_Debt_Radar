"""The LLM boundary (docs/day-5-implementation-brief.md section 10).

  LlmClient          the protocol every caller depends on. No caller imports a vendor SDK.
  RecordedClient     replays stored fixtures (the client of every CI test). No network, no key.
  LlmRequest/LlmResponse and the error classes.

The vendor SDK `anthropic` is imported ONLY in backend/app/llm/anthropic_client.py (test G2). Reproducibility comes from stored
outputs (agent_runs, syntheses, llm_classifications), never from re-generation (D5-11).

Fixture provenance. A fixture that was written by hand or by a deterministic stub carries "provenance": "stub_not_model_output"
and its model name starts with "stub:", so a stored row never claims that a real model produced it. Only a fixture written by
scripts/record_llm_fixtures.py from a live call carries "provenance": "recorded_model_output".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

PURPOSES = ("classify", "synthesize", "review")
PROVENANCE_STUB = "stub_not_model_output"
PROVENANCE_RECORDED = "recorded_model_output"
STUB_MODEL_PREFIX = "stub:"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def output_hash(raw_text: str) -> str:
    """SHA-256 of the canonical JSON of the output when it parses, else of the raw text."""
    try:
        return sha256_json(json.loads(raw_text))
    except (ValueError, TypeError):
        return sha256_text(raw_text)


# ---------------------------------------------------------------- errors
class LlmError(Exception):
    """Base class. `error_class` is stored in agent_runs.error_class."""

    error_class = "llm_error"


class LlmTransportError(LlmError):
    """Timeout, connection error, rate limit or 5xx after the allowed retry."""

    error_class = "transport"


class LlmUnavailableError(LlmError):
    """The requested model cannot be used (not found or not permitted). The Reviewer then falls back to the primary model."""

    error_class = "model_unavailable"


class LlmNotConfiguredError(LlmError):
    error_class = "not_configured"


class LlmFixtureMissingError(LlmError):
    """RecordedClient has no fixture for the request (a test must never fall through to a live call)."""

    error_class = "fixture_missing"


# ---------------------------------------------------------------- request and response
@dataclass(frozen=True)
class LlmRequest:
    purpose: str
    model: str
    system: str                    # the loaded prompt text (never stored in a user-visible field)
    user: str                      # the JSON text of `input_obj`
    input_obj: Mapping[str, Any]   # the structured input (what agent_runs.input stores)
    input_sha256: str              # sha256 over the canonical JSON of {purpose, prompt version, prompt hash, input}
    prompt_id: str
    prompt_version: str
    prompt_sha256: str
    max_output_tokens: int
    temperature: float = 0.0
    timeout_s: int = 60
    max_retries: int = 1
    # Replay hints used by RecordedClient only (never sent to a model): scenario_key and the evidence index used to resolve the
    # symbolic evidence references of a hand-authored fixture.
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class LlmResponse:
    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    request_id: str | None = None
    provenance: str | None = None  # stub_not_model_output | recorded_model_output | None (a live model call)
    model_fallback: bool = False


@runtime_checkable
class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...


# ---------------------------------------------------------------- recorded fixtures
def _resolve_selector(selector: str, index: list[Mapping[str, Any]]) -> str:
    """'@customer:coach_helpful', '@behavioral:comparison', '@experiment' -> the evidence id from the request's evidence index.

    The part after the colon matches the item's theme or analysis type. The selector must match exactly one item."""
    body = selector[1:]
    etype, _, key = body.partition(":")
    hits = [e for e in index if e.get("evidence_type") == etype
            and (not key or key in (e.get("theme"), e.get("analysis_type")))]
    if len(hits) != 1:
        raise LlmFixtureMissingError(f"fixture selector {selector!r} matches {len(hits)} evidence items (expected exactly one)")
    return str(hits[0]["id"])


def resolve_selectors(value: Any, index: list[Mapping[str, Any]]) -> Any:
    if isinstance(value, str) and value.startswith("@") and len(value) > 1:
        return _resolve_selector(value, index)
    if isinstance(value, list):
        return [resolve_selectors(v, index) for v in value]
    if isinstance(value, dict):
        return {k: resolve_selectors(v, index) for k, v in value.items()}
    return value


class RecordedClient:
    """Replays fixtures. Lookup order: an exact (purpose, prompt_version, input_sha256) match (a recording from a live run), then
    a scenario fixture (purpose, prompt_version, scenario_key[, variant]) whose evidence selectors are resolved against the
    request's evidence index. A missing fixture raises LlmFixtureMissingError: a CI test never reaches the network."""

    def __init__(self, fixtures: list[Mapping[str, Any]] | None = None, *, directory: Path | str | None = None):
        self.fixtures: list[Mapping[str, Any]] = list(fixtures or [])
        if directory is not None:
            for path in sorted(Path(directory).rglob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("purpose") in PURPOSES:
                    self.fixtures.append(data)
        self.calls: list[LlmRequest] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        fixture = self._find(request)
        if fixture.get("raise"):
            cls = {"transport": LlmTransportError, "unavailable": LlmUnavailableError}.get(fixture["raise"], LlmError)
            raise cls(f"fixture requested an error: {fixture['raise']}")
        if "output_text" in fixture:
            text = str(fixture["output_text"])
        else:
            index = list(request.meta.get("evidence_index") or [])
            text = json.dumps(resolve_selectors(fixture["output"], index), sort_keys=True)
        return LlmResponse(text=text, model=str(fixture.get("model") or "stub:recorded"), tokens_in=None, tokens_out=None,
                           request_id=f"fixture:{fixture.get('fixture_id', 'unnamed')}", provenance=fixture.get("provenance"))

    def _find(self, request: LlmRequest) -> Mapping[str, Any]:
        base = [f for f in self.fixtures if f.get("purpose") == request.purpose and f.get("prompt_version") == request.prompt_version]
        exact = [f for f in base if f.get("input_sha256") == request.input_sha256]
        if exact:
            return exact[0]
        scenario = request.meta.get("scenario_key")
        by_scenario = [f for f in base if f.get("input_sha256") is None and f.get("scenario_key") == scenario
                       and (f.get("variant") or "default") == (request.meta.get("variant") or "default")]
        if by_scenario:
            return by_scenario[0]
        raise LlmFixtureMissingError(f"no recorded fixture for purpose={request.purpose} prompt={request.prompt_version} "
                                     f"scenario={scenario!r} input_sha256={request.input_sha256[:12]}")
