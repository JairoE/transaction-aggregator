"""Wire contracts shared by every API route."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

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


__all__ = [
    "BankConnectionResponse",
    "BankSlug",
    "CardResponse",
    "ConnectionsResponse",
    "CreateLinkTokenRequest",
    "ErrorResponse",
    "ExchangePublicTokenRequest",
    "ExchangeResponse",
    "LinkTokenResponse",
    "LoginRequest",
    "OwnerResponse",
    "SessionResponse",
]
