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
    settings = Settings(**{k.lower(): v for k, v in _env().items()})

    assert settings.environment == "test"
    assert settings.session_cookie_name == "ta_session"
    assert settings.token_encryption_key_version == 1
    assert str(settings.public_base_url).startswith("http://127.0.0.1:8000")


def test_settings_require_plaid_credentials() -> None:
    values = {k.lower(): v for k, v in _env().items()}
    del values["plaid_client_id"]

    with pytest.raises(ValidationError):
        Settings(**values)


def test_settings_reject_short_application_secret() -> None:
    values = {k.lower(): v for k, v in _env(APPLICATION_SECRET="tooshort").items()}

    with pytest.raises(ValidationError):
        Settings(**values)


def test_secrets_are_not_rendered_in_repr() -> None:
    settings = Settings(**{k.lower(): v for k, v in _env().items()})

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
        Settings(**values)


def test_production_accepts_stable_https_public_base_url() -> None:
    values = {
        k.lower(): v
        for k, v in _env(
            ENVIRONMENT="production", PUBLIC_BASE_URL="https://aggregator.example.com"
        ).items()
    }

    settings = Settings(**values)

    assert settings.environment == "production"
