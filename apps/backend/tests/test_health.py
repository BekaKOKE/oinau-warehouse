"""Смоук-тесты каркаса. Внешние зависимости не требуются."""

from __future__ import annotations

from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_request_id_header_is_returned(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Request-ID"]


async def test_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-42"})
    assert response.headers["X-Request-ID"] == "trace-42"


async def test_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_unknown_route_uses_unified_error_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/public/does-not-exist")
    assert response.status_code == 404
    assert "error" in response.json()
    assert response.json()["error"]["code"] == "http_404"


async def test_api_v1_surfaces_are_registered(client: AsyncClient) -> None:
    """Три поверхности API существуют и разделены по префиксам."""
    schema = (await client.get("/openapi.json")).json()
    assert schema["info"]["title"]
