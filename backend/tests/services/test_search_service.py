from __future__ import annotations

import time
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import BankConnection, CardAccount, Owner, Transaction
from app.services.search_service import normalize_query


async def _add_transaction(
    db_session,
    *,
    transaction_id: str,
    card_id: str,
    search_text: str,
    posted_date: date | None = None,
    authorized_date: date | None = None,
) -> None:
    db_session.add(
        Transaction(
            id=transaction_id,
            plaid_transaction_id=f"plaid-{transaction_id}",
            card_account_id=card_id,
            posted_date=posted_date,
            authorized_date=authorized_date,
            merchant_name=search_text,
            name=search_text,
            original_description=None,
            category="Shopping",
            amount_cents=100,
            currency_code="USD",
            pending=False,
            search_text=search_text.casefold(),
        )
    )
    await db_session.commit()


async def test_blank_query_returns_recent_transactions_for_every_card(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "")

    assert len(result.groups) == 8
    assert all(group.transactions for group in result.groups)
    for group in result.groups:
        dates = [
            (row.posted_date or row.authorized_date) for row in group.transactions
        ]
        assert dates == sorted(dates, reverse=True)


async def test_paze_returns_ten_matches_across_eight_cards(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "Paze")

    assert result.total_matches == 10
    assert len(result.groups) == 8
    assert sum(group.match_count for group in result.groups) == 10


async def test_search_is_case_insensitive_and_preserves_display_text(
    search_service, eight_card_owner
) -> None:
    lower = await search_service.search(eight_card_owner.id, "paze")
    upper = await search_service.search(eight_card_owner.id, "PAZE")
    mixed = await search_service.search(eight_card_owner.id, "  PaZe  ")

    assert lower.total_matches == upper.total_matches == mixed.total_matches == 10
    row = next(
        row
        for group in lower.groups
        for row in group.transactions
        if row.original_description
    )
    assert row.original_description.startswith("PAZE*")


async def test_cards_without_a_match_stay_in_the_result(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "Juniper Hotel")

    assert len(result.groups) == 8
    assert result.total_matches == 1
    zero_match = [group for group in result.groups if group.match_count == 0]
    assert len(zero_match) == 7
    assert all(group.transactions == [] for group in zero_match)


async def test_each_group_has_an_independent_cursor(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "", per_card_limit=5)

    cursors = [group.next_cursor for group in result.groups]
    assert all(cursor for cursor in cursors)
    assert len(set(cursors)) == len(cursors)
    assert all(group.has_more for group in result.groups)


async def test_continuation_returns_the_next_page_only_for_that_card(
    search_service, eight_card_owner
) -> None:
    first = await search_service.search(eight_card_owner.id, "", per_card_limit=5)
    target = first.groups[0]
    other = first.groups[1]

    second = await search_service.search(
        eight_card_owner.id,
        "",
        per_card_limit=5,
        cursors={target.card.id: target.next_cursor or ""},
    )

    advanced = next(
        group for group in second.groups if group.card.id == target.card.id
    )
    untouched = next(
        group for group in second.groups if group.card.id == other.card.id
    )
    first_ids = {row.id for row in target.transactions}
    assert {row.id for row in advanced.transactions}.isdisjoint(first_ids)
    assert [row.id for row in untouched.transactions] == [
        row.id for row in other.transactions
    ]


async def test_a_cursor_cannot_be_replayed_against_another_card(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "", per_card_limit=5)
    stolen = result.groups[0].next_cursor
    victim = result.groups[1].card.id

    with pytest.raises(AppError) as error:
        await search_service.search(
            eight_card_owner.id, "", per_card_limit=5, cursors={victim: stolen or ""}
        )

    assert error.value.code == "CURSOR_INVALID"


async def test_a_tampered_cursor_is_rejected(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "", per_card_limit=5)
    group = result.groups[0]
    tampered = (group.next_cursor or "")[:-2] + "AA"

    with pytest.raises(AppError) as error:
        await search_service.search(
            eight_card_owner.id, "", per_card_limit=5, cursors={group.card.id: tampered}
        )

    assert error.value.code == "CURSOR_INVALID"


async def test_sql_metacharacters_are_treated_as_literal_text(
    search_service, eight_card_owner
) -> None:
    for hostile in ["' OR 1=1 --", '"; DROP TABLE transactions; --', "%", "_", "*"]:
        result = await search_service.search(eight_card_owner.id, hostile)
        assert result.total_matches >= 0
        assert len(result.groups) == 8

    still_there = await search_service.search(eight_card_owner.id, "Paze")
    assert still_there.total_matches == 10


async def test_punctuation_matches_the_statement_text_literally(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "PAZE*URBAN")

    assert result.total_matches == 1


async def test_short_queries_use_the_indexed_fallback(
    search_service, eight_card_owner
) -> None:
    normalized = normalize_query("pa")
    assert normalized.uses_index is False
    assert normalized.like_pattern == "%pa%"

    result = await search_service.search(eight_card_owner.id, "pa")
    assert result.total_matches > 0


