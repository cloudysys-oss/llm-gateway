from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import crud
from app.db import get_db
from app.proxy import resolve_project

from .conftest import override_get_db


def _build_test_app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(project=Depends(resolve_project)):
        return {"project_id": project.id, "project_name": project.name}

    return app


def test_missing_authorization_header_returns_401(env_settings, conn):
    app = _build_test_app()
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app)

    response = client.get("/whoami")

    assert response.status_code == 401


def test_unknown_key_returns_401(env_settings, conn):
    app = _build_test_app()
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app)

    response = client.get("/whoami", headers={"Authorization": "Bearer sk-proj-nope"})

    assert response.status_code == 401


def test_valid_key_resolves_project(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    app = _build_test_app()
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app)

    response = client.get("/whoami", headers={"Authorization": f"Bearer {raw_key}"})

    assert response.status_code == 200
    assert response.json() == {"project_id": project.id, "project_name": "Demo"}


def test_disabled_project_returns_403(env_settings, conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    conn.execute("UPDATE projects SET status = 'disabled' WHERE id = ?", (project.id,))
    conn.commit()
    app = _build_test_app()
    app.dependency_overrides[get_db] = override_get_db(conn)
    client = TestClient(app)

    response = client.get("/whoami", headers={"Authorization": f"Bearer {raw_key}"})

    assert response.status_code == 403
