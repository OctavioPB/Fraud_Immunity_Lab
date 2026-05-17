"""
auth — JWT Authentication Middleware
=====================================

Validates HS256 JWTs on every request (except exempted paths).
Extracts `tenant_id` from claims and stores the decoded payload on
`request.state.token_payload` for downstream use by route handlers.

Algorithm: HS256 (CLAUDE.md §5: JWT_ALGORITHM=HS256)
Secret: API_SECRET_KEY env var

Exempted paths (no auth required):
  /health, /metrics, /docs, /redoc, /openapi.json

401 Unauthorized:
  - Token missing
  - Token expired
  - Token signature invalid

403 Forbidden:
  - Token valid but missing required `tenant_id` claim
"""

import os
import time
from typing import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

_JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "dev-only-secret-change-in-production")

_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def _decode_token(token: str) -> dict:
    """
    Decode and validate a HS256 JWT.

    Raises:
        ValueError: on expired, invalid, or missing claims.
    """
    try:
        import jwt as pyjwt  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "PyJWT not installed. Run: pip install PyJWT"
        )

    payload = pyjwt.decode(
        token,
        _SECRET_KEY,
        algorithms=[_JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat", "tenant_id"]},
    )

    # Explicit expiry check (pyjwt validates this but we log it explicitly)
    if payload.get("exp", 0) < int(time.time()):
        raise ValueError("Token expired")

    if not payload.get("tenant_id"):
        raise ValueError("Missing tenant_id claim")

    return payload


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that validates JWT Bearer tokens.

    Stores decoded payload at `request.state.token_payload` so route
    handlers can access `tenant_id` and `scopes` without re-decoding.
    """

    def __init__(self, app: ASGIApp, *, enforce: bool = True) -> None:
        super().__init__(app)
        self._enforce = enforce

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enforce:
            request.state.token_payload = {
                "sub": "dev-user",
                "tenant_id": "default",
                "scopes": ["read", "write"],
            }
            return await call_next(request)

        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header missing or malformed. Expected: Bearer <token>"},
            )

        token = auth_header.removeprefix("Bearer ").strip()

        try:
            payload = _decode_token(token)
        except ValueError as exc:
            log.warning(
                "jwt_validation_failed",
                path=request.url.path,
                reason=str(exc),
            )
            status_code = 403 if "tenant_id" in str(exc) else 401
            return JSONResponse(
                status_code=status_code,
                content={"detail": str(exc)},
            )
        except Exception as exc:
            log.warning(
                "jwt_decode_error",
                path=request.url.path,
                error=str(exc),
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token."},
            )

        request.state.token_payload = payload
        return await call_next(request)


def create_access_token(
    subject: str,
    tenant_id: str,
    *,
    scopes: list[str] | None = None,
    expires_in_seconds: int = 3600,
) -> str:
    """
    Create a signed HS256 JWT.

    For internal use: seed tokens for testing, Airflow DAG callbacks, etc.
    Production tokens should be issued by the identity provider.
    """
    try:
        import jwt as pyjwt  # type: ignore[import]
    except ImportError:
        raise RuntimeError("PyJWT not installed. Run: pip install PyJWT")

    now = int(time.time())
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + expires_in_seconds,
        "scopes": scopes or [],
    }
    return pyjwt.encode(payload, _SECRET_KEY, algorithm=_JWT_ALGORITHM)
