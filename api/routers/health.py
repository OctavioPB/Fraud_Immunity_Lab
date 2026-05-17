"""Health check endpoint — used by Docker health checks and load balancers."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["infra"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return service liveness status."""
    return HealthResponse(status="ok", version="0.1.0")
