"""A deterministic in-process bank used by the demo environment and e2e tests.

It implements `PlaidGateway` exactly, so every layer above it — encryption,
sync, cursors, search — runs the real code path. No network call is made and no
real bank credential is ever involved. The fixture is the approved acceptance
set: four banks, two credit cards each, and ten `Paze` matches spread across
all eight cards.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.plaid_gateway import (
    SUPPORTED_BANKS,
    ExchangedItem,
    ItemStatus,
    LinkTokenRequest,
    PlaidAccount,
    PlaidGatewayError,
    PlaidTransaction,
    RefreshUnsupported,
    SyncPage,
)

PAGE_SIZE = 100
HISTORY_DAYS = 730
FIXTURE_TODAY = date(2026, 8, 19)


@dataclass(frozen=True)
class DemoCard:
    account_id: str
    name: str
    official_name: str
    mask: str


@dataclass(frozen=True)
class DemoBank:
    slug: str
    display_name: str
    institution_id: str
    cards: tuple[DemoCard, ...]


DEMO_BANKS: dict[str, DemoBank] = {
    "capital-one": DemoBank(
        "capital-one",
        "Capital One",
        "ins_128026",
        (
            DemoCard("demo-co-venture", "Venture", "Capital One Venture", "4812"),
            DemoCard("demo-co-savor", "Savor", "Capital One Savor Rewards", "9064"),
        ),
    ),
    "chase": DemoBank(
        "chase",
        "Chase",
        "ins_3",
        (
            DemoCard(
                "demo-ch-sapphire",
                "Sapphire Preferred",
                "Chase Sapphire Preferred",
                "1187",
            ),
            DemoCard(
                "demo-ch-freedom",
                "Freedom Unlimited",
                "Chase Freedom Unlimited",
                "2041",
            ),
        ),
    ),
    "citi": DemoBank(
        "citi",
        "Citi",
        "ins_5",
        (
            DemoCard("demo-ci-double", "Double Cash", "Citi Double Cash Card", "7730"),
            DemoCard("demo-ci-custom", "Custom Cash", "Citi Custom Cash Card", "3628"),
        ),
    ),
    "wells-fargo": DemoBank(
        "wells-fargo",
        "Wells Fargo",
        "ins_4",
        (
            DemoCard("demo-wf-active", "Active Cash", "Wells Fargo Active Cash", "5509"),
            DemoCard("demo-wf-autograph", "Autograph", "Wells Fargo Autograph", "6144"),
        ),
    ),
}

# The approved acceptance fixture: ten Paze transactions across all eight cards.
PAZE_FIXTURE: tuple[tuple[str, str, str, str, str], ...] = (
    ("demo-co-venture", "Urban Market", "64.18", "2026-08-12", "PAZE*URBAN MARKET"),
    ("demo-co-venture", "Metro Transit", "22.50", "2026-07-29", "PAZE*METRO TRANSIT"),
    ("demo-co-savor", "Harbor Books", "38.42", "2026-08-08", "PAZE*HARBOR BOOKS"),
    ("demo-ch-sapphire", "Northstar Air", "342.16", "2026-08-06", "PAZE*NORTHSTAR AIR"),
    ("demo-ch-freedom", "Corner Market", "78.36", "2026-08-03", "PAZE*CORNER MARKET"),
    ("demo-ch-freedom", "Beacon Pharmacy", "16.84", "2026-07-22", "PAZE*BEACON RX"),
    ("demo-ci-double", "Canvas Supply", "54.90", "2026-08-01", "PAZE*CANVAS SUPPLY"),
    ("demo-ci-custom", "Green Basket", "91.20", "2026-07-31", "PAZE*GREEN BASKET"),
    ("demo-wf-active", "Maple Market", "43.68", "2026-07-27", "PAZE*MAPLE MARKET"),
    ("demo-wf-autograph", "Redwood Rail", "116.00", "2026-07-25", "PAZE*REDWOOD RAIL"),
)

# Recent rows shown before any search is submitted, newest first per card.
RECENT_FIXTURE: tuple[tuple[str, str, str, str, str], ...] = (
    ("demo-co-venture", "Juniper Hotel", "184.20", "2026-08-17", "Travel"),
    ("demo-co-venture", "Atlas Coffee", "12.80", "2026-08-15", "Dining"),
    ("demo-co-venture", "Cloud Nine Market", "74.11", "2026-08-13", "Groceries"),
    ("demo-co-savor", "Olive & Oak", "96.44", "2026-08-16", "Dining"),
    ("demo-co-savor", "Reel Cinema", "28.00", "2026-08-14", "Entertainment"),
    ("demo-co-savor", "Fresh Fields", "52.19", "2026-08-10", "Groceries"),
    ("demo-ch-sapphire", "Northstar Air", "418.90", "2026-08-17", "Travel"),
    ("demo-ch-sapphire", "Harbor Rides", "34.62", "2026-08-11", "Transit"),
    ("demo-ch-sapphire", "Kite & Key", "73.16", "2026-08-09", "Dining"),
    ("demo-ch-freedom", "Corner Market", "68.29", "2026-08-18", "Groceries"),
    ("demo-ch-freedom", "Beacon Pharmacy", "19.47", "2026-08-12", "Health"),
    ("demo-ch-freedom", "Streamline", "14.99", "2026-08-07", "Subscription"),
    ("demo-ci-double", "Canvas Supply", "44.50", "2026-08-18", "Shopping"),
    ("demo-ci-double", "Ferry Line", "9.75", "2026-08-14", "Transit"),
    ("demo-ci-double", "Bright Cleaners", "31.40", "2026-08-09", "Services"),
    ("demo-ci-custom", "Green Basket", "91.20", "2026-08-16", "Groceries"),
    ("demo-ci-custom", "Nova Fitness", "48.00", "2026-08-12", "Health"),
    ("demo-ci-custom", "Paper Lantern", "27.65", "2026-08-06", "Dining"),
    ("demo-wf-active", "Maple Market", "43.68", "2026-08-18", "Groceries"),
    ("demo-wf-active", "City Parking", "18.00", "2026-08-13", "Transit"),
    ("demo-wf-active", "Bluebird Bakery", "22.35", "2026-08-08", "Dining"),
    ("demo-wf-autograph", "Redwood Rail", "116.00", "2026-08-17", "Travel"),
    ("demo-wf-autograph", "Summit Outfitters", "134.90", "2026-08-11", "Shopping"),
    ("demo-wf-autograph", "Lantern Diner", "39.25", "2026-08-05", "Dining"),
)

BACKFILL_MERCHANTS: tuple[tuple[str, str], ...] = (
    ("Riverside Grocer", "Groceries"),
    ("Copper Kettle", "Dining"),
    ("Transit Authority", "Transit"),
    ("Northgate Pharmacy", "Health"),
    ("Lakeshore Fuel", "Automotive"),
    ("Willow Hardware", "Home"),
    ("Beacon Books", "Shopping"),
    ("Sunset Cinema", "Entertainment"),
    ("Harbor Deli", "Dining"),
    ("Union Utilities", "Bills"),
    ("Bright Wireless", "Bills"),
    ("Cedar Cleaners", "Services"),
)


def _card_bank(account_id: str) -> DemoBank:
    for bank in DEMO_BANKS.values():
        if any(card.account_id == account_id for card in bank.cards):
            return bank
    raise KeyError(account_id)


def _stable_int(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16)


def _backfill_for(card: DemoCard) -> list[PlaidTransaction]:
    """Two years of deterministic history so pagination is exercised."""

    rows: list[PlaidTransaction] = []
    for index in range(56):
        seed = _stable_int(card.account_id, str(index))
        merchant, category = BACKFILL_MERCHANTS[seed % len(BACKFILL_MERCHANTS)]
        offset = 20 + index * 12 + (seed % 7)
        if offset > HISTORY_DAYS:
            break
        posted = FIXTURE_TODAY - timedelta(days=offset)
        amount = Decimal(seed % 18000) / Decimal(100) + Decimal("3.25")
        rows.append(
            PlaidTransaction(
                transaction_id=f"demo-txn-{card.account_id}-{index:03d}",
                account_id=card.account_id,
                name=merchant,
                merchant_name=merchant,
                original_description=f"{merchant.upper()} #{seed % 9999:04d}",
                amount=amount.quantize(Decimal("0.01")),
                iso_currency_code="USD",
                date=posted,
                authorized_date=posted,
                pending=False,
                category=category,
            )
        )
    return rows


def _fixture_rows(card: DemoCard) -> list[PlaidTransaction]:
    rows: list[PlaidTransaction] = []
    for account_id, merchant, amount, posted, statement in PAZE_FIXTURE:
        if account_id != card.account_id:
            continue
        rows.append(
            PlaidTransaction(
                transaction_id=f"demo-paze-{account_id}-{merchant.lower().replace(' ', '-')}",
                account_id=account_id,
                name=f"Paze {merchant}",
                merchant_name=f"Paze · {merchant}",
                original_description=statement,
                amount=Decimal(amount),
                iso_currency_code="USD",
                date=date.fromisoformat(posted),
                authorized_date=date.fromisoformat(posted),
                pending=False,
                category="Shopping",
            )
        )
    for account_id, merchant, amount, posted, category in RECENT_FIXTURE:
        if account_id != card.account_id:
            continue
        rows.append(
            PlaidTransaction(
                transaction_id=f"demo-recent-{account_id}-{posted}",
                account_id=account_id,
                name=merchant,
                merchant_name=merchant,
                original_description=merchant.upper().replace(" ", " "),
                amount=Decimal(amount),
                iso_currency_code="USD",
                date=date.fromisoformat(posted),
                authorized_date=date.fromisoformat(posted),
                pending=False,
                category=category,
            )
        )
    return rows


def transactions_for_bank(bank: DemoBank) -> list[PlaidTransaction]:
    rows: list[PlaidTransaction] = []
    for card in bank.cards:
        rows.extend(_fixture_rows(card))
        rows.extend(_backfill_for(card))
    rows.sort(key=lambda row: (row.date or date.min, row.transaction_id), reverse=True)
    return rows


class DemoPlaidGateway:
    """Implements `PlaidGateway` against the fixture above."""

    def __init__(self) -> None:
        self.link_token_requests: list[LinkTokenRequest] = []

    @staticmethod
    def bank_for_token(token: str) -> DemoBank:
        for slug, bank in DEMO_BANKS.items():
            if slug in token:
                return bank
        raise PlaidGatewayError("ITEM_NOT_FOUND", "permanent")

    def create_user(self, client_user_id: str) -> str:
        return f"demo-user-{client_user_id}"

    def create_link_token(self, request: LinkTokenRequest) -> str:
        self.link_token_requests.append(request)
        slug = next(
            (
                slug
                for slug, bank in SUPPORTED_BANKS.items()
                if request.institution_id in bank.institution_ids
            ),
            "capital-one",
        )
        mode = "update" if request.access_token else "new"
        return f"link-demo-{slug}-{mode}"

    def exchange_public_token(self, public_token: str) -> ExchangedItem:
        bank = self.bank_for_token(public_token)
        return ExchangedItem(
            access_token=f"access-demo-{bank.slug}",
            item_id=f"item-demo-{bank.slug}",
            institution_id=bank.institution_id,
        )

    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        bank = self.bank_for_token(access_token)
        accounts = [
            PlaidAccount(
                account_id=card.account_id,
                name=card.name,
                official_name=card.official_name,
                mask=card.mask,
                type="credit",
                subtype="credit card",
            )
            for card in bank.cards
        ]
        # One non-credit account proves the dashboard filters it out.
        accounts.append(
            PlaidAccount(
                account_id=f"demo-{bank.slug}-checking",
                name="Everyday Checking",
                official_name=None,
                mask="0001",
                type="depository",
                subtype="checking",
            )
        )
        return accounts

    def get_item_status(self, access_token: str) -> ItemStatus:
        bank = self.bank_for_token(access_token)
        return ItemStatus(
            item_id=f"item-demo-{bank.slug}",
            institution_id=bank.institution_id,
            error_code=None,
            consent_expiration_time=None,
            last_successful_update=f"{FIXTURE_TODAY.isoformat()}T12:00:00+00:00",
        )

    def transactions_sync(self, access_token: str, cursor: str) -> SyncPage:
        bank = self.bank_for_token(access_token)
        rows = transactions_for_bank(bank)
        offset = int(cursor.rsplit(":", 1)[-1]) if cursor else 0
        window = rows[offset : offset + PAGE_SIZE]
        next_offset = offset + len(window)
        return SyncPage(
            added=window,
            modified=(),
            removed_ids=(),
            next_cursor=f"demo:{bank.slug}:{next_offset}",
            has_more=next_offset < len(rows),
            request_id=f"demo-request-{bank.slug}-{offset}",
        )

    def transactions_refresh(self, access_token: str) -> None:
        bank = self.bank_for_token(access_token)
        if bank.slug == "capital-one":
            # Capital One credit-only Items do not support /transactions/refresh.
            raise RefreshUnsupported()

    def remove_item(self, access_token: str) -> None:
        return None

    def verify_webhook(self, body: bytes, verification_header: str | None) -> bool:
        return True


__all__ = [
    "DEMO_BANKS",
    "DemoBank",
    "DemoCard",
    "DemoPlaidGateway",
    "PAZE_FIXTURE",
    "transactions_for_bank",
]
