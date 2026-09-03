"""clear unsafe historical card masks

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_safe_last_four(mask: object) -> bool:
    return (
        isinstance(mask, str)
        and len(mask) == 4
        and mask.isascii()
        and mask.isdecimal()
    )


def upgrade() -> None:
    """Clear historical values that violate the current last-four-only rule."""

    card_accounts = sa.table(
        "card_accounts",
        sa.column("id", sa.String),
        sa.column("mask", sa.String),
    )
    bind = op.get_bind()
    unsafe_ids = [
        card_id
        for card_id, mask in bind.execute(
            sa.select(card_accounts.c.id, card_accounts.c.mask).where(
                card_accounts.c.mask.is_not(None)
            )
        )
        if not _is_safe_last_four(mask)
    ]
    if unsafe_ids:
        bind.execute(
            card_accounts.update()
            .where(card_accounts.c.id.in_(unsafe_ids))
            .values(mask=None)
        )


def downgrade() -> None:
    # Clearing unsafe data is intentionally irreversible.
    pass
