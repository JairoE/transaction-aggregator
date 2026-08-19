from __future__ import annotations

import os
from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator, Iterator
from os import urandom
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def token_encryption_key() -> str:
    return urlsafe_b64encode(urandom(32)).decode()


@pytest.fixture
def settings_env(tmp_path: Path, token_encryption_key: str) -> Iterator[dict[str, str]]:
    values = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'transactions.db'}",
        "APPLICATION_SECRET": "s" * 32,
        "TOKEN_ENCRYPTION_KEY": token_encryption_key,
        "TOKEN_ENCRYPTION_KEY_VERSION": "1",
        "PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "PLAID_CLIENT_ID": "test-client-id",
        "PLAID_SECRET": "test-plaid-secret",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield values
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def migrated_sqlite_path(tmp_path: Path) -> str:
    path = tmp_path / "migrated.db"
    command.upgrade(alembic_config(f"sqlite+pysqlite:///{path}"), "head")
    return str(path)


@pytest.fixture
def seeded_card(migrated_sqlite_path: str) -> dict[str, str]:
    import sqlite3

    now = "2026-08-01T00:00:00+00:00"
    connection = sqlite3.connect(migrated_sqlite_path)
    try:
        connection.execute(
            "INSERT INTO owners (id, email, password_hash, plaid_user_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("owner-1", "owner@example.com", "hash", "plaid-user-1", now, now),
        )
        connection.execute(
            "INSERT INTO bank_connections (id, owner_id, bank_slug, institution_id, "
            "institution_name, plaid_item_id, plaid_environment, lifecycle_status, "
            "refresh_supported, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "conn-1",
                "owner-1",
                "capital-one",
                "ins_128026",
                "Capital One",
                "item-1",
                "sandbox",
                "active",
                1,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO card_accounts (id, connection_id, plaid_account_id, name, "
            "official_name, mask, subtype, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "card-1",
                "conn-1",
                "plaid-account-1",
                "Venture",
                "Capital One Venture",
                "4812",
                "credit card",
                1,
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return {"owner_id": "owner-1", "connection_id": "conn-1", "card_id": "card-1"}


@pytest.fixture
async def db_session(settings_env: dict[str, str]) -> AsyncIterator[AsyncSession]:
    from app.config import get_settings
    from app.db import create_database

    get_settings.cache_clear()
    settings = get_settings()
    database = create_database(settings)
    await database.create_all()
    async with database.session() as session:
        yield session
    await database.dispose()
    get_settings.cache_clear()
