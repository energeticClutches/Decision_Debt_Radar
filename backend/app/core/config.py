"""Application settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    # 127.0.0.1, not localhost: "localhost" can hang on some Windows setups.
    database_url: str = "postgresql+psycopg://ddr:change_me_local_only@127.0.0.1:5432/ddr"

    anthropic_api_key: SecretStr | None = None
    # Day 6 (D6-01): live | replay | off. replay (the local and demo default) serves recorded demo fixtures from backend/demo_fixtures
    # and needs no key; live needs ANTHROPIC_API_KEY; off gives no client (the Day-5 behaviour without a key).
    ddr_llm_mode: Literal["live", "replay", "off"] = "replay"
    anthropic_model_primary: str = "claude-sonnet-5-5"
    anthropic_model_reviewer: str = "claude-opus-5-5"

    ddi_params_version: str = "ddi_params_v0.1"
    nbe_params_version: str = "nbe_params_v0.2"
    # Day 4: generic analytics parameters and the tenant (organisation) analytics configuration.
    # Day 5: analytics_params_v0.2 (v0.1 plus the customer and llm sections) and the tenant configuration v0.2 (plus the customer
    # taxonomy). v0.1 of both stays released and loadable.
    analytics_params_version: str = "analytics_params_v0.2"
    tenant_config_key: str = "fitconnect"
    tenant_config_version: str = "fitconnect_analytics_config_v0.2"
    # Day 5: the LLM call models and the live-call switch. The API key is read from the environment only and is never stored.
    prompt_version: str = "v0.1"                     # prompts/<version>/*.md, hash-checked against prompts/prompt_hashes.json
    llm_model_classify: str | None = None            # default: anthropic_model_primary
    llm_model_synthesize: str | None = None          # default: anthropic_model_primary
    llm_model_review: str | None = None              # default: anthropic_model_reviewer

    # Optional fixed "as of" date for reproducible demos (ISO date). Unset = the system date.
    ddr_as_of_date: date | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
