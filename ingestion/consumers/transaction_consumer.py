"""
Transaction event consumer.

Consumes from KAFKA_TOPIC_TRANSACTIONS, validates each event against the
TransactionEvent Avro schema and Pydantic model, then emits validated events
for downstream ML processing (behavioral drift, anomaly detection).

Malformed or schema-invalid events are routed to the dead-letter topic.
"""

import os
from typing import Any

import structlog

from ingestion.consumers.base_consumer import BaseConsumer
from ingestion.schemas.models import TransactionEvent
from ingestion.schemas.registry import deserialize, load_schema

logger = structlog.get_logger(__name__)

_SCHEMA = load_schema("transaction_event")


class TransactionConsumer(BaseConsumer):
    """Consumes and validates transaction events from Kafka."""

    def __init__(self) -> None:
        topic = os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions")
        super().__init__(topic=topic)

    def deserialize(self, raw: bytes) -> dict[str, Any]:
        return deserialize(raw, _SCHEMA)

    def process(self, event: dict[str, Any]) -> None:
        validated = TransactionEvent(**event)
        log = logger.bind(
            transaction_id=validated.transaction_id,
            account_id=validated.account_id,
            amount=validated.amount,
            currency=validated.currency,
            channel=validated.channel,
            synthetic=validated.is_synthetic,
        )

        if validated.is_synthetic:
            log.info("synthetic_transaction_received")
        else:
            log.info("transaction_received")

        self._emit_for_processing(validated)

    def _emit_for_processing(self, event: TransactionEvent) -> None:
        """
        Forward the validated event to the ML processing pipeline.
        Wired to Celery tasks in Sprint 5 (behavioral drift detection).
        """
        # Placeholder — Sprint 5 connects this to anomaly_pipeline.apply_async()
        logger.debug(
            "transaction_queued_for_processing",
            transaction_id=event.transaction_id,
        )
