from __future__ import annotations

import platform
from datetime import date
from time import perf_counter

import pytest
from sqlalchemy import insert

from app.models import BankConnection, CardAccount, Transaction, utcnow
from app.schemas import (
    AllTimeWindow,
    CreateTransactionLimitationRequest,
    FixedWindow,
    RollingWindow,
)
from app.services.limitation_service import LimitationService

pytestmark = pytest.mark.performance

RULE_COUNT = 100
TRANSACTION_COUNT = 100_000


async def test_limitation_evaluation_p95_stays_under_half_a_second(
    db_session,
    owner,
) -> None:  # type: ignore[no-untyped-def]
    connection = BankConnection(
        owner_id=owner.id,
        bank_slug="capital-one",
        institution_id="ins-performance",
        institution_name="Performance Bank",
        plaid_item_id="item-performance",
        plaid_environment="test",
        lifecycle_status="active",
    )
    cards = [
        CardAccount(
            connection=connection,
            plaid_account_id=f"performance-card-{index}",
            name=f"Performance Card {index}",
            mask=f"{index:04d}",
            is_active=True,
            display_order=index,
        )
        for index in range(8)
    ]
    db_session.add_all([connection, *cards])
    await db_session.flush()

    timestamp = utcnow()
    for start in range(0, TRANSACTION_COUNT, 5_000):
        rows = []
        for index in range(start, min(start + 5_000, TRANSACTION_COUNT)):
            matches_rule = index % 100 < len(cards)
            merchant = "Scale Merchant" if matches_rule else "Everyday Purchase"
            rows.append({
                "id": f"performance-transaction-{index}",
                "plaid_transaction_id": f"performance-plaid-{index}",
                "card_account_id": cards[index % len(cards)].id,
                "authorized_date": date(2026, 8, 22),
                "posted_date": date(2026, 8, 22),
                "merchant_name": merchant,
                "name": f"{merchant} purchase",
                "original_description": merchant.upper(),
                "category": "Test",
                "amount_cents": 100,
                "currency_code": "USD",
                "pending": index % 10 == 0,
                "search_text": f"{merchant.lower()} {merchant.lower()} purchase",
                "created_at": timestamp,
                "updated_at": timestamp,
            })
        await db_session.execute(insert(Transaction), rows)

    service = LimitationService(db_session)
    windows = (
        AllTimeWindow(type="all_time"),
        RollingWindow(type="rolling", days=5),
        FixedWindow(
            type="fixed",
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
        ),
    )
    for index in range(RULE_COUNT):
        await service.create_rule(
            owner.id,
            CreateTransactionLimitationRequest(
                keyword="Scale Merchant",
                threshold=1,
                card_scope="all_cards",
                card_ids=[],
                window=windows[index % len(windows)],
                is_enabled=True,
            ),
        )
    await db_session.flush()

    await service.evaluate_active_alerts(owner.id, as_of_date=date(2026, 8, 22))
    durations_ms = []
    for _ in range(20):
        started = perf_counter()
        result = await service.evaluate_active_alerts(
            owner.id,
            as_of_date=date(2026, 8, 22),
        )
        durations_ms.append((perf_counter() - started) * 1000)
    p95_ms = sorted(durations_ms)[18]
    print(
        f"limitation evaluation: {RULE_COUNT} rules, {TRANSACTION_COUNT} transactions, "
        f"p95={p95_ms:.1f}ms, {platform.machine()} {platform.system()}"
    )
    assert len(result.alerts) == RULE_COUNT * len(cards)
    assert p95_ms < 500
