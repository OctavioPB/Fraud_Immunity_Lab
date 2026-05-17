"""
Unit tests for red_team/agents/validators.py.

Covers:
  - JSON Schema validation pass and fail cases
  - PII pattern detection for all registered patterns
  - PII stripping (scan then strip)
  - Full validate_and_sanitize pipeline
"""

import pytest

from red_team.agents.validators import (
    ValidationResult,
    scan_for_pii,
    strip_pii,
    validate_and_sanitize,
    validate_schema,
)


def _valid_scenario(**overrides: object) -> dict:
    base = {
        "attack_type": "phishing",
        "complexity": "high",
        "target_segment": "retail_banking",
        "evasion_tactics": ["vpn", "slow_velocity"],
        "transaction_pattern": {"amount": 500},
        "expected_detection_signals": ["behavioral_drift"],
        "synthetic": True,
        "origin": "red_team",
    }
    return {**base, **overrides}


class TestValidateSchema:
    def test_valid_scenario_passes(self) -> None:
        result = validate_schema(_valid_scenario())
        assert result.valid is True
        assert result.errors == []

    def test_missing_attack_type_fails(self) -> None:
        data = _valid_scenario()
        del data["attack_type"]
        result = validate_schema(data)
        assert result.valid is False
        assert result.errors

    def test_missing_evasion_tactics_fails(self) -> None:
        data = _valid_scenario()
        del data["evasion_tactics"]
        result = validate_schema(data)
        assert result.valid is False

    def test_invalid_complexity_fails(self) -> None:
        result = validate_schema(_valid_scenario(complexity="extreme"))
        assert result.valid is False

    def test_empty_expected_signals_fails(self) -> None:
        result = validate_schema(_valid_scenario(expected_detection_signals=[]))
        assert result.valid is False

    def test_empty_evasion_tactics_fails(self) -> None:
        result = validate_schema(_valid_scenario(evasion_tactics=[]))
        assert result.valid is False

    def test_extra_fields_allowed(self) -> None:
        data = _valid_scenario(agent_version="1.0.0", scenario_id="abc-123")
        result = validate_schema(data)
        assert result.valid is True


class TestScanForPii:
    def test_clean_data_returns_empty(self) -> None:
        data = _valid_scenario()
        found = scan_for_pii(data)
        assert found == {}

    def test_detects_ssn(self) -> None:
        data = _valid_scenario(transaction_pattern={"note": "SSN 123-45-6789"})
        found = scan_for_pii(data)
        assert "ssn" in found

    def test_detects_email(self) -> None:
        data = _valid_scenario(transaction_pattern={"contact": "victim@example.com"})
        found = scan_for_pii(data)
        assert "email" in found

    def test_detects_credit_card(self) -> None:
        data = _valid_scenario(transaction_pattern={"card": "4111 1111 1111 1111"})
        found = scan_for_pii(data)
        assert "credit_card" in found

    def test_detects_phone_number(self) -> None:
        data = _valid_scenario(transaction_pattern={"phone": "555-867-5309"})
        found = scan_for_pii(data)
        assert "phone_us" in found

    def test_detects_large_account_number(self) -> None:
        data = _valid_scenario(transaction_pattern={"acct": "1234567890123456"})
        found = scan_for_pii(data)
        assert "account_number" in found


class TestStripPii:
    def test_strips_ssn(self) -> None:
        data = _valid_scenario(transaction_pattern={"note": "SSN 123-45-6789"})
        clean = strip_pii(data)
        assert "123-45-6789" not in str(clean)
        assert "[REDACTED]" in str(clean)

    def test_strips_email(self) -> None:
        data = _valid_scenario(transaction_pattern={"c": "victim@bank.com"})
        clean = strip_pii(data)
        assert "victim@bank.com" not in str(clean)

    def test_does_not_mutate_original(self) -> None:
        data = _valid_scenario(transaction_pattern={"ssn": "999-99-9999"})
        original_str = str(data)
        strip_pii(data)
        assert str(data) == original_str  # original unchanged


class TestValidateAndSanitize:
    def test_clean_valid_scenario_passes(self) -> None:
        data = _valid_scenario()
        result, sanitized = validate_and_sanitize(data)
        assert result.valid is True
        assert result.has_pii is False

    def test_invalid_schema_fails_without_sanitizing(self) -> None:
        data = {"attack_type": "phishing"}  # missing required fields
        result, _ = validate_and_sanitize(data)
        assert result.valid is False

    def test_pii_detected_and_stripped(self) -> None:
        data = _valid_scenario(
            transaction_pattern={"contact": "attacker@evil.com"}
        )
        result, sanitized = validate_and_sanitize(data)
        assert result.valid is True
        assert "attacker@evil.com" not in str(sanitized)
        assert "[REDACTED]" in str(sanitized)

    def test_synthetic_tag_survives_sanitization(self) -> None:
        data = _valid_scenario(transaction_pattern={"pii": "test@test.com"})
        _, sanitized = validate_and_sanitize(data)
        assert sanitized.get("synthetic") is True
        assert sanitized.get("origin") == "red_team"
