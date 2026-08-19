from __future__ import annotations

import json
import logging

from app.logging import JsonFormatter, redact


def test_redaction_covers_sensitive_keys() -> None:
    payload = {
        "password": "hunter2",
        "access_token": "access-production-abc",
        "public_token": "public-abc",
        "Authorization": "Bearer abc",
        "cookie": "ta_session=abc",
        "csrf_token": "abc",
        "plaid_secret": "abc",
        "nested": {"session_token": "abc", "safe": "keep me"},
        "items": [{"api_key": "abc"}],
    }

    cleaned = redact(payload)

    serialized = json.dumps(cleaned)
    for secret in ["hunter2", "access-production-abc", "public-abc", "Bearer abc"]:
        assert secret not in serialized
    assert cleaned["nested"]["safe"] == "keep me"
    assert cleaned["items"][0]["api_key"] == "[redacted]"


def test_search_queries_and_descriptions_are_not_logged() -> None:
    cleaned = redact({"query": "Paze", "original_description": "PAZE*URBAN MARKET"})

    assert cleaned["query"] == "[redacted]"
    assert cleaned["original_description"] == "[redacted]"


def test_formatter_emits_structured_json_without_secrets() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="sync_completed",
        args=(),
        exc_info=None,
    )
    record.connection_id = "conn-1"
    record.access_token = "access-production-abc"

    line = json.loads(formatter.format(record))

    assert line["event"] == "sync_completed"
    assert line["level"] == "INFO"
    assert line["connection_id"] == "conn-1"
    assert line["access_token"] == "[redacted]"


def test_redaction_survives_unserializable_values() -> None:
    class Opaque:
        def __repr__(self) -> str:  # pragma: no cover - trivial
            return "<opaque>"

    cleaned = redact({"value": Opaque()})

    assert json.dumps(cleaned)
