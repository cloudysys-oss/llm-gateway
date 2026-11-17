import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import crud, queries
from app.db import get_db
from app.proxy import get_http_client, router

from .conftest import override_get_db

SSE_CHUNK = 'data: {{"choices": [{{"delta": {{"content": "{text}"}}}}]}}\n\n'
SSE_USAGE_CHUNK = (
    'data: {"choices": [], "usage": '
    '{"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}\n\n'
)
SSE_DONE = "data: [DONE]\n\n"


def _build_test_app(conn, handler):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db(conn)

    async def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    app.dependency_overrides[get_http_client] = lambda: mock_client
    return app


def test_injects_include_usage_when_client_did_not_ask(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        body = (
            SSE_CHUNK.format(text="Hi") + SSE_USAGE_CHUNK + SSE_DONE
        ).encode("utf-8")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o", "stream": True},
    )

    assert response.status_code == 200
    assert captured["body"]["stream_options"] == {"include_usage": True}
    # the synthetic usage-only chunk must NOT reach the client
    assert '"usage"' not in response.text
    assert "[DONE]" in response.text

    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["total_tokens"] == 10
    assert logged[0]["prompt_tokens"] == 7


def test_captures_usage_when_backend_omits_space_after_data_colon(env_settings, conn):
    """Real-world regression: some OpenAI-compatible backends emit
    `data:{...}` with no space after the colon, instead of the more common
    `data: {...}`. Both are valid SSE (the space is optional per spec), but
    our line-matching originally required the space literally, so these
    lines were never parsed and usage was silently never captured."""
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    no_space_body = (
        'data:{"choices": [{"delta": {"content": "Hi"}}]}\n\n'
        'data:{"choices": [], "usage": '
        '{"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}\n\n'
        "data:[DONE]\n\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=no_space_body, headers={"content-type": "text/event-stream"}
        )

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o", "stream": True, "stream_options": {"include_usage": True}},
    )

    assert response.status_code == 200
    assert '"usage"' in response.text
    assert "[DONE]" in response.text

    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["total_tokens"] == 10
    assert logged[0]["prompt_tokens"] == 7


def test_forwards_usage_chunk_when_client_already_asked_for_it(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        body = (SSE_USAGE_CHUNK + SSE_DONE).encode("utf-8")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o", "stream": True, "stream_options": {"include_usage": True}},
    )

    assert '"usage"' in response.text

    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["total_tokens"] == 10


def test_captures_usage_attached_to_the_final_content_chunk_vllm_style(env_settings, conn):
    """Some OpenAI-compatible backends (vLLM-style servers) attach `usage` to
    the same chunk as the final finish_reason, instead of a separate
    usage-only chunk with empty `choices`. Usage must still be captured, and
    the finish_reason/content in that chunk must still reach the client."""
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    vllm_style_final_chunk = (
        'data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], '
        '"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = (SSE_CHUNK.format(text="Hi") + vllm_style_final_chunk + SSE_DONE).encode("utf-8")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    app = _build_test_app(conn, handler)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "gpt-4o", "stream": True},
    )

    assert response.status_code == 200
    # usage field itself is stripped (client never asked for it)...
    assert '"usage"' not in response.text
    # ...but the finish_reason chunk it was attached to must still be forwarded
    assert '"finish_reason": "stop"' in response.text
    assert "[DONE]" in response.text

    logged = queries.recent_requests(conn, project.id)
    assert logged[0]["total_tokens"] == 10
    assert logged[0]["prompt_tokens"] == 7
