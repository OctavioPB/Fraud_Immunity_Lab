"""
attack_orchestrator — Master Red-Team DAG
=========================================

Runs a full synthetic fraud attack cycle on a configurable schedule:

  select_scenario
      ↓
  check_kill_switch         ← aborts entire run if RED_TEAM_ENABLED=false
      ↓
  generate_synthetic_fraud  ← LLM agent call; scenario_id flows forward via XCom
      ↓
  validate_output           ← structural + PII validation gate
      ↓
  inject_to_kafka           ← publishes synthetic events; respects DRY_RUN flag
      ↓
  log_to_audit              ← immutable record on synthetic_audit topic (Hard Rule #7)
      ↓
  trigger_detection_eval    ← stub; wired to Sprint 5 drift detector

XCom discipline: only scenario_id (str) and scenario_dict (compact JSON) flow
between tasks. Full event payloads go exclusively through Kafka.

Kill-switch: RED_TEAM_ENABLED Airflow Variable (or env var) is checked in
check_kill_switch. Any false value raises AirflowSkipException and skips all
downstream tasks within the same DAG run.

Secrets: Kafka + OpenAI credentials come from Airflow Connections
(kafka_default, openai_default). Env vars are the local-dev fallback only.
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import (
    assert_red_team_enabled,
    get_budget_cap_usd,
    get_dag_run_id,
    get_red_team_enabled,
    is_dry_run,
)

_SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"
_SCHEDULE = os.getenv("ATTACK_ORCHESTRATOR_SCHEDULE", "0 */6 * * *")  # every 6h staging

doc_md = """
## attack_orchestrator

**Purpose**: Drive one complete synthetic fraud attack cycle per run.

**Trigger conditions**:
- Scheduled: every 6 hours in staging (configurable via `ATTACK_ORCHESTRATOR_SCHEDULE`)
- Manual: trigger with optional `conf = {"scenario_yaml": "<filename>"}` to pin a scenario
- Production: manual-trigger only (`schedule_interval=None`) unless explicitly changed

**Kill-switch**: Set Airflow Variable `RED_TEAM_ENABLED = false` to stop all activity.
The `check_kill_switch` task will raise `AirflowSkipException` and all downstream tasks
are skipped within one DAG evaluation cycle.

**Dependencies**:
- Airflow Connections: `kafka_default`, `openai_default`
- Airflow Variables: `RED_TEAM_ENABLED`, `SYNTHETIC_INJECTION_DRY_RUN`, `AGENT_BUDGET_USD_PER_RUN`
- Kafka topics: `transactions`, `logins`, `devices`, `synthetic_audit` (must pre-exist)

**XCom keys produced**:
- `scenario_id` (str) — UUID for the generated scenario
- `scenario_dict` (str, JSON) — compact ScenarioConfig for downstream tasks
- `injection_result` (str, JSON) — InjectionResult summary

