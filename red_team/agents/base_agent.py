"""
Base attacker agent — all LLM-powered fraud scenario generators extend this.

Enforces (all non-negotiable):
  - RED_TEAM_ENABLED kill-switch on every entry point       (Hard Rule #5)
  - synthetic=true tag on every generated scenario          (Hard Rule #3)
  - PII scan + strip before scenario is accepted            (Hard Rule #4)
  - Append-only audit record to synthetic_audit on every call (Hard Rule #7)
  - Rate limiting and cost budget cap per session
  - JSON Schema validation with up to 3 retry attempts
"""

import functools
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from threading import Lock
from typing import Any

import structlog
from pydantic import BaseModel, Field

from red_team.agents.audit import AuditProducer, make_audit_record
from red_team.agents.validators import validate_and_sanitize

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_AGENT_VERSION = "1.0.0"


# ── ScenarioConfig ────────────────────────────────────────────────────────────

class ScenarioConfig(BaseModel):
    """Canonical output schema for every attacker agent. (Hard Rule #3 enforced)"""

    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    attack_type: str
    complexity: str = Field(pattern="^(low|medium|high|critical)$")
    target_segment: str
    evasion_tactics: list[str] = Field(min_length=1)
    transaction_pattern: dict[str, Any]
    expected_detection_signals: list[str] = Field(min_length=1)
    agent_version: str = _AGENT_VERSION
    # Hard Rule #3: always present, always true
    synthetic: bool = True
    origin: str = "red_team"


# ── Kill-switch decorator ─────────────────────────────────────────────────────

def require_red_team_enabled(fn):  # type: ignore[no-untyped-def]
    """Blocks execution when RED_TEAM_ENABLED != 'true'. (Hard Rule #5)"""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if os.getenv("RED_TEAM_ENABLED", "false").lower() != "true":
            logger.warning("red_team_disabled_kill_switch", fn=fn.__qualname__)
            raise RuntimeError(
                "RED_TEAM_ENABLED is not set to 'true'. "
                "Attacker agent calls are blocked. (Hard Rule #5)"
            )
        return fn(*args, **kwargs)

    return wrapper


# ── Rate limiter ──────────────────────────────────────────────────────────────

class _RateLimiter:
    """Token-bucket rate limiter for LLM API calls."""

    def __init__(self, calls_per_minute: int) -> None:
        self._min_interval = 60.0 / max(1, calls_per_minute)
        self._last_call_ts: float = 0.0
        self._lock = Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call_ts)
            if wait > 0:
                time.sleep(wait)
            self._last_call_ts = time.monotonic()


