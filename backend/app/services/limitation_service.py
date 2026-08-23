"""Owner-scoped transaction limitation rules and derived local alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError
from app.models import (
    BankConnection,
    CardAccount,
    Transaction,
    TransactionLimitation,
    TransactionLimitationCard,
    utcnow,
)
from app.schemas import (
    CreateTransactionLimitationRequest,
    UpdateTransactionLimitationRequest,
)
from app.services.plaid_gateway import SUPPORTED_BANKS
from app.services.search_service import (
    CardRow,
    normalize_query,
    transaction_match_filter,
)

BANK_ORDER = {slug: index for index, slug in enumerate(SUPPORTED_BANKS)}


@dataclass(frozen=True)
class RuleResult:
    rule: TransactionLimitation
    card_ids: list[str]


@dataclass(frozen=True)
class RuleListResult:
    rules: list[RuleResult]
    cards: list[CardRow]


@dataclass(frozen=True)
class EvaluatedWindow:
    type: str
    days: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    effective_start_date: date | None = None
    effective_end_date: date | None = None


@dataclass(frozen=True)
class ActiveTransactionLimitAlert:
    rule_id: str
    keyword: str
    threshold: int
    card: CardRow
    match_count: int
    pending_count: int
    window: EvaluatedWindow


@dataclass(frozen=True)
class AlertResult:
    alerts: list[ActiveTransactionLimitAlert]
    evaluated_at: datetime
    as_of_date: date
    cache_as_of: datetime | None


class LimitationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_rules(self, owner_id: str) -> RuleListResult:
        rules = (
            await self._session.execute(
                select(TransactionLimitation)
                .options(selectinload(TransactionLimitation.card_links))
                .where(TransactionLimitation.owner_id == owner_id)
                .order_by(
                    TransactionLimitation.created_at,
                    TransactionLimitation.id,
                )
            )
        ).scalars().all()
        cards = await self._list_cards(owner_id)
        return RuleListResult(
            rules=[self._rule_result(rule) for rule in rules],
            cards=cards,
        )

    async def create_rule(
        self,
        owner_id: str,
        payload: CreateTransactionLimitationRequest,
    ) -> RuleResult:
        keyword, normalized_keyword = _normalize_keyword(payload.keyword)
        card_ids = _deduplicate(payload.card_ids)
        await self._validate_cards(owner_id, payload.card_scope, card_ids)

        rule = TransactionLimitation(
            owner_id=owner_id,
            keyword=keyword,
            normalized_keyword=normalized_keyword,
            threshold=payload.threshold,
            card_scope=payload.card_scope,
            window_type=payload.window.type,
            rolling_days=(
                payload.window.days if payload.window.type == "rolling" else None
            ),
            start_date=(
                payload.window.start_date if payload.window.type == "fixed" else None
            ),
            end_date=(
                payload.window.end_date if payload.window.type == "fixed" else None
            ),
            is_enabled=payload.is_enabled,
        )
        rule.card_links = [
            TransactionLimitationCard(card_account_id=card_id)
            for card_id in card_ids
        ]
        self._session.add(rule)
        await self._session.flush()
        return self._rule_result(rule)

    async def update_rule(
        self,
        owner_id: str,
        rule_id: str,
        payload: UpdateTransactionLimitationRequest,
    ) -> RuleResult:
        rule = await self._get_rule(owner_id, rule_id)
        card_ids = (
            _deduplicate(payload.card_ids)
            if payload.card_ids is not None
            else [link.card_account_id for link in rule.card_links]
        )
        card_scope = payload.card_scope or rule.card_scope
        await self._validate_cards(owner_id, card_scope, card_ids)

        if payload.keyword is not None:
            rule.keyword, rule.normalized_keyword = _normalize_keyword(payload.keyword)
        if payload.threshold is not None:
            rule.threshold = payload.threshold
        if payload.card_scope is not None:
            rule.card_scope = payload.card_scope
        if payload.window is not None:
            rule.window_type = payload.window.type
            rule.rolling_days = (
                payload.window.days if payload.window.type == "rolling" else None
            )
            rule.start_date = (
                payload.window.start_date if payload.window.type == "fixed" else None
            )
            rule.end_date = (
                payload.window.end_date if payload.window.type == "fixed" else None
            )
        if payload.is_enabled is not None:
            rule.is_enabled = payload.is_enabled
        if payload.card_ids is not None:
            rule.card_links = [
                TransactionLimitationCard(card_account_id=card_id)
                for card_id in card_ids
            ]
        await self._session.flush()
        return self._rule_result(rule)

    async def delete_rule(self, owner_id: str, rule_id: str) -> None:
        rule = await self._get_rule(owner_id, rule_id)
        await self._session.delete(rule)
        await self._session.flush()

    async def evaluate_active_alerts(
        self,
        owner_id: str,
        *,
        as_of_date: date | None = None,
    ) -> AlertResult:
        today = as_of_date or date.today()
        cards = await self._list_cards(owner_id)
        cards_by_id = {card.id: card for card in cards}
        active_card_ids = set(cards_by_id)
        rules = (
            await self._session.execute(
                select(TransactionLimitation)
                .options(selectinload(TransactionLimitation.card_links))
                .where(TransactionLimitation.owner_id == owner_id)
                .where(TransactionLimitation.is_enabled.is_(True))
                .order_by(
                    TransactionLimitation.created_at,
                    TransactionLimitation.id,
                )
            )
        ).scalars().all()

        alerts: list[ActiveTransactionLimitAlert] = []
        evaluation_cache: dict[
            tuple[str, tuple[str, ...], str, int | None, date | None, date | None],
            list[tuple[str, int, int]],
        ] = {}
        for rule in rules:
            target_ids = (
                active_card_ids
                if rule.card_scope == "all_cards"
                else {
                    link.card_account_id
                    for link in rule.card_links
                    if link.card_account_id in active_card_ids
                }
            )
            if not target_ids:
                continue
            normalized = normalize_query(rule.keyword)
            pending_count = func.sum(
                case((Transaction.pending.is_(True), 1), else_=0)
            )
            date_filter = None
            evaluated_window = EvaluatedWindow(type="all_time")
            if rule.window_type == "rolling":
                assert rule.rolling_days is not None
                start_date = today - timedelta(days=rule.rolling_days - 1)
                effective_date = func.coalesce(
                    Transaction.posted_date,
                    Transaction.authorized_date,
                )
                date_filter = effective_date.between(start_date, today)
                evaluated_window = EvaluatedWindow(
                    type="rolling",
                    days=rule.rolling_days,
                    effective_start_date=start_date,
                    effective_end_date=today,
                )
            elif rule.window_type == "fixed":
                assert rule.start_date is not None
                assert rule.end_date is not None
                effective_date = func.coalesce(
                    Transaction.posted_date,
                    Transaction.authorized_date,
                )
                date_filter = effective_date.between(rule.start_date, rule.end_date)
                evaluated_window = EvaluatedWindow(
                    type="fixed",
                    start_date=rule.start_date,
                    end_date=rule.end_date,
                    effective_start_date=rule.start_date,
                    effective_end_date=rule.end_date,
                )
            cache_key = (
                normalized.normalized,
                tuple(sorted(target_ids)),
                rule.window_type,
                rule.rolling_days,
                rule.start_date,
                rule.end_date,
            )
            rows = evaluation_cache.get(cache_key)
            if rows is None:
                statement = (
                    select(
                        Transaction.card_account_id,
                        func.count(Transaction.id),
                        pending_count,
                    )
                    .where(Transaction.card_account_id.in_(target_ids))
                    .where(transaction_match_filter(normalized))
                )
                if date_filter is not None:
                    statement = statement.where(date_filter)
                raw_rows = (
                    await self._session.execute(
                        statement.group_by(Transaction.card_account_id)
                    )
                ).all()
                rows = [
                    (card_id, int(match_count), int(pending or 0))
                    for card_id, match_count, pending in raw_rows
                ]
                evaluation_cache[cache_key] = rows
            for card_id, match_count, pending in rows:
                if match_count < rule.threshold:
                    continue
                alerts.append(
                    ActiveTransactionLimitAlert(
                        rule_id=rule.id,
                        keyword=rule.keyword,
                        threshold=rule.threshold,
                        card=cards_by_id[card_id],
                        match_count=match_count,
                        pending_count=pending,
                        window=evaluated_window,
                    )
                )

        card_position = {card.id: index for index, card in enumerate(cards)}
        alerts.sort(key=lambda alert: (card_position[alert.card.id], alert.rule_id))
        successful_syncs = [
            card.last_successful_sync_at
            for card in cards
            if card.last_successful_sync_at is not None
        ]
        return AlertResult(
            alerts=alerts,
            evaluated_at=utcnow(),
            as_of_date=today,
            cache_as_of=min(successful_syncs) if successful_syncs else None,
        )

    async def _get_rule(
        self, owner_id: str, rule_id: str
    ) -> TransactionLimitation:
        rule = (
            await self._session.execute(
                select(TransactionLimitation)
                .options(selectinload(TransactionLimitation.card_links))
                .where(TransactionLimitation.id == rule_id)
                .where(TransactionLimitation.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if rule is None:
            raise AppError(
                "TRANSACTION_LIMITATION_NOT_FOUND",
                "That transaction limitation was not found.",
                404,
            )
        return rule

    async def _validate_cards(
        self,
        owner_id: str,
        card_scope: str,
        card_ids: list[str],
    ) -> None:
        if card_scope == "all_cards":
            if card_ids:
                raise AppError(
                    "REQUEST_INVALID", "All-card rules cannot select cards.", 422
                )
            return
        if not card_ids:
            raise AppError(
                "REQUEST_INVALID", "Select at least one active card.", 422
            )
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
    def _rule_result(rule: TransactionLimitation) -> RuleResult:
        return RuleResult(
            rule=rule,
            card_ids=sorted(link.card_account_id for link in rule.card_links),
        )


def _normalize_keyword(keyword: str) -> tuple[str, str]:
    normalized = normalize_query(keyword)
    if normalized.is_blank:
        raise AppError("REQUEST_INVALID", "Enter a keyword or phrase.", 422)
    return keyword.strip(), normalized.normalized


def _deduplicate(card_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(card_ids))


__all__ = [
    "ActiveTransactionLimitAlert",
    "AlertResult",
    "EvaluatedWindow",
    "LimitationService",
    "RuleListResult",
    "RuleResult",
]
