from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import select

from app.models import (
    BankConnection,
    TransactionRefresh,
    TransactionRefreshRequest,
    TransactionRefreshTarget,
    utcnow,
)


async def test_create_snapshots_connections_without_provider_io(
    db_session, owner, connected_connection, drained_initial_job, fake_plaid
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    service = TransactionRefreshService(db_session)
    run, coalesced = await service.create_or_coalesce(owner.id, "visible-key")

    assert coalesced is False
    assert run.state == "queued"
    requests = (
        await db_session.execute(select(TransactionRefreshRequest))
    ).scalars().all()
    targets = (
        await db_session.execute(select(TransactionRefreshTarget))
    ).scalars().all()
    connection = await db_session.get(BankConnection, connected_connection.id)
    assert len(requests) == len(targets) == 1
    assert requests[0].idempotency_key_sha256 == hashlib.sha256(
        b"visible-key"
    ).hexdigest()
    assert "visible-key" not in requests[0].idempotency_key_sha256
    assert targets[0].required_sync_generation == connection.sync_requested_generation
    assert fake_plaid.refreshed_tokens == []


async def test_same_and_different_keys_coalesce_to_the_active_run(
    db_session, owner, connected_connection, drained_initial_job
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    service = TransactionRefreshService(db_session)
    first, first_coalesced = await service.create_or_coalesce(owner.id, "first")
    replay, replay_coalesced = await service.create_or_coalesce(owner.id, "first")
    other, other_coalesced = await service.create_or_coalesce(owner.id, "other")

    assert first_coalesced is False
    assert replay_coalesced is other_coalesced is True
    assert first.id == replay.id == other.id
    requests = (
        await db_session.execute(select(TransactionRefreshRequest))
    ).scalars().all()
    assert len(requests) == 2


async def test_worker_accepts_refresh_then_syncs_and_completes_target(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService
    from tests.fakes.plaid import page, transaction

    fake_plaid.script_sync(
        connected_connection.access_token,
        [
            page(
                added=[transaction("fresh", "acct-credit-1")],
                next_cursor="fresh-cursor",
            )
        ],
    )
    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "accepted"
    )
    await db_session.commit()

    assert await sync_worker.run_once() is True

    await db_session.refresh(run)
    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    assert run.state == "succeeded"
    assert target.state == "updated"
    assert target.refresh_outcome == "accepted"
    assert target.provider_request_id == "refresh-request-1"
    assert target.added_count == 1
    assert fake_plaid.refreshed_tokens == [connected_connection.access_token]


async def test_cooldown_target_skips_paid_call_but_still_syncs(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    connection = await db_session.get(BankConnection, connected_connection.id)
    connection.last_refresh_at = utcnow()
    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "cooldown"
    )
    await db_session.commit()

    assert await sync_worker.run_once() is True
    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    assert target.state == "cooldown"
    assert target.refresh_outcome == "cooldown"
    assert target.next_refresh_eligible_at > utcnow()
    assert fake_plaid.refreshed_tokens == []


async def test_disabled_refresh_worker_drains_queued_target_as_sync_only(
    database,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
) -> None:
    from app.services.sync_worker import SyncWorker
    from app.services.transaction_refresh_service import TransactionRefreshService

    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "disabled-before-dispatch"
    )
    await db_session.commit()
    disabled_worker = SyncWorker(
        database,
        fake_plaid,
        token_cipher,
        transaction_refresh_enabled=False,
    )

    assert await disabled_worker.run_once() is True

    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    await db_session.refresh(run)
    assert run.state == "succeeded"
    assert target.state == "no_changes"
    assert target.refresh_outcome == "not_attempted"
    assert fake_plaid.refreshed_tokens == []
    assert fake_plaid.sync_call_count(connected_connection.access_token) == 1


async def test_unsupported_provider_is_remembered_after_sync_only_fallback(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    fake_plaid.refresh_supported = False
    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "unsupported"
    )
    await db_session.commit()

    assert await sync_worker.run_once() is True

    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert target.state == "automatic_updates_only"
    assert target.refresh_outcome == "unsupported"
    assert connection.refresh_supported is False
    assert fake_plaid.refreshed_tokens == []


async def test_owner_action_refresh_error_finishes_reconnect_required(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    monkeypatch,
) -> None:
    from app.services import transaction_refresh_service
    from app.services.plaid_gateway import PlaidGatewayError
    from app.services.transaction_refresh_service import TransactionRefreshService

    events: list[tuple[str, dict[str, object]]] = []

    def capture_event(event: str, *, extra: dict[str, object]) -> None:
        events.append((event, extra))

    monkeypatch.setattr(transaction_refresh_service.logger, "info", capture_event)

    fake_plaid.refresh_error = PlaidGatewayError(
        "ITEM_LOGIN_REQUIRED", "owner_action"
    )
    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "reconnect"
    )
    await db_session.commit()

    assert await sync_worker.run_once() is True

    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    await db_session.refresh(run)
    assert target.state == "reconnect_required"
    assert target.error_code == "ITEM_LOGIN_REQUIRED"
    assert run.state == "failed"
    assert fake_plaid.sync_call_count(connected_connection.access_token) == 0
    terminal = next(
        extra
        for event, extra in events
        if event == "transaction_refresh_target_completed"
    )
    assert terminal == {
        "refresh_id": run.id,
        "target_id": target.id,
        "state": "reconnect_required",
        "refresh_outcome": "failed",
        "error_code": "ITEM_LOGIN_REQUIRED",
        "added": 0,
        "modified": 0,
        "removed": 0,
    }


