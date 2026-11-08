"""Rate limiting, applied to the whole API in one place.

Why: sign-in, Maps lookups, Gemini analysis and outbound calls all cost money or reach real
people. Without limits, one script (or one bug in the web app) can run up the bill or ring an
owner's phone over and over.

How it works: a sliding window per (rule, caller). The caller is the signed-in user when the
request carries a valid session token, otherwise the client address. Going over the limit gives
HTTP 429 with a Retry-After header.

Limits: counts are kept in memory, so each API instance counts on its own. That is a deliberate
first layer: it stops a runaway client and a casual abuser. A shared limit across instances
needs a shared store (Redis or the database) or Cloud Armor in front, which is a later step.
Money-critical limits that must be exact (one live call per PG) are enforced in the database.
"""

import os
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import jwt

MINUTE = 60
HOUR = 3600
MAX_TRACKED = 50_000  # memory bound: callers tracked at once


@dataclass(frozen=True)
class Rule:
    name: str
    method: str
    pattern: re.Pattern
    limit: int
    window: int
    by: str  # "user" or "ip"


def _rule(name: str, method: str, path: str, limit: int, window: int, by: str = "user") -> Rule:
    return Rule(name, method, re.compile(path), limit, window, by)


RULES: tuple[Rule, ...] = (
    _rule("sign_in", "POST", r"^/v1/auth/(google|demo)$", 20, MINUTE, by="ip"),
    _rule("places", "POST", r"^/v1/places/validate$", 60, MINUTE),
    _rule("rank", "POST", r"^/v1/plans/[^/]+/rank-areas$", 20, MINUTE),
    _rule("call_batch", "POST", r"^/v1/plans/[^/]+/call-batches$", 10, MINUTE),
    _rule("call_approve", "POST", r"^/v1/call-batches/[^/]+/approve$", 10, MINUTE),
    _rule("call_link", "POST", r"^/v1/calls/[^/]+/web-session$", 10, MINUTE),
    _rule("call_extract", "POST", r"^/v1/calls/[^/]+/extract$", 20, MINUTE),
    _rule("agreement_new", "POST", r"^/v1/agreements$", 10, MINUTE),
    _rule("agreement_file", "PUT", r"^/v1/agreements/[^/]+/file$", 10, MINUTE),
    _rule("agreement_analyze", "POST", r"^/v1/agreements/[^/]+/analyze$", 5, MINUTE),
    _rule("delete_account", "DELETE", r"^/v1/me$", 3, HOUR),
)

# Backstop for everything not listed above (reads, plan edits).
DEFAULT_RULE = Rule("default", "*", re.compile(r".*"), 300, MINUTE, "user")

# Health checks and the internal jobs are never limited: Cloud Run and Scheduler call them.
EXEMPT = re.compile(r"^/(health|healthz|ready|internal)(/|$)")


class Limiter:
    """Sliding-window counter. `clock` is injectable so tests do not have to sleep."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def reset(self) -> None:
        self._hits.clear()

    def check(self, rule: Rule, caller: str) -> int:
        """Records a hit. Returns 0 if allowed, otherwise the seconds until a slot frees up."""
        now = self._clock()
        key = (rule.name, caller)
        window = self._hits.get(key)
        if window is None:
            if len(self._hits) >= MAX_TRACKED:
                self._prune(now)
            window = self._hits[key] = deque()
        while window and now - window[0] >= rule.window:
            window.popleft()
        if len(window) >= rule.limit:
            return max(1, int(rule.window - (now - window[0])) + 1)
        window.append(now)
        return 0

    def _prune(self, now: float) -> None:
        longest = max(r.window for r in (*RULES, DEFAULT_RULE))
        for key in [k for k, w in self._hits.items() if not w or now - w[-1] >= longest]:
            del self._hits[key]
        if len(self._hits) >= MAX_TRACKED:  # still full of live callers: drop the oldest half
            for key in list(self._hits)[: MAX_TRACKED // 2]:
                del self._hits[key]


def pick_rule(method: str, path: str) -> Rule:
    for rule in RULES:
        if rule.method == method and rule.pattern.match(path):
            return rule
    return DEFAULT_RULE


def client_ip(scope: dict) -> str:
    """The last X-Forwarded-For entry is the one Cloud Run's front end appended, so a caller
    cannot choose it. Earlier entries are caller-supplied and ignored."""
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            parts = [p.strip() for p in value.decode("latin-1").split(",") if p.strip()]
            if parts:
                return parts[-1]
    client = scope.get("client")
    return client[0] if client else "unknown"


def session_user(scope: dict, secret: Callable[[], str]) -> str | None:
    """The user id from a *verified* session token. An unverified one would let a caller dodge
    the limit by inventing a new id on every request."""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            text = value.decode("latin-1")
            if not text.startswith("Bearer "):
                return None
            try:
                return str(jwt.decode(text[7:], secret(), algorithms=["HS256"])["sub"])
            except (jwt.PyJWTError, KeyError):
                return None
    return None


LIMITER = Limiter()  # the one the running app uses; tests reset it between tests


def enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").strip().lower() != "false"


class RateLimitMiddleware:
    """Plain ASGI middleware, so it runs before routing and before any database work."""

    def __init__(self, app, limiter: Limiter | None = None):
        self.app = app
        self.limiter = limiter or LIMITER

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled() or EXEMPT.match(scope["path"]):
            return await self.app(scope, receive, send)

        from relocation_api.auth import _session_secret

        rule = pick_rule(scope["method"], scope["path"])
        user = session_user(scope, _session_secret)
        caller = f"ip:{client_ip(scope)}" if rule.by == "ip" or user is None else f"user:{user}"
        wait = self.limiter.check(rule, caller)
        if wait == 0:
            return await self.app(scope, receive, send)

        body = b'{"detail":"Too many requests. Please wait a moment and try again."}'
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(wait).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
