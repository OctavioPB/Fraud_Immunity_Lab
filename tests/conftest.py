"""Shared pytest fixtures for all test suites."""

import os

import pytest


@pytest.fixture(autouse=True)
def disable_red_team_in_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Unit tests must not trigger real LLM calls or inject into Kafka.
    Override env flags so the kill-switch is active by default.
    """
    monkeypatch.setenv("RED_TEAM_ENABLED", "false")
    monkeypatch.setenv("SYNTHETIC_INJECTION_DRY_RUN", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")


@pytest.fixture
def red_team_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable red-team for tests that specifically need to exercise agent logic."""
    monkeypatch.setenv("RED_TEAM_ENABLED", "true")
