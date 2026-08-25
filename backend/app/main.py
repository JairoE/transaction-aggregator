"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import auth as auth_api
from app.api import connections as connections_api
from app.api import limitations as limitations_api
from app.api import search as search_api
from app.api import sync as sync_api
from app.api import webhooks as webhooks_api
from app.config import Settings, get_settings
from app.db import Database, create_database
from app.errors import AppError
from app.services.plaid_gateway import PlaidGatewayError as _PlaidGatewayError
from app.logging import configure_logging
from app.middleware import (
    RequestContextMiddleware,
    TrustedHostMiddleware,
    build_content_security_policy,
    mount_spa,
)
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
        import asyncio

        from app.services.sync_service import enqueue_stale_connections
        from app.services.sync_worker import SyncWorker

        owns_database = database is None
        app.state.database = database or create_database(resolved_settings)
        await app.state.database.verify_fts5_trigram()

        tasks: list[asyncio.Task[None]] = []
        worker: SyncWorker | None = None
        if resolved_settings.enable_background_worker:
            worker = SyncWorker(
                app.state.database, app.state.plaid_gateway, app.state.token_cipher
            )
            app.state.sync_worker = worker
            # Startup recovery: anything not synced within the window is queued.
            async with app.state.database.session() as session:
                await enqueue_stale_connections(
                    session,
                    stale_after_minutes=resolved_settings.sync_interval_minutes,
                    trigger="startup",
                )
                await session.commit()
            tasks.append(asyncio.create_task(worker.run_forever()))
            tasks.append(
                asyncio.create_task(
                    worker.run_scheduler(resolved_settings.sync_interval_minutes)
                )
            )
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            if owns_database:
                await app.state.database.dispose()

    if resolved_settings.environment != "test":
        configure_logging()

    app = FastAPI(title="Transaction Aggregator API", lifespan=lifespan)
    app.add_middleware(
        RequestContextMiddleware,
        content_security_policy=build_content_security_policy(
            allow_plaid=not resolved_settings.uses_fake_plaid
        ),
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=resolved_settings.trusted_host_list
    )
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

    @app.exception_handler(_PlaidGatewayError)
    async def handle_plaid_error(
        _: Request, error: _PlaidGatewayError
    ) -> JSONResponse:
        """Any Plaid failure surfaced synchronously (Link, exchange, update,
        disconnect) gets a stable typed response instead of a 500. The sync
        worker's own retry/backoff path classifies these separately; this
        only covers requests made directly from a route handler.
        """

        status = 503 if error.retry_class == "transient" else 502
        return JSONResponse(
            status_code=status,
            content={
                "code": "PLAID_UNAVAILABLE",
                "message": (
                    "The bank could not complete this request right now. "
                    "Please try again in a moment."
                ),
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_api.router)
    app.include_router(connections_api.router)
    app.include_router(limitations_api.router)
    app.include_router(search_api.router)
    app.include_router(sync_api.router)
    app.include_router(webhooks_api.router)

    # Mounted last so the SPA catch-all never shadows an API route.
    mount_spa(app, Path(__file__).resolve().parents[2] / "frontend" / "dist")

    return app
