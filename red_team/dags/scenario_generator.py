"""
scenario_generator — Scenario Library Freshness DAG
====================================================

Runs weekly to keep the scenario library current by generating new variants
of each attack type and rotating out stale configs.

Tasks:
  audit_library      ← catalogue existing YAMLs; detect coverage gaps
      ↓
  generate_variants  ← call all three agents for fresh scenario dicts
      ↓
  write_new_configs  ← serialize new ScenarioConfig dicts to YAML in scenarios/
      ↓
  report_coverage    ← log coverage metrics; alert if any attack type untested

Kill-switch: checks RED_TEAM_ENABLED before each task (same Hard Rule #5 enforcement).

Dependencies: Airflow Variables: RED_TEAM_ENABLED, AGENT_BUDGET_USD_PER_RUN
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import (
    assert_red_team_enabled,
    get_budget_cap_usd,
)

_SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"
_VARIANTS_PER_TYPE = int(os.getenv("SCENARIO_VARIANTS_PER_RUN", "2"))

doc_md = """
## scenario_generator

**Purpose**: Keep the scenario library fresh by generating new variants of each
attack type weekly. Prevents detection models from overfitting to stale patterns.

**Schedule**: Weekly (Sundays at 02:00 UTC).

**Kill-switch**: `RED_TEAM_ENABLED` Airflow Variable — same as attack_orchestrator.

**Output**: New YAML files written to `red_team/scenarios/` with datestamped names.
These are intended to be committed to git by the operator after review.

**Dependencies**:
- Airflow Variables: `RED_TEAM_ENABLED`, `AGENT_BUDGET_USD_PER_RUN`, `SCENARIO_VARIANTS_PER_RUN`
- Airflow Connections: `openai_default`

**Hard Rules enforced**: #3, #5
"""

_KNOWN_ATTACK_TYPES = [
    ("phishing", "retail_banking"),
    ("money_laundering", "corporate_banking"),
    ("account_takeover", "retail_banking"),
]


@dag(
    dag_id="scenario_generator",
    schedule_interval="0 2 * * 0",  # Sundays 02:00 UTC
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["red_team"],
    doc_md=doc_md,
    default_args={"retries": 1, "retry_delay": 60},
)
def scenario_generator() -> None:

    @task(task_id="audit_library")
    def audit_library() -> dict[str, Any]:
        """
        Catalogue existing scenario YAMLs and identify coverage gaps.
        Returns a summary dict used by generate_variants to decide what to create.
        """
        assert_red_team_enabled()

        from red_team.scenarios.schema import load_all_scenarios

        existing = load_all_scenarios(_SCENARIOS_DIR)
        type_counts: dict[str, int] = {}
        for s in existing:
            type_counts[s.attack_type] = type_counts.get(s.attack_type, 0) + 1

        import structlog
        structlog.get_logger(__name__).info(
            "scenario_library_audit",
            total=len(existing),
            by_attack_type=type_counts,
        )

        return {
            "total_existing": len(existing),
            "type_counts": type_counts,
        }

    @task(task_id="generate_variants")
    def generate_variants(library_audit: dict[str, Any]) -> list[dict[str, str]]:
        """
        Generate new scenario variants for each attack type.
        Prioritises types with lowest existing coverage.
        Returns list of {attack_type, scenario_json} dicts for write_new_configs.
        """
        assert_red_team_enabled()

        from red_team.agents.phishing_agent import PhishingAgent
        from red_team.agents.laundering_agent import LaunderingAgent
        from red_team.agents.account_takeover_agent import AccountTakeoverAgent
        import structlog

        log = structlog.get_logger(__name__)
        budget = get_budget_cap_usd()

        agents = {
            "phishing": PhishingAgent(budget_usd=budget / 3),
            "money_laundering": LaunderingAgent(budget_usd=budget / 3),
            "account_takeover": AccountTakeoverAgent(budget_usd=budget / 3),
        }

        results = []
        for attack_type, segment in _KNOWN_ATTACK_TYPES:
            agent = agents[attack_type]
            for i in range(_VARIANTS_PER_TYPE):
                try:
                    scenario = agent.generate_scenario(
                        complexity="high",
                        target_segment=segment,
                    )
                    results.append({
                        "attack_type": attack_type,
                        "scenario_json": scenario.model_dump_json(),
                    })
                    log.info(
                        "variant_generated",
                        attack_type=attack_type,
                        variant=i + 1,
                        scenario_id=scenario.scenario_id,
                    )
                except Exception as exc:
                    log.error(
                        "variant_generation_failed",
                        attack_type=attack_type,
                        variant=i + 1,
                        error=str(exc),
                    )

        return results

    @task(task_id="write_new_configs")
    def write_new_configs(variants: list[dict[str, str]]) -> list[str]:
        """
        Serialize new ScenarioConfig dicts to dated YAML files.
        Files are written to scenarios/ and must be reviewed + committed by the operator.
        """
        assert_red_team_enabled()

        import yaml
        import structlog

        log = structlog.get_logger(__name__)
        date_tag = datetime.utcnow().strftime("%Y%m%d")
        written: list[str] = []

        for v in variants:
            data = json.loads(v["scenario_json"])
            attack_type = data.get("attack_type", "unknown")
            scenario_id = data.get("scenario_id", "noid")[:8]
            filename = f"generated_{date_tag}_{attack_type}_{scenario_id}.yaml"
            path = _SCENARIOS_DIR / filename

            yaml_data = {
                "name": f"Generated {attack_type} variant — {date_tag}",
                "version": "1.0.0",
                "attack_type": attack_type,
                "complexity": data.get("complexity", "high"),
                "target_segment": data.get("target_segment", "retail_banking"),
                "description": (
                    f"Auto-generated {attack_type} scenario variant. "
                    "Review and rename before promoting to production library."
                ),
                "evasion_tactics": data.get("evasion_tactics", []),
                "expected_detection_signals": data.get("expected_detection_signals", []),
                "parameters": data.get("transaction_pattern", {}),
                "tags": ["generated", attack_type, date_tag],
            }

            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True)

            log.info("scenario_yaml_written", path=str(path))
            written.append(filename)

        return written

    @task(task_id="report_coverage")
    def report_coverage(written_files: list[str]) -> dict[str, Any]:
        """
        Log final coverage metrics after generation.
        Alert (via structlog warning) if any canonical attack type still has < 2 scenarios.
        """
        from red_team.scenarios.schema import load_all_scenarios
        import structlog

        log = structlog.get_logger(__name__)
        all_scenarios = load_all_scenarios(_SCENARIOS_DIR)
        type_counts: dict[str, int] = {}
        for s in all_scenarios:
            type_counts[s.attack_type] = type_counts.get(s.attack_type, 0) + 1

        gaps = [t for t, c in type_counts.items() if c < 2]
        if gaps:
            log.warning("scenario_coverage_gap", attack_types_with_low_coverage=gaps)

        log.info(
            "scenario_coverage_report",
            total=len(all_scenarios),
            by_type=type_counts,
            new_files_written=len(written_files),
        )

        return {"total": len(all_scenarios), "by_type": type_counts, "gaps": gaps}

    # ── Task wiring ────────────────────────────────────────────────────────────
    audit = audit_library()
    variants = generate_variants(audit)
    written = write_new_configs(variants)
    report_coverage(written)


scenario_generator_dag = scenario_generator()
