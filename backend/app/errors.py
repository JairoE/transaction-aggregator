"""Stable application error codes returned to the browser.

Responses never contain stack traces, provider messages, or secrets — only a
short machine-readable code and owner-safe copy.
"""

from __future__ import annotations


class AppError(Exception):
    """An error that maps to a stable API code and HTTP status."""

    def __init__(
        self, code: str, message: str, status_code: int = 400, *, retryable: bool = False
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


class AuthRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__("AUTH_REQUIRED", "Sign in to continue.", 401)


class AuthInvalidError(AppError):
    def __init__(self) -> None:
        super().__init__("AUTH_INVALID", "Email or password is incorrect.", 401)


class CsrfInvalidError(AppError):
    def __init__(self) -> None:
        super().__init__("CSRF_INVALID", "Your session token was missing or stale.", 403)


class OriginInvalidError(AppError):
    def __init__(self) -> None:
        super().__init__("ORIGIN_INVALID", "This request came from an unexpected origin.", 403)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.") -> None:
        super().__init__("NOT_FOUND", message, 404)


__all__ = [
    "AppError",
    "AuthInvalidError",
    "AuthRequiredError",
    "CsrfInvalidError",
    "NotFoundError",
    "OriginInvalidError",
]
