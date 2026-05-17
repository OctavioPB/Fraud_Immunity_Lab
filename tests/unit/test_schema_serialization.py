"""
Unit tests for Avro schema loading, serialization, and deserialization.
Validates the Confluent wire format round-trip without a live Schema Registry.
"""

import time

import pytest

from ingestion.schemas.registry import deserialize, load_schema, serialize


@pytest.fixture(scope="module")
def tx_schema():  # type: ignore[no-untyped-def]
    return load_schema("transaction_event")


@pytest.fixture(scope="module")
def login_schema():  # type: ignore[no-untyped-def]
    return load_schema("login_event")


@pytest.fixture(scope="module")
def device_schema():  # type: ignore[no-untyped-def]
    return load_schema("device_event")


class TestTransactionSchema:
    def _record(self) -> dict:
        return {
            "transaction_id": "tx-abc",
            "account_id": "acct-xyz",
            "amount": 150.00,
            "currency": "USD",
            "merchant_id": "merch-123",
            "timestamp": int(time.time() * 1000),
            "channel": "card_not_present",
            "metadata": {"synthetic": "true", "origin": "red_team"},
        }

    def test_schema_loads(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        assert tx_schema is not None

    def test_roundtrip(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        record = self._record()
        schema_id = 1
        raw = serialize(record, tx_schema, schema_id)
        recovered = deserialize(raw, tx_schema)
        assert recovered["transaction_id"] == record["transaction_id"]
        assert recovered["amount"] == pytest.approx(record["amount"])
        assert recovered["metadata"]["synthetic"] == "true"

    def test_wire_format_magic_byte(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        raw = serialize(self._record(), tx_schema, 42)
        assert raw[0:1] == b"\x00"

    def test_wire_format_schema_id(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        import struct
        raw = serialize(self._record(), tx_schema, 99)
        schema_id_in_bytes = struct.unpack(">I", raw[1:5])[0]
        assert schema_id_in_bytes == 99

    def test_deserialize_rejects_invalid_magic_byte(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match="magic byte"):
            deserialize(b"\x01garbage", tx_schema)

    def test_synthetic_metadata_preserved(self, tx_schema) -> None:  # type: ignore[no-untyped-def]
        record = self._record()
        raw = serialize(record, tx_schema, 1)
        out = deserialize(raw, tx_schema)
        assert out["metadata"].get("synthetic") == "true"
        assert out["metadata"].get("origin") == "red_team"


class TestLoginSchema:
    def _record(self) -> dict:
        return {
            "session_id": "sess-001",
            "account_id": "acct-001",
            "ip_address": "deadbeef00000000",
            "user_agent": "Mozilla/5.0",
            "geo": {"country": "MX", "city": "CDMX", "lat": 19.43, "lon": -99.13},
            "timestamp": int(time.time() * 1000),
            "success": True,
            "failure_reason": None,
            "metadata": {"synthetic": "true", "origin": "red_team"},
        }

    def test_roundtrip(self, login_schema) -> None:  # type: ignore[no-untyped-def]
        record = self._record()
        raw = serialize(record, login_schema, 2)
        recovered = deserialize(raw, login_schema)
        assert recovered["session_id"] == record["session_id"]
        assert recovered["geo"]["country"] == "MX"
        assert recovered["success"] is True

    def test_failed_login_roundtrip(self, login_schema) -> None:  # type: ignore[no-untyped-def]
        record = self._record()
        record["success"] = False
        record["failure_reason"] = "bad_password"
        raw = serialize(record, login_schema, 2)
        recovered = deserialize(raw, login_schema)
        assert recovered["success"] is False
        assert recovered["failure_reason"] == "bad_password"


class TestDeviceSchema:
    def _record(self) -> dict:
        return {
            "device_id": "dev-001",
            "account_id": "acct-001",
            "fingerprint": "a" * 64,
            "os": "iOS 17.2",
            "app_version": "4.2.1",
            "event_type": "fingerprint_changed",
            "timestamp": int(time.time() * 1000),
            "metadata": {"synthetic": "true", "origin": "red_team"},
        }

    def test_roundtrip(self, device_schema) -> None:  # type: ignore[no-untyped-def]
        record = self._record()
        raw = serialize(record, device_schema, 3)
        recovered = deserialize(raw, device_schema)
        assert recovered["device_id"] == record["device_id"]
        assert recovered["event_type"] == "fingerprint_changed"
        assert recovered["metadata"]["synthetic"] == "true"
