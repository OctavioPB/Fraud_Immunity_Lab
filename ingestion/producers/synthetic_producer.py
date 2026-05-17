"""
Synthetic event producer — generates realistic fake events for load testing
and red-team injection into the Kafka ingestion pipeline.

Hard Rule #3: every event produced here MUST carry synthetic=true in metadata.
Hard Rule (env flag): respects SYNTHETIC_INJECTION_DRY_RUN — logs instead of
publishing when set to 'true'.
"""

import hashlib
import os
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from confluent_kafka import Producer

from ingestion.schemas.registry import SchemaRegistry, load_schema, serialize

logger = structlog.get_logger(__name__)

# ── Schemas (loaded once at module level) ────────────────────────────────────
_TX_SCHEMA = load_schema("transaction_event")
_LOGIN_SCHEMA = load_schema("login_event")
_DEVICE_SCHEMA = load_schema("device_event")

# ── Synthetic tag — Hard Rule #3 ─────────────────────────────────────────────
_SYNTHETIC_METADATA: dict[str, str] = {
    "synthetic": "true",
    "origin": "red_team",
}

# ── Reference data for realistic generation ───────────────────────────────────
_CURRENCIES = ["USD", "EUR", "MXN", "GBP", "BRL", "CAD"]
_CHANNELS = ["card_present", "card_not_present", "ach", "wire", "p2p", "atm"]
_OS_LIST = ["iOS 17.2", "Android 14", "Windows 11", "macOS 14", "Android 13"]
_COUNTRIES = ["US", "MX", "GB", "DE", "BR", "CA", "FR"]
_DEVICE_EVENT_TYPES = ["registered", "seen", "fingerprint_changed", "removed"]
_FAIL_REASONS = ["bad_password", "mfa_failed", "account_locked", "ip_blocked"]


@dataclass
class ProducerStats:
    produced: int = 0
    skipped_dry_run: int = 0
    errors: int = 0


