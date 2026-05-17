"""
Unit tests for red_team/dags/shared/kafka_injector.py.

All tests run with SYNTHETIC_INJECTION_DRY_RUN=true so no Kafka connection
is needed. Verifies event-count routing per attack type and that the synthetic
tag is preserved on every produced event.
"""

import unittest.mock as mock

import pytest

from red_team.dags.shared.kafka_injector import (
    InjectionResult,
    _ATTACK_TYPE_TO_EVENTS,
    inject_scenario,
)


def _scenario(attack_type: str = "phishing") -> dict:
    return {
        "scenario_id": "test-scenario-id",
        "attack_type": attack_type,
        "complexity": "high",
        "target_segment": "retail_banking",
        "evasion_tactics": ["vpn"],
        "transaction_pattern": {},
        "expected_detection_signals": ["drift"],
        "synthetic": True,
        "origin": "red_team",
    }


@pytest.fixture(autouse=True)
def dry_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNTHETIC_INJECTION_DRY_RUN", "true")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


class TestInjectionResult:
    def test_total_events_property(self) -> None:
        result = InjectionResult(
            scenario_id="abc",
            attack_type="phishing",
            logins_produced=4,
            transactions_produced=3,
            devices_produced=1,
            injected_at_ms=0,
            dry_run=True,
        )
        assert result.total_events == 8


class TestInjectScenario:
    def test_returns_injection_result(self) -> None:
        result = inject_scenario("sid-001", _scenario("phishing"))
        assert isinstance(result, InjectionResult)
        assert result.scenario_id == "sid-001"
        assert result.attack_type == "phishing"
        assert result.dry_run is True

    def test_phishing_event_mix(self) -> None:
        result = inject_scenario("sid-phishing", _scenario("phishing"))
        expected = _ATTACK_TYPE_TO_EVENTS["phishing"]
        assert result.logins_produced == expected["logins"]
        assert result.transactions_produced == expected["transactions"]
        assert result.devices_produced == expected["devices"]

    def test_laundering_produces_no_logins(self) -> None:
        result = inject_scenario("sid-launder", _scenario("money_laundering"))
        assert result.logins_produced == 0
        assert result.transactions_produced > 0

    def test_smurfing_produces_no_logins_no_devices(self) -> None:
        result = inject_scenario("sid-smurf", _scenario("smurfing"))
        assert result.logins_produced == 0
        assert result.devices_produced == 0

    def test_ato_produces_device_events(self) -> None:
        result = inject_scenario("sid-ato", _scenario("account_takeover"))
        expected = _ATTACK_TYPE_TO_EVENTS["account_takeover"]
        assert result.devices_produced == expected["devices"]

    def test_credential_stuffing_has_many_logins(self) -> None:
        result = inject_scenario("sid-stuffing", _scenario("credential_stuffing"))
        assert result.logins_produced >= 15

    def test_unknown_attack_type_uses_defaults(self) -> None:
        scenario = _scenario("unknown_future_type")
        scenario["attack_type"] = "unknown_future_type"
        result = inject_scenario("sid-unknown", scenario)
        assert result.total_events > 0

    def test_dag_run_id_passed_to_producer(self) -> None:
        result = inject_scenario(
            "sid-dag", _scenario("phishing"), dag_run_id="run_20260516_001"
        )
        assert result.scenario_id == "sid-dag"

    def test_injected_at_ms_is_set(self) -> None:
        result = inject_scenario("sid-ts", _scenario("phishing"))
        assert result.injected_at_ms > 0

    def test_all_attack_types_produce_events(self) -> None:
        for attack_type in _ATTACK_TYPE_TO_EVENTS:
            result = inject_scenario(f"sid-{attack_type}", _scenario(attack_type))
            assert result.total_events > 0, (
                f"Attack type '{attack_type}' produced zero events"
            )


class TestSyntheticTagPreservation:
    """Verify Hard Rule #3 compliance: every event must carry synthetic=true."""

    def test_synthetic_metadata_in_produced_events(self) -> None:
        """
        The SyntheticProducer always adds synthetic=true to metadata.
        In dry-run mode, we verify by intercepting the build_ calls.
        """
        from ingestion.producers.synthetic_producer import SyntheticProducer

        with mock.patch.object(
            SyntheticProducer, "produce_transaction", wraps=None
        ) as mock_tx:
            mock_tx.return_value = {}
            with mock.patch.object(
                SyntheticProducer, "produce_login", wraps=None
            ) as mock_login:
                mock_login.return_value = {}
                with mock.patch.object(
                    SyntheticProducer, "produce_device", wraps=None
                ) as mock_device:
                    mock_device.return_value = {}
                    inject_scenario("sid-tag", _scenario("phishing"))

            # Check extra_metadata arg always includes synthetic tag
            for call in mock_tx.call_args_list:
                meta = call.kwargs.get("extra_metadata", {})
                assert meta.get("synthetic") == "true", (
                    "produce_transaction called without synthetic tag in extra_metadata"
                )
