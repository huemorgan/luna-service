"""Luna Service control plane — FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from cloud.api.agent_routes import router as agent_router
from cloud.api.auth_routes import router as auth_router
from cloud.api.proxy import router as proxy_router
from cloud.config import get_settings
from cloud.db.models import Base
from cloud.db.session import dispose_engine

UI_DIR = Path(__file__).parent / "ui" / "dist"

RESERVED_PREFIXES = (
    "/api/", "/auth/", "/healthz",
    "/assets/", "/favicon", "/icons",
)


class SPAStaticMiddleware(BaseHTTPMiddleware):
    """Serve UI static files before route matching so the proxy
    catch-all doesn't intercept asset requests."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in ("/assets/",)):
            file = UI_DIR / path.lstrip("/")
            if file.is_file():
                return FileResponse(file)

        if path in ("/favicon.svg", "/icons.svg"):
            file = UI_DIR / path.lstrip("/")
            if file.is_file():
                return FileResponse(file)

        response: Response = await call_next(request)

        if response.status_code == 404 and UI_DIR.is_dir():
            first = path.split("/")[1] if "/" in path else ""
            is_api = any(path.startswith(p) for p in RESERVED_PREFIXES)
            if not is_api and first:
                pass
            elif not is_api:
                return FileResponse(UI_DIR / "index.html")

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    from cloud.db.session import _get_engine
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Luna Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(SPAStaticMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env == "dev" else [settings.base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "service": "luna-service"}

    @app.get("/")
    async def root():
        if UI_DIR.is_dir():
            return FileResponse(UI_DIR / "index.html")
        return {"service": "luna-service", "status": "no UI built"}

    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(proxy_router)

    return app


app = create_app()
