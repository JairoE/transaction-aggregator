"""fixed transaction limitation windows

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WINDOW_CHECK = """
(
  window_type = 'all_time'
  AND rolling_days IS NULL
  AND start_date IS NULL
  AND end_date IS NULL
)
OR (
  window_type = 'rolling'
  AND rolling_days IS NOT NULL
  AND rolling_days BETWEEN 1 AND 730
  AND start_date IS NULL
  AND end_date IS NULL
)
OR (
  window_type = 'fixed'
  AND rolling_days IS NULL
  AND start_date IS NOT NULL
  AND end_date IS NOT NULL
  AND start_date <= end_date
)
"""


def upgrade() -> None:
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("end_date", sa.Date(), nullable=True))
        batch_op.drop_constraint("ck_limitation_window_type", type_="check")
        batch_op.create_check_constraint("ck_limitation_window_type", WINDOW_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    fixed_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM transaction_limitations "
            "WHERE window_type = 'fixed'"
        )
    ).scalar_one()
    if fixed_count:
        raise RuntimeError(
            "Convert or delete fixed transaction limitations before "
            "downgrading to 0004."
        )
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.drop_constraint("ck_limitation_window_type", type_="check")
        batch_op.drop_column("end_date")
        batch_op.drop_column("start_date")
        batch_op.create_check_constraint(
            "ck_limitation_window_type",
            "(window_type = 'all_time' AND rolling_days IS NULL) OR "
            "(window_type = 'rolling' AND rolling_days IS NOT NULL "
            "AND rolling_days BETWEEN 1 AND 730)",
        )
