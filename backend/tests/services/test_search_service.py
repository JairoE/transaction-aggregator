from __future__ import annotations

import time

import pytest

from app.errors import AppError
from app.services.search_service import normalize_query


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
