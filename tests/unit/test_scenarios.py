"""
Unit tests for the scenario YAML config library.

Validates:
  - All 10 seed scenario YAML files load and parse without error
  - Schema validation rejects invalid configs
  - Required fields are present in all seed configs
  - Attack type allow-list is enforced
"""

from pathlib import Path

import pytest

from red_team.scenarios.schema import (
    ScenarioYamlConfig,
    load_all_scenarios,
    load_scenario,
)

_SCENARIOS_DIR = Path(__file__).parent.parent.parent / "red_team" / "scenarios"


class TestSeedScenarios:
    """All 10 seed YAML files must load and validate cleanly."""

    def test_all_scenarios_load(self) -> None:
        scenarios = load_all_scenarios(_SCENARIOS_DIR)
        assert len(scenarios) >= 10, (
            f"Expected ≥ 10 seed scenarios, got {len(scenarios)}"
        )

    def test_all_scenarios_have_required_fields(self) -> None:
        for s in load_all_scenarios(_SCENARIOS_DIR):
            assert s.name
            assert s.version
            assert s.attack_type
            assert s.complexity in {"low", "medium", "high", "critical"}
            assert s.target_segment
            assert s.description
            assert len(s.evasion_tactics) >= 1
            assert len(s.expected_detection_signals) >= 1

    def test_all_scenarios_have_synthetic_detection_signals(self) -> None:
        """Every scenario must define at least one detection signal."""
        for s in load_all_scenarios(_SCENARIOS_DIR):
            assert s.expected_detection_signals, (
                f"Scenario '{s.name}' has no expected_detection_signals"
            )

    def test_scenario_attack_types_are_varied(self) -> None:
        scenarios = load_all_scenarios(_SCENARIOS_DIR)
        types = {s.attack_type for s in scenarios}
        assert len(types) >= 5, (
            f"Expected ≥ 5 distinct attack types, got {len(types)}: {types}"
        )

    def test_complexity_distribution_reasonable(self) -> None:
        scenarios = load_all_scenarios(_SCENARIOS_DIR)
        complexities = [s.complexity for s in scenarios]
        assert "high" in complexities or "critical" in complexities, (
            "No high-complexity scenarios — red team coverage gap"
        )

    def test_individual_yaml_files_by_name(self) -> None:
        expected_files = [
            "01_card_fraud_cnp.yaml",
            "02_card_fraud_skimming.yaml",
            "03_synthetic_identity.yaml",
            "04_first_party_fraud.yaml",
            "05_mule_account.yaml",
            "06_smurfing.yaml",
            "07_phishing_spear.yaml",
            "08_credential_stuffing.yaml",
            "09_money_laundering_layering.yaml",
            "10_friendly_fraud.yaml",
        ]
        for filename in expected_files:
            path = _SCENARIOS_DIR / filename
            assert path.exists(), f"Missing seed scenario: {filename}"
            scenario = load_scenario(path)
            assert scenario.name  # parsed and validated


class TestSchemaValidation:
    def test_unknown_attack_type_rejected(self) -> None:
        with pytest.raises(Exception, match="attack_type"):
            ScenarioYamlConfig(
                name="test",
                version="1.0.0",
                attack_type="unknown_attack",
                complexity="high",
                target_segment="retail",
                description="test",
                evasion_tactics=["vpn"],
                expected_detection_signals=["signal_a"],
            )

    def test_invalid_complexity_rejected(self) -> None:
        with pytest.raises(Exception):
            ScenarioYamlConfig(
                name="test",
                version="1.0.0",
                attack_type="phishing",
                complexity="extreme",  # not in enum
                target_segment="retail",
                description="test",
                evasion_tactics=["vpn"],
                expected_detection_signals=["signal_a"],
            )

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(Exception):
            ScenarioYamlConfig(
                name="test",
                version="1.0.0",
                attack_type="phishing",
                complexity="high",
                target_segment="retail",
                description="test",
                evasion_tactics=["vpn"],
                expected_detection_signals=["signal_a"],
                unknown_field="should_fail",  # type: ignore[call-arg]
            )

    def test_valid_config_parsed_correctly(self) -> None:
        config = ScenarioYamlConfig(
            name="Card fraud test",
            version="1.0.0",
            attack_type="card_fraud",
            complexity="medium",
            target_segment="retail_banking",
            description="A card fraud test scenario",
            evasion_tactics=["residential_proxy", "low_velocity"],
            expected_detection_signals=["velocity_spike", "geo_mismatch"],
            parameters={"amount_range": [100, 500]},
            tags=["card_fraud", "test"],
        )
        assert config.attack_type == "card_fraud"
        assert len(config.evasion_tactics) == 2
        assert config.parameters["amount_range"] == [100, 500]
