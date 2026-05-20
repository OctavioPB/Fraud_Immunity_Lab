"""
Sovereign Fraud Immunity Lab — FastAPI entry point.
"""

import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, metrics
from api.routers import immunity_score, auth, fraud_rings, alerts, tenants, reports, admin
from api.middleware.auth import JWTAuthMiddleware
from api.middleware.logging import RequestLoggingMiddleware
from api.middleware.rate_limit import RateLimitMiddleware

logger = structlog.get_logger(__name__)

_AUTH_ENABLED: bool = (
    os.getenv("JWT_AUTH_ENABLED", "true").strip().lower() == "true"
)

app = FastAPI(
    title="Fraud Immunity Lab API",
    description=(
        "Internal services for the Sovereign Fraud Immunity Lab. "
        "Provides Immunity Score computation, scenario coverage reporting, "
        "fraud ring visualization, real-time alert feed, tenant provisioning, "
        "and Prometheus metrics."
    ),
    version="0.6.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware order: outermost runs last on request, first on response.
# Stack (innermost → outermost, i.e., add_middleware call order reversed):
#   CORS → JWTAuth (sets tenant_id) → RateLimit (reads tenant_id) → RequestLogging
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(JWTAuthMiddleware, enforce=_AUTH_ENABLED)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("API_ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(immunity_score.router)
app.include_router(fraud_rings.router)
app.include_router(alerts.router)
app.include_router(tenants.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "fraud_immunity_lab_api_started",
        version="0.6.0",
        jwt_auth_enabled=_AUTH_ENABLED,
    )