async def test_disconnect_before_reservation_prevents_provider_io(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "disconnected"
    )
    connection = await db_session.get(BankConnection, connected_connection.id)
    connection.lifecycle_status = "removed"
    connection.access_token_ciphertext = None
    connection.access_token_nonce = None
    connection.access_token_key_version = None
    await db_session.commit()

    assert await sync_worker.run_once() is True

    target = (
        await db_session.execute(
            select(TransactionRefreshTarget).where(
                TransactionRefreshTarget.refresh_id == run.id
            )
        )
    ).scalars().one()
    assert target.state == "disconnected"
    assert fake_plaid.refreshed_tokens == []
    assert fake_plaid.sync_call_count(connected_connection.access_token) == 0


async def test_crash_after_dispatch_reservation_recovers_as_outcome_unknown(
    sync_worker,
    db_session,
    owner,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    from app.models import SyncJob
    from app.services.transaction_refresh_service import TransactionRefreshService

    run, _ = await TransactionRefreshService(db_session).create_or_coalesce(
        owner.id, "uncertain"
    )
    await db_session.commit()
    claim = await sync_worker._claim_next_job()
    assert claim is not None
    job = await db_session.get(SyncJob, claim.job_id)
    service = TransactionRefreshService(db_session)
    target_id = await service.reserve_target_for_job(
        connected_connection.id, claim.job_id, claim.lease_token
    )
    await db_session.commit()
    assert target_id is not None
    prepared = await service.prepare_reserved_target(
        target_id, claim.job_id, claim.lease_token, sync_worker.cipher
    )
    await db_session.commit()
    assert prepared is not None and prepared.access_token is not None
    job.lease_expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    assert await sync_worker.recover_expired() == 1
    assert await sync_worker.run_once() is True

    target = await db_session.get(TransactionRefreshTarget, target_id)
    await db_session.refresh(target)
    await db_session.refresh(run)
    assert target.refresh_outcome == "outcome_unknown"
    assert target.state == "outcome_unknown"
    assert run.state == "failed"
    assert fake_plaid.refreshed_tokens == []


async def test_cleanup_is_bounded_and_never_deletes_active_runs(
    db_session, owner
) -> None:
    from app.services.transaction_refresh_service import TransactionRefreshService

    expired = utcnow() - timedelta(days=1)
    for index in range(105):
        db_session.add(
            TransactionRefresh(
                owner_id=owner.id,
                state="succeeded",
                finished_at=expired,
                expires_at=expired,
            )
        )
    active = TransactionRefresh(
        owner_id=owner.id,
        state="queued",
        expires_at=expired,
    )
    db_session.add(active)
    await db_session.flush()

    deleted = await TransactionRefreshService(db_session).cleanup_expired()

    assert deleted == 100
    remaining = (await db_session.execute(select(TransactionRefresh))).scalars().all()
    assert active in remaining
    assert len(remaining) == 6