class SyntheticProducer:
    """
    Generates and publishes synthetic Kafka events for all three topics.

    Usage:
        producer = SyntheticProducer()
        producer.produce_transaction_burst(count=1000)
    """

    def __init__(self) -> None:
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self._dry_run = os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").lower() == "true"

        self._tx_topic = os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions")
        self._login_topic = os.getenv("KAFKA_TOPIC_LOGINS", "logins")
        self._device_topic = os.getenv("KAFKA_TOPIC_DEVICES", "devices")

        self._registry = SchemaRegistry()
        self._stats = ProducerStats()

        if not self._dry_run:
            self._producer = Producer(
                {
                    "bootstrap.servers": bootstrap,
                    "enable.idempotence": True,
                    "acks": "all",
                    "retries": 5,
                    "delivery.timeout.ms": 30000,
                }
            )
            self._tx_schema_id = self._registry.register(
                "transactions-value", _TX_SCHEMA
            )
            self._login_schema_id = self._registry.register(
                "logins-value", _LOGIN_SCHEMA
            )
            self._device_schema_id = self._registry.register(
                "devices-value", _DEVICE_SCHEMA
            )
        else:
            logger.info("synthetic_producer_dry_run_mode")

    # ── Event builders ────────────────────────────────────────────────────────

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _new_account_id() -> str:
        return str(uuid.uuid4())

    def build_transaction(
        self,
        account_id: str | None = None,
        amount: float | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        metadata = {**_SYNTHETIC_METADATA, **(extra_metadata or {})}
        return {
            "transaction_id": str(uuid.uuid4()),
            "account_id": account_id or self._new_account_id(),
            "amount": amount or round(random.uniform(1.00, 9999.99), 2),
            "currency": random.choice(_CURRENCIES),
            "merchant_id": str(uuid.uuid4()),
            "timestamp": self._now_ms(),
            "channel": random.choice(_CHANNELS),
            "metadata": metadata,
        }

    def build_login(
        self,
        account_id: str | None = None,
        success: bool | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        is_success = success if success is not None else random.random() > 0.15
        country = random.choice(_COUNTRIES)
        metadata = {**_SYNTHETIC_METADATA, **(extra_metadata or {})}
        return {
            "session_id": str(uuid.uuid4()),
            "account_id": account_id or self._new_account_id(),
            "ip_address": hashlib.sha256(
                f"{random.randint(1, 255)}.{random.randint(0,255)}".encode()
            ).hexdigest()[:16],
            "user_agent": (
                "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            "geo": {
                "country": country,
                "city": f"City-{random.randint(1, 100)}",
                "lat": round(random.uniform(-60, 70), 2),
                "lon": round(random.uniform(-180, 180), 2),
            },
            "timestamp": self._now_ms(),
            "success": is_success,
            "failure_reason": None if is_success else random.choice(_FAIL_REASONS),
            "metadata": metadata,
        }

    def build_device(
        self,
        account_id: str | None = None,
        event_type: str | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(
            str(uuid.uuid4()).encode()
        ).hexdigest()
        metadata = {**_SYNTHETIC_METADATA, **(extra_metadata or {})}
        return {
            "device_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, fingerprint)),
            "account_id": account_id or self._new_account_id(),
            "fingerprint": fingerprint,
            "os": random.choice(_OS_LIST),
            "app_version": f"{random.randint(1,5)}.{random.randint(0,9)}.{random.randint(0,9)}",
            "event_type": event_type or random.choice(_DEVICE_EVENT_TYPES),
            "timestamp": self._now_ms(),
            "metadata": metadata,
        }

    # ── Publishing ────────────────────────────────────────────────────────────

    def _publish(self, topic: str, record: dict[str, Any], schema: Any, schema_id: int) -> None:
        if self._dry_run:
            logger.info(
                "dry_run_skipped",
                topic=topic,
                record_keys=list(record.keys()),
                synthetic=record.get("metadata", {}).get("synthetic"),
            )
            self._stats.skipped_dry_run += 1
            return

        try:
            payload = serialize(record, schema, schema_id)
            self._producer.produce(
                topic,
                value=payload,
                key=record.get("account_id", "").encode(),
            )
            self._stats.produced += 1
        except Exception as exc:
            logger.error("produce_failed", topic=topic, error=str(exc))
            self._stats.errors += 1

    def produce_transaction(
        self,
        account_id: str | None = None,
        amount: float | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        record = self.build_transaction(account_id, amount, extra_metadata)
        self._publish(self._tx_topic, record, _TX_SCHEMA, getattr(self, "_tx_schema_id", 0))
        return record

    def produce_login(
        self,
        account_id: str | None = None,
        success: bool | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        record = self.build_login(account_id, success, extra_metadata)
        self._publish(self._login_topic, record, _LOGIN_SCHEMA, getattr(self, "_login_schema_id", 0))
        return record

    def produce_device(
        self,
        account_id: str | None = None,
        event_type: str | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        record = self.build_device(account_id, event_type, extra_metadata)
        self._publish(
            self._device_topic, record, _DEVICE_SCHEMA, getattr(self, "_device_schema_id", 0)
        )
        return record

    # ── Burst helpers (load testing) ──────────────────────────────────────────

    def produce_transaction_burst(
        self,
        count: int = 1000,
        account_pool: list[str] | None = None,
    ) -> ProducerStats:
        """Produce `count` synthetic transactions. Uses a shared account pool if provided."""
        accounts = account_pool or [self._new_account_id() for _ in range(max(1, count // 10))]
        for _ in range(count):
            self.produce_transaction(account_id=random.choice(accounts))
        self._flush()
        logger.info("burst_complete", event_type="transaction", count=count, stats=self._stats.__dict__)
        return self._stats

    def produce_mixed_burst(
        self,
        transactions: int = 800,
        logins: int = 150,
        devices: int = 50,
    ) -> ProducerStats:
        """
        Produce a realistic mix of all three event types.
        Proportions approximate real-world traffic ratios.
        """
        accounts = [self._new_account_id() for _ in range(max(1, transactions // 5))]
        for _ in range(transactions):
            self.produce_transaction(account_id=random.choice(accounts))
        for _ in range(logins):
            self.produce_login(account_id=random.choice(accounts))
        for _ in range(devices):
            self.produce_device(account_id=random.choice(accounts))
        self._flush()
        logger.info(
            "mixed_burst_complete",
            transactions=transactions,
            logins=logins,
            devices=devices,
            stats=self._stats.__dict__,
        )
        return self._stats

    def _flush(self) -> None:
        if not self._dry_run:
            self._producer.flush(timeout=30)

    @property
    def stats(self) -> ProducerStats:
        return self._stats
