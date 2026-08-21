"""Owner credentials and opaque server-side sessions.

Passwords are hashed with Argon2id. The browser receives a random token; the
database stores only its SHA-256 hash, so a database read cannot reconstruct a
usable cookie.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Owner, OwnerSession, utcnow

MINIMUM_PASSWORD_LENGTH = 14
SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_LIFETIME_HOURS = 12

_password_hash = PasswordHash.recommended()


class OwnerAlreadyExistsError(Exception):
    """Raised when a second owner account is requested."""


class WeakPasswordError(Exception):
    """Raised when the chosen password is shorter than the minimum length."""


@dataclass(frozen=True)
class CreatedSession:
    token: str
    csrf_token: str
    expires_at: datetime
    session_id: str


@dataclass(frozen=True)
class ResolvedSession:
    owner: Owner
    session: OwnerSession


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_owner(session: AsyncSession) -> Owner | None:
    result = await session.execute(select(Owner).order_by(Owner.created_at).limit(1))
    return result.scalars().first()


async def create_owner(session: AsyncSession, email: str, password: str) -> Owner:
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {MINIMUM_PASSWORD_LENGTH} characters"
        )
    if await get_owner(session) is not None:
        raise OwnerAlreadyExistsError("an owner account already exists")

    owner = Owner(
        email=normalize_email(email),
        password_hash=_password_hash.hash(password),
    )
    session.add(owner)
    await session.flush()
    return owner


async def authenticate_owner(
    session: AsyncSession, email: str, password: str
) -> Owner | None:
    result = await session.execute(
        select(Owner).where(Owner.email == normalize_email(email))
    )
    owner = result.scalars().first()
    if owner is None:
        # Spend comparable time so a missing owner is not distinguishable.
        _password_hash.verify(password, _DUMMY_HASH)
        return None
    try:
        valid = _password_hash.verify(password, owner.password_hash)
    except Exception:
        return None
    return owner if valid else None


async def create_owner_session(
    session: AsyncSession,
    owner_id: str,
    lifetime_hours: int = DEFAULT_SESSION_LIFETIME_HOURS,
) -> CreatedSession:
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    expires_at = utcnow() + timedelta(hours=lifetime_hours)

    record = OwnerSession(
        owner_id=owner_id,
        token_sha256=hash_token(token),
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    session.add(record)
    await session.flush()
    return CreatedSession(
        token=token,
        csrf_token=csrf_token,
        expires_at=expires_at,
        session_id=record.id,
    )


async def resolve_session(
    session: AsyncSession, token: str | None
) -> ResolvedSession | None:
    if not token:
        return None
    result = await session.execute(
        select(OwnerSession, Owner)
        .join(Owner, Owner.id == OwnerSession.owner_id)
        .where(OwnerSession.token_sha256 == hash_token(token))
    )
    row = result.first()
    if row is None:
        return None
    owner_session, owner = row
    if owner_session.revoked_at is not None:
        return None
    if owner_session.expires_at <= utcnow():
        return None
    owner_session.last_seen_at = utcnow()
    return ResolvedSession(owner=owner, session=owner_session)


async def revoke_session(session: AsyncSession, token: str) -> None:
    result = await session.execute(
        select(OwnerSession).where(OwnerSession.token_sha256 == hash_token(token))
    )
    record = result.scalars().first()
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()


def csrf_matches(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return secrets.compare_digest(expected, provided)


_DUMMY_HASH = _password_hash.hash("dummy-password-for-constant-time-compare")

__all__ = [
    "CreatedSession",
    "OwnerAlreadyExistsError",
    "ResolvedSession",
    "WeakPasswordError",
    "authenticate_owner",
    "create_owner",
    "create_owner_session",
    "csrf_matches",
    "get_owner",
    "hash_token",
    "normalize_email",
    "resolve_session",
    "revoke_session",
]
