from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
