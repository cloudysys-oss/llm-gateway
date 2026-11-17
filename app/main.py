from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .dashboard.routes import router as dashboard_router
from .db import get_connection, init_db
from .proxy import router as proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = get_connection(settings.database_path)
    init_db(conn)
    conn.close()
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

    @app.get("/_gateway/healthz")
    def healthz():
        return {"status": "ok"}

    # dashboard_router MUST be included before proxy_router: proxy_router's
    # catch-all "/{path:path}" route would otherwise shadow every dashboard path.
    app.include_router(dashboard_router)
    app.include_router(proxy_router)

    return app


# NOTE: `app` is intentionally NOT instantiated at module import time here.
# create_app() calls get_settings(), which reads required env vars via
# os.environ[...] with no defaults. Building the app eagerly at import time
# would raise KeyError whenever this module is merely imported before those
# env vars are set (e.g. pytest collecting tests/test_integration.py, which
# imports `create_app` before the env_settings fixture runs). Uvicorn is
# instead pointed at the factory itself (`app.main:create_app` with
# `--factory`, see Dockerfile), so the app is only built once env vars are
# actually in place.
