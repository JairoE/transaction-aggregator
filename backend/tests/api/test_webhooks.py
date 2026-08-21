from __future__ import annotations

import json

from httpx import AsyncClient
from sqlalchemy import select

from app.models import SyncJob, WebhookReceipt


def _payload(item_id: str, code: str = "SYNC_UPDATES_AVAILABLE") -> dict[str, object]:
    return {
        "webhook_type": "TRANSACTIONS",
        "webhook_code": code,
        "item_id": item_id,
        "initial_update_complete": True,
    }


async def test_invalid_signature_is_rejected_and_enqueues_nothing(
    client: AsyncClient, fake_plaid, db_session, connected_item_id: str
) -> None:
    fake_plaid.webhook_valid = False

    response = await client.post(
        "/api/webhooks/plaid",
        content=json.dumps(_payload(connected_item_id)),
        headers={"Plaid-Verification": "bad", "Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "WEBHOOK_INVALID"
    receipts = (await db_session.execute(select(WebhookReceipt))).scalars().all()
    assert receipts == []


async def test_verified_webhook_enqueues_one_job(
    client: AsyncClient, db_session, connected_item_id: str, drained_initial_job
) -> None:
    response = await client.post(
        "/api/webhooks/plaid",
        content=json.dumps(_payload(connected_item_id)),
        headers={"Plaid-Verification": "signed", "Content-Type": "application/json"},
    )

    assert response.status_code == 204
    jobs = (
        await db_session.execute(select(SyncJob).where(SyncJob.state == "queued"))
    ).scalars().all()
    assert [job.trigger for job in jobs] == ["webhook"]


async def test_replayed_webhook_creates_one_receipt_and_one_job(
    client: AsyncClient, db_session, connected_item_id: str, drained_initial_job
) -> None:
    body = json.dumps(_payload(connected_item_id))
    headers = {"Plaid-Verification": "signed", "Content-Type": "application/json"}

    first = await client.post("/api/webhooks/plaid", content=body, headers=headers)
    second = await client.post("/api/webhooks/plaid", content=body, headers=headers)

    assert first.status_code == second.status_code == 204
    receipts = (await db_session.execute(select(WebhookReceipt))).scalars().all()
    assert len(receipts) == 1
    jobs = (
        await db_session.execute(select(SyncJob).where(SyncJob.state == "queued"))
    ).scalars().all()
    assert len(jobs) == 1


async def test_unknown_item_is_accepted_without_a_job(
    client: AsyncClient, db_session, connected_item_id: str, drained_initial_job
) -> None:
    response = await client.post(
        "/api/webhooks/plaid",
        content=json.dumps(_payload("item-does-not-exist")),
        headers={"Plaid-Verification": "signed", "Content-Type": "application/json"},
    )

    assert response.status_code == 204
    jobs = (
        await db_session.execute(select(SyncJob).where(SyncJob.state == "queued"))
    ).scalars().all()
    assert jobs == []


async def test_pending_disconnect_marks_the_connection(
    client: AsyncClient, db_session, connected_item_id: str, drained_initial_job
) -> None:
    from app.models import BankConnection

    response = await client.post(
        "/api/webhooks/plaid",
        content=json.dumps(_payload(connected_item_id, "PENDING_DISCONNECT")),
        headers={"Plaid-Verification": "signed", "Content-Type": "application/json"},
    )

    assert response.status_code == 204
    connection = (
        await db_session.execute(
            select(BankConnection).where(
                BankConnection.plaid_item_id == connected_item_id
            )
        )
    ).scalars().one()
    await db_session.refresh(connection)
    assert connection.last_error_code == "PENDING_DISCONNECT"


async def test_webhook_does_not_run_sync_inline(
    client: AsyncClient, fake_plaid, connected_item_id: str, drained_initial_job
) -> None:
    await client.post(
        "/api/webhooks/plaid",
        content=json.dumps(_payload(connected_item_id)),
        headers={"Plaid-Verification": "signed", "Content-Type": "application/json"},
    )

    assert fake_plaid.sync_call_count("access-sandbox-public-conn-1-1") == 0
