"""SQLAlchemy models for the local transaction cache.

Kept in one module for v1 so relationships and constraints stay auditable in a
single read. Timestamps are stored as timezone-aware ISO-8601 text so raw SQL
fixtures, Alembic, and the ORM all agree on one representation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes persisted as ISO-8601 UTC text."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetimes cannot be stored; pass a timezone-aware value "
                "(app.models.utcnow) so provider timestamps are never guessed"
            )
        return value.astimezone(UTC).isoformat()

    def process_result_value(
        self, value: str | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )


class Owner(TimestampMixin, Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    plaid_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    sessions: Mapped[list[OwnerSession]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    connections: Mapped[list[BankConnection]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    transaction_limitations: Mapped[list[TransactionLimitation]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class OwnerSession(Base):
    __tablename__ = "owner_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    owner: Mapped[Owner] = relationship(back_populates="sessions")


class BankConnection(TimestampMixin, Base):
    """One Plaid Item, or a token-free tombstone for a consumed Trial slot."""

    __tablename__ = "bank_connections"
    __table_args__ = (
        Index(
            "ux_bank_connections_active_institution",
            "owner_id",
            "institution_id",
            unique=True,
            sqlite_where=text("lifecycle_status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    institution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    institution_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plaid_item_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    plaid_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )

    access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_nonce: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_token_key_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_expiration_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_provider_update_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    refresh_supported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    owner: Mapped[Owner] = relationship(back_populates="connections")
    cards: Mapped[list[CardAccount]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.lifecycle_status == "active"


class CardAccount(TimestampMixin, Base):
    __tablename__ = "card_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plaid_account_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mask: Mapped[str | None] = mapped_column(String(8), nullable=True)
    subtype: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Provider discovery order, so panels appear as the bank listed them.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    connection: Mapped[BankConnection] = relationship(back_populates="cards")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    limitation_links: Mapped[list[TransactionLimitationCard]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class TransactionLimitation(TimestampMixin, Base):
    __tablename__ = "transaction_limitations"
    __table_args__ = (
        CheckConstraint(
            "threshold BETWEEN 1 AND 10000", name="ck_limitation_threshold"
        ),
        CheckConstraint(
            "card_scope IN ('all_cards', 'selected_cards')",
            name="ck_limitation_card_scope",
        ),
        CheckConstraint(
            "(window_type = 'all_time' AND rolling_days IS NULL) OR "
            "(window_type = 'rolling' AND rolling_days IS NOT NULL "
            "AND rolling_days BETWEEN 1 AND 730)",
            name="ck_limitation_window_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    card_scope: Mapped[str] = mapped_column(String(24), nullable=False)
    window_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="all_time"
    )
    rolling_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    owner: Mapped[Owner] = relationship(back_populates="transaction_limitations")
    card_links: Mapped[list[TransactionLimitationCard]] = relationship(
        back_populates="limitation", cascade="all, delete-orphan"
    )


class TransactionLimitationCard(Base):
    __tablename__ = "transaction_limitation_cards"

    limitation_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_limitations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    card_account_id: Mapped[str] = mapped_column(
        ForeignKey("card_accounts.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    limitation: Mapped[TransactionLimitation] = relationship(back_populates="card_links")
    card: Mapped[CardAccount] = relationship(back_populates="limitation_links")


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_card_posted", "card_account_id", "posted_date"),
        Index("ix_transactions_search_text", "search_text"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plaid_transaction_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    card_account_id: Mapped[str] = mapped_column(
        ForeignKey("card_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    authorized_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    original_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    card: Mapped[CardAccount] = relationship(back_populates="transactions")


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index(
            "ux_sync_jobs_active_connection",
            "connection_id",
            unique=True,
            sqlite_where=text("state IN ('queued', 'running')"),
        ),
        Index("ix_sync_jobs_state_run_after", "state", "run_after"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_after: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    starting_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    ending_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    modified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plaid_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"
    __table_args__ = (UniqueConstraint("payload_sha256", name="ux_webhook_payload"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    webhook_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    webhook_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plaid_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


__all__ = [
    "Base",
    "BankConnection",
    "CardAccount",
    "Owner",
    "OwnerSession",
    "SyncJob",
    "SyncRun",
    "Transaction",
    "TransactionLimitation",
    "TransactionLimitationCard",
    "UtcDateTime",
    "WebhookReceipt",
    "new_id",
    "utcnow",
]
