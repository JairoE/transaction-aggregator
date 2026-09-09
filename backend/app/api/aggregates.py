"""Owner-only saved transaction aggregate CRUD and evaluated summaries."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import CsrfDep, OwnerDep, SessionDep
from app.schemas import (
    CardResponse,
    CreateTransactionAggregateRequest,
    SavedTransactionAggregateListResponse,
    SavedTransactionAggregateResponse,
    TransactionAggregateListResponse,
    TransactionAggregateResponse,
    TransactionAggregateSummaryResponse,
    UpdateTransactionAggregateRequest,
)
from app.services.aggregate_service import (
    AggregateRuleResult,
    SavedAggregateEvaluation,
    TransactionAggregateService,
)
from app.services.search_service import CardRow

router = APIRouter(prefix="/api", tags=["transaction-aggregates"])


async def aggregate_service_dep(session: SessionDep) -> TransactionAggregateService:
    return TransactionAggregateService(session)


ServiceDep = Depends(aggregate_service_dep)


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


def _aggregate_response(result: AggregateRuleResult) -> TransactionAggregateResponse:
    aggregate = result.aggregate
    return TransactionAggregateResponse(
        id=aggregate.id,
        keyword=aggregate.keyword,
        card_scope=aggregate.card_scope,  # type: ignore[arg-type]
        card_ids=result.card_ids,
        created_at=aggregate.created_at,
        updated_at=aggregate.updated_at,
    )


def _saved_response(
    result: SavedAggregateEvaluation,
) -> SavedTransactionAggregateResponse:
    return SavedTransactionAggregateResponse(
        aggregate_id=result.aggregate_id,
        keyword=result.keyword,
        card=_card_response(result.card),
        summary=TransactionAggregateSummaryResponse(
            usd_match_count=result.summary.usd_match_count,
            usd_pending_count=result.summary.usd_pending_count,
            purchases_cents=result.summary.purchases_cents,
            refunds_cents=result.summary.refunds_cents,
            net_total_cents=result.summary.net_total_cents,
        ),
    )


@router.get("/transaction-aggregates", response_model=TransactionAggregateListResponse)
async def list_transaction_aggregates(
    owner: OwnerDep,
    service: TransactionAggregateService = ServiceDep,
) -> TransactionAggregateListResponse:
    result = await service.list_aggregates(owner.id)
    return TransactionAggregateListResponse(
        aggregates=[_aggregate_response(item) for item in result.aggregates],
        cards=[_card_response(card) for card in result.cards],
    )


@router.post(
    "/transaction-aggregates",
    response_model=TransactionAggregateResponse,
    status_code=201,
    dependencies=[CsrfDep],
)
async def create_transaction_aggregate(
    payload: CreateTransactionAggregateRequest,
    owner: OwnerDep,
    service: TransactionAggregateService = ServiceDep,
) -> TransactionAggregateResponse:
    return _aggregate_response(await service.create_aggregate(owner.id, payload))


@router.patch(
    "/transaction-aggregates/{aggregate_id}",
    response_model=TransactionAggregateResponse,
    dependencies=[CsrfDep],
)
async def update_transaction_aggregate(
    aggregate_id: str,
    payload: UpdateTransactionAggregateRequest,
    owner: OwnerDep,
    service: TransactionAggregateService = ServiceDep,
) -> TransactionAggregateResponse:
    return _aggregate_response(
        await service.update_aggregate(owner.id, aggregate_id, payload)
    )


@router.delete(
    "/transaction-aggregates/{aggregate_id}",
    status_code=204,
    dependencies=[CsrfDep],
)
async def delete_transaction_aggregate(
    aggregate_id: str,
    owner: OwnerDep,
    service: TransactionAggregateService = ServiceDep,
) -> None:
    await service.delete_aggregate(owner.id, aggregate_id)


@router.get(
    "/saved-transaction-aggregates",
    response_model=SavedTransactionAggregateListResponse,
)
async def list_saved_transaction_aggregates(
    owner: OwnerDep,
    service: TransactionAggregateService = ServiceDep,
) -> SavedTransactionAggregateListResponse:
    result = await service.evaluate_saved_aggregates(owner.id)
    return SavedTransactionAggregateListResponse(
        aggregates=[_saved_response(item) for item in result.aggregates],
        evaluated_at=result.evaluated_at,
        cache_as_of=result.cache_as_of,
    )


__all__ = ["router"]
