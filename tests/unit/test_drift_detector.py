"""
Unit tests for ml/anomaly/drift_detector.py.

All Pinecone calls are mocked — no live index required.
Verifies cosine similarity math, threshold selection, drift classification logic,
and the to_detection_event serialization contract.
"""

import math
import unittest.mock as mock

import pytest

from ml.anomaly.drift_detector import (
    AccountSegment,
    DriftDetector,
    DriftResult,
    NeighborMatch,
    _SUSPICION_THRESHOLD,
    _THRESHOLD_DEFAULT,
    _THRESHOLD_HIGH_VALUE,
)


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert DriftDetector.cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert DriftDetector.cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert DriftDetector.cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_normalized_similarity(self) -> None:
        a = [3.0, 4.0]  # norm=5
        b = [6.0, 8.0]  # norm=10, same direction
        assert DriftDetector.cosine_similarity(a, b) == pytest.approx(1.0)

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="dimension mismatch"):
            DriftDetector.cosine_similarity([1.0, 0.0], [1.0])

    def test_zero_vector_returns_zero(self) -> None:
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert DriftDetector.cosine_similarity(a, b) == 0.0


class TestGetThreshold:
    def test_default_threshold(self) -> None:
        assert DriftDetector.get_threshold(None) == _THRESHOLD_DEFAULT

    def test_high_value_threshold(self) -> None:
        assert DriftDetector.get_threshold("high_value") == _THRESHOLD_HIGH_VALUE

    def test_corporate_uses_high_value_threshold(self) -> None:
        assert DriftDetector.get_threshold("corporate_banking") == _THRESHOLD_HIGH_VALUE

    def test_retail_uses_default_threshold(self) -> None:
        assert DriftDetector.get_threshold("retail_banking") == _THRESHOLD_DEFAULT

    def test_unknown_segment_uses_default(self) -> None:
        assert DriftDetector.get_threshold("unknown_segment") == _THRESHOLD_DEFAULT

    def test_high_value_threshold_more_conservative(self) -> None:
        assert _THRESHOLD_HIGH_VALUE > _THRESHOLD_DEFAULT


class TestDetect:
    def _make_detector(self) -> DriftDetector:
        return DriftDetector(pinecone_api_key="test-key")

    def _mock_clean_result(
        self, account_token: str, personal_score: float
    ) -> dict:
        return {
            "matches": [
                {
                    "id": account_token,
                    "score": personal_score,
                    "metadata": {"label": "legitimate", "account_id": account_token},
                }
            ]
        }

    def _mock_suspicious_result(self, score: float) -> dict:
        return {
            "matches": [
                {
                    "id": "synthetic_abc123",
                    "score": score,
                    "metadata": {"label": "synthetic_fraud", "attack_type": "phishing"},
                }
            ]
        }

    def test_no_drift_when_score_above_threshold(self) -> None:
        detector = self._make_detector()
        account_token = "tok_abc"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.95  # above default 0.85 threshold
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result = detector.detect(account_token, "tx-001", embedding)

        assert result.flagged is False
        assert result.drift_type is None
        assert result.score == pytest.approx(0.95)

    def test_personal_drift_when_score_below_threshold(self) -> None:
        detector = self._make_detector()
        account_token = "tok_def"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.60  # well below 0.85 threshold
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result = detector.detect(account_token, "tx-002", embedding)

        assert result.flagged is True
        assert result.drift_type == "personal_drift"

    def test_suspicious_pattern_flagged(self) -> None:
        detector = self._make_detector()
        account_token = "tok_ghi"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.95  # no personal drift
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(
                _SUSPICION_THRESHOLD + 0.05  # above suspicion threshold
            )

            result = detector.detect(account_token, "tx-003", embedding)

        assert result.flagged is True
        assert result.drift_type == "suspicious_pattern"

    def test_both_drift_types_when_both_fire(self) -> None:
        detector = self._make_detector()
        account_token = "tok_jkl"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.50  # drift
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(
                _SUSPICION_THRESHOLD + 0.1  # suspicious
            )

            result = detector.detect(account_token, "tx-004", embedding)

        assert result.flagged is True
        assert result.drift_type == "both"

    def test_no_profile_does_not_flag_on_personal_drift(self) -> None:
        detector = self._make_detector()
        account_token = "tok_new"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            # Empty matches — profile not found
            mock_clean.return_value.query.return_value = {"matches": []}
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result = detector.detect(account_token, "tx-005", embedding)

        assert result.profile_exists is False
        assert result.flagged is False  # no profile = can't compute personal drift

    def test_high_value_account_uses_stricter_threshold(self) -> None:
        detector = self._make_detector()
        account_token = "tok_hv"
        embedding = [1.0] + [0.0] * 3071

        # Score between default and high-value thresholds should flag for high_value
        score_between_thresholds = (_THRESHOLD_DEFAULT + _THRESHOLD_HIGH_VALUE) / 2

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, score_between_thresholds
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result_default = detector.detect(
                account_token, "tx-006", embedding, account_segment="retail_banking"
            )
            result_high_value = detector.detect(
                account_token, "tx-007", embedding, account_segment="high_value"
            )

        assert result_default.flagged is False   # above default threshold
        assert result_high_value.flagged is True  # below high_value threshold

    def test_returns_drift_result_type(self) -> None:
        detector = self._make_detector()
        account_token = "tok_type"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.90
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result = detector.detect(account_token, "tx-type", embedding)

        assert isinstance(result, DriftResult)

    def test_latency_ms_is_set(self) -> None:
        detector = self._make_detector()
        account_token = "tok_lat"
        embedding = [1.0] + [0.0] * 3071

        with mock.patch.object(detector, "_get_clean_index") as mock_clean, \
             mock.patch.object(detector, "_get_suspicious_index") as mock_sus:
            mock_clean.return_value.query.return_value = self._mock_clean_result(
                account_token, 0.90
            )
            mock_sus.return_value.query.return_value = self._mock_suspicious_result(0.0)

            result = detector.detect(account_token, "tx-lat", embedding)

        assert result.latency_ms >= 0


class TestToDetectionEvent:
    def test_required_fields_present(self) -> None:
        detector = DriftDetector(pinecone_api_key="test")
        result = DriftResult(
            account_token="tok_abc",
            transaction_id="tx-001",
            score=0.75,
            flagged=True,
            drift_type="personal_drift",
            threshold_used=0.85,
        )
        event = detector.to_detection_event(result)

        assert event["account_token"] == "tok_abc"
        assert event["transaction_id"] == "tx-001"
        assert event["score"] == pytest.approx(0.75)
        assert event["flagged"] is True
        assert event["drift_type"] == "personal_drift"

    def test_nearest_neighbors_included(self) -> None:
        detector = DriftDetector(pinecone_api_key="test")
        result = DriftResult(
            account_token="tok_abc",
            transaction_id="tx-002",
            score=0.92,
            flagged=False,
            drift_type=None,
            nearest_clean_neighbors=[
                NeighborMatch("tok_abc", 0.92, {"label": "legitimate"}),
            ],
            nearest_suspicious_neighbors=[
                NeighborMatch("synthetic_xyz", 0.30, {"attack_type": "phishing"}),
            ],
        )
        event = detector.to_detection_event(result)

        assert len(event["nearest_clean"]) == 1
        assert len(event["nearest_suspicious"]) == 1
        assert event["nearest_suspicious"][0]["attack_type"] == "phishing"
