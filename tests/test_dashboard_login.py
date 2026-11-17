from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.dashboard.routes import router
from app.db import get_db

from .conftest import override_get_db


def _build_test_app(conn, settings):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db(conn)
    return app


def test_get_login_page_renders_form(env_settings, conn):
    client = TestClient(_build_test_app(conn, env_settings))

    response = client.get("/_gateway/login")

    assert response.status_code == 200
    assert "password" in response.text.lower()


def test_wrong_password_returns_401_and_does_not_start_session(env_settings, conn):
    client = TestClient(_build_test_app(conn, env_settings), follow_redirects=False)

    response = client.post("/_gateway/login", data={"password": "wrong"})

    assert response.status_code == 401
    dashboard_response = client.get("/_gateway/dashboard")
    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"] == "/_gateway/login"


def test_correct_password_redirects_and_starts_session(env_settings, conn):
    client = TestClient(_build_test_app(conn, env_settings), follow_redirects=False)

    response = client.post("/_gateway/login", data={"password": env_settings.dashboard_password})

    assert response.status_code == 303
    assert response.headers["location"] == "/_gateway/dashboard"


def test_logout_clears_session(env_settings, conn):
    client = TestClient(_build_test_app(conn, env_settings), follow_redirects=False)
    client.post("/_gateway/login", data={"password": env_settings.dashboard_password})

    client.get("/_gateway/logout")
    dashboard_response = client.get("/_gateway/dashboard", follow_redirects=False)

    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"] == "/_gateway/login"
