"""all-time transaction limitations

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_limitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=100), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("card_scope", sa.String(length=24), nullable=False),
        sa.Column("window_type", sa.String(length=16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.Column("updated_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.CheckConstraint(
            "threshold BETWEEN 1 AND 10000", name="ck_limitation_threshold"
        ),
        sa.CheckConstraint(
            "card_scope IN ('all_cards', 'selected_cards')",
            name="ck_limitation_card_scope",
        ),
        sa.CheckConstraint(
            "window_type = 'all_time'", name="ck_limitation_window_type"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_limitations_owner_id",
        "transaction_limitations",
        ["owner_id"],
    )
    op.create_table(
        "transaction_limitation_cards",
        sa.Column("limitation_id", sa.String(length=36), nullable=False),
        sa.Column("card_account_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["limitation_id"], ["transaction_limitations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["card_account_id"], ["card_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("limitation_id", "card_account_id"),
    )
    op.create_index(
        "ix_transaction_limitation_cards_card_id",
        "transaction_limitation_cards",
        ["card_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_limitation_cards_card_id",
        table_name="transaction_limitation_cards",
    )
    op.drop_table("transaction_limitation_cards")
    op.drop_index(
        "ix_transaction_limitations_owner_id", table_name="transaction_limitations"
    )
    op.drop_table("transaction_limitations")
