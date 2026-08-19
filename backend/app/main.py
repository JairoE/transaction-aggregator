"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import auth as auth_api
from app.api import connections as connections_api
from app.config import Settings, get_settings
from app.db import Database, create_database
from app.errors import AppError
from app.services.crypto import TokenCipher
from app.services.plaid_gateway import PlaidGateway


def build_plaid_gateway(settings: Settings) -> PlaidGateway:
    """Demo and test environments never reach the network."""

    if settings.uses_fake_plaid:
        from app.services.demo_gateway import DemoPlaidGateway

        return DemoPlaidGateway()

    from app.services.plaid_client import PlaidPythonGateway

    return PlaidPythonGateway(settings)


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    plaid_gateway: PlaidGateway | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_database = database is None
        app.state.database = database or create_database(resolved_settings)
        await app.state.database.verify_fts5_trigram()
        try:
            yield
        finally:
            if owns_database:
                await app.state.database.dispose()

    app = FastAPI(title="Transaction Aggregator API", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.plaid_gateway = plaid_gateway or build_plaid_gateway(resolved_settings)
    app.state.token_cipher = TokenCipher.from_base64_key(
        resolved_settings.token_encryption_key.get_secret_value(),
        resolved_settings.token_encryption_key_version,
    )
    if database is not None:
        app.state.database = database

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"code": error.code, "message": error.message},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, __: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "REQUEST_INVALID",
                "message": "The request could not be processed.",
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_api.router)
    app.include_router(connections_api.router)

    return app

