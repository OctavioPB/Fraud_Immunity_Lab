"""
cost_tracker — Per-Tenant OpenAI API Cost Tracking
====================================================

Logs each LLM invocation to PostgreSQL (`llm_cost_log` table) and checks
monthly budget thresholds.

Alert fires at 80% of monthly budget — logged as a structured warning so
Prometheus/Grafana can scrape and page on it.

Usage (from attacker agents):
    tracker = CostTracker()
    tracker.log_cost(tenant_id="acme", model="gpt-4o",
                     prompt_tokens=1_200, completion_tokens=450)
    if tracker.is_over_budget_warning(tenant_id, budget_usd=100.0):
        ...
"""

import os
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# OpenAI pricing (USD per 1 K tokens, as of 2025 — update when pricing changes)
_MODEL_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.00060},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "text-embedding-3-large": {"prompt": 0.00013, "completion": 0.0},
    "text-embedding-3-small": {"prompt": 0.00002, "completion": 0.0},
}
_DEFAULT_COST_PER_1K = {"prompt": 0.01, "completion": 0.03}

_BUDGET_WARN_FRACTION: float = 0.80
_POSTGRES_DSN: str = os.getenv(
    "DATABASE_URL",
    "postgresql://airflow:airflow@localhost:5432/airflow",
)


def estimate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return estimated cost in USD for a single LLM call."""
    pricing = _MODEL_COST_PER_1K.get(model, _DEFAULT_COST_PER_1K)
    return round(
        (prompt_tokens / 1_000) * pricing["prompt"]
        + (completion_tokens / 1_000) * pricing["completion"],
        6,
    )


class CostTracker:
    """Logs and queries per-tenant LLM spend against PostgreSQL."""

    def _conn(self) -> Any:
        import psycopg2  # type: ignore[import]

        return psycopg2.connect(_POSTGRES_DSN)

    def _ensure_table(self) -> None:
        try:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cost_log (
                    id               SERIAL PRIMARY KEY,
                    tenant_id        VARCHAR(64)  NOT NULL,
                    model            VARCHAR(64)  NOT NULL,
                    prompt_tokens    INTEGER      NOT NULL DEFAULT 0,
                    completion_tokens INTEGER     NOT NULL DEFAULT 0,
                    cost_usd         REAL         NOT NULL,
                    dag_run_id       VARCHAR(128),
                    recorded_at_ms   BIGINT       NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_cost_tenant_time
                    ON llm_cost_log (tenant_id, recorded_at_ms);
                """
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as exc:
            log.warning("cost_tracker_table_ensure_failed", error=str(exc))

    def log_cost(
        self,
        tenant_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
        *,
        dag_run_id: str | None = None,
    ) -> float:
        """
        Record one LLM call and return the estimated cost in USD.

        Gracefully no-ops if PostgreSQL is unavailable (never blocks the
        attacker agent pipeline).
        """
        cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
        try:
            self._ensure_table()
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO llm_cost_log
                    (tenant_id, model, prompt_tokens, completion_tokens,
                     cost_usd, dag_run_id, recorded_at_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    cost,
                    dag_run_id,
                    int(time.time() * 1000),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
            log.debug(
                "llm_cost_logged",
                tenant_id=tenant_id,
                model=model,
                cost_usd=cost,
                total_tokens=prompt_tokens + completion_tokens,
            )
        except Exception as exc:
            log.warning(
                "llm_cost_log_failed",
                tenant_id=tenant_id,
                model=model,
                error=str(exc),
            )

        # Update Prometheus counters (best-effort — never block the pipeline)
        try:
            from api.observability import LLM_COST_USD_TOTAL, LLM_TOKENS_TOTAL, LLM_CALLS_TOTAL  # noqa: PLC0415

            LLM_COST_USD_TOTAL.labels(tenant_id=tenant_id, model=model).inc(cost)
            LLM_TOKENS_TOTAL.labels(tenant_id=tenant_id, model=model, token_type="prompt").inc(prompt_tokens)
            LLM_TOKENS_TOTAL.labels(tenant_id=tenant_id, model=model, token_type="completion").inc(completion_tokens)
            LLM_CALLS_TOTAL.labels(tenant_id=tenant_id, model=model).inc()
        except Exception:
            pass

        return cost

    def get_monthly_spend(self, tenant_id: str) -> float:
        """Return total USD spend for the current calendar month."""
        try:
            import datetime

            now = datetime.datetime.utcnow()
            month_start_ms = int(
                datetime.datetime(now.year, now.month, 1).timestamp() * 1000
            )
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_cost_log "
                "WHERE tenant_id = %s AND recorded_at_ms >= %s",
                (tenant_id, month_start_ms),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return float(row[0]) if row else 0.0
        except Exception as exc:
            log.warning("monthly_spend_query_failed", tenant_id=tenant_id, error=str(exc))
            return 0.0

    def check_budget_alert(
        self,
        tenant_id: str,
        budget_usd: float,
    ) -> bool:
        """
        Check whether monthly spend has crossed the 80% budget warning threshold.

        Returns True if alert should fire.
        Emits a structured warning log (scraped by Prometheus via log-based metrics).
        """
        if budget_usd <= 0:
            return False
        spend = self.get_monthly_spend(tenant_id)
        fraction = spend / budget_usd
        if fraction >= _BUDGET_WARN_FRACTION:
            log.warning(
                "llm_budget_alert",
                tenant_id=tenant_id,
                spend_usd=round(spend, 4),
                budget_usd=budget_usd,
                fraction=round(fraction, 4),
                threshold=_BUDGET_WARN_FRACTION,
            )
            return True
        return False

    def get_spend_summary(self, tenant_id: str, days: int = 30) -> dict:
        """Return a breakdown of spend by model for the last N days."""
        try:
            cutoff_ms = int((time.time() - days * 86_400) * 1000)
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT model,
                       SUM(prompt_tokens) AS prompt_tokens,
                       SUM(completion_tokens) AS completion_tokens,
                       SUM(cost_usd) AS cost_usd,
                       COUNT(*) AS call_count
                FROM llm_cost_log
                WHERE tenant_id = %s AND recorded_at_ms >= %s
                GROUP BY model
                ORDER BY cost_usd DESC
                """,
                (tenant_id, cutoff_ms),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return {
                "tenant_id": tenant_id,
                "days": days,
                "total_usd": round(sum(r[3] for r in rows), 4),
                "by_model": [
                    {
                        "model": r[0],
                        "prompt_tokens": r[1],
                        "completion_tokens": r[2],
                        "cost_usd": round(r[3], 4),
                        "call_count": r[4],
                    }
                    for r in rows
                ],
            }
        except Exception as exc:
            log.warning("spend_summary_failed", tenant_id=tenant_id, error=str(exc))
            return {"tenant_id": tenant_id, "days": days, "total_usd": 0.0, "by_model": []}
