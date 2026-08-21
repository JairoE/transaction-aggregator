from __future__ import annotations

import json
import logging

from httpx import AsyncClient


async def _exchange(client: AsyncClient, csrf: str, bank: str, institution_id: str,
                    institution_name: str, public_token: str = "public-1"):
    return await client.post(
        "/api/connections/exchange",
        headers={"X-CSRF-Token": csrf},
        json={
            "bank": bank,
            "public_token": public_token,
            "institution_id": institution_id,
            "institution_name": institution_name,
        },
    )


async def test_connections_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/connections")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


async def test_connections_lists_four_supported_banks(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get("/api/connections")

    assert response.status_code == 200
    body = response.json()
    assert [bank["bank"] for bank in body["banks"]] == [
        "capital-one",
        "chase",
        "citi",
        "wells-fargo",
    ]
    assert body["production_item_limit"] == 10
    assert all(bank["connected"] is False for bank in body["banks"])


async def test_link_token_requires_csrf(authenticated_client: AsyncClient) -> None:
    response = await authenticated_client.post(
        "/api/connections/link-token", json={"bank": "chase"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


async def test_link_token_returns_a_token(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/connections/link-token",
        headers={"X-CSRF-Token": csrf_token},
        json={"bank": "chase"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["link_token"]
    assert body["mode"] == "new"
    assert body["consumes_trial_slot"] is False


async def test_link_token_rejects_unsupported_bank(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/connections/link-token",
        headers={"X-CSRF-Token": csrf_token},
        json={"bank": "wells-fargoo"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


async def test_exchange_creates_cards_and_updates_summary(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    exchange = await _exchange(
        authenticated_client, csrf_token, "capital-one", "ins_128026", "Capital One"
    )

    assert exchange.status_code == 200, exchange.text
    assert exchange.json()["card_count"] == 2

    summary = await authenticated_client.get("/api/connections")
    capital_one = next(
        bank for bank in summary.json()["banks"] if bank["bank"] == "capital-one"
    )
    assert capital_one["connected"] is True
    assert capital_one["card_count"] == 2


async def test_duplicate_connection_is_blocked_before_link(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    await _exchange(
        authenticated_client, csrf_token, "citi", "ins_5", "Citi", "public-a"
    )

    response = await authenticated_client.post(
        "/api/connections/link-token",
        headers={"X-CSRF-Token": csrf_token},
        json={"bank": "citi"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "USE_UPDATE_MODE"


async def test_wrong_institution_returns_a_stable_code(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await _exchange(
        authenticated_client, csrf_token, "chase", "ins_5", "Citi", "public-b"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WRONG_INSTITUTION_LINKED"


async def test_update_token_uses_update_mode(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    exchange = await _exchange(
        authenticated_client, csrf_token, "chase", "ins_3", "Chase", "public-c"
    )
    connection_id = exchange.json()["connection_id"]

    response = await authenticated_client.post(
        f"/api/connections/{connection_id}/update-token",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "update"
    assert response.json()["consumes_trial_slot"] is False


async def test_disconnect_requires_csrf_and_then_succeeds(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    exchange = await _exchange(
        authenticated_client, csrf_token, "wells-fargo", "ins_4", "Wells Fargo", "public-d"
    )
    connection_id = exchange.json()["connection_id"]

    without_csrf = await authenticated_client.delete(
        f"/api/connections/{connection_id}"
    )
    assert without_csrf.status_code == 403

    response = await authenticated_client.delete(
        f"/api/connections/{connection_id}", headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 204

    summary = await authenticated_client.get("/api/connections")
    wells = next(
        bank for bank in summary.json()["banks"] if bank["bank"] == "wells-fargo"
    )
    assert wells["connected"] is False


async def test_disconnect_unknown_connection_is_not_found(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.delete(
        "/api/connections/does-not-exist", headers={"X-CSRF-Token": csrf_token}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_no_response_or_log_contains_an_access_token(
    authenticated_client: AsyncClient, csrf_token: str, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        exchange = await _exchange(
            authenticated_client, csrf_token, "citi", "ins_5", "Citi", "public-e"
        )
        summary = await authenticated_client.get("/api/connections")

    bodies = json.dumps([exchange.json(), summary.json()])
    assert "access-sandbox" not in bodies
    assert "access-sandbox" not in caplog.text
    assert "public-e" not in bodies


async def test_connections_expose_health_state_for_every_bank(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    await _exchange(
        authenticated_client, csrf_token, "chase", "ins_3", "Chase", "public-health"
    )

    body = (await authenticated_client.get("/api/connections")).json()

    chase = next(bank for bank in body["banks"] if bank["bank"] == "chase")
    citi = next(bank for bank in body["banks"] if bank["bank"] == "citi")
    # The exchange queues an initial job, so Chase is syncing, not ready.
    assert chase["state"] == "syncing"
    assert chase["action"] == "none"
    assert chase["message"]
    assert citi["state"] == "disconnected"


async def test_a_failing_bank_does_not_hide_a_healthy_one(
    authenticated_client: AsyncClient, csrf_token: str, db_session, fake_plaid
) -> None:
    from sqlalchemy import select, update

    fake_plaid.shared_default_accounts = False

    from app.models import BankConnection, SyncJob, utcnow

    await _exchange(
        authenticated_client, csrf_token, "chase", "ins_3", "Chase", "public-ok"
    )
    await _exchange(
        authenticated_client, csrf_token, "citi", "ins_5", "Citi", "public-bad"
    )
    await db_session.execute(update(SyncJob).values(state="succeeded"))
    await db_session.execute(
        update(BankConnection).values(last_successful_sync_at=utcnow())
    )
    broken = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.bank_slug == "citi")
        )
    ).scalars().one()
    broken.last_error_code = "ITEM_LOGIN_REQUIRED"
    await db_session.commit()

    body = (await authenticated_client.get("/api/connections")).json()

    chase = next(bank for bank in body["banks"] if bank["bank"] == "chase")
    citi = next(bank for bank in body["banks"] if bank["bank"] == "citi")
    assert chase["state"] == "ready"
    assert chase["card_count"] == 2
    assert citi["state"] == "needs_reconnect"
    assert citi["action"] == "reconnect"
    assert citi["card_count"] == 2, "cached cards remain visible"
    assert "ITEM_LOGIN_REQUIRED" not in citi["message"]


async def test_a_plaid_failure_returns_a_typed_error_not_a_500(
    authenticated_client: AsyncClient, csrf_token: str, fake_plaid
) -> None:
    from app.services.plaid_gateway import PlaidGatewayError

    fake_plaid.link_token_requests = fake_plaid.link_token_requests  # no-op, keep fixture
    original = fake_plaid.create_link_token

    def failing(request):
        raise PlaidGatewayError("INVALID_USER_TOKEN", "permanent")

    fake_plaid.create_link_token = failing  # type: ignore[method-assign]
    try:
        response = await authenticated_client.post(
            "/api/connections/link-token",
            headers={"X-CSRF-Token": csrf_token},
            json={"bank": "chase"},
        )
    finally:
        fake_plaid.create_link_token = original  # type: ignore[method-assign]

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PLAID_UNAVAILABLE"
    assert "INVALID_USER_TOKEN" not in response.text
    assert "Traceback" not in response.text
