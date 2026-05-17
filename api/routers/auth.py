"""
auth router — JWT token issuance for the Fraud Immunity Lab dashboard.

POST /auth/token
    Authenticate with username + password.
    Returns a signed HS256 JWT valid for 8 hours.
    Store in an httpOnly cookie via the Next.js login route handler.

This endpoint is exempt from JWTAuthMiddleware (see _EXEMPT_PATHS).
"""

import os

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.middleware.auth import create_access_token

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])

# In production, replace with a proper identity provider.
# Credentials are read from environment variables.
_DEMO_USERS: dict[str, str] = {
    "admin": os.getenv("DASHBOARD_ADMIN_PASSWORD", "fraud-lab-2024"),
}


class TokenRequest(BaseModel):
    username: str
    password: str
    tenant_id: str = "default"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Issue JWT access token",
    description=(
        "Authenticate with username + password. "
        "Returns a signed HS256 JWT valid for 8 hours. "
        "Intended for use by the dashboard login route handler only."
    ),
)
async def issue_token(body: TokenRequest) -> TokenResponse:
    expected = _DEMO_USERS.get(body.username)
    if expected is None or body.password != expected:
        log.warning("auth_failed", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        subject=body.username,
        tenant_id=body.tenant_id,
        expires_in_seconds=8 * 3600,
    )
    log.info("auth_token_issued", username=body.username, tenant_id=body.tenant_id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        tenant_id=body.tenant_id,
    )
