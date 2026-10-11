"""Production middleware: one request log line per request and the rate limit (pure ASGI, standard library only).

The request line carries the method, the path (no query string), the status and the duration in milliseconds, as JSON on stdout.
It never carries a header, a body or the demo identity. A refused request gets HTTP 429 with the API's usual error body.
"""

from __future__ import annotations

import json
import logging
import sys
import time

from app.core.config import Settings
from app.core.ratelimit import SlidingWindowLimiter, client_key

log = logging.getLogger("ddr.request")
RATE_LIMITED_MESSAGE = ("The public demo is shared, so it limits how often changes can be made. "
                        "Please wait a few minutes and try again.")


def configure_request_logging(*, stream=None) -> None:
    if any(getattr(h, "_ddr", False) for h in log.handlers):
        return
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._ddr = True                                   # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class RequestMiddleware:
    def __init__(self, app, *, settings: Settings, limiter: SlidingWindowLimiter | None, log_requests: bool):
        self.app = app
        self.limiter = limiter
        self.trust = settings.trust_forwarded_for
        self.log_requests = log_requests

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        method, path = scope["method"], scope["path"]
        peer = (scope.get("client") or (None,))[0]
        ip = client_key(scope.get("headers", []), peer, self.trust)
        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        decision = self.limiter.check(ip, method, path) if self.limiter else None
        try:
            if decision is not None and not decision.allowed:
                await self._refuse(send_wrapper, decision.retry_after, decision.scope)
            else:
                await self.app(scope, receive, send_wrapper)
        finally:
            if self.log_requests:
                log.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": method, "path": path,
                                     "status": status["code"], "ms": round((time.perf_counter() - started) * 1000, 1), "ip": ip}))

    @staticmethod
    async def _refuse(send, retry_after: int, scope_name: str) -> None:
        message = RATE_LIMITED_MESSAGE if scope_name != "pipeline" else (
            "Pipeline runs are limited on the shared public demo. Please wait a few minutes and try again.")
        body = json.dumps({"error": {"code": "rate_limited", "message": message,
                                     "detail": {"retry_after_seconds": retry_after, "limit": scope_name}}}).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"retry-after", str(retry_after).encode())]})
        await send({"type": "http.response.body", "body": body})
