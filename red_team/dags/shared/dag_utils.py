"""
Shared utilities for all red_team and ml DAGs.

Design rules:
  - Secrets come from Airflow Connections/Variables first, env vars as fallback.
  - RED_TEAM_ENABLED is always checked via get_red_team_enabled(), never raw os.getenv.
  - All functions are safe to import at DAG parse time (no heavy I/O at module level).
"""

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── Kill-switch ───────────────────────────────────────────────────────────────

def get_red_team_enabled() -> bool:
    """
    Read RED_TEAM_ENABLED from Airflow Variable (preferred) or env var (fallback).
    Airflow Variable takes precedence so ops can flip the switch without redeploying.
    Hard Rule #5: this is the canonical check — use nowhere else.
    """
    try:
        from airflow.models import Variable
        val = Variable.get("RED_TEAM_ENABLED", default_var=None)
        if val is not None:
            return val.strip().lower() == "true"
    except Exception:
        pass
    return os.getenv("RED_TEAM_ENABLED", "false").strip().lower() == "true"


def assert_red_team_enabled() -> None:
    """
    Raise AirflowSkipException if RED_TEAM_ENABLED is not true.
    Call this as the first statement of any red-team task.
    """
    if not get_red_team_enabled():
        try:
            from airflow.exceptions import AirflowSkipException
            raise AirflowSkipException(
                "RED_TEAM_ENABLED is not 'true' — skipping red-team task. "
                "Set the Airflow Variable 'RED_TEAM_ENABLED' to 'true' to enable. "
                "(Hard Rule #5)"
            )
        except ImportError:
            raise RuntimeError(
                "RED_TEAM_ENABLED is not 'true'. Red-team tasks are disabled."
            )


# ── Budget cap ────────────────────────────────────────────────────────────────

def get_budget_cap_usd() -> float:
    """Read per-DAG-run LLM budget from Airflow Variable, default $5.00."""
    try:
        from airflow.models import Variable
        return float(Variable.get("AGENT_BUDGET_USD_PER_RUN", default_var="5.0"))
    except Exception:
        return float(os.getenv("AGENT_BUDGET_USD_PER_SESSION", "5.0"))


def get_detection_recall_threshold() -> float:
    """Recall threshold below which ML retraining is triggered. Default 0.90."""
    try:
        from airflow.models import Variable
        return float(Variable.get("DETECTION_RECALL_THRESHOLD", default_var="0.90"))
    except Exception:
        return 0.90


# ── Connection helpers ────────────────────────────────────────────────────────

def get_kafka_bootstrap() -> str:
    """Kafka bootstrap servers from Airflow Connection 'kafka_default' or env."""
    try:
        from airflow.hooks.base import BaseHook
        conn = BaseHook.get_connection("kafka_default")
        return f"{conn.host}:{conn.port or 9092}"
    except Exception:
        return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


def get_openai_api_key() -> str:
    """OpenAI API key from Airflow Connection 'openai_default' or env."""
    try:
        from airflow.hooks.base import BaseHook
        conn = BaseHook.get_connection("openai_default")
        return conn.password or ""
    except Exception:
        return os.getenv("OPENAI_API_KEY", "")


def get_schema_registry_url() -> str:
    """Schema Registry URL from Airflow Connection or env."""
    try:
        from airflow.hooks.base import BaseHook
        conn = BaseHook.get_connection("schema_registry_default")
        return f"http://{conn.host}:{conn.port or 8081}"
    except Exception:
        return os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")


# ── DAG-run metadata ──────────────────────────────────────────────────────────

def get_dag_run_id(context: dict[str, Any] | None = None) -> str | None:
    """Extract DAG run ID from the Airflow task context, or return None."""
    if context is None:
        return None
    dag_run = context.get("dag_run")
    if dag_run is None:
        return None
    return str(getattr(dag_run, "run_id", None))


# ── Dry-run flag ──────────────────────────────────────────────────────────────

def is_dry_run() -> bool:
    """True when SYNTHETIC_INJECTION_DRY_RUN is set — events are logged, not published."""
    try:
        from airflow.models import Variable
        val = Variable.get("SYNTHETIC_INJECTION_DRY_RUN", default_var=None)
        if val is not None:
            return val.strip().lower() == "true"
    except Exception:
        pass
    return os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").strip().lower() == "true"
