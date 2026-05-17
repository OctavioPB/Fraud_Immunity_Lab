"""
Unit tests for api/services/score_calculator.py.

All Redis, Pinecone, and PostgreSQL calls are mocked.
Tests verify the score formula, component computation, Redis caching,
and scenario coverage report generation.
"""

import time
import unittest.mock as mock

import pytest

from api.schemas.immunity_score import ScoreComponents
from api.services.score_calculator import (
    ScoreCalculator,
    ScoreInputs,
    _CANONICAL_ATTACK_TYPES,
)


def _make_inputs(
    detection_recalls: dict | None = None,
    fp_rate: float = 0.03,
    total_profiles: int = 100,
    fresh_profiles: int = 90,
    attack_types_tested: set | None = None,
) -> ScoreInputs:
    return ScoreInputs(
        attack_type_recalls=detection_recalls or {at: 0.95 for at in _CANONICAL_ATTACK_TYPES},
        false_positive_rate=fp_rate,
        total_legitimate_evaluated=500,
        total_profiles=total_profiles,
        fresh_profiles=fresh_profiles,
        attack_types_tested_30d=attack_types_tested or set(_CANONICAL_ATTACK_TYPES),
        tenant_id="test-tenant",
    )


class TestScoreComponents:
    def test_composite_formula(self) -> None:
        comp = ScoreComponents(
            detection_coverage=1.0,
            false_positive_health=1.0,
            model_freshness=1.0,
            scenario_diversity=1.0,
        )
        assert comp.composite == pytest.approx(1.0)

    def test_weighted_formula_matches_spec(self) -> None:
        comp = ScoreComponents(
            detection_coverage=0.8,
            false_positive_health=0.9,
            model_freshness=0.7,
            scenario_diversity=0.5,
        )
        expected = 0.40 * 0.8 + 0.30 * 0.9 + 0.20 * 0.7 + 0.10 * 0.5
        assert comp.composite == pytest.approx(expected, rel=1e-4)

    def test_perfect_score_is_one(self) -> None:
        comp = ScoreComponents(
            detection_coverage=1.0,
            false_positive_health=1.0,
            model_freshness=1.0,
            scenario_diversity=1.0,
        )
        assert comp.composite == pytest.approx(1.0)

    def test_zero_score_is_zero(self) -> None:
        comp = ScoreComponents(
            detection_coverage=0.0,
            false_positive_health=0.0,
            model_freshness=0.0,
            scenario_diversity=0.0,
        )
        assert comp.composite == pytest.approx(0.0)


