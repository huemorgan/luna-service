"""Luna Service control plane — FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from cloud.api.agent_routes import router as agent_router
from cloud.api.auth_routes import router as auth_router
from cloud.api.proxy import router as proxy_router
from cloud.config import get_settings
from cloud.db.models import Base
from cloud.db.session import dispose_engine, get_session_factory

UI_DIR = Path(__file__).parent / "ui" / "dist"


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env == "dev" else [settings.base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(proxy_router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "service": "luna-service"}

    if UI_DIR.is_dir():
        from fastapi.responses import FileResponse

        app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="ui-assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            file_path = UI_DIR / path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(UI_DIR / "index.html")

    return app


app = create_app()
