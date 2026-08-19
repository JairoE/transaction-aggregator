from __future__ import annotations

import os
from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator, Iterator
from os import urandom
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
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
async def db_session(database) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


@pytest.fixture
async def database(settings_env: dict[str, str]):
    from app.config import get_settings
    from app.db import create_database

    get_settings.cache_clear()
    settings = get_settings()
    database = create_database(settings)
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()
        get_settings.cache_clear()


@pytest.fixture
async def app(database, fake_plaid):
    from app.config import get_settings
    from app.main import create_app

    return create_app(
        settings=get_settings(), database=database, plaid_gateway=fake_plaid
    )


@pytest.fixture
async def client(app) -> AsyncIterator["AsyncClient"]:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    ) as http_client:
        yield http_client


@pytest.fixture
async def owner(database):
    from app.services import auth as auth_service

    async with database.session() as session:
        created = await auth_service.create_owner(
            session, "owner@example.com", "correct horse battery staple"
        )
        await session.commit()
        await session.refresh(created)
        return created


@pytest.fixture
async def login_response(client, owner):
    response = await client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
async def authenticated_client(client, login_response):
    return client


@pytest.fixture
async def csrf_token(login_response) -> str:
    return login_response.json()["csrf_token"]


@pytest.fixture
def fake_plaid():
    from tests.fakes.plaid import FakePlaidGateway

    return FakePlaidGateway()


@pytest.fixture
def token_cipher(settings_env: dict[str, str]):
    from app.services.crypto import TokenCipher

    return TokenCipher.from_base64_key(settings_env["TOKEN_ENCRYPTION_KEY"], 1)


@pytest.fixture
async def connection_service(db_session, fake_plaid, token_cipher):
    from app.config import get_settings
    from app.services.connection_service import ConnectionService

    get_settings.cache_clear()
    return ConnectionService(db_session, get_settings(), fake_plaid, token_cipher)


@pytest.fixture
async def production_connection_service(db_session, fake_plaid, token_cipher):
    from app.config import Settings
    from app.services.connection_service import ConnectionService

    settings = Settings(
        environment="production",
        database_url="sqlite+aiosqlite:///:memory:",
        application_secret="s" * 32,
        token_encryption_key="k" * 43,
        public_base_url="https://aggregator.example.com",
        plaid_client_id="client",
        plaid_secret="secret",
    )
    return ConnectionService(db_session, settings, fake_plaid, token_cipher)


@pytest.fixture
async def db_session_factory(database):
    return database.session


@pytest.fixture
async def seed_production_tombstones(db_session):
    from app.models import BankConnection, utcnow

    async def _seed(owner_id: str, count: int) -> None:
        for index in range(count):
            db_session.add(
                BankConnection(
                    owner_id=owner_id,
                    bank_slug="chase",
                    institution_id=f"ins_seed_{index}",
                    institution_name="Seeded",
                    plaid_item_id=f"item-seed-{index}",
                    plaid_environment="production",
                    lifecycle_status="removed",
                    removed_at=utcnow(),
                )
            )
        await db_session.flush()

    return _seed
