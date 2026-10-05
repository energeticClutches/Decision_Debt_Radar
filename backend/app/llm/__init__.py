"""LLM boundary: client protocol, recorded fixtures, prompts, sanitising and the agent_runs metadata writer.

The live client (app.llm.anthropic_client) is imported lazily by `get_llm_client`, and only when a key is configured.
"""

from __future__ import annotations

from app.llm.client import (
    LlmClient,
    LlmError,
    LlmFixtureMissingError,
    LlmNotConfiguredError,
    LlmRequest,
    LlmResponse,
    LlmTransportError,
    LlmUnavailableError,
    RecordedClient,
)


def get_llm_client() -> LlmClient | None:
    """The live client when ANTHROPIC_API_KEY is set, else None (the pipeline then records the LLM stages as skipped)."""
    from app.core.config import get_settings
    key = get_settings().anthropic_api_key
    secret = key.get_secret_value().strip() if key is not None else ""
    if not secret:
        return None
    from app.llm.anthropic_client import AnthropicClient       # the only module that imports the vendor SDK
    return AnthropicClient(secret)


__all__ = ["LlmClient", "LlmError", "LlmFixtureMissingError", "LlmNotConfiguredError", "LlmRequest", "LlmResponse",
           "LlmTransportError", "LlmUnavailableError", "RecordedClient", "get_llm_client"]
