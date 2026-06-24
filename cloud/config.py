"""Control-plane settings, loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://luna:luna@localhost:5435/lunaservice"
    session_secret: str = "dev-session-secret-change-me"

    identity_provider: str = "stub"  # "google" | "stub"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8100/auth/google/callback"

    base_url: str = "http://localhost:8100"

    runtime: str = "docker-local"  # "docker-local" | "fly-machines"
    tenant_database_url: str = ""  # shared tenant DB; falls back to database_url
    trusted_proxy_secret: str = "dev-proxy-secret"
    vault_root_key: str = "a" * 64  # 32 bytes hex-encoded

    github_pat: str = ""
    github_repo: str = "huemorgan/luna-service"
    admin_webhook_secret: str = "dev-webhook-secret"

    # Luna Marketplaces (plan 022) — separate product on its own domain. The
    # Cursor plugin-dev kit lives there; we expose a stable branded path that
    # redirects to it, so updating the zip there updates our download with no
    # site rebuild.
    marketplace_plugin_zip_url: str = (
        "https://marketplaces.com.ai/downloads/luna-plugin-cursor.zip"
    )

    model_config = {"env_prefix": "CLOUD_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
