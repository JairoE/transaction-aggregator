"""Durable synchronization jobs and Plaid cursor reconciliation.

The page loop collects every page for one attempt and then applies added,
modified, removed, and the new cursor inside a single database transaction. A
failure therefore leaves the previous cache and cursor untouched.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models import (
    BankConnection,
    CardAccount,
    SyncJob,
    SyncRun,
    Transaction,
    utcnow,
)
from app.services.crypto import EncryptedSecret, TokenCipher
from app.services.plaid_gateway import (
    PlaidGateway,
    PlaidGatewayError,
    PlaidTransaction,
    RefreshUnsupported,
    SyncMutationDuringPagination,
    SyncPage,
)

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATES = ("queued", "running")
MAX_PAGES_PER_ATTEMPT = 200
REFRESH_COOLDOWN_MINUTES = 15


@dataclass(frozen=True)
class SyncSummary:
    connection_id: str
    added: int
    modified: int
    removed: int
    starting_cursor: str
    ending_cursor: str


async def active_job_for(
    session: AsyncSession, connection_id: str
) -> SyncJob | None:
    return (
        await session.execute(
            select(SyncJob)
            .where(SyncJob.connection_id == connection_id)
            .where(SyncJob.state.in_(ACTIVE_JOB_STATES))
            .limit(1)
        )
    ).scalars().first()


async def enqueue_sync(
    session: AsyncSession, connection_id: str, trigger: str
) -> SyncJob:
    """Queue a sync for one connection, or return the job already in flight."""

    existing = await active_job_for(session, connection_id)
    if existing is not None:
        return existing

    job = SyncJob(
        connection_id=connection_id,
        trigger=trigger,
        state="queued",
        attempts=0,
        run_after=utcnow(),
    )
    session.add(job)
    await session.flush()
    return job


async def enqueue_stale_connections(
    session: AsyncSession, stale_after_minutes: int = 60, trigger: str = "startup"
) -> int:
    """Queue every active connection whose cache is older than the threshold."""

    threshold = utcnow() - timedelta(minutes=stale_after_minutes)
    connections = (
        await session.execute(
            select(BankConnection).where(BankConnection.lifecycle_status == "active")
        )
    ).scalars().all()

    queued = 0
    for connection in connections:
        last = connection.last_successful_sync_at
        if last is not None and last > threshold:
            continue
        if await active_job_for(session, connection.id) is not None:
            # A queued or running job already covers this connection.
            continue
        await enqueue_sync(session, connection.id, trigger)
        queued += 1
    return queued


async def request_refresh(
    session: AsyncSession,
    connection: BankConnection,
    gateway: PlaidGateway,
    cipher: TokenCipher,
) -> bool:
    """Best-effort provider refresh; disables itself when unsupported."""

    if not connection.refresh_supported:
        return False
    last = connection.last_refresh_at
    if last is not None and utcnow() - last < timedelta(minutes=REFRESH_COOLDOWN_MINUTES):
        return False

    access_token = decrypt_access_token(connection, cipher)
    try:
        gateway.transactions_refresh(access_token)
    except RefreshUnsupported:
        connection.refresh_supported = False
        return False
    except PlaidGatewayError:
        return False
    connection.last_refresh_at = utcnow()
    return True


def decrypt_access_token(connection: BankConnection, cipher: TokenCipher) -> str:
    if (
        connection.access_token_ciphertext is None
        or connection.access_token_nonce is None
        or connection.access_token_key_version is None
    ):
        raise AppError(
            "CONNECTION_TOKEN_MISSING",
            "This connection has no stored credential. Reconnect the bank.",
            409,
        )
    return cipher.decrypt(
        EncryptedSecret(
            ciphertext=connection.access_token_ciphertext,
            nonce=connection.access_token_nonce,
            key_version=connection.access_token_key_version,
        ),
        context=connection.id,
    )


def normalize_search_text(*parts: str | None) -> str:
    """One lowercase haystack covering merchant, name, and statement text."""

    joined = " ".join(part for part in parts if part)
    folded = unicodedata.normalize("NFKD", joined)
    return " ".join(folded.casefold().split())


def to_cents(amount: Decimal) -> int:
    return int(
        (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


class SyncService:
    def __init__(
        self,
        session: AsyncSession,
        gateway: PlaidGateway,
        cipher: TokenCipher,
    ) -> None:
        self._session = session
        self._gateway = gateway
        self._cipher = cipher

    async def synchronize(
        self, connection_id: str, job_id: str | None = None
    ) -> SyncSummary:
        connection = await self._session.get(BankConnection, connection_id)
        if connection is None or connection.lifecycle_status != "active":
            raise AppError("CONNECTION_NOT_ACTIVE", "That connection is not active.", 409)

        access_token = decrypt_access_token(connection, self._cipher)
        attempt_cursor = connection.sync_cursor or ""
        started_at = utcnow()

        try:
            pages, ending_cursor, request_id = self._collect_pages(
                access_token, attempt_cursor
            )
        except PlaidGatewayError as error:
            await self._record_failure(connection, job_id, attempt_cursor, started_at, error)
            raise

        summary = await self._apply(connection, pages, attempt_cursor, ending_cursor)

        connection.sync_cursor = ending_cursor
        connection.last_successful_sync_at = utcnow()
        connection.last_error_code = None
        connection.last_error_at = None
        await self._record_run(
            connection,
            job_id,
            attempt_cursor,
            ending_cursor,
            summary,
            started_at,
            "succeeded",
            None,
            request_id,
        )
        await self._session.flush()
        return summary

    # --- page loop --------------------------------------------------------
    def _collect_pages(
        self, access_token: str, attempt_cursor: str
    ) -> tuple[list[SyncPage], str, str | None]:
        request_cursor = attempt_cursor
        pages: list[SyncPage] = []
        request_id: str | None = None
        guard = 0

        while True:
            guard += 1
            if guard > MAX_PAGES_PER_ATTEMPT:
                raise PlaidGatewayError("TRANSACTIONS_SYNC_LIMIT", "transient")
            try:
                page = self._gateway.transactions_sync(access_token, request_cursor)
            except SyncMutationDuringPagination:
                # Plaid mutated the Item mid-pagination; discard partial work and
                # restart from the cursor this attempt began with.
                request_cursor = attempt_cursor
                pages.clear()
                continue
            pages.append(page)
            request_id = page.request_id or request_id
            request_cursor = page.next_cursor
            if not page.has_more:
                break

        return pages, request_cursor, request_id

    # --- one atomic apply -------------------------------------------------
    async def _apply(
        self,
        connection: BankConnection,
        pages: list[SyncPage],
        starting_cursor: str,
        ending_cursor: str,
    ) -> SyncSummary:
        card_by_plaid_id = {
            card.plaid_account_id: card
            for card in (
                await self._session.execute(
                    select(CardAccount).where(
                        CardAccount.connection_id == connection.id
                    )
                )
            ).scalars().all()
        }

        added = modified = removed = 0

        for page in pages:
            for provider_row in page.added:
                if await self._upsert(provider_row, card_by_plaid_id, inserted=True):
                    added += 1
            for provider_row in page.modified:
                if await self._upsert(provider_row, card_by_plaid_id, inserted=False):
                    modified += 1
            if page.removed_ids:
                removed += await self._remove(list(page.removed_ids))

        await self._session.flush()
        return SyncSummary(
            connection_id=connection.id,
            added=added,
            modified=modified,
            removed=removed,
            starting_cursor=starting_cursor,
            ending_cursor=ending_cursor,
        )

    async def _upsert(
        self,
        provider_row: PlaidTransaction,
        card_by_plaid_id: dict[str, CardAccount],
        inserted: bool,
    ) -> bool:
        card = card_by_plaid_id.get(provider_row.account_id)
        if card is None:
            # Non-credit accounts under the same Item are intentionally ignored.
            return False

        existing = (
            await self._session.execute(
                select(Transaction).where(
                    Transaction.plaid_transaction_id == provider_row.transaction_id
                )
            )
        ).scalars().first()

        values = {
            "card_account_id": card.id,
            "authorized_date": provider_row.authorized_date,
            "posted_date": provider_row.date,
            "merchant_name": provider_row.merchant_name,
            "name": provider_row.name,
            "original_description": provider_row.original_description,
            "category": provider_row.category,
            "amount_cents": to_cents(provider_row.amount),
            "currency_code": provider_row.iso_currency_code or "USD",
            "pending": provider_row.pending,
            "search_text": normalize_search_text(
                provider_row.merchant_name,
                provider_row.name,
                provider_row.original_description,
            ),
        }

        if existing is None:
            self._session.add(
                Transaction(
                    plaid_transaction_id=provider_row.transaction_id, **values
                )
            )
            return True

        for key, value in values.items():
            setattr(existing, key, value)
        # A re-delivered "added" row is not a new row; only count real changes.
        return not inserted

    async def _remove(self, transaction_ids: list[str]) -> int:
        result = await self._session.execute(
            delete(Transaction).where(
                Transaction.plaid_transaction_id.in_(transaction_ids)
            )
        )
        return int(result.rowcount or 0)

    # --- audit ------------------------------------------------------------
    async def _record_run(
        self,
        connection: BankConnection,
        job_id: str | None,
        starting_cursor: str,
        ending_cursor: str | None,
        summary: SyncSummary | None,
        started_at: datetime,
        outcome: str,
        error_code: str | None,
        request_id: str | None,
    ) -> None:
        self._session.add(
            SyncRun(
                connection_id=connection.id,
                job_id=job_id,
                starting_cursor=starting_cursor,
                ending_cursor=ending_cursor,
                added_count=summary.added if summary else 0,
                modified_count=summary.modified if summary else 0,
                removed_count=summary.removed if summary else 0,
                outcome=outcome,
                error_code=error_code,
                plaid_request_id=request_id,
                started_at=started_at,
                finished_at=utcnow(),
            )
        )

    async def _record_failure(
        self,
        connection: BankConnection,
        job_id: str | None,
        attempt_cursor: str,
        started_at: datetime,
        error: PlaidGatewayError,
    ) -> None:
        connection.last_error_code = error.error_code
        connection.last_error_at = utcnow()
        await self._record_run(
            connection,
            job_id,
            attempt_cursor,
            None,
            None,
            started_at,
            "failed",
            error.error_code,
            error.request_id,
        )
        await self._session.flush()
        logger.warning(
            "sync_failed",
            extra={
                "connection_id": connection.id,
                "plaid_error_code": error.error_code,
                "retry_class": error.retry_class,
            },
        )


__all__ = [
    "ACTIVE_JOB_STATES",
    "active_job_for",
    "REFRESH_COOLDOWN_MINUTES",
    "SyncService",
    "SyncSummary",
    "decrypt_access_token",
    "enqueue_stale_connections",
    "enqueue_sync",
    "normalize_search_text",
    "request_refresh",
    "to_cents",
]
