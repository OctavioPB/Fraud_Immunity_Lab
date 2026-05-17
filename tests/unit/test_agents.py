"""
Unit tests for the attacker agent framework.

All tests mock the OpenAI client — no real LLM calls are made.
Every test that exercises generate_scenario() requires RED_TEAM_ENABLED=true.
The conftest.py fixture disables it by default for safety.
"""

import json
import unittest.mock as mock
import uuid

import pytest

from red_team.agents.base_agent import (
    BaseAgent,
    ScenarioConfig,
    _RateLimiter,
    require_red_team_enabled,
)
from red_team.agents.phishing_agent import PhishingAgent
from red_team.agents.laundering_agent import LaunderingAgent
from red_team.agents.account_takeover_agent import AccountTakeoverAgent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_llm_response(attack_type: str = "phishing") -> str:
    """Minimal valid scenario JSON that an LLM would return."""
    return json.dumps({
        "attack_type": attack_type,
        "complexity": "high",
        "target_segment": "retail_banking",
        "evasion_tactics": ["vpn_exit_node", "residential_proxy"],
        "transaction_pattern": {
            "initial_vector": "spear_phishing_email",
            "time_to_first_transaction_minutes": 30,
            "post_compromise_transactions": [
                {"step": 1, "type": "p2p", "amount_ratio": 0.8, "delay_minutes": 5,
                 "destination_type": "domestic"}
            ],
            "login_event_sequence": [
                {"event": "initial_login", "success": True, "device": "new", "geo_change": True}
            ],
        },
        "expected_detection_signals": ["behavioral_drift_login", "new_device_high_value"],
    })


