from app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("BACKEND_BASE_URL", "https://backend.example/api")
    monkeypatch.setenv("BACKEND_API_KEY", "real-key")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "session-secret")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/gateway-test.db")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "120")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.backend_base_url == "https://backend.example/api"
    assert settings.backend_api_key == "real-key"
    assert settings.dashboard_password == "secret"
    assert settings.session_secret == "session-secret"
    assert settings.database_path == "/tmp/gateway-test.db"
    assert settings.port == 9000
    assert settings.request_timeout_seconds == 120.0


def test_get_settings_defaults_database_path_and_port(monkeypatch):
    monkeypatch.setenv("BACKEND_BASE_URL", "https://backend.example/api")
    monkeypatch.setenv("BACKEND_API_KEY", "real-key")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "session-secret")
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("REQUEST_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_path == "/data/gateway.db"
    assert settings.port == 8080
    assert settings.request_timeout_seconds == 600.0
