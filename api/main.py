"""
Sovereign Fraud Immunity Lab — FastAPI entry point.
"""

import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, metrics

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Fraud Immunity Lab API",
    description="Internal services for the Sovereign Fraud Immunity Lab",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("API_ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("fraud_immunity_lab_api_started", version="0.1.0")
