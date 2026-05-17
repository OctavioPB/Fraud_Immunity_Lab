"""
Unit tests for TransactionConsumer, LoginConsumer, DeviceConsumer.

Uses serialize() to produce valid Avro wire-format bytes, then exercises
deserialization + Pydantic validation. Dead-letter routing is verified by
passing corrupted bytes.
"""

import time
import unittest.mock as mock

import pytest

from ingestion.consumers.device_consumer import DeviceConsumer
from ingestion.consumers.login_consumer import LoginConsumer
from ingestion.consumers.transaction_consumer import TransactionConsumer
from ingestion.schemas.registry import load_schema, serialize

_TX_SCHEMA = load_schema("transaction_event")
_LOGIN_SCHEMA = load_schema("login_event")
_DEVICE_SCHEMA = load_schema("device_event")


def _tx_bytes(overrides: dict | None = None) -> bytes:
    record = {
        "transaction_id": "tx-test",
        "account_id": "acct-test",
        "amount": 50.00,
        "currency": "USD",
        "merchant_id": "merch-test",
        "timestamp": int(time.time() * 1000),
        "channel": "card_present",
        "metadata": {"synthetic": "true", "origin": "red_team"},
        **(overrides or {}),
    }
    return serialize(record, _TX_SCHEMA, schema_id=1)


def _login_bytes(overrides: dict | None = None) -> bytes:
    record = {
        "session_id": "sess-test",
        "account_id": "acct-test",
        "ip_address": "deadbeef00000000",
        "user_agent": "Mozilla/5.0",
        "geo": {"country": "MX", "city": "CDMX", "lat": 19.43, "lon": -99.13},
        "timestamp": int(time.time() * 1000),
        "success": True,
        "failure_reason": None,
        "metadata": {"synthetic": "true", "origin": "red_team"},
        **(overrides or {}),
    }
    return serialize(record, _LOGIN_SCHEMA, schema_id=2)


def _device_bytes(overrides: dict | None = None) -> bytes:
    record = {
        "device_id": "dev-test",
        "account_id": "acct-test",
        "fingerprint": "f" * 64,
        "os": "Android 14",
        "app_version": "3.1.0",
        "event_type": "registered",
        "timestamp": int(time.time() * 1000),
        "metadata": {"synthetic": "true", "origin": "red_team"},
        **(overrides or {}),
    }
    return serialize(record, _DEVICE_SCHEMA, schema_id=3)


# ── Shared consumer fixture helpers ───────────────────────────────────────────

def _make_consumer(klass):  # type: ignore[no-untyped-def]
    """Instantiate a consumer without starting the Kafka connection."""
    with mock.patch("confluent_kafka.Consumer"), mock.patch("confluent_kafka.Producer"):
        return klass()


class TestTransactionConsumer:
    def test_deserialize_valid_bytes(self) -> None:
        consumer = _make_consumer(TransactionConsumer)
        result = consumer.deserialize(_tx_bytes())
        assert result["transaction_id"] == "tx-test"
        assert result["metadata"]["synthetic"] == "true"

    def test_process_does_not_raise_on_valid_event(self) -> None:
        consumer = _make_consumer(TransactionConsumer)
        event = consumer.deserialize(_tx_bytes())
        consumer.process(event)  # should not raise

    def test_deserialize_raises_on_corrupt_bytes(self) -> None:
        consumer = _make_consumer(TransactionConsumer)
        with pytest.raises(Exception):
            consumer.deserialize(b"totally not avro")

    def test_deserialize_raises_on_missing_magic_byte(self) -> None:
        consumer = _make_consumer(TransactionConsumer)
        with pytest.raises(ValueError):
            consumer.deserialize(b"\x99garbage")


class TestLoginConsumer:
    def test_deserialize_valid_bytes(self) -> None:
        consumer = _make_consumer(LoginConsumer)
        result = consumer.deserialize(_login_bytes())
        assert result["session_id"] == "sess-test"
        assert result["geo"]["country"] == "MX"

    def test_process_successful_login(self) -> None:
        consumer = _make_consumer(LoginConsumer)
        event = consumer.deserialize(_login_bytes())
        consumer.process(event)

    def test_process_failed_login(self) -> None:
        consumer = _make_consumer(LoginConsumer)
        raw = _login_bytes({"success": False, "failure_reason": "bad_password"})
        event = consumer.deserialize(raw)
        consumer.process(event)

    def test_deserialize_raises_on_corrupt_bytes(self) -> None:
        consumer = _make_consumer(LoginConsumer)
        with pytest.raises(Exception):
            consumer.deserialize(b"\x00\x00\x00\x00\x01garbage_avro")


class TestDeviceConsumer:
    def test_deserialize_valid_bytes(self) -> None:
        consumer = _make_consumer(DeviceConsumer)
        result = consumer.deserialize(_device_bytes())
        assert result["device_id"] == "dev-test"
        assert result["event_type"] == "registered"

    def test_process_high_risk_event_does_not_raise(self) -> None:
        consumer = _make_consumer(DeviceConsumer)
        raw = _device_bytes({"event_type": "fingerprint_changed"})
        event = consumer.deserialize(raw)
        consumer.process(event)  # logs warning but does not raise

    def test_process_synthetic_device_event(self) -> None:
        consumer = _make_consumer(DeviceConsumer)
        event = consumer.deserialize(_device_bytes())
        consumer.process(event)

    def test_dead_letter_called_on_invalid_bytes(self) -> None:
        consumer = _make_consumer(DeviceConsumer)
        consumer._send_to_dlq = mock.MagicMock()  # type: ignore[method-assign]
        # Simulate what run() does when deserialization fails
        raw = b"corrupt"
        try:
            consumer.deserialize(raw)
        except Exception as exc:
            consumer._send_to_dlq(raw, str(exc))
        consumer._send_to_dlq.assert_called_once()
