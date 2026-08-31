"""Wire contracts shared by every API route."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, EmailStr, Field, model_validator

BankSlug = Literal["capital-one", "chase", "citi", "wells-fargo"]


class ErrorResponse(BaseModel):
    code: str
    message: str


class OwnerResponse(BaseModel):
    id: str
    email: str


class SessionResponse(BaseModel):
    owner: OwnerResponse
    csrf_token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class CreateLinkTokenRequest(BaseModel):
    bank: BankSlug
    confirm_trial_slot: bool = False


class ExchangePublicTokenRequest(BaseModel):
    bank: BankSlug
    public_token: str = Field(min_length=1, max_length=512)
    institution_id: str = Field(min_length=1, max_length=64)
    institution_name: str = Field(min_length=1, max_length=128)


class LinkTokenResponse(BaseModel):
    link_token: str
    bank: str
    mode: Literal["new", "update"]
    consumes_trial_slot: bool
    production_item_count: int
    production_item_limit: int


class BankConnectionResponse(BaseModel):
    bank: BankSlug
    display_name: str
    connected: bool
    connection_id: str | None
    institution_name: str | None
    card_count: int
    lifecycle_status: str
    state: str = "disconnected"
    action: str = "none"
    message: str = "Not connected."
    cache_as_of: datetime | None = None
    last_successful_sync_at: datetime | None
    last_provider_update_at: datetime | None
    consent_expiration_at: datetime | None
    last_error_code: str | None
    refresh_supported: bool


class ConnectionsResponse(BaseModel):
    banks: list[BankConnectionResponse]
    production_item_count: int
    production_item_limit: int
    environment: str
    uses_demo_bank: bool


class CardResponse(BaseModel):
    id: str
    connection_id: str
    bank: BankSlug
    bank_display_name: str
    name: str
    official_name: str | None
    mask: str | None
    state: str = "ready"
    last_successful_sync_at: datetime | None = None


class ExchangeResponse(BaseModel):
    connection_id: str
    bank: BankSlug
    institution_name: str
    card_count: int
    sync_job_id: str | None


class TransactionMatch(BaseModel):
    id: str
    card_id: str
    merchant_name: str | None
    description: str
    original_description: str | None
    category: str | None
    amount_cents: int
    currency_code: str
    authorized_date: date | None
    posted_date: date | None
    pending: bool


class AllTransactionRow(BaseModel):
    transaction: TransactionMatch
    card: CardResponse


class AllTransactionsResponse(BaseModel):
    query: str
    total_matches: int
    card_count: int
    bank_count: int
    rows: list[AllTransactionRow]
    next_cursor: str | None
    has_more: bool
    cache_as_of: datetime | None


class CardTransactionGroup(BaseModel):
    card: CardResponse
    transactions: list[TransactionMatch]
    match_count: int
    next_cursor: str | None
    has_more: bool


class GroupedSearchResponse(BaseModel):
    query: str
    total_matches: int
    card_count: int
    groups: list[CardTransactionGroup]
    cache_as_of: datetime | None


class AllTimeWindow(BaseModel):
    type: Literal["all_time"]


class RollingWindow(BaseModel):
    type: Literal["rolling"]
    days: int = Field(ge=1, le=730)


class FixedWindow(BaseModel):
    type: Literal["fixed"]
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


TransactionWindow = Annotated[
    AllTimeWindow | RollingWindow | FixedWindow,
    Field(discriminator="type"),
]


class CreateTransactionLimitationRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    threshold: int = Field(ge=1, le=10_000)
    card_scope: Literal["all_cards", "selected_cards"]
    card_ids: list[str] = Field(default_factory=list, max_length=100)
    window: TransactionWindow
    is_enabled: bool = True


class UpdateTransactionLimitationRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=100)
    threshold: int | None = Field(default=None, ge=1, le=10_000)
    card_scope: Literal["all_cards", "selected_cards"] | None = None
    card_ids: list[str] | None = Field(default=None, max_length=100)
    window: TransactionWindow | None = None
    is_enabled: bool | None = None


class TransactionLimitationResponse(BaseModel):
    id: str
    keyword: str
    threshold: int
    card_scope: Literal["all_cards", "selected_cards"]
    card_ids: list[str]
    window: TransactionWindow
    is_enabled: bool
    needs_card_selection: bool
    created_at: datetime
    updated_at: datetime


class TransactionLimitationListResponse(BaseModel):
    rules: list[TransactionLimitationResponse]
    cards: list[CardResponse]


class EvaluatedAllTimeWindow(BaseModel):
    type: Literal["all_time"]
    days: None = None
    start_date: None = None
    end_date: None = None
    effective_start_date: None = None
    effective_end_date: None = None


class EvaluatedRollingWindow(BaseModel):
    type: Literal["rolling"]
    days: int = Field(ge=1, le=730)
    start_date: None = None
    end_date: None = None
    effective_start_date: date
    effective_end_date: date


class EvaluatedFixedWindow(BaseModel):
    type: Literal["fixed"]
    days: None = None
    start_date: date
    end_date: date
    effective_start_date: date
    effective_end_date: date


EvaluatedTransactionWindow = Annotated[
    EvaluatedAllTimeWindow | EvaluatedRollingWindow | EvaluatedFixedWindow,
    Field(discriminator="type"),
]


class TransactionLimitAlertResponse(BaseModel):
    rule_id: str
    keyword: str
    threshold: int
    card: CardResponse
    match_count: int
    pending_count: int
    window: EvaluatedTransactionWindow


class TransactionLimitAlertListResponse(BaseModel):
    alerts: list[TransactionLimitAlertResponse]
    evaluated_at: datetime
    as_of_date: date
    cache_as_of: datetime | None


__all__ = [
    "BankConnectionResponse",
    "AllTransactionRow",
    "AllTransactionsResponse",
    "AllTimeWindow",
    "CardTransactionGroup",
    "GroupedSearchResponse",
    "TransactionMatch",
    "BankSlug",
    "CardResponse",
    "ConnectionsResponse",
    "CreateTransactionLimitationRequest",
    "CreateLinkTokenRequest",
    "ErrorResponse",
    "ExchangePublicTokenRequest",
    "ExchangeResponse",
    "EvaluatedAllTimeWindow",
    "EvaluatedFixedWindow",
    "EvaluatedRollingWindow",
    "LinkTokenResponse",
    "LoginRequest",
    "RollingWindow",
    "FixedWindow",
    "OwnerResponse",
    "SessionResponse",
    "TransactionLimitationListResponse",
    "TransactionLimitationResponse",
    "TransactionLimitAlertListResponse",
    "TransactionLimitAlertResponse",
    "UpdateTransactionLimitationRequest",
]
