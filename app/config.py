import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    backend_base_url: str
    backend_api_key: str
    dashboard_password: str
    session_secret: str
    database_path: str
    port: int
    request_timeout_seconds: float


@lru_cache
def get_settings() -> Settings:
    return Settings(
        backend_base_url=os.environ["BACKEND_BASE_URL"],
        backend_api_key=os.environ["BACKEND_API_KEY"],
        dashboard_password=os.environ["DASHBOARD_PASSWORD"],
        session_secret=os.environ["SESSION_SECRET"],
        database_path=os.environ.get("DATABASE_PATH", "/data/gateway.db"),
        port=int(os.environ.get("PORT", "8080")),
        request_timeout_seconds=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "600")),
    )
