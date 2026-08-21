"""One in-process worker draining the durable SQLite job table.

Claiming a job and executing it use separate database transactions so a crash
mid-sync leaves the job recoverable rather than lost, and one connection's
failure never rolls back another's work.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, update

from app.db import Database
from app.errors import AppError
from app.models import BankConnection, SyncJob, SyncRun, utcnow
from app.services.crypto import TokenCipher
from app.services.plaid_gateway import PlaidGateway, PlaidGatewayError
from app.services.sync_service import (
    SyncService,
    enqueue_stale_connections,
)

logger = logging.getLogger(__name__)

BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 480, 1800)
IDLE_SLEEP_SECONDS = 2.0


class SyncWorker:
    def __init__(
        self,
        database: Database,
        gateway: PlaidGateway,
        cipher: TokenCipher,
    ) -> None:
        self._database = database
        self._gateway = gateway
        self.cipher = cipher
        self._stopped = asyncio.Event()

    async def run_once(self) -> bool:
        """Claim and execute at most one due job. Returns True if work ran."""

        job_id = await self._claim_next_job()
        if job_id is None:
            return False

        try:
            async with self._database.session() as session:
                job = await session.get(SyncJob, job_id)
                if job is None:
                    return False
                service = SyncService(session, self._gateway, self.cipher)
                await service.synchronize(job.connection_id, job_id=job.id)
                job.state = "succeeded"
                job.finished_at = utcnow()
                job.last_error_code = None
                await session.commit()
            return True
        except (PlaidGatewayError, AppError) as error:
            await self._record_failure(job_id, error)
            return True
        except Exception as error:  # unexpected local failure
            logger.exception("sync_worker_unexpected_error")
            await self._record_failure(
                job_id, PlaidGatewayError("WORKER_ERROR", "transient")
            )
            del error
            return True

    async def _claim_next_job(self) -> str | None:
        """Claim one due job with a conditional UPDATE.

        SQLAlchemy silently drops FOR UPDATE on SQLite, so the claim is made
        atomic by an UPDATE guarded on the state we read; a losing claimant
        simply sees rowcount 0 and moves on.
        """

        async with self._database.session() as session:
            candidate = (
                await session.execute(
                    select(SyncJob.id)
                    .where(SyncJob.state == "queued")
                    .where(SyncJob.run_after <= utcnow())
                    .order_by(SyncJob.run_after, SyncJob.created_at)
                    .limit(1)
                )
            ).scalars().first()
            if candidate is None:
                return None

            claimed = await session.execute(
                update(SyncJob)
                .where(SyncJob.id == candidate)
                .where(SyncJob.state == "queued")
                .values(
                    state="running",
                    started_at=utcnow(),
                    attempts=SyncJob.attempts + 1,
                    updated_at=utcnow(),
                )
            )
            if not claimed.rowcount:
                await session.rollback()
                return None
            await session.commit()
            return candidate

    async def _record_failure(self, job_id: str, error: Exception) -> None:
        code = getattr(error, "error_code", None) or getattr(error, "code", "UNKNOWN")
        retry_class = getattr(error, "retry_class", "permanent")

        async with self._database.session() as session:
            job = await session.get(SyncJob, job_id)
            if job is None:
                return
            job.last_error_code = code
            job.finished_at = utcnow()

            retryable = retry_class == "transient" and job.attempts <= len(
                BACKOFF_SECONDS
            )
            if retryable:
                delay = BACKOFF_SECONDS[min(job.attempts, len(BACKOFF_SECONDS)) - 1]
                job.state = "queued"
                job.run_after = utcnow() + timedelta(seconds=delay)
                job.finished_at = None
            else:
                job.state = "failed"

            connection = await session.get(BankConnection, job.connection_id)
            if connection is not None:
                connection.last_error_code = code
                connection.last_error_at = utcnow()
                # SyncService records this on its own session, which is rolled
                # back when synchronize() raises, so the audit row is written
                # here where it is committed.
                session.add(
                    SyncRun(
                        connection_id=connection.id,
                        job_id=job.id,
                        starting_cursor=connection.sync_cursor,
                        ending_cursor=None,
                        outcome="failed",
                        error_code=code,
                        started_at=job.started_at or utcnow(),
                        finished_at=utcnow(),
                    )
                )
            await session.commit()

    # --- long-running loops ----------------------------------------------
    async def run_forever(self) -> None:
        while not self._stopped.is_set():
            try:
                did_work = await self.run_once()
            except Exception:  # pragma: no cover - loop must survive
                logger.exception("sync_worker_loop_error")
                did_work = False
            if not did_work:
                try:
                    await asyncio.wait_for(
                        self._stopped.wait(), timeout=IDLE_SLEEP_SECONDS
                    )
                except TimeoutError:
                    continue

    async def run_scheduler(self, interval_minutes: int) -> None:
        while not self._stopped.is_set():
            try:
                async with self._database.session() as session:
                    queued = await enqueue_stale_connections(
                        session, stale_after_minutes=interval_minutes
                    )
                    await session.commit()
                if queued:
                    logger.info("scheduled_sync_enqueued", extra={"queued": queued})
            except Exception:  # pragma: no cover - loop must survive
                logger.exception("sync_scheduler_error")
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=interval_minutes * 60
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()


__all__ = ["BACKOFF_SECONDS", "SyncWorker"]
