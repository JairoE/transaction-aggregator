"""require net-total transaction limitation thresholds

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METRIC_THRESHOLD_CHECK = """
(metric = 'count' AND total_threshold_cents IS NULL)
OR (
  metric = 'net_total_usd'
  AND total_threshold_cents IS NOT NULL
  AND total_threshold_cents BETWEEN 1 AND 2147483647
)
"""

LEGACY_METRIC_THRESHOLD_CHECK = """
(metric = 'count' AND total_threshold_cents IS NULL)
OR (
  metric = 'net_total_usd'
  AND total_threshold_cents BETWEEN 1 AND 2147483647
)
"""


def upgrade() -> None:
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.drop_constraint("ck_limitation_metric_threshold", type_="check")
        batch_op.create_check_constraint(
            "ck_limitation_metric_threshold", METRIC_THRESHOLD_CHECK
        )


def downgrade() -> None:
    with op.batch_alter_table("transaction_limitations") as batch_op:
        batch_op.drop_constraint("ck_limitation_metric_threshold", type_="check")
        batch_op.create_check_constraint(
            "ck_limitation_metric_threshold", LEGACY_METRIC_THRESHOLD_CHECK
        )
