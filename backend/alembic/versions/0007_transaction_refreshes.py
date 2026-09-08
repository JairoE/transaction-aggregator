"""durable transaction refresh orchestration

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RUN_STATES = "'queued', 'running', 'succeeded', 'partial', 'failed'"
TARGET_STATES = (
    "'queued', 'refreshing', 'syncing', 'updated', 'no_changes', "
    "'automatic_updates_only', 'cooldown', 'reconnect_required', "
    "'outcome_unknown', 'failed', 'disconnected'"
)
ACTIVE_TARGET_STATES = "'queued', 'refreshing', 'syncing'"
ATTEMPT_STATES = (
    "'not_attempted', 'reserved', 'dispatching', 'accepted', 'unsupported', "
    "'cooldown', 'outcome_unknown', 'failed'"
)


def upgrade() -> None:
    with op.batch_alter_table("bank_connections") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sync_requested_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "sync_completed_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_bank_connections_sync_generations_nonnegative",
            "sync_requested_generation >= 0 AND sync_completed_generation >= 0",
        )
        batch_op.create_check_constraint(
            "ck_bank_connections_sync_generation_order",
            "sync_completed_generation <= sync_requested_generation",
        )

    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "target_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("lease_owner", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("lease_token", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "lease_expires_at",
                app.models.UtcDateTime(length=32),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_sync_jobs_target_generation_nonnegative",
            "target_generation >= 0",
        )
        batch_op.create_index(
            "ix_sync_jobs_state_lease_expires",
            ["state", "lease_expires_at"],
            unique=False,
        )

    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "completed_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_sync_runs_completed_generation_nonnegative",
            "completed_generation >= 0",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sync_jobs SET target_generation = 1 "
            "WHERE state IN ('queued', 'running')"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE bank_connections SET sync_requested_generation = 1 "
            "WHERE id IN (SELECT connection_id FROM sync_jobs "
            "WHERE state IN ('queued', 'running'))"
        )
    )

    op.create_table(
        "transaction_refreshes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.Column("started_at", app.models.UtcDateTime(length=32), nullable=True),
        sa.Column("finished_at", app.models.UtcDateTime(length=32), nullable=True),
        sa.Column("expires_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.CheckConstraint(
            f"state IN ({RUN_STATES})", name="ck_transaction_refreshes_state"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_refreshes_owner_created",
        "transaction_refreshes",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_transaction_refreshes_expires_at",
        "transaction_refreshes",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ux_transaction_refreshes_active_owner",
        "transaction_refreshes",
        ["owner_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued', 'running')"),
    )

    op.create_table(
        "transaction_refresh_requests",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(64), nullable=False),
        sa.Column("refresh_id", sa.String(36), nullable=False),
        sa.Column("created_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.Column("expires_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["refresh_id"], ["transaction_refreshes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key_sha256",
            name="ux_transaction_refresh_requests_owner_key",
        ),
    )
    op.create_index(
        "ix_transaction_refresh_requests_refresh_id",
        "transaction_refresh_requests",
        ["refresh_id"],
        unique=False,
    )
    op.create_index(
        "ix_transaction_refresh_requests_expires_at",
        "transaction_refresh_requests",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "transaction_refresh_targets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("refresh_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("refresh_outcome", sa.String(32), nullable=False),
        sa.Column("required_sync_generation", sa.Integer(), nullable=False),
        sa.Column("provider_request_id", sa.String(64), nullable=True),
        sa.Column(
            "next_refresh_eligible_at",
            app.models.UtcDateTime(length=32),
            nullable=True,
        ),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("modified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("removed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("started_at", app.models.UtcDateTime(length=32), nullable=True),
        sa.Column("finished_at", app.models.UtcDateTime(length=32), nullable=True),
        sa.Column("created_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.Column("updated_at", app.models.UtcDateTime(length=32), nullable=False),
        sa.CheckConstraint(
            f"state IN ({TARGET_STATES})", name="ck_transaction_refresh_targets_state"
        ),
        sa.CheckConstraint(
            f"refresh_outcome IN ({ATTEMPT_STATES})",
            name="ck_transaction_refresh_targets_outcome",
        ),
        sa.CheckConstraint(
            "required_sync_generation >= 0",
            name="ck_transaction_refresh_targets_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "added_count >= 0 AND modified_count >= 0 AND removed_count >= 0",
            name="ck_transaction_refresh_targets_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["refresh_id"], ["transaction_refreshes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["bank_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "refresh_id",
            "connection_id",
            name="ux_transaction_refresh_targets_refresh_connection",
        ),
    )
    op.create_index(
        "ix_transaction_refresh_targets_refresh_id",
        "transaction_refresh_targets",
        ["refresh_id"],
        unique=False,
    )
    op.create_index(
        "ix_transaction_refresh_targets_connection_id",
        "transaction_refresh_targets",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        "ux_transaction_refresh_targets_active_connection",
        "transaction_refresh_targets",
        ["connection_id"],
        unique=True,
        sqlite_where=sa.text(f"state IN ({ACTIVE_TARGET_STATES})"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_transaction_refresh_targets_active_connection",
        table_name="transaction_refresh_targets",
    )
    op.drop_index(
        "ix_transaction_refresh_targets_connection_id",
        table_name="transaction_refresh_targets",
    )
    op.drop_index(
        "ix_transaction_refresh_targets_refresh_id",
        table_name="transaction_refresh_targets",
    )
    op.drop_table("transaction_refresh_targets")

    op.drop_index(
        "ix_transaction_refresh_requests_expires_at",
        table_name="transaction_refresh_requests",
    )
    op.drop_index(
        "ix_transaction_refresh_requests_refresh_id",
        table_name="transaction_refresh_requests",
    )
    op.drop_table("transaction_refresh_requests")

    op.drop_index(
        "ux_transaction_refreshes_active_owner", table_name="transaction_refreshes"
    )
    op.drop_index(
        "ix_transaction_refreshes_expires_at", table_name="transaction_refreshes"
    )
    op.drop_index(
        "ix_transaction_refreshes_owner_created", table_name="transaction_refreshes"
    )
    op.drop_table("transaction_refreshes")

    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.drop_constraint(
            "ck_sync_runs_completed_generation_nonnegative", type_="check"
        )
        batch_op.drop_column("completed_generation")

    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.drop_index("ix_sync_jobs_state_lease_expires")
        batch_op.drop_constraint(
            "ck_sync_jobs_target_generation_nonnegative", type_="check"
        )
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_token")
        batch_op.drop_column("lease_owner")
        batch_op.drop_column("target_generation")

    with op.batch_alter_table("bank_connections") as batch_op:
        batch_op.drop_constraint(
            "ck_bank_connections_sync_generation_order", type_="check"
        )
        batch_op.drop_constraint(
            "ck_bank_connections_sync_generations_nonnegative", type_="check"
        )
        batch_op.drop_column("sync_completed_generation")
        batch_op.drop_column("sync_requested_generation")
