"""End-to-end tests against the real Plaid Sandbox API.

Every test here is marked `plaid_sandbox` and skipped unless credentials are
present, so `make test` stays offline. See `conftest.py` for why Sandbox is
free to exercise this aggressively.

What these cover that the fakes cannot: the shapes Plaid actually returns.
Both production incidents this suite exists to prevent — `/user/create`
returning two differently-formatted identifiers, and institutions changing
their `institution_id` — were contract mismatches that every offline test
happily agreed with.
"""

from __future__ import annotations

import pytest

from app.services.plaid_client import PlaidPythonGateway
from app.services.plaid_gateway import LinkTokenRequest
from tests.integration.conftest import (
    requires_registered_redirect_uri,
    requires_sandbox_credentials,
)

pytestmark = [pytest.mark.plaid_sandbox, requires_sandbox_credentials]


# --- users ----------------------------------------------------------------
def test_user_create_returns_two_distinct_identifiers(
    gateway: PlaidPythonGateway,
) -> None:
    """The production bug in full: `user_id` and `user_token` are different
    values in different formats, and Link only accepts the latter. An offline
    test can assert this about a hand-built response object; only a live call
    proves Plaid still behaves that way.
    """
    plaid_user = gateway.create_user("integration-owner")

    assert plaid_user.user_id
    assert plaid_user.user_token
    assert plaid_user.user_id != plaid_user.user_token
    assert plaid_user.user_token.startswith("user-")


def test_user_create_is_idempotent_on_client_user_id(
    gateway: PlaidPythonGateway,
) -> None:
    """`_ensure_plaid_user` persists `user_id` once but re-fetches `user_token`
    on every Link session, which is only correct if repeat calls return the
    same id and a usable token.
    """
    first = gateway.create_user("integration-owner-idempotent")
    second = gateway.create_user("integration-owner-idempotent")

    assert first.user_id == second.user_id


# --- link tokens ----------------------------------------------------------
@requires_registered_redirect_uri
def test_link_token_create_accepts_the_user_token(
    gateway: PlaidPythonGateway, sandbox_settings
) -> None:
    """Passing `user_id` where Plaid wants `user_token` is what produced
    INVALID_USER_TOKEN in production. This is the call that failed.
    """
    plaid_user = gateway.create_user("integration-owner-link")

    link_token = gateway.create_link_token(
        LinkTokenRequest(
            client_user_id="integration-owner-link",
            user_token=plaid_user.user_token,
            redirect_uri=sandbox_settings.oauth_redirect_uri,
            webhook_url=None,
        )
    )

    assert link_token.startswith("link-sandbox-")


# --- exchange -------------------------------------------------------------
def test_exchange_reports_the_institution_that_was_linked(
    gateway: PlaidPythonGateway,
) -> None:
    """`exchange_public_token` folds an `/item/get` into its result so the
    caller can validate the institution. If that ever stops being populated,
    the connection flow silently loses the field it makes decisions on.
    """
    from tests.integration.conftest import (
        SANDBOX_INSTITUTION_ID,
        create_sandbox_public_token,
    )

    public_token = create_sandbox_public_token(gateway, SANDBOX_INSTITUTION_ID)
    exchanged = gateway.exchange_public_token(public_token)

    try:
        assert exchanged.access_token.startswith("access-sandbox-")
        assert exchanged.item_id
        assert exchanged.institution_id == SANDBOX_INSTITUTION_ID
    finally:
        try:
            gateway.remove_item(exchanged.access_token)
        except Exception:  # noqa: BLE001 - cleanup must not mask a failure
            pass


# --- accounts -------------------------------------------------------------
def test_accounts_carry_the_fields_card_discovery_depends_on(
    gateway: PlaidPythonGateway, sandbox_item: str
) -> None:
    accounts = gateway.get_accounts(sandbox_item)

    assert accounts, "sandbox item returned no accounts"
    for account in accounts:
        assert account.account_id
        assert account.name
        assert account.type

    credit = [account for account in accounts if account.type == "credit"]
    assert credit, "sandbox item exposed no credit accounts to surface as cards"
    assert any(account.subtype == "credit card" for account in credit)


# --- item status ----------------------------------------------------------
def test_item_status_is_healthy_for_a_fresh_item(
    gateway: PlaidPythonGateway, sandbox_item: str
) -> None:
    status = gateway.get_item_status(sandbox_item)

    assert status.item_id
    assert status.institution_id
    assert status.error_code is None


# --- transactions ---------------------------------------------------------
def test_transactions_sync_returns_a_usable_cursor(
    gateway: PlaidPythonGateway, sandbox_item: str
) -> None:
    """Asserts the pagination contract the sync worker is built on, not the
    presence of data: Sandbox populates transactions asynchronously, so a
    first page can legitimately be empty. The cursor must always advance.
    """
    page = gateway.transactions_sync(sandbox_item, "")

    assert page.next_cursor, "an empty cursor would restart the sync forever"
    assert isinstance(page.has_more, bool)
    assert page.removed_ids == [] or all(page.removed_ids)

    for transaction in page.added:
        assert transaction.transaction_id
        assert transaction.account_id
        assert transaction.name
        assert transaction.amount is not None


def test_transactions_sync_is_incremental(
    gateway: PlaidPythonGateway, sandbox_item: str
) -> None:
    """Re-syncing from the returned cursor must not replay the same rows —
    the property that keeps the local cache from duplicating history.
    """
    first = gateway.transactions_sync(sandbox_item, "")
    while first.has_more:
        first = gateway.transactions_sync(sandbox_item, first.next_cursor)

    second = gateway.transactions_sync(sandbox_item, first.next_cursor)

    assert second.added == []
    assert second.modified == []
    assert second.removed_ids == []


# --- removal --------------------------------------------------------------
def test_remove_item_revokes_the_access_token(gateway: PlaidPythonGateway) -> None:
    """The cleanup path the wrong-institution guard relies on. After removal
    the token must be genuinely dead, not merely marked inactive locally.
    """
    from app.services.plaid_gateway import PlaidGatewayError
    from tests.integration.conftest import (
        SANDBOX_INSTITUTION_ID,
        exchange_sandbox_item,
    )

    access_token = exchange_sandbox_item(gateway, SANDBOX_INSTITUTION_ID)

    gateway.remove_item(access_token)

    with pytest.raises(PlaidGatewayError):
        gateway.get_item_status(access_token)
