"""The only boundary that speaks to Plaid.

Provider responses are translated into application dataclasses here so that no
Plaid SDK type, access token, or raw request body escapes into the rest of the
application. Provider exceptions become `PlaidGatewayError` carrying only the
error code, request ID, and a retry classification.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

BankSlug = Literal["capital-one", "chase", "citi", "wells-fargo"]
RetryClass = Literal["transient", "owner_action", "permanent", "unsupported"]

DAYS_REQUESTED = 730


@dataclass(frozen=True)
class SupportedBank:
    slug: str
    display_name: str
    institution_ids: frozenset[str]


SUPPORTED_BANKS: dict[str, SupportedBank] = {
    "capital-one": SupportedBank(
        "capital-one", "Capital One", frozenset({"ins_128026"})
    ),
    "chase": SupportedBank(
        # ins_3 is Chase's legacy (pre-OAuth) institution ID; ins_56 is the
        # entity real Link traffic resolves to since Chase migrated to
        # OAuth. Plaid never merged the two, so both remain "Chase".
        "chase", "Chase", frozenset({"ins_3", "ins_56"})
    ),
    "citi": SupportedBank("citi", "Citi", frozenset({"ins_5"})),
    "wells-fargo": SupportedBank(
        # ins_4 is stale; ins_127991 is the ID Plaid's registry currently
        # returns for "Wells Fargo" in both sandbox and production.
        "wells-fargo", "Wells Fargo", frozenset({"ins_4", "ins_127991"})
    ),
}


def load_supported_banks(overrides_json: str | None) -> dict[str, SupportedBank]:
    """Allow an environment override so provider institution IDs can change."""

    banks = dict(SUPPORTED_BANKS)
    if not overrides_json:
        return banks
    parsed = json.loads(overrides_json)
    for slug, institution_ids in parsed.items():
        if slug not in banks:
            continue
        banks[slug] = SupportedBank(
            slug, banks[slug].display_name, frozenset(institution_ids)
        )
    return banks


@dataclass(frozen=True)
class LinkTokenRequest:
    client_user_id: str
    user_token: str | None
    redirect_uri: str
    webhook_url: str | None
    institution_id: str | None = None
    access_token: str | None = None
    days_requested: int = DAYS_REQUESTED


@dataclass(frozen=True)
class PlaidUser:
    """`/user/create`'s two distinct identifiers.

    `user_id` is the permanent identifier worth persisting (FR-CONN-003).
    `user_token` is a separate, differently-formatted value Link actually
    requires; conflating the two produces Plaid's INVALID_USER_TOKEN error.
    """

    user_id: str
    user_token: str


@dataclass(frozen=True)
class ExchangedItem:
    access_token: str
    item_id: str
    institution_id: str | None = None


@dataclass(frozen=True)
class PlaidAccount:
    account_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str
    subtype: str | None


@dataclass(frozen=True)
class PlaidTransaction:
    transaction_id: str
    account_id: str
    name: str
    merchant_name: str | None
    original_description: str | None
    amount: Decimal
    iso_currency_code: str | None
    date: date | None
    authorized_date: date | None
    pending: bool
    category: str | None = None


@dataclass(frozen=True)
class SyncPage:
    added: Sequence[PlaidTransaction]
    modified: Sequence[PlaidTransaction]
    removed_ids: Sequence[str]
    next_cursor: str
    has_more: bool
    request_id: str | None = None


@dataclass(frozen=True)
class ItemStatus:
    item_id: str
    institution_id: str | None
    error_code: str | None
    consent_expiration_time: str | None
    last_successful_update: str | None


@dataclass(frozen=True)
class WebhookEvent:
    webhook_type: str | None
    webhook_code: str | None
    item_id: str | None
    payload: dict[str, object] = field(default_factory=dict)


class PlaidGatewayError(Exception):
    """A provider failure reduced to owner-safe, loggable fields."""

    def __init__(
        self,
        error_code: str,
        retry_class: RetryClass,
        request_id: str | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retry_class = retry_class
        self.request_id = request_id

    def __str__(self) -> str:
        return f"{self.error_code} (retry={self.retry_class})"


class SyncMutationDuringPagination(Exception):
    """Plaid reported TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION."""


class RefreshUnsupported(Exception):
    """The institution does not support /transactions/refresh."""


class PlaidGateway(Protocol):
    def create_user(self, client_user_id: str) -> PlaidUser:
        raise NotImplementedError

    def create_link_token(self, request: LinkTokenRequest) -> str:
        raise NotImplementedError

    def exchange_public_token(self, public_token: str) -> ExchangedItem:
        raise NotImplementedError

    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        raise NotImplementedError

    def get_item_status(self, access_token: str) -> ItemStatus:
        raise NotImplementedError

    def transactions_sync(self, access_token: str, cursor: str) -> SyncPage:
        raise NotImplementedError

    def transactions_refresh(self, access_token: str) -> None:
        raise NotImplementedError

    def remove_item(self, access_token: str) -> None:
        raise NotImplementedError

    def verify_webhook(self, body: bytes, verification_header: str | None) -> bool:
        raise NotImplementedError


OWNER_ACTION_CODES = frozenset(
    {
        "ITEM_LOGIN_REQUIRED",
        "PENDING_EXPIRATION",
        "PENDING_DISCONNECT",
        "ITEM_NOT_SUPPORTED",
        "INVALID_CREDENTIALS",
        "INVALID_MFA",
        "USER_PERMISSION_REVOKED",
        "USER_ACCOUNT_REVOKED",
        "ACCESS_NOT_GRANTED",
        "NO_ACCOUNTS",
    }
)

TRANSIENT_CODES = frozenset(
    {
        "INSTITUTION_DOWN",
        "INSTITUTION_NOT_RESPONDING",
        "INSTITUTION_NO_LONGER_SUPPORTED",
        "INTERNAL_SERVER_ERROR",
        "PLANNED_MAINTENANCE",
        "RATE_LIMIT",
        "RATE_LIMIT_EXCEEDED",
        "PRODUCT_NOT_READY",
        "TRANSACTIONS_SYNC_LIMIT",
    }
)

UNSUPPORTED_CODES = frozenset(
    {"PRODUCTS_NOT_SUPPORTED", "TRANSACTIONS_REFRESH_NOT_SUPPORTED"}
)


def classify_error_code(code: str | None) -> RetryClass:
    if code is None:
        return "transient"
    if code in OWNER_ACTION_CODES:
        return "owner_action"
    if code in UNSUPPORTED_CODES:
        return "unsupported"
    if code in TRANSIENT_CODES:
        return "transient"
    return "permanent"


__all__ = [
    "DAYS_REQUESTED",
    "BankSlug",
    "ExchangedItem",
    "ItemStatus",
    "LinkTokenRequest",
    "PlaidAccount",
    "PlaidGateway",
    "PlaidGatewayError",
    "PlaidUser",
    "PlaidTransaction",
    "RefreshUnsupported",
    "RetryClass",
    "SUPPORTED_BANKS",
    "SupportedBank",
    "SyncMutationDuringPagination",
    "SyncPage",
    "WebhookEvent",
    "classify_error_code",
    "load_supported_banks",
]
