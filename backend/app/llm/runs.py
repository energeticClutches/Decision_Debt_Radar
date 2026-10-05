"""The agent_runs metadata writer: every LLM call writes exactly one agent_runs row (docs/day-5-implementation-brief.md section 10).

The row stores the purpose, the requested and the answering model (`stub:<name>` for a fixture or a stub, so a stored row never
claims that a real model produced it), whether the Reviewer fell back to the primary model, the prompt id, version and hash, the
parameters, the input and output hashes (SHA-256 of the canonical JSON), the raw input and raw output, the provider request id,
the token counts, the latency and the error class. A failed call is a row with status 'failed' and an error class: an LLM failure
is never silently dropped and never counts as a pass.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import AgentRun
from app.llm.client import (
    LlmClient,
    LlmError,
    LlmRequest,
    LlmResponse,
    LlmUnavailableError,
    output_hash,
)
from app.repositories import agent_runs as runs_repo


@dataclass
class LlmCallResult:
    run: AgentRun
    response: LlmResponse | None
    error: LlmError | None

    @property
    def ok(self) -> bool:
        return self.error is None and self.response is not None


def call_llm(session: Session, client: LlmClient, request: LlmRequest, *, decision_id: uuid.UUID, assessment_id: uuid.UUID | None,
             stage: str | None, agent_name: str, is_synthetic: bool, fallback: LlmRequest | None = None) -> LlmCallResult:
    """Call the client once (plus the optional model fallback) and write the agent_runs row. Never raises an LlmError: it is returned.

    `fallback` is the same request for the primary model. It is used only when the requested model is unavailable (D5-11), and
    `model_fallback` is then true on the row."""
    t0 = time.perf_counter()
    response: LlmResponse | None = None
    error: LlmError | None = None
    used = request
    fell_back = False
    try:
        try:
            response = client.complete(request)
        except LlmUnavailableError as exc:
            if fallback is None:
                raise
            used, fell_back = fallback, True
            response = client.complete(fallback)
            response.model_fallback = True
            _ = exc
    except LlmError as exc:
        error = exc
    latency = int((time.perf_counter() - t0) * 1000)
    raw_text = response.text if response is not None else None
    run = runs_repo.add_run(
        session, decision_id=decision_id, assessment_id=assessment_id, stage=stage, agent_name=agent_name,
        status="succeeded" if error is None else "failed", purpose=request.purpose,
        input={"purpose": request.purpose, "prompt_id": request.prompt_id, "prompt_version": request.prompt_version,
               "input": dict(request.input_obj)},
        output=None if raw_text is None else {"raw_text": raw_text, "provenance": response.provenance},
        model=(response.model if response is not None else used.model), model_fallback=fell_back,
        prompt_version=request.prompt_version, prompt_id=request.prompt_id, prompt_sha256=request.prompt_sha256,
        params={"temperature": used.temperature, "max_output_tokens": used.max_output_tokens, "timeout_s": used.timeout_s,
                "max_retries": used.max_retries, "model_requested": request.model, "model_used": used.model},
        input_sha256=request.input_sha256, output_sha256=None if raw_text is None else output_hash(raw_text),
        request_id=None if response is None else response.request_id,
        tokens_in=None if response is None else response.tokens_in, tokens_out=None if response is None else response.tokens_out,
        latency_ms=latency, error=None if error is None else str(error)[:500],
        error_class=None if error is None else error.error_class, is_synthetic=is_synthetic)
    return LlmCallResult(run=run, response=response, error=error)


def mark_run_failed(session: Session, run: AgentRun, error_class: str, message: str) -> None:
    """The call itself succeeded but its output was rejected (malformed JSON or a schema error): the run is failed, with the reason."""
    run.status = "failed"
    run.error_class = error_class
    run.error = message[:500]
    session.flush()
