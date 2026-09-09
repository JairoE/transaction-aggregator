from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from app.models import BankConnection, CardAccount, Owner, Transaction, TransactionAggregate


async def _seed_matching_card(db_session, owner) -> CardAccount:  # type: ignore[no-untyped-def]
    connection = BankConnection(
        owner_id=owner.id,
        bank_slug="chase",
        institution_id="ins-api-aggregate",
        institution_name="Chase",
        plaid_item_id="item-api-aggregate",
        plaid_environment="test",
        lifecycle_status="active",
    )
    card = CardAccount(
        connection=connection,
        plaid_account_id="api-aggregate-card",
        name="Freedom",
        mask="1234",
        is_active=True,
        display_order=0,
    )
    db_session.add_all([connection, card])
    await db_session.flush()
    db_session.add_all(
        [
            Transaction(
                plaid_transaction_id="api-aggregate-purchase",
                card_account_id=card.id,
                authorized_date=date(2026, 9, 8),
                posted_date=None,
                merchant_name="Paze",
                name="Paze checkout",
                original_description="PAZE CHECKOUT",
                amount_cents=12_000,
                currency_code="USD",
                pending=True,
                search_text="paze checkout",
            ),
            Transaction(
                plaid_transaction_id="api-aggregate-refund",
                card_account_id=card.id,
                authorized_date=date(2026, 9, 8),
                posted_date=date(2026, 9, 8),
                merchant_name="Paze",
                name="Paze refund",
                original_description="PAZE REFUND",
                amount_cents=-2_000,
                currency_code="USD",
                pending=False,
                search_text="paze refund",
            ),
        ]
    )
    await db_session.commit()
    return card


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/transaction-aggregates"),
        ("post", "/api/transaction-aggregates"),
        ("patch", "/api/transaction-aggregates/missing"),
        ("delete", "/api/transaction-aggregates/missing"),
        ("get", "/api/saved-transaction-aggregates"),
    ],
)
async def test_aggregate_routes_require_authentication(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    assert (await client.request(method, path, json={})).status_code == 401


async def test_create_list_evaluate_update_and_delete_aggregate(
    authenticated_client: AsyncClient,
    csrf_token: str,
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    card = await _seed_matching_card(db_session, owner)
    headers = {"X-CSRF-Token": csrf_token}
    created = await authenticated_client.post(
        "/api/transaction-aggregates",
        headers=headers,
        json={
            "keyword": " Paze ",
            "card_scope": "selected_cards",
            "card_ids": [card.id, card.id],
        },
    )
    assert created.status_code == 201, created.text
    aggregate_id = created.json()["id"]
    assert created.json()["keyword"] == "Paze"
    assert created.json()["card_ids"] == [card.id]

    listing = await authenticated_client.get("/api/transaction-aggregates")
    assert listing.status_code == 200
    assert listing.json()["aggregates"][0]["id"] == aggregate_id
    assert listing.json()["cards"][0]["id"] == card.id

    evaluated = await authenticated_client.get(
        "/api/saved-transaction-aggregates"
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["aggregates"] == [
        {
            "aggregate_id": aggregate_id,
            "keyword": "Paze",
            "card": listing.json()["cards"][0],
            "summary": {
                "usd_match_count": 2,
                "usd_pending_count": 1,
                "purchases_cents": 12_000,
                "refunds_cents": 2_000,
                "net_total_cents": 10_000,
            },
        }
    ]
    assert evaluated.json()["evaluated_at"] is not None
    assert evaluated.json()["cache_as_of"] is None

    updated = await authenticated_client.patch(
        f"/api/transaction-aggregates/{aggregate_id}",
        headers=headers,
        json={"keyword": "Dunkin", "card_scope": "all_cards", "card_ids": []},
    )
    assert updated.status_code == 200
    assert updated.json()["keyword"] == "Dunkin"
    assert updated.json()["card_scope"] == "all_cards"

    deleted = await authenticated_client.delete(
        f"/api/transaction-aggregates/{aggregate_id}", headers=headers
    )
    assert deleted.status_code == 204
    assert (await authenticated_client.get("/api/transaction-aggregates")).json()[
        "aggregates"
    ] == []


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
async def test_aggregate_mutations_require_csrf(
    authenticated_client: AsyncClient,
    method: str,
) -> None:
    path = "/api/transaction-aggregates"
    if method != "post":
        path += "/missing"
    response = await authenticated_client.request(method, path, json={})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


async def test_selected_cards_must_belong_to_owner(
    authenticated_client: AsyncClient,
    csrf_token: str,
) -> None:
    response = await authenticated_client.post(
        "/api/transaction-aggregates",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "keyword": "Paze",
            "card_scope": "selected_cards",
            "card_ids": ["not-this-owner-card"],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


async def test_other_owners_aggregate_is_hidden_from_mutations(
    authenticated_client: AsyncClient,
    csrf_token: str,
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    other_owner = Owner(email="aggregate-other@example.com", password_hash="hash")
    aggregate = TransactionAggregate(
        owner=other_owner,
        keyword="Hidden",
        normalized_keyword="hidden",
        card_scope="all_cards",
    )
    db_session.add_all([other_owner, aggregate])
    await db_session.commit()

    response = await authenticated_client.patch(
        f"/api/transaction-aggregates/{aggregate.id}",
        headers={"X-CSRF-Token": csrf_token},
        json={"keyword": "Still hidden"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "TRANSACTION_AGGREGATE_NOT_FOUND"
