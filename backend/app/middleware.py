"""Security headers, request identity, and the SPA fallback.

The SPA is served from the same origin as the API so the session cookie can
stay SameSite=Strict, and `/api/*` never falls through to `index.html` — a
missing endpoint must look like a missing endpoint, not a blank page.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

logger = logging.getLogger("app.request")

PLAID_CDN = "https://cdn.plaid.com"
PLAID_APIS = "https://production.plaid.com https://sandbox.plaid.com"


def build_content_security_policy(allow_plaid: bool) -> str:
    """Only widen the policy for the origins real Plaid Link actually needs."""

    script = f"script-src 'self' {PLAID_CDN}" if allow_plaid else "script-src 'self'"
    connect = (
        f"connect-src 'self' {PLAID_APIS}" if allow_plaid else "connect-src 'self'"
    )
    frame = f"frame-src 'self' {PLAID_CDN}" if allow_plaid else "frame-src 'self'"
    return "; ".join(
        (
            "default-src 'self'",
            script,
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self' data:",
            connect,
            frame,
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        )
    )


CONTENT_SECURITY_POLICY = build_content_security_policy(allow_plaid=True)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamps a request id, applies security headers, and logs the outcome."""

    def __init__(self, app, content_security_policy: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._csp = content_security_policy

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("Content-Security-Policy", self._csp)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        if request.url.path.startswith("/api"):
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "route": request.url.path,
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                    "owner_id": getattr(request.state, "owner_id", None),
                },
            )
        return response


class TrustedHostMiddleware(BaseHTTPMiddleware):
    """Rejects Host headers outside the configured allowlist."""

    def __init__(self, app, allowed_hosts: tuple[str, ...]) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._allowed = {host.lower() for host in allowed_hosts}

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if "*" not in self._allowed:
            host = (request.headers.get("host") or "").split(":", 1)[0].lower()
            if host and host not in self._allowed:
                return JSONResponse(
                    status_code=400,
                    content={
                        "code": "HOST_NOT_ALLOWED",
                        "message": "This host is not configured for the application.",
                    },
                )
        return await call_next(request)


class ImmutableStaticFiles(StaticFiles):
    """Vite writes content-hashed filenames, so assets can be cached for a year."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_spa(app: FastAPI, dist_directory: Path) -> None:
    """Serve the built SPA same-origin, without shadowing the API."""

    if not dist_directory.is_dir():
        return

    assets = dist_directory / "assets"
    if assets.is_dir():
        app.mount(
            "/assets",
            ImmutableStaticFiles(directory=assets),
            name="assets",
        )

    index_file = dist_directory / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> Response:
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": "Not found."},
            )

        candidate = (dist_directory / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and dist_directory.resolve() in candidate.parents
        ):
            return FileResponse(
                candidate,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

        if "text/html" not in request.headers.get("accept", "text/html"):
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": "Not found."},
            )

        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "ImmutableStaticFiles",
    "build_content_security_policy",
    "SECURITY_HEADERS",
    "RequestContextMiddleware",
    "TrustedHostMiddleware",
    "mount_spa",
]
