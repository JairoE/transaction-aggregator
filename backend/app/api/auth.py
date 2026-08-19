"""Owner sign-in, session inspection, and sign-out."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.dependencies import (
    CsrfDep,
    ResolvedSessionDep,
    SessionDep,
    SettingsDep,
)
from app.errors import AuthInvalidError
from app.models import utcnow
from app.schemas import LoginRequest, OwnerResponse, SessionResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(
    response: Response, settings, token: str, max_age_seconds: int
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> SessionResponse:
    owner = await auth_service.authenticate_owner(
        session, payload.email, payload.password
    )
    if owner is None:
        raise AuthInvalidError()

    created = await auth_service.create_owner_session(
        session, owner.id, lifetime_hours=settings.session_lifetime_hours
    )
    _set_session_cookie(
        response, settings, created.token, settings.session_lifetime_hours * 3600
    )
    return SessionResponse(
        owner=OwnerResponse(id=owner.id, email=owner.email),
        csrf_token=created.csrf_token,
    )


@router.get("/session", response_model=SessionResponse)
async def read_session(resolved: ResolvedSessionDep) -> SessionResponse:
    return SessionResponse(
        owner=OwnerResponse(id=resolved.owner.id, email=resolved.owner.email),
        csrf_token=resolved.session.csrf_token,
    )


@router.post("/logout", status_code=204, dependencies=[CsrfDep])
async def logout(
    response: Response,
    resolved: ResolvedSessionDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    resolved.session.revoked_at = utcnow()
    await session.flush()
    response.delete_cookie(
        key=settings.session_cookie_name, path="/", samesite="strict"
    )
    response.status_code = 204
    return response


__all__ = ["router"]
