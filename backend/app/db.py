"""SQLite engine and session management with WAL mode enabled."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models import Base


@dataclass
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def verify_fts5_trigram(self) -> None:
        """Fail closed when SQLite lacks FTS5 or the trigram tokenizer."""

        async with self.engine.begin() as connection:
            try:
                await connection.execute(
                    text(
                        "CREATE VIRTUAL TABLE temp.fts5_probe "
                        "USING fts5(probe, tokenize='trigram')"
                    )
                )
                await connection.execute(text("DROP TABLE temp.fts5_probe"))
            except Exception as error:  # pragma: no cover - environment guard
                raise RuntimeError(
                    "SQLite must be compiled with FTS5 and the trigram tokenizer. "
                    "Install a Python build linked against SQLite 3.34+ with FTS5."
                ) from error

    async def dispose(self) -> None:
        await self.engine.dispose()


def _sqlite_file_path(database_url: str) -> Path | None:
    marker = "sqlite+aiosqlite:///"
    if not database_url.startswith(marker):
        return None
    raw = database_url[len(marker) :]
    if not raw or raw == ":memory:":
        return None
    return Path(raw).expanduser()


def create_database(settings: Settings) -> Database:
    path = _sqlite_file_path(settings.database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:  # pragma: no cover - non-POSIX filesystems
            pass

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    if path is not None and path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - non-POSIX filesystems
            pass

    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    return Database(engine=engine, session_factory=session_factory)


__all__ = ["Database", "create_database"]
