"""
Audit producer — appends immutable records to the synthetic_audit Kafka topic.

Hard Rule #7: the synthetic_audit topic is append-only. This module ONLY
produces to that topic; it never reads, seeks, or modifies existing records.

Every scenario generation call must produce one audit record BEFORE any
downstream injection occurs, so that the audit trail captures all attempts
including those that ultimately fail validation.
"""

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_AUDIT_TOPIC = "synthetic_audit"


@dataclass
class AuditRecord:
    """Immutable record of one attacker agent call. (Hard Rule #7)"""

    audit_id: str
    scenario_id: str
    attack_type: str
    agent_class: str
    agent_version: str
    generated_at_ms: int
    injected_at_ms: int | None
    dry_run: bool
    cost_usd: float
    validation_passed: bool
    pii_detected: bool
    dag_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditProducer:
    """
    Kafka producer scoped exclusively to synthetic_audit.
    Append-only — no delete, no seek, no offset manipulation.
    """

    def __init__(self) -> None:
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self._dry_run = os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").lower() == "true"
        self._topic = _AUDIT_TOPIC
        self._producer = None

        if not self._dry_run:
            try:
                from confluent_kafka import Producer

                self._producer = Producer(
                    {
                        "bootstrap.servers": bootstrap,
                        "enable.idempotence": True,
                        "acks": "all",
                        "retries": 10,
                        "delivery.timeout.ms": 60000,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "audit_producer_init_failed",
                    error=str(exc),
                    note="Audit records will be logged only",
                )

    def append(self, record: AuditRecord) -> None:
        """
        Append one audit record to synthetic_audit.
        Falls back to structured log if Kafka is unavailable — the audit trail
        must never be lost, even in dev environments without Kafka.
        """
        payload = json.dumps(record.to_dict()).encode()
        logger.info("audit_record", **record.to_dict())

        if self._dry_run or self._producer is None:
            return

        try:
            self._producer.produce(
                self._topic,
                value=payload,
                key=record.scenario_id.encode(),
            )
            self._producer.poll(0)
        except Exception as exc:
            # Log but never raise — a Kafka hiccup must not abort a DAG run.
            # The structured log above already preserves the record.
            logger.error(
                "audit_kafka_produce_failed",
                scenario_id=record.scenario_id,
                error=str(exc),
            )

    def flush(self) -> None:
        if self._producer is not None:
            self._producer.flush(timeout=10)


def make_audit_record(
    *,
    scenario_id: str,
    attack_type: str,
    agent_class: str,
    agent_version: str,
    cost_usd: float,
    validation_passed: bool,
    pii_detected: bool,
    injected_at_ms: int | None = None,
    dag_run_id: str | None = None,
) -> AuditRecord:
    """Factory that generates a fully-populated AuditRecord."""
    return AuditRecord(
        audit_id=str(uuid.uuid4()),
        scenario_id=scenario_id,
        attack_type=attack_type,
        agent_class=agent_class,
        agent_version=agent_version,
        generated_at_ms=int(time.time() * 1000),
        injected_at_ms=injected_at_ms,
        dry_run=os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").lower() == "true",
        cost_usd=cost_usd,
        validation_passed=validation_passed,
        pii_detected=pii_detected,
        dag_run_id=dag_run_id,
    )
