"""LLM boundary: client protocol, recorded fixtures, prompts, sanitising and the agent_runs metadata writer.

The live client (app.llm.anthropic_client) is imported lazily by `get_llm_client`, and only in live mode with a key. Replay mode
(app.llm.replay) serves the demo fixtures in backend/demo_fixtures.
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
    """The client for the configured DDR_LLM_MODE (D6-01).

    live    AnthropicClient when ANTHROPIC_API_KEY is set, else None (the pipeline then records the LLM stages as skipped)
    replay  ReplayDemoClient over backend/demo_fixtures (no key, no network; every output is marked stub_not_model_output)
    off     None (the Day-5 behaviour without a key)
    """
    from app.core.config import get_settings
    settings = get_settings()
    if settings.ddr_llm_mode == "off":
        return None
    if settings.ddr_llm_mode == "replay":
        from app.llm.replay import ReplayDemoClient
        return ReplayDemoClient()
    key = settings.anthropic_api_key
    secret = key.get_secret_value().strip() if key is not None else ""
    if not secret:
        return None
    from app.llm.anthropic_client import AnthropicClient       # the only module that imports the vendor SDK
    return AnthropicClient(secret)


__all__ = ["LlmClient", "LlmError", "LlmFixtureMissingError", "LlmNotConfiguredError", "LlmRequest", "LlmResponse",
           "LlmTransportError", "LlmUnavailableError", "RecordedClient", "get_llm_client"]
