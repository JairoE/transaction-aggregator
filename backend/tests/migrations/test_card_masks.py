from __future__ import annotations

import sqlite3

from alembic import command

from tests.conftest import alembic_config


NOW = "2026-09-01T00:00:00+00:00"


def test_card_mask_migration_clears_unsafe_historical_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "historical-card-masks.db"
    config = alembic_config(f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "0005")

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO owners (id, email, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner-1", "owner@example.com", "hash", NOW, NOW),
        )
        connection.execute(
            "INSERT INTO bank_connections "
            "(id, owner_id, bank_slug, institution_id, institution_name, "
            "plaid_item_id, plaid_environment, lifecycle_status, "
            "refresh_supported, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "connection-1",
                "owner-1",
                "chase",
                "institution-1",
                "Chase",
                "item-1",
                "sandbox",
                "active",
                1,
                NOW,
                NOW,
            ),
        )
        for index, mask in enumerate(
            ["4812", "4111111111111111", "123", "12A4", "１２３４"]
        ):
            connection.execute(
                "INSERT INTO card_accounts "
                "(id, connection_id, plaid_account_id, name, mask, is_active, "
                "display_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"card-{index}",
                    "connection-1",
                    f"account-{index}",
                    f"Card {index}",
                    mask,
                    1,
                    index,
                    NOW,
                    NOW,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(path)
    try:
        masks = dict(connection.execute("SELECT id, mask FROM card_accounts"))
    finally:
        connection.close()

    assert masks == {
        "card-0": "4812",
        "card-1": None,
        "card-2": None,
        "card-3": None,
        "card-4": None,
    }
