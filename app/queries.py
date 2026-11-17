import sqlite3

_BREAKDOWN_COLUMNS = ("label", "model")


def project_summary(conn: sqlite3.Connection, project_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS request_count,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(AVG(total_tokens), 0) AS avg_tokens
        FROM requests WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    return dict(row)


def daily_totals(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS day, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM requests WHERE project_id = ?
        GROUP BY day ORDER BY day
        """,
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def breakdown_by(conn: sqlite3.Connection, project_id: int, column: str) -> list[dict]:
    if column not in _BREAKDOWN_COLUMNS:
        raise ValueError(f"column must be one of {_BREAKDOWN_COLUMNS}")
    rows = conn.execute(
        f"""
        SELECT COALESCE({column}, '(未標記)') AS key,
               COUNT(*) AS request_count,
               COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM requests WHERE project_id = ?
        GROUP BY key ORDER BY total_tokens DESC
        """,
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_requests(
    conn: sqlite3.Connection, project_id: int, limit: int = 50, after_id: int = 0
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, created_at, label, model, endpoint_path,
               prompt_tokens, completion_tokens, total_tokens, status_code
        FROM requests WHERE project_id = ? AND id > ?
        ORDER BY id DESC LIMIT ?
        """,
        (project_id, after_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def dashboard_overview(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.status,
               COUNT(r.id) AS request_count,
               COALESCE(SUM(r.total_tokens), 0) AS total_tokens,
               COALESCE(SUM(
                   CASE WHEN substr(r.created_at, 1, 10) = date('now') THEN 1 ELSE 0 END
               ), 0) AS today_request_count,
               COALESCE(SUM(
                   CASE WHEN substr(r.created_at, 1, 10) = date('now') THEN r.total_tokens ELSE 0 END
               ), 0) AS today_total_tokens,
               COALESCE(SUM(
                   CASE WHEN substr(r.created_at, 1, 7) = strftime('%Y-%m', 'now') THEN 1 ELSE 0 END
               ), 0) AS month_request_count,
               COALESCE(SUM(
                   CASE WHEN substr(r.created_at, 1, 7) = strftime('%Y-%m', 'now') THEN r.total_tokens ELSE 0 END
               ), 0) AS month_total_tokens
        FROM projects p LEFT JOIN requests r ON r.project_id = p.id
        GROUP BY p.id ORDER BY p.created_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]
