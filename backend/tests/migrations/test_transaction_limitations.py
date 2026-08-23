from __future__ import annotations

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config


NOW = "2026-08-22T00:00:00+00:00"


def _table_names(path: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()


def _insert_rule(
    connection: sqlite3.Connection,
    *,
    window_type: str = "all_time",
    threshold: int = 10,
) -> None:
    connection.execute(
        "INSERT INTO transaction_limitations "
        "(id, owner_id, keyword, normalized_keyword, threshold, card_scope, "
        "window_type, is_enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rule-1",
            "owner-1",
            "Paze",
            "paze",
            threshold,
            "all_cards",
            window_type,
            1,
            NOW,
            NOW,
        ),
    )


def test_all_time_limitation_schema_enforces_window_and_threshold(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
) -> None:
    assert {
        "transaction_limitations",
        "transaction_limitation_cards",
    } <= _table_names(migrated_sqlite_path)

    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        _insert_rule(connection)
        connection.execute("DELETE FROM transaction_limitations")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_rule(connection, window_type="rolling")
        connection.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            _insert_rule(connection, threshold=0)
    finally:
        connection.close()


def test_rule_card_associations_are_unique_and_cascade(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _insert_rule(connection)
        pair = ("rule-1", seeded_card["card_id"])
        connection.execute(
            "INSERT INTO transaction_limitation_cards "
            "(limitation_id, card_account_id) VALUES (?, ?)",
            pair,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transaction_limitation_cards "
                "(limitation_id, card_account_id) VALUES (?, ?)",
                pair,
            )
        connection.rollback()

        _insert_rule(connection)
        connection.execute(
            "INSERT INTO transaction_limitation_cards "
            "(limitation_id, card_account_id) VALUES (?, ?)",
            pair,
        )
        connection.execute("DELETE FROM transaction_limitations WHERE id = 'rule-1'")
        remaining = connection.execute(
            "SELECT count(*) FROM transaction_limitation_cards"
        ).fetchone()[0]
        assert remaining == 0
    finally:
        connection.close()


def test_rolling_window_schema_enforces_days(
    migrated_sqlite_path: str,
    seeded_card: dict[str, str],
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        connection.execute(
            "INSERT INTO transaction_limitations "
            "(id, owner_id, keyword, normalized_keyword, threshold, card_scope, "
            "window_type, rolling_days, is_enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rolling-1", "owner-1", "Paze", "paze", 5, "all_cards", "rolling", 5, 1, NOW, NOW),
        )
        for window_type, days in (("rolling", 0), ("rolling", 731), ("rolling", None), ("all_time", 5)):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO transaction_limitations "
                    "(id, owner_id, keyword, normalized_keyword, threshold, card_scope, "
                    "window_type, rolling_days, is_enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"invalid-{window_type}-{days}", "owner-1", "Paze", "paze", 5, "all_cards", window_type, days, 1, NOW, NOW),
                )
                connection.rollback()
    finally:
        connection.close()


def test_rolling_downgrade_refuses_data_loss(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "rolling-downgrade.db"
    config = alembic_config(f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "0004")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO owners (id, email, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner-1", "owner@example.com", "hash", NOW, NOW),
        )
        connection.execute(
            "INSERT INTO transaction_limitations "
            "(id, owner_id, keyword, normalized_keyword, threshold, card_scope, "
            "window_type, rolling_days, is_enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rolling-1", "owner-1", "Paze", "paze", 5, "all_cards", "rolling", 5, 1, NOW, NOW),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="Convert or delete rolling"):
        command.downgrade(config, "0003")
