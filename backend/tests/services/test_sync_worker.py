from __future__ import annotations

import asyncio
import threading
from datetime import timedelta

from sqlalchemy import select, update

from app.models import BankConnection, SyncJob, SyncRun, Transaction, utcnow
from app.services.plaid_gateway import PlaidGatewayError
from app.services.sync_worker import BACKOFF_SECONDS
from tests.fakes.plaid import page, transaction


async def test_run_once_claims_and_completes_a_queued_job(
    sync_worker, db_session, connected_connection, fake_plaid
) -> None:
    from app.services.sync_service import enqueue_sync

    fake_plaid.script_sync(
        connected_connection.access_token,
        [page(request_cursor="", added=[transaction("t1", "acct-credit-1")], next_cursor="cursor-1")],
    )
    await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()

    assert await sync_worker.run_once() is True

    job = (await db_session.execute(select(SyncJob))).scalars().one()
    await db_session.refresh(job)
    assert job.state == "succeeded"
    assert job.finished_at is not None


async def test_run_once_returns_false_when_no_job_is_due(sync_worker) -> None:
    assert await sync_worker.run_once() is False


async def test_transient_failure_retries_with_capped_backoff(
    sync_worker, db_session, connected_connection, fake_plaid
) -> None:
    from app.services.sync_service import enqueue_sync

    job = (await enqueue_sync(db_session, connected_connection.id, "manual")).job
    job_id = job.id
    await db_session.commit()

    fake_plaid.sync_error = PlaidGatewayError("INSTITUTION_DOWN", "transient")
    before = utcnow()
    await sync_worker.run_once()

    stored = await db_session.get(SyncJob, job_id)
    await db_session.refresh(stored)
    assert stored.state == "queued"
    assert stored.attempts == 1
    assert stored.run_after >= before + timedelta(seconds=BACKOFF_SECONDS[0] - 1)


async def test_backoff_is_capped_at_thirty_minutes() -> None:
    assert BACKOFF_SECONDS == (30, 120, 480, 1800)


async def test_owner_action_failure_stops_automatic_retries(
    sync_worker, db_session, connected_connection, fake_plaid
) -> None:
    from app.models import BankConnection
    from app.services.sync_service import enqueue_sync

    job = (await enqueue_sync(db_session, connected_connection.id, "manual")).job
    job_id = job.id
    await db_session.commit()

    fake_plaid.sync_error = PlaidGatewayError("ITEM_LOGIN_REQUIRED", "owner_action")
    await sync_worker.run_once()

    stored = await db_session.get(SyncJob, job_id)
    await db_session.refresh(stored)
    assert stored.state == "failed"
    assert stored.last_error_code == "ITEM_LOGIN_REQUIRED"

    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.last_error_code == "ITEM_LOGIN_REQUIRED"


async def test_exhausted_retries_fail_the_job(
    sync_worker, db_session, connected_connection, fake_plaid
) -> None:
    from app.services.sync_service import enqueue_sync

    job = (await enqueue_sync(db_session, connected_connection.id, "manual")).job
    job.attempts = len(BACKOFF_SECONDS)
    job_id = job.id
    await db_session.commit()

    fake_plaid.sync_error = PlaidGatewayError("INSTITUTION_DOWN", "transient")
    await sync_worker.run_once()

    stored = await db_session.get(SyncJob, job_id)
    await db_session.refresh(stored)
    assert stored.state == "failed"


async def test_one_connection_failure_does_not_block_another(
    sync_worker, db_session, connected_connection, second_connection, fake_plaid
) -> None:
    from app.services.sync_service import enqueue_sync

    fake_plaid.script_sync(
        second_connection.access_token,
        [page(request_cursor="", added=[transaction("s1", "acct-credit-3")], next_cursor="cursor-1")],
    )
    await enqueue_sync(db_session, connected_connection.id, "manual")
    await enqueue_sync(db_session, second_connection.id, "manual")
    await db_session.commit()

    fake_plaid.sync_error = PlaidGatewayError("INSTITUTION_DOWN", "transient")
    await sync_worker.run_once()
    await sync_worker.run_once()

    jobs = {
        job.connection_id: job
        for job in (await db_session.execute(select(SyncJob))).scalars().all()
    }
    for job in jobs.values():
        await db_session.refresh(job)
    assert jobs[connected_connection.id].state == "queued"
    assert jobs[second_connection.id].state == "succeeded"


