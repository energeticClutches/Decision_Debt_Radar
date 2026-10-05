"""Build LlmRequest objects (the prompt, the structured input, the hashes, the model and the call settings)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.llm.client import LlmRequest, sha256_json
from app.llm.prompts import Prompt


def default_models() -> dict[str, str]:
    """The model per purpose from the settings (D5-11): Sonnet for classification and synthesis, Opus for review.
    `primary` is the model the Reviewer falls back to when its model is unavailable."""
    from app.core.config import get_settings
    s = get_settings()
    return {"classify": s.llm_model_classify or s.anthropic_model_primary, "synthesize": s.llm_model_synthesize or s.anthropic_model_primary,
            "review": s.llm_model_review or s.anthropic_model_reviewer, "primary": s.anthropic_model_primary}


def request_input_hash(purpose: str, prompt: Prompt, input_obj: Mapping[str, Any]) -> str:
    return sha256_json({"purpose": purpose, "prompt_version": prompt.version, "prompt_sha256": prompt.sha256, "input": input_obj})


def build_request(*, purpose: str, prompt: Prompt, input_obj: Mapping[str, Any], model: str, llm_params: Mapping[str, Any],
                  meta: Mapping[str, Any] | None = None) -> LlmRequest:
    return LlmRequest(
        purpose=purpose, model=model, system=prompt.text, user=json.dumps(input_obj, sort_keys=True, ensure_ascii=False),
        input_obj=dict(input_obj), input_sha256=request_input_hash(purpose, prompt, input_obj), prompt_id=prompt.id,
        prompt_version=prompt.version, prompt_sha256=prompt.sha256,
        max_output_tokens=int(llm_params["max_output_tokens"][purpose]), temperature=float(llm_params["temperature"]),
        timeout_s=int(llm_params["timeout_s"]), max_retries=int(llm_params["max_retries"]), meta=dict(meta or {}))
