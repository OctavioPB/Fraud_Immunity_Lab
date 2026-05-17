"""
Unit tests for api/routers/immunity_score.py and api/middleware/auth.py.

Uses FastAPI TestClient with JWT auth middleware disabled (enforce=False)
to test routing, response shapes, and error handling without a live Redis instance.
"""

import time
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

from api.middleware.auth import create_access_token, _decode_token, JWTAuthMiddleware
from api.schemas.immunity_score import (
    ImmunityScoreResponse,
    ScenarioCoverageResponse,
    ScoreComponents,
    ScoreHistoryResponse,
)


# ── Minimal app fixture with auth disabled ─────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    from fastapi import FastAPI
    from api.routers.immunity_score import router
    from api.middleware.auth import JWTAuthMiddleware

    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware, enforce=False)
    app.include_router(router)
    return TestClient(app)


def _mock_score_payload(tenant_id: str = "default") -> dict:
    return {
        "tenant_id": tenant_id,
        "score": 82.5,
        "components": {
            "detection_coverage": 0.90,
            "false_positive_health": 0.97,
            "model_freshness": 0.85,
            "scenario_diversity": 0.70,
        },
        "computed_at_ms": int(time.time() * 1000),
        "cache_hit": False,
        "version": "1.0",
    }


# ── GET /immunity-score ────────────────────────────────────────────────────────

class TestGetImmunityScore:
    def test_returns_200(self, client: TestClient) -> None:
        from api.routers.immunity_score import get_calculator
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_score.return_value = (_mock_score_payload(), False)

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score")

        assert resp.status_code == 200

    def test_response_schema_valid(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_score.return_value = (_mock_score_payload(), False)

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score")

        data = resp.json()
        # Validate against Pydantic schema
        score_resp = ImmunityScoreResponse(**data)
        assert 0 <= score_resp.score <= 100

    def test_score_in_range(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_score.return_value = (_mock_score_payload(), True)

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score")

        assert 0 <= resp.json()["score"] <= 100

    def test_cache_hit_field_present(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_score.return_value = (_mock_score_payload(), True)

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score")

        assert "cache_hit" in resp.json()

    def test_503_when_calculator_raises(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_score.side_effect = RuntimeError("Redis down")

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score")

        assert resp.status_code == 503


# ── GET /immunity-score/history ────────────────────────────────────────────────

class TestGetScoreHistory:
    def _make_history_row(self, days_ago: int = 0) -> dict:
        return {
            "score": 80.0,
            "detection_coverage": 0.9,
            "false_positive_health": 0.95,
            "model_freshness": 0.85,
            "scenario_diversity": 0.70,
            "recorded_at_ms": int(time.time() * 1000) - days_ago * 86_400_000,
        }

    def test_returns_200(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_history.return_value = [self._make_history_row(1)]

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/history?days=7")

        assert resp.status_code == 200

    def test_response_schema_valid(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        rows = [self._make_history_row(i) for i in range(1, 4)]
        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_history.return_value = rows

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/history?days=7")

        data = resp.json()
        hist = ScoreHistoryResponse(**data)
        assert hist.point_count == 3

    def test_empty_history_returns_empty_list(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_history.return_value = []

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/history")

        assert resp.json()["points"] == []

    def test_days_param_validated(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.get_history.return_value = []

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/history?days=999")

        assert resp.status_code == 422  # days > 365 is invalid


# ── GET /immunity-score/scenarios ──────────────────────────────────────────────

class TestGetScenarioCoverage:
    def test_returns_200(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator, _CANONICAL_ATTACK_TYPES
        from api.schemas.immunity_score import AttackTypeCoverage

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.build_scenario_coverage.return_value = [
            AttackTypeCoverage(attack_type=at, scenario_count=0, recommended=True)
            for at in _CANONICAL_ATTACK_TYPES
        ]

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/scenarios")

        assert resp.status_code == 200

    def test_response_lists_all_attack_types(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator, _CANONICAL_ATTACK_TYPES
        from api.schemas.immunity_score import AttackTypeCoverage

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.build_scenario_coverage.return_value = [
            AttackTypeCoverage(attack_type=at, scenario_count=2, recommended=False)
            for at in _CANONICAL_ATTACK_TYPES
        ]

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/scenarios")

        data = resp.json()
        assert len(data["attack_types"]) == len(_CANONICAL_ATTACK_TYPES)

    def test_coverage_fraction_in_range(self, client: TestClient) -> None:
        from api.services.score_calculator import ScoreCalculator, _CANONICAL_ATTACK_TYPES
        from api.schemas.immunity_score import AttackTypeCoverage

        mock_calc = mock.MagicMock(spec=ScoreCalculator)
        mock_calc.build_scenario_coverage.return_value = [
            AttackTypeCoverage(attack_type=at, scenario_count=1, recommended=False)
            for at in _CANONICAL_ATTACK_TYPES[:5]
        ] + [
            AttackTypeCoverage(attack_type=at, scenario_count=0, recommended=True)
            for at in _CANONICAL_ATTACK_TYPES[5:]
        ]

        with mock.patch("api.routers.immunity_score.get_calculator", return_value=mock_calc):
            resp = client.get("/immunity-score/scenarios")

        frac = resp.json()["coverage_fraction"]
        assert 0.0 <= frac <= 1.0


# ── JWT auth middleware ────────────────────────────────────────────────────────

class TestJWTAuthMiddleware:
    def test_create_and_decode_token(self) -> None:
        token = create_access_token("user-001", "tenant-abc")
        payload = _decode_token(token)
        assert payload["tenant_id"] == "tenant-abc"
        assert payload["sub"] == "user-001"

    def test_expired_token_raises(self) -> None:
        token = create_access_token("user-002", "tenant-xyz", expires_in_seconds=-1)
        with pytest.raises(Exception):
            _decode_token(token)

    def test_exempt_paths_no_auth_required(self) -> None:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(JWTAuthMiddleware, enforce=True)

        @app.get("/health")
        async def health():
            return JSONResponse({"status": "ok"})

        c = TestClient(app)
        resp = c.get("/health")
        assert resp.status_code == 200

    def test_missing_token_returns_401(self) -> None:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(JWTAuthMiddleware, enforce=True)

        @app.get("/protected")
        async def protected():
            return JSONResponse({"data": "secret"})

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/protected")
        assert resp.status_code == 401

    def test_valid_token_passes(self) -> None:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(JWTAuthMiddleware, enforce=True)

        @app.get("/protected")
        async def protected(request: Request):
            payload = getattr(request.state, "token_payload", {})
            return JSONResponse({"tenant_id": payload.get("tenant_id")})

        token = create_access_token("user-003", "tenant-test")
        c = TestClient(app)
        resp = c.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "tenant-test"