def _mock_openai_response(content: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 500
    resp.usage.completion_tokens = 300
    return resp


def _patch_openai(agent: BaseAgent, content: str) -> mock.MagicMock:
    patcher = mock.patch("openai.OpenAI")
    mock_cls = patcher.start()
    mock_cls.return_value.chat.completions.create.return_value = (
        _mock_openai_response(content)
    )
    return patcher


# ── Kill-switch tests ─────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_blocks_when_disabled(self) -> None:
        @require_red_team_enabled
        def dummy() -> str:
            return "ran"
        # RED_TEAM_ENABLED is set to 'false' by conftest autouse fixture
        with pytest.raises(RuntimeError, match="RED_TEAM_ENABLED"):
            dummy()

    def test_allows_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")

        @require_red_team_enabled
        def dummy() -> str:
            return "ran"

        assert dummy() == "ran"

    def test_phishing_agent_blocked_by_default(self) -> None:
        agent = PhishingAgent()
        with pytest.raises(RuntimeError, match="RED_TEAM_ENABLED"):
            agent.generate_scenario()

    def test_laundering_agent_blocked_by_default(self) -> None:
        agent = LaunderingAgent()
        with pytest.raises(RuntimeError, match="RED_TEAM_ENABLED"):
            agent.generate_scenario()

    def test_ato_agent_blocked_by_default(self) -> None:
        agent = AccountTakeoverAgent()
        with pytest.raises(RuntimeError, match="RED_TEAM_ENABLED"):
            agent.generate_scenario()


# ── ScenarioConfig model tests ────────────────────────────────────────────────

class TestScenarioConfig:
    def test_synthetic_tag_always_true(self) -> None:
        s = ScenarioConfig(
            attack_type="phishing",
            complexity="high",
            target_segment="retail",
            evasion_tactics=["vpn"],
            transaction_pattern={},
            expected_detection_signals=["signal_a"],
        )
        assert s.synthetic is True
        assert s.origin == "red_team"

    def test_scenario_id_auto_generated(self) -> None:
        s = ScenarioConfig(
            attack_type="phishing",
            complexity="low",
            target_segment="retail",
            evasion_tactics=["vpn"],
            transaction_pattern={},
            expected_detection_signals=["signal_a"],
        )
        uuid.UUID(s.scenario_id)  # raises if not a valid UUID

    def test_invalid_complexity_rejected(self) -> None:
        with pytest.raises(Exception):
            ScenarioConfig(
                attack_type="phishing",
                complexity="mega",
                target_segment="retail",
                evasion_tactics=["vpn"],
                transaction_pattern={},
                expected_detection_signals=["signal_a"],
            )

    def test_empty_evasion_tactics_rejected(self) -> None:
        with pytest.raises(Exception):
            ScenarioConfig(
                attack_type="phishing",
                complexity="high",
                target_segment="retail",
                evasion_tactics=[],
                transaction_pattern={},
                expected_detection_signals=["signal_a"],
            )


# ── Generation with mocked LLM ────────────────────────────────────────────────

class TestPhishingAgentGeneration:
    def test_generate_returns_scenario_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent()

        patcher = _patch_openai(agent, _valid_llm_response("phishing"))
        try:
            with mock.patch.object(agent._audit, "append"):
                scenario = agent.generate_scenario()
        finally:
            patcher.stop()

        assert isinstance(scenario, ScenarioConfig)
        assert scenario.attack_type == "phishing"
        assert scenario.synthetic is True

    def test_generate_enforces_synthetic_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent()

        # LLM output that forgets the tag — base_agent must enforce it
        bad_output = json.dumps({
            "attack_type": "phishing",
            "complexity": "high",
            "target_segment": "retail_banking",
            "evasion_tactics": ["vpn"],
            "transaction_pattern": {"note": "no tag here"},
            "expected_detection_signals": ["drift"],
            "synthetic": False,  # LLM tried to lie
            "origin": "evil",
        })

        patcher = _patch_openai(agent, bad_output)
        try:
            with mock.patch.object(agent._audit, "append"):
                scenario = agent.generate_scenario()
        finally:
            patcher.stop()

        # Base agent must override whatever the LLM said
        assert scenario.synthetic is True
        assert scenario.origin == "red_team"

    def test_budget_exceeded_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent(budget_usd=0.0)  # zero budget

        with pytest.raises(RuntimeError, match="Budget cap"):
            agent.generate_scenario()

    def test_cost_accumulates_across_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent(budget_usd=100.0)

        patcher = _patch_openai(agent, _valid_llm_response("phishing"))
        try:
            with mock.patch.object(agent._audit, "append"):
                agent.generate_scenario()
                agent.generate_scenario()
        finally:
            patcher.stop()

        assert agent.total_cost_usd > 0
        assert agent.call_count == 2


class TestRateLimiter:
    def test_does_not_block_first_call(self) -> None:
        import time
        rl = _RateLimiter(calls_per_minute=60)
        start = time.monotonic()
        rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # first call should be instant

    def test_second_call_respects_interval(self) -> None:
        import time
        # 6 calls/minute = 10s interval — too slow for tests
        # Use 600 calls/minute = 0.1s interval instead
        rl = _RateLimiter(calls_per_minute=600)
        rl.acquire()  # first call — sets last_call_ts
        start = time.monotonic()
        rl.acquire()  # second call — should wait ~0.1s
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # some waiting happened


class TestAuditIntegration:
    def test_audit_appended_on_successful_generation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent()

        patcher = _patch_openai(agent, _valid_llm_response("phishing"))
        with mock.patch.object(agent._audit, "append") as mock_append:
            try:
                agent.generate_scenario()
            finally:
                patcher.stop()

        mock_append.assert_called_once()
        record = mock_append.call_args[0][0]
        assert record.validation_passed is True
        assert record.attack_type == "phishing"

    def test_audit_appended_even_on_validation_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        agent = PhishingAgent()

        # Return structurally invalid JSON from LLM
        invalid_response = json.dumps({"attack_type": "phishing"})  # missing required fields
        patcher = _patch_openai(agent, invalid_response)
        with mock.patch.object(agent._audit, "append") as mock_append:
            try:
                with pytest.raises(Exception):
                    agent.generate_scenario()
            finally:
                patcher.stop()

        # Audit records must be written even for failed attempts
        assert mock_append.called
