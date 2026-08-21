"""Fixtures for tests that call the real Plaid Sandbox API.

These are excluded from the default suite (see `addopts` in pyproject) because
they need network access and real Sandbox credentials. Run them with
`make test-sandbox`.

Sandbox is free and consumes no Trial Item slots — that budget is a production
concern only — and `/sandbox/public_token/create` mints a public token without
going through Link at all, so the whole exchange → sync → remove path runs
unattended. That is what makes these worth having: `FakePlaidGateway` cannot
catch SDK or provider contract drift, which is what actually broke us in
production twice.

Credentials come from dedicated `PLAID_SANDBOX_*` variables rather than the
application's own `PLAID_CLIENT_ID`/`PLAID_SECRET`. Those may legitimately hold
production values, and silently borrowing them would make it ambiguous which
environment a run was talking to.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.config import Settings
from app.services.plaid_client import PlaidPythonGateway

#: Plaid's canonical Sandbox test institution ("First Platypus Bank"). It is
#: always available and returns a deterministic set of accounts.
SANDBOX_INSTITUTION_ID = "ins_109508"

_CLIENT_ID = os.environ.get("PLAID_SANDBOX_CLIENT_ID", "").strip()
_SECRET = os.environ.get("PLAID_SANDBOX_SECRET", "").strip()

requires_sandbox_credentials = pytest.mark.skipif(
    not (_CLIENT_ID and _SECRET),
    reason=(
        "set PLAID_SANDBOX_CLIENT_ID and PLAID_SANDBOX_SECRET "
        "(Plaid dashboard → Keys → Sandbox) to run the live sandbox suite"
    ),
)


@pytest.fixture(scope="session")
def sandbox_settings() -> Settings:
    """Settings pinned to `sandbox`, never `production`.

    `PlaidPythonGateway` selects its host from `plaid_host_environment`, which
    only returns "production" when `environment == "production"`. Building the
    settings here rather than reading the developer's `backend/.env` is what
    guarantees these tests cannot reach the production API.
    """
    settings = Settings(
        _env_file=None,
        environment="sandbox",
        database_url="sqlite+aiosqlite:///:memory:",
        application_secret="s" * 32,
        token_encryption_key="k" * 43,
        public_base_url="https://aggregator.example.com",
        plaid_client_id=_CLIENT_ID or "unset",
        plaid_secret=_SECRET or "unset",
    )
    # Belt and braces: a regression that made production reachable from here
    # would spend real, non-refundable Trial Item slots.
    assert settings.plaid_host_environment == "sandbox"
    return settings


@pytest.fixture(scope="session")
def gateway(sandbox_settings: Settings) -> PlaidPythonGateway:
    return PlaidPythonGateway(sandbox_settings)


@pytest.fixture
def sandbox_item(gateway: PlaidPythonGateway) -> Iterator[str]:
    """An access token for a freshly minted Sandbox Item, removed afterwards.

    Cleanup is best-effort: Sandbox Items cost nothing and expire on their own,
    so a failure to remove one must not mask the assertion that actually failed.
    """
    access_token = exchange_sandbox_item(gateway, SANDBOX_INSTITUTION_ID)
    try:
        yield access_token
    finally:
        try:
            gateway.remove_item(access_token)
        except Exception:  # noqa: BLE001 - cleanup must never mask a failure
            pass


def create_sandbox_public_token(
    gateway: PlaidPythonGateway, institution_id: str
) -> str:
    """Mint a public token directly, bypassing Link.

    This is the whole reason the suite is affordable: no browser, no OAuth, and
    no Trial slot — but the resulting token exchanges through exactly the same
    code path a real Link session would use.
    """
    from plaid.model.products import Products
    from plaid.model.sandbox_public_token_create_request import (
        SandboxPublicTokenCreateRequest,
    )

    response = gateway._client.sandbox_public_token_create(
        SandboxPublicTokenCreateRequest(
            institution_id=institution_id,
            initial_products=[Products("transactions")],
        )
    )
    return str(response["public_token"])


def exchange_sandbox_item(gateway: PlaidPythonGateway, institution_id: str) -> str:
    public_token = create_sandbox_public_token(gateway, institution_id)
    return gateway.exchange_public_token(public_token).access_token
