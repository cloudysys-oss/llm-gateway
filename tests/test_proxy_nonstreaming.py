import json

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


def test_forwards_request_and_logs_usage(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}", "X-Task-Label": "batch"},
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["usage"]["total_tokens"] == 15
    assert captured["url"] == "http://backend.test/chat/completions"
    assert captured["auth"] == "Bearer real-backend-key"
    assert captured["body"]["model"] == "gpt-4o"

    logged = queries.recent_requests(conn, project.id)
    assert len(logged) == 1
    assert logged[0]["total_tokens"] == 15
    assert logged[0]["label"] == "batch"
    assert logged[0]["model"] == "gpt-4o"


def test_label_header_is_not_forwarded_to_backend(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-task-label" not in request.headers
        return httpx.Response(200, json={"choices": [], "usage": {"total_tokens": 1}})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}", "X-Task-Label": "batch"},
        json={"model": "gpt-4o"},
    )

    assert response.status_code == 200


def test_request_without_label_header_logs_null_label(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [], "usage": {"total_tokens": 1}})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o"},
    )

    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["label"] is None
