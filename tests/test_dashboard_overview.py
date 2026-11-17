from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app import crud, queries
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


def test_dashboard_requires_login(env_settings, conn):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=env_settings.session_secret)
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app, follow_redirects=False)

    response = client.get("/_gateway/dashboard")

    assert response.status_code == 303


def test_dashboard_lists_existing_projects(env_settings, conn):
    crud.create_project(conn, "合約審查機器人")
    client = _logged_in_client(conn, env_settings)

    response = client.get("/_gateway/dashboard")

    assert response.status_code == 200
    assert "合約審查機器人" in response.text


def test_creating_project_shows_key_once(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.post("/_gateway/dashboard/projects", data={"name": "新專案"})

    assert response.status_code == 200
    assert "sk-proj-" in response.text

    projects = crud.list_projects(conn)
    assert any(p.name == "新專案" for p in projects)


def test_creating_project_with_blank_name_returns_400(env_settings, conn):
    client = _logged_in_client(conn, env_settings)

    response = client.post("/_gateway/dashboard/projects", data={"name": "   "})

    assert response.status_code == 400
    assert crud.list_projects(conn) == []


def _log_at(conn, project_id, total_tokens, created_at):
    conn.execute(
        """
        INSERT INTO requests (project_id, label, model, endpoint_path, method, is_streaming,
                               prompt_tokens, completion_tokens, total_tokens, status_code,
                               latency_ms, created_at)
        VALUES (?, NULL, 'gpt-4o', '/chat/completions', 'POST', 0, 1, 1, ?, 200, 10, ?)
        """,
        (project_id, total_tokens, created_at),
    )
    conn.commit()


def test_dashboard_shows_today_and_month_totals_separately_from_all_time(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    now = datetime.now(timezone.utc)
    last_month = now - timedelta(days=40)
    _log_at(conn, project.id, 10, now.isoformat())
    _log_at(conn, project.id, 90, last_month.isoformat())
    client = _logged_in_client(conn, env_settings)

    response = client.get("/_gateway/dashboard")

    assert response.status_code == 200
    overview = queries.dashboard_overview(conn)
    row = next(r for r in overview if r["id"] == project.id)
    assert row["today_total_tokens"] == 10
    assert row["today_request_count"] == 1
    assert row["month_total_tokens"] == 10
    assert row["total_tokens"] == 100
