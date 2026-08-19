"""Verified Plaid webhooks.

The handler verifies, deduplicates, enqueues, and returns quickly. It never
runs `/transactions/sync` inline, so a slow institution cannot make Plaid time
out and retry into a pile-up.
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import SessionDep
from app.models import BankConnection, WebhookReceipt
from app.services.sync_service import enqueue_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

ENQUEUE_CODES = frozenset(
    {
        "SYNC_UPDATES_AVAILABLE",
        "DEFAULT_UPDATE",
        "INITIAL_UPDATE",
        "HISTORICAL_UPDATE",
        "TRANSACTIONS_REMOVED",
    }
)
ATTENTION_CODES = frozenset(
    {"PENDING_DISCONNECT", "PENDING_EXPIRATION", "ERROR", "USER_PERMISSION_REVOKED"}
)


@router.post("/plaid", status_code=204)
async def receive_plaid_webhook(
    request: Request, session: SessionDep
) -> Response:
    body = await request.body()
    gateway = request.app.state.plaid_gateway

    if not gateway.verify_webhook(body, request.headers.get("plaid-verification")):
        logger.warning("plaid_webhook_rejected")
        return Response(
            status_code=401,
            content=json.dumps(
                {"code": "WEBHOOK_INVALID", "message": "Signature verification failed."}
            ),
            media_type="application/json",
        )

    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = {}

    digest = hashlib.sha256(body).hexdigest()
    webhook_type = payload.get("webhook_type")
    webhook_code = payload.get("webhook_code")
    item_id = payload.get("item_id")

    receipt = WebhookReceipt(
        payload_sha256=digest,
        webhook_type=webhook_type,
        webhook_code=webhook_code,
        plaid_item_id=item_id,
    )
    session.add(receipt)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # A replayed webhook must not create a second job.
        return Response(status_code=204)

    if not item_id:
        return Response(status_code=204)

    connection = (
        await session.execute(
            select(BankConnection)
            .where(BankConnection.plaid_item_id == item_id)
            .where(BankConnection.lifecycle_status == "active")
        )
    ).scalars().first()
    if connection is None:
        return Response(status_code=204)

    if webhook_code in ATTENTION_CODES:
        error = payload.get("error") or {}
        connection.last_error_code = (
            error.get("error_code") if isinstance(error, dict) else None
        ) or webhook_code

    if webhook_code in ENQUEUE_CODES or webhook_code in ATTENTION_CODES:
        await enqueue_sync(session, connection.id, "webhook")

    logger.info(
        "plaid_webhook_received",
        extra={"webhook_type": webhook_type, "webhook_code": webhook_code},
    )
    return Response(status_code=204)


__all__ = ["router"]
