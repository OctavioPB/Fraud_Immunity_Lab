"""Unit tests for BaseAgent kill-switch and ScenarioConfig validation."""

import pytest

from red_team.agents.base_agent import ScenarioConfig, require_red_team_enabled


def test_kill_switch_blocks_when_disabled() -> None:
    """RED_TEAM_ENABLED=false must raise RuntimeError on any agent call."""

    @require_red_team_enabled
    def dummy() -> str:
        return "executed"

    with pytest.raises(RuntimeError, match="RED_TEAM_ENABLED"):
        dummy()


def test_kill_switch_allows_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RED_TEAM_ENABLED", "true")

    @require_red_team_enabled
    def dummy() -> str:
        return "executed"

    assert dummy() == "executed"


def test_scenario_config_enforces_synthetic_tag() -> None:
    scenario = ScenarioConfig(
        attack_type="phishing",
        complexity="medium",
        target_segment="retail",
        evasion_tactics=["vpn", "slow_velocity"],
        transaction_pattern={"amount_range": [100, 500]},
        expected_detection_signals=["behavioral_drift", "ip_change"],
    )
    assert scenario.synthetic is True
    assert scenario.origin == "red_team"


def test_scenario_config_rejects_invalid_complexity() -> None:
    with pytest.raises(Exception):
        ScenarioConfig(
            attack_type="test",
            complexity="extreme",  # not in allowed values
            target_segment="retail",
            evasion_tactics=[],
            transaction_pattern={},
            expected_detection_signals=[],
        )
