"""
Prometheus-compatible /metrics endpoint.

Exposes:
  - fil_consumer_lag_messages{topic, partition}: lag per topic-partition
  - fil_events_processed_total{topic}: cumulative events processed
  - fil_dlq_events_total{topic}: cumulative DLQ events
  - fil_consumer_lag_alert{topic}: 1 when lag > threshold

Alert threshold: configured via CONSUMER_LAG_ALERT_THRESHOLD (default 1000).
"""

import os
import time

import structlog
from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["infra"])

_LAG_ALERT_THRESHOLD = int(os.getenv("CONSUMER_LAG_ALERT_THRESHOLD", "1000"))

# ── Metrics registry ─────────────────────────────────────────────────────────

_registry = CollectorRegistry()

EVENTS_PROCESSED = Counter(
    "fil_events_processed_total",
    "Total events successfully processed per topic",
    ["topic"],
    registry=_registry,
)

DLQ_EVENTS = Counter(
    "fil_dlq_events_total",
    "Total events routed to dead-letter topic",
    ["topic"],
    registry=_registry,
)

CONSUMER_LAG = Gauge(
    "fil_consumer_lag_messages",
    "Consumer lag in messages per topic-partition",
    ["topic", "partition"],
    registry=_registry,
)

CONSUMER_LAG_ALERT = Gauge(
    "fil_consumer_lag_alert",
    "1 if consumer lag exceeds alert threshold, 0 otherwise",
    ["topic"],
    registry=_registry,
)

SCRAPE_TIMESTAMP = Gauge(
    "fil_metrics_last_scrape_timestamp_seconds",
    "Unix timestamp of the last successful metrics scrape",
    registry=_registry,
)


def _get_consumer_lag() -> dict[str, dict[str, int]]:
    """
    Query the Kafka broker for consumer group lag per topic-partition.
    Returns {topic: {partition_str: lag}}.
    Returns an empty dict (not an error) if Kafka is unreachable —
    the metrics endpoint must not fail just because Kafka is down.
    """
    try:
        from confluent_kafka import Consumer, TopicPartition
        from confluent_kafka.admin import AdminClient

        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        group_id = os.getenv("KAFKA_CONSUMER_GROUP", "fraud-immunity-group")

        watched_topics = [
            os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions"),
            os.getenv("KAFKA_TOPIC_LOGINS", "logins"),
            os.getenv("KAFKA_TOPIC_DEVICES", "devices"),
        ]

        admin = AdminClient({"bootstrap.servers": bootstrap})

        # 1. Get partition metadata for each topic
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

        # 2. Get high watermarks via a temporary consumer
        tmp = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": f"{group_id}-metrics-probe",
                "auto.offset.reset": "latest",
            }
        )
        all_partitions = [p for parts in partitions_by_topic.values() for p in parts]
        high_watermarks: dict[tuple[str, int], int] = {}
        for tp in all_partitions:
            _, high = tmp.get_watermark_offsets(tp, timeout=5)
            high_watermarks[(tp.topic, tp.partition)] = high
        tmp.close()

        # 3. Get committed consumer group offsets
        committed_consumer = Consumer(
            {"bootstrap.servers": bootstrap, "group.id": group_id}
        )
        committed_tps = committed_consumer.committed(all_partitions, timeout=5)
        committed_consumer.close()

        committed_offsets: dict[tuple[str, int], int] = {}
        for tp in committed_tps:
            committed_offsets[(tp.topic, tp.partition)] = (
                tp.offset if tp.offset >= 0 else 0
            )

        # 4. Compute lag
        result: dict[str, dict[str, int]] = {t: {} for t in watched_topics}
        for (topic, partition), high in high_watermarks.items():
            committed = committed_offsets.get((topic, partition), 0)
            lag = max(0, high - committed)
            result[topic][str(partition)] = lag

        return result

    except Exception as exc:
        logger.warning("consumer_lag_fetch_failed", error=str(exc))
        return {}


@router.get("/metrics")
async def metrics() -> Response:
    """
    Prometheus scrape endpoint — returns metrics in text exposition format.
    Safe to call even when Kafka is temporarily unreachable.
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

    return Response(content=generate_latest(_registry), media_type=CONTENT_TYPE_LATEST)
