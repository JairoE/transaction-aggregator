from __future__ import annotations

from httpx import AsyncClient


async def test_search_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/transactions/search?q=Paze")

    assert response.status_code == 401


async def test_search_returns_ten_grouped_paze_matches(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    response = await demo_client.get("/api/transactions/search?q=Paze")

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 10
    assert body["card_count"] == 8
    assert len(body["groups"]) == 8
    assert sum(group["match_count"] for group in body["groups"]) == 10
    masks = [group["card"]["mask"] for group in body["groups"]]
    assert masks == ["4812", "9064", "1187", "2041", "7730", "3628", "5509", "6144"]


async def test_blank_search_returns_recent_rows_for_every_card(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    response = await demo_client.get("/api/transactions/search?q=&per_card_limit=3")

    body = response.json()
    assert len(body["groups"]) == 8
    assert all(len(group["transactions"]) == 3 for group in body["groups"])
    assert all(group["has_more"] is True for group in body["groups"])


async def test_zero_match_cards_stay_visible(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    response = await demo_client.get("/api/transactions/search?q=Juniper%20Hotel")

    body = response.json()
    assert body["total_matches"] == 1
    assert len(body["groups"]) == 8
    empty = [group for group in body["groups"] if group["match_count"] == 0]
    assert len(empty) == 7


async def test_per_card_cursor_advances_only_that_card(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    first = (
        await demo_client.get("/api/transactions/search?q=&per_card_limit=3")
    ).json()
    target = first["groups"][0]
    other = first["groups"][1]

    second = (
        await demo_client.get(
            "/api/transactions/search?q=&per_card_limit=3"
            f"&cursor.{target['card']['id']}={target['next_cursor']}"
        )
    ).json()

    advanced = next(
        group for group in second["groups"] if group["card"]["id"] == target["card"]["id"]
    )
    untouched = next(
        group for group in second["groups"] if group["card"]["id"] == other["card"]["id"]
    )
    assert {row["id"] for row in advanced["transactions"]}.isdisjoint(
        {row["id"] for row in target["transactions"]}
    )
    assert [row["id"] for row in untouched["transactions"]] == [
        row["id"] for row in other["transactions"]
    ]


async def test_invalid_cursor_returns_a_stable_code(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    first = (
        await demo_client.get("/api/transactions/search?q=&per_card_limit=3")
    ).json()
    card_id = first["groups"][0]["card"]["id"]

    response = await demo_client.get(
        f"/api/transactions/search?q=&cursor.{card_id}=not-a-cursor"
    )

    assert response.status_code == 400
    assert response.json()["code"] == "CURSOR_INVALID"


async def test_card_endpoint_paginates_one_card(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    search = (
        await demo_client.get("/api/transactions/search?q=&per_card_limit=3")
    ).json()
    card_id = search["groups"][0]["card"]["id"]

    response = await demo_client.get(
        f"/api/cards/{card_id}/transactions?limit=3"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["card"]["id"] == card_id
    assert len(body["transactions"]) == 3
    assert body["has_more"] is True


async def test_card_endpoint_rejects_an_unknown_card(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    response = await demo_client.get("/api/cards/not-a-card/transactions")

    assert response.status_code == 404


async def test_per_card_limit_is_capped_at_fifty(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    response = await demo_client.get("/api/transactions/search?q=&per_card_limit=500")

    assert response.status_code == 422


async def test_search_never_calls_plaid(
    demo_client: AsyncClient, demo_login, eight_card_owner, demo_plaid
) -> None:
    before = len(demo_plaid.link_token_requests)

    await demo_client.get("/api/transactions/search?q=Paze")

    assert len(demo_plaid.link_token_requests) == before


async def test_response_exposes_display_fields_for_each_row(
    demo_client: AsyncClient, demo_login, eight_card_owner
) -> None:
    body = (await demo_client.get("/api/transactions/search?q=Paze")).json()
    row = body["groups"][0]["transactions"][0]

    assert set(row) >= {
        "id",
        "card_id",
        "merchant_name",
        "description",
        "original_description",
        "amount_cents",
        "currency_code",
        "posted_date",
        "pending",
    }
    assert row["currency_code"] == "USD"
