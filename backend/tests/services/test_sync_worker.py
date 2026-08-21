from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import SyncJob, utcnow
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

    job = await enqueue_sync(db_session, connected_connection.id, "manual")
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

    job = await enqueue_sync(db_session, connected_connection.id, "manual")
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

    job = await enqueue_sync(db_session, connected_connection.id, "manual")
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


async def test_unsupported_refresh_disables_the_capability(
    sync_worker, db_session, connected_connection, fake_plaid
) -> None:
    from app.models import BankConnection
    from app.services.sync_service import request_refresh

    fake_plaid.refresh_supported = False
    connection = await db_session.get(BankConnection, connected_connection.id)

    await request_refresh(db_session, connection, fake_plaid, sync_worker.cipher)
    await db_session.commit()
    await db_session.refresh(connection)

    assert connection.refresh_supported is False


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
