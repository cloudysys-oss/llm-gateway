import pytest

from app import crud, queries
from app.db import get_connection, init_db


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def _log(conn, project_id, label, model, total_tokens, day):
    conn.execute(
        """
        INSERT INTO requests (project_id, label, model, endpoint_path, method, is_streaming,
                               prompt_tokens, completion_tokens, total_tokens, status_code,
                               latency_ms, created_at)
        VALUES (?, ?, ?, '/chat/completions', 'POST', 0, 1, 1, ?, 200, 10, ?)
        """,
        (project_id, label, model, total_tokens, f"{day}T00:00:00+00:00"),
    )
    conn.commit()


def test_project_summary_aggregates_requests(conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 100, "2026-07-29")
    _log(conn, project.id, "batch", "gpt-4o", 50, "2026-07-30")

    summary = queries.project_summary(conn, project.id)

    assert summary["request_count"] == 2
    assert summary["total_tokens"] == 150


def test_daily_totals_groups_by_day(conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 100, "2026-07-29")
    _log(conn, project.id, "batch", "gpt-4o", 50, "2026-07-29")
    _log(conn, project.id, "batch", "gpt-4o", 20, "2026-07-30")

    totals = queries.daily_totals(conn, project.id)

    assert totals == [
        {"day": "2026-07-29", "tokens": 150},
        {"day": "2026-07-30", "tokens": 20},
    ]


def test_breakdown_by_label_groups_and_sorts_desc(conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 10, "2026-07-30")
    _log(conn, project.id, None, "gpt-4o", 90, "2026-07-30")

    breakdown = queries.breakdown_by(conn, project.id, "label")

    assert breakdown[0]["key"] == "(未標記)"
    assert breakdown[0]["total_tokens"] == 90
    assert breakdown[1]["key"] == "batch"


def test_breakdown_by_model_groups(conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o-mini", 10, "2026-07-30")
    _log(conn, project.id, "batch", "gpt-4o", 90, "2026-07-30")

    breakdown = queries.breakdown_by(conn, project.id, "model")

    keys = {row["key"] for row in breakdown}
    assert keys == {"gpt-4o", "gpt-4o-mini"}


def test_recent_requests_orders_newest_first_and_respects_after_id(conn):
    project = crud.create_project(conn, "Demo")
    _log(conn, project.id, "batch", "gpt-4o", 10, "2026-07-29")
    _log(conn, project.id, "batch", "gpt-4o", 20, "2026-07-30")

    rows = queries.recent_requests(conn, project.id)
    assert [r["total_tokens"] for r in rows] == [20, 10]

    newer_only = queries.recent_requests(conn, project.id, after_id=rows[1]["id"])
    assert [r["total_tokens"] for r in newer_only] == [20]


def test_dashboard_overview_lists_all_projects_with_totals(conn):
    p1 = crud.create_project(conn, "A")
    crud.create_project(conn, "B")
    _log(conn, p1.id, "batch", "gpt-4o", 40, "2026-07-30")

    overview = queries.dashboard_overview(conn)

    by_name = {row["name"]: row for row in overview}
    assert by_name["A"]["total_tokens"] == 40
    assert by_name["A"]["request_count"] == 1
    assert by_name["B"]["total_tokens"] == 0
    assert by_name["B"]["request_count"] == 0
