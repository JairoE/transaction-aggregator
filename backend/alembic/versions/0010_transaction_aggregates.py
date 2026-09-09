"""saved transaction aggregate definitions

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_aggregates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=100), nullable=False),
        sa.Column("card_scope", sa.String(length=24), nullable=False),
        sa.Column("created_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.Column("updated_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.CheckConstraint(
            "card_scope IN ('all_cards', 'selected_cards')",
            name="ck_transaction_aggregate_card_scope",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_aggregates_owner_id",
        "transaction_aggregates",
        ["owner_id"],
    )
    op.create_table(
        "transaction_aggregate_cards",
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("card_account_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["aggregate_id"], ["transaction_aggregates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["card_account_id"], ["card_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("aggregate_id", "card_account_id"),
    )
    op.create_index(
        "ix_transaction_aggregate_cards_card_id",
        "transaction_aggregate_cards",
        ["card_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_aggregate_cards_card_id",
        table_name="transaction_aggregate_cards",
    )
    op.drop_table("transaction_aggregate_cards")
    op.drop_index(
        "ix_transaction_aggregates_owner_id", table_name="transaction_aggregates"
    )
    op.drop_table("transaction_aggregates")
