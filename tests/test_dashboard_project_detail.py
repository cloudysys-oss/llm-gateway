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


def test_overview_tab_shows_totals_and_chart(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 100)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}")

    assert response.status_code == 200
    assert "100" in response.text
    assert "<svg" in response.text


def test_by_label_tab_shows_breakdown(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 100)
    _log(conn, project.id, None, "gpt-4o", 20)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}?tab=label")

    assert response.status_code == 200
    assert "batch" in response.text
    assert "未標記" in response.text


def test_by_model_tab_shows_breakdown(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o-mini", 20)
    client = _logged_in_client(conn, env_settings)

    response = client.get(f"/_gateway/dashboard/{project.id}?tab=model")

    assert response.status_code == 200
    assert "gpt-4o-mini" in response.text


def test_unknown_project_returns_404(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.get("/_gateway/dashboard/999")

    assert response.status_code == 404


def test_toggle_status_disables_then_reenables_project(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    client = _logged_in_client(conn, env_settings)

    response = client.post(f"/_gateway/dashboard/{project.id}/toggle-status")
    assert response.status_code == 303
    assert crud.get_project(conn, project.id).status == "disabled"

    client.post(f"/_gateway/dashboard/{project.id}/toggle-status")
    assert crud.get_project(conn, project.id).status == "active"


def test_toggle_status_for_unknown_project_returns_404(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.post("/_gateway/dashboard/999/toggle-status")

    assert response.status_code == 404
