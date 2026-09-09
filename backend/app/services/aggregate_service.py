"""Owner-scoped saved aggregate definitions and all-history evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError
from app.models import (
    BankConnection,
    CardAccount,
    Transaction,
    TransactionAggregate,
    TransactionAggregateCard,
    utcnow,
)
from app.schemas import (
    CreateTransactionAggregateRequest,
    UpdateTransactionAggregateRequest,
)
from app.services.plaid_gateway import SUPPORTED_BANKS
from app.services.search_service import CardRow, normalize_query, transaction_match_filter
from app.services.transaction_summary import (
    TransactionSummary,
    transaction_summary_columns,
    transaction_summary_from_row,
)

BANK_ORDER = {slug: index for index, slug in enumerate(SUPPORTED_BANKS)}
EMPTY_SUMMARY = TransactionSummary(0, 0, 0, 0, 0)


@dataclass(frozen=True)
class AggregateRuleResult:
    aggregate: TransactionAggregate
    card_ids: list[str]


@dataclass(frozen=True)
class AggregateListResult:
    aggregates: list[AggregateRuleResult]
    cards: list[CardRow]


@dataclass(frozen=True)
class SavedAggregateEvaluation:
    aggregate_id: str
    keyword: str
    card: CardRow
    summary: TransactionSummary


@dataclass(frozen=True)
class SavedAggregateResult:
    aggregates: list[SavedAggregateEvaluation]
    evaluated_at: datetime
    cache_as_of: datetime | None


class TransactionAggregateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_aggregates(self, owner_id: str) -> AggregateListResult:
        aggregates = await self._list_definitions(owner_id)
        return AggregateListResult(
            aggregates=[self._aggregate_result(item) for item in aggregates],
            cards=await self._list_cards(owner_id),
        )

    async def create_aggregate(
        self,
        owner_id: str,
        payload: CreateTransactionAggregateRequest,
    ) -> AggregateRuleResult:
        keyword, normalized_keyword = _normalize_keyword(payload.keyword)
        card_ids = _deduplicate(payload.card_ids)
        await self._validate_cards(owner_id, payload.card_scope, card_ids)

        aggregate = TransactionAggregate(
            owner_id=owner_id,
            keyword=keyword,
            normalized_keyword=normalized_keyword,
            card_scope=payload.card_scope,
            card_links=[
                TransactionAggregateCard(card_account_id=card_id)
                for card_id in card_ids
            ],
        )
        self._session.add(aggregate)
        await self._session.flush()
        return self._aggregate_result(aggregate)

    async def update_aggregate(
        self,
        owner_id: str,
        aggregate_id: str,
        payload: UpdateTransactionAggregateRequest,
    ) -> AggregateRuleResult:
        aggregate = await self._get_aggregate(owner_id, aggregate_id)
        card_scope = payload.card_scope or aggregate.card_scope
        current_card_ids = [link.card_account_id for link in aggregate.card_links]
        if payload.card_ids is not None:
            card_ids = _deduplicate(payload.card_ids)
        elif payload.card_scope == "all_cards":
            card_ids = []
        else:
            card_ids = current_card_ids
        if payload.card_scope is not None or payload.card_ids is not None:
            await self._validate_cards(owner_id, card_scope, card_ids)

        if payload.keyword is not None:
            aggregate.keyword, aggregate.normalized_keyword = _normalize_keyword(
                payload.keyword
            )
        if payload.card_scope is not None:
            aggregate.card_scope = payload.card_scope
        if payload.card_scope is not None or payload.card_ids is not None:
            aggregate.card_links = [
                TransactionAggregateCard(card_account_id=card_id)
                for card_id in card_ids
            ]
        await self._session.flush()
        return self._aggregate_result(aggregate)

    async def delete_aggregate(self, owner_id: str, aggregate_id: str) -> None:
        aggregate = await self._get_aggregate(owner_id, aggregate_id)
        await self._session.delete(aggregate)
        await self._session.flush()

    async def evaluate_saved_aggregates(
        self, owner_id: str
    ) -> SavedAggregateResult:
        cards = await self._list_cards(owner_id)
        cards_by_id = {card.id: card for card in cards}
        active_card_ids = set(cards_by_id)
        definitions = await self._list_definitions(owner_id)

        evaluations: list[SavedAggregateEvaluation] = []
        definition_position = {
            aggregate.id: position for position, aggregate in enumerate(definitions)
        }
        for aggregate in definitions:
            target_ids = (
                active_card_ids
                if aggregate.card_scope == "all_cards"
                else {
                    link.card_account_id
                    for link in aggregate.card_links
                    if link.card_account_id in active_card_ids
                }
            )
            if not target_ids:
                continue

            normalized = normalize_query(aggregate.normalized_keyword)
            rows = (
                await self._session.execute(
                    select(
                        Transaction.card_account_id,
                        *transaction_summary_columns(),
                    )
                    .where(Transaction.card_account_id.in_(target_ids))
                    .where(transaction_match_filter(normalized))
                    .group_by(Transaction.card_account_id)
                )
            ).all()
            summaries = {
                row.card_account_id: transaction_summary_from_row(row) for row in rows
            }
            evaluations.extend(
                SavedAggregateEvaluation(
                    aggregate_id=aggregate.id,
                    keyword=aggregate.keyword,
                    card=cards_by_id[card_id],
                    summary=summaries.get(card_id, EMPTY_SUMMARY),
                )
                for card_id in target_ids
            )

        card_position = {card.id: position for position, card in enumerate(cards)}
        evaluations.sort(
            key=lambda item: (
                card_position[item.card.id],
                definition_position[item.aggregate_id],
            )
        )
        evaluated_card_ids = {item.card.id for item in evaluations}
        successful_syncs = [
            card.last_successful_sync_at
            for card in cards
            if card.id in evaluated_card_ids
            if card.last_successful_sync_at is not None
        ]
        return SavedAggregateResult(
            aggregates=evaluations,
            evaluated_at=utcnow(),
            cache_as_of=min(successful_syncs) if successful_syncs else None,
        )

    async def _list_definitions(
        self, owner_id: str
    ) -> list[TransactionAggregate]:
        return list(
            (
                await self._session.execute(
                    select(TransactionAggregate)
                    .options(selectinload(TransactionAggregate.card_links))
                    .where(TransactionAggregate.owner_id == owner_id)
                    .order_by(
                        TransactionAggregate.created_at,
                        TransactionAggregate.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _get_aggregate(
        self, owner_id: str, aggregate_id: str
    ) -> TransactionAggregate:
        aggregate = (
            await self._session.execute(
                select(TransactionAggregate)
                .options(selectinload(TransactionAggregate.card_links))
                .where(TransactionAggregate.id == aggregate_id)
                .where(TransactionAggregate.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if aggregate is None:
            raise AppError(
                "TRANSACTION_AGGREGATE_NOT_FOUND",
                "That saved aggregate was not found.",
                404,
            )
        return aggregate

    async def _validate_cards(
        self,
        owner_id: str,
        card_scope: str,
        card_ids: list[str],
    ) -> None:
        if card_scope == "all_cards":
            if card_ids:
                raise AppError(
                    "REQUEST_INVALID",
                    "All-card aggregates cannot select cards.",
                    422,
                )
            return
        if not card_ids:
            raise AppError("REQUEST_INVALID", "Select at least one active card.", 422)
        available_ids = {card.id for card in await self._list_cards(owner_id)}
        if not set(card_ids) <= available_ids:
            raise AppError(
                "REQUEST_INVALID",
                "One or more selected cards are unavailable.",
                422,
            )

    async def _list_cards(self, owner_id: str) -> list[CardRow]:
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

    @staticmethod
    def _aggregate_result(aggregate: TransactionAggregate) -> AggregateRuleResult:
        return AggregateRuleResult(
            aggregate=aggregate,
            card_ids=sorted(link.card_account_id for link in aggregate.card_links),
        )


def _normalize_keyword(keyword: str) -> tuple[str, str]:
    normalized = normalize_query(keyword)
    if normalized.is_blank:
        raise AppError("REQUEST_INVALID", "Enter a keyword or phrase.", 422)
    return keyword.strip(), normalized.normalized


def _deduplicate(card_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(card_ids))


__all__ = [
    "AggregateListResult",
    "AggregateRuleResult",
    "SavedAggregateEvaluation",
    "SavedAggregateResult",
    "TransactionAggregateService",
]
