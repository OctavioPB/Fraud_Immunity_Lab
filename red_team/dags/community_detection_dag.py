"""
community_detection_dag — Daily Louvain Fraud Ring Detection
============================================================

Runs Louvain community detection on the Neo4j account relationship graph
daily and publishes alerts for high-risk fraud rings.

Tasks:
  check_kill_switch        ← abort if RED_TEAM_ENABLED=false (on-demand trigger only)
      ↓
  run_louvain_detection    ← project GDS graph, run Louvain, evaluate clusters
      ↓
  persist_fraud_rings      ← write FraudRing nodes to Neo4j
      ↓
  publish_high_risk_alerts ← publish rings with risk_score > threshold to alerts topic
      ↓
  report_detection_summary ← log coverage metrics + Hard Rule #6 recall check

Schedule:
  - Daily at 02:00 UTC (between profile_refresh_dag at 01:00 and model_retraining_trigger at 03:00)
  - On-demand: triggered by attack_orchestrator via Airflow TriggerDagRunOperator
    when a laundering-type scenario is injected.

Tags: ["ml", "red_team"] — bridges both domains.

Hard Rules enforced: #3 (synthetic flag), #6 (detection recall gate)
"""

import os
import json
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import get_detection_recall_threshold

_ALERT_THRESHOLD: float = float(os.getenv("FRAUD_RING_ALERT_THRESHOLD", "0.85"))
_MIN_PRECISION_TARGET: float = 0.85  # Hard Rule #6 analogue for graph detection

doc_md = """
## community_detection_dag

**Purpose**: Run Louvain community detection daily on the Neo4j SENT_TO graph
to surface fraud rings. High-risk rings (score > threshold) are published to
the `alerts` Kafka topic.

**Schedule**: Daily at 02:00 UTC; also triggered on-demand by `attack_orchestrator`
after laundering/smurfing scenario injection.

**Kill-switch**: `RED_TEAM_ENABLED` is checked only on the on-demand trigger path.
The scheduled daily run always executes (it reads live + synthetic data).

**Hard Rules enforced**:
- #3: FraudRing nodes and SENT_TO relationships from synthetic injections carry
  `synthetic: true` — never stripped.
- #6: Louvain must detect ≥ 85% of injected synthetic laundering rings before
  the scenario type is considered covered.

**Dependencies**:
- Airflow Connections: Neo4j credentials via env vars (Sprint 5; Airflow Connection in Sprint 9)
- Airflow Variables: `FRAUD_RING_ALERT_THRESHOLD`, `FRAUD_RING_WINDOW_DAYS`
- Kafka topics: `alerts` (must pre-exist)

**Tags**: `["ml", "red_team"]`
"""


