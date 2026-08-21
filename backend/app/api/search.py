"""Grouped cached search and per-card continuation.

Neither route calls Plaid; both read only the local SQLite cache.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import OwnerDep, SessionDep, SettingsDep
from app.schemas import (
    CardResponse,
    CardTransactionGroup,
    GroupedSearchResponse,
    TransactionMatch,
)
from app.services.search_service import (
    DEFAULT_PER_CARD_LIMIT,
    MAX_PER_CARD_LIMIT,
    CardGroup,
    SearchService,
)

router = APIRouter(prefix="/api", tags=["search"])

CURSOR_PREFIX = "cursor."


async def search_service_dep(session: SessionDep, settings: SettingsDep) -> SearchService:
    return SearchService(session, settings.application_secret.get_secret_value())


ServiceDep = Depends(search_service_dep)


def _serialize(group: CardGroup) -> CardTransactionGroup:
    return CardTransactionGroup(
        card=CardResponse(
            id=group.card.id,
            connection_id=group.card.connection_id,
            bank=group.card.bank,  # type: ignore[arg-type]
            bank_display_name=group.card.bank_display_name,
            name=group.card.name,
            official_name=group.card.official_name,
            mask=group.card.mask,
            state="needs_attention" if group.card.last_error_code else "ready",
            last_successful_sync_at=group.card.last_successful_sync_at,
        ),
        transactions=[
            TransactionMatch(
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
            for row in group.transactions
        ],
        match_count=group.match_count,
        next_cursor=group.next_cursor,
        has_more=group.has_more,
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
