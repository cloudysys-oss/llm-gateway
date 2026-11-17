import pytest

from app import crud
from app.db import get_connection, init_db


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_create_project_returns_active_project(conn):
    project = crud.create_project(conn, "Demo Project")

    assert project.id is not None
    assert project.name == "Demo Project"
    assert project.status == "active"


def test_list_projects_returns_created_projects(conn):
    crud.create_project(conn, "A")
    crud.create_project(conn, "B")

    projects = crud.list_projects(conn)

    assert {p.name for p in projects} == {"A", "B"}


def test_set_project_status_updates_status(conn):
    project = crud.create_project(conn, "Demo")

    crud.set_project_status(conn, project.id, "disabled")

    assert crud.get_project(conn, project.id).status == "disabled"


def test_create_api_key_resolves_back_to_project(conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)

    resolved = crud.get_project_by_key(conn, raw_key)

    assert resolved is not None
    assert resolved.id == project.id


def test_revoked_key_no_longer_resolves(conn):
    project = crud.create_project(conn, "Demo")
    raw_key = crud.create_api_key(conn, project.id)
    key_row = crud.list_api_keys(conn, project.id)[0]

    crud.revoke_api_key(conn, key_row["id"])

    assert crud.get_project_by_key(conn, raw_key) is None


def test_unknown_key_resolves_to_none(conn):
    assert crud.get_project_by_key(conn, "sk-proj-does-not-exist") is None


def test_log_request_inserts_row(conn):
    project = crud.create_project(conn, "Demo")

    crud.log_request(
        conn,
        project_id=project.id,
        label="batch",
        model="gpt-4o",
        endpoint_path="/chat/completions",
        method="POST",
        is_streaming=False,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        status_code=200,
        latency_ms=120,
    )

    row = conn.execute("SELECT * FROM requests").fetchone()
    assert row["project_id"] == project.id
    assert row["label"] == "batch"
    assert row["total_tokens"] == 15
    assert row["is_streaming"] == 0