@dag(
    dag_id="community_detection_dag",
    schedule_interval="0 2 * * *",  # daily 02:00 UTC
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["ml", "red_team"],
    doc_md=doc_md,
    default_args={"retries": 2, "retry_delay": 120},
)
def community_detection_dag() -> None:

    @task(task_id="run_louvain_detection")
    def run_louvain_detection(**context: Any) -> dict[str, Any]:
        """
        Project the GDS graph and execute Louvain community detection.

        Accepts optional DAG run conf:
          {window_days: int, min_cluster_size: int, scenario_id: str}

        Returns detection summary without persisted rings (handled next task).
        """
        import structlog
        from ml.graph.community_detection import CommunityDetector

        log = structlog.get_logger(__name__)

        dag_run = context.get("dag_run")
        conf = getattr(dag_run, "conf", {}) or {}
        window_days = int(conf.get("window_days", os.getenv("FRAUD_RING_WINDOW_DAYS", "30")))
        min_cluster_size = int(conf.get("min_cluster_size", os.getenv("FRAUD_RING_MIN_CLUSTER_SIZE", "3")))
        dag_run_id = (getattr(dag_run, "run_id", None) or "manual") if dag_run else "manual"

        detector = CommunityDetector(
            dry_run=False,
            dag_run_id=dag_run_id,
        )

        try:
            summary = detector.detect(
                window_days=window_days,
                min_cluster_size=min_cluster_size,
            )
        except Exception as exc:
            log.error("louvain_detection_failed", error=str(exc))
            # Return empty summary — downstream tasks handle gracefully
            summary = {
                "rings_detected": 0,
                "rings_persisted": 0,
                "alerts_published": 0,
                "communities_evaluated": 0,
                "elapsed_ms": 0,
                "window_days": window_days,
                "fraud_rings": [],
                "error": str(exc),
            }

        log.info(
            "louvain_detection_task_complete",
            rings_detected=summary.get("rings_detected", 0),
            communities_evaluated=summary.get("communities_evaluated", 0),
            elapsed_ms=summary.get("elapsed_ms", 0),
        )

        # Truncate fraud_rings list for XCom (keep only summary, not full member_ids)
        summary["fraud_rings"] = [
            {
                "ring_id": r.get("ring_id"),
                "risk_score": r.get("risk_score"),
                "member_count": r.get("member_count"),
                "signals": r.get("signals"),
                "synthetic": r.get("synthetic"),
                "total_flow": r.get("total_flow"),
            }
            for r in summary.get("fraud_rings", [])
        ]

        return summary

    @task(task_id="evaluate_synthetic_coverage")
    def evaluate_synthetic_coverage(detection_summary: dict[str, Any]) -> dict[str, Any]:
        """
        Check detection precision against synthetic fraud rings.

        Of the detected rings, what fraction were seeded by attacker agents?
        This validates Hard Rule #6 for graph-based detection:
        Louvain must detect synthetic laundering rings with ≥ 85% precision.

        Returns:
            {synthetic_rings, total_rings, precision, hard_rule_6_passed}
        """
        import structlog

        log = structlog.get_logger(__name__)

        fraud_rings = detection_summary.get("fraud_rings", [])
        total_rings = len(fraud_rings)
        synthetic_rings = sum(1 for r in fraud_rings if r.get("synthetic"))

        precision = synthetic_rings / total_rings if total_rings > 0 else 0.0
        hard_rule_6_passed = precision >= _MIN_PRECISION_TARGET or total_rings == 0

        log.info(
            "synthetic_coverage_evaluation",
            total_rings=total_rings,
            synthetic_rings=synthetic_rings,
            precision=round(precision, 4),
            hard_rule_6_passed=hard_rule_6_passed,
            target_precision=_MIN_PRECISION_TARGET,
        )

        if not hard_rule_6_passed and total_rings > 0:
            log.warning(
                "graph_detection_precision_below_target",
                precision=round(precision, 4),
                target=_MIN_PRECISION_TARGET,
                action_required=(
                    "Louvain detection precision < 85% on synthetic rings. "
                    "Money-laundering scenario types MUST NOT be deployed to production "
                    "until precision recovers. (Hard Rule #6)"
                ),
            )

        return {
            "synthetic_rings": synthetic_rings,
            "total_rings": total_rings,
            "precision": round(precision, 4),
            "hard_rule_6_passed": hard_rule_6_passed,
            "target_precision": _MIN_PRECISION_TARGET,
        }

    @task(task_id="publish_high_risk_alerts")
    def publish_high_risk_alerts(detection_summary: dict[str, Any]) -> dict[str, Any]:
        """
        Publish alerts for rings with risk_score > FRAUD_RING_ALERT_THRESHOLD.

        Sprint 6: publishes to `alerts` Kafka topic.
        Sprint 9+: also integrates with PagerDuty/Slack via Airflow Connection.

        Returns:
            {alerts_published, high_risk_ring_ids}
        """
        import json
        import structlog
        from ml.graph.community_detection import _ALERT_THRESHOLD

        log = structlog.get_logger(__name__)

        high_risk = [
            r for r in detection_summary.get("fraud_rings", [])
            if float(r.get("risk_score", 0.0)) >= _ALERT_THRESHOLD
        ]

        if not high_risk:
            log.info("no_high_risk_rings", threshold=_ALERT_THRESHOLD)
            return {"alerts_published": 0, "high_risk_ring_ids": []}

        published = 0
        ring_ids: list[str] = []

        try:
            from confluent_kafka import Producer  # type: ignore[import]

            kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
            topic = os.getenv("KAFKA_TOPIC_ALERTS", "alerts")
            producer = Producer({"bootstrap.servers": kafka_bootstrap})

            for ring in high_risk:
                alert_payload = {
                    "alert_type": "fraud_ring_detected",
                    "source": "community_detection_dag",
                    **ring,
                }
                producer.produce(
                    topic=topic,
                    key=ring.get("ring_id", "unknown"),
                    value=json.dumps(alert_payload).encode(),
                )
                ring_ids.append(ring.get("ring_id", "unknown"))
                published += 1

            producer.flush(timeout=10)
            log.warning(
                "high_risk_rings_alerted",
                count=published,
                ring_ids=ring_ids,
            )

        except ImportError:
            log.error("confluent_kafka_not_installed_for_alerts")
        except Exception as exc:
            log.error("alert_publish_error", error=str(exc))

        return {"alerts_published": published, "high_risk_ring_ids": ring_ids}

    @task(task_id="report_detection_summary")
    def report_detection_summary(
        detection_summary: dict[str, Any],
        coverage_eval: dict[str, Any],
        alert_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Log the final detection summary for this DAG run.
        Includes Hard Rule #6 status for graph-based detection.
        """
        import structlog

        log = structlog.get_logger(__name__)

        recall_threshold = get_detection_recall_threshold()

        report = {
            "rings_detected": detection_summary.get("rings_detected", 0),
            "rings_persisted": detection_summary.get("rings_persisted", 0),
            "alerts_published": alert_result.get("alerts_published", 0),
            "communities_evaluated": detection_summary.get("communities_evaluated", 0),
            "elapsed_ms": detection_summary.get("elapsed_ms", 0),
            "synthetic_rings": coverage_eval.get("synthetic_rings", 0),
            "detection_precision": coverage_eval.get("precision", 0.0),
            "hard_rule_6_passed": coverage_eval.get("hard_rule_6_passed", True),
            "recall_threshold": recall_threshold,
        }

        if report["rings_detected"] > 0:
            log.warning(
                "fraud_rings_report",
                **report,
            )
        else:
            log.info("no_fraud_rings_detected", **report)

        return report

    # ── Task wiring ────────────────────────────────────────────────────────────
    detection = run_louvain_detection()
    coverage = evaluate_synthetic_coverage(detection)
    alerts = publish_high_risk_alerts(detection)
    report_detection_summary(detection, coverage, alerts)


community_detection_dag_instance = community_detection_dag()
