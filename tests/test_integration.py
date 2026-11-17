import httpx
from fastapi.testclient import TestClient

from app import crud, queries
from app.db import get_connection, init_db
from app.main import create_app
from app.proxy import get_http_client


def test_full_flow_healthz_login_and_proxy(env_settings):
    app = create_app()

    def _sync_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [], "usage": {"total_tokens": 5}}
        )

    async def _handler(request: httpx.Request) -> httpx.Response:
        return _sync_handler(request)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    app.dependency_overrides[get_http_client] = lambda: mock_client

    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/_gateway/healthz").json() == {"status": "ok"}

        # dashboard requires login
        assert client.get("/_gateway/dashboard").status_code == 303

        login = client.post(
            "/_gateway/login", data={"password": env_settings.dashboard_password}
        )
        assert login.status_code == 303
        assert client.get("/_gateway/dashboard").status_code == 200

        # create a project directly against the same DB file the app is using
        conn = get_connection(env_settings.database_path)
        init_db(conn)
        project = crud.create_project(conn, "Integration Demo")
        raw_key = crud.create_api_key(conn, project.id)
        conn.close()

        proxy_response = client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"model": "gpt-4o", "messages": []},
        )
        assert proxy_response.status_code == 200
        assert proxy_response.json()["usage"]["total_tokens"] == 5

        # dashboard now shows the logged usage
        detail = client.get(f"/_gateway/dashboard/{project.id}")
        assert "5" in detail.text


def test_streaming_request_logs_usage_with_real_db_wiring(env_settings):
    """Regression test: get_db() is a real yield-dependency here (not overridden,
    unlike every other proxy test), so this reproduces the production bug where
    FastAPI closes it right after proxy() returns the StreamingResponse object,
    before event_stream()'s finally block runs crud.log_request against it."""
    app = create_app()

    async def _handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
            b'data: {"choices": [], "usage": '
            b'{"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    app.dependency_overrides[get_http_client] = lambda: mock_client

    with TestClient(app, follow_redirects=False) as client:
        conn = get_connection(env_settings.database_path)
        init_db(conn)
        project = crud.create_project(conn, "Streaming Demo")
        raw_key = crud.create_api_key(conn, project.id)
        conn.close()

        response = client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"model": "gpt-4o", "messages": [], "stream": True},
        )

        assert response.status_code == 200
        assert "[DONE]" in response.text

        verify_conn = get_connection(env_settings.database_path)
        logged = queries.recent_requests(verify_conn, project.id)
        verify_conn.close()
        assert logged[0]["total_tokens"] == 5
