from __future__ import annotations

from datetime import date

import pytest

from app.errors import AppError
from app.models import BankConnection, CardAccount, Transaction
from app.schemas import AllTimeWindow, CreateTransactionLimitationRequest
from app.services.limitation_service import LimitationService


async def _seed_cards(db_session, owner):  # type: ignore[no-untyped-def]
    connection = BankConnection(
        owner_id=owner.id,
        bank_slug="capital-one",
        institution_id="ins-limitations",
        institution_name="Capital One",
        plaid_item_id="item-limitations",
        plaid_environment="test",
        lifecycle_status="active",
    )
    first = CardAccount(
        connection=connection,
        plaid_account_id="account-limit-1",
        name="Venture",
        mask="4812",
        is_active=True,
        display_order=0,
    )
    second = CardAccount(
        connection=connection,
        plaid_account_id="account-limit-2",
        name="Savor",
        mask="9921",
        is_active=True,
        display_order=1,
    )
    db_session.add_all([connection, first, second])
    await db_session.flush()

    rows = [
        (first, "paze-1", True),
        (first, "paze-2", False),
        (second, "paze-3", False),
    ]
    for card, transaction_id, pending in rows:
        db_session.add(
            Transaction(
                plaid_transaction_id=transaction_id,
                card_account_id=card.id,
                authorized_date=date(2026, 8, 20),
                posted_date=None if pending else date(2026, 8, 21),
                merchant_name="Paze",
                name="Paze checkout",
                original_description="PAZE*CHECKOUT",
                amount_cents=1000,
                currency_code="USD",
                pending=pending,
                search_text="paze paze checkout paze*checkout",
            )
        )
    await db_session.flush()
    return first, second


def _all_time_request(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "keyword": " Paze ",
        "threshold": 2,
        "card_scope": "all_cards",
        "card_ids": [],
        "window": AllTimeWindow(type="all_time"),
        "is_enabled": True,
    }
    values.update(overrides)
    return CreateTransactionLimitationRequest(**values)


async def test_all_time_alerts_are_per_card_and_include_pending(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    first, second = await _seed_cards(db_session, owner)
    service = LimitationService(db_session)
    created = await service.create_rule(owner.id, _all_time_request())

    assert created.rule.keyword == "Paze"
    assert created.rule.normalized_keyword == "paze"

    result = await service.evaluate_active_alerts(owner.id)

    assert [alert.card.id for alert in result.alerts] == [first.id]
    assert result.alerts[0].match_count == 2
    assert result.alerts[0].pending_count == 1
    assert result.alerts[0].threshold == 2
    assert second.id not in {alert.card.id for alert in result.alerts}


async def test_selected_card_rules_reject_missing_or_unowned_cards(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    await _seed_cards(db_session, owner)
    service = LimitationService(db_session)

    with pytest.raises(AppError) as missing:
        await service.create_rule(
            owner.id,
            _all_time_request(card_scope="selected_cards", card_ids=[]),
        )
    assert missing.value.code == "REQUEST_INVALID"

    with pytest.raises(AppError) as unavailable:
        await service.create_rule(
            owner.id,
            _all_time_request(
                card_scope="selected_cards", card_ids=["not-the-owner-card"]
            ),
        )
    assert unavailable.value.code == "REQUEST_INVALID"


async def test_disabled_rules_do_not_produce_alerts(db_session, owner) -> None:  # type: ignore[no-untyped-def]
    await _seed_cards(db_session, owner)
    service = LimitationService(db_session)
    await service.create_rule(owner.id, _all_time_request(is_enabled=False))

    assert (await service.evaluate_active_alerts(owner.id)).alerts == []
