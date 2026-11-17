from app.db import get_connection, init_db


def test_init_db_creates_expected_tables():
    conn = get_connection(":memory:")
    init_db(conn)

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert {"projects", "api_keys", "requests"} <= tables


def test_get_connection_returns_row_factory_rows():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO projects (name, status, created_at) VALUES ('demo', 'active', '2026-07-30')"
    )
    conn.commit()

    row = conn.execute("SELECT name, status FROM projects").fetchone()

    assert row["name"] == "demo"
    assert row["status"] == "active"
