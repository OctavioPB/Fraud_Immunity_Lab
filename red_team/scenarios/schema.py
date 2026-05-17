"""
Pydantic schema for scenario YAML config files.
Every .yaml file in red_team/scenarios/ is validated against ScenarioYamlConfig
at load time. Unknown fields are rejected to prevent silent misconfiguration.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class ScenarioYamlConfig(BaseModel):
    """Validated representation of a scenario YAML config file."""

    model_config = {"extra": "forbid"}

    name: str = Field(description="Human-readable scenario name")
    version: str = Field(description="Semantic version of this scenario config")
    attack_type: str = Field(description="Machine-readable attack type identifier")
    complexity: str = Field(
        pattern="^(low|medium|high|critical)$",
        description="Attack complexity level",
    )
    target_segment: str = Field(description="Banking/financial segment being targeted")
    description: str = Field(description="Plain-English summary of the attack pattern")
    evasion_tactics: list[str] = Field(
        min_length=1,
        description="Ordered list of evasion techniques used in this scenario",
    )
    expected_detection_signals: list[str] = Field(
        min_length=1,
        description="Named detection signals this scenario should trigger",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Scenario-specific parameters passed to the attacker agent",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form tags for filtering and reporting",
    )

    @field_validator("attack_type")
    @classmethod
    def attack_type_known(cls, v: str) -> str:
        known = {
            "phishing",
            "credential_stuffing",
            "money_laundering",
            "account_takeover",
            "card_fraud",
            "synthetic_identity",
            "first_party_fraud",
            "mule_account",
            "smurfing",
            "friendly_fraud",
        }
        if v not in known:
            raise ValueError(
                f"Unknown attack_type '{v}'. Known types: {sorted(known)}"
            )
        return v


def load_scenario(path: Path) -> ScenarioYamlConfig:
    """Load and validate a single scenario YAML file."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ScenarioYamlConfig(**raw)


def load_all_scenarios(
    directory: Path | None = None,
) -> list[ScenarioYamlConfig]:
    """Load and validate all .yaml files in the scenarios directory."""
    if directory is None:
        directory = Path(__file__).parent
    scenarios = []
    for yaml_path in sorted(directory.glob("*.yaml")):
        scenarios.append(load_scenario(yaml_path))
    return scenarios
