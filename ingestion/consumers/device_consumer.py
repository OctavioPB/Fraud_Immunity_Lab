"""
Device event consumer.

Consumes from KAFKA_TOPIC_DEVICES, validates each event against the
DeviceEvent Avro schema and Pydantic model. fingerprint_changed events
are flagged as high-priority signals for account takeover detection.

Malformed events are routed to the dead-letter topic.
"""

import os
from typing import Any

import structlog

from ingestion.consumers.base_consumer import BaseConsumer
from ingestion.schemas.models import DeviceEvent
from ingestion.schemas.registry import deserialize, load_schema

logger = structlog.get_logger(__name__)

_SCHEMA = load_schema("device_event")

_HIGH_RISK_EVENT_TYPES = {"fingerprint_changed", "removed"}


class DeviceConsumer(BaseConsumer):
    """Consumes and validates device events from Kafka."""

    def __init__(self) -> None:
        topic = os.getenv("KAFKA_TOPIC_DEVICES", "devices")
        super().__init__(topic=topic)

    def deserialize(self, raw: bytes) -> dict[str, Any]:
        return deserialize(raw, _SCHEMA)

    def process(self, event: dict[str, Any]) -> None:
        validated = DeviceEvent(**event)
        log = logger.bind(
            device_id=validated.device_id,
            account_id=validated.account_id,
            event_type=validated.event_type,
            os=validated.os,
            synthetic=validated.is_synthetic,
        )

        if validated.event_type in _HIGH_RISK_EVENT_TYPES:
            log.warning(
                "high_risk_device_event",
                fingerprint=validated.fingerprint,
            )
        elif validated.is_synthetic:
            log.info("synthetic_device_event_received")
        else:
            log.info("device_event_received")

        self._emit_for_processing(validated)

    def _emit_for_processing(self, event: DeviceEvent) -> None:
        """
        Forward to graph ingestion pipeline.
        Wired to Neo4j (Account)-[:USED_DEVICE]->(Device) in Sprint 6.
        """
        logger.debug(
            "device_event_queued_for_processing",
            device_id=event.device_id,
            event_type=event.event_type,
        )
