"""Local browser harness for plan 045's read-only admin page."""

from fastapi import FastAPI

app = FastAPI()
state = {"mode": "healthy"}

HEALTHY_STATS = {
    "configured": True,
    "reachable": True,
    "authorized": True,
    "stats": {
        "version": "0.2.0",
        "uptime_s": 7260,
        "db": {"ok": True, "latency_ms": 5},
        "webhook": {
            "configured": True,
            "pending_updates": 0,
            "last_error": None,
        },
        "totals": {
            "accounts": 2,
            "active_chats": 14,
            "messages_24h_in": 54,
            "messages_24h_out": 38,
            "forward_failures_24h": 1,
        },
        "hourly": [
            {"hour": f"2026-07-16T{hour:02d}:00:00Z", "in": hour % 7, "out": hour % 5}
            for hour in range(24)
        ],
        "accounts": [],
    },
}

INSTANCES = [
    {
        "agent_id": "00000000-0000-0000-0000-000000000020",
        "name": "Support Luna",
        "slug": "acme-support",
        "status": "running",
        "plugin_installed": True,
        "account": {
            "status": "active",
            "enabled": True,
            "bot": {
                "id": 123456789,
                "username": "acme_support_bot",
                "first_name": "Support Luna",
            },
            "webhook": {
                "configured": True,
                "pending_updates": 0,
                "last_error": None,
            },
            "privacy_mode": True,
            "group_visibility": "mentions only",
            "last_activity_at": "2026-07-16T12:00:00Z",
            "messages_24h_in": 42,
            "messages_24h_out": 31,
            "error": None,
        },
    },
    {
        "agent_id": "00000000-0000-0000-0000-000000000021",
        "name": "Ops Luna",
        "slug": "acme-ops",
        "status": "sleeping",
        "plugin_installed": True,
        "account": {
            "status": "degraded",
            "enabled": True,
            "bot": {
                "id": 987654321,
                "username": "acme_ops_bot",
                "first_name": "Ops Luna",
            },
            "webhook": {
                "configured": False,
                "pending_updates": 3,
                "last_error": "recent delivery failure",
            },
            "privacy_mode": False,
            "group_visibility": "all group messages",
            "last_activity_at": None,
            "messages_24h_in": 12,
            "messages_24h_out": 7,
            "error": "webhook needs attention",
        },
    },
]


@app.get("/api/auth/me")
async def auth_me():
    return {
        "user": {
            "id": "admin",
            "email": "admin@example.com",
            "name": "Admin",
            "avatar_url": None,
            "is_admin": True,
        },
        "account": None,
    }


@app.get("/api/admin/telegram/stats")
async def telegram_stats():
    if state["mode"] == "unconfigured":
        return {"configured": False}
    if state["mode"] == "unauthorized":
        return {"configured": True, "reachable": True, "authorized": False}
    if state["mode"] == "unreachable":
        return {"configured": True, "reachable": False}
    return HEALTHY_STATS


@app.get("/api/admin/telegram/instances")
async def telegram_instances():
    return INSTANCES if state["mode"] == "healthy" else []


@app.post("/api/test/telegram-state/{mode}")
async def set_telegram_state(mode: str):
    if mode not in {"healthy", "unconfigured", "unauthorized", "unreachable"}:
        return {"ok": False}
    state["mode"] = mode
    return {"ok": True, "mode": mode}