async def test_failed_attempt_still_records_a_sync_run(
    sync_worker, database, db_session, connected_connection, fake_plaid
) -> None:
    """The service records failures on a session the worker rolls back."""

    from app.models import SyncRun
    from app.services.sync_service import enqueue_sync

    await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()

    fake_plaid.sync_error = PlaidGatewayError("INSTITUTION_DOWN", "transient")
    await sync_worker.run_once()

    async with database.session() as session:
        runs = (await session.execute(select(SyncRun))).scalars().all()

    assert len(runs) == 1
    assert runs[0].outcome == "failed"
    assert runs[0].error_code == "INSTITUTION_DOWN"


async def test_a_running_job_cannot_be_claimed_twice(
    sync_worker, db_session, connected_connection
) -> None:
    from app.services.sync_service import enqueue_sync

    await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()

    first = await sync_worker._claim_next_job()
    second = await sync_worker._claim_next_job()

    assert first is not None
    assert second is None


async def test_competing_workers_issue_one_fenced_claim(
    database,
    db_session,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
) -> None:
    from app.services.sync_service import enqueue_sync
    from app.services.sync_worker import SyncWorker

    await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()
    workers = [
        SyncWorker(database, fake_plaid, token_cipher),
        SyncWorker(database, fake_plaid, token_cipher),
    ]

    claims = await asyncio.gather(*(worker._claim_next_job() for worker in workers))

    claim = next(claim for claim in claims if claim is not None)
    assert sum(result is not None for result in claims) == 1
    assert claim.lease_token
    stored = await db_session.get(SyncJob, claim.job_id)
    await db_session.refresh(stored)
    assert stored.lease_token == claim.lease_token
    assert stored.lease_owner == claim.lease_owner
    assert stored.lease_expires_at > utcnow()


async def test_heartbeat_renews_lease_during_slow_provider_call(
    database,
    db_session,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
    monkeypatch,
) -> None:
    from app.services.sync_service import enqueue_sync
    from app.services.sync_worker import SyncWorker

    entered = threading.Event()
    release = threading.Event()
    original_sync = fake_plaid.transactions_sync

    def blocked_sync(access_token: str, cursor: str):
        entered.set()
        assert release.wait(timeout=2)
        return original_sync(access_token, cursor)

    monkeypatch.setattr(fake_plaid, "transactions_sync", blocked_sync)
    queued = await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()
    worker = SyncWorker(
        database,
        fake_plaid,
        token_cipher,
        lease_seconds=0.4,
        heartbeat_seconds=0.05,
        provider_timeout_seconds=0.3,
    )

    running = asyncio.create_task(worker.run_once())
    assert await asyncio.to_thread(entered.wait, 1)
    job = await db_session.get(SyncJob, queued.job.id)
    await db_session.refresh(job)
    first_expiry = job.lease_expires_at
    await asyncio.sleep(0.12)
    await db_session.rollback()
    await db_session.refresh(job)
    renewed_expiry = job.lease_expires_at
    release.set()

    assert renewed_expiry > first_expiry
    assert await running is True


