from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.get_main_option("sqlalchemy.url")
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url.replace("sqlite+aiosqlite://", "sqlite+pysqlite://")
    return override


# The FTS5 index and its shadow tables are created by raw DDL in migration
# 0002, so autogenerate must not try to drop them as "unknown" tables.
IGNORED_TABLE_PREFIXES = ("transactions_fts", "sqlite_")


def include_name(name, type_, parent_names) -> bool:  # type: ignore[no-untyped-def]
    if type_ == "table" and name:
        return not name.startswith(IGNORED_TABLE_PREFIXES)
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        user_module_prefix="app.models.",
        include_name=include_name,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            user_module_prefix="app.models.",
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
