from __future__ import annotations

import sqlite3


def _objects(path: str, kind: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type=?", (kind,)
            )
        }
    finally:
        connection.close()


def test_search_index_and_triggers_exist(migrated_sqlite_path: str) -> None:
    assert "transactions_fts" in _objects(migrated_sqlite_path, "table")
    assert {
        "transactions_fts_insert",
        "transactions_fts_update",
        "transactions_fts_delete",
    } <= _objects(migrated_sqlite_path, "trigger")


def test_index_uses_the_trigram_tokenizer(migrated_sqlite_path: str) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='transactions_fts'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert "trigram" in sql
    assert "content='transactions'" in sql


def test_triggers_keep_the_index_in_step(
    migrated_sqlite_path: str, seeded_card: dict[str, str]
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    columns = (
        "id, plaid_transaction_id, card_account_id, posted_date, merchant_name, "
        "name, original_description, amount_cents, currency_code, pending, "
        "search_text, created_at, updated_at"
    )
    row = (
        "txn-fts-1",
        "plaid-fts-1",
        seeded_card["card_id"],
        "2026-08-12",
        "Paze · Urban Market",
        "Paze Urban Market",
        "PAZE*URBAN MARKET",
        6418,
        "USD",
        0,
        "paze · urban market paze urban market paze*urban market",
        "2026-08-12T00:00:00+00:00",
        "2026-08-12T00:00:00+00:00",
    )
    try:
        connection.execute(
            f"INSERT INTO transactions ({columns}) VALUES ({', '.join(['?'] * len(row))})",
            row,
        )
        connection.commit()

        found = connection.execute(
            "SELECT count(*) FROM transactions_fts WHERE transactions_fts MATCH ?",
            ('"paze"',),
        ).fetchone()[0]
        assert found == 1

        connection.execute(
            "UPDATE transactions SET search_text = 'renamed only', "
            "merchant_name = 'Renamed', name = 'Renamed', "
            "original_description = 'RENAMED' WHERE id = 'txn-fts-1'"
        )
        connection.commit()
        after_update = connection.execute(
            "SELECT count(*) FROM transactions_fts WHERE transactions_fts MATCH ?",
            ('"paze"',),
        ).fetchone()[0]
        assert after_update == 0

        connection.execute("DELETE FROM transactions WHERE id = 'txn-fts-1'")
        connection.commit()
        after_delete = connection.execute(
            "SELECT count(*) FROM transactions_fts"
        ).fetchone()[0]
        assert after_delete == 0
    finally:
        connection.close()
