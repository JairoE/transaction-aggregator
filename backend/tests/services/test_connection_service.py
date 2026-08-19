from __future__ import annotations

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import BankConnection, CardAccount, Transaction
from app.services.connection_service import ConnectionService
from app.services.plaid_gateway import DAYS_REQUESTED
from tests.fakes.plaid import credit_card


async def test_link_token_requests_transactions_credit_and_redirect(
    connection_service: ConnectionService, owner, fake_plaid
) -> None:
    result = await connection_service.create_link_token(owner, "capital-one")

    assert result.link_token.startswith("link-sandbox-new")
    request = fake_plaid.link_token_requests[-1]
    assert request.days_requested == DAYS_REQUESTED
    assert request.redirect_uri.endswith("/oauth-return")
    assert request.access_token is None
    assert request.client_user_id == owner.id


async def test_sandbox_link_does_not_require_trial_confirmation(
    connection_service: ConnectionService, owner
) -> None:
    result = await connection_service.create_link_token(owner, "chase")

    assert result.consumes_trial_slot is False
    assert result.production_item_count == 0


async def test_production_link_requires_explicit_confirmation(
    production_connection_service: ConnectionService, owner
) -> None:
    with pytest.raises(AppError) as error:
        await production_connection_service.create_link_token(owner, "chase")

    assert error.value.code == "TRIAL_SLOT_UNCONFIRMED"


async def test_production_link_accepts_confirmation(
    production_connection_service: ConnectionService, owner
) -> None:
    result = await production_connection_service.create_link_token(
        owner, "chase", confirm_trial_slot=True
    )

    assert result.consumes_trial_slot is True


async def test_tenth_production_item_blocks_another_link(
    production_connection_service: ConnectionService,
    owner,
    db_session_factory,
    seed_production_tombstones,
) -> None:
    await seed_production_tombstones(owner.id, 10)

    with pytest.raises(AppError) as error:
        await production_connection_service.create_link_token(
            owner, "chase", confirm_trial_slot=True
        )

    assert error.value.code == "TRIAL_LIMIT_REACHED"


async def test_removed_production_items_still_count(
    production_connection_service: ConnectionService, owner, seed_production_tombstones
) -> None:
    await seed_production_tombstones(owner.id, 9)

    result = await production_connection_service.create_link_token(
        owner, "chase", confirm_trial_slot=True
    )

    assert result.production_item_count == 9


async def test_active_institution_blocks_duplicate_link(
    connection_service: ConnectionService, owner, fake_plaid
) -> None:
    await connection_service.exchange_public_token(
        owner, "capital-one", "public-1", "ins_128026", "Capital One"
    )

    with pytest.raises(AppError) as error:
        await connection_service.create_link_token(owner, "capital-one")

    assert error.value.code == "USE_UPDATE_MODE"


async def test_exchange_encrypts_token_and_stores_only_credit_cards(
    connection_service: ConnectionService, owner, fake_plaid, db_session
) -> None:
    connection = await connection_service.exchange_public_token(
        owner, "capital-one", "public-1", "ins_128026", "Capital One"
    )

    stored = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connection.id)
        )
    ).scalars().one()
    assert stored.access_token_ciphertext is not None
    assert "access-sandbox" not in stored.access_token_ciphertext
    assert stored.access_token_nonce is not None
    assert stored.access_token_key_version == 1
    assert stored.lifecycle_status == "active"

    cards = (
        await db_session.execute(
            select(CardAccount).where(CardAccount.connection_id == connection.id)
        )
    ).scalars().all()
    assert {card.mask for card in cards} == {"4812", "9064"}


async def test_exchange_enqueues_initial_sync(
    connection_service: ConnectionService, owner, db_session
) -> None:
    from app.models import SyncJob

    connection = await connection_service.exchange_public_token(
        owner, "chase", "public-2", "ins_3", "Chase"
    )

    jobs = (
        await db_session.execute(
            select(SyncJob).where(SyncJob.connection_id == connection.id)
        )
    ).scalars().all()
    assert [job.trigger for job in jobs] == ["initial"]
    assert jobs[0].state == "queued"


