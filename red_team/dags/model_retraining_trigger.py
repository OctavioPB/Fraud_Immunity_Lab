"""
model_retraining_trigger — ML Retraining Trigger DAG
=====================================================

Runs daily to check detection recall against the configured threshold.
If recall drops below threshold, triggers an ML retraining pipeline run.

Tasks:
  fetch_detection_metrics  ← query detection API or database for current recall
      ↓
  evaluate_recall          ← compare against DETECTION_RECALL_THRESHOLD
      ↓
  trigger_retraining       ← conditionally trigger retraining (ShortCircuit-style)
      ↓
  notify_ops               ← log alert when retraining is triggered

Sprint 4: fetch_detection_metrics is a stub returning synthetic metrics.
Sprint 5: wired to real drift detection results from Pinecone + Celery.
Sprint 7: wired to Immunity Score engine for threshold data.

Tags: ["ml"] — separate from red_team tag so it can run independently.

Dependencies:
- Airflow Variables: DETECTION_RECALL_THRESHOLD
- Sprint 5+: Airflow Connection to PostgreSQL metrics store
"""

import json
import os
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import get_detection_recall_threshold

doc_md = """
## model_retraining_trigger

**Purpose**: Continuously validate that the detection layer can catch synthetic fraud.
Triggers ML retraining when recall drops below the configured threshold.

**Schedule**: Daily at 03:00 UTC (off-peak).

**Threshold**: Airflow Variable `DETECTION_RECALL_THRESHOLD` (default 0.90).

**Retraining trigger**: When `current_recall < threshold`, this DAG raises a
Airflow sensor signal and logs an actionable alert. In Sprint 5+, it will
directly invoke the Pinecone profile rebuilder and anomaly model refit.

**Dependencies**:
- Airflow Variables: `DETECTION_RECALL_THRESHOLD`
- Sprint 5+: `detection_api_default` Airflow Connection

**Tags**: `["ml"]` — runs independently of red_team DAGs.

**Hard Rules enforced**: #6 (detection must precede deployment)
"""


@dag(
    dag_id="model_retraining_trigger",
    schedule_interval="0 3 * * *",  # daily 03:00 UTC
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["ml"],
    doc_md=doc_md,
    default_args={"retries": 2, "retry_delay": 120},
)
def model_retraining_trigger() -> None:

    @task(task_id="fetch_detection_metrics")
    def fetch_detection_metrics() -> dict[str, Any]:
        """
        Fetch current detection recall metrics.

        Sprint 4: returns a stub value based on env var or synthetic random data.
        Sprint 5: replaced by query against detection_results Kafka topic aggregates.
        Sprint 7: query Immunity Score API for DetectionCoverage component.
        """
        import random
        import structlog

        log = structlog.get_logger(__name__)

        # Sprint 4 stub — simulate realistic recall with occasional drops
        stub_recall = float(os.getenv("STUB_DETECTION_RECALL", "0.0"))
        if stub_recall == 0.0:
            # Simulate realistic recall: mostly good, occasionally degraded
            stub_recall = round(random.uniform(0.84, 0.97), 4)

        metrics = {
            "recall": stub_recall,
            "false_positive_rate": round(random.uniform(0.005, 0.025), 4),
            "scenarios_evaluated": random.randint(20, 200),
            "attack_types_covered": random.randint(5, 10),
            "source": "stub_sprint4",
        }

        log.info("detection_metrics_fetched", **metrics)
        return metrics

    @task(task_id="evaluate_recall")
    def evaluate_recall(metrics: dict[str, Any]) -> dict[str, Any]:
        """
        Compare current recall against the threshold.
        Returns {needs_retraining: bool, shortfall: float, ...}.
        Hard Rule #6: if shortfall > 0, a new scenario type is NOT safe to deploy.
        """
        import structlog

        log = structlog.get_logger(__name__)
        threshold = get_detection_recall_threshold()
        current_recall = metrics["recall"]
        shortfall = max(0.0, threshold - current_recall)
        needs_retraining = shortfall > 0

        result = {
            "current_recall": current_recall,
            "threshold": threshold,
            "shortfall": round(shortfall, 4),
            "needs_retraining": needs_retraining,
            "false_positive_rate": metrics.get("false_positive_rate", 0.0),
            "scenarios_evaluated": metrics.get("scenarios_evaluated", 0),
        }

        if needs_retraining:
            log.warning(
                "detection_recall_below_threshold",
                current_recall=current_recall,
                threshold=threshold,
                shortfall=shortfall,
                hard_rule="Rule #6: detection must meet threshold before new scenarios deploy",
            )
        else:
            log.info(
                "detection_recall_healthy",
                current_recall=current_recall,
                threshold=threshold,
            )

        return result

    @task(task_id="trigger_retraining")
    def trigger_retraining(evaluation: dict[str, Any]) -> dict[str, Any]:
        """
        Conditionally trigger ML retraining pipeline.

        Sprint 4: logs the intent; no actual retraining invoked.
        Sprint 5: calls Celery task profile_builder.rebuild_all_profiles.delay()
        Sprint 7: also recomputes Immunity Score ModelFreshness component.

        Returns {triggered: bool, reason: str}.
        """
        import structlog

        log = structlog.get_logger(__name__)

        if not evaluation["needs_retraining"]:
            log.info(
                "retraining_not_needed",
                current_recall=evaluation["current_recall"],
                threshold=evaluation["threshold"],
            )
            return {
                "triggered": False,
                "reason": f"recall {evaluation['current_recall']:.4f} >= threshold {evaluation['threshold']}",
            }

        # Sprint 4 stub — log the trigger intent
        log.warning(
            "retraining_triggered",
            shortfall=evaluation["shortfall"],
            false_positive_rate=evaluation["false_positive_rate"],
            note="Sprint 4 stub — Celery task will be wired in Sprint 5",
        )

        # Sprint 5 hook (commented out until Celery tasks exist):
        # from ml.embeddings.profile_builder import rebuild_all_profiles
        # rebuild_all_profiles.delay()

        return {
            "triggered": True,
            "reason": (
                f"recall {evaluation['current_recall']:.4f} < "
                f"threshold {evaluation['threshold']} "
                f"(shortfall: {evaluation['shortfall']:.4f})"
            ),
            "scenarios_evaluated": evaluation["scenarios_evaluated"],
        }

    @task(task_id="notify_ops")
    def notify_ops(retraining_result: dict[str, Any], evaluation: dict[str, Any]) -> None:
        """
        Log a structured ops alert when retraining is triggered.
        Sprint 9+: integrate with PagerDuty / Slack webhook via Airflow Connection.
        """
        import structlog

        log = structlog.get_logger(__name__)

        if retraining_result["triggered"]:
            log.warning(
                "ops_alert_retraining_triggered",
                reason=retraining_result["reason"],
                current_recall=evaluation["current_recall"],
                threshold=evaluation["threshold"],
                action_required=(
                    "Review detection model performance. "
                    "New synthetic scenario types must NOT be deployed until "
                    "recall returns to >= threshold. (Hard Rule #6)"
                ),
            )
        else:
            log.info(
                "ops_check_passed",
                recall=evaluation["current_recall"],
                threshold=evaluation["threshold"],
            )

    # ── Task wiring ────────────────────────────────────────────────────────────
    metrics = fetch_detection_metrics()
    evaluation = evaluate_recall(metrics)
    retraining = trigger_retraining(evaluation)
    notify_ops(retraining, evaluation)


model_retraining_trigger_dag = model_retraining_trigger()