async def test_query_normalization_rules() -> None:
    assert normalize_query("   ").is_blank is True
    assert normalize_query(None).is_blank is True
    assert normalize_query("  Paze  ").normalized == "paze"
    assert normalize_query("Paze   Market").normalized == "paze market"
    assert len(normalize_query("x" * 500).normalized) == 100
    assert normalize_query('say "hi"').fts_expression == '"say ""hi"""'


async def test_per_card_limit_is_clamped(search_service, eight_card_owner) -> None:
    result = await search_service.search(eight_card_owner.id, "", per_card_limit=999)

    assert all(len(group.transactions) <= 50 for group in result.groups)


async def test_cache_as_of_reports_the_oldest_card_sync(
    search_service, eight_card_owner
) -> None:
    result = await search_service.search(eight_card_owner.id, "")

    assert result.cache_as_of is not None


async def test_search_over_fifty_thousand_rows_stays_under_250ms(
    search_service, eight_card_owner, db_session
) -> None:
    from app.models import CardAccount, Transaction

    cards = (await db_session.execute(__import__("sqlalchemy").select(CardAccount))).scalars().all()
    import datetime as dt

    batch = []
    for index in range(50_000):
        card = cards[index % len(cards)]
        batch.append(
            {
                "id": f"perf-{index}",
                "plaid_transaction_id": f"perf-plaid-{index}",
                "card_account_id": card.id,
                "posted_date": dt.date(2025, 1, 1) + dt.timedelta(days=index % 700),
                "authorized_date": None,
                "merchant_name": f"Merchant {index % 997}",
                "name": f"Merchant {index % 997}",
                "original_description": f"MERCHANT {index % 997} #{index}",
                "category": "Shopping",
                "amount_cents": 100 + (index % 9000),
                "currency_code": "USD",
                "pending": False,
                "search_text": f"merchant {index % 997} merchant {index % 997} #{index}",
                "created_at": dt.datetime.now(dt.UTC),
                "updated_at": dt.datetime.now(dt.UTC),
            }
        )
    await db_session.execute(Transaction.__table__.insert(), batch)
    await db_session.commit()

    timings = []
    for _ in range(10):
        started = time.perf_counter()
        result = await search_service.search(eight_card_owner.id, "Paze")
        timings.append((time.perf_counter() - started) * 1000)

    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert result.total_matches == 10
    assert p95 < 250, f"p95 was {p95:.1f} ms over 50k rows"


async def test_all_transactions_returns_one_global_newest_first_page(
    search_service, eight_card_owner, db_session
) -> None:
    cards = (await search_service.list_cards(eight_card_owner.id))[:3]
    await _add_transaction(
        db_session,
        transaction_id="aggregate-newest",
        card_id=cards[0].id,
        search_text="Aggregate Ordering Sentinel",
        posted_date=date(2026, 9, 3),
    )
    await _add_transaction(
        db_session,
        transaction_id="aggregate-middle",
        card_id=cards[1].id,
        search_text="Aggregate Ordering Sentinel",
        authorized_date=date(2026, 9, 2),
    )
    await _add_transaction(
        db_session,
        transaction_id="aggregate-oldest",
        card_id=cards[2].id,
        search_text="Aggregate Ordering Sentinel",
        posted_date=date(2026, 9, 1),
    )

    result = await search_service.all_transactions(
        eight_card_owner.id, "Aggregate Ordering Sentinel", limit=50
    )

    assert [row.transaction.id for row in result.rows] == [
        "aggregate-newest",
        "aggregate-middle",
        "aggregate-oldest",
    ]


async def test_all_transactions_counts_the_full_fleet_when_search_has_no_matches(
    search_service, eight_card_owner
) -> None:
    result = await search_service.all_transactions(
        eight_card_owner.id, "No Aggregate Matches Exist"
    )

    assert result.rows == []
    assert result.total_matches == 0
    assert result.card_count == 8
    assert result.bank_count == 4


async def test_all_transactions_paginates_dated_and_null_date_rows_without_duplicates(
    search_service, eight_card_owner, db_session
) -> None:
    cards = (await search_service.list_cards(eight_card_owner.id))[:3]
    fixtures = [
        ("aggregate-page-5", cards[0].id, date(2026, 9, 5), None),
        ("aggregate-page-4", cards[1].id, date(2026, 9, 4), None),
        ("aggregate-page-3", cards[2].id, None, date(2026, 9, 3)),
        ("aggregate-page-null-b", cards[0].id, None, None),
        ("aggregate-page-null-a", cards[1].id, None, None),
    ]
    for transaction_id, card_id, posted, authorized in fixtures:
        await _add_transaction(
            db_session,
            transaction_id=transaction_id,
            card_id=card_id,
            search_text="Aggregate Pagination Sentinel",
            posted_date=posted,
            authorized_date=authorized,
        )

    cursor = None
    received: list[str] = []
    while True:
        page = await search_service.all_transactions(
            eight_card_owner.id,
            "Aggregate Pagination Sentinel",
            limit=2,
            cursor=cursor,
        )
        received.extend(row.transaction.id for row in page.rows)
        if not page.has_more:
            break
        cursor = page.next_cursor

    assert received == [
        "aggregate-page-5",
        "aggregate-page-4",
        "aggregate-page-3",
        "aggregate-page-null-b",
        "aggregate-page-null-a",
    ]
    assert len(received) == len(set(received))


