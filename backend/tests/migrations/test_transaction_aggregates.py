from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from tests.conftest import alembic_config


NOW = "2026-09-08T00:00:00+00:00"


def _insert_aggregate(
    connection: sqlite3.Connection,
    *,
    aggregate_id: str = "aggregate-1",
    card_scope: str = "all_cards",
) -> None:
    connection.execute(
        "INSERT INTO transaction_aggregates "
        "(id, owner_id, keyword, normalized_keyword, card_scope, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (aggregate_id, "owner-1", "Paze", "paze", card_scope, NOW, NOW),
    )


def test_transaction_aggregate_schema_accepts_supported_card_scopes(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        _insert_aggregate(connection)
        _insert_aggregate(
            connection,
            aggregate_id="aggregate-2",
            card_scope="selected_cards",
        )
        connection.execute(
            "INSERT INTO transaction_aggregate_cards "
            "(aggregate_id, card_account_id) VALUES (?, ?)",
            ("aggregate-2", seeded_card["card_id"]),
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE transaction_aggregates SET card_scope = 'unknown' "
                "WHERE id = 'aggregate-1'"
            )
    finally:
        connection.close()


def test_transaction_aggregate_card_pairs_are_unique(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        _insert_aggregate(connection, card_scope="selected_cards")
        pair = ("aggregate-1", seeded_card["card_id"])
        connection.execute(
            "INSERT INTO transaction_aggregate_cards "
            "(aggregate_id, card_account_id) VALUES (?, ?)",
            pair,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transaction_aggregate_cards "
                "(aggregate_id, card_account_id) VALUES (?, ?)",
                pair,
            )
    finally:
        connection.close()


@pytest.mark.parametrize("deleted_resource", ["aggregate", "card", "owner"])
def test_transaction_aggregate_links_cascade(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
    deleted_resource: str,
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _insert_aggregate(connection, card_scope="selected_cards")
        connection.execute(
            "INSERT INTO transaction_aggregate_cards "
            "(aggregate_id, card_account_id) VALUES (?, ?)",
            ("aggregate-1", seeded_card["card_id"]),
        )
        if deleted_resource == "aggregate":
            connection.execute(
                "DELETE FROM transaction_aggregates WHERE id = 'aggregate-1'"
            )
        elif deleted_resource == "card":
            connection.execute(
                "DELETE FROM card_accounts WHERE id = ?",
                (seeded_card["card_id"],),
            )
        else:
            connection.execute(
                "DELETE FROM owners WHERE id = ?",
                (seeded_card["owner_id"],),
            )

        assert connection.execute(
            "SELECT count(*) FROM transaction_aggregate_cards"
        ).fetchone()[0] == 0
        if deleted_resource == "owner":
            assert connection.execute(
                "SELECT count(*) FROM transaction_aggregates"
            ).fetchone()[0] == 0
    finally:
        connection.close()


def test_transaction_aggregate_migration_can_downgrade_and_upgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "aggregate-downgrade.sqlite3"
    config = alembic_config(f"sqlite+pysqlite:///{path}")

    command.upgrade(config, "head")
    command.downgrade(config, "0009")

    connection = sqlite3.connect(path)
    try:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "transaction_aggregates" not in table_names
        assert "transaction_aggregate_cards" not in table_names
    finally:
        connection.close()

    command.upgrade(config, "head")
