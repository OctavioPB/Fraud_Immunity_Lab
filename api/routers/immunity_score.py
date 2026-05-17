"""
immunity_score router — Immunity Score API Endpoints
====================================================

GET /immunity-score
    Returns current composite Immunity Score + component breakdown.
    Served from Redis cache (5-min TTL) on cache hit.

GET /immunity-score/history?days=30
    Returns the score time series from PostgreSQL for trend visualization.

GET /immunity-score/scenarios
    Returns per-attack-type detection coverage with Hard Rule #6 status.

All endpoints require a valid JWT (injected by JWTAuthMiddleware).
All queries are scoped to the `tenant_id` extracted from JWT claims.
"""

import time
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.schemas.immunity_score import (
    AttackTypeCoverage,
    ImmunityScoreResponse,
    ScenarioCoverageResponse,
    ScoreComponents,
    ScoreHistoryPoint,
    ScoreHistoryResponse,
)
from api.services.score_calculator import ScoreCalculator, _CANONICAL_ATTACK_TYPES

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/immunity-score", tags=["Immunity Score"])


# ── Dependency: ScoreCalculator singleton ─────────────────────────────────────

_calculator: ScoreCalculator | None = None


def get_calculator() -> ScoreCalculator:
    global _calculator
    if _calculator is None:
        _calculator = ScoreCalculator()
    return _calculator


# ── Dependency: tenant_id from request state ──────────────────────────────────

def get_tenant_id(request: Request) -> str:
    """
    Extract tenant_id from the JWT payload stored on request.state by
    JWTAuthMiddleware. Falls back to "default" if auth middleware is disabled
    (local dev only).
    """
    token_payload = getattr(request.state, "token_payload", None)
    if token_payload is None:
        return "default"
    return token_payload.get("tenant_id", "default")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ImmunityScoreResponse,
    summary="Get current Immunity Score",
    description=(
        "Returns the composite Immunity Score (0–100) and component breakdown for the "
        "authenticated tenant. Served from Redis cache (5-min TTL) on cache hit."
    ),
)
async def get_immunity_score(
    request: Request,
    calculator: ScoreCalculator = Depends(get_calculator),
) -> ImmunityScoreResponse:
    tenant_id = get_tenant_id(request)

    try:
        payload, cache_hit = calculator.get_score(tenant_id)
    except Exception as exc:
        log.error(
            "immunity_score_endpoint_error",
            tenant_id=tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Score computation temporarily unavailable. Retry in a moment.",
        )

    components = ScoreComponents(**payload["components"])

    return ImmunityScoreResponse(
        tenant_id=payload["tenant_id"],
        score=payload["score"],
        components=components,
        computed_at_ms=payload["computed_at_ms"],
        cache_hit=cache_hit,
        version=payload.get("version", "1.0"),
    )


@router.get(
    "/history",
    response_model=ScoreHistoryResponse,
    summary="Get Immunity Score history",
    description=(
        "Returns the Immunity Score time series from PostgreSQL. "
        "Use `?days=N` to control the lookback window (default 30, max 365)."
    ),
)
async def get_score_history(
    request: Request,
    days: Annotated[int, Query(ge=1, le=365, description="Lookback window in days")] = 30,
    calculator: ScoreCalculator = Depends(get_calculator),
) -> ScoreHistoryResponse:
    tenant_id = get_tenant_id(request)

    try:
        rows = calculator.get_history(tenant_id, days)
    except Exception as exc:
        log.error(
            "score_history_endpoint_error",
            tenant_id=tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="History unavailable. Check PostgreSQL connectivity.",
        )

    points: list[ScoreHistoryPoint] = []
    for row in rows:
        components = ScoreComponents(
            detection_coverage=row.get("detection_coverage", 0.0),
            false_positive_health=row.get("false_positive_health", 0.0),
            model_freshness=row.get("model_freshness", 0.0),
            scenario_diversity=row.get("scenario_diversity", 0.0),
        )
        points.append(
            ScoreHistoryPoint(
                score=row["score"],
                components=components,
                recorded_at_ms=row["recorded_at_ms"],
            )
        )

    return ScoreHistoryResponse(
        tenant_id=tenant_id,
        days=days,
        points=points,
        point_count=len(points),
    )


@router.get(
    "/scenarios",
    response_model=ScenarioCoverageResponse,
    summary="Get scenario coverage report",
    description=(
        "Lists all canonical attack types with their detection recall and Hard Rule #6 status. "
        "Highlights untested attack types and recommends which to run next."
    ),
)
async def get_scenario_coverage(
    request: Request,
    calculator: ScoreCalculator = Depends(get_calculator),
) -> ScenarioCoverageResponse:
    tenant_id = get_tenant_id(request)

    try:
        attack_types = calculator.build_scenario_coverage(tenant_id)
    except Exception as exc:
        log.error(
            "scenario_coverage_endpoint_error",
            tenant_id=tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Coverage report temporarily unavailable.",
        )

    tested = [at for at in attack_types if at.scenario_count > 0]
    untested = [at for at in attack_types if at.scenario_count == 0]
    coverage_fraction = (
        len(tested) / len(_CANONICAL_ATTACK_TYPES) if _CANONICAL_ATTACK_TYPES else 0.0
    )

    return ScenarioCoverageResponse(
        tenant_id=tenant_id,
        window_days=30,
        tested_count=len(tested),
        untested_count=len(untested),
        coverage_fraction=round(coverage_fraction, 4),
        attack_types=attack_types,
        generated_at_ms=int(time.time() * 1000),
    )


@router.post(
    "/cache/invalidate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate score cache",
    description=(
        "Force cache invalidation so the next GET /immunity-score recomputes fresh data. "
        "Called automatically by attack_orchestrator after a completed DAG run."
    ),
)
async def invalidate_cache(
    request: Request,
    calculator: ScoreCalculator = Depends(get_calculator),
) -> None:
    tenant_id = get_tenant_id(request)
    calculator.invalidate_cache(tenant_id)
    log.info("immunity_score_cache_invalidated_via_api", tenant_id=tenant_id)
