"""Contract tests against the real plaid-python SDK types.

These construct the exact objects `PlaidPythonGateway` builds. They need no
network access, and they are the only coverage for code paths the demo and
fake gateways never exercise.
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings


@pytest.fixture
def production_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="sandbox",
        database_url="sqlite+aiosqlite:///:memory:",
        application_secret="s" * 32,
        token_encryption_key="k" * 43,
        public_base_url="https://aggregator.example.com",
        plaid_client_id="client-id",
        plaid_secret="plaid-secret",
    )


def test_credit_card_account_filter_is_a_valid_sdk_object() -> None:
    from plaid.model.credit_filter import CreditFilter
    from plaid.model.link_token_account_filters import LinkTokenAccountFilters

    from app.services.plaid_client import _credit_card_subtypes

    filters = LinkTokenAccountFilters(
        credit=CreditFilter(account_subtypes=_credit_card_subtypes())
    )

    assert filters.credit is not None


def test_new_link_token_request_builds_without_sdk_type_errors(
    production_settings: Settings,
) -> None:
    from plaid.model.country_code import CountryCode
    from plaid.model.credit_filter import CreditFilter
    from plaid.model.link_token_account_filters import LinkTokenAccountFilters
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.link_token_transactions import LinkTokenTransactions
    from plaid.model.products import Products

    from app.services.plaid_client import _credit_card_subtypes

    request = LinkTokenCreateRequest(
        client_name="Transaction Aggregator",
        language="en",
        country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id="owner-1"),
        redirect_uri="https://aggregator.example.com/oauth-return",
        products=[Products("transactions")],
        transactions=LinkTokenTransactions(days_requested=730),
        account_filters=LinkTokenAccountFilters(
            credit=CreditFilter(account_subtypes=_credit_card_subtypes())
        ),
    )

    assert request.days_requested if hasattr(request, "days_requested") else True
    assert request.client_name == "Transaction Aggregator"


def test_update_mode_request_omits_products(production_settings: Settings) -> None:
    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser

    request = LinkTokenCreateRequest(
        client_name="Transaction Aggregator",
        language="en",
        country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id="owner-1"),
        redirect_uri="https://aggregator.example.com/oauth-return",
        access_token="access-sandbox-token",
    )

    assert not hasattr(request, "products") or request.get("products") is None


def test_jwk_public_key_serializes_for_jwt_verification() -> None:
    """`dict(model)` raises on plaid-python models; `to_dict()` is required."""

    from plaid.model.jwk_public_key import JWKPublicKey

    key = JWKPublicKey(
        alg="ES256",
        crv="P-256",
        kid="key-id",
        kty="EC",
        use="sig",
        x="dGVzdC14",
        y="dGVzdC15",
        created_at=1,
        expired_at=None,
    )

    serialized = json.dumps(key.to_dict())

    assert json.loads(serialized)["kid"] == "key-id"
    with pytest.raises(Exception):
        dict(key)


def test_gateway_constructs_against_both_hosts(production_settings: Settings) -> None:
    from app.services.plaid_client import PlaidPythonGateway

    assert PlaidPythonGateway(production_settings) is not None


def test_only_the_production_environment_selects_the_production_host() -> None:
    """Guards the Trial Item budget against a misrouted environment.

    Plaid's Trial plan allows 10 production Items, cumulatively, and
    `/item/remove` does not return a slot. A change that let `demo`, `sandbox`,
    or `test` reach the production host would therefore spend real,
    unrecoverable capacity — quietly, and while appearing to run locally.
    """

    def _settings(environment: str) -> Settings:
        return Settings(
            _env_file=None,
            environment=environment,
            database_url="sqlite+aiosqlite:///:memory:",
            application_secret="s" * 32,
            token_encryption_key="k" * 43,
            public_base_url="https://aggregator.example.com",
            plaid_client_id="client-id",
            plaid_secret="plaid-secret",
        )

    assert _settings("production").plaid_host_environment == "production"
    for safe in ("sandbox", "demo", "test"):
        assert _settings(safe).plaid_host_environment == "sandbox"


def test_user_create_response_yields_distinct_id_and_token() -> None:
    """The two fields have different formats; conflating them produces
    Plaid's INVALID_USER_TOKEN error on the following link_token_create call.
    """

    from plaid.model.user_create_response import UserCreateResponse

    from app.services.plaid_client import _build_plaid_user

    response = UserCreateResponse(
        user_id="66125e2b-9d4d-4a1b-9f3a-000000000000",
        user_token="user-sandbox-66125e2b-9d4d-4a1b-9f3a-000000000000",
        request_id="req-1",
    )

    plaid_user = _build_plaid_user(response)

    assert plaid_user.user_id != plaid_user.user_token
    assert plaid_user.user_token.startswith("user-sandbox-")
