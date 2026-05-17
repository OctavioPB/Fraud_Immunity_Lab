"""
Phishing & credential stuffing attacker agent.

Generates scenarios that model a full phishing attack lifecycle:
  1. Credential harvest (spear-phishing email, lookalike domain, smishing)
  2. Login sequence with device/geo anomalies
  3. Post-compromise transactions that follow the attack pattern

Output feeds the ingestion pipeline as synthetic LoginEvents + TransactionEvents.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from red_team.agents.base_agent import BaseAgent, ScenarioConfig

_TEMPLATE_DIR = Path(__file__).parent / "prompts"
_JINJA_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)

_DEFAULT_EVASION_TACTICS = [
    "vpn_exit_node",
    "residential_proxy",
    "low_velocity_warmup",
    "trusted_device_spoofing",
    "lookalike_domain",
]

_TARGET_SEGMENTS = [
    "retail_banking",
    "wealth_management",
    "small_business",
    "corporate_treasury",
    "crypto_exchange",
]


class PhishingAgent(BaseAgent):
    """
    LLM-powered phishing scenario generator.

    Each call produces a novel scenario describing a phishing attack path
    from initial email delivery to post-compromise cash-out transactions.
    """

    _CALLS_PER_MINUTE = 15

    @property
    def attack_type(self) -> str:
        return "phishing"

    def _build_prompt(
        self,
        *,
        complexity: str = "high",
        target_segment: str = "retail_banking",
        evasion_tactics: list[str] | None = None,
        **_: Any,
    ) -> list[dict[str, str]]:
        tactics = evasion_tactics or _DEFAULT_EVASION_TACTICS[:3]
        template = _JINJA_ENV.get_template("phishing.j2")
        user_content = template.render(
            complexity=complexity,
            target_segment=target_segment,
            evasion_tactics=tactics,
        )
        return [
            {
                "role": "system",
                "content": (
                    "You are a security researcher generating synthetic fraud scenarios "
                    "for a fraud immunity lab. All output is used for defensive ML training only. "
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
