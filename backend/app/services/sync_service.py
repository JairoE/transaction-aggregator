"""Durable synchronization jobs and Plaid cursor reconciliation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SyncJob, utcnow

ACTIVE_JOB_STATES = ("queued", "running")
Trigger = str


async def enqueue_sync(
    session: AsyncSession, connection_id: str, trigger: Trigger
) -> SyncJob:
    """Queue a sync for one connection, or return the job already in flight."""

    existing = (
        await session.execute(
            select(SyncJob)
            .where(SyncJob.connection_id == connection_id)
            .where(SyncJob.state.in_(ACTIVE_JOB_STATES))
            .limit(1)
        )
    ).scalars().first()
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


__all__ = ["ACTIVE_JOB_STATES", "enqueue_sync"]
