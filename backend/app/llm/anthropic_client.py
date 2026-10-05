"""The live Anthropic client. The ONLY module under backend/app that imports `anthropic` (test G2).

Used only when ANTHROPIC_API_KEY is set (the application) or by tests marked `llm` (opt-in). CI never reaches this module's network
path: every CI test uses RecordedClient or a test double. One retry on a transport error, a rate limit or a 5xx; none on a schema
error (the repair path lives in the synthesis and review services). No tool use, no streaming, temperature 0.
"""

from __future__ import annotations

import anthropic

from app.llm.client import LlmRequest, LlmResponse, LlmTransportError, LlmUnavailableError


class AnthropicClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("an API key is required")
        self._api_key = api_key

    def complete(self, request: LlmRequest) -> LlmResponse:
        client = anthropic.Anthropic(api_key=self._api_key, timeout=float(request.timeout_s), max_retries=0)
        attempts = 1 + max(0, request.max_retries)
        last: Exception | None = None
        for _ in range(attempts):
            try:
                message = client.messages.create(
                    model=request.model, max_tokens=request.max_output_tokens, temperature=request.temperature,
                    system=request.system, messages=[{"role": "user", "content": request.user}])
            except (anthropic.NotFoundError, anthropic.PermissionDeniedError) as exc:
                raise LlmUnavailableError(f"model {request.model} is not available: {type(exc).__name__}") from exc
            except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError,
                    anthropic.InternalServerError, anthropic.OverloadedError, anthropic.ServiceUnavailableError) as exc:
                last = exc
                continue
            except anthropic.APIStatusError as exc:
                if getattr(exc, "status_code", 0) >= 500:
                    last = exc
                    continue
                raise LlmTransportError(f"request rejected: {type(exc).__name__} {getattr(exc, 'status_code', '')}") from exc
            text = "".join(getattr(block, "text", "") for block in message.content if getattr(block, "type", "") == "text")
            usage = getattr(message, "usage", None)
            return LlmResponse(text=text, model=str(getattr(message, "model", request.model)),
                               tokens_in=getattr(usage, "input_tokens", None), tokens_out=getattr(usage, "output_tokens", None),
                               request_id=getattr(message, "_request_id", None) or getattr(message, "id", None), provenance=None)
        raise LlmTransportError(f"transport error after {attempts} attempt(s): {type(last).__name__}") from last
