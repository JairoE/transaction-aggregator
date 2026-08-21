from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Owner, OwnerSession, utcnow
from app.services import auth as auth_service

PASSWORD = "correct horse battery staple"


async def test_create_owner_hashes_password_with_argon2id(
    db_session: AsyncSession,
) -> None:
    owner = await auth_service.create_owner(db_session, "Owner@Example.com", PASSWORD)

    assert owner.email == "owner@example.com"
    assert PASSWORD not in owner.password_hash
    assert owner.password_hash.startswith("$argon2id$")


async def test_create_owner_refuses_a_second_owner(db_session: AsyncSession) -> None:
    await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    with pytest.raises(auth_service.OwnerAlreadyExistsError):
        await auth_service.create_owner(db_session, "other@example.com", PASSWORD)


async def test_create_owner_rejects_short_passwords(db_session: AsyncSession) -> None:
    with pytest.raises(auth_service.WeakPasswordError):
        await auth_service.create_owner(db_session, "owner@example.com", "short")


async def test_authenticate_owner_accepts_correct_credentials(
    db_session: AsyncSession,
) -> None:
    await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    owner = await auth_service.authenticate_owner(
        db_session, "OWNER@example.com", PASSWORD
    )

    assert owner is not None
    assert owner.email == "owner@example.com"


async def test_authenticate_owner_rejects_wrong_password(
    db_session: AsyncSession,
) -> None:
    await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    assert await auth_service.authenticate_owner(db_session, "owner@example.com", "x") is None


async def test_authenticate_owner_rejects_unknown_email(
    db_session: AsyncSession,
) -> None:
    await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    assert await auth_service.authenticate_owner(db_session, "nobody@example.com", PASSWORD) is None


async def test_session_stores_only_the_token_hash(db_session: AsyncSession) -> None:
    owner = await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    created = await auth_service.create_owner_session(db_session, owner.id)
    await db_session.commit()

    stored = (await db_session.execute(select(OwnerSession))).scalars().one()
    assert stored.token_sha256 != created.token
    assert stored.token_sha256 == hashlib.sha256(created.token.encode()).hexdigest()
    assert len(created.token) >= 43
    assert len(created.csrf_token) >= 32
    assert created.csrf_token != created.token


async def test_resolve_session_returns_owner_for_valid_token(
    db_session: AsyncSession,
) -> None:
    owner = await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)
    created = await auth_service.create_owner_session(db_session, owner.id)
    await db_session.commit()

    resolved = await auth_service.resolve_session(db_session, created.token)

    assert resolved is not None
    assert resolved.owner.id == owner.id
    assert resolved.session.csrf_token == created.csrf_token


async def test_expired_session_is_rejected(db_session: AsyncSession) -> None:
    owner = await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)
    with freeze_time(utcnow() - timedelta(hours=13)):
        created = await auth_service.create_owner_session(db_session, owner.id)
        await db_session.commit()

    assert await auth_service.resolve_session(db_session, created.token) is None


async def test_revoked_session_is_rejected(db_session: AsyncSession) -> None:
    owner = await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)
    created = await auth_service.create_owner_session(db_session, owner.id)
    await db_session.commit()

    await auth_service.revoke_session(db_session, created.token)
    await db_session.commit()

    assert await auth_service.resolve_session(db_session, created.token) is None


async def test_unknown_token_is_rejected(db_session: AsyncSession) -> None:
    await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    assert await auth_service.resolve_session(db_session, "not-a-real-token") is None


async def test_get_owner_returns_the_single_owner(db_session: AsyncSession) -> None:
    assert await auth_service.get_owner(db_session) is None

    owner = await auth_service.create_owner(db_session, "owner@example.com", PASSWORD)

    found = await auth_service.get_owner(db_session)
    assert found is not None and found.id == owner.id
    assert isinstance(found, Owner)
