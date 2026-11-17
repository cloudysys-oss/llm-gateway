import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import crud, queries
from app.db import get_db
from app.proxy import get_http_client, router

from .conftest import override_get_db


def _build_test_app(conn, handler):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db(conn)

    async def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    app.dependency_overrides[get_http_client] = lambda: mock_client
    return app


def test_backend_connection_failure_returns_502_and_logs_zero_tokens(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o"},
    )

    assert response.status_code == 502
    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["status_code"] == 502
    assert logged[0]["total_tokens"] is None


def test_backend_non_2xx_status_is_passed_through(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o"},
    )

    assert response.status_code == 429
    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["status_code"] == 429
