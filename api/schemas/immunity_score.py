"""
immunity_score — Pydantic schemas for the Immunity Score API.

All models use strict validation (extra="forbid") to prevent accidental PII
leakage or undocumented fields in API responses.

ImmunityScore formula:
  0.40 × DetectionCoverage   — % of known attack types flagged by detection layer
  0.30 × FalsePositiveHealth — 1 - false_positive_rate
  0.20 × ModelFreshness      — based on profile age + retraining recency
  0.10 × ScenarioDiversity   — breadth of attack types tested in last 30 days
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_config


class ScoreComponents(BaseModel):
    """Breakdown of the four Immunity Score sub-components."""

    model_config = model_config(extra="forbid")

    detection_coverage: float = Field(
        ge=0.0, le=1.0, description="Fraction of known attack types with ≥90% recall"
    )
    false_positive_health: float = Field(
        ge=0.0, le=1.0, description="1 - false_positive_rate on legitimate transactions"
    )
    model_freshness: float = Field(
        ge=0.0, le=1.0, description="Recency score: profile age and retraining lag"
    )
    scenario_diversity: float = Field(
        ge=0.0, le=1.0, description="Fraction of canonical attack types tested in last 30 days"
    )

    @property
    def composite(self) -> float:
        return round(
            0.40 * self.detection_coverage
            + 0.30 * self.false_positive_health
            + 0.20 * self.model_freshness
            + 0.10 * self.scenario_diversity,
            4,
        )


class ImmunityScoreResponse(BaseModel):
    """Response for GET /immunity-score."""

    model_config = model_config(extra="forbid")

    tenant_id: str = Field(description="Tenant identifier from JWT claims")
    score: float = Field(ge=0.0, le=100.0, description="Composite Immunity Score (0–100)")
    components: ScoreComponents
    computed_at_ms: int = Field(description="Epoch ms when this score was computed")
    cache_hit: bool = Field(description="True if this response was served from Redis cache")
    version: str = Field(default="1.0", description="Score formula version")

    @field_validator("score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)


class ScoreHistoryPoint(BaseModel):
    """A single point in the Immunity Score time series."""

    model_config = model_config(extra="forbid")

    score: float = Field(ge=0.0, le=100.0)
    components: ScoreComponents
    recorded_at_ms: int


class ScoreHistoryResponse(BaseModel):
    """Response for GET /immunity-score/history."""

    model_config = model_config(extra="forbid")

    tenant_id: str
    days: int = Field(ge=1, le=365)
    points: list[ScoreHistoryPoint]
    point_count: int

    @field_validator("point_count", mode="before")
    @classmethod
    def set_point_count(cls, v: Any, info: Any) -> int:
        return v


class AttackTypeCoverage(BaseModel):
    """Detection coverage for a single attack type."""

    model_config = model_config(extra="forbid")

    attack_type: str
    last_tested_ms: int | None = Field(
        default=None, description="Epoch ms of most recent scenario run, or null if never tested"
    )
    scenario_count: int = Field(ge=0, description="Number of scenarios run in the last 30 days")
    detection_recall: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Measured recall, or null if not evaluated"
    )
    hard_rule_6_passed: bool | None = Field(
        default=None, description="True if recall ≥ 0.90, null if not yet evaluated"
    )
    recommended: bool = Field(
        default=False,
        description="True if this attack type should be prioritised in the next run",
    )


class ScenarioCoverageResponse(BaseModel):
    """Response for GET /immunity-score/scenarios."""

    model_config = model_config(extra="forbid")

    tenant_id: str
    window_days: int = Field(default=30)
    tested_count: int
    untested_count: int
    coverage_fraction: float = Field(ge=0.0, le=1.0)
    attack_types: list[AttackTypeCoverage]
    generated_at_ms: int


class TokenPayload(BaseModel):
    """Decoded JWT claims (internal use — not returned to clients)."""

    model_config = model_config(extra="forbid")

    sub: str = Field(description="Subject — user identifier")
    tenant_id: str = Field(description="Tenant identifier for data isolation")
    exp: int = Field(description="Expiry epoch seconds")
    iat: int = Field(description="Issued-at epoch seconds")
    scopes: list[str] = Field(default_factory=list)
