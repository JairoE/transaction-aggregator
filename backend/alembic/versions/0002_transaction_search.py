"""transaction search index

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

Adds an external-content FTS5 table over `transactions` using the trigram
tokenizer so arbitrary substring search stays indexed, plus triggers that keep
it in step with inserts, updates, and deletes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FTS_COLUMNS = "merchant_name, name, original_description, search_text"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE VIRTUAL TABLE transactions_fts USING fts5(
            {FTS_COLUMNS},
            content='transactions',
            content_rowid='rowid',
            tokenize='trigram'
        )
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER transactions_fts_insert AFTER INSERT ON transactions BEGIN
            INSERT INTO transactions_fts(rowid, {FTS_COLUMNS})
            VALUES (
                new.rowid,
                new.merchant_name,
                new.name,
                new.original_description,
                new.search_text
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER transactions_fts_delete AFTER DELETE ON transactions BEGIN
            INSERT INTO transactions_fts(transactions_fts, rowid, {FTS_COLUMNS})
            VALUES (
                'delete',
                old.rowid,
                old.merchant_name,
                old.name,
                old.original_description,
                old.search_text
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER transactions_fts_update AFTER UPDATE ON transactions BEGIN
            INSERT INTO transactions_fts(transactions_fts, rowid, {FTS_COLUMNS})
            VALUES (
                'delete',
                old.rowid,
                old.merchant_name,
                old.name,
                old.original_description,
                old.search_text
            );
            INSERT INTO transactions_fts(rowid, {FTS_COLUMNS})
            VALUES (
                new.rowid,
                new.merchant_name,
                new.name,
                new.original_description,
                new.search_text
            );
        END
        """
    )
    op.execute("INSERT INTO transactions_fts(transactions_fts) VALUES ('rebuild')")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS transactions_fts_update")
    op.execute("DROP TRIGGER IF EXISTS transactions_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS transactions_fts_insert")
    op.execute("DROP TABLE IF EXISTS transactions_fts")
