"""Owner-only transaction limitation CRUD and derived alerts."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import CsrfDep, OwnerDep, SessionDep
from app.schemas import (
    AllTimeWindow,
    CardResponse,
    CreateTransactionLimitationRequest,
    EvaluatedAllTimeWindow,
    EvaluatedFixedWindow,
    EvaluatedRollingWindow,
    FixedWindow,
    RollingWindow,
    TransactionLimitationListResponse,
    TransactionLimitationResponse,
    TransactionLimitAlertListResponse,
    TransactionLimitAlertResponse,
    UpdateTransactionLimitationRequest,
)
from app.services.limitation_service import (
    ActiveTransactionLimitAlert,
    LimitationService,
    RuleResult,
)
from app.services.search_service import CardRow

router = APIRouter(prefix="/api", tags=["transaction-limitations"])


async def limitation_service_dep(session: SessionDep) -> LimitationService:
    return LimitationService(session)


ServiceDep = Depends(limitation_service_dep)


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


def _rule_response(result: RuleResult) -> TransactionLimitationResponse:
    rule = result.rule
    if rule.window_type == "rolling" and rule.rolling_days is not None:
        window = RollingWindow(type="rolling", days=rule.rolling_days)
    elif (
        rule.window_type == "fixed"
        and rule.start_date is not None
        and rule.end_date is not None
    ):
        window = FixedWindow(
            type="fixed",
            start_date=rule.start_date,
            end_date=rule.end_date,
        )
    else:
        window = AllTimeWindow(type="all_time")
    return TransactionLimitationResponse(
        id=rule.id,
        keyword=rule.keyword,
        threshold=rule.threshold,
        card_scope=rule.card_scope,  # type: ignore[arg-type]
        card_ids=result.card_ids,
        window=window,
        is_enabled=rule.is_enabled,
        needs_card_selection=rule.card_scope == "selected_cards" and not result.card_ids,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _alert_response(
    alert: ActiveTransactionLimitAlert,
) -> TransactionLimitAlertResponse:
    if (
        alert.window.type == "rolling"
        and alert.window.days is not None
        and alert.window.effective_start_date is not None
        and alert.window.effective_end_date is not None
    ):
        window = EvaluatedRollingWindow(
            type="rolling",
            days=alert.window.days,
            effective_start_date=alert.window.effective_start_date,
            effective_end_date=alert.window.effective_end_date,
        )
    elif (
        alert.window.type == "fixed"
        and alert.window.start_date is not None
        and alert.window.end_date is not None
        and alert.window.effective_start_date is not None
        and alert.window.effective_end_date is not None
    ):
        window = EvaluatedFixedWindow(
            type="fixed",
            start_date=alert.window.start_date,
            end_date=alert.window.end_date,
            effective_start_date=alert.window.effective_start_date,
            effective_end_date=alert.window.effective_end_date,
        )
    else:
        window = EvaluatedAllTimeWindow(type="all_time")
    return TransactionLimitAlertResponse(
        rule_id=alert.rule_id,
        keyword=alert.keyword,
        threshold=alert.threshold,
        card=_card_response(alert.card),
        match_count=alert.match_count,
        pending_count=alert.pending_count,
        window=window,
    )


@router.get(
    "/transaction-limitations", response_model=TransactionLimitationListResponse
)
async def list_transaction_limitations(
    owner: OwnerDep,
    service: LimitationService = ServiceDep,
) -> TransactionLimitationListResponse:
    result = await service.list_rules(owner.id)
    return TransactionLimitationListResponse(
        rules=[_rule_response(rule) for rule in result.rules],
        cards=[_card_response(card) for card in result.cards],
    )


@router.post(
    "/transaction-limitations",
    response_model=TransactionLimitationResponse,
    status_code=201,
    dependencies=[CsrfDep],
)
async def create_transaction_limitation(
    payload: CreateTransactionLimitationRequest,
    owner: OwnerDep,
    service: LimitationService = ServiceDep,
) -> TransactionLimitationResponse:
    return _rule_response(await service.create_rule(owner.id, payload))


@router.patch(
    "/transaction-limitations/{rule_id}",
    response_model=TransactionLimitationResponse,
    dependencies=[CsrfDep],
)
async def update_transaction_limitation(
    rule_id: str,
    payload: UpdateTransactionLimitationRequest,
    owner: OwnerDep,
    service: LimitationService = ServiceDep,
) -> TransactionLimitationResponse:
    return _rule_response(await service.update_rule(owner.id, rule_id, payload))


@router.delete(
    "/transaction-limitations/{rule_id}",
    status_code=204,
    dependencies=[CsrfDep],
)
async def delete_transaction_limitation(
    rule_id: str,
    owner: OwnerDep,
    service: LimitationService = ServiceDep,
) -> None:
    await service.delete_rule(owner.id, rule_id)


@router.get(
    "/transaction-limit-alerts", response_model=TransactionLimitAlertListResponse
)
async def list_transaction_limit_alerts(
    owner: OwnerDep,
    service: LimitationService = ServiceDep,
) -> TransactionLimitAlertListResponse:
    result = await service.evaluate_active_alerts(owner.id)
    return TransactionLimitAlertListResponse(
        alerts=[_alert_response(alert) for alert in result.alerts],
        evaluated_at=result.evaluated_at,
        as_of_date=result.as_of_date,
        cache_as_of=result.cache_as_of,
    )


__all__ = ["router"]
