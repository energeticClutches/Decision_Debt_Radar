"""Application settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    # 127.0.0.1, not localhost: "localhost" can hang on some Windows setups.
    database_url: str = "postgresql+psycopg://ddr:change_me_local_only@127.0.0.1:5432/ddr"

    anthropic_api_key: SecretStr | None = None
    anthropic_model_primary: str = "claude-sonnet-5-5"
    anthropic_model_reviewer: str = "claude-opus-5-5"

    ddi_params_version: str = "ddi_params_v0.1"
    nbe_params_version: str = "nbe_params_v0.2"
    # Day 4: generic analytics parameters and the tenant (organisation) analytics configuration.
    analytics_params_version: str = "analytics_params_v0.1"
    tenant_config_key: str = "fitconnect"

    # Optional fixed "as of" date for reproducible demos (ISO date). Unset = the system date.
    ddr_as_of_date: date | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
