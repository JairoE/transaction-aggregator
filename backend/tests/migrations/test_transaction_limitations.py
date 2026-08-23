from __future__ import annotations

import sqlite3

import pytest


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
