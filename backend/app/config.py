"""Application settings loaded from the process environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["test", "demo", "sandbox", "production"]


class Settings(BaseSettings):
    """Every value the application needs that is not stored in the database."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "sandbox"
    database_url: str = "sqlite+aiosqlite:///./data/transactions.db"
    application_secret: SecretStr
    token_encryption_key: SecretStr
    token_encryption_key_version: int = 1
    session_cookie_name: str = "ta_session"
    session_lifetime_hours: int = 12
    public_base_url: AnyHttpUrl
    plaid_client_id: SecretStr
    plaid_secret: SecretStr
    plaid_webhook_url: AnyHttpUrl | None = None
    plaid_institution_overrides: str | None = None
    trusted_hosts: str = "127.0.0.1,localhost"
    sync_interval_minutes: int = 60
    display_stale_after_minutes: int | None = None
    enable_background_worker: bool = True

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if len(self.application_secret.get_secret_value()) < 32:
            raise ValueError("application_secret must be at least 32 characters")
        if self.token_encryption_key_version < 1:
            raise ValueError("token_encryption_key_version must be >= 1")
        if self.environment == "production":
            url = str(self.public_base_url)
            if not url.startswith("https://"):
                raise ValueError("production public_base_url must use HTTPS")
            host = self.public_base_url.host or ""
            if host in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("production public_base_url must not be loopback")
        return self

    @property
    def stale_display_minutes(self) -> int:
        """How old a cache may get before the owner is warned about it.

        Deliberately longer than `sync_interval_minutes`, which is the
        *enqueue* threshold (FR-SYNC-007/008). The scheduler ticks on its own
        clock while a connection ages on its own, so equal thresholds would
        flag healthy connections for up to a full sweep every cycle. Warning
        only after two missed sweeps plus grace means `stale` reports that
        automatic recovery has actually failed, not that an hour has passed.
        """

        if self.display_stale_after_minutes is not None:
            return self.display_stale_after_minutes
        return self.sync_interval_minutes * 2 + 30

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{str(self.public_base_url).rstrip('/')}/oauth-return"

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        base = str(self.public_base_url).rstrip("/")
        if self.environment in {"test", "demo", "sandbox"}:
            return (base, "http://127.0.0.1:5173", "http://localhost:5173")
        return (base,)

    @property
    def trusted_host_list(self) -> tuple[str, ...]:
        return tuple(
            host.strip() for host in self.trusted_hosts.split(",") if host.strip()
        )

    @property
    def uses_fake_plaid(self) -> bool:
        """Demo and test environments never reach the real Plaid API."""

        return self.environment in {"test", "demo"}

    @property
    def plaid_host_environment(self) -> str:
        return "production" if self.environment == "production" else "sandbox"

    @property
    def cookie_secure(self) -> bool:
        return str(self.public_base_url).startswith("https://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


__all__ = ["Environment", "Settings", "get_settings"]
