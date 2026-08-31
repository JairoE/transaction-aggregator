"""Cached, grouped, per-card transaction search.

Every read here is local SQLite. Substring matching uses the FTS5 trigram
index for terms of three characters or more and an escaped LIKE over the
normalized column below that, because trigram indexes cannot serve shorter
needles. User input is never concatenated into SQL.
"""

from __future__ import annotations

import base64
import hmac
import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256

from sqlalchemy import Select, func, literal_column, or_, select, text, true
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models import BankConnection, CardAccount, Transaction
from app.services.plaid_gateway import SUPPORTED_BANKS

MAX_QUERY_LENGTH = 100
TRIGRAM_MINIMUM = 3
DEFAULT_PER_CARD_LIMIT = 25
MAX_PER_CARD_LIMIT = 50
BANK_ORDER = {slug: index for index, slug in enumerate(SUPPORTED_BANKS)}


@dataclass(frozen=True)
class NormalizedQuery:
    raw: str
    normalized: str
    is_blank: bool
    uses_index: bool
    fts_expression: str | None
    like_pattern: str | None


def normalize_query(query: str | None) -> NormalizedQuery:
    """Trim, case-fold, collapse whitespace, and cap length."""

    raw = (query or "").strip()
    folded = unicodedata.normalize("NFKD", raw)[:MAX_QUERY_LENGTH]
    normalized = " ".join(folded.casefold().split())

    if not normalized:
        return NormalizedQuery(raw, "", True, False, None, None)

    if len(normalized) >= TRIGRAM_MINIMUM:
        # Double quotes make the whole phrase one literal FTS5 string, so
        # punctuation and operators such as AND, *, ^ are treated as text.
        escaped = normalized.replace('"', '""')
        return NormalizedQuery(raw, normalized, False, True, f'"{escaped}"', None)

    like = (
        normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return NormalizedQuery(raw, normalized, False, False, None, f"%{like}%")


def transaction_match_filter(normalized: NormalizedQuery) -> ColumnElement[bool]:
    """Return the shared literal-substring predicate for cached transactions."""

    if normalized.is_blank:
        return true()
    if normalized.uses_index:
        matching_rowids = (
            select(literal_column("rowid"))
            .select_from(text("transactions_fts"))
            .where(text("transactions_fts MATCH :fts_query"))
            .params(fts_query=normalized.fts_expression)
        )
        return literal_column("transactions.rowid").in_(matching_rowids)
    return Transaction.search_text.like(normalized.like_pattern or "", escape="\\")


@dataclass(frozen=True)
class TransactionRow:
    id: str
    card_id: str
    merchant_name: str | None
    description: str
    original_description: str | None
    category: str | None
    amount_cents: int
    currency_code: str
    authorized_date: date | None
    posted_date: date | None
    pending: bool


@dataclass(frozen=True)
class CardRow:
    id: str
    connection_id: str
    bank: str
    bank_display_name: str
    name: str
    official_name: str | None
    mask: str | None
    display_order: int
    last_successful_sync_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True)
class CardGroup:
    card: CardRow
    transactions: list[TransactionRow]
    match_count: int
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class GroupedSearchResult:
    query: str
    total_matches: int
    groups: list[CardGroup]
    cache_as_of: datetime | None


@dataclass(frozen=True)
class AllTransactionRow:
    transaction: TransactionRow
    card: CardRow


@dataclass(frozen=True)
class AllTransactionsResult:
    query: str
    total_matches: int
    card_count: int
    bank_count: int
    rows: list[AllTransactionRow]
    next_cursor: str | None
    has_more: bool
    cache_as_of: datetime | None


