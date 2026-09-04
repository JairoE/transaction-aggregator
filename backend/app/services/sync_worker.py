"""One in-process worker draining the durable SQLite job table.

Claiming a job and executing it use separate database transactions so a crash
mid-sync leaves the job recoverable rather than lost, and one connection's
failure never rolls back another's work.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update

from app.db import Database
from app.errors import AppError
from app.models import BankConnection, SyncJob, SyncRun, utcnow
from app.services.crypto import TokenCipher
from app.services.plaid_gateway import (
    PlaidGateway,
    PlaidGatewayError,
    RefreshUnsupported,
)
from app.services.sync_service import (
    LeaseLostError,
    SyncService,
    enqueue_stale_connections,
)
from app.services.transaction_refresh_service import (
    RefreshPreparation,
    TransactionRefreshService,
)

logger = logging.getLogger(__name__)

BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 480, 1800)
IDLE_SLEEP_SECONDS = 2.0


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    lease_owner: str
    lease_token: str
    target_generation: int


class SyncWorker:
    def __init__(
        self,
        database: Database,
        gateway: PlaidGateway,
        cipher: TokenCipher,
        *,
        lease_seconds: float | None = None,
        heartbeat_seconds: float | None = None,
        provider_timeout_seconds: float | None = None,
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._database = database
        self._gateway = gateway
        self.cipher = cipher
        self._worker_id = uuid4().hex
        self._lease_seconds = float(
            lease_seconds
            if lease_seconds is not None
            else settings.sync_lease_seconds
        )
        self._heartbeat_seconds = float(
            heartbeat_seconds
            if heartbeat_seconds is not None
            else settings.sync_heartbeat_seconds
        )
        self._provider_timeout_seconds = float(
            provider_timeout_seconds
            if provider_timeout_seconds is not None
            else settings.provider_timeout_seconds
        )
        self._stopped = asyncio.Event()

    async def run_once(self) -> bool:
        """Claim and execute at most one due job. Returns True if work ran."""

        claim = await self._claim_next_job()
        if claim is None:
            return False

        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(claim, heartbeat_stop))
        try:
            refresh = await self._process_refresh_target(claim)
            if refresh is not None and not refresh.should_sync:
                await self._finish_without_sync(claim)
                return True
            async with self._database.session() as session:
                job = (
                    await session.execute(
                        select(SyncJob)
                        .where(SyncJob.id == claim.job_id)
                        .where(SyncJob.state == "running")
                        .where(SyncJob.lease_token == claim.lease_token)
                    )
                ).scalars().first()
                if job is None:
                    raise LeaseLostError(claim.job_id)
                connection_id = job.connection_id
                service = SyncService(
                    session,
                    self._gateway,
                    self.cipher,
                    provider_timeout_seconds=self._provider_timeout_seconds,
                )
                summary = await service.synchronize(
                    connection_id,
                    job_id=job.id,
                    lease_token=claim.lease_token,
                    completed_generation=claim.target_generation,
                )
                await TransactionRefreshService(session).complete_target_for_sync(
                    connection_id,
                    claim.target_generation,
                    summary,
                )
                connection = await session.get(BankConnection, connection_id)
                if connection is None:
                    raise LeaseLostError(claim.job_id)
                needs_another_pass = (
                    connection.sync_requested_generation > claim.target_generation
                )
                completed = await session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == claim.job_id)
                    .where(SyncJob.state == "running")
                    .where(SyncJob.lease_token == claim.lease_token)
                    .values(
                        state="queued" if needs_another_pass else "succeeded",
                        run_after=utcnow(),
                        finished_at=None if needs_another_pass else utcnow(),
                        last_error_code=None,
                        lease_owner=None,
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=utcnow(),
                    )
                )
                if not completed.rowcount:
                    await session.rollback()
                    raise LeaseLostError(claim.job_id)
                await session.commit()
            return True
        except LeaseLostError:
            logger.warning(
                "sync_job_stale_fence_rejected",
                extra={"job_id": claim.job_id, "worker_id": self._worker_id},
            )
            return True
        except (PlaidGatewayError, AppError) as error:
            await self._record_failure(claim, error)
            return True
        except Exception as error:  # unexpected local failure
            logger.exception("sync_worker_unexpected_error")
            await self._record_failure(
                claim, PlaidGatewayError("WORKER_ERROR", "transient")
            )
            del error
            return True
        finally:
            heartbeat_stop.set()
            await heartbeat

    async def _process_refresh_target(
        self, claim: JobClaim
    ) -> RefreshPreparation | None:
        async with self._database.session() as session:
            job = await session.get(SyncJob, claim.job_id)
            if job is None:
                return None
            service = TransactionRefreshService(session)
            target_id = await service.reserve_target_for_job(
                job.connection_id, job.id, claim.lease_token
            )
            await session.commit()
        if target_id is None:
            return None

        async with self._database.session() as session:
            service = TransactionRefreshService(session)
            preparation = await service.prepare_reserved_target(
                target_id, claim.job_id, claim.lease_token, self.cipher
            )
            await session.commit()
        if preparation is None or preparation.access_token is None:
            return preparation

        outcome = "accepted"
        request_id: str | None = None
        error_code: str | None = None
        should_sync = True
        try:
            request_id = await asyncio.wait_for(
                asyncio.to_thread(
                    self._gateway.transactions_refresh,
                    preparation.access_token,
                ),
                timeout=self._provider_timeout_seconds,
            )
        except RefreshUnsupported:
            outcome = "unsupported"
            error_code = "PRODUCTS_NOT_SUPPORTED"
        except TimeoutError:
            outcome = "outcome_unknown"
            error_code = "REFRESH_OUTCOME_UNKNOWN"
        except PlaidGatewayError as error:
            outcome = "failed"
            error_code = error.error_code
            should_sync = error.retry_class != "owner_action"

        async with self._database.session() as session:
            recorded = await TransactionRefreshService(
                session
            ).record_dispatch_outcome(
                target_id,
                claim.job_id,
                claim.lease_token,
                outcome,
                provider_request_id=request_id,
                error_code=error_code,
            )
            if not recorded:
                await session.rollback()
                raise LeaseLostError(claim.job_id)
            await session.commit()
        logger.info(
            "transaction_refresh_dispatch_completed",
            extra={
                "job_id": claim.job_id,
                "target_id": target_id,
                "outcome": outcome,
                "error_code": error_code,
            },
        )
        return RefreshPreparation(target_id, None, should_sync=should_sync)

    async def _finish_without_sync(self, claim: JobClaim) -> None:
        async with self._database.session() as session:
            finished = await session.execute(
                update(SyncJob)
                .where(SyncJob.id == claim.job_id)
                .where(SyncJob.state == "running")
                .where(SyncJob.lease_token == claim.lease_token)
                .values(
                    state="succeeded",
                    finished_at=utcnow(),
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=utcnow(),
                )
            )
            if not finished.rowcount:
                await session.rollback()
                raise LeaseLostError(claim.job_id)
            await session.commit()

    async def _claim_next_job(self) -> JobClaim | None:
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

            lease_token = uuid4().hex
            now = utcnow()
            claimed = await session.execute(
                update(SyncJob)
                .where(SyncJob.id == candidate)
                .where(SyncJob.state == "queued")
                .values(
                    state="running",
                    started_at=now,
                    attempts=SyncJob.attempts + 1,
                    lease_owner=self._worker_id,
                    lease_token=lease_token,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    updated_at=now,
                )
                .returning(SyncJob.target_generation)
            )
            target_generation = claimed.scalar_one_or_none()
            if target_generation is None:
                await session.rollback()
                return None
            await session.commit()
            return JobClaim(
                job_id=candidate,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                target_generation=target_generation,
            )

    async def _record_failure(self, claim: JobClaim, error: Exception) -> None:
        code = getattr(error, "error_code", None) or getattr(error, "code", "UNKNOWN")
        retry_class = getattr(error, "retry_class", "permanent")

        async with self._database.session() as session:
            fenced = await session.execute(
                update(SyncJob)
                .where(SyncJob.id == claim.job_id)
                .where(SyncJob.state == "running")
                .where(SyncJob.lease_token == claim.lease_token)
                .values(updated_at=utcnow())
            )
            if not fenced.rowcount:
                await session.rollback()
                logger.warning(
                    "sync_job_stale_fence_rejected",
                    extra={"job_id": claim.job_id, "worker_id": self._worker_id},
                )
                return
            job = await session.get(SyncJob, claim.job_id)
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
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None

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
                if not retryable:
                    await TransactionRefreshService(session).mark_target_failed(
                        connection.id,
                        code,
                        reconnect=retry_class == "owner_action",
                    )
            await session.commit()

    async def _heartbeat(
        self, claim: JobClaim, stopped: asyncio.Event
    ) -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(
                    stopped.wait(), timeout=self._heartbeat_seconds
                )
                return
            except TimeoutError:
                pass

            try:
                async with self._database.session() as session:
                    now = utcnow()
                    renewed = await session.execute(
                        update(SyncJob)
                        .where(SyncJob.id == claim.job_id)
                        .where(SyncJob.state == "running")
                        .where(SyncJob.lease_token == claim.lease_token)
                        .where(SyncJob.lease_expires_at > now)
                        .values(
                            lease_expires_at=now
                            + timedelta(seconds=self._lease_seconds),
                            updated_at=now,
                        )
                    )
                    if not renewed.rowcount:
                        await session.rollback()
                        return
                    await session.commit()
            except Exception:  # pragma: no cover - the fence still protects writes
                logger.exception(
                    "sync_job_heartbeat_error", extra={"job_id": claim.job_id}
                )
                return

    async def recover_expired(self) -> int:
        """Return abandoned ordinary work to the queue for a fenced retry."""

        async with self._database.session() as session:
            expired_jobs = (
                await session.execute(
                    select(SyncJob)
                    .where(SyncJob.state == "running")
                    .where(SyncJob.lease_expires_at <= utcnow())
                )
            ).scalars().all()
            refreshes = TransactionRefreshService(session)
            for job in expired_jobs:
                await refreshes.recover_target_for_job(job)
            recovered = await session.execute(
                update(SyncJob)
                .where(SyncJob.state == "running")
                .where(SyncJob.lease_expires_at <= utcnow())
                .values(
                    state="queued",
                    run_after=utcnow(),
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=utcnow(),
                )
            )
            await session.commit()
            count = int(recovered.rowcount or 0)
            if count:
                logger.info("sync_job_leases_recovered", extra={"count": count})
            return count

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


__all__ = ["BACKOFF_SECONDS", "JobClaim", "SyncWorker"]
