from __future__ import annotations

import logging

from httpx import AsyncClient

PASSWORD = "correct horse battery staple"


async def test_login_sets_opaque_cookie_and_returns_csrf_token(
    client: AsyncClient, owner
) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["owner"]["email"] == owner.email
    assert len(body["csrf_token"]) >= 32
    set_cookie = response.headers["set-cookie"]
    assert "ta_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie.replace("SameSite=Strict", "SameSite=strict")
    assert body["csrf_token"] not in set_cookie


async def test_login_email_is_case_insensitive(client: AsyncClient, owner) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": owner.email.upper(), "password": PASSWORD},
    )

    assert response.status_code == 200


async def test_login_with_wrong_password_is_generic(client: AsyncClient, owner) -> None:
    response = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": "wrong password!!"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID"
    assert "set-cookie" not in response.headers


async def test_login_with_unknown_email_is_indistinguishable(
    client: AsyncClient, owner
) -> None:
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    wrong = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": "wrong password!!"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_password_is_never_logged(
    client: AsyncClient, owner, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        await client.post(
            "/api/auth/login", json={"email": owner.email, "password": PASSWORD}
        )

    assert PASSWORD not in caplog.text


async def test_session_endpoint_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


async def test_session_endpoint_returns_owner_when_authenticated(
    authenticated_client: AsyncClient, owner
) -> None:
    response = await authenticated_client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json()["owner"]["email"] == owner.email


async def test_mutation_rejects_missing_csrf(authenticated_client: AsyncClient) -> None:
    response = await authenticated_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": ""}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


async def test_mutation_rejects_wrong_csrf(authenticated_client: AsyncClient) -> None:
    response = await authenticated_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": "not-the-real-token"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


async def test_mutation_rejects_cross_origin(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token, "Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_INVALID"


async def test_mutation_allows_same_origin(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    response = await authenticated_client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token, "Origin": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 204


async def test_logout_revokes_the_server_side_session(
    authenticated_client: AsyncClient, csrf_token: str
) -> None:
    logout = await authenticated_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf_token}
    )
    assert logout.status_code == 204

    after = await authenticated_client.get("/api/auth/session")
    assert after.status_code == 401


async def test_login_rotates_the_session_token(client: AsyncClient, owner) -> None:
    first = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": PASSWORD}
    )
    second = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": PASSWORD}
    )

    assert first.json()["csrf_token"] != second.json()["csrf_token"]
