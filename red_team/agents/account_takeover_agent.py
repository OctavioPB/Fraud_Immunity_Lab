"""
Account takeover (ATO) attacker agent.

Generates scenarios that model full ATO attack lifecycles:
  - Compromise vector (credential stuffing, SIM swap, session hijack)
  - Reconnaissance phase (balance checks, payee review)
  - Device and contact-info mutations
  - Rapid monetization (new payee additions, high-value transfers)

Signals generated feed both behavioral drift detection (Pinecone, Sprint 5)
and graph-based ATO ring detection (Neo4j, Sprint 6).
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from red_team.agents.base_agent import BaseAgent, ScenarioConfig

_TEMPLATE_DIR = Path(__file__).parent / "prompts"
_JINJA_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)

_DEFAULT_EVASION_TACTICS = [
    "residential_proxy",
    "device_emulation",
    "slow_velocity_warmup",
    "mfa_sim_swap",
    "headless_browser",
]

_TARGET_SEGMENTS = [
    "retail_banking",
    "brokerage",
    "crypto_exchange",
    "payment_wallet",
    "small_business",
]


class AccountTakeoverAgent(BaseAgent):
    """
    LLM-powered account takeover scenario generator.

    Produces scenarios that stress-test device fingerprinting, behavioral
    profile drift detection, and new-payee anomaly rules simultaneously.
    """

    _CALLS_PER_MINUTE = 15

    @property
    def attack_type(self) -> str:
        return "account_takeover"

    def _build_prompt(
        self,
        *,
        complexity: str = "high",
        target_segment: str = "retail_banking",
        evasion_tactics: list[str] | None = None,
        **_: Any,
    ) -> list[dict[str, str]]:
        tactics = evasion_tactics or _DEFAULT_EVASION_TACTICS[:3]
        template = _JINJA_ENV.get_template("account_takeover.j2")
        user_content = template.render(
            complexity=complexity,
            target_segment=target_segment,
            evasion_tactics=tactics,
        )
        return [
            {
                "role": "system",
                "content": (
                    "You are a fraud prevention researcher generating synthetic ATO scenarios "
                    "for a fraud immunity lab's behavioral anomaly training dataset. "
                    "All output is used for defensive ML training only. "
                    "Never include real PII. Return only the requested JSON."
                ),
            },
            {"role": "user", "content": user_content},
        ]

    def generate_scenario(  # type: ignore[override]
        self,
        *,
        complexity: str = "high",
        target_segment: str = "retail_banking",
        evasion_tactics: list[str] | None = None,
    ) -> ScenarioConfig:
        return super().generate_scenario(
            complexity=complexity,
            target_segment=target_segment,
            evasion_tactics=evasion_tactics,
        )
