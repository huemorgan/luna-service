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

    # WhatsApp gateway monitoring (plan 034). URL of the always-on Baileys
    # gateway (Render: luna-wa-gateway) and its admin key — the key stays
    # server-side; the UI only ever sees proxied stats.
    whatsapp_gateway_url: str = ""
    whatsapp_gateway_admin_key: str = ""
    # Marketplace serving plugin-whatsapp (>=0.6.0) for the connect flow.
    whatsapp_plugin_marketplace_url: str = "https://luna-marketplaces.onrender.com/mp/official/"

    # Scheduler service monitoring + provisioning (plan 035). URL of the
    # always-on trigger service (Render: luna-scheduler) and its admin key —
    # the key stays server-side; the UI only ever sees proxied stats.
    scheduler_service_url: str = ""
    scheduler_service_admin_key: str = ""

    # Plan 039: global billing mode — off | observe | shadow | enforce.
    # Per-account enforcement overrides (039/010) resolve as the maximum of
    # this global mode and the account override.
    billing_mode: str = "off"

    # Plan 039/007: Stripe. The secret key must be a restricted key in prod
    # (scopes listed in plans/039-pricing-billing/006-stripe-account-setup/
    # test-mode-bindings.md). livemode is declared explicitly so a key that
    # doesn't match the declared mode fails closed instead of charging the
    # wrong environment. payments_enabled is DERIVED from these plus price
    # bindings — a missing value degrades the UI to "Coming soon".
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_livemode: bool = False

    model_config = {"env_prefix": "CLOUD_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