class CursorCodec:
    """Opaque, signed, card-scoped continuation cursors."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def encode(self, card_id: str, sort_date: str | None, row_id: str) -> str:
        payload = json.dumps(
            {"c": card_id, "d": sort_date, "i": row_id}, separators=(",", ":")
        ).encode("utf-8")
        signature = hmac.new(self._secret, payload, sha256).digest()[:16]
        return _b64(payload) + "." + _b64(signature)

    def decode(self, cursor: str, expected_card_id: str) -> tuple[str | None, str]:
        try:
            payload_part, signature_part = cursor.split(".", 1)
            payload = _unb64(payload_part)
            signature = _unb64(signature_part)
        except (ValueError, TypeError) as error:
            raise _cursor_invalid() from error

        expected = hmac.new(self._secret, payload, sha256).digest()[:16]
        if not hmac.compare_digest(expected, signature):
            raise _cursor_invalid()

        try:
            data = json.loads(payload)
        except ValueError as error:
            raise _cursor_invalid() from error

        if data.get("c") != expected_card_id:
            # A cursor from one card must never paginate another card's list.
            raise _cursor_invalid()
        return data.get("d"), str(data.get("i"))


class AggregateCursorCodec:
    """Opaque, signed continuation cursors bound to a normalized query."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def encode(self, query: str, sort_date: str | None, row_id: str) -> str:
        payload = json.dumps(
            {"q": query, "d": sort_date, "i": row_id}, separators=(",", ":")
        ).encode("utf-8")
        signature = hmac.new(self._secret, payload, sha256).digest()[:16]
        return _b64(payload) + "." + _b64(signature)

    def decode(self, cursor: str, expected_query: str) -> tuple[str | None, str]:
        try:
            payload_part, signature_part = cursor.split(".", 1)
            payload = _unb64(payload_part)
            signature = _unb64(signature_part)
        except (ValueError, TypeError) as error:
            raise _cursor_invalid() from error

        expected = hmac.new(self._secret, payload, sha256).digest()[:16]
        if not hmac.compare_digest(expected, signature):
            raise _cursor_invalid()

        try:
            data = json.loads(payload)
            query = data["q"]
            sort_date = data["d"]
            row_id = data["i"]
        except (KeyError, TypeError, ValueError) as error:
            raise _cursor_invalid() from error

        if query != expected_query or not isinstance(row_id, str):
            raise _cursor_invalid()
        if sort_date is not None and not isinstance(sort_date, str):
            raise _cursor_invalid()
        return sort_date, row_id


