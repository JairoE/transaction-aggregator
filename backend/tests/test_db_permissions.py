"""SEC-011: the local database must never be readable by other accounts."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from app.config import Settings
from app.db import create_database
from app.models import UtcDateTime, utcnow


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'nested' / 'transactions.db'}",
        application_secret="s" * 32,
        token_encryption_key="k" * 43,
        public_base_url="http://127.0.0.1:8000",
        plaid_client_id="client",
        plaid_secret="secret",
    )


async def test_new_database_file_is_owner_only(tmp_path: Path) -> None:
    database = create_database(_settings(tmp_path))
    try:
        await database.create_all()
    finally:
        await database.dispose()

    path = tmp_path / "nested" / "transactions.db"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "nested").stat().st_mode) == 0o700


def test_naive_datetimes_are_refused() -> None:
    from datetime import datetime

    with pytest.raises(ValueError):
        UtcDateTime().process_bind_param(datetime(2026, 8, 19, 3, 0, 0), None)

    assert UtcDateTime().process_bind_param(utcnow(), None) is not None