async def test_wrong_institution_is_removed_and_tombstoned(
    connection_service: ConnectionService, owner, fake_plaid, db_session
) -> None:
    with pytest.raises(AppError) as error:
        await connection_service.exchange_public_token(
            owner, "chase", "public-3", "ins_5", "Citi"
        )

    assert error.value.code == "WRONG_INSTITUTION_LINKED"
    assert fake_plaid.removed_tokens, "the mistaken Item must be removed from Plaid"

    tombstones = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.lifecycle_status == "removed")
        )
    ).scalars().all()
    assert len(tombstones) == 1
    assert tombstones[0].access_token_ciphertext is None


async def test_update_link_token_reuses_existing_item(
    connection_service: ConnectionService, owner, fake_plaid
) -> None:
    connection = await connection_service.exchange_public_token(
        owner, "citi", "public-4", "ins_5", "Citi"
    )

    result = await connection_service.create_update_link_token(owner, connection.id)

    request = fake_plaid.link_token_requests[-1]
    assert request.access_token is not None
    assert result.consumes_trial_slot is False


async def test_disconnect_purges_data_and_keeps_tombstone(
    connection_service: ConnectionService, owner, fake_plaid, db_session
) -> None:
    connection = await connection_service.exchange_public_token(
        owner, "wells-fargo", "public-5", "ins_4", "Wells Fargo"
    )
    card = (
        await db_session.execute(
            select(CardAccount).where(CardAccount.connection_id == connection.id)
        )
    ).scalars().first()
    assert card is not None
    db_session.add(
        Transaction(
            plaid_transaction_id="txn-purge-1",
            card_account_id=card.id,
            name="Maple Market",
            amount_cents=4368,
            currency_code="USD",
            search_text="maple market",
        )
    )
    await db_session.commit()

    await connection_service.disconnect(owner, connection.id)
    await db_session.commit()

    assert fake_plaid.removed_tokens
    remaining_cards = (
        await db_session.execute(
            select(CardAccount).where(CardAccount.connection_id == connection.id)
        )
    ).scalars().all()
    assert remaining_cards == []
    remaining_transactions = (
        await db_session.execute(select(Transaction))
    ).scalars().all()
    assert remaining_transactions == []

    tombstone = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connection.id)
        )
    ).scalars().one()
    assert tombstone.lifecycle_status == "removed"
    assert tombstone.access_token_ciphertext is None
    assert tombstone.access_token_nonce is None
    assert tombstone.removed_at is not None


async def test_disconnect_allows_reconnecting_the_same_institution(
    connection_service: ConnectionService, owner, fake_plaid
) -> None:
    connection = await connection_service.exchange_public_token(
        owner, "citi", "public-6", "ins_5", "Citi"
    )
    await connection_service.disconnect(owner, connection.id)

    result = await connection_service.create_link_token(owner, "citi")

    assert result.link_token.startswith("link-sandbox-new")


async def test_list_connections_reports_every_supported_bank(
    connection_service: ConnectionService, owner
) -> None:
    await connection_service.exchange_public_token(
        owner, "chase", "public-7", "ins_3", "Chase"
    )

    summary = await connection_service.list_connections(owner)

    assert [bank.bank for bank in summary.banks] == [
        "capital-one",
        "chase",
        "citi",
        "wells-fargo",
    ]
    chase = next(bank for bank in summary.banks if bank.bank == "chase")
    assert chase.connected is True
    assert chase.card_count == 2
    capital_one = next(bank for bank in summary.banks if bank.bank == "capital-one")
    assert capital_one.connected is False


async def test_non_credit_accounts_never_become_cards(
    connection_service: ConnectionService, owner, fake_plaid, db_session
) -> None:
    fake_plaid.accounts_by_token = {}
    original = fake_plaid.get_accounts

    def only_checking(access_token: str):
        from tests.fakes.plaid import checking

        return [checking("acct-only-checking"), credit_card("acct-c", "Savor", "1111")]

    fake_plaid.get_accounts = only_checking  # type: ignore[method-assign]
    try:
        connection = await connection_service.exchange_public_token(
            owner, "citi", "public-8", "ins_5", "Citi"
        )
    finally:
        fake_plaid.get_accounts = original  # type: ignore[method-assign]

    cards = (
        await db_session.execute(
            select(CardAccount).where(CardAccount.connection_id == connection.id)
        )
    ).scalars().all()
    assert [card.plaid_account_id for card in cards] == ["acct-c"]
