import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import auth


@dataclass
class Project:
    id: int
    name: str
    status: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_project(conn: sqlite3.Connection, name: str) -> Project:
    created_at = _now()
    cur = conn.execute(
        "INSERT INTO projects (name, status, created_at) VALUES (?, 'active', ?)",
        (name, created_at),
    )
    conn.commit()
    return Project(id=cur.lastrowid, name=name, status="active", created_at=created_at)


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute(
        "SELECT id, name, status, created_at FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return [Project(**dict(row)) for row in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[Project]:
    row = conn.execute(
        "SELECT id, name, status, created_at FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return Project(**dict(row)) if row else None


def set_project_status(conn: sqlite3.Connection, project_id: int, status: str) -> None:
    conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
    conn.commit()


def create_api_key(conn: sqlite3.Connection, project_id: int) -> str:
    raw_key = auth.generate_api_key()
    conn.execute(
        "INSERT INTO api_keys (project_id, key_hash, key_prefix, created_at) VALUES (?, ?, ?, ?)",
        (project_id, auth.hash_key(raw_key), auth.display_prefix(raw_key), _now()),
    )
    conn.commit()
    return raw_key


def revoke_api_key(conn: sqlite3.Connection, key_id: int) -> None:
    conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?", (_now(), key_id))
    conn.commit()


def list_api_keys(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, key_prefix, created_at, revoked_at FROM api_keys
        WHERE project_id = ? ORDER BY created_at DESC
        """,
        (project_id,),
    ).fetchall()


def get_project_by_key(conn: sqlite3.Connection, raw_key: str) -> Optional[Project]:
    key_hash = auth.hash_key(raw_key)
    row = conn.execute(
        """
        SELECT p.id, p.name, p.status, p.created_at
        FROM api_keys k JOIN projects p ON p.id = k.project_id
        WHERE k.key_hash = ? AND k.revoked_at IS NULL
        """,
        (key_hash,),
    ).fetchone()
    return Project(**dict(row)) if row else None


def log_request(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    label: Optional[str],
    model: Optional[str],
    endpoint_path: str,
    method: str,
    is_streaming: bool,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
    status_code: Optional[int],
    latency_ms: Optional[int],
) -> None:
    conn.execute(
        """
        INSERT INTO requests (
            project_id, label, model, endpoint_path, method, is_streaming,
            prompt_tokens, completion_tokens, total_tokens, status_code, latency_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            label,
            model,
            endpoint_path,
            method,
            int(is_streaming),
            prompt_tokens,
            completion_tokens,
            total_tokens,
            status_code,
            latency_ms,
            _now(),
        ),
    )
    conn.commit()