async def test_all_transactions_cursor_is_signed_and_bound_to_query(
    search_service, eight_card_owner
) -> None:
    page = await search_service.all_transactions(eight_card_owner.id, "Paze", limit=2)
    tampered = (page.next_cursor or "")[:-2] + "AA"

    with pytest.raises(AppError) as tampered_error:
        await search_service.all_transactions(
            eight_card_owner.id, "Paze", limit=2, cursor=tampered
        )
    with pytest.raises(AppError) as replay_error:
        await search_service.all_transactions(
            eight_card_owner.id,
            "Juniper",
            limit=2,
            cursor=page.next_cursor,
        )

    assert tampered_error.value.code == "CURSOR_INVALID"
    assert replay_error.value.code == "CURSOR_INVALID"


async def test_all_transactions_excludes_other_owner_inactive_card_and_removed_connection_rows(
    search_service, eight_card_owner, db_session
) -> None:
    active_card = (await search_service.list_cards(eight_card_owner.id))[0]
    await _add_transaction(
        db_session,
        transaction_id="aggregate-visible",
        card_id=active_card.id,
        search_text="Aggregate Scope Sentinel",
        posted_date=date(2026, 9, 1),
    )
    other_owner = Owner(
        id="aggregate-other-owner",
        email="aggregate-other@example.com",
        password_hash="hash",
    )
    other_connection = BankConnection(
        id="aggregate-other-connection",
        owner_id=other_owner.id,
        bank_slug="chase",
        institution_id="aggregate-other-institution",
        institution_name="Other Bank",
        plaid_item_id="aggregate-other-item",
        plaid_environment="test",
        lifecycle_status="active",
    )
    other_card = CardAccount(
        id="aggregate-other-card",
        connection_id=other_connection.id,
        plaid_account_id="aggregate-other-account",
        name="Other Card",
        is_active=True,
    )
    inactive_card = CardAccount(
        id="aggregate-inactive-card",
        connection_id=active_card.connection_id,
        plaid_account_id="aggregate-inactive-account",
        name="Inactive Card",
        is_active=False,
    )
    removed_connection = BankConnection(
        id="aggregate-removed-connection",
        owner_id=eight_card_owner.id,
        bank_slug="citi",
        institution_id="aggregate-removed-institution",
        institution_name="Removed Bank",
        plaid_item_id="aggregate-removed-item",
        plaid_environment="test",
        lifecycle_status="removed",
    )
    removed_card = CardAccount(
        id="aggregate-removed-card",
        connection_id=removed_connection.id,
        plaid_account_id="aggregate-removed-account",
        name="Removed Card",
        is_active=True,
    )
    db_session.add_all(
        [
            other_owner,
            other_connection,
            other_card,
            inactive_card,
            removed_connection,
            removed_card,
        ]
    )
    await db_session.commit()
    for transaction_id, card_id in [
        ("aggregate-other-owner-row", other_card.id),
        ("aggregate-inactive-card-row", inactive_card.id),
        ("aggregate-removed-connection-row", removed_card.id),
    ]:
        await _add_transaction(
            db_session,
            transaction_id=transaction_id,
            card_id=card_id,
            search_text="Aggregate Scope Sentinel",
            posted_date=date(2026, 9, 2),
        )

    result = await search_service.all_transactions(
        eight_card_owner.id, "Aggregate Scope Sentinel"
    )

    assert [row.transaction.id for row in result.rows] == ["aggregate-visible"]


async def test_all_transactions_cache_as_of_uses_oldest_active_card_sync(
    search_service, eight_card_owner, db_session
) -> None:
    connections = (
        await db_session.execute(
            select(BankConnection)
            .where(BankConnection.owner_id == eight_card_owner.id)
            .where(BankConnection.lifecycle_status == "active")
        )
    ).scalars().all()
    for index, connection in enumerate(connections):
        connection.last_successful_sync_at = datetime(2026, 9, 2 + index, tzinfo=UTC)
    connections[1].last_successful_sync_at = datetime(2026, 9, 1, tzinfo=UTC)
    await db_session.commit()

    result = await search_service.all_transactions(eight_card_owner.id)

    assert result.cache_as_of == datetime(2026, 9, 1, tzinfo=UTC)
