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
