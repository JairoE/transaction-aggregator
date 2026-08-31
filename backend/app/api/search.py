"""Grouped cached search and per-card continuation.

Neither route calls Plaid; both read only the local SQLite cache.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import OwnerDep, SessionDep, SettingsDep
from app.schemas import (
    AllTransactionRow,
    AllTransactionsResponse,
    CardResponse,
    CardTransactionGroup,
    GroupedSearchResponse,
    TransactionMatch,
)
from app.services.search_service import (
    DEFAULT_PER_CARD_LIMIT,
    MAX_PER_CARD_LIMIT,
    AllTransactionRow as AllTransactionServiceRow,
    CardGroup,
    CardRow,
    SearchService,
    TransactionRow,
)

router = APIRouter(prefix="/api", tags=["search"])

CURSOR_PREFIX = "cursor."


async def search_service_dep(session: SessionDep, settings: SettingsDep) -> SearchService:
    return SearchService(session, settings.application_secret.get_secret_value())


ServiceDep = Depends(search_service_dep)


def _serialize(group: CardGroup) -> CardTransactionGroup:
    return CardTransactionGroup(
        card=_card_response(group.card),
        transactions=[_transaction_response(row) for row in group.transactions],
        match_count=group.match_count,
        next_cursor=group.next_cursor,
        has_more=group.has_more,
    )


def _card_response(card: CardRow) -> CardResponse:
    return CardResponse(
        id=card.id,
        connection_id=card.connection_id,
        bank=card.bank,  # type: ignore[arg-type]
        bank_display_name=card.bank_display_name,
        name=card.name,
        official_name=card.official_name,
        mask=card.mask,
        state="needs_attention" if card.last_error_code else "ready",
        last_successful_sync_at=card.last_successful_sync_at,
    )


def _transaction_response(row: TransactionRow) -> TransactionMatch:
    return TransactionMatch(
        id=row.id,
        card_id=row.card_id,
        merchant_name=row.merchant_name,
        description=row.description,
        original_description=row.original_description,
        category=row.category,
        amount_cents=row.amount_cents,
        currency_code=row.currency_code,
        authorized_date=row.authorized_date,
        posted_date=row.posted_date,
        pending=row.pending,
    )


def _serialize_all_row(row: AllTransactionServiceRow) -> AllTransactionRow:
    return AllTransactionRow(
        transaction=_transaction_response(row.transaction),
        card=_card_response(row.card),
    )


@router.get("/transactions", response_model=AllTransactionsResponse)
async def all_transactions(
    owner: OwnerDep,
    q: str = Query(default="", max_length=200),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=MAX_PER_CARD_LIMIT, ge=1, le=MAX_PER_CARD_LIMIT),
    service: SearchService = ServiceDep,
) -> AllTransactionsResponse:
    result = await service.all_transactions(
        owner.id, query=q, limit=limit, cursor=cursor
    )
    return AllTransactionsResponse(
        query=result.query,
        total_matches=result.total_matches,
        card_count=result.card_count,
        bank_count=result.bank_count,
        rows=[_serialize_all_row(row) for row in result.rows],
        next_cursor=result.next_cursor,
        has_more=result.has_more,
        cache_as_of=result.cache_as_of,
    )


@router.get("/transactions/search", response_model=GroupedSearchResponse)
async def search_transactions(
    request: Request,
    owner: OwnerDep,
    q: str = Query(default="", max_length=200),
    per_card_limit: int = Query(
        default=DEFAULT_PER_CARD_LIMIT, ge=1, le=MAX_PER_CARD_LIMIT
    ),
    service: SearchService = ServiceDep,
) -> GroupedSearchResponse:
    cursors = {
        key[len(CURSOR_PREFIX) :]: value
        for key, value in request.query_params.items()
        if key.startswith(CURSOR_PREFIX) and value
    }
    result = await service.search(
        owner.id, query=q, per_card_limit=per_card_limit, cursors=cursors
    )
    return GroupedSearchResponse(
        query=result.query,
        total_matches=result.total_matches,
        card_count=len(result.groups),
        groups=[_serialize(group) for group in result.groups],
        cache_as_of=result.cache_as_of,
    )


@router.get("/cards/{card_id}/transactions", response_model=CardTransactionGroup)
async def card_transactions(
    card_id: str,
    owner: OwnerDep,
    q: str = Query(default="", max_length=200),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PER_CARD_LIMIT, ge=1, le=MAX_PER_CARD_LIMIT),
    service: SearchService = ServiceDep,
) -> CardTransactionGroup:
    group = await service.card_transactions(
        owner.id, card_id, query=q, limit=limit, cursor=cursor
    )
    return _serialize(group)


__all__ = ["router"]
