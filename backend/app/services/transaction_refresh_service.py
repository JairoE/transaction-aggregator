"""Durable owner-scoped transaction refresh orchestration."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, NotFoundError
from app.models import (
    BankConnection,
    Owner,
    SyncJob,
    TransactionRefresh,
    TransactionRefreshRequest,
    TransactionRefreshTarget,
    utcnow,
)
from app.services.sync_service import SyncSummary, enqueue_sync
from app.services.sync_service import decrypt_access_token
from app.services.crypto import TokenCipher

REFRESH_RETENTION_DAYS = 7
REFRESH_COOLDOWN_MINUTES = 15
ACTIVE_RUN_STATES = ("queued", "running")
ACTIVE_TARGET_STATES = ("queued", "refreshing", "syncing")
ACCEPTABLE_TARGET_STATES = (
    "updated",
    "no_changes",
    "automatic_updates_only",
    "cooldown",
)

logger = logging.getLogger(__name__)


def _log_target_completed(target: TransactionRefreshTarget) -> None:
    logger.info(
        "transaction_refresh_target_completed",
        extra={
            "refresh_id": target.refresh_id,
            "target_id": target.id,
            "state": target.state,
            "refresh_outcome": target.refresh_outcome,
            "error_code": target.error_code,
            "added": target.added_count,
            "modified": target.modified_count,
            "removed": target.removed_count,
        },
    )


@dataclass(frozen=True)
class RefreshPreparation:
    target_id: str
    access_token: str | None
    should_sync: bool = True


class TransactionRefreshService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_coalesce(
        self, owner_id: str, idempotency_key: str
    ) -> tuple[TransactionRefresh, bool]:
        """Create one fleet run or durably map this request to active work."""

        digest = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()

        # Serialize creators for one owner before checking mappings or active
        # work. SQLite's writer lock then makes the unique indexes a backstop
        # instead of an expected source of request errors.
        owned = await self._session.execute(
            update(Owner)
            .where(Owner.id == owner_id)
            .values(updated_at=Owner.updated_at)
            .returning(Owner.id)
        )
        if owned.scalar_one_or_none() is None:
            raise NotFoundError()

        mapped = (
            await self._session.execute(
                select(TransactionRefresh)
                .join(
                    TransactionRefreshRequest,
                    TransactionRefreshRequest.refresh_id == TransactionRefresh.id,
                )
                .where(TransactionRefreshRequest.owner_id == owner_id)
                .where(TransactionRefreshRequest.idempotency_key_sha256 == digest)
                .where(TransactionRefreshRequest.expires_at > utcnow())
            )
        ).scalars().first()
        if mapped is not None:
            logger.info(
                "transaction_refresh_coalesced",
                extra={"owner_id": owner_id, "refresh_id": mapped.id},
            )
            return mapped, True

        active = (
            await self._session.execute(
                select(TransactionRefresh)
                .where(TransactionRefresh.owner_id == owner_id)
                .where(TransactionRefresh.state.in_(ACTIVE_RUN_STATES))
                .limit(1)
            )
        ).scalars().first()
        expires_at = utcnow() + timedelta(days=REFRESH_RETENTION_DAYS)
        if active is not None:
            self._session.add(
                TransactionRefreshRequest(
                    owner_id=owner_id,
                    idempotency_key_sha256=digest,
                    refresh_id=active.id,
                    expires_at=expires_at,
                )
            )
            await self._session.flush()
            logger.info(
                "transaction_refresh_coalesced",
                extra={"owner_id": owner_id, "refresh_id": active.id},
            )
            return active, True

        connections = (
            await self._session.execute(
                select(BankConnection)
                .where(BankConnection.owner_id == owner_id)
                .where(BankConnection.lifecycle_status == "active")
                .order_by(BankConnection.created_at, BankConnection.id)
            )
        ).scalars().all()
        if not connections:
            raise AppError(
                "NO_ACTIVE_CONNECTIONS",
                "Connect a bank before checking for new transactions.",
                409,
            )

        run = TransactionRefresh(
            owner_id=owner_id,
            state="queued",
            expires_at=expires_at,
        )
        self._session.add(run)
        await self._session.flush()
        self._session.add(
            TransactionRefreshRequest(
                owner_id=owner_id,
                idempotency_key_sha256=digest,
                refresh_id=run.id,
                expires_at=expires_at,
            )
        )
        for connection in connections:
            queued = await enqueue_sync(self._session, connection.id, "refresh")
            self._session.add(
                TransactionRefreshTarget(
                    refresh_id=run.id,
                    connection_id=connection.id,
                    state="queued",
                    refresh_outcome="not_attempted",
                    required_sync_generation=queued.requested_generation,
                )
            )
        await self._session.flush()
        logger.info(
            "transaction_refresh_created",
            extra={
                "owner_id": owner_id,
                "refresh_id": run.id,
                "target_count": len(connections),
            },
        )
        return run, False

    async def get_owned(
        self, owner_id: str, refresh_id: str
    ) -> TransactionRefresh:
        run = (
            await self._session.execute(
                select(TransactionRefresh)
                .where(TransactionRefresh.id == refresh_id)
                .where(TransactionRefresh.owner_id == owner_id)
                .where(TransactionRefresh.expires_at > utcnow())
            )
        ).scalars().first()
        if run is None:
            raise NotFoundError("That transaction refresh was not found.")
        return run

    async def active_for_owner(self, owner_id: str) -> TransactionRefresh | None:
        return (
            await self._session.execute(
                select(TransactionRefresh)
                .where(TransactionRefresh.owner_id == owner_id)
                .where(TransactionRefresh.state.in_(ACTIVE_RUN_STATES))
                .order_by(TransactionRefresh.created_at.desc())
                .limit(1)
            )
        ).scalars().first()

    async def reserve_target_for_job(
        self, connection_id: str, job_id: str, lease_token: str
    ) -> str | None:
        job = (
            await self._session.execute(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .where(SyncJob.connection_id == connection_id)
                .where(SyncJob.state == "running")
                .where(SyncJob.lease_token == lease_token)
            )
        ).scalars().first()
        if job is None:
            return None
        target = (
            await self._session.execute(
                select(TransactionRefreshTarget)
                .where(TransactionRefreshTarget.connection_id == connection_id)
                .where(TransactionRefreshTarget.state == "queued")
                .where(
                    TransactionRefreshTarget.required_sync_generation
                    <= job.target_generation
                )
                .limit(1)
            )
        ).scalars().first()
        if target is None:
            return None

        now = utcnow()
        target.state = "refreshing"
        target.refresh_outcome = "reserved"
        target.started_at = target.started_at or now
        run = await self._session.get(TransactionRefresh, target.refresh_id)
        if run is not None:
            run.state = "running"
            run.started_at = run.started_at or now
        await self._session.flush()
        return target.id

    async def prepare_reserved_target(
        self,
        target_id: str,
        job_id: str,
        lease_token: str,
        cipher: TokenCipher,
        *,
        provider_refresh_enabled: bool = True,
    ) -> RefreshPreparation | None:
        target = await self._owned_target(target_id, job_id, lease_token)
        if target is None or target.refresh_outcome != "reserved":
            return None
        connection = await self._session.get(BankConnection, target.connection_id)
        if connection is None or connection.lifecycle_status != "active":
            target.state = "disconnected"
            target.refresh_outcome = "failed"
            target.error_code = "CONNECTION_DISCONNECTED"
            target.finished_at = utcnow()
            _log_target_completed(target)
            await self.derive_run(target.refresh_id)
            return RefreshPreparation(target.id, None, should_sync=False)

        if not provider_refresh_enabled:
            target.state = "syncing"
            target.refresh_outcome = "not_attempted"
            return RefreshPreparation(target.id, None)

        now = utcnow()
        eligible_at = (
            connection.last_refresh_at + timedelta(minutes=REFRESH_COOLDOWN_MINUTES)
            if connection.last_refresh_at is not None
            else None
        )
        if not connection.refresh_supported:
            target.state = "syncing"
            target.refresh_outcome = "unsupported"
            return RefreshPreparation(target.id, None)
        if eligible_at is not None and eligible_at > now:
            target.state = "syncing"
            target.refresh_outcome = "cooldown"
            target.next_refresh_eligible_at = eligible_at
            return RefreshPreparation(target.id, None)

        try:
            access_token = decrypt_access_token(connection, cipher)
        except AppError as error:
            target.state = "reconnect_required"
            target.refresh_outcome = "failed"
            target.error_code = error.code
            target.finished_at = now
            _log_target_completed(target)
            await self.derive_run(target.refresh_id)
            return RefreshPreparation(target.id, None, should_sync=False)

        # This transaction must commit before the provider call. From this
        # point on, absence of a response is treated as an unknown outcome.
        target.refresh_outcome = "dispatching"
        target.next_refresh_eligible_at = now + timedelta(
            minutes=REFRESH_COOLDOWN_MINUTES
        )
        connection.last_refresh_at = now
        return RefreshPreparation(target.id, access_token)

    async def record_dispatch_outcome(
        self,
        target_id: str,
        job_id: str,
        lease_token: str,
        outcome: str,
        *,
        provider_request_id: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        target = await self._owned_target(target_id, job_id, lease_token)
        if target is None or target.refresh_outcome != "dispatching":
            return False
        target.refresh_outcome = outcome
        target.provider_request_id = provider_request_id
        target.error_code = error_code
        if outcome == "unsupported":
            connection = await self._session.get(
                BankConnection, target.connection_id
            )
            if connection is not None:
                connection.refresh_supported = False
        if outcome == "failed" and error_code in {
            "ITEM_LOGIN_REQUIRED",
            "PENDING_EXPIRATION",
            "PENDING_DISCONNECT",
            "USER_PERMISSION_REVOKED",
            "ACCESS_NOT_GRANTED",
        }:
            target.state = "reconnect_required"
            target.finished_at = utcnow()
            _log_target_completed(target)
            await self.derive_run(target.refresh_id)
        else:
            target.state = "syncing"
        return True

    async def recover_target_for_job(self, job: SyncJob) -> None:
        target = (
            await self._session.execute(
                select(TransactionRefreshTarget)
                .where(TransactionRefreshTarget.connection_id == job.connection_id)
                .where(TransactionRefreshTarget.state.in_(("refreshing", "syncing")))
                .limit(1)
            )
        ).scalars().first()
        if target is None:
            return
        if target.refresh_outcome == "dispatching":
            target.refresh_outcome = "outcome_unknown"
            target.state = "syncing"
            target.error_code = "REFRESH_OUTCOME_UNKNOWN"
        elif target.refresh_outcome == "reserved":
            target.refresh_outcome = "not_attempted"
            target.state = "queued"

    async def _owned_target(
        self, target_id: str, job_id: str, lease_token: str
    ) -> TransactionRefreshTarget | None:
        return (
            await self._session.execute(
                select(TransactionRefreshTarget)
                .join(
                    SyncJob,
                    SyncJob.connection_id
                    == TransactionRefreshTarget.connection_id,
                )
                .where(TransactionRefreshTarget.id == target_id)
                .where(SyncJob.id == job_id)
                .where(SyncJob.state == "running")
                .where(SyncJob.lease_token == lease_token)
            )
        ).scalars().first()

    async def complete_target_for_sync(
        self,
        connection_id: str,
        completed_generation: int,
        summary: SyncSummary,
    ) -> None:
        target = (
            await self._session.execute(
                select(TransactionRefreshTarget)
                .where(TransactionRefreshTarget.connection_id == connection_id)
                .where(TransactionRefreshTarget.state == "syncing")
                .where(
                    TransactionRefreshTarget.required_sync_generation
                    <= completed_generation
                )
                .limit(1)
            )
        ).scalars().first()
        if target is None:
            return

        target.added_count = summary.added
        target.modified_count = summary.modified
        target.removed_count = summary.removed
        changed = summary.added + summary.modified + summary.removed > 0
        target.state = {
            "cooldown": "cooldown",
            "unsupported": "automatic_updates_only",
            "outcome_unknown": "outcome_unknown",
            "failed": "failed",
        }.get(target.refresh_outcome, "updated" if changed else "no_changes")
        target.finished_at = utcnow()
        _log_target_completed(target)
        await self.derive_run(target.refresh_id)

    async def mark_target_failed(
        self, connection_id: str, error_code: str, *, reconnect: bool
    ) -> None:
        target = (
            await self._session.execute(
                select(TransactionRefreshTarget)
                .where(TransactionRefreshTarget.connection_id == connection_id)
                .where(TransactionRefreshTarget.state.in_(ACTIVE_TARGET_STATES))
                .limit(1)
            )
        ).scalars().first()
        if target is None:
            return
        target.state = "reconnect_required" if reconnect else "failed"
        target.error_code = error_code
        target.finished_at = utcnow()
        _log_target_completed(target)
        await self.derive_run(target.refresh_id)

    async def derive_run(self, refresh_id: str) -> None:
        run = await self._session.get(TransactionRefresh, refresh_id)
        if run is None:
            return
        targets = (
            await self._session.execute(
                select(TransactionRefreshTarget).where(
                    TransactionRefreshTarget.refresh_id == refresh_id
                )
            )
        ).scalars().all()
        if not targets or any(target.state in ACTIVE_TARGET_STATES for target in targets):
            return
        acceptable = sum(
            target.state in ACCEPTABLE_TARGET_STATES for target in targets
        )
        run.state = (
            "succeeded"
            if acceptable == len(targets)
            else "failed" if acceptable == 0 else "partial"
        )
        run.finished_at = utcnow()
        logger.info(
            "transaction_refresh_completed",
            extra={"refresh_id": run.id, "owner_id": run.owner_id, "state": run.state},
        )

    async def cleanup_expired(self, batch_size: int = 100) -> int:
        ids = (
            await self._session.execute(
                select(TransactionRefresh.id)
                .where(TransactionRefresh.expires_at <= utcnow())
                .where(TransactionRefresh.state.not_in(ACTIVE_RUN_STATES))
                .order_by(TransactionRefresh.expires_at, TransactionRefresh.id)
                .limit(batch_size)
            )
        ).scalars().all()
        if not ids:
            return 0
        await self._session.execute(
            delete(TransactionRefresh).where(TransactionRefresh.id.in_(ids))
        )
        await self._session.flush()
        logger.info("transaction_refresh_cleanup", extra={"deleted": len(ids)})
        return len(ids)


__all__ = [
    "ACCEPTABLE_TARGET_STATES",
    "ACTIVE_RUN_STATES",
    "ACTIVE_TARGET_STATES",
    "REFRESH_COOLDOWN_MINUTES",
    "REFRESH_RETENTION_DAYS",
    "RefreshPreparation",
    "TransactionRefreshService",
]
