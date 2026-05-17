"""
Unit tests for ml/graph/community_detection.py.

All Neo4j GDS and Kafka calls are mocked — no live database or broker required.
Tests cover FraudRing construction, risk score computation, ring ID derivation,
and the detect() orchestration logic.
"""

import unittest.mock as mock

import pytest

from ml.graph.community_detection import (
    CommunityDetector,
    FraudRing,
    _ALERT_THRESHOLD,
    _compute_risk_score,
    _derive_ring_id,
)


class TestDerivRingId:
    def test_deterministic(self) -> None:
        ids = ["tok_a", "tok_b", "tok_c"]
        assert _derive_ring_id(ids) == _derive_ring_id(ids)

    def test_order_independent(self) -> None:
        ids_a = ["tok_x", "tok_y", "tok_z"]
        ids_b = ["tok_z", "tok_x", "tok_y"]
        assert _derive_ring_id(ids_a) == _derive_ring_id(ids_b)

    def test_different_members_different_ids(self) -> None:
        assert _derive_ring_id(["tok_1", "tok_2"]) != _derive_ring_id(["tok_3", "tok_4"])

    def test_returns_valid_uuid_format(self) -> None:
        import re
        ring_id = _derive_ring_id(["tok_a", "tok_b"])
        assert re.match(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            ring_id,
        )


class TestComputeRiskScore:
    def test_zero_signals_zero_score(self) -> None:
        score, signals = _compute_risk_score(0.0, 0, 0, 0, 10)
        assert score == pytest.approx(0.0)
        assert signals == []

    def test_high_unidirectional_ratio_fires_signal(self) -> None:
        score, signals = _compute_risk_score(0.80, 0, 0, 0, 10)
        assert "unidirectional_flow" in signals
        assert score > 0

    def test_shared_ip_fires_signal(self) -> None:
        _, signals = _compute_risk_score(0.0, 3, 0, 0, 10)
        assert "shared_ip" in signals

    def test_shared_device_fires_signal(self) -> None:
        _, signals = _compute_risk_score(0.0, 0, 3, 0, 10)
        assert "shared_device" in signals

    def test_synthetic_injection_fires_signal(self) -> None:
        _, signals = _compute_risk_score(0.0, 0, 0, 5, 10)
        assert "synthetic_injection" in signals

    def test_score_capped_at_one(self) -> None:
        score, _ = _compute_risk_score(1.0, 10, 10, 10, 10)
        assert score <= 1.0

    def test_full_laundering_pattern_high_score(self) -> None:
        score, signals = _compute_risk_score(
            unidirectional_ratio=0.90,
            shared_ip_count=3,
            shared_device_count=2,
            synthetic_edge_count=8,
            total_edges=10,
        )
        assert score >= 0.70
        assert "unidirectional_flow" in signals
        assert "shared_ip" in signals
        assert "shared_device" in signals
        assert "synthetic_injection" in signals

    def test_zero_edges_no_synthetic_signal(self) -> None:
        _, signals = _compute_risk_score(0.0, 0, 0, 0, 0)
        assert "synthetic_injection" not in signals


class TestFraudRing:
    def _make_ring(self, risk_score: float = 0.75) -> FraudRing:
        return FraudRing(
            ring_id="test-ring-001",
            community_id=42,
            member_account_ids=["tok_a", "tok_b", "tok_c"],
            risk_score=risk_score,
            signals=["unidirectional_flow", "shared_ip"],
            total_flow=50_000.0,
            unidirectional_ratio=0.80,
            shared_ip_count=2,
            shared_device_count=0,
            synthetic=True,
        )

    def test_member_count_property(self) -> None:
        ring = self._make_ring()
        assert ring.member_count == 3

    def test_is_high_risk_true(self) -> None:
        ring = self._make_ring(risk_score=_ALERT_THRESHOLD + 0.01)
        assert ring.is_high_risk is True

    def test_is_high_risk_false(self) -> None:
        ring = self._make_ring(risk_score=_ALERT_THRESHOLD - 0.01)
        assert ring.is_high_risk is False

    def test_to_dict_contains_required_keys(self) -> None:
        ring = self._make_ring()
        d = ring.to_dict()
        for key in (
            "ring_id", "community_id", "member_account_ids", "member_count",
            "risk_score", "signals", "total_flow", "synthetic", "detected_at_ms",
        ):
            assert key in d, f"Missing key: {key}"

    def test_synthetic_flag_true_in_dict(self) -> None:
        ring = self._make_ring()
        assert ring.to_dict()["synthetic"] is True

    def test_risk_score_rounded_in_dict(self) -> None:
        ring = self._make_ring(risk_score=0.8765432)
        d = ring.to_dict()
        assert d["risk_score"] == pytest.approx(0.8765, abs=1e-3)


