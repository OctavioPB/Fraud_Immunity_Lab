"""
logging — Request/Response Logging Middleware
=============================================

Logs every HTTP request and response with a correlation ID (X-Request-ID header
or auto-generated UUID4). Structured JSON output via structlog.

Log fields per request:
  correlation_id, method, path, status_code, duration_ms, tenant_id (if auth'd)

The correlation ID is also echoed back in the X-Request-ID response header so
clients and external systems can trace distributed calls.
"""

import time
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

_SKIP_LOGGING_PATHS: frozenset[str] = frozenset({"/health", "/metrics"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs all HTTP requests with timing, status, and correlation IDs.

    Correlation ID priority:
      1. X-Request-ID header from the client (pass-through mode for upstream callers)
      2. Auto-generated UUID4 (when no header is present)

    The correlation ID is bound to the structlog context for the duration of
    the request, so all log lines emitted within a request carry it automatically.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = (
            request.headers.get("X-Request-ID") or str(uuid.uuid4())
        )
        request.state.correlation_id = correlation_id

        start_ms = time.monotonic() * 1000

        if request.url.path in _SKIP_LOGGING_PATHS:
            response = await call_next(request)
            response.headers["X-Request-ID"] = correlation_id
            return response

        # Bind correlation_id to structlog context for this request
        bound_log = log.bind(correlation_id=correlation_id)

        tenant_id = "unauthenticated"
        token_payload = getattr(request.state, "token_payload", None)
        if token_payload:
            tenant_id = token_payload.get("tenant_id", "unknown")

        bound_log.info(
            "http_request_received",
            method=request.method,
            path=request.url.path,
            query=str(request.url.query) if request.url.query else None,
            tenant_id=tenant_id,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round(time.monotonic() * 1000 - start_ms, 1)
            bound_log.error(
                "http_request_unhandled_exception",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round(time.monotonic() * 1000 - start_ms, 1)

        level = "warning" if response.status_code >= 400 else "info"
        getattr(bound_log, level)(
            "http_request_complete",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            tenant_id=tenant_id,
        )

        response.headers["X-Request-ID"] = correlation_id
        return response