async def test_expired_job_is_recovered_and_completed(
    database,
    db_session,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
) -> None:
    from app.services.sync_service import enqueue_sync
    from app.services.sync_worker import SyncWorker

    await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()
    first_worker = SyncWorker(database, fake_plaid, token_cipher)
    claim = await first_worker._claim_next_job()
    assert claim is not None
    await db_session.execute(
        update(SyncJob)
        .where(SyncJob.id == claim.job_id)
        .values(lease_expires_at=utcnow() - timedelta(seconds=1))
    )
    await db_session.commit()

    recovery_worker = SyncWorker(database, fake_plaid, token_cipher)
    assert await recovery_worker.recover_expired() == 1
    assert await recovery_worker.run_once() is True

    job = await db_session.get(SyncJob, claim.job_id)
    await db_session.refresh(job)
    assert job.state == "succeeded"
    assert job.lease_token is None


async def test_stale_fence_cannot_apply_or_complete_job(
    database,
    db_session,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
    monkeypatch,
) -> None:
    from app.services.sync_service import enqueue_sync
    from app.services.sync_worker import SyncWorker

    entered = threading.Event()
    release = threading.Event()

    def blocked_sync(_access_token: str, _cursor: str):
        entered.set()
        assert release.wait(timeout=2)
        return page(
            added=[transaction("stale", "acct-credit-1")], next_cursor="stale"
        )

    monkeypatch.setattr(fake_plaid, "transactions_sync", blocked_sync)
    queued = await enqueue_sync(db_session, connected_connection.id, "manual")
    await db_session.commit()
    worker = SyncWorker(
        database,
        fake_plaid,
        token_cipher,
        lease_seconds=1,
        heartbeat_seconds=0.05,
        provider_timeout_seconds=0.5,
    )

    running = asyncio.create_task(worker.run_once())
    assert await asyncio.to_thread(entered.wait, 1)
    job = await db_session.get(SyncJob, queued.job.id)
    await db_session.execute(
        update(SyncJob)
        .where(SyncJob.id == job.id)
        .values(lease_token="replacement-token", lease_owner="replacement-worker")
    )
    await db_session.commit()
    release.set()
    assert await running is True

    transactions = (await db_session.execute(select(Transaction))).scalars().all()
    await db_session.refresh(job)
    assert transactions == []
    assert job.state == "running"
    assert job.lease_token == "replacement-token"


async def test_generation_requested_during_sync_forces_a_second_pass(
    database,
    db_session,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    token_cipher,
    monkeypatch,
) -> None:
    from app.services.sync_service import enqueue_sync
    from app.services.sync_worker import SyncWorker

    entered = threading.Event()
    release = threading.Event()
    original_sync = fake_plaid.transactions_sync

    def blocked_first_sync(access_token: str, cursor: str):
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=2)
        return original_sync(access_token, cursor)

    monkeypatch.setattr(fake_plaid, "transactions_sync", blocked_first_sync)
    queued = await enqueue_sync(db_session, connected_connection.id, "manual")
    first_generation = queued.requested_generation
    await db_session.commit()
    worker = SyncWorker(database, fake_plaid, token_cipher)

    first_pass = asyncio.create_task(worker.run_once())
    assert await asyncio.to_thread(entered.wait, 1)
    async with database.session() as session:
        newer = await enqueue_sync(session, connected_connection.id, "webhook")
        await session.commit()
    release.set()
    assert await first_pass is True

    job = await db_session.get(SyncJob, queued.job.id)
    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(job)
    await db_session.refresh(connection)
    assert first_generation < newer.requested_generation
    assert connection.sync_completed_generation == first_generation
    assert connection.sync_requested_generation == newer.requested_generation
    assert job.state == "queued"

    assert await worker.run_once() is True
    await db_session.refresh(job)
    await db_session.refresh(connection)
    runs = (
        await db_session.execute(
            select(SyncRun)
            .where(SyncRun.connection_id == connected_connection.id)
            .where(SyncRun.outcome == "succeeded")
            .order_by(SyncRun.finished_at)
        )
    ).scalars().all()
    assert job.state == "succeeded"
    assert connection.sync_completed_generation == newer.requested_generation
    assert [run.completed_generation for run in runs[-2:]] == [
        first_generation,
        newer.requested_generation,
    ]
