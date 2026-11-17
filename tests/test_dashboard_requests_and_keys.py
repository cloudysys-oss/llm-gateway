from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app import crud
from app.dashboard.routes import router
from app.db import get_db

from .conftest import override_get_db


def _logged_in_client(conn, settings):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app, follow_redirects=False)
    client.post("/_gateway/login", data={"password": settings.dashboard_password})
    return client


def _log(conn, project_id, total_tokens):
    conn.execute(
        """
        INSERT INTO requests (project_id, label, model, endpoint_path, method, is_streaming,
                               prompt_tokens, completion_tokens, total_tokens, status_code,
                               latency_ms, created_at)
        VALUES (?, NULL, 'gpt-4o', '/chat/completions', 'POST', 0, 1, 1, ?, 200, 10,
                '2026-07-30T00:00:00+00:00')
        """,
        (project_id, total_tokens),
    )
    conn.commit()


def test_requests_tab_lists_recent_requests(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, 42)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}?tab=requests")

    assert response.status_code == 200
    assert "42" in response.text


def test_requests_json_polling_endpoint_returns_only_newer_rows(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, 10)
    client = _logged_in_client(conn, env_settings)
    first = client.get(f"/_gateway/dashboard/{project.id}/requests.json").json()
    last_id = first["requests"][0]["id"]
    _log(conn, project.id, 20)

    response = client.get(
        f"/_gateway/dashboard/{project.id}/requests.json", params={"after_id": last_id}
    )

    assert response.status_code == 200
    tokens = [r["total_tokens"] for r in response.json()["requests"]]
    assert tokens == [20]


def test_generate_key_shows_it_once_and_revoke_removes_access(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    client = _logged_in_client(conn, env_settings)

    response = client.post(f"/_gateway/dashboard/{project.id}/keys")
    assert response.status_code == 200
    assert "sk-proj-" in response.text

    key_row = crud.list_api_keys(conn, project.id)[0]
    revoke_response = client.post(
        f"/_gateway/dashboard/{project.id}/keys/{key_row['id']}/revoke", follow_redirects=False
    )
    assert revoke_response.status_code == 303

    keys_after = crud.list_api_keys(conn, project.id)
    assert keys_after[0]["revoked_at"] is not None


def test_generate_key_for_unknown_project_returns_404(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.post("/_gateway/dashboard/999/keys")

    assert response.status_code == 404


def test_revoke_key_belonging_to_a_different_project_returns_404(env_settings, conn):
    project_a = crud.create_project(conn, "A")
    project_b = crud.create_project(conn, "B")
    crud.create_api_key(conn, project_a.id)
    key_a = crud.list_api_keys(conn, project_a.id)[0]
    client = _logged_in_client(conn, env_settings)

    response = client.post(
        f"/_gateway/dashboard/{project_b.id}/keys/{key_a['id']}/revoke", follow_redirects=False
    )

    assert response.status_code == 404
    assert crud.list_api_keys(conn, project_a.id)[0]["revoked_at"] is None
