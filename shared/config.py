"""Environment-based configuration.

All settings are read from environment variables prefixed with ``ATLAS_`` (or a
``.env`` file). Secrets are typed as ``SecretStr`` so they never appear in logs
or ``repr`` output.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    # --- runtime -----------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./atlas.db"
    redis_url: str | None = None
    auto_migrate: bool = True

    # --- task execution ------------------------------------------------------
    task_backend: Literal["inline", "celery"] = "inline"

    # --- security ------------------------------------------------------------
    secret_key: SecretStr = SecretStr("dev-insecure-change-me-dev-insecure-change-me")
    # Fernet key (urlsafe base64, 32 bytes) for encrypting sensitive columns at rest.
    encryption_key: SecretStr | None = None
    # HMAC key used for identifier lookup hashes (suppression list, audit log).
    hash_key: SecretStr | None = None
    access_token_ttl_minutes: int = 60
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    cookie_secure: bool = False
    api_rate_limit_per_minute: int = 120
    public_rate_limit_per_minute: int = 10
    max_request_bytes: int = 1_000_000
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # --- compliance ------------------------------------------------------------
    require_consent_for_individuals: bool = True
    default_retention_days: int = 90
    max_retention_days: int = 365

    # --- collection ------------------------------------------------------------
    http_timeout_seconds: float = 15.0
    http_max_response_bytes: int = 5_000_000
    http_pin_dns: bool = True
    http_allowed_ports: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [80, 443])
    user_agent: str = "ATLAS-OSINT/0.2 (+https://github.com/codesphere-u/atlas-osint; research)"
    adapter_timeout_seconds: float = 30.0
    max_concurrent_adapters: int = 8
    sec_edgar_user_agent: str | None = None  # SEC requires a contact in the UA

    # --- source credentials (optional; adapters report "not configured" if absent)
    github_token: SecretStr | None = None
    hibp_api_key: SecretStr | None = None
    companies_house_api_key: SecretStr | None = None
    opencorporates_api_token: SecretStr | None = None
    numverify_api_key: SecretStr | None = None
    opensanctions_api_key: SecretStr | None = None
    certspotter_api_key: SecretStr | None = None  # optional; raises the anonymous rate limit
    fediverse_instances: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["mastodon.social"])
    lookalike_max_candidates: int = 150
    # DNS backend: "system" (host resolvers) or "doh" (DNS-over-HTTPS JSON API; use where port 53 is filtered)
    dns_resolver: Literal["system", "doh"] = "system"
    doh_url: str = "https://dns.google/resolve"

    # --- scheduling (inline backend only; Celery beat handles this when task_backend=celery) ---
    inline_scheduler: bool = True
    scheduler_interval_seconds: int = 60

    # --- AI analysis -------------------------------------------------------------
    ai_provider: Literal["none", "anthropic", "openai_compatible"] = "none"
    ai_model: str = "claude-opus-5-5"
    anthropic_api_key: SecretStr | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None
    ai_max_findings: int = 200

    @field_validator("cors_origins", "http_allowed_ports", "fediverse_instances", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [p.strip() for p in text.split(",") if p.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_production(self) -> list[str]:
        """Return a list of configuration problems that must block a production start."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if (
            self.secret_key.get_secret_value().startswith("dev-insecure")
            or len(self.secret_key.get_secret_value()) < 32
        ):
            problems.append("ATLAS_SECRET_KEY must be set to a random value of at least 32 characters")
        if self.encryption_key is None:
            problems.append("ATLAS_ENCRYPTION_KEY must be set (Fernet key) in production")
        if self.hash_key is None:
            problems.append("ATLAS_HASH_KEY must be set in production")
        if not self.cookie_secure:
            problems.append("ATLAS_COOKIE_SECURE must be true in production (TLS required)")
        if self.database_url.startswith("sqlite"):
            problems.append("SQLite is not supported in production; use PostgreSQL")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
