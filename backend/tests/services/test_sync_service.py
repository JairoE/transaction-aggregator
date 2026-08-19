from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import BankConnection, CardAccount, SyncRun, Transaction, utcnow
from app.services.plaid_gateway import PlaidGatewayError
from tests.fakes.plaid import page, transaction


async def test_initial_sync_starts_from_an_empty_cursor(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    fake_plaid.script_sync(
        token,
        [
            page(
                request_cursor="",
                added=[transaction("t1", "acct-credit-1"), transaction("t2", "acct-credit-2")],
                next_cursor="cursor-1",
                has_more=False,
            )
        ],
    )

    summary = await sync_service.synchronize(connected_connection.id)

    assert summary.added == 2
    rows = (await db_session.execute(select(Transaction))).scalars().all()
    assert {row.plaid_transaction_id for row in rows} == {"t1", "t2"}
    connection = await db_session.get(BankConnection, connected_connection.id)
    assert connection is not None
    await db_session.refresh(connection)
    assert connection.sync_cursor == "cursor-1"
    assert connection.last_successful_sync_at is not None


async def test_multi_page_sync_advances_the_cursor_once(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    fake_plaid.script_sync(
        token,
        [
            page(
                request_cursor="",
                added=[transaction("t1", "acct-credit-1")],
                next_cursor="cursor-1",
                has_more=True,
            ),
            page(
                request_cursor="cursor-1",
                added=[transaction("t2", "acct-credit-1")],
                next_cursor="cursor-2",
                has_more=False,
            ),
        ],
    )

    summary = await sync_service.synchronize(connected_connection.id)

    assert summary.added == 2
    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.sync_cursor == "cursor-2"


async def test_added_modified_and_removed_apply_together(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    fake_plaid.script_sync(
        token,
        [
            page(
                request_cursor="",
                added=[
                    transaction("t1", "acct-credit-1", name="Old Name"),
                    transaction("t2", "acct-credit-1"),
                ],
                next_cursor="cursor-1",
            )
        ],
    )
    await sync_service.synchronize(connected_connection.id)

    fake_plaid.script_sync(
        token,
        [
            page(
                request_cursor="cursor-1",
                modified=[transaction("t1", "acct-credit-1", name="New Name")],
                removed_ids=["t2"],
                next_cursor="cursor-2",
            )
        ],
    )
    summary = await sync_service.synchronize(connected_connection.id)

    assert (summary.modified, summary.removed) == (1, 1)
    rows = (await db_session.execute(select(Transaction))).scalars().all()
    assert [row.plaid_transaction_id for row in rows] == ["t1"]
    assert rows[0].name == "New Name"


async def test_repeated_pages_never_duplicate_transactions(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    same_page = [
        page(
            request_cursor="",
            added=[transaction("t1", "acct-credit-1")],
            next_cursor="cursor-1",
        )
    ]
    fake_plaid.script_sync(token, same_page)
    await sync_service.synchronize(connected_connection.id)

    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    connection.sync_cursor = ""
    await db_session.commit()

    await sync_service.synchronize(connected_connection.id)

    rows = (await db_session.execute(select(Transaction))).scalars().all()
    assert len(rows) == 1


async def test_removing_an_unknown_transaction_is_idempotent(
    sync_service, connected_connection, fake_plaid
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [page(request_cursor="", removed_ids=["never-seen"], next_cursor="cursor-1")],
    )

    summary = await sync_service.synchronize(connected_connection.id)

    assert summary.removed == 0


async def test_mutation_during_pagination_restarts_from_the_attempt_cursor(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    fake_plaid.script_sync(
        token,
        [
            page(
                request_cursor="",
                added=[transaction("t1", "acct-credit-1")],
                next_cursor="cursor-1",
                has_more=True,
            ),
            page(
                request_cursor="cursor-1",
                added=[transaction("t2", "acct-credit-1")],
                next_cursor="cursor-2",
                has_more=False,
            ),
        ],
    )
    fake_plaid.mutation_once_at_call = 1

    summary = await sync_service.synchronize(connected_connection.id)

    assert summary.added == 2
    assert fake_plaid.sync_call_count(token) == 4
    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.sync_cursor == "cursor-2"


async def test_failure_preserves_the_previous_cursor_and_cache(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    token = connected_connection.access_token
    fake_plaid.script_sync(
        token,
        [page(request_cursor="", added=[transaction("t1", "acct-credit-1")], next_cursor="cursor-1")],
    )
    await sync_service.synchronize(connected_connection.id)

    fake_plaid.sync_error = PlaidGatewayError("INSTITUTION_DOWN", "transient")
    with pytest.raises(PlaidGatewayError):
        await sync_service.synchronize(connected_connection.id)

    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.sync_cursor == "cursor-1"
    rows = (await db_session.execute(select(Transaction))).scalars().all()
    assert len(rows) == 1


async def test_owner_action_error_sets_attention_and_stops_retries(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.sync_error = PlaidGatewayError("ITEM_LOGIN_REQUIRED", "owner_action")

    with pytest.raises(PlaidGatewayError):
        await sync_service.synchronize(connected_connection.id)

    connection = await db_session.get(BankConnection, connected_connection.id)
    await db_session.refresh(connection)
    assert connection.last_error_code == "ITEM_LOGIN_REQUIRED"


async def test_sync_run_is_recorded_for_every_attempt(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [page(request_cursor="", added=[transaction("t1", "acct-credit-1")], next_cursor="cursor-1")],
    )

    await sync_service.synchronize(connected_connection.id)

    runs = (await db_session.execute(select(SyncRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].outcome == "succeeded"
    assert runs[0].starting_cursor == ""
    assert runs[0].ending_cursor == "cursor-1"
    assert runs[0].added_count == 1


async def test_amounts_convert_to_integer_cents(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [
            page(
                request_cursor="",
                added=[transaction("t1", "acct-credit-1", amount="64.185")],
                next_cursor="cursor-1",
            )
        ],
    )

    await sync_service.synchronize(connected_connection.id)

    row = (await db_session.execute(select(Transaction))).scalars().one()
    assert row.amount_cents == 6419
    assert row.currency_code == "USD"


async def test_search_text_combines_merchant_name_and_statement(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [
            page(
                request_cursor="",
                added=[
                    transaction(
                        "t1",
                        "acct-credit-1",
                        name="Paze Urban Market",
                        merchant_name="Paze · Urban Market",
                        original_description="PAZE*URBAN MARKET",
                    )
                ],
                next_cursor="cursor-1",
            )
        ],
    )

    await sync_service.synchronize(connected_connection.id)

    row = (await db_session.execute(select(Transaction))).scalars().one()
    assert "paze" in row.search_text
    assert "urban market" in row.search_text
    assert row.original_description == "PAZE*URBAN MARKET"


async def test_transactions_for_unknown_accounts_are_ignored(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [
            page(
                request_cursor="",
                added=[
                    transaction("t1", "acct-credit-1"),
                    transaction("t2", "acct-checking-1"),
                ],
                next_cursor="cursor-1",
            )
        ],
    )

    summary = await sync_service.synchronize(connected_connection.id)

    assert summary.added == 1
    rows = (await db_session.execute(select(Transaction))).scalars().all()
    assert [row.plaid_transaction_id for row in rows] == ["t1"]


async def test_exchange_leaves_exactly_one_initial_job(
    db_session, connected_connection
) -> None:
    from app.models import SyncJob
    from app.services.sync_service import enqueue_sync

    queued = await enqueue_sync(db_session, connected_connection.id, "manual")

    jobs = (await db_session.execute(select(SyncJob))).scalars().all()
    assert len(jobs) == 1
    assert queued.trigger == "initial"


async def test_duplicate_enqueue_returns_the_existing_job(
    db_session, connected_connection, drained_initial_job
) -> None:
    from app.services.sync_service import enqueue_sync

    first = await enqueue_sync(db_session, connected_connection.id, "manual")
    second = await enqueue_sync(db_session, connected_connection.id, "webhook")

    assert first.id == second.id
    assert second.trigger == "manual"


async def test_stale_connections_are_enqueued_at_startup(
    db_session, connected_connection, drained_initial_job
) -> None:
    from app.models import SyncJob
    from app.services.sync_service import enqueue_stale_connections

    connection = await db_session.get(BankConnection, connected_connection.id)
    connection.last_successful_sync_at = utcnow() - timedelta(minutes=61)
    await db_session.commit()

    enqueued = await enqueue_stale_connections(db_session, stale_after_minutes=60)
    await db_session.commit()

    assert enqueued == 1
    jobs = (
        await db_session.execute(select(SyncJob).where(SyncJob.state == "queued"))
    ).scalars().all()
    assert [job.trigger for job in jobs] == ["startup"]


async def test_fresh_connections_are_not_enqueued(
    db_session, connected_connection, drained_initial_job
) -> None:
    from app.services.sync_service import enqueue_stale_connections

    connection = await db_session.get(BankConnection, connected_connection.id)
    connection.last_successful_sync_at = utcnow() - timedelta(minutes=5)
    await db_session.commit()

    assert await enqueue_stale_connections(db_session, stale_after_minutes=60) == 0


async def test_pending_transactions_are_stored_when_supplied(
    sync_service, connected_connection, fake_plaid, db_session
) -> None:
    fake_plaid.script_sync(
        connected_connection.access_token,
        [
            page(
                request_cursor="",
                added=[
                    transaction("t1", "acct-credit-1", pending=True, posted=date(2026, 8, 18))
                ],
                next_cursor="cursor-1",
            )
        ],
    )

    await sync_service.synchronize(connected_connection.id)

    row = (await db_session.execute(select(Transaction))).scalars().one()
    assert row.pending is True
    assert row.posted_date == date(2026, 8, 18)


async def test_cards_discovered_during_sync_are_upserted(
    sync_service, connected_connection, db_session
) -> None:
    cards = (
        await db_session.execute(
            select(CardAccount).where(
                CardAccount.connection_id == connected_connection.id
            )
        )
    ).scalars().all()

    assert {card.plaid_account_id for card in cards} == {
        "acct-credit-1",
        "acct-credit-2",
    }
