"""
Base attacker agent — all LLM-powered fraud scenario generators extend this.
Enforces: rate limiting, cost tracking, output validation, audit logging,
and the RED_TEAM_ENABLED kill-switch (Hard Rule #5).
"""

import functools
import json
import os
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 3


class ScenarioConfig(BaseModel):
    """Canonical output schema for every attacker agent."""

    attack_type: str
    complexity: str = Field(pattern="^(low|medium|high|critical)$")
    target_segment: str
    evasion_tactics: list[str]
    transaction_pattern: dict[str, Any]
    expected_detection_signals: list[str]
    # Hard Rule #3: synthetic tag is always present
    synthetic: bool = True
    origin: str = "red_team"


def require_red_team_enabled(fn):  # type: ignore[no-untyped-def]
    """Decorator that enforces the RED_TEAM_ENABLED kill-switch (Hard Rule #5)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if os.getenv("RED_TEAM_ENABLED", "false").lower() != "true":
            logger.warning(
                "red_team_disabled_kill_switch",
                fn=fn.__qualname__,
            )
            raise RuntimeError(
                "RED_TEAM_ENABLED is not set to 'true'. "
                "Attacker agent calls are blocked. (Hard Rule #5)"
            )
        return fn(*args, **kwargs)

    return wrapper


class BaseAgent(ABC):
    """Abstract attacker agent. Subclasses implement generate_scenario()."""

    def __init__(self, model: str | None = None) -> None:
        self._model = model or os.getenv("OPENAI_AGENT_MODEL", "gpt-4o")
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0

    @abstractmethod
    def _build_prompt(self, **kwargs: Any) -> list[dict[str, str]]:
        """Return the messages list for the OpenAI chat completion call."""
        ...

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # gpt-4o pricing as of 2025 — update if model changes
        input_cost = (prompt_tokens / 1_000_000) * 2.50
        output_cost = (completion_tokens / 1_000_000) * 10.00
        return input_cost + output_cost

    @require_red_team_enabled
    def generate_scenario(self, **kwargs: Any) -> ScenarioConfig:
        """Generate and validate one fraud scenario. Retries up to 3 times."""
        import openai

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                messages = self._build_prompt(**kwargs)
                response = client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.9,
                )

                raw_output = response.choices[0].message.content
                cost = self._estimate_cost(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
                self._total_cost_usd += cost
                self._call_count += 1

                data = json.loads(raw_output)
                # Enforce synthetic tag regardless of LLM output (Hard Rule #3)
                data["synthetic"] = True
                data["origin"] = "red_team"

                scenario = ScenarioConfig(**data)
                logger.info(
                    "scenario_generated",
                    attack_type=scenario.attack_type,
                    attempt=attempt,
                    cost_usd=round(cost, 6),
                )
                return scenario

            except Exception as exc:
                logger.warning(
                    "scenario_generation_failed",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == _MAX_RETRIES:
                    raise
                time.sleep(2**attempt)

        raise RuntimeError("generate_scenario exhausted retries")

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd
