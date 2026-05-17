"""
Prometheus-compatible /metrics endpoint.

Exposes all metrics from `api.observability` including:
  - fil_detection_latency_seconds{tenant_id}: drift detection latency histogram
  - fil_score_computation_seconds{tenant_id}: immunity score computation time
  - fil_llm_cost_usd_total{tenant_id, model}: cumulative LLM spend
  - fil_llm_tokens_total{tenant_id, model, token_type}: token usage
  - fil_llm_budget_fraction{tenant_id}: spend / budget ratio
  - fil_consumer_lag_messages{topic, partition}: Kafka lag
  - fil_consumer_lag_alert{topic}: 1 when lag > threshold
  - fil_events_processed_total{topic}: events processed
  - fil_rate_limit_exceeded_total{tenant_id, bucket}: rate-limited requests
"""

import os
import time

import structlog
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.observability import (
    CONSUMER_LAG,
    CONSUMER_LAG_ALERT,
    LLM_BUDGET_FRACTION,
    SCRAPE_TIMESTAMP,
    registry,
)
from api.services.cost_tracker import CostTracker
from api.services.tenant_provisioner import TenantProvisioner

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["infra"])

_LAG_ALERT_THRESHOLD = int(os.getenv("CONSUMER_LAG_ALERT_THRESHOLD", "1000"))
_cost_tracker = CostTracker()
_provisioner = TenantProvisioner()


def _get_consumer_lag() -> dict[str, dict[str, int]]:
    """
    Query the Kafka broker for consumer group lag per topic-partition.
    Returns {topic: {partition_str: lag}}.
    Gracefully returns empty dict when Kafka is unreachable.
    """
    try:
        from confluent_kafka import Consumer, TopicPartition  # type: ignore[import]
        from confluent_kafka.admin import AdminClient  # type: ignore[import]

        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        group_id = os.getenv("KAFKA_CONSUMER_GROUP", "fraud-immunity-group")

        watched_topics = [
            os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions"),
            os.getenv("KAFKA_TOPIC_LOGINS", "logins"),
            os.getenv("KAFKA_TOPIC_DEVICES", "devices"),
        ]

        admin = AdminClient({"bootstrap.servers": bootstrap})
        meta = admin.list_topics(timeout=5)

        partitions_by_topic: dict[str, list[TopicPartition]] = {}
        for topic in watched_topics:
            if topic in meta.topics:
                partitions_by_topic[topic] = [
                    TopicPartition(topic, p)
                    for p in meta.topics[topic].partitions
                ]

        if not partitions_by_topic:
            return {}

        all_partitions = [p for parts in partitions_by_topic.values() for p in parts]

        tmp = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": f"{group_id}-metrics-probe",
                "auto.offset.reset": "latest",
            }
        )
        high_watermarks: dict[tuple[str, int], int] = {}
        for tp in all_partitions:
            _, high = tmp.get_watermark_offsets(tp, timeout=5)
            high_watermarks[(tp.topic, tp.partition)] = high
        tmp.close()

        committed_consumer = Consumer(
            {"bootstrap.servers": bootstrap, "group.id": group_id}
        )
        committed_tps = committed_consumer.committed(all_partitions, timeout=5)
        committed_consumer.close()

        committed_offsets: dict[tuple[str, int], int] = {
            (tp.topic, tp.partition): (tp.offset if tp.offset >= 0 else 0)
            for tp in committed_tps
        }

        result: dict[str, dict[str, int]] = {t: {} for t in watched_topics}
        for (topic, partition), high in high_watermarks.items():
            committed = committed_offsets.get((topic, partition), 0)
            result[topic][str(partition)] = max(0, high - committed)

        return result

    except Exception as exc:
        logger.warning("consumer_lag_fetch_failed", error=str(exc))
        return {}


def _refresh_budget_metrics() -> None:
    """Update fil_llm_budget_fraction for all active tenants."""
    try:
        tenants = _provisioner.list_tenants()
        for tenant in tenants:
            if not tenant.get("active"):
                continue
            tenant_id = tenant["tenant_id"]
            budget = float(tenant.get("monthly_llm_budget_usd", 0))
            if budget <= 0:
                continue
            spend = _cost_tracker.get_monthly_spend(tenant_id)
            LLM_BUDGET_FRACTION.labels(tenant_id=tenant_id).set(
                round(spend / budget, 4)
            )
    except Exception as exc:
        logger.warning("budget_metrics_refresh_failed", error=str(exc))


@router.get("/metrics")
async def metrics() -> Response:
    """
    Prometheus scrape endpoint — returns all metrics in text exposition format.
    Safe to call even when Kafka or PostgreSQL are temporarily unreachable.
    """
    SCRAPE_TIMESTAMP.set(time.time())

    watched_topics = [
        os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions"),
        os.getenv("KAFKA_TOPIC_LOGINS", "logins"),
        os.getenv("KAFKA_TOPIC_DEVICES", "devices"),
    ]

    lag_data = _get_consumer_lag()
    for topic in watched_topics:
        topic_partitions = lag_data.get(topic, {"0": 0})
        total_lag = sum(topic_partitions.values())

        for partition, lag in topic_partitions.items():
            CONSUMER_LAG.labels(topic=topic, partition=partition).set(lag)

        alert_state = 1 if total_lag > _LAG_ALERT_THRESHOLD else 0
        CONSUMER_LAG_ALERT.labels(topic=topic).set(alert_state)

        if alert_state:
            logger.warning(
                "consumer_lag_threshold_exceeded",
                topic=topic,
                total_lag=total_lag,
                threshold=_LAG_ALERT_THRESHOLD,
            )

    _refresh_budget_metrics()

    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
