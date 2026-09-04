from __future__ import annotations

import asyncio
from datetime import timedelta

from httpx import AsyncClient


def _headers(csrf_token: str, key: str = "refresh-key") -> dict[str, str]:
    return {
        "X-CSRF-Token": csrf_token,
        "Idempotency-Key": key,
        "Origin": "http://127.0.0.1:8000",
    }


async def test_create_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/transaction-refreshes",
        headers={"Idempotency-Key": "key", "Origin": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 401


async def test_create_requires_csrf_and_idempotency_key(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    missing_csrf = await authenticated_client.post(
        "/api/transaction-refreshes",
        headers={
            "Idempotency-Key": "key",
            "Origin": "http://127.0.0.1:8000",
        },
    )
    missing_key = await authenticated_client.post(
        "/api/transaction-refreshes",
        headers={
            "X-CSRF-Token": csrf_token,
            "Origin": "http://127.0.0.1:8000",
        },
    )

    assert missing_csrf.status_code == 403
    assert missing_key.status_code == 422
    assert missing_key.json()["code"] == "REQUEST_INVALID"


async def test_create_rejects_missing_origin_and_malformed_key(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    missing_origin = await authenticated_client.post(
        "/api/transaction-refreshes",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "key"},
    )
    malformed = await authenticated_client.post(
        "/api/transaction-refreshes",
        headers=_headers(csrf_token, "contains spaces"),
    )

    assert missing_origin.status_code == 403
    assert missing_origin.json()["code"] == "ORIGIN_INVALID"
    assert malformed.status_code == 422


async def test_create_returns_run_without_inline_provider_io(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
    fake_plaid,
) -> None:
    response = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token)
    )

    assert response.status_code == 202
    body = response.json()
    assert body["coalesced"] is False
    assert body["refresh"]["state"] == "queued"
    assert body["refresh"]["summary"] == {
        "total": 1,
        "completed": 0,
        "updated": 0,
        "attention": 0,
        "added": 0,
        "modified": 0,
        "removed": 0,
    }
    assert body["refresh"]["targets"][0]["connection_id"] == connected_connection.id
    assert fake_plaid.refreshed_tokens == []


async def test_replay_and_active_discovery_return_the_same_run(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    first = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token)
    )
    replay = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token)
    )
    active = await authenticated_client.get("/api/transaction-refreshes/active")
    by_id = await authenticated_client.get(
        f"/api/transaction-refreshes/{first.json()['refresh']['id']}"
    )

    assert replay.status_code == 202
    assert replay.json()["coalesced"] is True
    assert active.status_code == by_id.status_code == 200
    assert active.json()["id"] == by_id.json()["id"] == first.json()["refresh"]["id"]


async def test_terminal_idempotent_replay_returns_200(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
    sync_worker,
) -> None:
    first = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token, "terminal")
    )
    assert await sync_worker.run_once() is True

    replay = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token, "terminal")
    )

    assert replay.status_code == 200
    assert replay.json()["refresh"]["id"] == first.json()["refresh"]["id"]


async def test_active_discovery_returns_204_when_idle(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get("/api/transaction-refreshes/active")

    assert response.status_code == 204
    assert response.content == b""


async def test_missing_expired_and_cross_owner_ids_share_not_found_contract(
    authenticated_client: AsyncClient, db_session, owner
) -> None:
    from app.models import Owner, TransactionRefresh, utcnow

    other = Owner(
        email="other@example.com",
        password_hash="hash",
        plaid_user_id="other-plaid-user",
    )
    db_session.add(other)
    await db_session.flush()
    expired = TransactionRefresh(
        owner_id=owner.id,
        state="succeeded",
        finished_at=utcnow(),
        expires_at=utcnow() - timedelta(seconds=1),
    )
    cross_owner = TransactionRefresh(
        owner_id=other.id,
        state="succeeded",
        finished_at=utcnow(),
        expires_at=utcnow() + timedelta(days=1),
    )
    db_session.add_all([expired, cross_owner])
    await db_session.commit()

    responses = [
        await authenticated_client.get("/api/transaction-refreshes/missing"),
        await authenticated_client.get(f"/api/transaction-refreshes/{expired.id}"),
        await authenticated_client.get(
            f"/api/transaction-refreshes/{cross_owner.id}"
        ),
    ]

    assert {response.status_code for response in responses} == {404}
    assert {response.json()["code"] for response in responses} == {"NOT_FOUND"}


async def test_disabled_feature_returns_stable_conflict(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
    app,
) -> None:
    app.state.settings.enable_transaction_refresh = False

    response = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TRANSACTION_REFRESH_DISABLED"


async def test_no_active_connections_is_a_stable_conflict(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/transaction-refreshes", headers=_headers(csrf_token)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "NO_ACTIVE_CONNECTIONS"


async def test_one_hundred_concurrent_posts_coalesce_to_one_run(
    authenticated_client: AsyncClient,
    csrf_token: str,
    connected_connection,
    drained_initial_job,
) -> None:
    responses = await asyncio.gather(
        *(
            authenticated_client.post(
                "/api/transaction-refreshes",
                headers=_headers(csrf_token, f"concurrent-{index}"),
            )
            for index in range(100)
        )
    )

    assert {response.status_code for response in responses} == {202}
    ids = {response.json()["refresh"]["id"] for response in responses}
    assert len(ids) == 1
    assert sum(not response.json()["coalesced"] for response in responses) == 1
