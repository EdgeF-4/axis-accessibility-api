"""Runtime configuration.

Single source of truth for every value AXIS reads from the environment. All
fields are prefixed `AXIS_` except where an external convention (e.g.
`ANTHROPIC_API_KEY`) wins, in which case the override is explicit.

The settings object is constructed via :func:`get_settings`, which caches a
single immutable instance for the process. Tests reach in by clearing the
cache and re-instantiating.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Frozen runtime settings; loaded from environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="AXIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    # --- runtime ---
    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"  # noqa: S104 -- container bind address; controlled at compose
    port: int = 8000

    # --- database ---
    db_dsn: str = "postgresql+asyncpg://axis:axis@localhost:5432/axis"
    db_pool_size: int = 10
    db_max_overflow: int = 5

    # --- redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- auth ---
    jwt_secret: SecretStr = Field(default=SecretStr("dev-only-replace-me"))
    jwt_alg: Literal["HS256", "RS256"] = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 2_592_000
    jwt_issuer: str = "axis.local"
    jwt_audience: str = "axis-api"

    # --- anthropic / extraction ---
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "AXIS_ANTHROPIC_API_KEY"),
    )
    extraction_model: str = "claude-opus-4-7"
    extraction_persist_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    extraction_review_threshold: float = Field(default=0.50, ge=0.0, le=1.0)

    # --- ingestion resilience ---
    ingest_max_attempts: int = Field(default=5, ge=1)
    ingest_backoff_base_seconds: float = Field(default=2.0, gt=0)
    ingest_backoff_max_seconds: float = Field(default=60.0, gt=0)
    breaker_fails_to_open: int = Field(default=5, ge=1)
    breaker_window_seconds: float = Field(default=60.0, gt=0)
    breaker_open_seconds: float = Field(default=30.0, gt=0)

    # --- observability ---
    otel_exporter: Literal["none", "otlp"] = "none"
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "axis-api"

    # --- rate limiting ---
    ratelimit_default: str = "100/minute"
    ratelimit_auth: str = "10/minute"

    # --- partner api keys ---
    partner_key_prefix_len: int = Field(default=8, ge=4, le=16)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached :class:`Settings` instance for this process."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings — for tests that mutate the environment."""
    get_settings.cache_clear()
