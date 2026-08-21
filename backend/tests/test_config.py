from base64 import urlsafe_b64encode
from os import urandom

import pytest
from pydantic import ValidationError

from app.config import Settings


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "ENVIRONMENT": "test",
        "APPLICATION_SECRET": "a" * 32,
        "TOKEN_ENCRYPTION_KEY": urlsafe_b64encode(urandom(32)).decode(),
        "PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "PLAID_CLIENT_ID": "client-id",
        "PLAID_SECRET": "plaid-secret",
    }
    base.update(overrides)
    return base


def test_settings_load_from_environment() -> None:
    settings = Settings(_env_file=None, **{k.lower(): v for k, v in _env().items()})

    assert settings.environment == "test"
    assert settings.session_cookie_name == "ta_session"
    assert settings.token_encryption_key_version == 1
    assert str(settings.public_base_url).startswith("http://127.0.0.1:8000")


def test_settings_require_plaid_credentials() -> None:
    values = {k.lower(): v for k, v in _env().items()}
    del values["plaid_client_id"]

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_reject_short_application_secret() -> None:
    values = {k.lower(): v for k, v in _env(APPLICATION_SECRET="tooshort").items()}

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_secrets_are_not_rendered_in_repr() -> None:
    settings = Settings(_env_file=None, **{k.lower(): v for k, v in _env().items()})

    rendered = repr(settings)

    assert "plaid-secret" not in rendered
    assert settings.plaid_secret.get_secret_value() == "plaid-secret"


def test_production_requires_https_public_base_url() -> None:
    values = {
        k.lower(): v
        for k, v in _env(
            ENVIRONMENT="production", PUBLIC_BASE_URL="http://127.0.0.1:8000"
        ).items()
    }

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_production_accepts_stable_https_public_base_url() -> None:
    values = {
        k.lower(): v
        for k, v in _env(
            ENVIRONMENT="production", PUBLIC_BASE_URL="https://aggregator.example.com"
        ).items()
    }

    settings = Settings(_env_file=None, **values)

    assert settings.environment == "production"


def test_production_origin_allowlist_excludes_local_dev_servers() -> None:
    """Browsing a production deployment over loopback fails in a way that
    looks like a bug rather than a policy: the Secure session cookie is never
    stored, so a successful sign-in still reads as signed out, and any write
    comes back ORIGIN_INVALID. Only PUBLIC_BASE_URL is trusted here.
    """
    values = {
        k.lower(): v
        for k, v in _env(
            ENVIRONMENT="production", PUBLIC_BASE_URL="https://aggregator.example.com"
        ).items()
    }

    settings = Settings(_env_file=None, **values)

    assert settings.allowed_origins == ("https://aggregator.example.com",)


def test_sandbox_keeps_the_local_dev_server_origins() -> None:
    """The counterpart: sandbox is meant to be driven from `make dev`, so the
    Vite origins stay trusted there and the exclusion above is specific to
    production rather than incidental.
    """
    values = {k.lower(): v for k, v in _env(ENVIRONMENT="sandbox").items()}

    settings = Settings(_env_file=None, **values)

    assert "http://127.0.0.1:5173" in settings.allowed_origins
    assert "http://localhost:5173" in settings.allowed_origins
