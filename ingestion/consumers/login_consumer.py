"""
Login event consumer.

Consumes from KAFKA_TOPIC_LOGINS, validates each event against the
LoginEvent Avro schema and Pydantic model. Failed login events are
escalated to the detection layer for credential stuffing analysis.

Malformed events are routed to the dead-letter topic.
"""

import os
from typing import Any

import structlog

from ingestion.consumers.base_consumer import BaseConsumer
from ingestion.schemas.models import LoginEvent
from ingestion.schemas.registry import deserialize, load_schema

logger = structlog.get_logger(__name__)

_SCHEMA = load_schema("login_event")


class LoginConsumer(BaseConsumer):
    """Consumes and validates login events from Kafka."""

    def __init__(self) -> None:
        topic = os.getenv("KAFKA_TOPIC_LOGINS", "logins")
        super().__init__(topic=topic)

    def deserialize(self, raw: bytes) -> dict[str, Any]:
        return deserialize(raw, _SCHEMA)

    def process(self, event: dict[str, Any]) -> None:
        validated = LoginEvent(**event)
        log = logger.bind(
            session_id=validated.session_id,
            account_id=validated.account_id,
            success=validated.success,
            country=validated.geo.country,
            synthetic=validated.is_synthetic,
        )

        if validated.is_synthetic:
            log.info("synthetic_login_received")
        elif not validated.success:
            log.info(
                "failed_login_received",
                failure_reason=validated.failure_reason,
            )
        else:
            log.info("login_received")

        self._emit_for_processing(validated)

    def _emit_for_processing(self, event: LoginEvent) -> None:
        """
        Forward the validated event to the detection pipeline.
        Wired to graph ingestion (Neo4j LOGGED_IN_FROM) in Sprint 6.
        """
        logger.debug(
            "login_queued_for_processing",
            session_id=event.session_id,
            success=event.success,
        )
