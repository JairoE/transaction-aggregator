"""The SPA is served same-origin without ever shadowing the API."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
requires_build = pytest.mark.skipif(
    not (DIST / "index.html").is_file(),
    reason="run `pnpm --dir frontend build` first",
)


@pytest.fixture
async def packaged_client(database):
    from app.config import get_settings
    from app.main import create_app

    app = create_app(settings=get_settings(), database=database)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        yield client


async def test_api_routes_never_fall_through_to_the_spa(
    packaged_client: AsyncClient,
) -> None:
    response = await packaged_client.get(
        "/api/not-a-real-endpoint", headers={"Accept": "text/html"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert "<!doctype html" not in response.text.lower()


@requires_build
async def test_client_routes_serve_the_spa(packaged_client: AsyncClient) -> None:
    for route in ("/", "/connections", "/dashboard", "/oauth-return"):
        response = await packaged_client.get(route, headers={"Accept": "text/html"})

        assert response.status_code == 200, route
        assert "<!doctype html" in response.text.lower(), route
        assert response.headers["cache-control"] == "no-cache", route


@requires_build
async def test_hashed_assets_are_cached_immutably(
    packaged_client: AsyncClient,
) -> None:
    asset = next((DIST / "assets").glob("*.js"))

    response = await packaged_client.get(f"/assets/{asset.name}")

    assert response.status_code == 200
    assert "max-age=31536000" in response.headers["cache-control"]


@requires_build
async def test_non_html_requests_do_not_receive_the_spa(
    packaged_client: AsyncClient,
) -> None:
    response = await packaged_client.get(
        "/nope.json", headers={"Accept": "application/json"}
    )

    assert response.status_code == 404


@requires_build
async def test_the_built_bundle_contains_no_secrets() -> None:
    """SEC-002: Plaid credentials must never reach the frontend bundle."""

    forbidden = ("access-sandbox", "access-production", "plaid_secret", "PLAID_SECRET")
    for bundle in (DIST / "assets").glob("*.js"):
        content = bundle.read_text(errors="ignore")
        for needle in forbidden:
            assert needle not in content, f"{needle} found in {bundle.name}"
