"""Request-scoped dependencies: database session, owner session, and CSRF."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Database
from app.errors import AuthRequiredError, CsrfInvalidError, OriginInvalidError
from app.models import Owner
from app.services import auth as auth_service
from app.services.auth import ResolvedSession


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_database(request: Request) -> Database:
    return request.app.state.database  # type: ignore[no-any-return]


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def require_session(
    request: Request, session: SessionDep, settings: SettingsDep
) -> ResolvedSession:
    token = request.cookies.get(settings.session_cookie_name)
    resolved = await auth_service.resolve_session(session, token)
    if resolved is None:
        raise AuthRequiredError()
    request.state.owner_id = resolved.owner.id
    return resolved


ResolvedSessionDep = Annotated[ResolvedSession, Depends(require_session)]


async def require_owner(resolved: ResolvedSessionDep) -> Owner:
    return resolved.owner


OwnerDep = Annotated[Owner, Depends(require_owner)]


async def require_csrf(
    request: Request, resolved: ResolvedSessionDep, settings: SettingsDep
) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise OriginInvalidError()
    provided = request.headers.get("x-csrf-token")
    if not auth_service.csrf_matches(resolved.session.csrf_token, provided):
        raise CsrfInvalidError()


CsrfDep = Depends(require_csrf)

__all__ = [
    "CsrfDep",
    "OwnerDep",
    "ResolvedSessionDep",
    "SessionDep",
    "SettingsDep",
    "get_database",
    "get_db_session",
    "require_csrf",
    "require_owner",
    "require_session",
]


def get_plaid_gateway(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.plaid_gateway


def get_token_cipher(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.token_cipher


async def connection_service_dep(request: Request, session: SessionDep):  # type: ignore[no-untyped-def]
    from app.services.connection_service import ConnectionService

    return ConnectionService(
        session,
        request.app.state.settings,
        request.app.state.plaid_gateway,
        request.app.state.token_cipher,
    )
