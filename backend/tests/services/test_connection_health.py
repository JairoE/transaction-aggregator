from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import BankConnection, utcnow
from app.services.connection_health import classify_connection_health

NOW = utcnow()


def _connection(**overrides) -> BankConnection:
    values = {
        "id": "conn-1",
        "owner_id": "owner-1",
        "bank_slug": "capital-one",
        "institution_id": "ins_128026",
        "institution_name": "Capital One",
        "plaid_item_id": "item-1",
        "plaid_environment": "sandbox",
        "lifecycle_status": "active",
        "last_successful_sync_at": NOW - timedelta(minutes=5),
        "refresh_supported": True,
    }
    values.update(overrides)
    return BankConnection(**values)


def test_healthy_recent_connection_is_ready() -> None:
    health = classify_connection_health(_connection(), has_active_job=False, now=NOW)

    assert health.state == "ready"
    assert health.action == "none"
    assert health.last_error_code is None


def test_removed_connection_is_disconnected() -> None:
    health = classify_connection_health(
        _connection(lifecycle_status="removed", last_successful_sync_at=None),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "disconnected"
    assert health.action == "none"


@pytest.mark.parametrize(
    "code",
    [
        "ITEM_LOGIN_REQUIRED",
        "INVALID_CREDENTIALS",
        "INVALID_MFA",
        "USER_PERMISSION_REVOKED",
        "ACCESS_NOT_GRANTED",
    ],
)
def test_owner_action_errors_require_reconnect(code: str) -> None:
    health = classify_connection_health(
        _connection(last_error_code=code), has_active_job=False, now=NOW
    )

    assert health.state == "needs_reconnect"
    assert health.action == "reconnect"
    assert health.last_error_code == code


def test_expired_consent_requires_renewal() -> None:
    health = classify_connection_health(
        _connection(consent_expiration_at=NOW - timedelta(days=1)),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "consent_expired"
    assert health.action == "renew_consent"


def test_pending_disconnect_requires_renewal() -> None:
    health = classify_connection_health(
        _connection(last_error_code="PENDING_DISCONNECT"),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "consent_expired"
    assert health.action == "renew_consent"


def test_future_consent_expiry_is_still_ready() -> None:
    health = classify_connection_health(
        _connection(consent_expiration_at=NOW + timedelta(days=30)),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "ready"


def test_transient_provider_error_is_degraded_not_broken() -> None:
    health = classify_connection_health(
        _connection(last_error_code="INSTITUTION_DOWN"),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "provider_degraded"
    assert health.action == "sync"
    assert health.cache_as_of is not None, "cached data stays available"


def test_queued_job_reports_syncing() -> None:
    health = classify_connection_health(
        _connection(), has_active_job=True, now=NOW
    )

    assert health.state == "syncing"
    assert health.action == "none"


def test_reconnect_clears_the_error_and_returns_to_syncing() -> None:
    repaired = _connection(last_error_code=None)

    syncing = classify_connection_health(repaired, has_active_job=True, now=NOW)
    ready = classify_connection_health(repaired, has_active_job=False, now=NOW)

    assert syncing.state == "syncing"
    assert ready.state == "ready"


def test_cache_older_than_an_hour_is_stale() -> None:
    health = classify_connection_health(
        _connection(last_successful_sync_at=NOW - timedelta(minutes=61)),
        has_active_job=False,
        now=NOW,
    )

    assert health.state == "stale"
    assert health.action == "sync"
    assert health.cache_as_of == NOW - timedelta(minutes=61)


def test_never_synced_connection_is_stale() -> None:
    health = classify_connection_health(
        _connection(last_successful_sync_at=None), has_active_job=False, now=NOW
    )

    assert health.state == "stale"
    assert health.cache_as_of is None


def test_owner_action_outranks_a_queued_retry() -> None:
    health = classify_connection_health(
        _connection(last_error_code="ITEM_LOGIN_REQUIRED"),
        has_active_job=True,
        now=NOW,
    )

    assert health.state == "needs_reconnect"


def test_no_raw_provider_message_is_exposed() -> None:
    health = classify_connection_health(
        _connection(last_error_code="INSTITUTION_DOWN"), has_active_job=False, now=NOW
    )

    assert health.message
    assert "INSTITUTION_DOWN" not in health.message
