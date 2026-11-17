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


def _log(conn, project_id, label, model, total_tokens):
    conn.execute(
        """
        INSERT INTO requests (project_id, label, model, endpoint_path, method, is_streaming,
                               prompt_tokens, completion_tokens, total_tokens, status_code,
                               latency_ms, created_at)
        VALUES (?, ?, ?, '/chat/completions', 'POST', 0, 1, 1, ?, 200, 10, '2026-07-30T00:00:00+00:00')
        """,
        (project_id, label, model, total_tokens),
    )
    conn.commit()


def test_export_requests_csv(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 42)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}/export.csv?tab=requests")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "42" in response.text
    assert "batch" in response.text


def test_export_by_label_csv(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 42)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}/export.csv?tab=label")

    assert response.status_code == 200
    assert "batch" in response.text


def test_export_for_unknown_project_returns_404(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.get("/_gateway/dashboard/999/export.csv")

    assert response.status_code == 404


def test_export_with_invalid_tab_returns_400(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}/export.csv?tab=not-a-real-tab")

    assert response.status_code == 400
