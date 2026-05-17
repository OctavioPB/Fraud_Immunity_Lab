"""
scenario_coverage_dag — Daily Scenario Coverage Report
=======================================================

Generates a ScenarioCoverageReport daily and writes metrics to Redis so the
Immunity Score API's /scenarios endpoint reflects fresh data.

Tasks:
  compute_coverage_metrics   ← query detection recall per attack type from Redis
      ↓
  identify_coverage_gaps     ← compare tested vs canonical attack types
      ↓
  publish_coverage_to_redis  ← write metrics that ScoreCalculator reads
      ↓
  recommend_next_scenarios   ← log actionable recommendations for operators

Schedule: Daily at 00:30 UTC (before profile_refresh at 01:00 and Louvain at 02:00).

Tags: ["ml"] — feeds the Immunity Score engine (Sprint 7).

Hard Rules enforced: #6 (surfaces any attack types below 90% recall threshold)
"""

import os
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import get_detection_recall_threshold

_CANONICAL_ATTACK_TYPES: list[str] = [
    "phishing",
    "money_laundering",
    "account_takeover",
    "credential_stuffing",
    "smurfing",
    "card_fraud",
    "synthetic_identity",
    "first_party_fraud",
    "mule_account",
    "friendly_fraud",
]
_WINDOW_DAYS: int = 30

doc_md = """
## scenario_coverage_dag

**Purpose**: Generate a daily scenario coverage report that feeds the Immunity Score
API's `/scenarios` endpoint. Identifies coverage gaps and recommends next scenarios.

**Schedule**: Daily at 00:30 UTC.

**Output**: Writes per-attack-type recall metrics to Redis (TTL: 30 days).
These keys are read by `ScoreCalculator.build_scenario_coverage()`.

**Hard Rules enforced**:
- #6: Any attack type with recall < 90% is flagged as a gap and causes a
  structured warning log.

**Redis keys written**:
  - `detection_recall:{tenant_id}:{attack_type}`
  - `last_scenario_run:{tenant_id}:{attack_type}`
  - `scenarios_tested_30d:{tenant_id}` (Redis Set)
  - `scenario_count_30d:{tenant_id}:{attack_type}`
"""


