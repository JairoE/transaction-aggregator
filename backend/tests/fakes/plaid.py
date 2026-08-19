"""A programmable in-memory Plaid gateway for tests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.plaid_gateway import (
    ExchangedItem,
    ItemStatus,
    LinkTokenRequest,
    PlaidAccount,
    PlaidGatewayError,
    PlaidTransaction,
    RefreshUnsupported,
    SyncMutationDuringPagination,
    SyncPage,
)


def credit_card(
    account_id: str, name: str, mask: str, official_name: str | None = None
) -> PlaidAccount:
    return PlaidAccount(
        account_id=account_id,
        name=name,
        official_name=official_name,
        mask=mask,
        type="credit",
        subtype="credit card",
    )


def checking(account_id: str, name: str = "Everyday Checking") -> PlaidAccount:
    return PlaidAccount(
        account_id=account_id,
        name=name,
        official_name=None,
        mask="0001",
        type="depository",
        subtype="checking",
    )


def transaction(
    transaction_id: str,
    account_id: str,
    *,
    name: str = "Urban Market",
    merchant_name: str | None = "Urban Market",
    original_description: str | None = None,
    amount: str = "64.18",
    posted: date | None = None,
    pending: bool = False,
) -> PlaidTransaction:
    return PlaidTransaction(
        transaction_id=transaction_id,
        account_id=account_id,
        name=name,
        merchant_name=merchant_name,
        original_description=original_description,
        amount=Decimal(amount),
        iso_currency_code="USD",
        date=posted or date(2026, 8, 12),
        authorized_date=posted or date(2026, 8, 12),
        pending=pending,
    )


@dataclass
class FakePlaidGateway:
    """Records every call and replays scripted responses."""

    accounts_by_token: dict[str, list[PlaidAccount]] = field(default_factory=dict)
    sync_pages: dict[str, list[SyncPage]] = field(default_factory=dict)
    item_statuses: dict[str, ItemStatus] = field(default_factory=dict)
    institution_for_public_token: dict[str, str] = field(default_factory=dict)

    link_token_requests: list[LinkTokenRequest] = field(default_factory=list)
    removed_tokens: list[str] = field(default_factory=list)
    refreshed_tokens: list[str] = field(default_factory=list)
    created_users: list[str] = field(default_factory=list)

    refresh_supported: bool = True
    shared_default_accounts: bool = True
    webhook_valid: bool = True
    exchange_error: PlaidGatewayError | None = None
    accounts_error: PlaidGatewayError | None = None
    sync_error: Exception | None = None
    mutation_once_at_call: int | None = None

    _sync_calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _mutation_raised: bool = False
    _next_item_index: int = 0

    # --- gateway protocol -------------------------------------------------
    def create_user(self, client_user_id: str) -> str:
        self.created_users.append(client_user_id)
        return f"plaid-user-{client_user_id}"

    def create_link_token(self, request: LinkTokenRequest) -> str:
        self.link_token_requests.append(request)
        suffix = "update" if request.access_token else "new"
        return f"link-sandbox-{suffix}-{len(self.link_token_requests)}"

    def exchange_public_token(self, public_token: str) -> ExchangedItem:
        if self.exchange_error is not None:
            raise self.exchange_error
        self._next_item_index += 1
        index = self._next_item_index
        access_token = f"access-sandbox-{public_token}-{index}"
        item_id = f"item-{public_token}-{index}"
        return ExchangedItem(
            access_token=access_token,
            item_id=item_id,
            institution_id=self.institution_for_public_token.get(public_token),
        )

    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        if self.accounts_error is not None:
            raise self.accounts_error
        scripted = self.accounts_by_token.get(access_token)
        if scripted is not None:
            return list(scripted)
        if self.shared_default_accounts:
            return self.default_accounts()
        # Plaid account ids are globally unique, so distinct Items must not
        # reuse them; derive a stable suffix from the token.
        suffix = access_token.rsplit("-", 1)[-1]
        return [
            credit_card(f"acct-credit-1-{suffix}", "Venture", "4812"),
            credit_card(f"acct-credit-2-{suffix}", "Savor", "9064"),
            checking(f"acct-checking-1-{suffix}"),
        ]

    def get_item_status(self, access_token: str) -> ItemStatus:
        return self.item_statuses.get(
            access_token,
            ItemStatus(
                item_id="item-unknown",
                institution_id=None,
                error_code=None,
                consent_expiration_time=None,
                last_successful_update=None,
            ),
        )

    def transactions_sync(self, access_token: str, cursor: str) -> SyncPage:
        call_index = self._sync_calls[access_token]
        self._sync_calls[access_token] = call_index + 1

        if (
            self.mutation_once_at_call is not None
            and call_index == self.mutation_once_at_call
            and not self._mutation_raised
        ):
            self._mutation_raised = True
            raise SyncMutationDuringPagination()

        if self.sync_error is not None:
            error, self.sync_error = self.sync_error, None
            raise error

        pages = self.sync_pages.get(access_token, [])
        for page in pages:
            if _cursor_matches(page, cursor):
                return page
        return SyncPage(
            added=(), modified=(), removed_ids=(), next_cursor=cursor or "cursor-0",
            has_more=False,
        )

    def transactions_refresh(self, access_token: str) -> None:
        if not self.refresh_supported:
            raise RefreshUnsupported()
        self.refreshed_tokens.append(access_token)

    def remove_item(self, access_token: str) -> None:
        self.removed_tokens.append(access_token)

    def verify_webhook(self, body: bytes, verification_header: str | None) -> bool:
        return self.webhook_valid

    # --- test helpers -----------------------------------------------------
    @staticmethod
    def default_accounts() -> list[PlaidAccount]:
        return [
            credit_card("acct-credit-1", "Venture", "4812"),
            credit_card("acct-credit-2", "Savor", "9064"),
            checking("acct-checking-1"),
        ]

    def script_sync(self, access_token: str, pages: Sequence[SyncPage]) -> None:
        self.sync_pages[access_token] = list(pages)

    def sync_call_count(self, access_token: str) -> int:
        return self._sync_calls[access_token]


def _cursor_matches(page: SyncPage, cursor: str) -> bool:
    return getattr(page, "_request_cursor", cursor) == cursor


def page(
    *,
    request_cursor: str = "",
    added: Sequence[PlaidTransaction] = (),
    modified: Sequence[PlaidTransaction] = (),
    removed_ids: Sequence[str] = (),
    next_cursor: str = "cursor-1",
    has_more: bool = False,
) -> SyncPage:
    built = SyncPage(
        added=added,
        modified=modified,
        removed_ids=removed_ids,
        next_cursor=next_cursor,
        has_more=has_more,
    )
    object.__setattr__(built, "_request_cursor", request_cursor)
    return built


__all__ = [
    "FakePlaidGateway",
    "checking",
    "credit_card",
    "page",
    "transaction",
]
