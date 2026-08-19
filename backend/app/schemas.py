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


__all__ = [
    "BankSlug",
    "ErrorResponse",
    "LoginRequest",
    "OwnerResponse",
    "SessionResponse",
    "datetime",
]
