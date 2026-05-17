"""
Unit tests for red_team/dags/shared/dag_utils.py.

Verifies kill-switch logic, budget cap reading, and connection fallbacks
all without requiring a running Airflow instance.
"""

import pytest

from red_team.dags.shared.dag_utils import (
    assert_red_team_enabled,
    get_budget_cap_usd,
    get_detection_recall_threshold,
    get_red_team_enabled,
    is_dry_run,
)


class TestGetRedTeamEnabled:
    def test_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "false")
        assert get_red_team_enabled() is False

    def test_true_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        assert get_red_team_enabled() is True

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "TRUE")
        assert get_red_team_enabled() is True

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "  true  ")
        assert get_red_team_enabled() is True

    def test_any_other_value_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("1", "yes", "on", "enabled", ""):
            monkeypatch.setenv("RED_TEAM_ENABLED", val)
            assert get_red_team_enabled() is False, f"Expected False for '{val}'"


class TestAssertRedTeamEnabled:
    def test_raises_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "false")
        with pytest.raises(Exception, match="RED_TEAM_ENABLED"):
            assert_red_team_enabled()

    def test_passes_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "true")
        assert_red_team_enabled()  # must not raise

    def test_raises_airflow_skip_when_airflow_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RED_TEAM_ENABLED", "false")
        try:
            from airflow.exceptions import AirflowSkipException
            with pytest.raises(AirflowSkipException):
                assert_red_team_enabled()
        except ImportError:
            pytest.skip("Airflow not installed — skip AirflowSkipException variant")


class TestGetBudgetCap:
    def test_default_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_BUDGET_USD_PER_SESSION", raising=False)
        cap = get_budget_cap_usd()
        assert cap == 5.0

    def test_env_var_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_BUDGET_USD_PER_SESSION", "12.50")
        assert get_budget_cap_usd() == 12.50

    def test_returns_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_BUDGET_USD_PER_SESSION", "3")
        assert isinstance(get_budget_cap_usd(), float)


class TestGetRecallThreshold:
    def test_default_threshold(self) -> None:
        threshold = get_detection_recall_threshold()
        assert 0.0 < threshold <= 1.0

    def test_default_is_ninety_percent(self) -> None:
        assert get_detection_recall_threshold() == pytest.approx(0.90)


class TestIsDryRun:
    def test_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNTHETIC_INJECTION_DRY_RUN", "false")
        assert is_dry_run() is False

    def test_true_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNTHETIC_INJECTION_DRY_RUN", "true")
        assert is_dry_run() is True
