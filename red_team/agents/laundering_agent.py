"""
Money laundering attacker agent.

Generates multi-hop transaction graph scenarios for Neo4j ingestion.
Models all three laundering phases:
  - Placement: injecting illicit funds into the financial system
  - Layering: obscuring origin through a chain of accounts
  - Integration: merging funds back into the legitimate economy

Output is structured to seed Neo4j (Account)-[:SENT_TO]->(Account) chains
detectable by Louvain community detection in Sprint 6.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from red_team.agents.base_agent import BaseAgent, ScenarioConfig

_TEMPLATE_DIR = Path(__file__).parent / "prompts"
_JINJA_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)

_DEFAULT_EVASION_TACTICS = [
    "smurfing",
    "round_trip_transactions",
    "shell_company_layering",
    "trade_based_laundering",
    "rapid_cycling",
]

_TARGET_SEGMENTS = [
    "retail_banking",
    "corporate_banking",
    "payment_processor",
    "crypto_exchange",
    "real_estate_adjacent",
]


class LaunderingAgent(BaseAgent):
    """
    LLM-powered money laundering scenario generator.

    Outputs transaction chains structured as adjacency lists compatible with
    the Neo4j graph schema defined in Sprint 6 (Account, Transaction nodes).
    """

    _CALLS_PER_MINUTE = 12

    @property
    def attack_type(self) -> str:
        return "money_laundering"

    def _build_prompt(
        self,
        *,
        complexity: str = "high",
        target_segment: str = "corporate_banking",
        evasion_tactics: list[str] | None = None,
        **_: Any,
    ) -> list[dict[str, str]]:
        tactics = evasion_tactics or _DEFAULT_EVASION_TACTICS[:3]
        template = _JINJA_ENV.get_template("laundering.j2")
        user_content = template.render(
            complexity=complexity,
            target_segment=target_segment,
            evasion_tactics=tactics,
        )
        return [
            {
                "role": "system",
                "content": (
                    "You are a financial crime analyst generating synthetic laundering scenarios "
                    "for a fraud immunity lab's graph detection training dataset. "
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
        target_segment: str = "corporate_banking",
        evasion_tactics: list[str] | None = None,
    ) -> ScenarioConfig:
        return super().generate_scenario(
            complexity=complexity,
            target_segment=target_segment,
            evasion_tactics=evasion_tactics,
        )
