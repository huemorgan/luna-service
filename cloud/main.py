"""Luna Service control plane — FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from cloud.api.admin_routes import router as admin_router
from cloud.api.agent_routes import router as agent_router
from cloud.api.auth_routes import router as auth_router
from cloud.api.gateway_admin_routes import router as gateway_admin_router
from cloud.api.gateway_proxy import router as gateway_proxy_router
from cloud.api.proxy import router as proxy_router
from cloud.api.relay_routes import router as relay_router
from cloud.config import get_settings
from cloud.db.models import Base
from cloud.db.session import dispose_engine

UI_DIR = Path(__file__).parent / "ui" / "dist"

RESERVED_PREFIXES = (
    "/api/", "/auth/", "/healthz",
    "/assets/", "/favicon", "/icons",
    "/a/", "/proxy/",
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
            is_api = any(path.startswith(p) for p in RESERVED_PREFIXES)
            if not is_api:
                return FileResponse(UI_DIR / "index.html")

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text
    from cloud.db.session import _get_engine
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for col, coltype in [
            ("error_message", "TEXT"),
            ("error_at", "TIMESTAMPTZ"),
            ("slug", "TEXT"),
            ("cached_metrics", "JSONB"),
            ("cached_metrics_at", "TIMESTAMPTZ"),
            ("image_version", "TEXT"),
            ("config_overrides", "JSONB"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE agents ADD COLUMN IF NOT EXISTS {col} {coltype}"
            ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT false"
        ))
        await conn.execute(text(
            "ALTER TABLE luna_images ADD COLUMN IF NOT EXISTS image_config JSONB"
        ))
        for col, coltype in [
            ("actor_ip", "TEXT"),
            ("before_state", "JSONB"),
            ("after_state", "JSONB"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS {col} {coltype}"
            ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at DESC)"
        ))
        await conn.execute(text(
            "ALTER TABLE luna_images ADD COLUMN IF NOT EXISTS cache_warmed_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE luna_images ADD COLUMN IF NOT EXISTS git_branch TEXT"
        ))
        for col, coltype in [
            ("sdk_major", "INTEGER"),
            ("sdk_min_major", "INTEGER"),
            ("release_notes", "TEXT"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE luna_images ADD COLUMN IF NOT EXISTS {col} {coltype}"
            ))
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS app_settings ("
            "key TEXT PRIMARY KEY, value JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        await conn.execute(text(
            "UPDATE users SET is_admin = true WHERE email = 'vaselin@gmail.com' AND is_admin = false"
        ))
        # Backfill NULL slugs from account slug + agent name
        await conn.execute(text("""
            UPDATE agents SET slug = accounts.slug || '-' || LOWER(REGEXP_REPLACE(agents.name, '[^a-zA-Z0-9]+', '-', 'g'))
            FROM accounts
            WHERE agents.account_id = accounts.id AND agents.slug IS NULL
        """))
        # Clean up destroyed agents with no valid runtime
        await conn.execute(text("""
            DELETE FROM agents WHERE status IN ('error', 'provisioning') AND runtime_ref IS NULL AND slug IS NULL
        """))

    # Seed the credential-gateway service registry (insert-if-missing only)
    from cloud.db.session import get_session as _get_db
    from cloud.gateway.registry import seed_services
    from cloud.gateway.model_registry import seed_models
    async with _get_db() as db:
        await seed_services(db)
        await seed_models(db)  # Plan 018: system model catalog
        await db.commit()

    # Composio trigger-relay forwarder (plan 015)
    import asyncio
    import os
    forwarder_task = None
    if os.environ.get("CLOUD_RELAY_FORWARDER", "1") == "1":
        from cloud.relay.forwarder import forwarder_loop
        forwarder_task = asyncio.create_task(forwarder_loop())

    yield

    if forwarder_task:
        forwarder_task.cancel()
        try:
            await forwarder_task
        except (asyncio.CancelledError, Exception):
            pass
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

    # Marketing-site public routes (plan 021). Declared here so they win over
    # the SPA 404 fallback and emit real text/xml for crawlers.
    MARKETING_PATHS = (
        "/", "/products/hosting", "/products/open-source", "/products/marketplace",
        "/pricing", "/security", "/about",
    )

    @app.get("/robots.txt")
    async def robots_txt():
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /dashboard\n"
            "Disallow: /api/\n"
            f"Sitemap: {settings.base_url.rstrip('/')}/sitemap.xml\n"
        )
        return Response(content=body, media_type="text/plain")

    @app.get("/sitemap.xml")
    async def sitemap_xml():
        base = settings.base_url.rstrip("/")
        urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in MARKETING_PATHS)
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>"
        )
        return Response(content=body, media_type="application/xml")

    # Branded download for the Cursor plugin-dev kit (plan 022). 302s to the
    # canonical zip hosted on marketplaces.com.ai, so updating it there updates
    # our download with no rebuild.
    @app.get("/downloads/luna-plugin-cursor.zip")
    async def plugin_cursor_zip():
        return RedirectResponse(settings.marketplace_plugin_zip_url, status_code=302)

    @app.get("/")
    async def root():
        if UI_DIR.is_dir():
            return FileResponse(UI_DIR / "index.html")
        return {"service": "luna-service", "status": "no UI built"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(gateway_admin_router)
    app.include_router(agent_router)
    app.include_router(relay_router)
    app.include_router(gateway_proxy_router)
    app.include_router(proxy_router)

    return app


app = create_app()
