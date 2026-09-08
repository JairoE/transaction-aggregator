"""net-total transaction limitation alerts

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METRIC_THRESHOLD_CHECK = """
(metric = 'count' AND total_threshold_cents IS NULL)
OR (
  metric = 'net_total_usd'
  AND total_threshold_cents BETWEEN 1 AND 2147483647
)
"""


def upgrade() -> None:
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "metric",
                sa.String(length=16),
                nullable=False,
                server_default="count",
            )
        )
        batch_op.add_column(
            sa.Column("total_threshold_cents", sa.Integer(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_limitation_metric_threshold", METRIC_THRESHOLD_CHECK
        )


def downgrade() -> None:
    bind = op.get_bind()
    total_rule_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM transaction_limitations "
            "WHERE metric = 'net_total_usd'"
        )
    ).scalar_one()
    if total_rule_count:
        raise RuntimeError(
            "Convert or delete net-total transaction limitations before "
            "downgrading to 0007."
        )
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.drop_constraint("ck_limitation_metric_threshold", type_="check")
        batch_op.drop_column("total_threshold_cents")
        batch_op.drop_column("metric")
