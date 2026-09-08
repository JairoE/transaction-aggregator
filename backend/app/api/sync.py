"""Manual synchronization and sync status."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CsrfDep, OwnerDep, SessionDep
from app.errors import NotFoundError
from app.models import BankConnection, SyncJob
from app.services.sync_service import enqueue_sync

router = APIRouter(prefix="/api", tags=["sync"])

class SyncJobResponse(BaseModel):
    job_id: str
    connection_id: str
    state: str
    trigger: str
    refresh_requested: bool


class SyncStatusEntry(BaseModel):
    connection_id: str
    bank: str
    state: str
    trigger: str | None
    last_error_code: str | None


class SyncStatusResponse(BaseModel):
    jobs: list[SyncStatusEntry]
    running: int
    queued: int


@router.post(
    "/connections/{connection_id}/sync",
    response_model=SyncJobResponse,
    status_code=202,
    dependencies=[CsrfDep],
)
async def trigger_sync(
    connection_id: str,
    owner: OwnerDep,
    session: SessionDep,
) -> SyncJobResponse:
    connection = (
        await session.execute(
            select(BankConnection)
            .where(BankConnection.id == connection_id)
            .where(BankConnection.owner_id == owner.id)
            .where(BankConnection.lifecycle_status == "active")
        )
    ).scalars().first()
    if connection is None:
        raise NotFoundError("That bank connection was not found.")

    queued = await enqueue_sync(session, connection.id, "manual")
    job = queued.job
    return SyncJobResponse(
        job_id=job.id,
        connection_id=connection.id,
        state=job.state,
        trigger=job.trigger,
        refresh_requested=False,
    )


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(owner: OwnerDep, session: SessionDep) -> SyncStatusResponse:
    rows = (
        await session.execute(
            select(SyncJob, BankConnection)
            .join(BankConnection, BankConnection.id == SyncJob.connection_id)
            .where(BankConnection.owner_id == owner.id)
            .where(SyncJob.state.in_(("queued", "running")))
            .order_by(SyncJob.created_at)
        )
    ).all()

    entries = [
        SyncStatusEntry(
            connection_id=connection.id,
            bank=connection.bank_slug,
            state=job.state,
            trigger=job.trigger,
            last_error_code=connection.last_error_code,
        )
        for job, connection in rows
    ]
    return SyncStatusResponse(
        jobs=entries,
        running=sum(1 for entry in entries if entry.state == "running"),
        queued=sum(1 for entry in entries if entry.state == "queued"),
    )


__all__ = ["router"]