# ── Base agent ────────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """
    Abstract attacker agent. Subclasses implement:
      - _build_prompt(**kwargs) -> list[dict]   (OpenAI messages list)
      - attack_type property (str)
    """

    # Override in subclasses for per-agent rate limits
    _CALLS_PER_MINUTE: int = 20

    def __init__(
        self,
        model: str | None = None,
        budget_usd: float | None = None,
    ) -> None:
        self._model = model or os.getenv("OPENAI_AGENT_MODEL", "gpt-4o")
        self._budget_usd = budget_usd or float(
            os.getenv("AGENT_BUDGET_USD_PER_SESSION", "5.0")
        )
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0
        self._rate_limiter = _RateLimiter(self._CALLS_PER_MINUTE)
        self._audit = AuditProducer()

    # ── Subclass interface ────────────────────────────────────────────────────

    @abstractmethod
    def _build_prompt(self, **kwargs: Any) -> list[dict[str, str]]:
        """Return OpenAI messages list for the scenario generation call."""
        ...

    @property
    @abstractmethod
    def attack_type(self) -> str:
        """Machine-readable attack type identifier for this agent."""
        ...

    # ── Cost tracking ─────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
        # gpt-4o pricing (2025) — update when model changes
        return (prompt_tokens / 1_000_000) * 2.50 + (completion_tokens / 1_000_000) * 10.00

    def _check_budget(self, projected_additional: float = 0.0) -> None:
        if self._total_cost_usd + projected_additional > self._budget_usd:
            raise RuntimeError(
                f"Budget cap exceeded: spent ${self._total_cost_usd:.4f} of "
                f"${self._budget_usd:.2f} limit. "
                "Increase AGENT_BUDGET_USD_PER_SESSION to continue."
            )

    # ── Core generation ───────────────────────────────────────────────────────

    @require_red_team_enabled
    def generate_scenario(self, **kwargs: Any) -> ScenarioConfig:
        """
        Generate one validated fraud scenario. Retries up to 3 times on failure.
        Appends an audit record to synthetic_audit on EVERY attempt (pass or fail).
        Hard Rules #3, #4, #5, #7 are all enforced here.
        """
        import openai

        self._check_budget(projected_additional=0.002)  # rough pre-flight check
        self._rate_limiter.acquire()

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        scenario_id = str(uuid.uuid4())
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            cost: float = 0.0
            validation_passed = False
            pii_detected = False

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

                # Hard Rule #3: enforce synthetic tag regardless of LLM output
                data["synthetic"] = True
                data["origin"] = "red_team"
                data["scenario_id"] = scenario_id
                data["agent_version"] = _AGENT_VERSION

                # Validate structure + PII scan (Hard Rules #4)
                result, data = validate_and_sanitize(data)
                pii_detected = result.has_pii

                if not result.valid:
                    raise ValueError(f"Schema validation failed: {result.errors}")

                validation_passed = True
                scenario = ScenarioConfig(**data)

                # Hard Rule #7: audit record appended before any injection
                self._audit.append(
                    make_audit_record(
                        scenario_id=scenario_id,
                        attack_type=self.attack_type,
                        agent_class=type(self).__name__,
                        agent_version=_AGENT_VERSION,
                        cost_usd=cost,
                        validation_passed=True,
                        pii_detected=pii_detected,
                    )
                )

                logger.info(
                    "scenario_generated",
                    attack_type=scenario.attack_type,
                    scenario_id=scenario_id,
                    attempt=attempt,
                    cost_usd=round(cost, 6),
                    total_cost_usd=round(self._total_cost_usd, 6),
                )
                return scenario

            except Exception as exc:
                last_exc = exc
                # Audit the failed attempt too (Hard Rule #7)
                self._audit.append(
                    make_audit_record(
                        scenario_id=scenario_id,
                        attack_type=self.attack_type,
                        agent_class=type(self).__name__,
                        agent_version=_AGENT_VERSION,
                        cost_usd=cost,
                        validation_passed=validation_passed,
                        pii_detected=pii_detected,
                    )
                )
                logger.warning(
                    "scenario_generation_attempt_failed",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(2 ** attempt)

        raise RuntimeError(
            f"generate_scenario exhausted {_MAX_RETRIES} retries"
        ) from last_exc

    def generate_batch(self, count: int = 20, **kwargs: Any) -> list[ScenarioConfig]:
        """
        Generate `count` unique scenarios. Raises on budget exhaustion.
        Definition of Done requires ≥ 20 unique outputs per agent per run.
        """
        results: list[ScenarioConfig] = []
        seen_ids: set[str] = set()

        for i in range(count):
            self._check_budget()
            scenario = self.generate_scenario(**kwargs)
            if scenario.scenario_id not in seen_ids:
                seen_ids.add(scenario.scenario_id)
                results.append(scenario)
            logger.info(
                "batch_progress",
                agent=type(self).__name__,
                generated=i + 1,
                total=count,
            )

        self._audit.flush()
        return results

    # ── Observability ─────────────────────────────────────────────────────────

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    @property
    def call_count(self) -> int:
        return self._call_count

    def cost_summary(self) -> dict[str, Any]:
        return {
            "agent": type(self).__name__,
            "call_count": self._call_count,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "budget_usd": self._budget_usd,
            "budget_remaining_usd": round(
                self._budget_usd - self._total_cost_usd, 6
            ),
        }
