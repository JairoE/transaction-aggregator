from __future__ import annotations

from datetime import date

from httpx import AsyncClient

from app.models import BankConnection, CardAccount, Transaction


async def _seed_matching_card(db_session, owner) -> CardAccount:  # type: ignore[no-untyped-def]
    connection = BankConnection(
        owner_id=owner.id,
        bank_slug="chase",
        institution_id="ins-api-limit",
        institution_name="Chase",
        plaid_item_id="item-api-limit",
        plaid_environment="test",
        lifecycle_status="active",
    )
    card = CardAccount(
        connection=connection,
        plaid_account_id="account-api-limit",
        name="Freedom",
        mask="1234",
        is_active=True,
        display_order=0,
    )
    db_session.add_all([connection, card])
    await db_session.flush()
    for index, pending in enumerate((False, True), start=1):
        db_session.add(
            Transaction(
                plaid_transaction_id=f"api-paze-{index}",
                card_account_id=card.id,
                authorized_date=date(2026, 8, 20),
                posted_date=None if pending else date(2026, 8, 21),
                merchant_name="Paze",
                name="Paze checkout",
                original_description="PAZE*CHECKOUT",
                amount_cents=1200,
                currency_code="USD",
                pending=pending,
                search_text="paze paze checkout paze*checkout",
            )
        )
    await db_session.commit()
    return card


async def test_limitation_routes_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/transaction-limitations")).status_code == 401
    assert (await client.get("/api/transaction-limit-alerts")).status_code == 401


async def test_create_list_alert_disable_and_delete_all_time_rule(
    authenticated_client: AsyncClient,
    csrf_token: str,
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    card = await _seed_matching_card(db_session, owner)
    headers = {"X-CSRF-Token": csrf_token}
    created = await authenticated_client.post(
        "/api/transaction-limitations",
        headers=headers,
        json={
            "keyword": "Paze",
            "threshold": 2,
            "card_scope": "all_cards",
            "card_ids": [],
            "window": {"type": "all_time"},
            "is_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    listing = await authenticated_client.get("/api/transaction-limitations")
    assert listing.status_code == 200
    assert listing.json()["rules"][0]["keyword"] == "Paze"
    assert listing.json()["cards"][0]["id"] == card.id

    alerts = await authenticated_client.get("/api/transaction-limit-alerts")
    assert alerts.status_code == 200
    assert alerts.json()["alerts"][0]["match_count"] == 2
    assert alerts.json()["alerts"][0]["pending_count"] == 1

    disabled = await authenticated_client.patch(
        f"/api/transaction-limitations/{rule_id}",
        headers=headers,
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200
    assert (await authenticated_client.get("/api/transaction-limit-alerts")).json()[
        "alerts"
    ] == []

    deleted = await authenticated_client.delete(
        f"/api/transaction-limitations/{rule_id}", headers=headers
    )
    assert deleted.status_code == 204


async def test_limitation_mutations_require_csrf(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.post(
        "/api/transaction-limitations",
        json={
            "keyword": "Paze",
            "threshold": 2,
            "card_scope": "all_cards",
            "card_ids": [],
            "window": {"type": "all_time"},
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


async def test_create_rolling_rule_returns_effective_window(
    authenticated_client: AsyncClient,
    csrf_token: str,
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    await _seed_matching_card(db_session, owner)
    created = await authenticated_client.post(
        "/api/transaction-limitations",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "keyword": "Paze",
            "threshold": 2,
            "card_scope": "all_cards",
            "card_ids": [],
            "window": {"type": "rolling", "days": 5},
            "is_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["window"] == {"type": "rolling", "days": 5}

    alerts = await authenticated_client.get("/api/transaction-limit-alerts")
    assert alerts.status_code == 200
    assert alerts.json()["alerts"][0]["window"] == {
        "type": "rolling",
        "days": 5,
        "start_date": None,
        "end_date": None,
        "effective_start_date": "2026-08-19",
        "effective_end_date": "2026-08-23",
    }
