"""Request/outbound timing instrumentation (plan 037-SPEED101, phase 0).

Pure ASGI — deliberately not BaseHTTPMiddleware, which would force every
streaming response (SSE, proxy) through an in-process bridge task.
"""

from __future__ import annotations

import logging
import random
import time

log = logging.getLogger("cloud.timing")

# Requests slower than this always log; faster ones are sampled.
SLOW_MS = 250
SAMPLE_RATE = 0.01


class TimingMiddleware:
    """Logs one structured line per HTTP request and adds a Server-Timing header.

    Duration covers first byte of the response body (TTFB for streams), so a
    300 s SSE stream doesn't report as a 300 s request.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        t0 = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                dur_ms = (time.perf_counter() - t0) * 1000
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", f"app;dur={dur_ms:.0f}".encode()))
                message = {**message, "headers": headers}
                self._log(scope, message["status"], dur_ms)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _log(scope, status: int, dur_ms: float) -> None:
        if dur_ms < SLOW_MS and random.random() > SAMPLE_RATE:
            return
        route = scope.get("route")
        path = getattr(route, "path", None) or scope.get("path", "?")
        log.info(
            "req method=%s route=%s status=%s duration_ms=%.0f",
            scope.get("method", "?"), path, status, dur_ms,
        )


# Outbound httpx timing — attach via AsyncClient(event_hooks=httpx_timing_hooks("gateway")).
OUTBOUND_SLOW_MS = 500


def httpx_timing_hooks(name: str) -> dict:
    async def on_request(request):
        request.extensions["_t0"] = time.perf_counter()

    async def on_response(response):
        t0 = response.request.extensions.get("_t0")
        if t0 is None:
            return
        dur_ms = (time.perf_counter() - t0) * 1000
        if dur_ms >= OUTBOUND_SLOW_MS:
            url = response.request.url
            log.info(
                "outbound client=%s method=%s host=%s path=%s status=%s duration_ms=%.0f",
                name, response.request.method, url.host, url.path,
                response.status_code, dur_ms,
            )

    return {"request": [on_request], "response": [on_response]}
