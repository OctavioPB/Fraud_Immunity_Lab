"""
Base Kafka consumer with dead-letter topic support, structured logging,
and schema validation. All topic consumers extend this class.
"""

import os
from abc import ABC, abstractmethod
from typing import Any

import structlog
from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

logger = structlog.get_logger(__name__)

_DEAD_LETTER_SUFFIX = ".dead_letter"


class BaseConsumer(ABC):
    """Abstract base for all ingestion consumers."""

    def __init__(self, topic: str, group_id: str | None = None) -> None:
        self.topic = topic
        self._group_id = group_id or os.getenv(
            "KAFKA_CONSUMER_GROUP", "fraud-immunity-group"
        )
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": self._group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        self._dlq_producer = Producer({"bootstrap.servers": bootstrap})
        self._dlq_topic = f"{topic}{_DEAD_LETTER_SUFFIX}"

    @abstractmethod
    def deserialize(self, raw: bytes) -> dict[str, Any]:
        """Deserialize raw Kafka message bytes into a Python dict."""
        ...

    @abstractmethod
    def process(self, event: dict[str, Any]) -> None:
        """Process a validated event. Implement in subclasses."""
        ...

    def _send_to_dlq(self, raw: bytes, error: str) -> None:
        import json

        payload = json.dumps(
            {"raw": raw.decode("utf-8", errors="replace"), "error": error}
        ).encode()
        self._dlq_producer.produce(self._dlq_topic, value=payload)
        self._dlq_producer.flush()
        logger.warning("event_sent_to_dlq", topic=self._dlq_topic, error=error)

    def run(self) -> None:
        """Main consume loop. Runs until interrupted."""
        self._consumer.subscribe([self.topic])
        logger.info("consumer_started", topic=self.topic, group=self._group_id)

        try:
            while True:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise KafkaException(msg.error())

                raw = msg.value()
                try:
                    event = self.deserialize(raw)
                    self.process(event)
                    self._consumer.commit(message=msg, asynchronous=False)
                except Exception as exc:
                    logger.error(
                        "event_processing_failed",
                        topic=self.topic,
                        error=str(exc),
                    )
                    self._send_to_dlq(raw, str(exc))
                    self._consumer.commit(message=msg, asynchronous=False)
        finally:
            self._consumer.close()
            logger.info("consumer_stopped", topic=self.topic)
