"""Owner-scoped API for durable transaction refresh runs."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import select

from app.dependencies import CsrfDep, OwnerDep, SessionDep
from app.errors import OriginInvalidError
from app.models import BankConnection, TransactionRefresh, TransactionRefreshTarget
from app.schemas import (
    CreateTransactionRefreshResponse,
    TransactionRefreshResponse,
    TransactionRefreshSummaryResponse,
    TransactionRefreshTargetResponse,
)
from app.services.transaction_refresh_service import (
    ACTIVE_TARGET_STATES,
    TransactionRefreshService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transaction-refreshes", tags=["transaction-refreshes"])

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[\x21-\x7e]+$",
    ),
]

ATTENTION_STATES = {
    "reconnect_required",
    "outcome_unknown",
    "failed",
    "disconnected",
}


async def serialize_refresh(
    session: SessionDep, run: TransactionRefresh
) -> TransactionRefreshResponse:
    rows = (
        await session.execute(
            select(TransactionRefreshTarget, BankConnection)
            .join(
                BankConnection,
                BankConnection.id == TransactionRefreshTarget.connection_id,
            )
            .where(TransactionRefreshTarget.refresh_id == run.id)
            .order_by(TransactionRefreshTarget.created_at, TransactionRefreshTarget.id)
        )
    ).all()
    targets = [
        TransactionRefreshTargetResponse(
            connection_id=target.connection_id,
            bank=connection.bank_slug,  # type: ignore[arg-type]
            state=target.state,  # type: ignore[arg-type]
            refresh_outcome=target.refresh_outcome,  # type: ignore[arg-type]
            next_refresh_eligible_at=target.next_refresh_eligible_at,
            added=target.added_count,
            modified=target.modified_count,
            removed=target.removed_count,
            error_code=target.error_code,
        )
        for target, connection in rows
    ]
    completed = sum(target.state not in ACTIVE_TARGET_STATES for target, _ in rows)
    return TransactionRefreshResponse(
        id=run.id,
        state=run.state,  # type: ignore[arg-type]
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        expires_at=run.expires_at,
        summary=TransactionRefreshSummaryResponse(
            total=len(rows),
            completed=completed,
            updated=sum(target.state == "updated" for target, _ in rows),
            attention=sum(target.state in ATTENTION_STATES for target, _ in rows),
            added=sum(target.added_count for target, _ in rows),
            modified=sum(target.modified_count for target, _ in rows),
            removed=sum(target.removed_count for target, _ in rows),
        ),
        targets=targets,
    )


@router.post(
    "",
    response_model=CreateTransactionRefreshResponse,
    status_code=202,
    responses={
        200: {
            "model": CreateTransactionRefreshResponse,
            "description": "Terminal idempotency-key replay",
        }
    },
    dependencies=[CsrfDep],
)
async def create_transaction_refresh(
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
    owner: OwnerDep,
    session: SessionDep,
) -> CreateTransactionRefreshResponse:
    started = perf_counter()
    if request.headers.get("origin") is None:
        raise OriginInvalidError()
    run, coalesced = await TransactionRefreshService(session).create_or_coalesce(
        owner.id, idempotency_key
    )
    if run.state not in {"queued", "running"}:
        response.status_code = 200
    serialized = await serialize_refresh(session, run)
    logger.info(
        "transaction_refresh_acknowledged",
        extra={
            "owner_id": owner.id,
            "refresh_id": run.id,
            "coalesced": coalesced,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
        },
    )
    return CreateTransactionRefreshResponse(
        coalesced=coalesced, refresh=serialized
    )


@router.get(
    "/active",
    response_model=TransactionRefreshResponse,
    responses={204: {"description": "No active transaction refresh"}},
)
async def active_transaction_refresh(
    owner: OwnerDep, session: SessionDep
) -> TransactionRefreshResponse | Response:
    run = await TransactionRefreshService(session).active_for_owner(owner.id)
    if run is None:
        return Response(status_code=204)
    return await serialize_refresh(session, run)


@router.get("/{refresh_id}", response_model=TransactionRefreshResponse)
async def get_transaction_refresh(
    refresh_id: str, owner: OwnerDep, session: SessionDep
) -> TransactionRefreshResponse:
    run = await TransactionRefreshService(session).get_owned(owner.id, refresh_id)
    return await serialize_refresh(session, run)


__all__ = ["router", "serialize_refresh"]
