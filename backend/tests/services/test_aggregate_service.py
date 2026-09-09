from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.errors import AppError
from app.models import BankConnection, CardAccount, Owner, Transaction
from app.services.transaction_summary import TransactionSummary


async def _seed_cards(db_session, owner):  # type: ignore[no-untyped-def]
    connection = BankConnection(
        owner_id=owner.id,
        bank_slug="capital-one",
        institution_id="ins-aggregates",
        institution_name="Capital One",
        plaid_item_id="item-aggregates",
        plaid_environment="test",
        lifecycle_status="active",
        last_successful_sync_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    first = CardAccount(
        connection=connection,
        plaid_account_id="aggregate-card-1",
        name="Savor",
        mask="5663",
        is_active=True,
        display_order=0,
    )
    second = CardAccount(
        connection=connection,
        plaid_account_id="aggregate-card-2",
        name="Discover it Miles",
        mask="9836",
        is_active=True,
        display_order=1,
    )
    db_session.add_all([connection, first, second])
    await db_session.flush()
    return first, second


def _create_request(**overrides):  # type: ignore[no-untyped-def]
    from app.schemas import CreateTransactionAggregateRequest

    values = {"keyword": " Paze ", "card_scope": "all_cards", "card_ids": []}
    values.update(overrides)
    return CreateTransactionAggregateRequest(**values)


async def test_create_normalizes_keyword_and_deduplicates_selected_cards(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    from app.services.aggregate_service import TransactionAggregateService

    first, second = await _seed_cards(db_session, owner)
    result = await TransactionAggregateService(db_session).create_aggregate(
        owner.id,
        _create_request(
            card_scope="selected_cards",
            card_ids=[second.id, first.id, second.id],
        ),
    )

    assert result.aggregate.keyword == "Paze"
    assert result.aggregate.normalized_keyword == "paze"
    assert result.card_ids == sorted([first.id, second.id])


@pytest.mark.parametrize(
    ("card_scope", "card_ids"),
    [
        ("selected_cards", []),
        ("selected_cards", ["not-this-owner-card"]),
        ("all_cards", ["unexpected-card"]),
    ],
)
async def test_create_rejects_invalid_card_selections(
    db_session,
    owner,
    card_scope: str,
    card_ids: list[str],
) -> None:  # type: ignore[no-untyped-def]
    from app.services.aggregate_service import TransactionAggregateService

    await _seed_cards(db_session, owner)

    with pytest.raises(AppError) as error:
        await TransactionAggregateService(db_session).create_aggregate(
            owner.id,
            _create_request(card_scope=card_scope, card_ids=card_ids),
        )

    assert error.value.code == "REQUEST_INVALID"


async def test_partial_update_and_mutations_are_owner_scoped(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    from app.schemas import UpdateTransactionAggregateRequest
    from app.services.aggregate_service import TransactionAggregateService

    first, _ = await _seed_cards(db_session, owner)
    service = TransactionAggregateService(db_session)
    created = await service.create_aggregate(owner.id, _create_request())
    updated = await service.update_aggregate(
        owner.id,
        created.aggregate.id,
        UpdateTransactionAggregateRequest(
            keyword=" Dunkin ",
            card_scope="selected_cards",
            card_ids=[first.id],
        ),
    )

    assert updated.aggregate.keyword == "Dunkin"
    assert updated.aggregate.normalized_keyword == "dunkin"
    assert updated.aggregate.card_scope == "selected_cards"
    assert updated.card_ids == [first.id]

    other_owner = Owner(email="other@example.com", password_hash="hash")
    db_session.add(other_owner)
    await db_session.flush()
    with pytest.raises(AppError) as hidden:
        await service.update_aggregate(
            other_owner.id,
            created.aggregate.id,
            UpdateTransactionAggregateRequest(keyword="Hidden"),
        )
    assert hidden.value.code == "TRANSACTION_AGGREGATE_NOT_FOUND"
    assert hidden.value.status_code == 404


async def test_evaluation_returns_each_target_card_with_complete_usd_summary(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    from app.services.aggregate_service import TransactionAggregateService

    first, second = await _seed_cards(db_session, owner)
    transactions = [
        ("purchase", 12_000, "USD", False),
        ("pending-purchase", 500, "USD", True),
        ("refund", -2_000, "USD", False),
        ("cad-purchase", 9_000, "CAD", False),
    ]
    for transaction_id, amount_cents, currency_code, pending in transactions:
        db_session.add(
            Transaction(
                plaid_transaction_id=f"aggregate-{transaction_id}",
                card_account_id=first.id,
                authorized_date=date(2026, 9, 8),
                posted_date=None if pending else date(2026, 9, 8),
                merchant_name="Paze",
                name=f"Paze {transaction_id}",
                original_description=f"PAZE {transaction_id}",
                amount_cents=amount_cents,
                currency_code=currency_code,
                pending=pending,
                search_text=f"paze {transaction_id}",
            )
        )
    await db_session.flush()

    service = TransactionAggregateService(db_session)
    await service.create_aggregate(owner.id, _create_request())
    result = await service.evaluate_saved_aggregates(owner.id)

    assert [item.card.id for item in result.aggregates] == [first.id, second.id]
    assert result.aggregates[0].summary == TransactionSummary(
        usd_match_count=3,
        usd_pending_count=1,
        purchases_cents=12_500,
        refunds_cents=2_000,
        net_total_cents=10_500,
    )
    assert result.aggregates[1].summary == TransactionSummary(0, 0, 0, 0, 0)
    assert result.cache_as_of == datetime(2026, 9, 8, tzinfo=UTC)


async def test_evaluation_freshness_ignores_cards_outside_selected_aggregates(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    from app.services.aggregate_service import TransactionAggregateService

    selected_card, _ = await _seed_cards(db_session, owner)
    stale_connection = BankConnection(
        owner_id=owner.id,
        bank_slug="chase",
        institution_id="ins-stale-aggregate",
        institution_name="Chase",
        plaid_item_id="item-stale-aggregate",
        plaid_environment="test",
        lifecycle_status="active",
        last_successful_sync_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add(
        CardAccount(
            connection=stale_connection,
            plaid_account_id="aggregate-stale-card",
            name="Freedom",
            mask="5584",
            is_active=True,
            display_order=0,
        )
    )
    await db_session.flush()

    service = TransactionAggregateService(db_session)
    await service.create_aggregate(
        owner.id,
        _create_request(
            card_scope="selected_cards",
            card_ids=[selected_card.id],
        ),
    )

    result = await service.evaluate_saved_aggregates(owner.id)

    assert [item.card.id for item in result.aggregates] == [selected_card.id]
    assert result.cache_as_of == datetime(2026, 9, 8, tzinfo=UTC)


async def test_listing_and_evaluation_exclude_other_owners_definitions(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    from app.models import TransactionAggregate
    from app.services.aggregate_service import TransactionAggregateService

    await _seed_cards(db_session, owner)
    service = TransactionAggregateService(db_session)
    own = await service.create_aggregate(owner.id, _create_request())
    other_owner = Owner(email="isolated@example.com", password_hash="hash")
    db_session.add(other_owner)
    await db_session.flush()
    db_session.add(
        TransactionAggregate(
            owner_id=other_owner.id,
            keyword="Hidden",
            normalized_keyword="hidden",
            card_scope="all_cards",
        )
    )
    await db_session.flush()

    listing = await service.list_aggregates(owner.id)
    evaluated = await service.evaluate_saved_aggregates(owner.id)

    assert [item.aggregate.id for item in listing.aggregates] == [own.aggregate.id]
    assert {item.aggregate_id for item in evaluated.aggregates} == {own.aggregate.id}