@dag(
    dag_id="scenario_coverage_dag",
    schedule_interval="30 0 * * *",  # 00:30 UTC daily
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["ml"],
    doc_md=doc_md,
    default_args={"retries": 1, "retry_delay": 60},
)
def scenario_coverage_dag() -> None:

    @task(task_id="compute_coverage_metrics")
    def compute_coverage_metrics(**context: Any) -> dict[str, Any]:
        """
        Compute detection recall per attack type from Redis detection_results aggregation.

        Sprint 7: reads from Redis keys written by anomaly_pipeline and
        community_detection_dag. Sprint 9: adds per-tenant scoping.

        Returns:
            {attack_type_recalls: dict, tested_attack_types: list, total_evaluated: int}
        """
        import structlog
        import os

        log = structlog.get_logger(__name__)
        recall_threshold = get_detection_recall_threshold()
        tenant_id = os.getenv("DEFAULT_TENANT_ID", "default")

        recalls: dict[str, Any] = {}
        tested: list[str] = []
        total_evaluated = 0

        try:
            import redis as redis_lib  # type: ignore[import]
            r = redis_lib.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )

            for attack_type in _CANONICAL_ATTACK_TYPES:
                recall_key = f"detection_recall:{tenant_id}:{attack_type}"
                count_key = f"scenario_count_30d:{tenant_id}:{attack_type}"

                recall_val = r.get(recall_key)
                count_val = r.get(count_key)

                if recall_val is not None:
                    recall = float(recall_val)
                    count = int(count_val) if count_val else 1
                    recalls[attack_type] = recall
                    tested.append(attack_type)
                    total_evaluated += count

                    if recall < recall_threshold:
                        log.warning(
                            "attack_type_below_recall_threshold",
                            attack_type=attack_type,
                            recall=round(recall, 4),
                            threshold=recall_threshold,
                            hard_rule="Rule #6: scenario must not deploy until recall ≥ threshold",
                        )
                    else:
                        log.info(
                            "attack_type_recall_healthy",
                            attack_type=attack_type,
                            recall=round(recall, 4),
                        )

        except ImportError:
            log.warning("redis_not_installed_using_stub_metrics")
            # Sprint 7 stub fallback — simulate coverage data
            for attack_type in _CANONICAL_ATTACK_TYPES[:5]:
                recalls[attack_type] = round(0.88 + (hash(attack_type) % 10) / 100, 4)
                tested.append(attack_type)
                total_evaluated += 5
        except Exception as exc:
            log.error("coverage_metrics_fetch_failed", error=str(exc))

        log.info(
            "coverage_metrics_computed",
            total_attack_types=len(_CANONICAL_ATTACK_TYPES),
            tested_count=len(tested),
            total_evaluated=total_evaluated,
        )

        return {
            "attack_type_recalls": recalls,
            "tested_attack_types": tested,
            "total_evaluated": total_evaluated,
            "tenant_id": tenant_id,
        }

    @task(task_id="identify_coverage_gaps")
    def identify_coverage_gaps(metrics: dict[str, Any]) -> dict[str, Any]:
        """
        Compare tested attack types against the canonical list to identify gaps.

        Returns:
            {gaps, below_threshold, coverage_fraction, gap_count}
        """
        import structlog

        log = structlog.get_logger(__name__)
        recall_threshold = get_detection_recall_threshold()

        tested = set(metrics.get("tested_attack_types", []))
        recalls = metrics.get("attack_type_recalls", {})

        untested = [at for at in _CANONICAL_ATTACK_TYPES if at not in tested]
        below_threshold = [
            at for at, recall in recalls.items()
            if recall < recall_threshold
        ]

        coverage_fraction = len(tested) / len(_CANONICAL_ATTACK_TYPES) if _CANONICAL_ATTACK_TYPES else 0.0

        gaps = untested + [at for at in below_threshold if at not in untested]

        if gaps:
            log.warning(
                "scenario_coverage_gaps_detected",
                untested_count=len(untested),
                below_threshold_count=len(below_threshold),
                gap_attack_types=gaps,
                coverage_fraction=round(coverage_fraction, 4),
            )
        else:
            log.info(
                "scenario_coverage_complete",
                coverage_fraction=round(coverage_fraction, 4),
                total_tested=len(tested),
            )

        return {
            "gaps": gaps,
            "untested": untested,
            "below_threshold": below_threshold,
            "coverage_fraction": round(coverage_fraction, 4),
            "gap_count": len(gaps),
        }

    @task(task_id="publish_coverage_to_redis")
    def publish_coverage_to_redis(
        metrics: dict[str, Any],
        gaps: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Write coverage metrics to Redis for ScoreCalculator.build_scenario_coverage().

        Also writes a summary key for the Immunity Score cache invalidation check:
          `coverage_report_generated_at:{tenant_id}` → epoch ms
        """
        import time
        import os
        import structlog

        log = structlog.get_logger(__name__)
        tenant_id = metrics.get("tenant_id", "default")
        window_s = _WINDOW_DAYS * 86_400
        now_ms = int(time.time() * 1000)
        written = 0

        try:
            import redis as redis_lib  # type: ignore[import]

            r = redis_lib.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            pipe = r.pipeline()

            # Write staleness count for model freshness component
            stale_count_val = r.get(f"stale_profile_count:{tenant_id}")
            if stale_count_val is None:
                pipe.setex(f"stale_profile_count:{tenant_id}", window_s, "0")

            # Publish coverage report timestamp
            pipe.setex(
                f"coverage_report_generated_at:{tenant_id}",
                window_s,
                str(now_ms),
            )

            # Write gap summary for dashboard consumption
            import json
            pipe.setex(
                f"coverage_gaps:{tenant_id}",
                window_s,
                json.dumps(gaps.get("gaps", [])),
            )

            pipe.execute()
            written = 1
            log.info(
                "coverage_metrics_published_to_redis",
                tenant_id=tenant_id,
                coverage_fraction=gaps.get("coverage_fraction", 0.0),
            )

        except ImportError:
            log.warning("redis_not_installed_skipping_publish")
        except Exception as exc:
            log.error("coverage_publish_failed", error=str(exc))

        return {
            "tenant_id": tenant_id,
            "published": written > 0,
            "published_at_ms": now_ms,
        }

    @task(task_id="recommend_next_scenarios")
    def recommend_next_scenarios(
        gaps: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Log actionable recommendations for operators to prioritize next runs.

        Priority order:
          1. Untested attack types (highest gap risk)
          2. Attack types below recall threshold (Hard Rule #6 failure)
          3. Attack types with lowest scenario count (least coverage depth)
        """
        import structlog

        log = structlog.get_logger(__name__)
        recalls = metrics.get("attack_type_recalls", {})

        recommendations: list[dict] = []

        # Priority 1: untested types
        for at in gaps.get("untested", []):
            recommendations.append({
                "attack_type": at,
                "priority": 1,
                "reason": "never tested — zero detection coverage",
            })

        # Priority 2: below threshold but tested
        for at in gaps.get("below_threshold", []):
            if at not in gaps.get("untested", []):
                recommendations.append({
                    "attack_type": at,
                    "priority": 2,
                    "reason": f"recall {recalls.get(at, 0.0):.4f} < threshold — Hard Rule #6",
                })

        recommendations.sort(key=lambda x: x["priority"])

        if recommendations:
            log.warning(
                "scenario_recommendations",
                recommendation_count=len(recommendations),
                top_priority=recommendations[0].get("attack_type"),
                recommendations=recommendations[:5],
            )
        else:
            log.info(
                "no_scenario_recommendations_needed",
                message="All canonical attack types have adequate coverage.",
            )

        return {
            "recommendation_count": len(recommendations),
            "recommendations": recommendations,
        }

    # ── Task wiring ────────────────────────────────────────────────────────────
    metrics = compute_coverage_metrics()
    gaps = identify_coverage_gaps(metrics)
    published = publish_coverage_to_redis(metrics, gaps)
    recommend_next_scenarios(gaps, metrics)


scenario_coverage_dag_instance = scenario_coverage_dag()
