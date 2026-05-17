"""
rate_limit — Per-Tenant, Per-Endpoint Redis Sliding-Window Rate Limiter
=======================================================================

Uses Redis sorted sets for an exact sliding-window counter.

Key format:  rate:{tenant_id}:{endpoint_bucket}
Each member:  "{timestamp_ms}:{uuid4}"  (unique per request)
Score:        epoch milliseconds

On each request:
  1. Remove members older than (now - window_ms)
  2. Count remaining members
  3. If count >= limit → 429 with Retry-After header
  4. Else ZADD current request, EXPIRE key to window_seconds + 1

Endpoint buckets map URL path prefixes to (limit, window_seconds) pairs.
Unknown paths fall back to the DEFAULT bucket.
"""

import os
import time
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = structlog.get_logger(__name__)

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# (requests, window_seconds)
_ENDPOINT_LIMITS: dict[str, tuple[int, int]] = {
    "POST:/tenants":        (5,   60),
    "GET:/immunity-score":  (60,  60),
    "GET:/fraud-rings":     (30,  60),
    "GET:/scenarios":       (60,  60),
    "GET:/score-history":   (60,  60),
    "POST:/auth/token":     (10,  60),
    "WS:/ws/alerts":        (10,  60),
    "DEFAULT":              (120, 60),
}


def _endpoint_bucket(method: str, path: str) -> str:
    """Map (method, path) to the most specific configured bucket key."""
    key = f"{method}:{path}"
    if key in _ENDPOINT_LIMITS:
        return key
    # Prefix match — check each configured bucket
    for bucket in _ENDPOINT_LIMITS:
        if bucket == "DEFAULT":
            continue
        b_method, b_path = bucket.split(":", 1)
        if method == b_method and path.startswith(b_path):
            return bucket
    return "DEFAULT"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter applied to every request.

    Reads tenant_id from the JWT payload stored by JWTAuthMiddleware
    (``request.state.tenant_id``).  Falls back to the client IP so that
    unauthenticated endpoints (e.g. /auth/token) are still rate-limited.

    Gracefully no-ops if Redis is unavailable — never blocks the pipeline.
    """

    def __init__(self, app, *, redis_url: str = _REDIS_URL) -> None:
        super().__init__(app)
        self._redis_url = redis_url
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis as redis_lib  # type: ignore[import]

                self._redis = redis_lib.from_url(
                    self._redis_url, decode_responses=True
                )
            except Exception:
                return None
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        r = self._get_redis()
        if r is None:
            return await call_next(request)

        tenant_id: str = getattr(request.state, "tenant_id", None) or (
            request.client.host if request.client else "unknown"
        )
        method = request.method
        path = request.url.path
        bucket = _endpoint_bucket(method, path)
        limit, window_s = _ENDPOINT_LIMITS[bucket]

        redis_key = f"rate:{tenant_id}:{bucket}"
        now_ms = int(time.time() * 1000)
        window_ms = window_s * 1000
        cutoff_ms = now_ms - window_ms
        member = f"{now_ms}:{uuid.uuid4().hex}"

        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, "-inf", cutoff_ms)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {member: now_ms})
            pipe.expire(redis_key, window_s + 1)
            results = pipe.execute()

            current_count: int = results[1]  # count BEFORE adding current request

            if current_count >= limit:
                # Undo the optimistic add
                r.zrem(redis_key, member)
                retry_after = window_s - int((now_ms - cutoff_ms) / 1000)
                log.warning(
                    "rate_limit_exceeded",
                    tenant_id=tenant_id,
                    bucket=bucket,
                    count=current_count,
                    limit=limit,
                )
                try:
                    from api.observability import RATE_LIMIT_EXCEEDED  # noqa: PLC0415

                    RATE_LIMIT_EXCEEDED.labels(tenant_id=tenant_id, bucket=bucket).inc()
                except Exception:
                    pass
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded.",
                        "bucket": bucket,
                        "limit": limit,
                        "window_seconds": window_s,
                    },
                    headers={"Retry-After": str(max(retry_after, 1))},
                )
        except Exception as exc:
            log.warning("rate_limit_redis_error", error=str(exc))

        return await call_next(request)
