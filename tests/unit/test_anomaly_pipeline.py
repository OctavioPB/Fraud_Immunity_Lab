"""
Unit tests for ml/anomaly/anomaly_pipeline.py.

Verifies the pipeline helper functions without Celery, OpenAI, or Pinecone.
Mocks external clients; tests transaction text serialization, chain dispatch,
and scenario detection eval logic.
"""

import time
import unittest.mock as mock

import pytest

from ml.anomaly.anomaly_pipeline import (
    _build_transaction_text,
    run_scenario_detection_eval,
)


def _make_transaction_event(
    transaction_id: str = "tx-001",
    amount: float = 150.0,
    channel: str = "card_not_present",
) -> dict:
    return {
        "transaction_id": transaction_id,
        "account_id": "tok_test_account",
        "amount": amount,
        "currency": "USD",
        "merchant_id": "merchant-001",
        "timestamp": int(time.time() * 1000),
        "channel": channel,
        "metadata": {
            "category": "retail",
            "geo_country": "US",
        },
    }


class TestBuildTransactionText:
    def test_includes_amount(self) -> None:
        event = _make_transaction_event(amount=99.99)
        text = _build_transaction_text(event)
        assert "99.99" in text

    def test_includes_currency(self) -> None:
        event = _make_transaction_event()
        text = _build_transaction_text(event)
        assert "USD" in text

    def test_includes_channel(self) -> None:
        event = _make_transaction_event(channel="ach")
        text = _build_transaction_text(event)
        assert "ach" in text

    def test_includes_merchant(self) -> None:
        event = _make_transaction_event()
        text = _build_transaction_text(event)
        assert "merchant-001" in text

    def test_includes_category(self) -> None:
        event = _make_transaction_event()
        text = _build_transaction_text(event)
        assert "retail" in text

    def test_includes_country(self) -> None:
        event = _make_transaction_event()
        text = _build_transaction_text(event)
        assert "US" in text

    def test_includes_hour_of_day(self) -> None:
        # timestamp in Jan 2026 noon UTC
        event = _make_transaction_event()
        event["timestamp"] = 12 * 3_600_000  # 12:00 UTC epoch day 1
        text = _build_transaction_text(event)
        assert "hour of day:" in text

    def test_no_raw_account_id_in_text(self) -> None:
        event = _make_transaction_event()
        event["account_id"] = "SENSITIVE-ACC-999"
        text = _build_transaction_text(event)
        # account_id is in the event dict but _build_transaction_text should not output it
        assert "SENSITIVE-ACC-999" not in text

    def test_no_synthetic_tag_in_text(self) -> None:
        event = _make_transaction_event()
        event["metadata"]["synthetic"] = "true"
        text = _build_transaction_text(event)
        # synthetic tag should not pollute the embedding feature space
        assert "synthetic" not in text


class TestRunScenarioDetectionEval:
    def _make_scenario_dict(self, attack_type: str = "phishing") -> dict:
        return {
            "scenario_id": "test-scenario-abc",
            "attack_type": attack_type,
            "complexity": "high",
            "target_segment": "retail_banking",
            "transaction_pattern": {"avg_amount": 500.0},
            "evasion_tactics": ["vpn"],
            "expected_detection_signals": ["drift"],
            "synthetic": True,
            "origin": "red_team",
        }

    def test_returns_dict_with_required_keys(self) -> None:
        scenario = self._make_scenario_dict()
        account_tokens = ["tok_aaa", "tok_bbb", "tok_ccc"]

        # Mock run_detection_pipeline to return flagged=True for all accounts
        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value = {
                "transaction_id": "eval_x",
                "flagged": True,
                "score": 0.5,
                "drift_type": "personal_drift",
            }
            result = run_scenario_detection_eval(
                scenario_id="test-scenario-abc",
                scenario_dict=scenario,
                injected_account_tokens=account_tokens,
                async_mode=False,
            )

        assert "scenario_id" in result
        assert "recall" in result
        assert "flagged_count" in result
        assert "accounts_evaluated" in result
        assert "eval_status" in result
        assert "hard_rule_6_passed" in result

    def test_perfect_recall_passes_hard_rule_6(self) -> None:
        scenario = self._make_scenario_dict()
        tokens = ["tok_1", "tok_2", "tok_3", "tok_4", "tok_5"]

        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value = {"flagged": True}
            result = run_scenario_detection_eval(
                "sid-001", scenario, tokens, async_mode=False
            )

        assert result["recall"] == pytest.approx(1.0)
        assert result["hard_rule_6_passed"] is True

    def test_low_recall_fails_hard_rule_6(self) -> None:
        scenario = self._make_scenario_dict()
        tokens = ["tok_1", "tok_2", "tok_3", "tok_4", "tok_5"]
        call_count = [0]

        def side_effect(*args, **kwargs) -> dict:
            call_count[0] += 1
            return {"flagged": call_count[0] <= 1}  # only first account flagged

        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline",
            side_effect=side_effect,
        ):
            result = run_scenario_detection_eval(
                "sid-002", scenario, tokens, async_mode=False
            )

        assert result["recall"] < 0.90
        assert result["hard_rule_6_passed"] is False

    def test_empty_tokens_returns_no_accounts(self) -> None:
        scenario = self._make_scenario_dict()

        result = run_scenario_detection_eval(
            "sid-empty", scenario, [], async_mode=False
        )

        assert result["accounts_evaluated"] == 0
        assert result["eval_status"] == "no_accounts"

    def test_accounts_evaluated_matches_token_count(self) -> None:
        scenario = self._make_scenario_dict()
        tokens = ["tok_a", "tok_b"]

        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value = {"flagged": False}
            result = run_scenario_detection_eval(
                "sid-count", scenario, tokens, async_mode=False
            )

        assert result["accounts_evaluated"] == 2

    def test_pipeline_exceptions_counted_as_not_flagged(self) -> None:
        scenario = self._make_scenario_dict()
        tokens = ["tok_err"]

        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline",
            side_effect=RuntimeError("Pinecone unavailable"),
        ):
            result = run_scenario_detection_eval(
                "sid-err", scenario, tokens, async_mode=False
            )

        assert result["flagged_count"] == 0
        assert result["accounts_evaluated"] == 1

    def test_scenario_id_preserved(self) -> None:
        scenario = self._make_scenario_dict()

        with mock.patch(
            "ml.anomaly.anomaly_pipeline.run_detection_pipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value = {"flagged": True}
            result = run_scenario_detection_eval(
                "sid-preserve-me", scenario, ["tok_x"], async_mode=False
            )

        assert result["scenario_id"] == "sid-preserve-me"