def _cursor_invalid() -> AppError:
    return AppError("CURSOR_INVALID", "That page link is no longer valid.", 400)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SearchService:
    def __init__(self, session: AsyncSession, application_secret: str) -> None:
        self._session = session
        self._cursors = CursorCodec(application_secret)
        self._aggregate_cursors = AggregateCursorCodec(application_secret)

    async def list_cards(self, owner_id: str) -> list[CardRow]:
        rows = (
            await self._session.execute(
                select(CardAccount, BankConnection)
                .join(BankConnection, BankConnection.id == CardAccount.connection_id)
                .where(BankConnection.owner_id == owner_id)
                .where(BankConnection.lifecycle_status == "active")
                .where(CardAccount.is_active.is_(True))
            )
        ).all()

        cards = [
            CardRow(
                id=card.id,
                connection_id=connection.id,
                bank=connection.bank_slug,
                bank_display_name=connection.institution_name,
                name=card.name,
                official_name=card.official_name,
                mask=card.mask,
                display_order=card.display_order,
                last_successful_sync_at=connection.last_successful_sync_at,
                last_error_code=connection.last_error_code,
            )
            for card, connection in rows
        ]
        cards.sort(
            key=lambda card: (
                BANK_ORDER.get(card.bank, 99),
                card.display_order,
                card.name,
                card.id,
            )
        )
        return cards

    async def search(
        self,
        owner_id: str,
        query: str | None = None,
        per_card_limit: int = DEFAULT_PER_CARD_LIMIT,
        cursors: dict[str, str] | None = None,
    ) -> GroupedSearchResult:
        limit = max(1, min(per_card_limit, MAX_PER_CARD_LIMIT))
        normalized = normalize_query(query)
        cards = await self.list_cards(owner_id)
        cursors = cursors or {}

        groups: list[CardGroup] = []
        total = 0
        cache_as_of: datetime | None = None

        for card in cards:
            match_count = await self._count(card.id, normalized)
            total += match_count
            rows = await self._page(
                card.id, normalized, limit, cursors.get(card.id)
            )
            has_more = len(rows) > limit
            visible = rows[:limit]
            next_cursor = None
            if has_more and visible:
                last = visible[-1]
                sort_date = (last.posted_date or last.authorized_date)
                next_cursor = self._cursors.encode(
                    card.id, sort_date.isoformat() if sort_date else None, last.id
                )
            groups.append(
                CardGroup(
                    card=card,
                    transactions=visible,
                    match_count=match_count,
                    next_cursor=next_cursor,
                    has_more=has_more,
                )
            )
            if card.last_successful_sync_at is not None:
                cache_as_of = (
                    card.last_successful_sync_at
                    if cache_as_of is None
                    else min(cache_as_of, card.last_successful_sync_at)
                )

        return GroupedSearchResult(
            query=normalized.raw,
            total_matches=total,
            groups=groups,
            cache_as_of=cache_as_of,
        )

    async def card_transactions(
        self,
        owner_id: str,
        card_id: str,
        query: str | None = None,
        limit: int = DEFAULT_PER_CARD_LIMIT,
        cursor: str | None = None,
    ) -> CardGroup:
        cards = {card.id: card for card in await self.list_cards(owner_id)}
        card = cards.get(card_id)
        if card is None:
            raise AppError("NOT_FOUND", "That card was not found.", 404)

        capped = max(1, min(limit, MAX_PER_CARD_LIMIT))
        normalized = normalize_query(query)
        rows = await self._page(card_id, normalized, capped, cursor)
        has_more = len(rows) > capped
        visible = rows[:capped]
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            sort_date = last.posted_date or last.authorized_date
            next_cursor = self._cursors.encode(
                card_id, sort_date.isoformat() if sort_date else None, last.id
            )
        return CardGroup(
            card=card,
            transactions=visible,
            match_count=await self._count(card_id, normalized),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def all_transactions(
        self,
        owner_id: str,
        query: str | None = None,
        limit: int = MAX_PER_CARD_LIMIT,
        cursor: str | None = None,
    ) -> AllTransactionsResult:
        capped = max(1, min(limit, MAX_PER_CARD_LIMIT))
        normalized = normalize_query(query)
        cards = await self.list_cards(owner_id)
        cache_as_of = _cache_as_of(cards)
        statement = self._aggregate_matching(owner_id, normalized)
        total_statement = select(func.count()).select_from(statement.subquery())
        total_matches = int(
            (await self._session.execute(total_statement)).scalar_one()
        )

        sort_date = func.coalesce(Transaction.posted_date, Transaction.authorized_date)
        if cursor:
            last_date, last_id = self._aggregate_cursors.decode(
                cursor, normalized.normalized
            )
            if last_date is None:
                statement = statement.where(sort_date.is_(None)).where(
                    Transaction.id < last_id
                )
            else:
                statement = statement.where(
                    or_(
                        sort_date.is_(None),
                        sort_date < last_date,
                        (sort_date == last_date) & (Transaction.id < last_id),
                    )
                )

        statement = statement.order_by(
            sort_date.is_(None).asc(), sort_date.desc(), Transaction.id.desc()
        ).limit(capped + 1)
        page = (await self._session.execute(statement)).all()
        has_more = len(page) > capped
        visible = page[:capped]
        rows = [
            AllTransactionRow(
                transaction=_to_row(transaction),
                card=_card_to_row(card, connection),
            )
            for transaction, card, connection in visible
        ]
        next_cursor = None
        if has_more and rows:
            last = rows[-1].transaction
            last_date = last.posted_date or last.authorized_date
            next_cursor = self._aggregate_cursors.encode(
                normalized.normalized,
                last_date.isoformat() if last_date else None,
                last.id,
            )

        return AllTransactionsResult(
            query=normalized.raw,
            total_matches=total_matches,
            card_count=len(cards),
            bank_count=len({card.bank for card in cards}),
            rows=rows,
            next_cursor=next_cursor,
            has_more=has_more,
            cache_as_of=cache_as_of,
        )

    # --- query building ---------------------------------------------------
    def _matching(self, card_id: str, normalized: NormalizedQuery) -> Select[tuple]:
        return (
            select(Transaction)
            .where(Transaction.card_account_id == card_id)
            .where(transaction_match_filter(normalized))
        )

    def _aggregate_matching(
        self, owner_id: str, normalized: NormalizedQuery
    ) -> Select[tuple[Transaction, CardAccount, BankConnection]]:
        return (
            select(Transaction, CardAccount, BankConnection)
            .join(CardAccount, CardAccount.id == Transaction.card_account_id)
            .join(BankConnection, BankConnection.id == CardAccount.connection_id)
            .where(BankConnection.owner_id == owner_id)
            .where(BankConnection.lifecycle_status == "active")
            .where(CardAccount.is_active.is_(True))
            .where(transaction_match_filter(normalized))
        )

    async def _count(self, card_id: str, normalized: NormalizedQuery) -> int:
        statement = select(func.count()).select_from(
            self._matching(card_id, normalized).subquery()
        )
        return int((await self._session.execute(statement)).scalar_one())

    async def _page(
        self,
        card_id: str,
        normalized: NormalizedQuery,
        limit: int,
        cursor: str | None,
    ) -> list[TransactionRow]:
        sort_date = func.coalesce(Transaction.posted_date, Transaction.authorized_date)
        statement = self._matching(card_id, normalized)

        if cursor:
            last_date, last_id = self._cursors.decode(cursor, card_id)
            if last_date is None:
                statement = statement.where(sort_date.is_(None)).where(
                    Transaction.id < last_id
                )
            else:
                statement = statement.where(
                    or_(
                        sort_date < last_date,
                        (sort_date == last_date) & (Transaction.id < last_id),
                    )
                )

        statement = statement.order_by(sort_date.desc(), Transaction.id.desc()).limit(
            limit + 1
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [_to_row(row) for row in rows]


def _to_row(row: Transaction) -> TransactionRow:
    return TransactionRow(
        id=row.id,
        card_id=row.card_account_id,
        merchant_name=row.merchant_name,
        description=row.name,
        original_description=row.original_description,
        category=row.category,
        amount_cents=row.amount_cents,
        currency_code=row.currency_code,
        authorized_date=row.authorized_date,
        posted_date=row.posted_date,
        pending=row.pending,
    )


def _card_to_row(card: CardAccount, connection: BankConnection) -> CardRow:
    return CardRow(
        id=card.id,
        connection_id=connection.id,
        bank=connection.bank_slug,
        bank_display_name=connection.institution_name,
        name=card.name,
        official_name=card.official_name,
        mask=card.mask,
        display_order=card.display_order,
        last_successful_sync_at=connection.last_successful_sync_at,
        last_error_code=connection.last_error_code,
    )


def _cache_as_of(cards: list[CardRow]) -> datetime | None:
    synced = [card.last_successful_sync_at for card in cards]
    return min((value for value in synced if value is not None), default=None)


__all__ = [
    "DEFAULT_PER_CARD_LIMIT",
    "MAX_PER_CARD_LIMIT",
    "AggregateCursorCodec",
    "AllTransactionRow",
    "AllTransactionsResult",
    "CardGroup",
    "CardRow",
    "CursorCodec",
    "GroupedSearchResult",
    "NormalizedQuery",
    "SearchService",
    "transaction_match_filter",
    "TransactionRow",
    "normalize_query",
]
