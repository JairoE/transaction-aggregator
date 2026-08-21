from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from app.models import SyncJob


async def test_manual_sync_requires_authentication(
    client: AsyncClient, connected_connection
) -> None:
    response = await client.post(f"/api/connections/{connected_connection.id}/sync")

    assert response.status_code == 401


async def test_manual_sync_returns_202_with_a_job(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    response = await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["connection_id"] == connected_connection.id
    assert body["state"] == "queued"
    assert body["trigger"] == "manual"


async def test_manual_sync_deduplicates_against_a_queued_job(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
    db_session,
) -> None:
    first = await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )
    second = await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert first.json()["job_id"] == second.json()["job_id"]
    jobs = (
        await db_session.execute(select(SyncJob).where(SyncJob.state == "queued"))
    ).scalars().all()
    assert len(jobs) == 1


async def test_manual_sync_requires_csrf(
    authenticated_client: AsyncClient, connected_connection
) -> None:
    response = await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync"
    )

    assert response.status_code == 403


async def test_manual_sync_on_unknown_connection_is_not_found(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/connections/nope/sync", headers={"X-CSRF-Token": csrf_token}
    )

    assert response.status_code == 404


async def test_unsupported_refresh_does_not_fail_the_sync_request(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
    fake_plaid,
    db_session,
) -> None:
    from app.models import BankConnection

    fake_plaid.refresh_supported = False

    response = await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202
    assert response.json()["refresh_requested"] is False
    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.refresh_supported is False


async def test_sync_status_lists_in_flight_jobs(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    await authenticated_client.post(
        f"/api/connections/{connected_connection.id}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    response = await authenticated_client.get("/api/sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] == 1
    assert body["jobs"][0]["bank"] == "capital-one"
