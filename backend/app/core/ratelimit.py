"""In-process rate limiting for the public demo (standard library only).

Two sliding-window limits, both keyed by the client address (the FIRST X-Forwarded-For address when the proxy header is trusted,
otherwise the socket peer):

  * mutating requests (POST, PUT, PATCH, DELETE)                      about 30 per 10 minutes
  * pipeline runs and re-synthesis (POST /decisions/{id}/pipeline-runs, POST /assessments/{id}/syntheses)   about 5 per 10 minutes

The state lives in the memory of one process. That is intentional: the hosted demo is a single free web service, and a restart
(a deploy or a cold start) clears it. It protects a shared demo from accidental loops and casual abuse; it is not a security boundary,
because a client can send its own X-Forwarded-For. It never reads or changes a decision, a score or the database.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
HEAVY = re.compile(r"^/(decisions/[^/]+/pipeline-runs|assessments/[^/]+/syntheses)/?$")
MAX_KEYS = 10_000                      # bounded memory: the oldest idle keys are dropped first


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0
    scope: str = ""


class SlidingWindowLimiter:
    def __init__(self, window_seconds: int, mutations: int, heavy: int, clock=time.monotonic):
        self.window = max(1, int(window_seconds))
        self.limits = {"mutation": int(mutations), "pipeline": int(heavy)}
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def classify(self, method: str, path: str) -> list[str]:
        if method.upper() not in MUTATING:
            return []
        scopes = ["mutation"]
        if method.upper() == "POST" and HEAVY.match(path):
            scopes.append("pipeline")
        return scopes

    def check(self, key: str, method: str, path: str) -> Decision:
        """Counts the request when it is allowed. A refused request is not counted, so the window drains normally."""
        scopes = [s for s in self.classify(method, path) if self.limits[s] > 0]
        if not scopes:
            return Decision(True)
        now = self._clock()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._evict(now)
            queues = {}
            for scope in scopes:
                q = self._hits.setdefault((key, scope), deque())
                while q and now - q[0] >= self.window:
                    q.popleft()
                queues[scope] = q
            for scope, q in queues.items():
                if len(q) >= self.limits[scope]:
                    return Decision(False, retry_after=max(1, int(self.window - (now - q[0])) + 1), scope=scope)
            for q in queues.values():
                q.append(now)
        return Decision(True)

    def _evict(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]:
            del self._hits[k]
        while len(self._hits) > MAX_KEYS:
            del self._hits[next(iter(self._hits))]


def client_key(headers: list[tuple[bytes, bytes]], peer: str | None, trust_forwarded_for: bool) -> str:
    """The first X-Forwarded-For address when trusted, else the socket peer."""
    if trust_forwarded_for:
        for name, value in headers:
            if name == b"x-forwarded-for":
                first = value.decode("latin-1").split(",")[0].strip()
                if first:
                    return first[:64]
    return peer or "unknown"
