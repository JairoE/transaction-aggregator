"""rolling transaction limitation windows

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WINDOW_CHECK = """
(window_type = 'all_time' AND rolling_days IS NULL)
OR (
  window_type = 'rolling'
  AND rolling_days IS NOT NULL
  AND rolling_days BETWEEN 1 AND 730
)
"""


def upgrade() -> None:
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.add_column(sa.Column("rolling_days", sa.Integer(), nullable=True))
        batch_op.drop_constraint("ck_limitation_window_type", type_="check")
        batch_op.create_check_constraint("ck_limitation_window_type", WINDOW_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    rolling_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM transaction_limitations "
            "WHERE window_type = 'rolling'"
        )
    ).scalar_one()
    if rolling_count:
        raise RuntimeError(
            "Convert or delete rolling transaction limitations before "
            "downgrading to 0003."
        )
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.drop_constraint("ck_limitation_window_type", type_="check")
        batch_op.drop_column("rolling_days")
        batch_op.create_check_constraint(
            "ck_limitation_window_type", "window_type = 'all_time'"
        )
