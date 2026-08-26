"""One canonical classifier for how a bank connection is doing.

Both the connections list and the dashboard read from here, so a bank can
never appear healthy on one screen and broken on another. Provider error codes
are used for classification only; the owner-facing copy never repeats them.

The staleness threshold here decides when to *warn a human*, and is deliberately
longer than the *enqueue* threshold `enqueue_stale_connections` uses (60 minutes,
FR-SYNC-007/008). The two clocks are independent — the scheduler ticks from
process start, a connection ages from its own last sync — so equal thresholds
would flag healthy connections for up to a full sweep, every cycle. `stale` is
worth surfacing only once automatic recovery has actually failed to keep up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.models import BankConnection, utcnow

ConnectionState = Literal[
    "ready",
    "syncing",
    "stale",
    "needs_reconnect",
    "consent_expired",
    "provider_degraded",
    "disconnected",
]
ConnectionAction = Literal["none", "sync", "reconnect", "renew_consent"]

DISPLAY_STALE_AFTER_MINUTES = 150

RECONNECT_CODES = frozenset(
    {
        "ITEM_LOGIN_REQUIRED",
        "INVALID_CREDENTIALS",
        "INVALID_MFA",
        "USER_PERMISSION_REVOKED",
        "USER_ACCOUNT_REVOKED",
        "ACCESS_NOT_GRANTED",
        "ITEM_NOT_SUPPORTED",
    }
)
CONSENT_CODES = frozenset({"PENDING_DISCONNECT", "PENDING_EXPIRATION"})
DEGRADED_CODES = frozenset(
    {
        "INSTITUTION_DOWN",
        "INSTITUTION_NOT_RESPONDING",
        "INTERNAL_SERVER_ERROR",
        "PLANNED_MAINTENANCE",
        "RATE_LIMIT",
        "RATE_LIMIT_EXCEEDED",
        "PRODUCT_NOT_READY",
        "PLAID_UNREACHABLE",
        "PLAID_UNAVAILABLE",
        "TRANSACTIONS_SYNC_LIMIT",
        "WORKER_ERROR",
    }
)

MESSAGES: dict[str, str] = {
    "ready": "Up to date.",
    "syncing": "Loading transactions…",
    "stale": "Showing cached transactions. Sync to check for new activity.",
    "needs_reconnect": "This bank needs you to sign in again to keep syncing.",
    "consent_expired": "Your access permission is expiring. Renew it to keep syncing.",
    "provider_degraded": (
        "This bank is temporarily unavailable. Cached transactions are still "
        "searchable and syncing will retry automatically."
    ),
    "disconnected": "Not connected.",
}


@dataclass(frozen=True)
class ConnectionHealth:
    state: ConnectionState
    action: ConnectionAction
    message: str
    cache_as_of: datetime | None
    last_error_code: str | None


def classify_connection_health(
    connection: BankConnection,
    has_active_job: bool = False,
    now: datetime | None = None,
    stale_after_minutes: int | None = None,
) -> ConnectionHealth:
    moment = now or utcnow()
    cache_as_of = connection.last_successful_sync_at
    error = connection.last_error_code

    state, action = _resolve(
        connection,
        error,
        has_active_job,
        cache_as_of,
        moment,
        stale_after_minutes
        if stale_after_minutes is not None
        else DISPLAY_STALE_AFTER_MINUTES,
    )

    return ConnectionHealth(
        state=state,
        action=action,
        message=MESSAGES[state],
        cache_as_of=cache_as_of,
        last_error_code=error,
    )


def _resolve(
    connection: BankConnection,
    error: str | None,
    has_active_job: bool,
    cache_as_of: datetime | None,
    moment: datetime,
    stale_after_minutes: int,
) -> tuple[ConnectionState, ConnectionAction]:
    if connection.lifecycle_status != "active":
        return "disconnected", "none"

    # Owner action outranks everything else: an automatic retry cannot fix it.
    if error in RECONNECT_CODES:
        return "needs_reconnect", "reconnect"

    expires_at = connection.consent_expiration_at
    if error in CONSENT_CODES or (expires_at is not None and expires_at <= moment):
        return "consent_expired", "renew_consent"

    if error in DEGRADED_CODES:
        return "provider_degraded", "sync"

    if has_active_job:
        return "syncing", "none"

    if cache_as_of is None:
        return "stale", "sync"

    if moment - cache_as_of > timedelta(minutes=stale_after_minutes):
        return "stale", "sync"

    return "ready", "none"


__all__ = [
    "DISPLAY_STALE_AFTER_MINUTES",
    "ConnectionAction",
    "ConnectionHealth",
    "ConnectionState",
    "classify_connection_health",
]