class TestComputeComponents:
    def test_full_coverage_all_at_threshold(self) -> None:
        inputs = _make_inputs(
            detection_recalls={at: 0.95 for at in _CANONICAL_ATTACK_TYPES}
        )
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.detection_coverage == pytest.approx(1.0)

    def test_partial_coverage_some_below_threshold(self) -> None:
        recalls = {at: 0.95 for at in _CANONICAL_ATTACK_TYPES}
        # Set half below threshold
        below = list(recalls.keys())[: len(recalls) // 2]
        for at in below:
            recalls[at] = 0.50
        inputs = _make_inputs(detection_recalls=recalls)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.detection_coverage < 1.0
        assert comps.detection_coverage > 0.0

    def test_zero_coverage_when_all_below_threshold(self) -> None:
        recalls = {at: 0.50 for at in _CANONICAL_ATTACK_TYPES}
        inputs = _make_inputs(detection_recalls=recalls)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.detection_coverage == pytest.approx(0.0)

    def test_fp_health_is_one_minus_fp_rate(self) -> None:
        inputs = _make_inputs(fp_rate=0.05)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.false_positive_health == pytest.approx(0.95)

    def test_fp_health_clamped_to_zero(self) -> None:
        inputs = _make_inputs(fp_rate=1.5)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.false_positive_health == pytest.approx(0.0)

    def test_model_freshness_fraction(self) -> None:
        inputs = _make_inputs(total_profiles=100, fresh_profiles=80)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.model_freshness == pytest.approx(0.80)

    def test_model_freshness_one_when_no_profiles(self) -> None:
        inputs = _make_inputs(total_profiles=0, fresh_profiles=0)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.model_freshness == pytest.approx(1.0)

    def test_scenario_diversity_full(self) -> None:
        inputs = _make_inputs(attack_types_tested=set(_CANONICAL_ATTACK_TYPES))
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.scenario_diversity == pytest.approx(1.0)

    def test_scenario_diversity_partial(self) -> None:
        half = set(list(_CANONICAL_ATTACK_TYPES)[: len(_CANONICAL_ATTACK_TYPES) // 2])
        inputs = _make_inputs(attack_types_tested=half)
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.scenario_diversity == pytest.approx(
            len(half) / len(_CANONICAL_ATTACK_TYPES), rel=1e-3
        )

    def test_scenario_diversity_zero_when_nothing_tested(self) -> None:
        inputs = _make_inputs(attack_types_tested=set())
        comps = ScoreCalculator.compute_components(inputs)
        assert comps.scenario_diversity == pytest.approx(0.0)


class TestComponentsToScore:
    def test_perfect_score_is_100(self) -> None:
        comps = ScoreComponents(
            detection_coverage=1.0,
            false_positive_health=1.0,
            model_freshness=1.0,
            scenario_diversity=1.0,
        )
        assert ScoreCalculator.components_to_score(comps) == pytest.approx(100.0)

    def test_zero_score_is_0(self) -> None:
        comps = ScoreComponents(
            detection_coverage=0.0,
            false_positive_health=0.0,
            model_freshness=0.0,
            scenario_diversity=0.0,
        )
        assert ScoreCalculator.components_to_score(comps) == pytest.approx(0.0)

    def test_score_range_is_0_to_100(self) -> None:
        import random
        for _ in range(20):
            comps = ScoreComponents(
                detection_coverage=random.random(),
                false_positive_health=random.random(),
                model_freshness=random.random(),
                scenario_diversity=random.random(),
            )
            score = ScoreCalculator.components_to_score(comps)
            assert 0.0 <= score <= 100.0


class TestGetScore:
    def _make_calculator_with_mocked_redis(
        self, cached_payload: dict | None = None
    ) -> ScoreCalculator:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()

        if cached_payload is not None:
            import json
            mock_redis.get.return_value = json.dumps(cached_payload)
        else:
            mock_redis.get.return_value = None
            mock_redis.smembers.return_value = set()

        calc._redis = mock_redis
        return calc

    def test_cache_hit_returns_cached_payload(self) -> None:
        import json
        cached = {
            "tenant_id": "test",
            "score": 78.5,
            "components": {
                "detection_coverage": 0.8,
                "false_positive_health": 0.9,
                "model_freshness": 0.7,
                "scenario_diversity": 0.6,
            },
            "computed_at_ms": int(time.time() * 1000),
            "cache_hit": False,
            "version": "1.0",
        }
        calc = self._make_calculator_with_mocked_redis(cached_payload=cached)
        payload, cache_hit = calc.get_score("test")
        assert cache_hit is True
        assert payload["score"] == 78.5

    def test_cache_miss_computes_score(self) -> None:
        calc = self._make_calculator_with_mocked_redis(cached_payload=None)
        # Mock all data fetchers to avoid real network calls
        with mock.patch.object(calc, "_fetch_detection_recalls", return_value={at: 0.95 for at in _CANONICAL_ATTACK_TYPES}), \
             mock.patch.object(calc, "_fetch_false_positive_rate", return_value=(0.02, 100)), \
             mock.patch.object(calc, "_fetch_profile_freshness", return_value=(50, 48)), \
             mock.patch.object(calc, "_fetch_scenario_diversity", return_value=set(_CANONICAL_ATTACK_TYPES)), \
             mock.patch.object(calc, "_persist_score"):
            payload, cache_hit = calc.get_score("test-tenant")

        assert cache_hit is False
        assert 0.0 <= payload["score"] <= 100.0
        assert "components" in payload

    def test_score_response_has_required_fields(self) -> None:
        calc = self._make_calculator_with_mocked_redis(cached_payload=None)
        with mock.patch.object(calc, "_fetch_detection_recalls", return_value={}), \
             mock.patch.object(calc, "_fetch_false_positive_rate", return_value=(0.0, 0)), \
             mock.patch.object(calc, "_fetch_profile_freshness", return_value=(0, 0)), \
             mock.patch.object(calc, "_fetch_scenario_diversity", return_value=set()), \
             mock.patch.object(calc, "_persist_score"):
            payload, _ = calc.get_score("tenant-x")

        for key in ("tenant_id", "score", "components", "computed_at_ms", "cache_hit", "version"):
            assert key in payload, f"Missing key: {key}"


class TestRecordScenarioRun:
    def test_writes_to_redis(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_pipe = mock.MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = lambda s: s
        mock_pipe.__exit__ = mock.MagicMock(return_value=False)
        calc._redis = mock_redis

        calc.record_scenario_run("tenant-1", "phishing", recall=0.95)

        mock_pipe.setex.assert_called()
        mock_pipe.sadd.assert_called()
        mock_pipe.execute.assert_called()

    def test_invalidates_cache(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_pipe = mock.MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        calc._redis = mock_redis

        with mock.patch.object(calc, "invalidate_cache") as mock_invalidate:
            calc.record_scenario_run("tenant-2", "smurfing", recall=0.92)

        mock_invalidate.assert_called_once_with("tenant-2")


class TestBuildScenarioCoverage:
    def test_returns_list_of_all_canonical_attack_types(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_redis.get.return_value = None
        mock_redis.smembers.return_value = set()
        calc._redis = mock_redis

        with mock.patch.object(calc, "_fetch_detection_recalls", return_value={}):
            coverage = calc.build_scenario_coverage("tenant-cov")

        assert len(coverage) == len(_CANONICAL_ATTACK_TYPES)

    def test_untested_types_have_zero_scenario_count(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_redis.get.return_value = None
        mock_redis.smembers.return_value = set()
        calc._redis = mock_redis

        with mock.patch.object(calc, "_fetch_detection_recalls", return_value={}):
            coverage = calc.build_scenario_coverage("tenant-cov")

        for item in coverage:
            assert item.scenario_count == 0

    def test_recommended_flag_true_for_untested(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_redis.get.return_value = None
        mock_redis.smembers.return_value = set()
        calc._redis = mock_redis

        with mock.patch.object(calc, "_fetch_detection_recalls", return_value={}):
            coverage = calc.build_scenario_coverage("tenant-cov")

        for item in coverage:
            assert item.recommended is True

    def test_recommended_false_for_well_tested(self) -> None:
        calc = ScoreCalculator()
        mock_redis = mock.MagicMock()
        mock_redis.smembers.return_value = set(_CANONICAL_ATTACK_TYPES)

        def fake_get(key):
            if "last_scenario_run" in key:
                return str(int(time.time() * 1000))
            if "scenario_count" in key:
                return "5"
            return None

        mock_redis.get.side_effect = fake_get
        calc._redis = mock_redis

        full_recalls = {at: 0.95 for at in _CANONICAL_ATTACK_TYPES}
        with mock.patch.object(calc, "_fetch_detection_recalls", return_value=full_recalls):
            coverage = calc.build_scenario_coverage("tenant-good")

        for item in coverage:
            assert item.recommended is False, f"{item.attack_type} should not be recommended"
