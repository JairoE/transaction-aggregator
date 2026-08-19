import sqlite3

import pytest
from sqlalchemy import inspect

from app.models import Base

CORE_TABLES = {
    "owners",
    "owner_sessions",
    "bank_connections",
    "card_accounts",
    "transactions",
    "sync_jobs",
    "sync_runs",
    "webhook_receipts",
}


def test_migration_creates_every_core_table(migrated_sqlite_path: str) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()

    assert CORE_TABLES <= names


def test_models_and_migration_declare_the_same_tables(
    migrated_sqlite_path: str,
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()

    declared = set(Base.metadata.tables)

    assert declared <= names


def test_plaid_transaction_id_is_unique(migrated_sqlite_path: str) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='transactions'"
            )
        }
        unique_columns: set[str] = set()
        for index in indexes:
            info = list(connection.execute(f"PRAGMA index_info('{index}')"))
            is_unique = next(
                row[2]
                for row in connection.execute("PRAGMA index_list('transactions')")
                if row[1] == index
            )
            if is_unique and len(info) == 1:
                unique_columns.add(info[0][2])
    finally:
        connection.close()

    assert "plaid_transaction_id" in unique_columns


def test_duplicate_plaid_transaction_id_raises(
    migrated_sqlite_path: str, seeded_card: dict[str, str]
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    connection.execute("PRAGMA foreign_keys = ON")
    row = (
        "txn-1",
        "plaid-txn-1",
        seeded_card["card_id"],
        "2026-08-01",
        "2026-08-01",
        "Urban Market",
        "PAZE*URBAN MARKET",
        "PAZE*URBAN MARKET",
        6418,
        "USD",
        0,
        "urban market paze*urban market",
        "2026-08-01T00:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
    )
    columns = (
        "id, plaid_transaction_id, card_account_id, authorized_date, posted_date, "
        "merchant_name, name, original_description, amount_cents, currency_code, "
        "pending, search_text, created_at, updated_at"
    )
    placeholders = ", ".join(["?"] * len(row))
    try:
        connection.execute(
            f"INSERT INTO transactions ({columns}) VALUES ({placeholders})", row
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO transactions ({columns}) VALUES ({placeholders})",
                ("txn-2",) + row[1:],
            )
            connection.commit()
    finally:
        connection.close()


def test_only_one_active_sync_job_per_connection(
    migrated_sqlite_path: str, seeded_card: dict[str, str]
) -> None:
    connection = sqlite3.connect(migrated_sqlite_path)
    columns = (
        "id, connection_id, trigger, state, attempts, run_after, created_at, updated_at"
    )
    try:
        connection.execute(
            f"INSERT INTO sync_jobs ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job-1",
                seeded_card["connection_id"],
                "initial",
                "queued",
                0,
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO sync_jobs ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "job-2",
                    seeded_card["connection_id"],
                    "manual",
                    "running",
                    0,
                    "2026-08-01T00:00:00+00:00",
                    "2026-08-01T00:00:00+00:00",
                    "2026-08-01T00:00:00+00:00",
                ),
            )
            connection.commit()

        connection.execute(
            f"INSERT INTO sync_jobs ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job-3",
                seeded_card["connection_id"],
                "manual",
                "succeeded",
                1,
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_removed_connection_keeps_tombstone_columns(
    migrated_sqlite_path: str,
) -> None:
    inspector_columns = {
        column["name"] for column in _columns(migrated_sqlite_path, "bank_connections")
    }

    assert {
        "lifecycle_status",
        "removed_at",
        "access_token_ciphertext",
        "access_token_nonce",
        "access_token_key_version",
        "plaid_environment",
    } <= inspector_columns


def _columns(path: str, table: str) -> list[dict[str, object]]:
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite+pysqlite:///{path}")
    try:
        return inspect(engine).get_columns(table)
    finally:
        engine.dispose()
