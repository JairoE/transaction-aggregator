from __future__ import annotations

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config


NOW = "2026-09-03T12:00:00+00:00"
LATER = "2026-09-10T12:00:00+00:00"


def _seed_0006(path: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO owners (id, email, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner-1", "owner@example.com", "hash", NOW, NOW),
        )
        connection.execute(
            "INSERT INTO bank_connections "
            "(id, owner_id, bank_slug, institution_id, institution_name, "
            "plaid_item_id, plaid_environment, lifecycle_status, refresh_supported, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "connection-1",
                "owner-1",
                "chase",
                "ins_3",
                "Chase",
                "item-1",
                "sandbox",
                "active",
                1,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO sync_jobs "
            "(id, connection_id, trigger, state, attempts, run_after, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "active-job",
                "connection-1",
                "startup",
                "queued",
                0,
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO sync_jobs "
            "(id, connection_id, trigger, state, attempts, run_after, finished_at, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "historical-job",
                "connection-1",
                "scheduled",
                "succeeded",
                1,
                NOW,
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO sync_runs "
            "(id, connection_id, job_id, added_count, modified_count, removed_count, "
            "outcome, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "historical-run",
                "connection-1",
                "historical-job",
                0,
                0,
                0,
                "succeeded",
                NOW,
                NOW,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info('{table}')")}


def test_refresh_migration_upgrades_existing_sync_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "refresh-upgrade.db"
    config = alembic_config(f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "0006")
    _seed_0006(str(path))

    command.upgrade(config, "head")

    connection = sqlite3.connect(path)
    try:
        assert {
            "transaction_refreshes",
            "transaction_refresh_requests",
            "transaction_refresh_targets",
        } <= _table_names(connection)
        assert {"sync_requested_generation", "sync_completed_generation"} <= (
            _column_names(connection, "bank_connections")
        )
        assert {
            "target_generation",
            "lease_owner",
            "lease_token",
            "lease_expires_at",
        } <= _column_names(connection, "sync_jobs")
        assert "completed_generation" in _column_names(connection, "sync_runs")

        assert connection.execute(
            "SELECT sync_requested_generation, sync_completed_generation "
            "FROM bank_connections WHERE id = 'connection-1'"
        ).fetchone() == (1, 0)
        assert connection.execute(
            "SELECT target_generation FROM sync_jobs WHERE id = 'active-job'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT target_generation FROM sync_jobs WHERE id = 'historical-job'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT completed_generation FROM sync_runs WHERE id = 'historical-run'"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_refresh_migration_enforces_active_and_idempotency_uniqueness(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "refresh-constraints.db"
    config = alembic_config(f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "0006")
    _seed_0006(str(path))
    command.upgrade(config, "head")

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO transaction_refreshes "
            "(id, owner_id, state, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            ("refresh-1", "owner-1", "queued", NOW, LATER),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transaction_refreshes "
                "(id, owner_id, state, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("refresh-2", "owner-1", "running", NOW, LATER),
            )

        connection.execute(
            "INSERT INTO transaction_refresh_requests "
            "(id, owner_id, idempotency_key_sha256, refresh_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("request-1", "owner-1", "a" * 64, "refresh-1", NOW, LATER),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transaction_refresh_requests "
                "(id, owner_id, idempotency_key_sha256, refresh_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("request-2", "owner-1", "a" * 64, "refresh-1", NOW, LATER),
            )

        connection.execute(
            "INSERT INTO transaction_refresh_targets "
            "(id, refresh_id, connection_id, state, refresh_outcome, "
            "required_sync_generation, added_count, modified_count, removed_count, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "target-1",
                "refresh-1",
                "connection-1",
                "queued",
                "not_attempted",
                2,
                0,
                0,
                0,
                NOW,
                NOW,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transaction_refresh_targets "
                "(id, refresh_id, connection_id, state, refresh_outcome, "
                "required_sync_generation, added_count, modified_count, removed_count, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "target-2",
                    "refresh-1",
                    "connection-1",
                    "syncing",
                    "accepted",
                    2,
                    0,
                    0,
                    0,
                    NOW,
                    NOW,
                ),
            )
    finally:
        connection.close()


def test_refresh_migration_downgrades_to_0006(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "refresh-downgrade.db"
    config = alembic_config(f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "head")

    command.downgrade(config, "0006")

    connection = sqlite3.connect(path)
    try:
        assert not {
            "transaction_refreshes",
            "transaction_refresh_requests",
            "transaction_refresh_targets",
        } & _table_names(connection)
        assert "sync_requested_generation" not in _column_names(
            connection, "bank_connections"
        )
        assert "target_generation" not in _column_names(connection, "sync_jobs")
        assert "completed_generation" not in _column_names(connection, "sync_runs")
    finally:
        connection.close()
