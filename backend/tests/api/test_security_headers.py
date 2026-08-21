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