class TestCommunityDetector:
    def _make_detector(self, dry_run: bool = True) -> CommunityDetector:
        return CommunityDetector(dry_run=dry_run, dag_run_id="test-run-001")

    def _mock_communities(self) -> list[dict]:
        """Simulate Louvain output: one large cluster, one small (below min size)."""
        return [
            {
                "community_id": 1,
                "member_account_ids": ["tok_a", "tok_b", "tok_c", "tok_d"],
                "member_count": 4,
            },
            {
                "community_id": 2,
                "member_account_ids": ["tok_x", "tok_y"],
                "member_count": 2,
            },
        ]

    def _mock_signals_laundering(self) -> dict:
        return {
            "total_flow": 100_000.0,
            "edge_count": 10,
            "unidirectional_ratio": 0.85,
            "shared_ip_count": 3,
            "shared_device_count": 1,
            "synthetic_edge_count": 5,
        }

    def _mock_signals_clean(self) -> dict:
        return {
            "total_flow": 500.0,
            "edge_count": 3,
            "unidirectional_ratio": 0.10,
            "shared_ip_count": 0,
            "shared_device_count": 0,
            "synthetic_edge_count": 0,
        }

    def test_detect_returns_summary_dict(self) -> None:
        detector = self._make_detector()

        with mock.patch.object(detector, "_project_graph", return_value={}), \
             mock.patch.object(detector, "_run_louvain", return_value=self._mock_communities()), \
             mock.patch.object(
                 detector, "_fetch_cluster_signals", return_value=self._mock_signals_laundering()
             ), \
             mock.patch.object(detector, "_drop_graph"):
            result = detector.detect()

        assert "rings_detected" in result
        assert "elapsed_ms" in result
        assert "fraud_rings" in result

    def test_detect_skips_small_clusters(self) -> None:
        detector = self._make_detector()
        communities = self._mock_communities()  # cluster 2 has only 2 members

        with mock.patch.object(detector, "_project_graph", return_value={}), \
             mock.patch.object(detector, "_run_louvain", return_value=communities), \
             mock.patch.object(
                 detector, "_fetch_cluster_signals", return_value=self._mock_signals_laundering()
             ), \
             mock.patch.object(detector, "_drop_graph"):
            result = detector.detect(min_cluster_size=3)

        # Only cluster 1 (size 4) should be evaluated
        assert result["rings_detected"] == 1

    def test_detect_skips_clusters_with_no_signals(self) -> None:
        detector = self._make_detector()

        with mock.patch.object(detector, "_project_graph", return_value={}), \
             mock.patch.object(
                 detector, "_run_louvain",
                 return_value=[{"community_id": 1, "member_account_ids": ["tok_a","tok_b","tok_c"], "member_count": 3}],
             ), \
             mock.patch.object(
                 detector, "_fetch_cluster_signals", return_value=self._mock_signals_clean()
             ), \
             mock.patch.object(detector, "_drop_graph"):
            result = detector.detect()

        assert result["rings_detected"] == 0

    def test_dry_run_does_not_persist(self) -> None:
        detector = self._make_detector(dry_run=True)

        with mock.patch.object(detector, "_project_graph", return_value={}), \
             mock.patch.object(
                 detector, "_run_louvain",
                 return_value=[{"community_id": 1, "member_account_ids": ["tok_a","tok_b","tok_c","tok_d"], "member_count": 4}],
             ), \
             mock.patch.object(
                 detector, "_fetch_cluster_signals", return_value=self._mock_signals_laundering()
             ), \
             mock.patch.object(detector, "_persist_fraud_ring") as mock_persist, \
             mock.patch.object(detector, "_drop_graph"):
            detector.detect()

        mock_persist.assert_not_called()

    def test_high_risk_ring_triggers_alert(self) -> None:
        detector = self._make_detector(dry_run=False)

        high_risk_signals = self._mock_signals_laundering()
        high_risk_signals["unidirectional_ratio"] = 1.0
        high_risk_signals["shared_ip_count"] = 5

        with mock.patch.object(detector, "_project_graph", return_value={}), \
             mock.patch.object(
                 detector, "_run_louvain",
                 return_value=[{"community_id": 1, "member_account_ids": ["tok_a","tok_b","tok_c","tok_d"], "member_count": 4}],
             ), \
             mock.patch.object(
                 detector, "_fetch_cluster_signals", return_value=high_risk_signals
             ), \
             mock.patch.object(detector, "_persist_fraud_ring"), \
             mock.patch.object(detector, "_publish_alert") as mock_alert, \
             mock.patch.object(detector, "_drop_graph"):
            result = detector.detect()

        mock_alert.assert_called_once()
        assert result["alerts_published"] == 1

    def test_detect_for_scenario_below_min_size(self) -> None:
        detector = self._make_detector()
        result = detector.detect_for_scenario(
            "sid-001",
            injected_account_tokens=["tok_a", "tok_b"],  # only 2 — below min 3
        )
        assert result["ring_detected"] is False
        assert "reason" in result

    def test_detect_for_scenario_with_signals(self) -> None:
        detector = self._make_detector()
        tokens = ["tok_a", "tok_b", "tok_c", "tok_d"]

        with mock.patch.object(
            detector, "_fetch_cluster_signals", return_value=self._mock_signals_laundering()
        ):
            result = detector.detect_for_scenario("sid-002", tokens)

        assert result["ring_detected"] is True
        assert result["risk_score"] > 0
        assert "ring_id" in result