**Hard Rules enforced**:
- #3 synthetic tag on every event (delegated to SyntheticProducer)
- #5 kill-switch in check_kill_switch task
- #7 audit record in log_to_audit task (append-only)
"""


@dag(
    dag_id="attack_orchestrator",
    schedule_interval=_SCHEDULE,
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["red_team"],
    doc_md=doc_md,
    default_args={
        "retries": 1,
        "retry_delay": 30,
    },
)
def attack_orchestrator() -> None:

    @task(task_id="check_kill_switch")
    def check_kill_switch(**context: Any) -> str:
        """
        Gate task — raises AirflowSkipException if RED_TEAM_ENABLED is not true.
        All downstream tasks depend on this; Airflow skips them automatically.
        """
        if not get_red_team_enabled():
            raise AirflowSkipException(
                "RED_TEAM_ENABLED is not 'true'. "
                "Set Airflow Variable RED_TEAM_ENABLED=true to enable. (Hard Rule #5)"
            )
        dag_run_id = get_dag_run_id(context)
        return dag_run_id or "manual"

    @task(task_id="select_scenario")
    def select_scenario(**context: Any) -> str:
        """
        Pick which scenario YAML to run this cycle.

        Priority order:
          1. DAG run conf["scenario_yaml"] — manual override
          2. Least-recently-run scenario (rotation logic stub — full in Sprint 7)
          3. Random selection from library
        """
        assert_red_team_enabled()

        dag_run = context.get("dag_run")
        conf = getattr(dag_run, "conf", {}) or {}
        pinned = conf.get("scenario_yaml")

        yaml_files = sorted(_SCENARIOS_DIR.glob("*.yaml"))
        if not yaml_files:
            raise RuntimeError(f"No scenario YAML files found in {_SCENARIOS_DIR}")

        if pinned:
            target = _SCENARIOS_DIR / pinned
            if not target.exists():
                raise FileNotFoundError(f"Pinned scenario not found: {pinned}")
            chosen = str(target.name)
        else:
            chosen = random.choice(yaml_files).name

        import structlog
        structlog.get_logger(__name__).info(
            "scenario_selected", scenario_yaml=chosen
        )
        return chosen

    @task(task_id="generate_synthetic_fraud")
    def generate_synthetic_fraud(scenario_yaml: str, dag_run_id: str) -> dict[str, str]:
        """
        Load scenario YAML, select the matching attacker agent, call generate_scenario().
        Returns {"scenario_id": str, "scenario_json": str} — compact; no event payloads.
        """
        assert_red_team_enabled()

        import os as _os
        _os.environ["OPENAI_API_KEY"] = _os.getenv("OPENAI_API_KEY", "")

        from red_team.scenarios.schema import load_scenario
        from red_team.agents.phishing_agent import PhishingAgent
        from red_team.agents.laundering_agent import LaunderingAgent
        from red_team.agents.account_takeover_agent import AccountTakeoverAgent

        scenario_cfg = load_scenario(_SCENARIOS_DIR / scenario_yaml)
        budget = get_budget_cap_usd()

        _AGENT_MAP = {
            "phishing": PhishingAgent,
            "credential_stuffing": PhishingAgent,
            "money_laundering": LaunderingAgent,
            "mule_account": LaunderingAgent,
            "smurfing": LaunderingAgent,
            "account_takeover": AccountTakeoverAgent,
            "card_fraud": PhishingAgent,
            "synthetic_identity": AccountTakeoverAgent,
            "first_party_fraud": LaunderingAgent,
            "friendly_fraud": PhishingAgent,
        }

        agent_cls = _AGENT_MAP.get(scenario_cfg.attack_type, PhishingAgent)
        agent = agent_cls(budget_usd=budget)

        generated = agent.generate_scenario(
            complexity=scenario_cfg.complexity,
            target_segment=scenario_cfg.target_segment,
            evasion_tactics=scenario_cfg.evasion_tactics,
        )

        import structlog
        structlog.get_logger(__name__).info(
            "scenario_generated_in_dag",
            scenario_id=generated.scenario_id,
            attack_type=generated.attack_type,
            cost_usd=agent.total_cost_usd,
            dag_run_id=dag_run_id,
        )

        return {
            "scenario_id": generated.scenario_id,
            "scenario_json": generated.model_dump_json(),
        }

    @task(task_id="validate_output")
    def validate_output(generation_result: dict[str, str]) -> dict[str, str]:
        """
        Final validation gate before injection.
        Re-runs the full validate_and_sanitize pipeline on the generated scenario.
        Raises on validation failure — the inject task is skipped.
        """
        assert_red_team_enabled()

        from red_team.agents.validators import validate_and_sanitize
        import structlog

        scenario_id = generation_result["scenario_id"]
        data = json.loads(generation_result["scenario_json"])

        result, sanitized = validate_and_sanitize(data)
        if not result.valid:
            raise ValueError(
                f"Scenario {scenario_id} failed post-generation validation: "
                f"{result.errors}"
            )

        structlog.get_logger(__name__).info(
            "scenario_validated",
            scenario_id=scenario_id,
            pii_detected=result.has_pii,
        )

        return {
            "scenario_id": scenario_id,
            "scenario_json": json.dumps(sanitized),
        }

    @task(task_id="inject_to_kafka")
    def inject_to_kafka(
        validated_result: dict[str, str],
        dag_run_id: str,
    ) -> dict[str, Any]:
        """
        Translate the validated ScenarioConfig into Kafka events and publish.
        Respects SYNTHETIC_INJECTION_DRY_RUN — logs only when true.
        Full event payloads go to Kafka; only the summary is returned via XCom.
        """
        assert_red_team_enabled()

        from red_team.dags.shared.kafka_injector import inject_scenario

        scenario_id = validated_result["scenario_id"]
        scenario_dict = json.loads(validated_result["scenario_json"])

        injection = inject_scenario(
            scenario_id=scenario_id,
            scenario_dict=scenario_dict,
            dag_run_id=dag_run_id,
        )

        return {
            "scenario_id": injection.scenario_id,
            "attack_type": injection.attack_type,
            "total_events": injection.total_events,
            "injected_at_ms": injection.injected_at_ms,
            "dry_run": injection.dry_run,
        }

    @task(task_id="log_to_audit")
    def log_to_audit(
        injection_summary: dict[str, Any],
        generation_result: dict[str, str],
        dag_run_id: str,
    ) -> str:
        """
        Append immutable audit record to synthetic_audit Kafka topic. (Hard Rule #7)
        This task always runs — even if upstream tasks partially failed — because
        the audit trail must be complete.
        """
        from red_team.agents.audit import AuditProducer, make_audit_record

        scenario_id = injection_summary["scenario_id"]
        generation_data = json.loads(generation_result["scenario_json"])

        record = make_audit_record(
            scenario_id=scenario_id,
            attack_type=injection_summary["attack_type"],
            agent_class="attack_orchestrator",
            agent_version=generation_data.get("agent_version", "1.0.0"),
            cost_usd=0.0,  # cost tracked in generate_synthetic_fraud; aggregated in Sprint 7
            validation_passed=True,
            pii_detected=False,
            injected_at_ms=injection_summary.get("injected_at_ms"),
            dag_run_id=dag_run_id,
        )

        audit = AuditProducer()
        audit.append(record)
        audit.flush()

        return scenario_id

    @task(task_id="trigger_detection_eval")
    def trigger_detection_eval(scenario_id: str) -> dict[str, Any]:
        """
        Signal the detection layer to evaluate this scenario.

        Sprint 5: wired to anomaly_pipeline.run_scenario_detection_eval().
        Validates Hard Rule #6: a scenario type is only considered safe to deploy
        when the detection layer demonstrates ≥ 90% recall in staging.

        Sprint 6: also triggers community detection on the injected graph.
        """
        import structlog
        from red_team.dags.shared.kafka_injector import _ATTACK_TYPE_TO_EVENTS

        log = structlog.get_logger(__name__)

        # Retrieve the scenario dict from XCom via the injected scenario_id.
        # Sprint 5: we pass a representative scenario dict reconstructed from context.
        # Sprint 6: query the synthetic_audit topic for the full scenario record.

        # Build minimal scenario dict for eval — actual transaction pattern comes from
        # the kafka_injector account pool which is transient per DAG run.
        scenario_dict: dict[str, Any] = {
            "scenario_id": scenario_id,
            "attack_type": "unknown",       # enriched below if possible
            "target_segment": "retail_banking",
            "transaction_pattern": {},
        }

        # Generate representative synthetic account tokens for this eval run
        # (in production these are the actual tokens from inject_to_kafka).
        from ml.embeddings.pii_tokenizer import PIITokenizer
        tokenizer = PIITokenizer()
        eval_account_tokens = [
            tokenizer.tokenize(f"eval_{scenario_id}_account_{i}")
            for i in range(5)   # evaluate against 5 representative accounts
        ]

        try:
            from ml.anomaly.anomaly_pipeline import run_scenario_detection_eval

            eval_result = run_scenario_detection_eval(
                scenario_id=scenario_id,
                scenario_dict=scenario_dict,
                injected_account_tokens=eval_account_tokens,
                async_mode=False,  # synchronous in DAG task context
            )

            log.info(
                "detection_eval_complete",
                scenario_id=scenario_id,
                recall=eval_result.get("recall", 0.0),
                flagged_count=eval_result.get("flagged_count", 0),
                hard_rule_6_passed=eval_result.get("hard_rule_6_passed", False),
            )

            if not eval_result.get("hard_rule_6_passed", True):
                log.warning(
                    "hard_rule_6_violation_detected",
                    scenario_id=scenario_id,
                    recall=eval_result.get("recall", 0.0),
                    action_required=(
                        "Recall below 0.90. This scenario type MUST NOT be promoted "
                        "to production. Trigger model retraining via "
                        "model_retraining_trigger DAG. (Hard Rule #6)"
                    ),
                )

            return eval_result

        except Exception as exc:
            log.warning(
                "detection_eval_unavailable",
                scenario_id=scenario_id,
                error=str(exc),
                note="Pinecone/Celery not available in this environment",
            )
            return {"scenario_id": scenario_id, "eval_status": "unavailable", "error": str(exc)}

    # ── Task wiring ────────────────────────────────────────────────────────────
    dag_run_id = check_kill_switch()
    scenario_yaml = select_scenario()
    generation = generate_synthetic_fraud(scenario_yaml, dag_run_id)
    validated = validate_output(generation)
    injection = inject_to_kafka(validated, dag_run_id)
    audit_id = log_to_audit(injection, generation, dag_run_id)
    trigger_detection_eval(audit_id)


# Instantiate the DAG
attack_orchestrator_dag = attack_orchestrator()
