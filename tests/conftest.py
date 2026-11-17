import pytest

from app.config import get_settings
from app.db import get_connection, init_db


@pytest.fixture
def env_settings(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("BACKEND_API_KEY", "real-backend-key")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-pass")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def conn(env_settings):
    connection = get_connection(env_settings.database_path)
    init_db(connection)
    yield connection
    connection.close()


def override_get_db(conn):
    """Build a FastAPI dependency override that yields a fixed connection.

    Must be an actual generator function (not just something returning an
    iterator): FastAPI decides whether to treat an overridden dependency as a
    generator by inspecting the override callable itself via
    inspect.isgeneratorfunction. `lambda: iter([conn])` is not a generator
    function, so FastAPI would use the returned iterator object as the
    dependency value instead of extracting conn from it.
    """

    def _get_db():
        yield conn

    return _get_db
