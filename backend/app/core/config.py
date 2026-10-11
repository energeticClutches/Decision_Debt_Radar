"""Application settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_AS_OF = date(2026, 10, 1)      # the synthetic data's as-of date: the hosted demo is pinned to it


def normalise_database_url(url: str) -> str:
    """Accept a provider connection string (Neon: postgres://...?sslmode=require) and return the SQLAlchemy URL for the psycopg 3
    driver. A URL that already names a driver (postgresql+psycopg://) is returned unchanged."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DDR_ENV=production (the hosted demo) pins the LLM mode to replay and the as-of date and turns on production logging.
    # APP_ENV is the older name of the same setting and is still read.
    app_env: str = Field("local", validation_alias=AliasChoices("DDR_ENV", "APP_ENV"))
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

    # Rate limits of the hosted demo (in-process, per client IP; see app.core.ratelimit). On by default only in production (local
    # development, demo_prepare and the test suites make far more writes than a visitor); DDR_RATE_LIMIT=1 or 0 overrides. A limit of 0 is off.
    ddr_rate_limit: bool | None = None
    # One JSON request line per request on stdout (method, path, status, ms). On by default only in production.
    ddr_log_requests: bool | None = None
    ddr_rate_limit_window_seconds: int = 600
    ddr_rate_limit_mutations: int = 30
    ddr_rate_limit_pipeline: int = 5
    # Only the first X-Forwarded-For address is used, and only when this is on (default: production, behind Render's proxy).
    ddr_trust_forwarded_for: bool | None = None

    @field_validator("database_url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        return normalise_database_url(value)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def rate_limit_enabled(self) -> bool:
        return self.is_production if self.ddr_rate_limit is None else self.ddr_rate_limit

    @property
    def log_requests(self) -> bool:
        return self.is_production if self.ddr_log_requests is None else self.ddr_log_requests

    @property
    def trust_forwarded_for(self) -> bool:
        return self.is_production if self.ddr_trust_forwarded_for is None else self.ddr_trust_forwarded_for

    @model_validator(mode="after")
    def _production_profile(self) -> "Settings":
        if self.is_production:
            # The public demo never calls a model and needs no key; its dates are reproducible.
            self.ddr_llm_mode = "replay"
            if self.ddr_as_of_date is None:
                self.ddr_as_of_date = PRODUCTION_AS_OF
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
