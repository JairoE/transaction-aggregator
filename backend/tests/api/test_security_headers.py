from __future__ import annotations

from httpx import AsyncClient


async def test_responses_carry_hardening_headers(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    headers = response.headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


async def test_content_security_policy_blocks_remote_script_sources(
    client: AsyncClient,
) -> None:
    policy = (await client.get("/api/health")).headers["content-security-policy"]

    assert "script-src 'self'" in policy
    assert "unsafe-eval" not in policy
    assert "https://cdn" not in policy


async def test_every_request_gets_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.headers["x-request-id"]


async def test_session_cookie_flags(client: AsyncClient, owner) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": "correct horse battery staple"},
    )

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=strict" in cookie.replace("SameSite=Strict", "SameSite=strict")


async def test_https_deployments_mark_the_cookie_secure() -> None:
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite+aiosqlite:///:memory:",
        application_secret="s" * 32,
        token_encryption_key="k" * 43,
        public_base_url="https://aggregator.example.com",
        plaid_client_id="client",
        plaid_secret="secret",
    )

    assert settings.cookie_secure is True


async def test_unknown_host_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"Host": "evil.example.com"})

    assert response.status_code == 400


async def test_missing_host_header_is_rejected(app) -> None:
    """A Host header that is absent entirely must be rejected like an unknown
    one, rather than falling through the allowlist as an empty string. httpx
    always synthesizes a Host from the base URL, so this drives the ASGI app
    directly to omit the header a real client could still withhold.
    """
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/health",
            "raw_path": b"/api/health",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 54321),
            "server": ("127.0.0.1", 8000),
        },
        receive,
        send,
    )

    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")

    assert start["status"] == 400
    assert b"HOST_NOT_ALLOWED" in body
